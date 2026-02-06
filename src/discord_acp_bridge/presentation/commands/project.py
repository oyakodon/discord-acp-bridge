"""Project management commands."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from discord_acp_bridge.application.project import ProjectNotFoundError
from discord_acp_bridge.presentation.bot import is_allowed_user

if TYPE_CHECKING:
    from discord_acp_bridge.presentation.bot import ACPBot

logger = logging.getLogger(__name__)


class ProjectCommands(commands.Cog):
    """プロジェクト管理コマンド群."""

    def __init__(self, bot: ACPBot) -> None:
        """
        Initialize ProjectCommands.

        Args:
            bot: Discord Bot インスタンス
        """
        self.bot = bot

    project_group = app_commands.Group(
        name="project", description="プロジェクト管理コマンド"
    )

    @project_group.command(name="list", description="登録済みプロジェクト一覧を表示")
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
                    "登録されているプロジェクトがありません。\n"
                    "`/project add <path>` でプロジェクトを追加してください。",
                    ephemeral=True,
                )
                return

            # プロジェクト一覧を整形
            lines = ["**登録済みプロジェクト:**"]
            for project in projects:
                status = "✅ **Active**" if project.is_active else ""
                lines.append(f"{project.id}. `{project.path}` {status}")

            message = "\n".join(lines)
            await interaction.response.send_message(message, ephemeral=True)

            logger.info("Sent project list to user %d", interaction.user.id)

        except Exception:
            logger.exception("Error listing projects")
            await interaction.response.send_message(
                "エラーが発生しました。ログを確認してください。", ephemeral=True
            )

    @project_group.command(name="switch", description="操作対象プロジェクトを切り替え")
    @app_commands.describe(project_id="切り替え先のプロジェクトID")
    @is_allowed_user()
    async def switch_project(
        self, interaction: discord.Interaction, project_id: int
    ) -> None:
        """
        操作対象プロジェクトを切り替える.

        Args:
            interaction: Discord Interaction
            project_id: 切り替え先のプロジェクトID
        """
        logger.info(
            "User %s (ID: %d) requested to switch to project #%d",
            interaction.user.name,
            interaction.user.id,
            project_id,
        )

        try:
            project = self.bot.project_service.switch_project(project_id)
            await interaction.response.send_message(
                f"プロジェクト #{project.id} に切り替えました:\n`{project.path}`",
                ephemeral=True,
            )

            logger.info(
                "User %d switched to project #%d", interaction.user.id, project_id
            )

        except ProjectNotFoundError:
            logger.warning(
                "User %d tried to switch to non-existent project #%d",
                interaction.user.id,
                project_id,
            )
            await interaction.response.send_message(
                f"プロジェクト #{project_id} が見つかりません。\n"
                f"`/project list` で登録済みプロジェクトを確認してください。",
                ephemeral=True,
            )

        except Exception:
            logger.exception("Error switching project")
            await interaction.response.send_message(
                "エラーが発生しました。ログを確認してください。", ephemeral=True
            )

    @project_group.command(name="add", description="新規プロジェクトを登録")
    @app_commands.describe(path="プロジェクトのディレクトリパス（絶対パス）")
    @is_allowed_user()
    async def add_project(self, interaction: discord.Interaction, path: str) -> None:
        """
        新規プロジェクトを登録する.

        Args:
            interaction: Discord Interaction
            path: プロジェクトのディレクトリパス
        """
        logger.info(
            "User %s (ID: %d) requested to add project: %s",
            interaction.user.name,
            interaction.user.id,
            path,
        )

        try:
            project = self.bot.project_service.add_project(path)
            await interaction.response.send_message(
                f"プロジェクト #{project.id} を登録しました:\n`{project.path}`\n\n"
                f"`/project switch {project.id}` で切り替えることができます。",
                ephemeral=True,
            )

            logger.info(
                "User %d added project #%d: %s", interaction.user.id, project.id, path
            )

        except ValueError as e:
            logger.warning(
                "User %d tried to add invalid path: %s (Error: %s)",
                interaction.user.id,
                path,
                e,
            )
            await interaction.response.send_message(
                f"無効なパスです: {e}\n絶対パスを指定してください。", ephemeral=True
            )

        except Exception:
            logger.exception("Error adding project")
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
