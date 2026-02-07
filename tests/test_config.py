"""Tests for configuration management."""

from __future__ import annotations

import pytest

from discord_acp_bridge.infrastructure.config import Config


def test_config_default_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """デフォルト値が正しく設定されることを確認する."""
    # 環境変数を設定
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test_token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456789")
    monkeypatch.setenv("DISCORD_ALLOWED_USER_ID", "987654321")

    config = Config()

    assert config.discord_bot_token == "test_token"
    assert config.discord_guild_id == 123456789
    assert config.discord_allowed_user_id == 987654321
    assert config.agent_command == ["claude-code-acp"]
    assert config.trusted_paths == []


def test_config_custom_agent_command_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """agent_commandがリスト形式で設定できることを確認する."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test_token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456789")
    monkeypatch.setenv("DISCORD_ALLOWED_USER_ID", "987654321")
    monkeypatch.setenv("AGENT_COMMAND", '["custom-agent", "--arg1", "value1"]')

    config = Config()

    assert config.agent_command == ["custom-agent", "--arg1", "value1"]


def test_config_custom_agent_command_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """agent_commandが単一の文字列をJSON配列形式で設定できることを確認する."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test_token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456789")
    monkeypatch.setenv("DISCORD_ALLOWED_USER_ID", "987654321")
    # Pydantic SettingsではList型はJSON形式で渡す必要がある
    monkeypatch.setenv("AGENT_COMMAND", '["custom-agent"]')

    config = Config()

    assert config.agent_command == ["custom-agent"]


def test_config_custom_trusted_paths_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """trusted_pathsがリスト形式で設定できることを確認する."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test_token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456789")
    monkeypatch.setenv("DISCORD_ALLOWED_USER_ID", "987654321")
    monkeypatch.setenv("TRUSTED_PATHS", '["/path/to/projects", "/another/path"]')

    config = Config()

    assert config.trusted_paths == ["/path/to/projects", "/another/path"]


def test_config_custom_trusted_paths_single_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """trusted_pathsが単一の文字列をJSON配列形式で設定できることを確認する."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test_token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456789")
    monkeypatch.setenv("DISCORD_ALLOWED_USER_ID", "987654321")
    monkeypatch.setenv("TRUSTED_PATHS", '["/path/to/projects"]')

    config = Config()

    assert config.trusted_paths == ["/path/to/projects"]
