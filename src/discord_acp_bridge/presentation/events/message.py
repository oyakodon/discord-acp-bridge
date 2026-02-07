"""Message event handler."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from discord_acp_bridge.application.session import SessionStateError
from discord_acp_bridge.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from discord_acp_bridge.presentation.bot import ACPBot

logger = get_logger(__name__)

# Debounce期間（秒）
DEBOUNCE_DELAY = 1.0


@dataclass
class DebounceState:
    """メッセージdebounce用の状態管理."""

    messages: list[str] = field(default_factory=list)
    task: asyncio.Task[None] | None = None


class MessageEventHandler(commands.Cog):
    """メッセージイベントハンドラー."""

    def __init__(self, bot: ACPBot) -> None:
        """
        Initialize MessageEventHandler.

        Args:
            bot: Discord Bot インスタンス
        """
        self.bot = bot
        # Debounce状態管理: (user_id, thread_id) -> DebounceState
        self._debounce_states: dict[tuple[int, int], DebounceState] = {}

    async def _send_debounced_messages(
        self,
        session_id: str,
        thread: discord.Thread,
        debounce_key: tuple[int, int],
    ) -> None:
        """
        Debounce期間後にメッセージをまとめて送信する.

        Args:
            session_id: セッションID
            thread: Discordスレッド
            debounce_key: Debounce状態のキー
        """
        try:
            # Debounce期間待機
            await asyncio.sleep(DEBOUNCE_DELAY)

            # バッファからメッセージを取得
            state = self._debounce_states.get(debounce_key)
            if state is None or not state.messages:
                return

            # メッセージを結合
            combined_message = "\n".join(state.messages)

            logger.info(
                "Sending debounced messages to session %s (count: %d)",
                session_id,
                len(state.messages),
            )

            # バッファをクリア
            state.messages.clear()
            state.task = None

            try:
                # プロンプトをセッションに送信
                await self.bot.session_service.send_prompt(session_id, combined_message)
                logger.info("Sent debounced prompt to session %s", session_id)

            except SessionStateError as e:
                logger.exception("Session state error")
                await thread.send(
                    f"⚠️ セッションの状態が不正です: {e}\n"
                    f"`/agent status` で状態を確認してください。"
                )

            except Exception:
                logger.exception("Error sending debounced prompt to session")
                await thread.send("❌ エラーが発生しました。ログを確認してください。")

        except asyncio.CancelledError:
            # タスクキャンセルは正常動作（新しいメッセージが来た場合）
            logger.debug("Debounce task cancelled for %s", debounce_key)
            raise  # CancelledErrorは再raiseする

        except Exception:
            # 予期しない例外をログに記録
            logger.exception(
                "Unexpected error in debounce task for session %s", session_id
            )
            # ユーザーには通知しない（既にthread.send()で通知済みの可能性がある）

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

        # Debounce処理
        debounce_key = (message.author.id, message.channel.id)

        # 既存の状態を取得または新規作成
        if debounce_key not in self._debounce_states:
            self._debounce_states[debounce_key] = DebounceState()

        state = self._debounce_states[debounce_key]

        # 既存のタスクがあればキャンセル
        if state.task is not None and not state.task.done():
            state.task.cancel()
            logger.debug("Cancelled previous debounce task for %s", debounce_key)

        # メッセージをバッファに追加
        state.messages.append(message.content)

        # 新しいdebounceタスクを作成
        state.task = asyncio.create_task(
            self._send_debounced_messages(session.id, message.channel, debounce_key)
        )

        logger.debug(
            "Added message to debounce buffer (count: %d)", len(state.messages)
        )


async def setup(bot: ACPBot) -> None:
    """
    Cogをセットアップする.

    Args:
        bot: Discord Bot インスタンス
    """
    await bot.add_cog(MessageEventHandler(bot))
