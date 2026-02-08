"""Session management service."""

from __future__ import annotations

import asyncio
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

from discord_acp_bridge.application.project import Project  # noqa: TC001
from discord_acp_bridge.infrastructure.acp_client import ACPClient, UsageUpdate
from discord_acp_bridge.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from discord_acp_bridge.infrastructure.config import Config

# コールバック型定義
MessageCallback = Callable[[int, str], Awaitable[None]]  # (thread_id, message) -> None
TimeoutCallback = Callable[[int], Awaitable[None]]  # (thread_id) -> None
TypingCallback = Callable[
    [int, bool], Awaitable[None]
]  # (thread_id, is_typing) -> None

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
        on_message: MessageCallback | None = None,
        on_timeout: TimeoutCallback | None = None,
        on_typing: TypingCallback | None = None,
    ) -> None:
        """
        Initialize SessionService.

        Args:
            config: アプリケーション設定
            on_message: ACPからのメッセージ受信時のコールバック
            on_timeout: セッションタイムアウト時のコールバック
            on_typing: タイピングインジケーター制御時のコールバック
        """
        self._config = config
        self._on_message_callback = on_message
        self._on_timeout_callback = on_timeout
        self._on_typing_callback = on_typing
        # セッション管理（user_id -> Session）
        self._sessions: dict[int, Session] = {}
        # セッションID逆引きマップ（session_id -> Session）
        self._session_map: dict[str, Session] = {}
        # スレッドIDからセッションを検索するためのマップ
        self._thread_sessions: dict[int, str] = {}  # thread_id -> session_id
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
                await self._stop_typing(thread_id)
            except asyncio.CancelledError:
                # キャンセルは正常な動作
                pass
            except Exception:
                logger.exception(
                    "Error in delayed typing stop for thread", thread_id=thread_id
                )

        self._typing_stop_tasks[thread_id] = asyncio.create_task(delayed_stop())

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
            # ACP Clientでモデルを変更
            await acp_client.set_session_model(model_id, session.acp_session_id)

            # セッションのモデル情報は CurrentModeUpdate 通知で更新される
            session.last_activity_at = datetime.now()

            logger.info(
                "Model change requested for session (waiting for confirmation)",
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

        logger.warning("Session killed", session_id=session_id)

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

        # CurrentModeUpdate通知を処理（モデル変更通知）
        if isinstance(update, CurrentModeUpdate):
            if update.model_id is not None:
                logger.info(
                    "Model changed for session",
                    session_id=session.id,
                    model_id=update.model_id,
                )
                session.current_model_id = update.model_id
            # available_modelsフィールドが存在する場合は更新
            if (
                hasattr(update, "available_models")
                and update.available_models is not None
            ):
                session.available_models = list(update.available_models)
                logger.debug(
                    "Available models updated for session",
                    session_id=session.id,
                    available_models=session.available_models,
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
        if session.id in self._acp_clients:
            del self._acp_clients[session.id]
