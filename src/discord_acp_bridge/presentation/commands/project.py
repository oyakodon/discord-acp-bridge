"""Project management commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from discord_acp_bridge.application.project import (
    ProjectCreationError,
    ProjectMode,
    ProjectNotFoundError,
)
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
            for project in projects:
                mode = self.bot.project_service.get_project_mode(project)
                mode_label = "🔒 read" if mode == ProjectMode.READ else "✏️ rw"
                lines.append(f"{project.id}. `{project.path}` [{mode_label}]")

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

    @projects_group.command(
        name="mode", description="プロジェクトの権限モードを変更"
    )
    @app_commands.describe(
        project_id="プロジェクトID",
        mode="権限モード (read: 読み取り専用, rw: 読み書き)",
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="read (読み取り専用)", value="read"),
            app_commands.Choice(name="rw (読み書き)", value="rw"),
        ]
    )
    @is_allowed_user()
    async def set_project_mode(
        self,
        interaction: discord.Interaction,
        project_id: int,
        mode: str,
    ) -> None:
        """
        プロジェクトの権限モードを変更する.

        Args:
            interaction: Discord Interaction
            project_id: プロジェクトID
            mode: 設定する権限モード ("read" or "rw")
        """
        logger.info(
            "User requested to change project mode",
            user_name=interaction.user.name,
            user_id=interaction.user.id,
            project_id=project_id,
            mode=mode,
        )

        try:
            project = self.bot.project_service.get_project_by_id(project_id)
            project_mode = ProjectMode(mode)
            self.bot.project_service.set_project_mode(project, project_mode)

            mode_label = "🔒 読み取り専用 (read)" if project_mode == ProjectMode.READ else "✏️ 読み書き (rw)"
            await interaction.response.send_message(
                f"プロジェクト #{project_id} の権限モードを変更しました。\n"
                f"**パス:** `{project.path}`\n"
                f"**モード:** {mode_label}",
                ephemeral=True,
            )

            logger.info(
                "Changed project mode",
                project_id=project_id,
                project_path=project.path,
                mode=mode,
            )

        except ProjectNotFoundError:
            await interaction.response.send_message(
                f"プロジェクト #{project_id} が見つかりません。"
                "`/projects list` でプロジェクト一覧を確認してください。",
                ephemeral=True,
            )

        except OSError as e:
            logger.exception("Error writing project config")
            await interaction.response.send_message(
                f"設定ファイルへの書き込みに失敗しました: {e}",
                ephemeral=True,
            )

        except Exception:
            logger.exception("Unexpected error changing project mode")
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
