"""Tests for message event handler."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from discord_acp_bridge.application.session import Session, SessionState
from discord_acp_bridge.presentation.events.message import (
    DEBOUNCE_DELAY,
    MessageEventHandler,
)


@pytest.fixture
def mock_bot() -> MagicMock:
    """テスト用のBotモックを作成する."""
    bot = MagicMock()
    bot.config.discord_allowed_user_id = 123456789
    bot.session_service = MagicMock()
    return bot


@pytest.fixture
def handler(mock_bot: MagicMock) -> MessageEventHandler:
    """テスト用のMessageEventHandlerを作成する."""
    return MessageEventHandler(mock_bot)


@pytest.fixture
def mock_message() -> MagicMock:
    """テスト用のメッセージモックを作成する."""
    message = MagicMock(spec=discord.Message)
    message.author.bot = False
    message.author.id = 123456789
    message.author.name = "TestUser"
    message.content = "Test message"

    # Threadモックを作成
    thread = MagicMock(spec=discord.Thread)
    thread.id = 987654321
    thread.send = AsyncMock()
    message.channel = thread

    return message


@pytest.fixture
def mock_session() -> Session:
    """テスト用のSessionモックを作成する."""
    from pathlib import Path

    from discord_acp_bridge.application.project import Project

    project = Project(id=1, path=str(Path("/test/project")), is_active=True)
    session = Session(user_id=123456789, project=project, state=SessionState.ACTIVE)
    session.thread_id = 987654321
    return session


class TestMessageEventHandler:
    """MessageEventHandlerのテスト."""

    def test_init(self, mock_bot: MagicMock) -> None:
        """初期化テスト."""
        handler = MessageEventHandler(mock_bot)
        assert handler.bot == mock_bot
        assert handler._debounce_states == {}

    @pytest.mark.asyncio
    async def test_on_message_bot_message_ignored(
        self, handler: MessageEventHandler, mock_message: MagicMock
    ) -> None:
        """Botメッセージは無視される."""
        mock_message.author.bot = True
        await handler.on_message(mock_message)

        # 何も処理されない
        handler.bot.session_service.get_session_by_thread.assert_not_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_on_message_unauthorized_user_ignored(
        self, handler: MessageEventHandler, mock_message: MagicMock
    ) -> None:
        """許可されていないユーザーのメッセージは無視される."""
        mock_message.author.id = 999999999  # 異なるユーザーID
        await handler.on_message(mock_message)

        # 何も処理されない
        handler.bot.session_service.get_session_by_thread.assert_not_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_on_message_non_thread_ignored(
        self, handler: MessageEventHandler, mock_message: MagicMock
    ) -> None:
        """スレッド以外のメッセージは無視される."""
        mock_message.channel = MagicMock(spec=discord.TextChannel)
        await handler.on_message(mock_message)

        # 何も処理されない
        handler.bot.session_service.get_session_by_thread.assert_not_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_on_message_no_session_ignored(
        self, handler: MessageEventHandler, mock_message: MagicMock
    ) -> None:
        """セッションに紐づいていないスレッドのメッセージは無視される."""
        handler.bot.session_service.get_session_by_thread.return_value = None  # type: ignore[attr-defined]
        await handler.on_message(mock_message)

        # get_session_by_threadは呼ばれるが、send_promptは呼ばれない
        handler.bot.session_service.get_session_by_thread.assert_called_once_with(  # type: ignore[attr-defined]
            987654321
        )
        handler.bot.session_service.send_prompt.assert_not_called()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_on_message_single_message(
        self,
        handler: MessageEventHandler,
        mock_message: MagicMock,
        mock_session: Session,
    ) -> None:
        """単一メッセージがdebounce後に送信される."""
        handler.bot.session_service.get_session_by_thread.return_value = mock_session  # type: ignore[attr-defined]
        handler.bot.session_service.send_prompt = AsyncMock()  # type: ignore[method-assign]

        # メッセージを送信
        await handler.on_message(mock_message)

        # Debounceキーが作成される
        debounce_key = (mock_message.author.id, mock_message.channel.id)
        assert debounce_key in handler._debounce_states
        assert len(handler._debounce_states[debounce_key].messages) == 1

        # Debounce期間待機
        await asyncio.sleep(DEBOUNCE_DELAY + 0.1)

        # プロンプトが送信される
        handler.bot.session_service.send_prompt.assert_called_once_with(
            mock_session.id, "Test message"
        )

        # バッファがクリアされる
        assert handler._debounce_states[debounce_key].messages == []

    @pytest.mark.asyncio
    async def test_on_message_multiple_messages_combined(
        self,
        handler: MessageEventHandler,
        mock_message: MagicMock,
        mock_session: Session,
    ) -> None:
        """連続したメッセージが結合される."""
        handler.bot.session_service.get_session_by_thread.return_value = mock_session  # type: ignore[attr-defined]
        handler.bot.session_service.send_prompt = AsyncMock()  # type: ignore[method-assign]

        # 複数メッセージを送信
        mock_message.content = "Message 1"
        await handler.on_message(mock_message)

        mock_message.content = "Message 2"
        await handler.on_message(mock_message)

        mock_message.content = "Message 3"
        await handler.on_message(mock_message)

        # Debounce期間待機
        await asyncio.sleep(DEBOUNCE_DELAY + 0.1)

        # 結合されたメッセージが送信される
        handler.bot.session_service.send_prompt.assert_called_once_with(
            mock_session.id, "Message 1\nMessage 2\nMessage 3"
        )

    @pytest.mark.asyncio
    async def test_on_message_task_cancelled_on_new_message(
        self,
        handler: MessageEventHandler,
        mock_message: MagicMock,
        mock_session: Session,
    ) -> None:
        """新しいメッセージが来たら前のタスクがキャンセルされる."""
        handler.bot.session_service.get_session_by_thread.return_value = mock_session  # type: ignore[attr-defined]
        handler.bot.session_service.send_prompt = AsyncMock()  # type: ignore[method-assign]

        # 最初のメッセージ
        mock_message.content = "Message 1"
        await handler.on_message(mock_message)

        debounce_key = (mock_message.author.id, mock_message.channel.id)
        first_task = handler._debounce_states[debounce_key].task

        # 少し待つ（debounce期間内）
        await asyncio.sleep(0.5)

        # 2つ目のメッセージ
        mock_message.content = "Message 2"
        await handler.on_message(mock_message)

        # 最初のタスクがキャンセルされている
        assert first_task is not None
        # タスクがキャンセル処理される時間を待つ
        await asyncio.sleep(0.01)
        assert first_task.cancelled()

        # Debounce期間待機
        await asyncio.sleep(DEBOUNCE_DELAY + 0.1)

        # 両方のメッセージが送信される
        handler.bot.session_service.send_prompt.assert_called_once_with(
            mock_session.id, "Message 1\nMessage 2"
        )

    @pytest.mark.asyncio
    async def test_send_debounced_messages_session_state_error(
        self,
        handler: MessageEventHandler,
        mock_message: MagicMock,
        mock_session: Session,
    ) -> None:
        """SessionStateErrorが発生した場合のエラーハンドリング."""
        from discord_acp_bridge.application.session import SessionStateError

        handler.bot.session_service.get_session_by_thread.return_value = mock_session  # type: ignore[attr-defined]
        handler.bot.session_service.send_prompt = AsyncMock(  # type: ignore[method-assign]
            side_effect=SessionStateError(
                mock_session.id, SessionState.CLOSED, "Invalid state"
            )
        )

        # メッセージを送信
        await handler.on_message(mock_message)

        # Debounce期間待機
        await asyncio.sleep(DEBOUNCE_DELAY + 0.1)

        # エラーメッセージが送信される
        mock_message.channel.send.assert_called_once()
        call_args = mock_message.channel.send.call_args[0][0]
        assert "セッションの状態が不正です" in call_args

    @pytest.mark.asyncio
    async def test_send_debounced_messages_general_error(
        self,
        handler: MessageEventHandler,
        mock_message: MagicMock,
        mock_session: Session,
    ) -> None:
        """一般的なエラーが発生した場合のエラーハンドリング."""
        handler.bot.session_service.get_session_by_thread.return_value = mock_session  # type: ignore[attr-defined]
        handler.bot.session_service.send_prompt = AsyncMock(  # type: ignore[method-assign]
            side_effect=Exception("Unexpected error")
        )

        # メッセージを送信
        await handler.on_message(mock_message)

        # Debounce期間待機
        await asyncio.sleep(DEBOUNCE_DELAY + 0.1)

        # エラーメッセージが送信される
        mock_message.channel.send.assert_called_once()
        call_args = mock_message.channel.send.call_args[0][0]
        assert "エラーが発生しました" in call_args

    @pytest.mark.asyncio
    async def test_send_debounced_messages_cancelled_error(
        self,
        handler: MessageEventHandler,
        mock_message: MagicMock,
        mock_session: Session,
    ) -> None:
        """タスクキャンセル時にCancelledErrorが適切に処理される."""
        handler.bot.session_service.get_session_by_thread.return_value = mock_session  # type: ignore[attr-defined]
        handler.bot.session_service.send_prompt = AsyncMock()  # type: ignore[method-assign]

        # メッセージを送信
        await handler.on_message(mock_message)

        debounce_key = (mock_message.author.id, mock_message.channel.id)
        task = handler._debounce_states[debounce_key].task

        # タスクをキャンセル
        assert task is not None
        task.cancel()

        # キャンセルが正常に処理される
        with pytest.raises(asyncio.CancelledError):
            await task
