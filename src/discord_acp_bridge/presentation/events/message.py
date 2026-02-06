"""Message event handler."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from discord_acp_bridge.application.session import SessionStateError

if TYPE_CHECKING:
    from discord_acp_bridge.presentation.bot import ACPBot

logger = logging.getLogger(__name__)


class MessageEventHandler(commands.Cog):
    """メッセージイベントハンドラー."""

    def __init__(self, bot: ACPBot) -> None:
        """
        Initialize MessageEventHandler.

        Args:
            bot: Discord Bot インスタンス
        """
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """
        メッセージ受信イベントハンドラー.

        スレッド内のメッセージを監視し、セッションに紐づくスレッドでのメッセージを
        エージェントに転送する。

        Args:
            message: 受信したメッセージ
        """
        # Bot自身のメッセージは無視
        if message.author.bot:
            return

        # 許可されたユーザー以外のメッセージは無視
        if message.author.id != self.bot.config.discord_allowed_user_id:
            logger.debug(
                "Ignoring message from unauthorized user: %s (ID: %d)",
                message.author.name,
                message.author.id,
            )
            return

        # スレッド内のメッセージのみ処理
        if not isinstance(message.channel, discord.Thread):
            return

        # スレッドIDからセッションを検索
        session = self.bot.session_service.get_session_by_thread(message.channel.id)
        if session is None:
            # このスレッドはセッションと紐づいていない
            logger.debug(
                "Message in thread %d is not associated with any session",
                message.channel.id,
            )
            return

        logger.info(
            "Received message in session %s (thread: %d): %s",
            session.id,
            message.channel.id,
            message.content[:50],
        )

        try:
            # タイピングインジケーターを開始
            async with message.channel.typing():
                # プロンプトをセッションに送信
                await self.bot.session_service.send_prompt(session.id, message.content)

            logger.info("Sent prompt to session %s", session.id)

            # TODO: ACPからの応答を受け取り、Discordに送信する処理を実装
            # MVP段階では、プロンプト送信のみ実装
            # 応答は session_service の _on_session_update コールバックで処理される予定

        except SessionStateError as e:
            logger.exception("Session state error")
            await message.channel.send(
                f"⚠️ セッションの状態が不正です: {e}\n"
                f"`/agent status` で状態を確認してください。"
            )

        except Exception:
            logger.exception("Error sending prompt to session")
            await message.channel.send(
                "❌ エラーが発生しました。ログを確認してください。"
            )


async def setup(bot: ACPBot) -> None:
    """
    Cogをセットアップする.

    Args:
        bot: Discord Bot インスタンス
    """
    await bot.add_cog(MessageEventHandler(bot))
