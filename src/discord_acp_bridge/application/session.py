"""Session management service."""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING

from acp.schema import (
    AgentMessageChunk,
    AgentPlanUpdate,
    AgentThoughtChunk,
    AvailableCommandsUpdate,
    CurrentModeUpdate,
    SessionInfoUpdate,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
    UserMessageChunk,
)
from pydantic import BaseModel, Field

from discord_acp_bridge.application.models import (
    PermissionRequest,  # noqa: TC001
    PermissionResponse,  # noqa: TC001
)
from discord_acp_bridge.application.project import (
    Project,  # noqa: TC001
    ProjectMode,  # noqa: TC001
    ProjectService,  # noqa: TC001
)
from discord_acp_bridge.infrastructure.acp_client import ACPClient, UsageUpdate
from discord_acp_bridge.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from acp import RequestPermissionResponse
    from acp.schema import PermissionOption, ToolCallUpdate

    from discord_acp_bridge.infrastructure.config import Config

# コールバック型定義
MessageCallback = Callable[[int, str], Awaitable[None]]  # (thread_id, message) -> None
TimeoutCallback = Callable[[int], Awaitable[None]]  # (thread_id) -> None
TypingCallback = Callable[
    [int, bool], Awaitable[None]
]  # (thread_id, is_typing) -> None
PermissionRequestCallback = Callable[[PermissionRequest], Awaitable[PermissionResponse]]

logger = get_logger(__name__)


class SessionState(str, Enum):
    """セッション状態."""

    CREATED = "created"
    ACTIVE = "active"
    PROMPTING = "prompting"
    CLOSED = "closed"


# ACP Update型のエイリアス（UsageUpdateは独自定義、将来のSDK対応に備える）
ACPUpdate = (
    UserMessageChunk
    | AgentMessageChunk
    | AgentThoughtChunk
    | ToolCallStart
    | ToolCallProgress
    | AgentPlanUpdate
    | AvailableCommandsUpdate
    | CurrentModeUpdate
    | SessionInfoUpdate
    | UsageUpdate
)

# Read モード時に拒否する Write 系ツール種別のセット
# bash はファイル変更・実行など任意の副作用を伴うため Write 系として扱う
_WRITE_KINDS: frozenset[str] = frozenset({
    "bash",
    "write",
    "write_file",
    "edit",
    "edit_file",
    "create",
    "create_file",
    "delete",
    "delete_file",
    "notebookedit",
    "notebook_edit",
    "todowrite",
    "todo_write",
    "run",
    "execute",
    "computer_use",
})


def _is_write_operation(kind: str) -> bool:
    """ツール種別が Write 系（ファイル変更・実行など）かどうかを判定する.

    Args:
        kind: ツール種別（_resolve_tool_kind で解決済みの小文字スラッグ）

    Returns:
        Write 系の場合 True
    """
    return kind.lower() in _WRITE_KINDS


