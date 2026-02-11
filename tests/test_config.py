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
    # 環境変数のデフォルト値を明示的に設定（.envファイルの値も上書きされる）
    monkeypatch.setenv("AGENT_COMMAND", '["claude-code-acp"]')
    monkeypatch.setenv("TRUSTED_PATHS", "[]")

    config = Config()

    assert config.discord_bot_token == "test_token"
    assert config.discord_guild_id == 123456789
    assert config.discord_allowed_user_id == 987654321
    assert config.agent_command == ["claude-code-acp"]
    assert config.trusted_paths == []
    assert config.default_project_mode == "read"


def test_config_custom_agent_command_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """agent_commandがリスト形式で設定できることを確認する."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test_token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456789")
    monkeypatch.setenv("DISCORD_ALLOWED_USER_ID", "987654321")
    monkeypatch.setenv("AGENT_COMMAND", '["custom-agent", "--arg1", "value1"]')
    monkeypatch.setenv("TRUSTED_PATHS", "[]")

    config = Config()

    assert config.agent_command == ["custom-agent", "--arg1", "value1"]


def test_config_custom_agent_command_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """agent_commandが単一の文字列をJSON配列形式で設定できることを確認する."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test_token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456789")
    monkeypatch.setenv("DISCORD_ALLOWED_USER_ID", "987654321")
    # Pydantic SettingsではList型はJSON形式で渡す必要がある
    monkeypatch.setenv("AGENT_COMMAND", '["custom-agent"]')
    monkeypatch.setenv("TRUSTED_PATHS", "[]")

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


def test_config_default_project_mode_rw(monkeypatch: pytest.MonkeyPatch) -> None:
    """default_project_mode=rw が正しく設定されることを確認する."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test_token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456789")
    monkeypatch.setenv("DISCORD_ALLOWED_USER_ID", "987654321")
    monkeypatch.setenv("DEFAULT_PROJECT_MODE", "rw")

    config = Config()

    assert config.default_project_mode == "rw"


def test_config_default_project_mode_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    """無効な default_project_mode が ValueError を発生させることを確認する."""
    from pydantic import ValidationError

    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test_token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456789")
    monkeypatch.setenv("DISCORD_ALLOWED_USER_ID", "987654321")
    monkeypatch.setenv("DEFAULT_PROJECT_MODE", "invalid_mode")

    with pytest.raises(ValidationError):
        Config()
