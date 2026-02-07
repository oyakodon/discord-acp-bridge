"""Project management commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from discord_acp_bridge.infrastructure.logging import get_logger
from discord_acp_bridge.presentation.bot import is_allowed_user

if TYPE_CHECKING:
    from discord_acp_bridge.presentation.bot import ACPBot

logger = get_logger(__name__)


class ProjectCommands(commands.Cog):
    """プロジェクト管理コマンド群."""

    def __init__(self, bot: ACPBot) -> None:
        """
        Initialize ProjectCommands.

        Args:
            bot: Discord Bot インスタンス
        """
        self.bot = bot

    @app_commands.command(name="projects", description="登録済みプロジェクト一覧を表示")
    @is_allowed_user()
    async def list_projects(self, interaction: discord.Interaction) -> None:
        """
        登録されているプロジェクトの一覧を表示する.

        Args:
            interaction: Discord Interaction
        """
        logger.info(
            "User %s (ID: %d) requested project list",
            interaction.user.name,
            interaction.user.id,
        )

        try:
            projects = self.bot.project_service.list_projects()

            if not projects:
                await interaction.response.send_message(
                    "Trusted Path配下にプロジェクトが見つかりません。\n"
                    "環境変数 `TRUSTED_PATHS` で指定されたディレクトリ配下に"
                    "プロジェクトディレクトリを作成してください。",
                    ephemeral=True,
                )
                return

            # プロジェクト一覧を整形
            lines = ["**登録済みプロジェクト:**"]
            lines.extend(f"{project.id}. `{project.path}`" for project in projects)

            message = "\n".join(lines)
            await interaction.response.send_message(message, ephemeral=True)

            logger.info("Sent project list to user %d", interaction.user.id)

        except Exception:
            logger.exception("Error listing projects")
            await interaction.response.send_message(
                "エラーが発生しました。ログを確認してください。", ephemeral=True
            )


async def setup(bot: ACPBot) -> None:
    """
    Cogをセットアップする.

    Args:
        bot: Discord Bot インスタンス
    """
    await bot.add_cog(ProjectCommands(bot))
