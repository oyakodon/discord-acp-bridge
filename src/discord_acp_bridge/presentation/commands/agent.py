"""Agent session commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from discord_acp_bridge.application.session import (
    ACPConnectionError,
    SessionNotFoundError,
)
from discord_acp_bridge.infrastructure.logging import get_logger
from discord_acp_bridge.presentation.bot import is_allowed_user

if TYPE_CHECKING:
    from discord_acp_bridge.presentation.bot import ACPBot

logger = get_logger(__name__)


class AgentCommands(commands.Cog):
    """エージェントセッション管理コマンド群."""

    def __init__(self, bot: ACPBot) -> None:
        """
        Initialize AgentCommands.

        Args:
            bot: Discord Bot インスタンス
        """
        self.bot = bot

    agent_group = app_commands.Group(
        name="agent", description="エージェントセッション管理コマンド"
    )

    @agent_group.command(name="start", description="エージェントセッションを開始")
    @is_allowed_user()
    async def start_session(self, interaction: discord.Interaction) -> None:
        """
        エージェントセッションを開始する.

        Args:
            interaction: Discord Interaction
        """
        logger.info(
            "User %s (ID: %d) requested to start agent session",
            interaction.user.name,
            interaction.user.id,
        )

        # Deferして応答時間を確保
        await interaction.response.defer(ephemeral=True)

        try:
            # 既存のアクティブセッションをチェック
            existing_session = self.bot.session_service.get_active_session(
                interaction.user.id
            )
            if existing_session is not None:
                await interaction.followup.send(
                    "既にアクティブなセッションが存在します。\n"
                    f"スレッド: <#{existing_session.thread_id}>\n"
                    f"先に `/agent stop` または `/agent kill` でセッションを終了してください。",
                    ephemeral=True,
                )
                logger.warning(
                    "User %d already has an active session: %s",
                    interaction.user.id,
                    existing_session.id,
                )
                return

            # アクティブなプロジェクトを取得
            active_project = self.bot.project_service.get_active_project()
            if active_project is None:
                await interaction.followup.send(
                    "アクティブなプロジェクトが設定されていません。\n"
                    "`/project switch <id>` でプロジェクトを選択してください。",
                    ephemeral=True,
                )
                logger.warning("User %d has no active project", interaction.user.id)
                return

            # スレッドを作成
            if not isinstance(interaction.channel, discord.TextChannel):
                await interaction.followup.send(
                    "このコマンドはテキストチャンネルでのみ使用できます。",
                    ephemeral=True,
                )
                logger.error(
                    "User %d tried to start session in non-text channel",
                    interaction.user.id,
                )
                return

            thread = await interaction.channel.create_thread(
                name=f"Agent - {active_project.path}",
                auto_archive_duration=60,  # 1時間後に自動アーカイブ
            )

            # セッションを作成
            session = await self.bot.session_service.create_session(
                user_id=interaction.user.id,
                project=active_project,
                thread_id=thread.id,
            )

            await interaction.followup.send(
                f"エージェントセッションを開始しました。\n"
                f"プロジェクト: `{active_project.path}`\n"
                f"スレッド: <#{thread.id}>\n\n"
                f"スレッド内でメッセージを送信することで、エージェントと対話できます。",
                ephemeral=True,
            )

            # スレッドに初期メッセージを送信
            await thread.send(
                f"🤖 エージェントセッションを開始しました。\n"
                f"プロジェクト: `{active_project.path}`\n\n"
                f"このスレッド内でメッセージを送信してください。"
            )

            logger.info(
                "User %d started session %s (thread: %d)",
                interaction.user.id,
                session.id,
                thread.id,
            )

        except ACPConnectionError as e:
            logger.exception("Failed to connect to ACP server")
            await interaction.followup.send(
                f"エージェントサーバーへの接続に失敗しました。\n"
                f"サーバーが起動しているか確認してください。\n\n"
                f"詳細: {e}",
                ephemeral=True,
            )

        except Exception:
            logger.exception("Error starting session")
            await interaction.followup.send(
                "エラーが発生しました。ログを確認してください。", ephemeral=True
            )

    @agent_group.command(name="stop", description="エージェントセッションを正常終了")
    @is_allowed_user()
    async def stop_session(self, interaction: discord.Interaction) -> None:
        """
        エージェントセッションを正常終了する.

        Args:
            interaction: Discord Interaction
        """
        logger.info(
            "User %s (ID: %d) requested to stop agent session",
            interaction.user.name,
            interaction.user.id,
        )

        # Deferして応答時間を確保
        await interaction.response.defer(ephemeral=True)

        try:
            # アクティブなセッションを取得
            session = self.bot.session_service.get_active_session(interaction.user.id)
            if session is None:
                await interaction.followup.send(
                    "アクティブなセッションが存在しません。\n"
                    "`/agent start` でセッションを開始してください。",
                    ephemeral=True,
                )
                logger.warning(
                    "User %d has no active session to stop", interaction.user.id
                )
                return

            # セッションを正常終了
            await self.bot.session_service.close_session(session.id)

            await interaction.followup.send(
                f"エージェントセッションを終了しました。\n"
                f"スレッド: <#{session.thread_id}>",
                ephemeral=True,
            )

            # スレッドに終了メッセージを送信し、アーカイブ
            if session.thread_id is not None:
                try:
                    thread = self.bot.get_channel(session.thread_id)
                    if isinstance(thread, discord.Thread):
                        await thread.send("🛑 エージェントセッションが終了しました。")
                except Exception:
                    logger.exception(
                        "Error sending end message to thread %d", session.thread_id
                    )

                # スレッドをアーカイブ（メッセージ送信とは分離）
                await self.bot.archive_session_thread(session.thread_id)

            logger.info("User %d stopped session %s", interaction.user.id, session.id)

        except SessionNotFoundError:
            logger.exception("Session not found")
            await interaction.followup.send(
                "セッションが見つかりません。既に終了している可能性があります。",
                ephemeral=True,
            )

        except Exception:
            logger.exception("Error stopping session")
            await interaction.followup.send(
                "エラーが発生しました。ログを確認してください。", ephemeral=True
            )

    @agent_group.command(name="kill", description="エージェントセッションを強制終了")
    @is_allowed_user()
    async def kill_session(self, interaction: discord.Interaction) -> None:
        """
        エージェントセッションを強制終了する.

        Args:
            interaction: Discord Interaction
        """
        logger.info(
            "User %s (ID: %d) requested to kill agent session",
            interaction.user.name,
            interaction.user.id,
        )

        # Deferして応答時間を確保
        await interaction.response.defer(ephemeral=True)

        try:
            # アクティブなセッションを取得
            session = self.bot.session_service.get_active_session(interaction.user.id)
            if session is None:
                await interaction.followup.send(
                    "アクティブなセッションが存在しません。\n"
                    "`/agent start` でセッションを開始してください。",
                    ephemeral=True,
                )
                logger.warning(
                    "User %d has no active session to kill", interaction.user.id
                )
                return

            # セッションを強制終了
            await self.bot.session_service.kill_session(session.id)

            await interaction.followup.send(
                f"エージェントセッションを強制終了しました。\n"
                f"スレッド: <#{session.thread_id}>",
                ephemeral=True,
            )

            # スレッドに終了メッセージを送信し、アーカイブ
            if session.thread_id is not None:
                try:
                    thread = self.bot.get_channel(session.thread_id)
                    if isinstance(thread, discord.Thread):
                        await thread.send(
                            "⚠️ エージェントセッションが強制終了されました。"
                        )
                except Exception:
                    logger.exception(
                        "Error sending kill message to thread %d", session.thread_id
                    )

                # スレッドをアーカイブ（メッセージ送信とは分離）
                await self.bot.archive_session_thread(session.thread_id)

            logger.warning("User %d killed session %s", interaction.user.id, session.id)

        except SessionNotFoundError:
            logger.exception("Session not found")
            await interaction.followup.send(
                "セッションが見つかりません。既に終了している可能性があります。",
                ephemeral=True,
            )

        except Exception:
            logger.exception("Error killing session")
            await interaction.followup.send(
                "エラーが発生しました。ログを確認してください。", ephemeral=True
            )

    @agent_group.command(name="status", description="現在のセッション状態を表示")
    @is_allowed_user()
    async def session_status(self, interaction: discord.Interaction) -> None:
        """
        現在のセッション状態を表示する.

        Args:
            interaction: Discord Interaction
        """
        logger.info(
            "User %s (ID: %d) requested session status",
            interaction.user.name,
            interaction.user.id,
        )

        try:
            # アクティブなセッションを取得
            session = self.bot.session_service.get_active_session(interaction.user.id)

            if session is None:
                await interaction.response.send_message(
                    "現在、アクティブなセッションはありません。\n"
                    "`/agent start` でセッションを開始してください。",
                    ephemeral=True,
                )
                return

            # ステータスメッセージを構築
            status_lines = [
                "**エージェントセッション情報:**",
                f"状態: `{session.state.value}`",
                f"プロジェクト: `{session.project.path}` (ID: {session.project.id})",
                f"スレッド: <#{session.thread_id}>",
                f"作成日時: {session.created_at.strftime('%Y-%m-%d %H:%M:%S')}",
                f"最終応答: {session.last_activity_at.strftime('%Y-%m-%d %H:%M:%S')}",
            ]

            message = "\n".join(status_lines)
            await interaction.response.send_message(message, ephemeral=True)

            logger.info("Sent session status to user %d", interaction.user.id)

        except Exception:
            logger.exception("Error getting session status")
            await interaction.response.send_message(
                "エラーが発生しました。ログを確認してください。", ephemeral=True
            )


async def setup(bot: ACPBot) -> None:
    """
    Cogをセットアップする.

    Args:
        bot: Discord Bot インスタンス
    """
    await bot.add_cog(AgentCommands(bot))