class Session(BaseModel):
    """セッション情報."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: int
    project: Project
    state: SessionState = SessionState.CREATED
    thread_id: int | None = None
    acp_session_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    last_activity_at: datetime = Field(default_factory=datetime.now)
    # モデル情報
    available_models: list[str] = Field(default_factory=list)
    current_model_id: str | None = None
    # 使用量情報
    context_used: int | None = None
    context_size: int | None = None
    total_cost: float | None = None
    cost_currency: str | None = None

    def is_active(self) -> bool:
        """
        セッションがアクティブかどうかを判定する.

        Returns:
            アクティブな場合True
        """
        return self.state in {SessionState.ACTIVE, SessionState.PROMPTING}


class SessionNotFoundError(Exception):
    """指定されたセッションが見つからない場合の例外."""

    def __init__(self, session_id: str) -> None:
        """
        Initialize SessionNotFoundError.

        Args:
            session_id: 見つからなかったセッションID
        """
        super().__init__(f"Session {session_id} not found")
        self.session_id = session_id


class SessionStateError(Exception):
    """セッション状態が不正な場合の例外."""

    def __init__(
        self, session_id: str, current_state: SessionState, message: str
    ) -> None:
        """
        Initialize SessionStateError.

        Args:
            session_id: セッションID
            current_state: 現在の状態
            message: エラーメッセージ
        """
        full_message = f"Invalid state for session {session_id} (current: {current_state}): {message}"
        super().__init__(full_message)
        self.session_id = session_id
        self.current_state = current_state


class ACPConnectionError(Exception):
    """ACP Server接続に失敗した場合の例外."""

    def __init__(self, message: str) -> None:
        """
        Initialize ACPConnectionError.

        Args:
            message: エラーメッセージ
        """
        super().__init__(f"ACP connection failed: {message}")


class ACPTimeoutError(Exception):
    """ACP Server応答がタイムアウトした場合の例外."""

    def __init__(self, session_id: str) -> None:
        """
        Initialize ACPTimeoutError.

        Args:
            session_id: タイムアウトしたセッションID
        """
        super().__init__(f"ACP session {session_id} timed out")
        self.session_id = session_id


class SessionService:
    """セッション管理サービス."""

    def __init__(
        self,
        config: Config,
        project_service: ProjectService | None = None,
        on_message: MessageCallback | None = None,
        on_timeout: TimeoutCallback | None = None,
        on_typing: TypingCallback | None = None,
        on_permission_request: PermissionRequestCallback | None = None,
    ) -> None:
        """
        Initialize SessionService.

        Args:
            config: アプリケーション設定
            project_service: プロジェクト管理サービス（Auto Approve チェックに使用）
            on_message: ACPからのメッセージ受信時のコールバック
            on_timeout: セッションタイムアウト時のコールバック
            on_typing: タイピングインジケーター制御時のコールバック
            on_permission_request: パーミッション要求時のコールバック
        """
        self._config = config
        self._project_service = project_service
        self._on_message_callback = on_message
        self._on_timeout_callback = on_timeout
        self._on_typing_callback = on_typing
        self._on_permission_request_callback = on_permission_request
        # セッション管理（user_id -> Session）
        self._sessions: dict[int, Session] = {}
        # セッションID逆引きマップ（session_id -> Session）
        self._session_map: dict[str, Session] = {}
        # スレッドIDからセッションを検索するためのマップ
        self._thread_sessions: dict[int, str] = {}  # thread_id -> session_id
        # ACPセッションID逆引きマップ（acp_session_id -> session_id）
        self._acp_session_map: dict[str, str] = {}
        # ACP Clientのマップ（session_id -> ACPClient）
        self._acp_clients: dict[str, ACPClient] = {}
        # メッセージバッファリング用（thread_id -> buffer）
        self._message_buffers: dict[int, list[str]] = {}
        # バッファフラッシュタスク（thread_id -> Task）
        self._flush_tasks: dict[int, asyncio.Task] = {}
        # タイピングインジケーター管理（thread_id -> Task）
        self._typing_tasks: dict[int, asyncio.Task] = {}
        # タイピング停止スケジュールタスク（thread_id -> Task）
        self._typing_stop_tasks: dict[int, asyncio.Task] = {}
        # タイピング状態管理（thread_id -> bool）
        self._typing_active: dict[int, bool] = {}

    async def create_session(
        self, user_id: int, project: Project, thread_id: int | None = None
    ) -> Session:
        """
        新規セッションを作成し、ACP Serverとの接続を確立する.

        Args:
            user_id: DiscordユーザーID
            project: 操作対象プロジェクト
            thread_id: DiscordスレッドID（オプション）

        Returns:
            作成されたセッション

        Raises:
            ACPConnectionError: ACP Server接続に失敗した場合
        """
        logger.info(
            "Creating session for user",
            user_id=user_id,
            project_id=project.id,
            project_path=project.path,
        )

        # セッションオブジェクトを作成
        session = Session(user_id=user_id, project=project, thread_id=thread_id)

        # ACP Clientを作成
        acp_client = ACPClient(
            command=self._config.agent_command,
            on_session_update=self._on_session_update,
            on_timeout=self._on_timeout,
            on_permission_request=self._handle_permission_request,
        )

        try:
            # ACP Server初期化とセッション作成
            acp_session_id = await acp_client.initialize(working_directory=project.path)
            session.acp_session_id = acp_session_id
            session.state = SessionState.ACTIVE
            session.last_activity_at = datetime.now()

            # モデル情報を取得して保存
            session.available_models = acp_client.get_available_models()
            session.current_model_id = acp_client.get_current_model()
            if not session.available_models:
                logger.warning("No available models for session", session_id=session.id)
            logger.info(
                "Session model info",
                available_models=session.available_models,
                current_model=session.current_model_id,
            )

            # セッションを登録
            self._sessions[user_id] = session
            self._session_map[session.id] = session
            self._acp_session_map[acp_session_id] = session.id
            self._acp_clients[session.id] = acp_client
            if thread_id is not None:
                self._thread_sessions[thread_id] = session.id

            logger.info(
                "Session created", session_id=session.id, acp_session_id=acp_session_id
            )
            return session

        except Exception as e:
            logger.exception("Failed to create session")
            # 失敗した場合はクリーンアップ
            await acp_client.close()
            raise ACPConnectionError(str(e)) from e

    async def _start_typing(self, thread_id: int) -> None:
        """
        タイピングインジケーターを開始する.

        5秒毎にタイピング状態を再送するバックグラウンドタスクを起動する。

        Args:
            thread_id: DiscordスレッドID
        """
        if self._on_typing_callback is None:
            return

        # ローカル変数にキャプチャ（型の絞り込みを保持）
        callback = self._on_typing_callback

        # 既存のタスクをキャンセル（再起動のため）
        if thread_id in self._typing_tasks:
            self._typing_tasks[thread_id].cancel()
            logger.debug("Restarting typing indicator for thread", thread_id=thread_id)
        else:
            logger.debug("Starting typing indicator for thread", thread_id=thread_id)

        self._typing_active[thread_id] = True

        async def typing_loop() -> None:
            try:
                while self._typing_active.get(thread_id, False):
                    await callback(thread_id, True)
                    await asyncio.sleep(5)  # 5秒毎に再送
            except asyncio.CancelledError:
                # キャンセルは正常な動作
                pass
            except Exception:
                logger.exception("Error in typing loop for thread", thread_id=thread_id)

        self._typing_tasks[thread_id] = asyncio.create_task(typing_loop())

    async def _stop_typing(self, thread_id: int) -> None:
        """
        タイピングインジケーターを停止する.

        Args:
            thread_id: DiscordスレッドID
        """
        if thread_id not in self._typing_active:
            return

        logger.debug("Stopping typing indicator for thread", thread_id=thread_id)
        self._typing_active[thread_id] = False

        # タスクをキャンセル
        if thread_id in self._typing_tasks:
            self._typing_tasks[thread_id].cancel()
            del self._typing_tasks[thread_id]

        # 停止スケジュールタスクもキャンセル
        if thread_id in self._typing_stop_tasks:
            self._typing_stop_tasks[thread_id].cancel()
            del self._typing_stop_tasks[thread_id]

        # 停止通知を送信
        if self._on_typing_callback is not None:
            try:
                await self._on_typing_callback(thread_id, False)
            except Exception:
                logger.exception(
                    "Error sending typing stop notification for thread",
                    thread_id=thread_id,
                )

        # 状態マップから削除
        del self._typing_active[thread_id]

    def _schedule_typing_stop(self, thread_id: int, delay: float = 2.0) -> None:
        """
        タイピングインジケーター停止をスケジュールする.

        既存の停止タスクがあればキャンセルして、新しいタスクをスケジュールする。
        これにより、update受信中はタイピングが継続し、updateが止まって
        一定時間経過後に自動的に停止する。

        Args:
            thread_id: DiscordスレッドID
            delay: 停止までの遅延時間（秒）
        """
        # タイピングが開始されていない場合はスケジュールしない
        if not self._typing_active.get(thread_id, False):
            return

        # 既存の停止タスクをキャンセル
        if thread_id in self._typing_stop_tasks:
            self._typing_stop_tasks[thread_id].cancel()

        async def delayed_stop() -> None:
            try:
                await asyncio.sleep(delay)
                # 停止タスクがキャンセルされずにここまで来た場合のみ停止
                if self._typing_active.get(thread_id, False):
                    await self._stop_typing(thread_id)
            except asyncio.CancelledError:
                # キャンセルは正常な動作
                pass
            except Exception:
                logger.exception(
                    "Error in delayed typing stop for thread", thread_id=thread_id
                )

        self._typing_stop_tasks[thread_id] = asyncio.create_task(delayed_stop())

    async def start_typing_for_thread(self, thread_id: int) -> None:
        """
        指定されたスレッドでタイピングインジケーターを開始する.

        メッセージ受信時など、外部から明示的にタイピング表示を開始する際に使用する。

        Args:
            thread_id: DiscordスレッドID
        """
        await self._start_typing(thread_id)

    async def stop_typing_for_thread(self, thread_id: int) -> None:
        """
        指定されたスレッドでタイピングインジケーターを停止する.

        エラー時など、外部から明示的にタイピング表示を停止する際に使用する。

        Args:
            thread_id: DiscordスレッドID
        """
        await self._stop_typing(thread_id)

    async def send_prompt(self, session_id: str, content: str) -> None:
        """
        プロンプトを送信する.

        応答はon_session_updateコールバックで非同期に処理される。

        Args:
            session_id: セッションID
            content: ユーザー入力内容

        Raises:
            SessionNotFoundError: セッションが存在しない場合
            SessionStateError: セッションが対話可能状態でない場合
        """
        session = self._get_session_by_id(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)

        if session.state == SessionState.CLOSED:
            raise SessionStateError(
                session_id, session.state, "Cannot send prompt to closed session"
            )

        if session.state == SessionState.CREATED:
            raise SessionStateError(
                session_id,
                session.state,
                "Cannot send prompt to session that is not yet active",
            )

        acp_client = self._acp_clients.get(session_id)
        if acp_client is None:
            msg = f"ACP client not found for session {session_id}"
            logger.error(msg)
            raise SessionNotFoundError(session_id)

        logger.info(
            "Sending prompt to session",
            session_id=session_id,
            content_preview=content[:50],
        )

        # タイピングインジケーターを開始
        if session.thread_id is not None:
            await self._start_typing(session.thread_id)

        # 状態をPromptingに変更
        original_state = session.state
        session.state = SessionState.PROMPTING
        session.last_activity_at = datetime.now()

        try:
            # プロンプトを送信（非同期）
            # 応答はsession_update通知で受け取る
            if session.acp_session_id is None:
                msg = f"ACP session ID is None for session {session_id}"
                logger.error(msg)
                raise SessionStateError(
                    session_id, session.state, "ACP session not initialized"
                )

            await acp_client.send_prompt(session.acp_session_id, content)
            # 送信成功後、状態をActiveに戻す
            session.state = SessionState.ACTIVE

        except Exception:
            # エラー時は元の状態に戻す
            session.state = original_state
            raise

    def get_active_session(self, user_id: int) -> Session | None:
        """
        指定ユーザーのアクティブなセッションを取得する.

        Args:
            user_id: DiscordユーザーID

        Returns:
            アクティブなセッション。なければNone
        """
        session = self._sessions.get(user_id)
        if session is not None and session.is_active():
            logger.debug(
                "Active session found for user", user_id=user_id, session_id=session.id
            )
            return session

        logger.debug("No active session for user", user_id=user_id)
        return None

    def get_session_by_thread(self, thread_id: int) -> Session | None:
        """
        スレッドIDからセッションを取得する.

        Args:
            thread_id: DiscordスレッドID

        Returns:
            該当するセッション。なければNone
        """
        session_id = self._thread_sessions.get(thread_id)
        if session_id is None:
            logger.debug("No session found for thread", thread_id=thread_id)
            return None

        session = self._get_session_by_id(session_id)
        if session is not None and session.is_active():
            logger.debug(
                "Session found for thread", thread_id=thread_id, session_id=session.id
            )
            return session

        logger.debug("Session for thread is not active", thread_id=thread_id)
        return None

    async def set_model(self, session_id: str, model_id: str) -> None:
        """
        セッションのモデルを変更する.

        Args:
            session_id: セッションID
            model_id: 変更先のモデルID

        Raises:
            SessionNotFoundError: セッションが存在しない場合
            SessionStateError: セッションが対話可能状態でない場合
            ValueError: モデルIDが利用可能なモデル一覧に含まれていない場合
        """
        session = self._get_session_by_id(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)

        if session.state == SessionState.CLOSED:
            raise SessionStateError(
                session_id, session.state, "Cannot change model of closed session"
            )

        if session.state == SessionState.CREATED:
            raise SessionStateError(
                session_id,
                session.state,
                "Cannot change model of session that is not yet active",
            )

        # モデルIDが利用可能なモデル一覧に含まれているかチェック
        if model_id not in session.available_models:
            msg = f"Model {model_id} is not available. Available models: {session.available_models}"
            logger.error(msg)
            raise ValueError(msg)

        acp_client = self._acp_clients.get(session_id)
        if acp_client is None:
            msg = f"ACP client not found for session {session_id}"
            logger.error(msg)
            raise SessionNotFoundError(session_id)

        if session.acp_session_id is None:
            msg = f"ACP session ID is None for session {session_id}"
            logger.error(msg)
            raise SessionStateError(
                session_id, session.state, "ACP session not initialized"
            )

        logger.info(
            "Changing model for session", session_id=session_id, model_id=model_id
        )

        try:
            # ACP Clientでモデルを変更（ACPClient内で楽観的なmodel_id追跡も更新される）
            await acp_client.set_session_model(model_id, session.acp_session_id)

            # ACP プロトコルにはモデル変更の通知メカニズムが定義されていないため、
            # ここで楽観的にセッション側のcurrent_model_idも更新する
            session.current_model_id = model_id
            session.last_activity_at = datetime.now()

            logger.info(
                "Model changed for session",
                session_id=session_id,
                model_id=model_id,
            )

        except Exception:
            logger.exception("Error changing model for session", session_id=session_id)
            raise

    async def close_session(self, session_id: str) -> None:
        """
        セッションを正常終了する.

        Args:
            session_id: セッションID

        Raises:
            SessionNotFoundError: セッションが存在しない場合
        """
        session = self._get_session_by_id(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)

        logger.info("Closing session", session_id=session_id)

        # バッファに残っているメッセージを送信
        if session.thread_id is not None:
            # フラッシュタスクをキャンセル
            if session.thread_id in self._flush_tasks:
                self._flush_tasks[session.thread_id].cancel()
            # バッファをフラッシュ
            await self._flush_message_buffer(session.thread_id)
            # タイピングインジケーターを停止
            await self._stop_typing(session.thread_id)

        acp_client = self._acp_clients.get(session_id)
        if acp_client is not None and session.acp_session_id is not None:
            try:
                # ACP Serverにキャンセル通知を送信
                await acp_client.cancel_session(session.acp_session_id)
                # ACP Clientをクローズ
                await acp_client.close()
            except Exception:
                logger.exception("Error closing ACP client")
            finally:
                del self._acp_clients[session_id]

        # セッション状態を更新
        session.state = SessionState.CLOSED
        session.last_activity_at = datetime.now()

        # マップからは削除しない（状態で判断できるようにする）
        # 将来的にクリーンアップ処理を実装する
        if session.thread_id is not None and session.thread_id in self._thread_sessions:
            del self._thread_sessions[session.thread_id]
        if (
            session.acp_session_id is not None
            and session.acp_session_id in self._acp_session_map
        ):
            del self._acp_session_map[session.acp_session_id]

        logger.info("Session closed", session_id=session_id)

    async def kill_session(self, session_id: str) -> None:
        """
        セッションを強制終了する.

        Args:
            session_id: セッションID

        Raises:
            SessionNotFoundError: セッションが存在しない場合
        """
        session = self._get_session_by_id(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)

        logger.warning("Force killing session", session_id=session_id)

        # バッファに残っているメッセージを送信
        if session.thread_id is not None:
            # フラッシュタスクをキャンセル
            if session.thread_id in self._flush_tasks:
                self._flush_tasks[session.thread_id].cancel()
            # バッファをフラッシュ
            await self._flush_message_buffer(session.thread_id)
            # タイピングインジケーターを停止
            await self._stop_typing(session.thread_id)

        acp_client = self._acp_clients.get(session_id)
        if acp_client is not None:
            try:
                # ACP Clientを強制クローズ（プロセスkill）
                await acp_client.close()
            except Exception:
                logger.exception("Error killing ACP client")
            finally:
                del self._acp_clients[session_id]

        # セッション状態を更新
        session.state = SessionState.CLOSED
        session.last_activity_at = datetime.now()

        # マップからは削除しない（状態で判断できるようにする）
        # 将来的にクリーンアップ処理を実装する
        if session.thread_id is not None and session.thread_id in self._thread_sessions:
            del self._thread_sessions[session.thread_id]
        if (
            session.acp_session_id is not None
            and session.acp_session_id in self._acp_session_map
        ):
            del self._acp_session_map[session.acp_session_id]

        logger.warning("Session killed", session_id=session_id)

    async def close_all_sessions(self) -> None:
        """
        すべてのアクティブセッションを正常終了する.

        アプリケーション終了時に呼び出される。
        """
        logger.info("Closing all active sessions...")

        # アクティブセッションのリストを取得（イテレート中の変更を避けるためコピー）
        active_sessions = [
            session for session in self._sessions.values() if session.is_active()
        ]

        if not active_sessions:
            logger.info("No active sessions to close")
            return

        logger.info("Closing %d active session(s)", len(active_sessions))

        # すべてのセッションを並列にクローズ
        close_tasks = [self.close_session(session.id) for session in active_sessions]

        # すべての終了処理を待機（エラーが発生しても続行）
        results = await asyncio.gather(*close_tasks, return_exceptions=True)

        # エラーをログに記録
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "Error closing session",
                    session_id=active_sessions[i].id,
                    error=str(result),
                )

        logger.info("All sessions closed")

    def _get_session_by_id(self, session_id: str) -> Session | None:
        """
        セッションIDからセッションを検索する.

        Args:
            session_id: セッションID

        Returns:
            該当するセッション。なければNone
        """
        return self._session_map.get(session_id)

    async def _safe_callback_wrapper(
        self, callback: MessageCallback | TimeoutCallback, *args: int | str
    ) -> None:
        """
        コールバックを安全に実行するラッパー.

        例外が発生してもログに記録し、タスクをクラッシュさせない。

        Args:
            callback: 実行するコールバック関数
            *args: コールバックに渡す引数
        """
        try:
            await callback(*args)  # type: ignore[arg-type]
        except Exception:
            logger.exception("Error in callback", callback_name=callback.__name__)

    async def _flush_message_buffer(self, thread_id: int) -> None:
        """
        メッセージバッファをフラッシュしてDiscordに送信する.

        Args:
            thread_id: スレッドID
        """
        # バッファが空の場合は何もしない
        if (
            thread_id not in self._message_buffers
            or not self._message_buffers[thread_id]
        ):
            return

        # バッファの内容を取得してクリア
        buffer = self._message_buffers[thread_id]
        self._message_buffers[thread_id] = []

        # タスクをクリーンアップ
        if thread_id in self._flush_tasks:
            del self._flush_tasks[thread_id]

        # バッファの内容を結合して送信
        content = "".join(buffer)
        if content and self._on_message_callback:
            try:
                await self._on_message_callback(thread_id, content)
                logger.debug(
                    "Flushed message buffer to thread",
                    thread_id=thread_id,
                    content_length=len(content),
                )
            except Exception:
                logger.exception(
                    "Error flushing message buffer to thread", thread_id=thread_id
                )

    def _schedule_buffer_flush(self, thread_id: int, delay: float = 1.5) -> None:
        """
        バッファフラッシュをスケジュールする.

        既存のタスクがあればキャンセルして、新しいタスクをスケジュールする。

        Args:
            thread_id: スレッドID
            delay: 遅延時間（秒）
        """
        # 既存のタスクをキャンセル
        if thread_id in self._flush_tasks:
            self._flush_tasks[thread_id].cancel()

        # 新しいフラッシュタスクを作成
        async def delayed_flush() -> None:
            try:
                await asyncio.sleep(delay)
                await self._flush_message_buffer(thread_id)
            except asyncio.CancelledError:
                # キャンセルは正常な動作なので再スロー
                raise
            except Exception:
                # その他の例外はログに記録
                logger.exception(
                    "Unexpected error in delayed flush task for thread",
                    thread_id=thread_id,
                )

        self._flush_tasks[thread_id] = asyncio.create_task(delayed_flush())

    def _on_session_update(self, acp_session_id: str, update: ACPUpdate) -> None:
        """
        ACP Clientからのsession_update通知を受け取る.

        Args:
            acp_session_id: ACPセッションID
            update: 更新内容
        """
        # ACPセッションIDから対応するセッションを検索
        session = None
        for s in self._sessions.values():
            if s.acp_session_id == acp_session_id:
                session = s
                break

        if session is None:
            logger.warning(
                "Session not found for ACP session", acp_session_id=acp_session_id
            )
            return

        # 最終アクティビティ時刻を更新
        session.last_activity_at = datetime.now()

        # タイピングインジケーターのタイマーをリセット
        # update受信中はタイピングを継続し、updateが止まって2秒後に自動停止
        if session.thread_id is not None:
            self._schedule_typing_stop(session.thread_id, delay=2.0)

        logger.debug(
            "Session update",
            session_id=session.id,
            acp_session_id=acp_session_id,
            update_type=type(update).__name__,
        )

        # CurrentModeUpdate通知を処理（モード変更通知）
        # Note: CurrentModeUpdateはセッションモードの変更通知であり、モデル変更通知ではない。
        # ACP プロトコルにはモデル変更の通知メカニズムが定義されていないため、
        # モデル変更後はset_session_model呼び出し側で楽観的に更新する。
        if isinstance(update, CurrentModeUpdate):
            logger.debug(
                "Mode changed for session",
                session_id=session.id,
                mode_id=update.current_mode_id,
            )

        # UsageUpdate通知を処理（使用量更新通知）
        if isinstance(update, UsageUpdate):
            session.context_used = update.used
            session.context_size = update.size
            if update.cost is not None:
                session.total_cost = update.cost.amount
                session.cost_currency = update.cost.currency
            logger.debug(
                "Usage updated for session",
                session_id=session.id,
                tokens_used=update.used,
                tokens_size=update.size,
                cost_amount=update.cost.amount if update.cost else None,
                cost_currency=update.cost.currency if update.cost else None,
            )

        # エージェントのメッセージをバッファに追加
        if (
            isinstance(update, AgentMessageChunk)
            and isinstance(update.content, TextContentBlock)
            and update.content.text
        ):
            if self._on_message_callback and session.thread_id:
                # バッファに追加
                if session.thread_id not in self._message_buffers:
                    self._message_buffers[session.thread_id] = []
                self._message_buffers[session.thread_id].append(update.content.text)

                # バッファフラッシュをスケジュール（既存のタスクがあればキャンセルして再スケジュール）
                self._schedule_buffer_flush(session.thread_id)

                logger.debug(
                    "Added message chunk to buffer",
                    thread_id=session.thread_id,
                    buffer_size=len(self._message_buffers[session.thread_id]),
                )

    def _on_timeout(self, acp_session_id: str) -> None:
        """
        ACP Clientからのタイムアウト通知を受け取る.

        Args:
            acp_session_id: ACPセッションID
        """
        # ACPセッションIDから対応するセッションを検索
        session = None
        for s in self._sessions.values():
            if s.acp_session_id == acp_session_id:
                session = s
                break

        if session is None:
            logger.warning(
                "Session not found for ACP session (timeout)",
                acp_session_id=acp_session_id,
            )
            return

        logger.error("Session timed out", session_id=session.id)

        # バッファに残っているメッセージをフラッシュしてからタイムアウト通知を送信
        if session.thread_id is not None:
            thread_id = session.thread_id  # 型の絞り込みを保持するためにキャプチャ

            # フラッシュタスクをキャンセル
            if thread_id in self._flush_tasks:
                self._flush_tasks[thread_id].cancel()

            # バッファをフラッシュしてからタイムアウト通知を送信
            async def flush_and_notify() -> None:
                try:
                    # バッファをフラッシュ
                    await self._flush_message_buffer(thread_id)
                    # タイピングインジケーターを停止
                    await self._stop_typing(thread_id)
                    # フラッシュ後にタイムアウト通知を送信
                    if self._on_timeout_callback:
                        await self._on_timeout_callback(thread_id)
                except Exception:
                    logger.exception(
                        "Error flushing buffer or sending timeout notification for thread",
                        thread_id=thread_id,
                    )

            asyncio.create_task(flush_and_notify())
            logger.debug(
                "Scheduled buffer flush and timeout notification for thread",
                thread_id=thread_id,
            )

        # セッションを強制終了
        # 注: この時点でACPプロセスは既にkillされている
        session.state = SessionState.CLOSED
        session.last_activity_at = datetime.now()

        # マップからは削除しない（状態で判断できるようにする）
        # ただし、スレッドマッピングとACPクライアントは削除
        if session.thread_id is not None and session.thread_id in self._thread_sessions:
            del self._thread_sessions[session.thread_id]
        if (
            session.acp_session_id is not None
            and session.acp_session_id in self._acp_session_map
        ):
            del self._acp_session_map[session.acp_session_id]
        if session.id in self._acp_clients:
            del self._acp_clients[session.id]

    async def _handle_permission_request(
        self,
        acp_session_id: str,
        options: list[PermissionOption],
        tool_call: ToolCallUpdate,
    ) -> RequestPermissionResponse:
        """
        ACP Clientからのパーミッション要求を処理する.

        コールバックが設定されている場合はDiscord UIに委譲し、
        設定されていないか permission_timeout=0 の場合は自動承認する。

        Args:
            acp_session_id: ACPセッションID
            options: 選択可能なパーミッションオプション
            tool_call: ツール呼び出し情報

        Returns:
            RequestPermissionResponse
        """
        from acp import RequestPermissionResponse as _RPR
        from acp.schema import AllowedOutcome, DeniedOutcome

        from discord_acp_bridge.application.models import (
            PermissionOptionInfo,
            ToolCallInfo,
        )

        # セッションを先に検索（read モードチェックを early return より前に行うため）
        session = self._find_session_by_acp_id(acp_session_id)
        raw_input_str = _format_raw_input(tool_call.raw_input)
        kind = _resolve_tool_kind(tool_call.kind, tool_call.title)

        # プロジェクトの権限モードチェック（read モード時は Write 系を自動拒否）
        # permission_timeout=0 やコールバックなしの場合でも read モードを優先させる
        if session is not None and self._project_service is not None:
            mode = self._project_service.get_project_mode(session.project)
            if mode == ProjectMode.READ and _is_write_operation(kind):
                logger.info(
                    "Auto-denied write operation due to read-only project mode",
                    session_id=session.id,
                    kind=kind,
                )
                return _RPR(outcome=DeniedOutcome(outcome="cancelled"))

        # 自動承認: コールバックなし or timeout=0
        if (
            self._on_permission_request_callback is None
            or self._config.permission_timeout == 0
        ):
            return self._auto_approve_permission(options)

        # セッション/スレッドが見つからない場合は自動承認
        if session is None or session.thread_id is None:
            logger.warning(
                "No session/thread for permission request, auto-approving",
                acp_session_id=acp_session_id,
            )
            return self._auto_approve_permission(options)

        # .acp-bridge/ ディレクトリへの操作は Auto Approve をバイパスし、
        # 必ず Discord UI でユーザーに確認を求める
        # セキュリティ上重要なチェックのため、切り詰めなしの全文字列で検査する
        full_raw_input_str = _raw_input_to_full_str(tool_call.raw_input)
        bypass_auto_approve = _targets_acp_bridge_dir(full_raw_input_str)
        if bypass_auto_approve:
            logger.info(
                "Bypassing auto-approve for .acp-bridge/ target",
                session_id=session.id,
                raw_input=full_raw_input_str[:100],
            )

        # プロジェクトの Auto Approve パターンをチェック
        # 既存パターンの多くは表示用に 500 文字へ切り詰めた raw_input を元に構築されているため、
        # ここでのマッチングも同じく切り詰め済み文字列を使用する（`{kind}:*` のようなワイルドカードパターンは
        # raw_input の内容に依存しない）
        if not bypass_auto_approve and self._project_service is not None:
            matched_pattern = self._project_service.is_auto_approved(
                session.project, kind, raw_input_str
            )
            if matched_pattern is not None:
                logger.info(
                    "Auto-approved permission request by project pattern",
                    session_id=session.id,
                    kind=kind,
                    matched_pattern=matched_pattern,
                )
                return self._auto_approve_permission(options)

        # ACP型 → 中間型に変換
        perm_request = PermissionRequest(
            session_id=session.id,
            acp_session_id=acp_session_id,
            thread_id=session.thread_id,
            tool_call=ToolCallInfo(
                tool_call_id=tool_call.tool_call_id,
                title=tool_call.title or "Unknown",
                kind=kind,
                raw_input=raw_input_str,
                content_summary=_format_content_summary(tool_call.content),
            ),
            options=[
                PermissionOptionInfo(
                    option_id=o.option_id,
                    name=o.name,
                    kind=o.kind,
                )
                for o in options
            ],
        )

        # Discord UIにパーミッション要求を送信し、応答を待つ
        try:
            perm_response = await asyncio.wait_for(
                self._on_permission_request_callback(perm_request),
                timeout=self._config.permission_timeout,
            )
        except TimeoutError:
            logger.warning(
                "Permission request timed out, auto-approving",
                session_id=session.id,
                timeout=self._config.permission_timeout,
            )
            return self._auto_approve_permission(options)

        # 応答を変換
        if perm_response.approved:
            option_id = perm_response.option_id
            if option_id is None and options:
                # デフォルトは allow_always を優先、なければ allow_once
                selected = next(
                    (o for o in options if o.kind == "allow_always"),
                    next(
                        (o for o in options if o.kind == "allow_once"),
                        options[0],
                    ),
                )
                option_id = selected.option_id
            if option_id is not None:
                outcome: AllowedOutcome | DeniedOutcome = AllowedOutcome(
                    outcome="selected", option_id=option_id
                )
            else:
                outcome = DeniedOutcome(outcome="cancelled")
        else:
            outcome = DeniedOutcome(outcome="cancelled")

            # 拒否+指示がある場合、非同期でsend_promptを送信
            if perm_response.instructions:
                self._send_rejection_instructions(
                    session.id, perm_response.instructions
                )

        # 「常に承認」によるパターン保存
        # .acp-bridge/ を対象とする操作は保存しても効果がないのでスキップ
        if (
            perm_response.auto_approve_pattern
            and self._project_service is not None
            and not bypass_auto_approve
        ):
            try:
                self._project_service.add_auto_approve_pattern(
                    session.project, perm_response.auto_approve_pattern
                )
                logger.info(
                    "Saved auto-approve pattern from UI",
                    session_id=session.id,
                    pattern=perm_response.auto_approve_pattern,
                )
            except Exception:
                logger.exception(
                    "Failed to save auto-approve pattern (non-blocking)",
                    session_id=session.id,
                    pattern=perm_response.auto_approve_pattern,
                )

        return _RPR(outcome=outcome)

    def _find_session_by_acp_id(self, acp_session_id: str) -> Session | None:
        """ACPセッションIDからセッションを検索する."""
        session_id = self._acp_session_map.get(acp_session_id)
        if session_id is None:
            return None
        return self._session_map.get(session_id)

    def _auto_approve_permission(
        self,
        options: list[PermissionOption],
    ) -> RequestPermissionResponse:
        """パーミッション要求を自動承認する."""
        from acp import RequestPermissionResponse as _RPR
        from acp.schema import AllowedOutcome, DeniedOutcome

        if options:
            selected = next(
                (o for o in options if o.kind == "allow_always"),
                options[0],
            )
            outcome: AllowedOutcome | DeniedOutcome = AllowedOutcome(
                outcome="selected", option_id=selected.option_id
            )
        else:
            outcome = DeniedOutcome(outcome="cancelled")
        return _RPR(outcome=outcome)

    def _send_rejection_instructions(self, session_id: str, instructions: str) -> None:
        """拒否+指示時に非同期でsend_promptを送信する."""

        async def _send() -> None:
            try:
                await self.send_prompt(session_id, instructions)
            except Exception:
                logger.exception(
                    "Error sending rejection instructions",
                    session_id=session_id,
                )

        task = asyncio.create_task(_send())

        def _handle_task_exception(t: asyncio.Task[None]) -> None:
            if not t.cancelled() and t.exception() is not None:
                logger.error(
                    "Rejection instructions task failed unexpectedly",
                    session_id=session_id,
                )

        task.add_done_callback(_handle_task_exception)


# パス区切り文字（/ または \）、空白、引用符の前後に .acp-bridge が現れるパターン
# 末尾スラッシュなし（ディレクトリ自体への操作）も検出する
# 例: "rm -rf .acp-bridge"、'cat ".acp-bridge/auto_approve.json"'
_ACP_BRIDGE_PATH_PATTERN = re.compile(r"(^|[/\\\s\"'])\.acp-bridge([/\\\s\"']|$)")


def _targets_acp_bridge_dir(raw_input: str) -> bool:
    r"""raw_input が .acp-bridge ディレクトリを対象としているか判定する.

    パス区切り文字（/・\）、空白、引用符の前後に .acp-bridge が現れるかをチェックする。
    末尾スラッシュなし（ディレクトリ自体の操作）や bash コマンド内のパスも検出対象とする。

    Args:
        raw_input: ツール呼び出しの入力文字列

    Returns:
        .acp-bridge を対象としている場合 True
    """
    return bool(_ACP_BRIDGE_PATH_PATTERN.search(raw_input))


def _raw_input_to_full_str(raw_input: object) -> str:
    """ToolCallUpdate.raw_input を切り詰めなしで文字列に変換する（セキュリティ検査用）.

    セキュリティ上重要なチェック（.acp-bridge/ バイパス等）に使用する。
    表示・パターンマッチング目的には _format_raw_input を使用すること。
    """
    if raw_input is None:
        return ""
    if isinstance(raw_input, str):
        return raw_input
    import json

    try:
        return json.dumps(raw_input, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(raw_input)


def _format_raw_input(raw_input: object) -> str:
    """ToolCallUpdate.raw_input を文字列に変換する."""
    if raw_input is None:
        return ""
    if isinstance(raw_input, str):
        return raw_input[:500]
    import json

    try:
        return json.dumps(raw_input, ensure_ascii=False)[:500]
    except (TypeError, ValueError):
        return str(raw_input)[:500]


def _resolve_tool_kind(kind: str | None, title: str | None) -> str:
    """ツール呼び出しの kind を解決する.

    ACP SDK が kind を返さない場合、title から kind を推測する。
    title は "Write File" のような形式を想定し、スペースをアンダースコアに変換して
    小文字化した文字列（例: "write_file"）を返す。

    Args:
        kind: ツール種別（None または空文字列の場合あり）
        title: ツールタイトル（フォールバック用）

    Returns:
        解決された kind 文字列（最低でも "unknown"）

    Note:
        title から推測した kind（例: "write_file"）は、将来 ACP SDK が
        kind を直接返すようになった場合の値と一致しない可能性があります。
        Auto Approve パターンは種別粒度のワイルドカード（"{kind}:*"）で
        保存されるため、不一致が発生した場合はパターンの再登録が必要です。
    """
    if kind:
        return kind
    if title:
        # タイトルから推測する場合はコロン以降を捨て、[a-z0-9_]+ に正規化する
        # 例: "Bash: echo hello" → "bash"、"Write File" → "write_file"
        base = title.split(":", 1)[0].strip().lower()
        if not base:
            return "unknown"
        normalized = re.sub(r"\s+", "_", base)
        normalized = re.sub(r"[^a-z0-9_]", "", normalized)
        return normalized or "unknown"
    return "unknown"


def _format_content_summary(content: object) -> str:
    """ToolCallUpdate.content を要約文字列に変換する."""
    if not content or not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        text = getattr(item, "text", None) or getattr(item, "content", None)
        if text and isinstance(text, str):
            parts.append(text[:200])
    return "\n".join(parts)[:500]
