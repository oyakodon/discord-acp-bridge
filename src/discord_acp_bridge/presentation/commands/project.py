"""Project management commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from discord_acp_bridge.application.project import ProjectCreationError
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

    projects_group = app_commands.Group(
        name="projects", description="プロジェクト管理コマンド"
    )

    @projects_group.command(name="list", description="登録済みプロジェクト一覧を表示")
    @is_allowed_user()
    async def list_projects(self, interaction: discord.Interaction) -> None:
        """
        登録されているプロジェクトの一覧を表示する.

        Args:
            interaction: Discord Interaction
        """
        logger.info(
            "User requested project list",
            user_name=interaction.user.name,
            user_id=interaction.user.id,
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

    @projects_group.command(
        name="new", description="新しいプロジェクトディレクトリを作成"
    )
    @app_commands.describe(name="プロジェクト名（ディレクトリ名）")
    @is_allowed_user()
    async def new_project(self, interaction: discord.Interaction, name: str) -> None:
        """
        Trusted Pathの最初のパス配下に新しいプロジェクトディレクトリを作成する.

        Args:
            interaction: Discord Interaction
            name: プロジェクト名
        """
        logger.info(
            "User requested to create new project",
            user_name=interaction.user.name,
            user_id=interaction.user.id,
            project_name=name,
        )

        try:
            project = self.bot.project_service.create_project(name)

            await interaction.response.send_message(
                f"プロジェクトを作成しました:\n"
                f"**ID:** {project.id}\n"
                f"**パス:** `{project.path}`",
                ephemeral=True,
            )

            logger.info(
                "Created new project",
                project_id=project.id,
                project_path=project.path,
            )

        except ProjectCreationError as e:
            logger.warning(
                "Project creation failed",
                user_id=interaction.user.id,
                project_name=name,
                error=str(e),
            )
            await interaction.response.send_message(
                f"プロジェクトの作成に失敗しました: {e}",
                ephemeral=True,
            )

        except Exception:
            logger.exception("Unexpected error creating project")
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
