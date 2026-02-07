"""Project management service."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from discord_acp_bridge.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from discord_acp_bridge.infrastructure.config import Config

logger = get_logger(__name__)


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

    def _is_path_trusted(self, path: Path) -> bool:
        """
        指定されたパスがTrusted Path配下にあるかチェックする.

        Args:
            path: チェック対象のパス

        Returns:
            Trusted Path配下にある場合True
        """
        abs_path = path.resolve()
        for trusted in self._config.trusted_paths:
            trusted_path = Path(trusted).resolve()
            try:
                # abs_pathがtrusted_pathの配下にあるかチェック
                abs_path.relative_to(trusted_path)
                return True
            except ValueError:
                # relative_toが失敗した場合は配下にない
                continue
        return False

    def list_projects(self) -> list[Project]:
        """
        Trusted Path配下のディレクトリを自動スキャンしてプロジェクト一覧を取得する.

        Returns:
            プロジェクト一覧（パス名でソート済み、ID順）
        """
        discovered_paths: list[str] = []

        for trusted in self._config.trusted_paths:
            trusted_path = Path(trusted).resolve()
            if not trusted_path.exists():
                logger.warning("Trusted path does not exist: %s", trusted_path)
                continue

            if not trusted_path.is_dir():
                logger.warning("Trusted path is not a directory: %s", trusted_path)
                continue

            # Trusted Path直下のディレクトリを収集
            try:
                for item in trusted_path.iterdir():
                    if item.is_dir() and not item.name.startswith("."):
                        # シンボリックリンク攻撃を防ぐため、Trusted Path検証を実施
                        if self._is_path_trusted(item):
                            discovered_paths.append(str(item.resolve()))
                        else:
                            logger.warning(
                                "Skipping directory outside trusted paths: %s", item
                            )
            except PermissionError:
                logger.warning("Permission denied when scanning: %s", trusted_path)
                continue

        # パス名でソート
        discovered_paths.sort()

        # Projectモデルに変換
        projects = []
        for idx, path in enumerate(discovered_paths):
            project_id = idx + 1
            is_active = project_id == self._active_project_id
            projects.append(Project(id=project_id, path=path, is_active=is_active))

        logger.debug("Listed %d projects from trusted paths", len(projects))
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

    def get_project_by_id(self, project_id: int) -> Project:
        """
        指定されたIDのプロジェクトを取得する.

        Args:
            project_id: プロジェクトID

        Returns:
            該当するプロジェクト

        Raises:
            ProjectNotFoundError: 指定されたIDのプロジェクトが存在しない場合
            ValueError: プロジェクトがTrusted Path配下にない場合（防御的チェック）
        """
        projects = self.list_projects()

        for project in projects:
            if project.id == project_id:
                # Trusted Path検証（防御的チェック）
                project_path = Path(project.path)
                if not self._is_path_trusted(project_path):
                    logger.error(
                        "SECURITY: Attempted to access path outside trusted paths. "
                        "Path: %s, Trusted Paths: %s, Project ID: %d",
                        project.path,
                        self._config.trusted_paths,
                        project_id,
                    )
                    msg = f"Project path is not within trusted paths: {project.path}"
                    raise ValueError(msg)

                logger.debug("Retrieved project #%d: %s", project_id, project.path)
                return project

        logger.error("Project #%d not found", project_id)
        raise ProjectNotFoundError(project_id)

    def switch_project(self, project_id: int) -> Project:
        """
        指定されたプロジェクトをアクティブに切り替える.

        Args:
            project_id: プロジェクトID

        Returns:
            切り替え後のプロジェクト

        Raises:
            ProjectNotFoundError: 指定されたIDのプロジェクトが存在しない場合
            ValueError: プロジェクトがTrusted Path配下にない場合（防御的チェック）
        """
        # get_project_by_idを使用してプロジェクトを取得
        project = self.get_project_by_id(project_id)

        self._active_project_id = project_id
        logger.info("Switched to project #%d: %s", project_id, project.path)
        return Project(id=project.id, path=project.path, is_active=True)
