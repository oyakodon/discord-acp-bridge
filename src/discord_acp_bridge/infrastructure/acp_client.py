"""ACP Client - Agent Client Protocol wrapper."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from acp import (
    PROTOCOL_VERSION,
    ReadTextFileResponse,
    RequestPermissionResponse,
    WriteTextFileResponse,
    spawn_agent_process,
    text_block,
)
from acp.client.connection import ClientSideConnection
from acp.interfaces import Agent, Client
from acp.schema import (
    AgentMessageChunk,
    AgentPlanUpdate,
    AgentThoughtChunk,
    AllowedOutcome,
    AvailableCommandsUpdate,
    CurrentModeUpdate,
    DeniedOutcome,
    EnvVariable,
    Implementation,
    InitializeResponse,  # noqa: TC001
    PermissionOption,
    SessionInfoUpdate,
    ToolCallProgress,
    ToolCallStart,
    ToolCallUpdate,
    UserMessageChunk,
)
from pydantic import BaseModel

from discord_acp_bridge.infrastructure.logging import get_logger

if TYPE_CHECKING:
    import asyncio.subprocess as aio_subprocess

    from acp.terminal import TerminalHandle

logger = get_logger(__name__)

# Watchdog Timer: 30分間無応答でタイムアウト
WATCHDOG_TIMEOUT = 30 * 60  # 30 minutes in seconds


# 使用量更新の型定義（ACP SDK v0.7.1ではまだ未実装）
class UsageUpdateCost(BaseModel):
    """使用量更新のコスト情報."""

    amount: float
    currency: str = "USD"


class UsageUpdate(BaseModel):
    """使用量更新通知（ACP RFC準拠、将来のSDK対応に備えた型定義）."""

    session_update: str = "usage_update"
    used: int
    size: int
    cost: UsageUpdateCost | None = None
    field_meta: dict[str, Any] | None = None


# コールバック型定義
SessionUpdateCallback = Callable[
    [
        str,
        UserMessageChunk
        | AgentMessageChunk
        | AgentThoughtChunk
        | ToolCallStart
        | ToolCallProgress
        | AgentPlanUpdate
        | AvailableCommandsUpdate
        | CurrentModeUpdate
        | SessionInfoUpdate
        | UsageUpdate,
    ],
    None,
]
TimeoutCallback = Callable[[str], None]


class ACPClient:
    """ACP Client - ACP Server との通信を管理するクラス."""

    def __init__(
        self,
        command: list[str],
        on_session_update: SessionUpdateCallback | None = None,
        on_timeout: TimeoutCallback | None = None,
    ) -> None:
        """
        ACP Client を初期化する.

        Args:
            command: ACP Server を起動するコマンド（例: ["claude-code-acp"]）
            on_session_update: session/update 通知を受け取るコールバック
            on_timeout: Watchdog タイムアウト時に呼ばれるコールバック

        Raises:
            ValueError: commandが空の場合
        """
        if not command:
            msg = "command must not be empty"
            raise ValueError(msg)

        self.command = command
        self.on_session_update = on_session_update
        self.on_timeout = on_timeout

        self._context: Any = None
        self._connection: ClientSideConnection | None = None
        self._process: aio_subprocess.Process | None = None
        self._acp_session_id: str | None = None
        self._watchdog_task: asyncio.Task[None] | None = None
        self._last_update_time: float | None = None
        self._init_response: InitializeResponse | None = None

        # Clientプロトコルの実装
        self._client_impl = self._create_client_impl()

    def _create_client_impl(self) -> Client:
        """Clientプロトコルの実装を作成する."""

        class ClientImpl:
            """ACP Client プロトコルの実装."""

            def __init__(self, parent: ACPClient) -> None:
                self.parent = parent

            async def request_permission(
                self,
                options: list[PermissionOption],
                session_id: str,
                tool_call: ToolCallUpdate,
                **kwargs: Any,
            ) -> RequestPermissionResponse:
                """パーミッション要求（未実装）."""
                logger.warning("request_permission is not implemented")
                # デフォルトで最初のオプションを許可
                if options:
                    outcome: AllowedOutcome | DeniedOutcome = AllowedOutcome(
                        outcome="selected", option_id=options[0].id
                    )
                else:
                    # オプションがない場合は拒否
                    outcome = DeniedOutcome(outcome="cancelled")
                return RequestPermissionResponse(outcome=outcome)

            async def session_update(
                self,
                session_id: str,
                update: UserMessageChunk
                | AgentMessageChunk
                | AgentThoughtChunk
                | ToolCallStart
                | ToolCallProgress
                | AgentPlanUpdate
                | AvailableCommandsUpdate
                | CurrentModeUpdate
                | SessionInfoUpdate
                | UsageUpdate
                | dict[str, Any],  # 未知の通知タイプに対応
                **kwargs: Any,
            ) -> None:
                """session/update 通知を受け取る."""
                # Watchdog Timer をリセット
                self.parent._reset_watchdog()

                # TODO: ACP SDK v0.8+ でUsageUpdateが正式サポートされたら、
                # dict[str, Any]を削除して型安全性を向上させる
                # 辞書形式の場合、UsageUpdateに変換を試みる
                parsed_update: (
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
                if isinstance(update, dict):
                    session_update_type = update.get("session_update")
                    if session_update_type == "usage_update":
                        try:
                            parsed_update = UsageUpdate.model_validate(update)
                            logger.debug("Parsed usage_update from dict")
                        except Exception as e:
                            logger.warning(
                                "Failed to parse usage_update (type: %s): %s. Error: %s",
                                session_update_type,
                                update,
                                e,
                            )
                            return
                    else:
                        # 未知の通知タイプは無視（将来の拡張に備えてINFOレベル）
                        logger.info(
                            "Unknown session_update type '%s', ignoring: %s",
                            session_update_type,
                            update,
                        )
                        return
                else:
                    parsed_update = update

                # コールバックを呼び出し
                if self.parent.on_session_update:
                    try:
                        self.parent.on_session_update(session_id, parsed_update)
                    except Exception:
                        logger.exception("Error in session_update callback")

            async def write_text_file(
                self, content: str, path: str, session_id: str, **kwargs: Any
            ) -> WriteTextFileResponse | None:
                """ファイル書き込み要求（未実装）."""
                logger.warning("write_text_file is not implemented")
                return None

            async def read_text_file(
                self,
                path: str,
                session_id: str,
                limit: int | None = None,
                line: int | None = None,
                **kwargs: Any,
            ) -> ReadTextFileResponse:
                """ファイル読み込み要求（未実装）."""
                logger.warning("read_text_file is not implemented")
                return ReadTextFileResponse(content="")

            async def create_terminal(
                self,
                command: str,
                session_id: str,
                args: list[str] | None = None,
                cwd: str | None = None,
                env: list[EnvVariable] | None = None,
                output_byte_limit: int | None = None,
                **kwargs: Any,
            ) -> TerminalHandle:
                """ターミナル作成要求（未実装）."""
                msg = "create_terminal is not implemented"
                raise NotImplementedError(msg)

            async def terminal_output(
                self, session_id: str, terminal_id: str, **kwargs: Any
            ) -> Any:
                """ターミナル出力要求（未実装）."""
                msg = "terminal_output is not implemented"
                raise NotImplementedError(msg)

            async def release_terminal(
                self, session_id: str, terminal_id: str, **kwargs: Any
            ) -> None:
                """ターミナル解放要求（未実装）."""
                logger.warning("release_terminal is not implemented")

            async def wait_for_terminal_exit(
                self, session_id: str, terminal_id: str, **kwargs: Any
            ) -> Any:
                """ターミナル終了待機要求（未実装）."""
                msg = "wait_for_terminal_exit is not implemented"
                raise NotImplementedError(msg)

            async def kill_terminal(
                self, session_id: str, terminal_id: str, **kwargs: Any
            ) -> None:
                """ターミナル強制終了要求（未実装）."""
                logger.warning("kill_terminal is not implemented")

            async def ext_method(
                self, method: str, params: dict[str, Any]
            ) -> dict[str, Any]:
                """拡張メソッド要求（未実装）."""
                logger.warning("ext_method '%s' is not implemented", method)
                return {}

            async def ext_notification(
                self, method: str, params: dict[str, Any]
            ) -> None:
                """拡張通知（未実装）."""
                logger.warning("ext_notification '%s' is not implemented", method)

            def on_connect(self, conn: Agent) -> None:
                """接続確立時のコールバック."""
                logger.info("Connected to ACP agent")

        return ClientImpl(self)

    async def initialize(self, working_directory: str) -> str:
        """
        ACP Server との接続を初期化し、セッションを作成する.

        Args:
            working_directory: 作業ディレクトリのパス

        Returns:
            セッション ID
        """
        logger.info(
            "Initializing ACP Client with command: %s, cwd: %s",
            self.command,
            working_directory,
        )

        # エージェントプロセスを起動
        command, *args = self.command
        self._context = spawn_agent_process(
            self._client_impl, command, *args, cwd=working_directory
        )
        self._connection, self._process = await self._context.__aenter__()

        # Initialize リクエストを送信
        init_response = await self._connection.initialize(
            protocol_version=PROTOCOL_VERSION,
            client_info=Implementation(name="discord-acp-bridge", version="0.1.0"),
        )
        self._init_response = init_response
        logger.info("ACP Server initialized: %s", init_response)

        # 新規セッションを作成
        session_response = await self._connection.new_session(
            cwd=working_directory, mcp_servers=[]
        )
        session_id = session_response.session_id

        self._acp_session_id = session_id
        logger.info("Session created: %s", session_id)

        # Watchdog Timer を開始
        self._start_watchdog()

        return session_id

    async def send_prompt(self, session_id: str, content: str) -> None:
        """
        ユーザー入力を送信する.

        Args:
            session_id: セッション ID
            content: ユーザーのメッセージ内容

        Raises:
            RuntimeError: 初期化されていない場合
        """
        if self._connection is None:
            msg = "ACP Client is not initialized. Call initialize() first."
            raise RuntimeError(msg)

        logger.info("Sending prompt to session %s: %s", session_id, content[:50])

        # session/prompt リクエストを送信
        await self._connection.prompt(
            prompt=[text_block(content)], session_id=session_id
        )

    async def set_session_model(self, model_id: str, session_id: str) -> None:
        """
        セッションのモデルを変更する.

        Args:
            model_id: モデル ID（例: "claude-sonnet-4-5"）
            session_id: セッション ID

        Raises:
            RuntimeError: 初期化されていない場合
        """
        if self._connection is None:
            msg = "ACP Client is not initialized. Call initialize() first."
            raise RuntimeError(msg)

        logger.info("Changing model for session %s to: %s", session_id, model_id)

        # set_session_model リクエストを送信
        await self._connection.set_session_model(
            model_id=model_id, session_id=session_id
        )

        logger.info("Model changed successfully for session %s", session_id)

    def get_available_models(self) -> list[str]:
        """
        利用可能なモデル一覧を取得する.

        Returns:
            利用可能なモデルIDのリスト

        Raises:
            RuntimeError: 初期化されていない場合
        """
        if self._init_response is None:
            msg = "ACP Client is not initialized. Call initialize() first."
            raise RuntimeError(msg)

        if self._init_response.session_model_state is None:
            logger.warning("SessionModelState is not available")
            return []

        models: list[str] = self._init_response.session_model_state.available_models
        return models

    def get_current_model(self) -> str | None:
        """
        現在のモデルIDを取得する.

        Returns:
            現在のモデルID。取得できない場合はNone

        Raises:
            RuntimeError: 初期化されていない場合
        """
        if self._init_response is None:
            msg = "ACP Client is not initialized. Call initialize() first."
            raise RuntimeError(msg)

        if self._init_response.session_model_state is None:
            logger.warning("SessionModelState is not available")
            return None

        model_id: str | None = self._init_response.session_model_state.current_model_id
        return model_id

    async def cancel_session(self, session_id: str) -> None:
        """
        セッションを終了する.

        Args:
            session_id: セッション ID

        Raises:
            RuntimeError: 初期化されていない場合
        """
        if self._connection is None:
            msg = "ACP Client is not initialized. Call initialize() first."
            raise RuntimeError(msg)

        logger.info("Cancelling session: %s", session_id)

        # Watchdog Timer を停止
        self._stop_watchdog()

        # session/cancel 通知を送信
        await self._connection.cancel(session_id=session_id)

        self._acp_session_id = None
        logger.info("Session cancelled: %s", session_id)

    async def close(self) -> None:
        """ACP Client をクローズする."""
        logger.info("Closing ACP Client")

        # Watchdog Timer を停止
        self._stop_watchdog()

        # コンテキストマネージャを適切にクローズ
        if self._context is not None:
            try:
                await self._context.__aexit__(None, None, None)
            except Exception:
                logger.exception("Error during context cleanup")
            finally:
                self._context = None

        # 念のため、残りのリソースをクリーンアップ
        await self._cleanup_connection()
        await self._cleanup_process(force=False)

        self._acp_session_id = None
        logger.info("ACP Client closed")

    def _start_watchdog(self) -> None:
        """Watchdog Timer を開始する."""
        if self._watchdog_task is not None and not self._watchdog_task.done():
            logger.warning("Watchdog timer is already running")
            return

        self._last_update_time = asyncio.get_event_loop().time()
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        logger.info("Watchdog timer started")

    def _stop_watchdog(self) -> None:
        """Watchdog Timer を停止する."""
        if self._watchdog_task is not None and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            self._watchdog_task = None
            logger.info("Watchdog timer stopped")

    def _reset_watchdog(self) -> None:
        """Watchdog Timer をリセットする."""
        self._last_update_time = asyncio.get_event_loop().time()

    async def _watchdog_loop(self) -> None:
        """Watchdog Timer のメインループ."""
        try:
            while True:
                await asyncio.sleep(10)  # 10秒ごとにチェック

                if self._last_update_time is None:
                    continue  # まだ初期化されていない

                elapsed = asyncio.get_event_loop().time() - self._last_update_time
                if elapsed > WATCHDOG_TIMEOUT:
                    logger.error(
                        "Watchdog timeout: No response for %.1f seconds",
                        elapsed,
                    )
                    if self.on_timeout and self._acp_session_id:
                        try:
                            self.on_timeout(self._acp_session_id)
                        except Exception:
                            logger.exception("Error in timeout callback")

                    # プロセスを強制終了
                    await self._force_kill()
                    break

        except asyncio.CancelledError:
            logger.info("Watchdog timer cancelled")
            raise

    async def _cleanup_connection(self) -> None:
        """Connection をクローズする（冪等）."""
        if self._connection is not None:
            try:
                await self._connection.close()
            except Exception:
                logger.exception("Error closing connection")
            finally:
                self._connection = None

    async def _cleanup_process(self, force: bool = False) -> None:
        """プロセスをクリーンアップする（冪等）."""
        if self._process is None:
            return

        try:
            if self._process.returncode is None:
                if force:
                    self._process.kill()
                else:
                    self._process.terminate()

                try:
                    timeout = 0.5 if force else 5.0
                    await asyncio.wait_for(self._process.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    if not force:
                        logger.warning("Process did not terminate, killing it")
                        self._process.kill()
                        try:
                            await self._process.wait()
                        except Exception:
                            logger.exception("Error waiting for killed process")
        except Exception:
            logger.exception("Error during process cleanup")
        finally:
            self._process = None

    async def _force_kill(self) -> None:
        """ACP Server プロセスを強制終了する."""
        logger.warning("Force killing ACP Server process")
        await self._cleanup_connection()
        await self._cleanup_process(force=True)
        self._acp_session_id = None
