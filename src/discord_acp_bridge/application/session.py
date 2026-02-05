"""Session management service."""

from __future__ import annotations

import logging
import uuid
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
    ToolCallProgress,
    ToolCallStart,
    UserMessageChunk,
)
from pydantic import BaseModel, Field

from discord_acp_bridge.application.project import Project  # noqa: TC001
from discord_acp_bridge.infrastructure.acp_client import ACPClient

if TYPE_CHECKING:
    from discord_acp_bridge.infrastructure.config import Config

logger = logging.getLogger(__name__)


class SessionState(str, Enum):
    """セッション状態."""

    CREATED = "created"
    ACTIVE = "active"
    PROMPTING = "prompting"
    CLOSED = "closed"


# ACP Update型のエイリアス
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

    def __init__(self, config: Config) -> None:
        """
        Initialize SessionService.

        Args:
            config: アプリケーション設定
        """
        self._config = config
        # セッション管理（user_id -> Session）
        self._sessions: dict[int, Session] = {}
        # セッションID逆引きマップ（session_id -> Session）
        self._session_map: dict[str, Session] = {}
        # スレッドIDからセッションを検索するためのマップ
        self._thread_sessions: dict[int, str] = {}  # thread_id -> session_id
        # ACP Clientのマップ（session_id -> ACPClient）
        self._acp_clients: dict[str, ACPClient] = {}

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
            "Creating session for user %d, project #%d: %s",
            user_id,
            project.id,
            project.path,
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

            # セッションを登録
            self._sessions[user_id] = session
            self._session_map[session.id] = session
            self._acp_clients[session.id] = acp_client
            if thread_id is not None:
                self._thread_sessions[thread_id] = session.id

            logger.info(
                "Session created: %s (ACP session: %s)", session.id, acp_session_id
            )
            return session

        except Exception as e:
            logger.exception("Failed to create session")
            # 失敗した場合はクリーンアップ
            await acp_client.close()
            raise ACPConnectionError(str(e)) from e

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

        logger.info("Sending prompt to session %s: %s", session_id, content[:50])

        # 状態をPromptingに変更
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

        finally:
            # 状態をActiveに戻す
            if session.state == SessionState.PROMPTING:
                session.state = SessionState.ACTIVE

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
            logger.debug("Active session found for user %d: %s", user_id, session.id)
            return session

        logger.debug("No active session for user %d", user_id)
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
            logger.debug("No session found for thread %d", thread_id)
            return None

        session = self._get_session_by_id(session_id)
        if session is not None and session.is_active():
            logger.debug("Session found for thread %d: %s", thread_id, session.id)
            return session

        logger.debug("Session for thread %d is not active", thread_id)
        return None

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

        logger.info("Closing session: %s", session_id)

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

        logger.info("Session closed: %s", session_id)

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

        logger.warning("Force killing session: %s", session_id)

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

        logger.warning("Session killed: %s", session_id)

    def _get_session_by_id(self, session_id: str) -> Session | None:
        """
        セッションIDからセッションを検索する.

        Args:
            session_id: セッションID

        Returns:
            該当するセッション。なければNone
        """
        return self._session_map.get(session_id)

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
            logger.warning("Session not found for ACP session %s", acp_session_id)
            return

        # 最終アクティビティ時刻を更新
        session.last_activity_at = datetime.now()

        logger.debug(
            "Session update for %s (ACP: %s): %s",
            session.id,
            acp_session_id,
            type(update).__name__,
        )

        # TODO: 更新内容をDiscordに転送する処理を実装
        # MVP段階では、ログ出力のみ

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
                "Session not found for ACP session %s (timeout)", acp_session_id
            )
            return

        logger.error("Session %s timed out", session.id)

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

        # TODO: Discordに通知を送信する処理を実装
        # MVP段階では、ログ出力のみ
