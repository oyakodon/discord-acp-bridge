"""Agent session commands."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from discord_acp_bridge.application.project import ProjectNotFoundError
from discord_acp_bridge.application.session import (
    ACPConnectionError,
    SessionNotFoundError,
)
from discord_acp_bridge.infrastructure.logging import get_logger
from discord_acp_bridge.presentation.bot import is_allowed_user

if TYPE_CHECKING:
    from discord_acp_bridge.presentation.bot import ACPBot

logger = get_logger(__name__)

# オートコンプリートの最大表示数（Discordの制限）
MAX_AUTOCOMPLETE_CHOICES = 25


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
    @app_commands.describe(project_id="プロジェクトID")
    @is_allowed_user()
    async def start_session(
        self, interaction: discord.Interaction, project_id: int
    ) -> None:
        """
        エージェントセッションを開始する.

        Args:
            interaction: Discord Interaction
            project_id: プロジェクトID
        """
        logger.info(
            "User %s (ID: %d) requested to start agent session (project_id: %d)",
            interaction.user.name,
            interaction.user.id,
            project_id,
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

            # プロジェクトを取得
            target_project = self.bot.project_service.get_project_by_id(project_id)
            logger.info(
                "User %d selected project #%d: %s",
                interaction.user.id,
                project_id,
                target_project.path,
            )

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

            # スレッド名を生成（100文字制限に対応）
            project_name = Path(target_project.path).name
            thread_name = f"Agent - {project_name}"
            if len(thread_name) > 100:
                # 100文字を超える場合は切り詰める
                max_project_len = 100 - len("Agent - ") - 3  # "..." の分を引く
                thread_name = f"Agent - {project_name[:max_project_len]}..."

            thread = await interaction.channel.create_thread(
                name=thread_name,
                auto_archive_duration=60,  # 1時間後に自動アーカイブ
            )

            # セッションを作成
            session = await self.bot.session_service.create_session(
                user_id=interaction.user.id,
                project=target_project,
                thread_id=thread.id,
            )

            await interaction.followup.send(
                f"エージェントセッションを開始しました。\n"
                f"プロジェクト: `{target_project.path}` (ID: {target_project.id})\n"
                f"スレッド: <#{thread.id}>\n\n"
                f"スレッド内でメッセージを送信することで、エージェントと対話できます。",
                ephemeral=True,
            )

            # スレッドに初期メッセージを送信（モデル情報を含む）
            initial_message_lines = [
                "🤖 エージェントセッションを開始しました。",
                f"プロジェクト: `{target_project.path}` (ID: {target_project.id})",
            ]
            if session.current_model_id:
                initial_message_lines.append(f"モデル: `{session.current_model_id}`")
            initial_message_lines.append(
                "\nこのスレッド内でメッセージを送信してください。"
            )

            await thread.send("\n".join(initial_message_lines))

            logger.info(
                "User %d started session %s (thread: %d, project: #%d)",
                interaction.user.id,
                session.id,
                thread.id,
                target_project.id,
            )

        except ProjectNotFoundError as e:
            logger.warning("Project #%d not found", e.project_id)
            await interaction.followup.send(
                f"プロジェクト ID {e.project_id} が見つかりません。\n"
                f"`/projects` でプロジェクト一覧を確認してください。",
                ephemeral=True,
            )

        except ValueError as e:
            logger.error("Invalid project path: %s", e)
            await interaction.followup.send(
                "指定されたプロジェクトは許可されたパス外にあります。\n"
                "セキュリティ上の理由によりアクセスできません。",
                ephemeral=True,
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

    @start_session.autocomplete("project_id")
    async def project_id_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[int]]:
        """
        プロジェクトIDのオートコンプリート.

        Args:
            interaction: Discord Interaction
            current: 現在入力中のテキスト

        Returns:
            オートコンプリートの選択肢
        """
        try:
            projects = self.bot.project_service.list_projects()

            # 入力に部分一致するプロジェクトをフィルタリング
            # プロジェクトIDまたはパス名で検索
            filtered_projects = [
                project
                for project in projects
                if current in str(project.id) or current.lower() in project.path.lower()
            ]

            # 最大25個まで返す（Discordの制限）
            return [
                app_commands.Choice(
                    name=f"{project.id}. {Path(project.path).name}",
                    value=project.id,
                )
                for project in filtered_projects[:MAX_AUTOCOMPLETE_CHOICES]
            ]
        except Exception:
            logger.exception("Error in project_id autocomplete")
            return []

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

            # モデル情報を追加
            if session.current_model_id:
                status_lines.append(f"現在のモデル: `{session.current_model_id}`")
            if session.available_models:
                models_str = ", ".join(f"`{m}`" for m in session.available_models)
                status_lines.append(f"利用可能なモデル: {models_str}")

            message = "\n".join(status_lines)
            await interaction.response.send_message(message, ephemeral=True)

            logger.info("Sent session status to user %d", interaction.user.id)

        except Exception:
            logger.exception("Error getting session status")
            await interaction.response.send_message(
                "エラーが発生しました。ログを確認してください。", ephemeral=True
            )

    @agent_group.command(name="model", description="セッションのモデルを切り替える")
    @app_commands.describe(model_id="使用するモデルID")
    @is_allowed_user()
    async def change_model(
        self, interaction: discord.Interaction, model_id: str
    ) -> None:
        """
        セッションのモデルを切り替える.

        Args:
            interaction: Discord Interaction
            model_id: 変更先のモデルID
        """
        logger.info(
            "User %s (ID: %d) requested to change model to: %s",
            interaction.user.name,
            interaction.user.id,
            model_id,
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
                    "User %d has no active session to change model", interaction.user.id
                )
                return

            # モデルを変更
            await self.bot.session_service.set_model(session.id, model_id)

            await interaction.followup.send(
                f"モデルを `{model_id}` に変更しました。", ephemeral=True
            )

            # スレッドに通知メッセージを送信
            if session.thread_id is not None:
                try:
                    thread = self.bot.get_channel(session.thread_id)
                    if isinstance(thread, discord.Thread):
                        await thread.send(f"🔄 モデルを `{model_id}` に変更しました。")
                except Exception:
                    logger.exception(
                        "Error sending model change notification to thread %d",
                        session.thread_id,
                    )

            logger.info(
                "User %d changed model to %s for session %s",
                interaction.user.id,
                model_id,
                session.id,
            )

        except SessionNotFoundError:
            logger.exception("Session not found")
            await interaction.followup.send(
                "セッションが見つかりません。既に終了している可能性があります。",
                ephemeral=True,
            )

        except ValueError as e:
            logger.error("Invalid model ID: %s", e)
            await interaction.followup.send(
                f"指定されたモデルIDは利用できません。\n"
                f"`/agent status` で利用可能なモデル一覧を確認してください。\n\n"
                f"詳細: {e}",
                ephemeral=True,
            )

        except Exception:
            logger.exception("Error changing model")
            await interaction.followup.send(
                "エラーが発生しました。ログを確認してください。", ephemeral=True
            )

    @change_model.autocomplete("model_id")
    async def model_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """
        モデルIDのオートコンプリート.

        Args:
            interaction: Discord Interaction
            current: 現在入力中のテキスト

        Returns:
            オートコンプリートの選択肢
        """
        # アクティブなセッションを取得
        session = self.bot.session_service.get_active_session(interaction.user.id)
        if session is None or not session.available_models:
            return []

        # 入力に部分一致するモデルをフィルタリング
        filtered_models = [
            model
            for model in session.available_models
            if current.lower() in model.lower()
        ]

        # 最大25個まで返す（Discordの制限）
        return [
            app_commands.Choice(name=model, value=model)
            for model in filtered_models[:25]
        ]

    @agent_group.command(name="usage", description="セッションの使用量情報を表示")
    @is_allowed_user()
    async def session_usage(self, interaction: discord.Interaction) -> None:
        """
        セッションの使用量情報を表示する.

        Args:
            interaction: Discord Interaction
        """
        logger.info(
            "User %s (ID: %d) requested session usage",
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

            # 使用量メッセージを構築
            usage_lines = [
                "**エージェントセッション使用量:**",
                f"プロジェクト: `{session.project.path}` (ID: {session.project.id})",
                f"作成日時: {session.created_at.strftime('%Y-%m-%d %H:%M:%S')}",
                f"最終応答: {session.last_activity_at.strftime('%Y-%m-%d %H:%M:%S')}",
                "",
            ]

            # コンテキスト使用量
            if session.context_used is not None and session.context_size is not None:
                # ゼロ除算を防ぐ
                if session.context_size > 0:
                    usage_percent = (session.context_used / session.context_size) * 100
                    usage_lines.extend([
                        "**コンテキスト使用量:**",
                        f"使用トークン数: `{session.context_used:,}` / `{session.context_size:,}`",
                        f"使用率: `{usage_percent:.1f}%`",
                        "",
                    ])
                else:
                    # context_sizeが0の場合
                    usage_lines.extend([
                        "**コンテキスト使用量:**",
                        f"使用トークン数: `{session.context_used:,}`",
                        "（コンテキストサイズ: 0）",
                        "",
                    ])
            else:
                usage_lines.extend([
                    "**コンテキスト使用量:**",
                    "（まだ使用量情報が取得できていません）",
                    "",
                ])

            # コスト情報
            if session.total_cost is not None:
                currency = session.cost_currency or "USD"
                usage_lines.extend([
                    "**累積コスト:**",
                    f"`{session.total_cost:.4f} {currency}`",
                ])
            else:
                usage_lines.extend([
                    "**累積コスト:**",
                    "（まだコスト情報が取得できていません）",
                ])

            message = "\n".join(usage_lines)
            await interaction.response.send_message(message, ephemeral=True)

            logger.info("Sent session usage to user %d", interaction.user.id)

        except Exception:
            logger.exception("Error getting session usage")
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
