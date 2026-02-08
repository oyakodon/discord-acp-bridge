"""Test cases for main entry point."""

from __future__ import annotations

import asyncio
import signal
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable


def _setup_mocks() -> tuple[
    MagicMock, MagicMock, MagicMock, dict[int, Callable[[], None]]
]:
    """テスト用の共通モックをセットアップする."""
    config = MagicMock()
    config.log_level = "INFO"
    config.discord_bot_token = "test-token"
    config.discord_guild_id = 123
    config.discord_allowed_user_id = 456

    mock_session = MagicMock()
    mock_session.close_all_sessions = AsyncMock()

    mock_bot = MagicMock()
    mock_bot.close = AsyncMock()
    mock_bot.start = AsyncMock()
    mock_bot.send_message_to_thread = AsyncMock()
    mock_bot.send_timeout_notification = AsyncMock()
    mock_bot.set_typing_indicator = AsyncMock()

    signal_handlers: dict[int, Callable[[], None]] = {}

    return config, mock_session, mock_bot, signal_handlers


def _patch_loop_signal_handlers(
    signal_handlers: dict[int, Callable[[], None]],
) -> None:
    """イベントループのシグナルハンドラーをモンキーパッチする."""
    loop = asyncio.get_running_loop()

    def fake_add(sig: int, handler: Callable[[], None]) -> None:
        signal_handlers[sig] = handler

    def fake_remove(sig: int) -> bool:
        signal_handlers.pop(sig, None)
        return True

    loop.add_signal_handler = fake_add  # type: ignore[assignment]
    loop.remove_signal_handler = fake_remove  # type: ignore[method-assign]


@pytest.mark.asyncio
async def test_signal_handler_sets_shutdown_event() -> None:
    """シグナルハンドラーがshutdown_eventをsetすることを確認."""
    from discord_acp_bridge.main import main

    config, mock_session, mock_bot, signal_handlers = _setup_mocks()
    shutdown_triggered = False

    with (
        patch("discord_acp_bridge.main.get_config", return_value=config),
        patch("discord_acp_bridge.main.configure_logging"),
        patch("discord_acp_bridge.main.ProjectService"),
        patch("discord_acp_bridge.main.SessionService", return_value=mock_session),
        patch(
            "discord_acp_bridge.presentation.bot.ACPBot",
            return_value=mock_bot,
        ),
    ):
        _patch_loop_signal_handlers(signal_handlers)

        async def fake_start(token: str) -> None:
            nonlocal shutdown_triggered
            assert signal.SIGINT in signal_handlers
            assert signal.SIGTERM in signal_handlers
            signal_handlers[signal.SIGINT]()
            shutdown_triggered = True
            await asyncio.sleep(0.1)

        mock_bot.start = AsyncMock(side_effect=fake_start)

        await main()

        assert shutdown_triggered
        mock_session.close_all_sessions.assert_called_once()
        mock_bot.close.assert_called_once()
        # シグナルハンドラーが解除されている
        assert signal.SIGINT not in signal_handlers
        assert signal.SIGTERM not in signal_handlers


@pytest.mark.asyncio
async def test_shutdown_double_signal_ignored() -> None:
    """二重シグナルが無視されることを確認."""
    from discord_acp_bridge.main import main

    config, mock_session, mock_bot, signal_handlers = _setup_mocks()
    signal_call_count = 0

    with (
        patch("discord_acp_bridge.main.get_config", return_value=config),
        patch("discord_acp_bridge.main.configure_logging"),
        patch("discord_acp_bridge.main.ProjectService"),
        patch("discord_acp_bridge.main.SessionService", return_value=mock_session),
        patch(
            "discord_acp_bridge.presentation.bot.ACPBot",
            return_value=mock_bot,
        ),
    ):
        _patch_loop_signal_handlers(signal_handlers)

        async def fake_start(token: str) -> None:
            nonlocal signal_call_count
            handler = signal_handlers[signal.SIGINT]
            handler()
            signal_call_count += 1
            handler()
            signal_call_count += 1
            await asyncio.sleep(0.1)

        mock_bot.start = AsyncMock(side_effect=fake_start)

        await main()

        assert signal_call_count == 2
        mock_session.close_all_sessions.assert_called_once()


@pytest.mark.asyncio
async def test_session_cleanup_error_does_not_prevent_shutdown() -> None:
    """セッションクリーンアップのエラーがシャットダウンを妨げないことを確認."""
    from discord_acp_bridge.main import main

    config, mock_session, mock_bot, signal_handlers = _setup_mocks()
    mock_session.close_all_sessions = AsyncMock(
        side_effect=RuntimeError("cleanup failed")
    )

    with (
        patch("discord_acp_bridge.main.get_config", return_value=config),
        patch("discord_acp_bridge.main.configure_logging"),
        patch("discord_acp_bridge.main.ProjectService"),
        patch("discord_acp_bridge.main.SessionService", return_value=mock_session),
        patch(
            "discord_acp_bridge.presentation.bot.ACPBot",
            return_value=mock_bot,
        ),
    ):
        _patch_loop_signal_handlers(signal_handlers)

        async def fake_start(token: str) -> None:
            signal_handlers[signal.SIGINT]()
            await asyncio.sleep(0.1)

        mock_bot.start = AsyncMock(side_effect=fake_start)

        await main()

        mock_bot.close.assert_called_once()


@pytest.mark.asyncio
async def test_sigterm_triggers_shutdown() -> None:
    """SIGTERMでもシャットダウンが発生することを確認."""
    from discord_acp_bridge.main import main

    config, mock_session, mock_bot, signal_handlers = _setup_mocks()

    with (
        patch("discord_acp_bridge.main.get_config", return_value=config),
        patch("discord_acp_bridge.main.configure_logging"),
        patch("discord_acp_bridge.main.ProjectService"),
        patch("discord_acp_bridge.main.SessionService", return_value=mock_session),
        patch(
            "discord_acp_bridge.presentation.bot.ACPBot",
            return_value=mock_bot,
        ),
    ):
        _patch_loop_signal_handlers(signal_handlers)

        async def fake_start(token: str) -> None:
            signal_handlers[signal.SIGTERM]()
            await asyncio.sleep(0.1)

        mock_bot.start = AsyncMock(side_effect=fake_start)

        await main()

        mock_session.close_all_sessions.assert_called_once()
        mock_bot.close.assert_called_once()
