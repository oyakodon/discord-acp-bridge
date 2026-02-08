"""Discord Bot client implementation."""

from __future__ import annotations

import discord
from discord import Intents, app_commands
from discord.ext import commands

from discord_acp_bridge.application.project import ProjectService  # noqa: TC001
from discord_acp_bridge.application.session import SessionService  # noqa: TC001
from discord_acp_bridge.infrastructure.config import Config  # noqa: TC001
from discord_acp_bridge.infrastructure.logging import get_logger

logger = get_logger(__name__)


class ACPBot(commands.Bot):
    """ACP Bridge Discord Bot."""

    def __init__(
        self,
        config: Config,
        project_service: ProjectService,
        session_service: SessionService | None,
    ) -> None:
        """
        Initialize ACPBot.

        Args:
            config: アプリケーション設定
            project_service: プロジェクト管理サービス
            session_service: セッション管理サービス（後から設定可能）
        """
        # Intentsの設定（必要最小限）
        intents = Intents.default()
        intents.message_content = True  # メッセージ内容を読み取るために必要
        intents.guilds = True
        intents.messages = True

        super().__init__(
            command_prefix="!",  # Slash Commandsを使うため、プレフィックスは使用しない
            intents=intents,
        )

        self.config = config
        self.project_service = project_service
        # session_serviceは後から設定される場合があるが、実行時には必ず設定される
        self.session_service: SessionService = session_service  # type: ignore[assignment]

    async def send_message_to_thread(self, thread_id: int, content: str) -> None:
        """
        スレッドにメッセージを送信する.

        Args:
            thread_id: スレッドID
            content: メッセージ内容
        """
        try:
            thread = self.get_channel(thread_id)
            if not isinstance(thread, discord.Thread):
                logger.error("Channel is not a thread", channel_id=thread_id)
                return

            # メッセージを2000文字以内に分割して送信
            # TODO: コードブロック内での分割を考慮した実装に改善
            if len(content) <= 2000:
                await thread.send(content)
            else:
                # 2000文字ごとに分割
                chunks = [content[i : i + 2000] for i in range(0, len(content), 2000)]
                for chunk in chunks:
                    await thread.send(chunk)

            logger.debug("Sent message to thread", thread_id=thread_id)

        except Exception:
            logger.exception("Error sending message to thread", thread_id=thread_id)

    async def archive_session_thread(self, thread_id: int) -> None:
        """
        セッションのスレッドをアーカイブする.

        Args:
            thread_id: スレッドID
        """
        try:
            thread = self.get_channel(thread_id)
            if not isinstance(thread, discord.Thread):
                logger.error("Channel is not a thread", channel_id=thread_id)
                return

            await thread.edit(archived=True)
            logger.info("Archived thread", thread_id=thread_id)

        except Exception:
            logger.exception("Error archiving thread", thread_id=thread_id)

    async def send_timeout_notification(self, thread_id: int) -> None:
        """
        タイムアウト通知をスレッドに送信し、スレッドをアーカイブする.

        Args:
            thread_id: スレッドID
        """
        try:
            thread = self.get_channel(thread_id)
            if not isinstance(thread, discord.Thread):
                logger.error("Channel is not a thread", channel_id=thread_id)
                return

            await thread.send(
                "⏱️ エージェントが30分間応答しないため、セッションを強制終了しました。"
            )
            logger.info("Sent timeout notification to thread", thread_id=thread_id)

        except Exception:
            logger.exception(
                "Error sending timeout notification to thread", thread_id=thread_id
            )

        # スレッドをアーカイブ（メッセージ送信とは分離）
        await self.archive_session_thread(thread_id)

    async def set_typing_indicator(self, thread_id: int, is_typing: bool) -> None:
        """
        タイピングインジケーターを制御する.

        Discord APIの制限により、タイピングインジケーターは10秒間のみ表示される。
        継続的に表示するには、5-10秒毎に再送する必要がある。

        Args:
            thread_id: スレッドID
            is_typing: タイピング中かどうか（Falseの場合は何もしない）
        """
        if not is_typing:
            # タイピング停止は_stop_typing()で明示的に管理される
            return

        try:
            thread = self.get_channel(thread_id)
            if not isinstance(thread, discord.Thread):
                logger.error("Channel is not a thread", channel_id=thread_id)
                return

            await thread.typing()
            logger.debug("Triggered typing indicator for thread", thread_id=thread_id)

        except Exception:
            logger.exception(
                "Error triggering typing indicator for thread", thread_id=thread_id
            )

    async def setup_hook(self) -> None:
        """
        Bot起動時の初期化処理.

        Cogのロードとコマンドツリーの同期を行う。
        """
        logger.info("Setting up bot...")

        # Cogのロード
        try:
            await self.load_extension(
                "discord_acp_bridge.presentation.commands.project"
            )
            logger.info("Loaded project commands")
        except Exception:
            logger.exception("Failed to load project commands")

        try:
            await self.load_extension("discord_acp_bridge.presentation.commands.agent")
            logger.info("Loaded agent commands")
        except Exception:
            logger.exception("Failed to load agent commands")

        try:
            await self.load_extension("discord_acp_bridge.presentation.events.message")
            logger.info("Loaded message event handler")
        except Exception:
            logger.exception("Failed to load message event handler")

        # コマンドツリーの同期
        # 開発用ギルドIDが指定されている場合は、そのギルドのみに同期
        if self.config.discord_guild_id:
            guild = discord.Object(id=self.config.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info(
                "Synced command tree to guild", guild_id=self.config.discord_guild_id
            )
        else:
            await self.tree.sync()
            logger.info("Synced command tree globally")

    async def on_ready(self) -> None:
        """Bot準備完了時のイベントハンドラー."""
        if self.user is None:
            logger.error("Bot user is None")
            return

        logger.info("Bot is ready", bot_name=self.user.name, bot_id=self.user.id)
        logger.info("Connected to guilds", guild_count=len(self.guilds))


def is_allowed_user():
    """
    許可されたユーザーかどうかをチェックするデコレーター.

    Returns:
        app_commandsのcheck関数
    """

    async def predicate(interaction: discord.Interaction) -> bool:
        """
        ユーザーが許可されているかチェックする.

        Args:
            interaction: Discord Interaction

        Returns:
            許可されている場合True
        """
        if not isinstance(interaction.client, ACPBot):
            logger.error("Client is not ACPBot")
            return False

        allowed_user_id = interaction.client.config.discord_allowed_user_id
        is_allowed = interaction.user.id == allowed_user_id

        if not is_allowed:
            logger.warning(
                "Unauthorized user attempted to use command",
                user_name=interaction.user.name,
                user_id=interaction.user.id,
            )

        return is_allowed

    return app_commands.check(predicate)
