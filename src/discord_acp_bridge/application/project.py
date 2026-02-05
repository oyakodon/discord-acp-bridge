"""Project management service."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from discord_acp_bridge.infrastructure.config import Config

logger = logging.getLogger(__name__)


class Project(BaseModel):
    """プロジェクト情報."""

    id: int
    path: str
    is_active: bool = False


class ProjectNotFoundError(Exception):
    """指定されたプロジェクトが見つからない場合の例外."""

    def __init__(self, project_id: int) -> None:
        """
        Initialize ProjectNotFoundError.

        Args:
            project_id: 見つからなかったプロジェクトID
        """
        super().__init__(f"Project #{project_id} not found")
        self.project_id = project_id


class ProjectService:
    """プロジェクト管理サービス."""

    def __init__(self, config: Config) -> None:
        """
        Initialize ProjectService.

        Args:
            config: アプリケーション設定
        """
        self._config = config
        self._active_project_id: int | None = None

    def list_projects(self) -> list[Project]:
        """
        登録されているプロジェクト一覧を取得する.

        Returns:
            プロジェクト一覧（ID順）
        """
        project_paths = self._config.load_projects()

        projects = []
        for idx, path in enumerate(project_paths):
            project_id = idx + 1
            is_active = project_id == self._active_project_id
            projects.append(Project(id=project_id, path=path, is_active=is_active))

        logger.debug("Listed %d projects", len(projects))
        return projects

    def get_active_project(self) -> Project | None:
        """
        現在アクティブなプロジェクトを取得する.

        Returns:
            アクティブなプロジェクト。なければNone
        """
        if self._active_project_id is None:
            logger.debug("No active project")
            return None

        projects = self.list_projects()
        for project in projects:
            if project.id == self._active_project_id:
                logger.debug("Active project: %s (ID: %d)", project.path, project.id)
                return project

        # アクティブIDが設定されているが、プロジェクトリストに存在しない場合
        logger.warning(
            "Active project ID %d not found in project list. Resetting.",
            self._active_project_id,
        )
        self._active_project_id = None
        return None

    def switch_project(self, project_id: int) -> Project:
        """
        指定されたプロジェクトをアクティブに切り替える.

        Args:
            project_id: プロジェクトID

        Returns:
            切り替え後のプロジェクト

        Raises:
            ProjectNotFoundError: 指定されたIDのプロジェクトが存在しない場合
        """
        projects = self.list_projects()

        for project in projects:
            if project.id == project_id:
                self._active_project_id = project_id
                logger.info("Switched to project #%d: %s", project_id, project.path)
                return Project(id=project.id, path=project.path, is_active=True)

        logger.error("Project #%d not found", project_id)
        raise ProjectNotFoundError(project_id)

    def add_project(self, path: str) -> Project:
        """
        新規プロジェクトを登録する.

        Args:
            path: プロジェクトのディレクトリパス

        Returns:
            登録されたプロジェクト

        Raises:
            ValueError: パスが存在しない、またはディレクトリでない場合
        """
        # パスの存在チェック
        project_path = Path(path)
        if not project_path.exists():
            msg = f"Path does not exist: {path}"
            logger.error(msg)
            raise ValueError(msg)

        if not project_path.is_dir():
            msg = f"Path is not a directory: {path}"
            logger.error(msg)
            raise ValueError(msg)

        # 既存のプロジェクトリストを取得
        project_paths = self._config.load_projects()

        # 絶対パスに変換して重複チェック
        abs_path = str(project_path.resolve())
        if abs_path in [str(Path(p).resolve()) for p in project_paths]:
            logger.warning("Project already exists: %s", abs_path)
            # 既存のプロジェクトを返す
            for idx, p in enumerate(project_paths):
                if str(Path(p).resolve()) == abs_path:
                    return Project(
                        id=idx + 1,
                        path=project_paths[idx],
                        is_active=idx + 1 == self._active_project_id,
                    )

        # 新規プロジェクトを追加
        project_paths.append(abs_path)
        self._config.save_projects(project_paths)

        # 新しいIDを計算
        new_id = len(project_paths)
        logger.info("Added project #%d: %s", new_id, abs_path)

        return Project(id=new_id, path=abs_path, is_active=False)
