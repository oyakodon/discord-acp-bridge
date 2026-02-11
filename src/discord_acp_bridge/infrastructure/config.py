"""Configuration management."""

from __future__ import annotations

import json

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """アプリケーション設定."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Discord設定
    discord_bot_token: str = Field(
        ...,
        description="Discord Bot Token",
    )
    discord_guild_id: int = Field(
        ...,
        description="開発用ギルドID（指定時はそのギルドのみにコマンド同期）",
    )
    discord_allowed_user_id: int = Field(
        ...,
        description="利用を許可するDiscordユーザーID",
    )

    # ACP Server設定
    agent_command: list[str] = Field(
        default=["claude-code-acp"],
        description="ACP Server起動コマンド",
    )

    # Trusted Paths（プロジェクトとして許可するディレクトリのルートパス）
    trusted_paths: list[str] = Field(
        default=[],
        description="プロジェクトとして許可するディレクトリのルートパスのリスト",
    )

    # パーミッション設定
    permission_timeout: float = Field(
        default=120.0,
        description="パーミッション要求のタイムアウト秒数（0で自動承認）",
    )

    # プロジェクト設定
    default_project_mode: str = Field(
        default="read",
        description="プロジェクトのデフォルト権限モード (read: 読み取り専用, rw: 読み書き)",
    )

    # ロギング設定
    log_level: str = Field(
        default="INFO",
        description="ログレベル（DEBUG, INFO, WARNING, ERROR, CRITICAL）",
    )
    log_dir: str = Field(
        default="logs",
        description="ログ出力ディレクトリ",
    )
    log_backup_count: int = Field(
        default=7,
        description="ログローテーションの保持日数",
    )

    @field_validator("agent_command", mode="before")
    @classmethod
    def parse_agent_command(cls, v: str | list[str]) -> list[str]:
        """agent_commandをパースする（JSON文字列または配列）."""
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
                return [v]
            except json.JSONDecodeError:
                return [v]
        return v

    @field_validator("trusted_paths", mode="before")
    @classmethod
    def parse_trusted_paths(cls, v: str | list[str]) -> list[str]:
        """trusted_pathsをパースする（JSON文字列または配列）."""
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
                return [v]
            except json.JSONDecodeError:
                return [v]
        return v

    @field_validator("default_project_mode")
    @classmethod
    def validate_default_project_mode(cls, v: str) -> str:
        """default_project_modeのバリデーション."""
        valid_modes = {"read", "rw"}
        if v not in valid_modes:
            msg = f"DEFAULT_PROJECT_MODE は 'read' または 'rw' を指定してください。got: {v!r}"
            raise ValueError(msg)
        return v


# グローバル設定インスタンス（シングルトン）
_config: Config | None = None


def get_config() -> Config:
    """
    グローバル設定インスタンスを取得する.

    Returns:
        設定インスタンス
    """
    global _config
    if _config is None:
        _config = Config()
    return _config
