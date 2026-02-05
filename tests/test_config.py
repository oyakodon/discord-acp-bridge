"""Tests for configuration management."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from discord_acp_bridge.infrastructure.config import Config


def test_config_default_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert config.projects_file == Path("projects.json")


def test_config_custom_agent_command_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """agent_commandがリスト形式で設定できることを確認する."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test_token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456789")
    monkeypatch.setenv("DISCORD_ALLOWED_USER_ID", "987654321")
    monkeypatch.setenv("AGENT_COMMAND", '["custom-agent", "--arg1", "value1"]')

    config = Config()

    assert config.agent_command == ["custom-agent", "--arg1", "value1"]


def test_config_custom_agent_command_string(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """agent_commandが単一の文字列をJSON配列形式で設定できることを確認する."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test_token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456789")
    monkeypatch.setenv("DISCORD_ALLOWED_USER_ID", "987654321")
    # Pydantic SettingsではList型はJSON形式で渡す必要がある
    monkeypatch.setenv("AGENT_COMMAND", '["custom-agent"]')

    config = Config()

    assert config.agent_command == ["custom-agent"]


def test_load_projects_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """プロジェクト設定ファイルの読み込みが成功することを確認する."""
    # 環境変数を設定
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test_token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456789")
    monkeypatch.setenv("DISCORD_ALLOWED_USER_ID", "987654321")

    # テスト用プロジェクトファイルを作成
    projects_file = tmp_path / "projects.json"
    projects_data = ["/path/to/project1", "/path/to/project2", "/path/to/project3"]
    projects_file.write_text(json.dumps(projects_data), encoding="utf-8")

    # Configインスタンスを作成
    config = Config(projects_file=projects_file)

    # プロジェクトを読み込み
    projects = config.load_projects()

    assert len(projects) == 3
    assert projects == projects_data


def test_load_projects_file_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """プロジェクト設定ファイルが存在しない場合、空のリストを返すことを確認する."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test_token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456789")
    monkeypatch.setenv("DISCORD_ALLOWED_USER_ID", "987654321")

    # 存在しないファイルを指定
    projects_file = tmp_path / "nonexistent.json"
    config = Config(projects_file=projects_file)

    # プロジェクトを読み込み（空のリストが返る）
    projects = config.load_projects()

    assert projects == []


def test_load_projects_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """不正なJSON形式のプロジェクト設定ファイルを読み込むとエラーになることを確認する."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test_token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456789")
    monkeypatch.setenv("DISCORD_ALLOWED_USER_ID", "987654321")

    # 不正なJSONファイルを作成
    projects_file = tmp_path / "projects.json"
    projects_file.write_text("{ invalid json }", encoding="utf-8")

    config = Config(projects_file=projects_file)

    # JSONDecodeErrorが発生することを確認
    with pytest.raises(json.JSONDecodeError):
        config.load_projects()


def test_load_projects_not_array(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """配列でないプロジェクト設定ファイルを読み込むとエラーになることを確認する."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test_token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456789")
    monkeypatch.setenv("DISCORD_ALLOWED_USER_ID", "987654321")

    # 配列でないJSONファイルを作成
    projects_file = tmp_path / "projects.json"
    projects_file.write_text('{"key": "value"}', encoding="utf-8")

    config = Config(projects_file=projects_file)

    # ValueErrorが発生することを確認
    with pytest.raises(ValueError, match="must contain a JSON array"):
        config.load_projects()


def test_load_projects_non_string_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """文字列でない要素を含むプロジェクト設定ファイルを読み込むとエラーになることを確認する."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test_token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456789")
    monkeypatch.setenv("DISCORD_ALLOWED_USER_ID", "987654321")

    # 文字列でない要素を含むJSONファイルを作成
    projects_file = tmp_path / "projects.json"
    projects_file.write_text('["/path/to/project", 123, true]', encoding="utf-8")

    config = Config(projects_file=projects_file)

    # ValueErrorが発生することを確認
    with pytest.raises(ValueError, match="must be strings"):
        config.load_projects()


def test_save_projects_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """プロジェクト設定ファイルの保存が成功することを確認する."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test_token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456789")
    monkeypatch.setenv("DISCORD_ALLOWED_USER_ID", "987654321")

    # テスト用プロジェクトファイルのパス
    projects_file = tmp_path / "projects.json"
    config = Config(projects_file=projects_file)

    # プロジェクトを保存
    projects_data = ["/path/to/project1", "/path/to/project2"]
    config.save_projects(projects_data)

    # ファイルが作成されていることを確認
    assert projects_file.exists()

    # ファイル内容を確認
    saved_projects = json.loads(projects_file.read_text(encoding="utf-8"))
    assert saved_projects == projects_data


def test_save_projects_creates_parent_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """親ディレクトリが存在しない場合、自動的に作成されることを確認する."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test_token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456789")
    monkeypatch.setenv("DISCORD_ALLOWED_USER_ID", "987654321")

    # 存在しないディレクトリ内のファイルパス
    projects_file = tmp_path / "subdir" / "projects.json"
    config = Config(projects_file=projects_file)

    # プロジェクトを保存
    projects_data = ["/path/to/project"]
    config.save_projects(projects_data)

    # ファイルと親ディレクトリが作成されていることを確認
    assert projects_file.exists()
    assert projects_file.parent.exists()


def test_save_projects_invalid_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """不正な型のプロジェクトリストを保存しようとするとエラーになることを確認する."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test_token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456789")
    monkeypatch.setenv("DISCORD_ALLOWED_USER_ID", "987654321")

    projects_file = tmp_path / "projects.json"
    config = Config(projects_file=projects_file)

    # リストでない値を渡す
    with pytest.raises(ValueError, match="must be a list"):
        config.save_projects("not a list")  # type: ignore[arg-type]


def test_save_projects_non_string_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """文字列でない要素を含むプロジェクトリストを保存しようとするとエラーになることを確認する."""
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test_token")
    monkeypatch.setenv("DISCORD_GUILD_ID", "123456789")
    monkeypatch.setenv("DISCORD_ALLOWED_USER_ID", "987654321")

    projects_file = tmp_path / "projects.json"
    config = Config(projects_file=projects_file)

    # 文字列でない要素を含むリストを渡す
    with pytest.raises(ValueError, match="must be strings"):
        config.save_projects(["/path/to/project", 123, True])  # type: ignore[list-item]
