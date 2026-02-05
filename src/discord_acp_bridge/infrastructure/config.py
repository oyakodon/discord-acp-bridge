"""Configuration management."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


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

    # プロジェクト設定ファイルパス
    projects_file: Path = Field(
        default=Path("projects.json"),
        description="プロジェクト設定ファイルのパス",
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

    @field_validator("projects_file", mode="before")
    @classmethod
    def parse_projects_file(cls, v: str | Path) -> Path:
        """projects_fileをPathに変換する."""
        if isinstance(v, str):
            return Path(v)
        return v

    def load_projects(self) -> list[str]:
        """
        プロジェクト設定ファイルからプロジェクトリストを読み込む.

        ファイルが存在しない場合は空のリストを返す.

        Returns:
            プロジェクトパスのリスト

        Raises:
            json.JSONDecodeError: 設定ファイルのフォーマットが不正な場合
            ValueError: 設定ファイルの内容が配列でない、または文字列以外の要素を含む場合
        """
        if not self.projects_file.exists():
            logger.warning(
                "Projects file not found: %s. Returning empty list.",
                self.projects_file,
            )
            return []

        try:
            content = self.projects_file.read_text(encoding="utf-8")
            projects = json.loads(content)

            if not isinstance(projects, list):
                msg = "Projects file must contain a JSON array"
                raise ValueError(msg)

            if not all(isinstance(p, str) for p in projects):
                msg = "All project entries must be strings"
                raise ValueError(msg)

            logger.info("Loaded %d projects from %s", len(projects), self.projects_file)
            return projects

        except json.JSONDecodeError:
            logger.exception("Failed to parse projects file: %s", self.projects_file)
            raise
        except ValueError:
            logger.exception("Invalid projects file format: %s", self.projects_file)
            raise

    def save_projects(self, projects: list[str]) -> None:
        """
        プロジェクトリストを設定ファイルに保存する.

        Args:
            projects: プロジェクトパスのリスト

        Raises:
            ValueError: projectsが不正な形式の場合
        """
        if not isinstance(projects, list):
            msg = "Projects must be a list"
            raise ValueError(msg)

        if not all(isinstance(p, str) for p in projects):
            msg = "All project entries must be strings"
            raise ValueError(msg)

        try:
            # 親ディレクトリが存在しない場合は作成
            self.projects_file.parent.mkdir(parents=True, exist_ok=True)

            # JSON形式で保存（インデント付き）
            content = json.dumps(projects, indent=2, ensure_ascii=False)
            self.projects_file.write_text(content, encoding="utf-8")

            logger.info("Saved %d projects to %s", len(projects), self.projects_file)

        except Exception:
            logger.exception("Failed to save projects file: %s", self.projects_file)
            raise


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
