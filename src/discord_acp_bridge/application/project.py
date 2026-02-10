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


class ProjectCreationError(Exception):
    """プロジェクト作成に失敗した場合の例外."""

    def __init__(self, message: str) -> None:
        """
        Initialize ProjectCreationError.

        Args:
            message: エラーメッセージ
        """
        super().__init__(message)


class ProjectService:
    """プロジェクト管理サービス."""

    def __init__(self, config: Config) -> None:
        """
        Initialize ProjectService.

        Args:
            config: アプリケーション設定
        """
        self._config = config

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

    def _scan_project_paths(self) -> list[str]:
        """
        Trusted Path配下のプロジェクトパスを収集する.

        Returns:
            ソート済みのプロジェクトパスリスト
        """
        discovered_paths: list[str] = []

        for trusted in self._config.trusted_paths:
            trusted_path = Path(trusted).resolve()
            if not trusted_path.exists():
                logger.warning("Trusted path does not exist", path=str(trusted_path))
                continue

            if not trusted_path.is_dir():
                logger.warning(
                    "Trusted path is not a directory", path=str(trusted_path)
                )
                continue

            # Trusted Path直下のディレクトリを収集
            try:
                for item in trusted_path.iterdir():
                    if item.is_dir() and not item.name.startswith("."):
                        resolved = item.resolve()
                        # シンボリックリンク攻撃を防ぐため、Trusted Path検証を実施
                        if self._is_path_trusted(resolved):
                            discovered_paths.append(str(resolved))
                        else:
                            logger.warning(
                                "Skipping directory outside trusted paths",
                                path=str(resolved),
                            )
            except PermissionError:
                logger.warning(
                    "Permission denied when scanning", path=str(trusted_path)
                )
                continue

        discovered_paths.sort()
        return discovered_paths

    def list_projects(self) -> list[Project]:
        """
        Trusted Path配下のディレクトリを自動スキャンしてプロジェクト一覧を取得する.

        Returns:
            プロジェクト一覧（パス名でソート済み、ID順）
        """
        discovered_paths = self._scan_project_paths()

        projects = [
            Project(id=idx + 1, path=path) for idx, path in enumerate(discovered_paths)
        ]

        logger.debug("Listed projects from trusted paths", project_count=len(projects))
        return projects

    def create_project(self, name: str) -> Project:
        """
        Trusted Pathの最初のパス配下に新しいプロジェクトディレクトリを作成する.

        Args:
            name: プロジェクト名（ディレクトリ名として使用される）

        Returns:
            作成されたプロジェクト

        Raises:
            ProjectCreationError: プロジェクト作成に失敗した場合
        """
        # Trusted Pathsが設定されているか確認
        if not self._config.trusted_paths:
            raise ProjectCreationError(
                "Trusted Pathsが設定されていません。"
                "環境変数 TRUSTED_PATHS を設定してください。"
            )

        # 名前のバリデーション
        name = name.strip()
        if not name:
            raise ProjectCreationError("プロジェクト名を指定してください。")

        # パストラバーサル防止
        if "/" in name or "\\" in name or "\0" in name:
            raise ProjectCreationError(
                "プロジェクト名にパス区切り文字は使用できません。"
            )

        # 隠しディレクトリの防止
        if name.startswith("."):
            raise ProjectCreationError(
                "プロジェクト名を `.` で始めることはできません。"
            )

        # Trusted Paths[0]配下に作成
        base_path = Path(self._config.trusted_paths[0]).resolve()

        if not base_path.exists():
            raise ProjectCreationError(f"Trusted Pathが存在しません: {base_path}")

        if not base_path.is_dir():
            raise ProjectCreationError(
                f"Trusted Pathがディレクトリではありません: {base_path}"
            )

        project_path = base_path / name

        # ディレクトリが既に存在するか確認
        if project_path.exists():
            raise ProjectCreationError(f"既に存在します: {project_path}")

        # 防御的チェック: パストラバーサル対策の最終確認
        if not self._is_path_trusted(project_path):
            raise ProjectCreationError(
                "プロジェクト名が不正です。Trusted Path外になります。"
            )

        # ディレクトリを作成
        try:
            project_path.mkdir(parents=False, exist_ok=False)
        except OSError as e:
            raise ProjectCreationError(f"ディレクトリの作成に失敗しました: {e}") from e

        logger.info(
            "Created new project directory",
            name=name,
            path=str(project_path),
        )

        # パス一覧を取得してIDを計算
        all_paths = self._scan_project_paths()
        project_id = all_paths.index(str(project_path)) + 1

        return Project(id=project_id, path=str(project_path))

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
                        "SECURITY: Attempted to access path outside trusted paths",
                        project_path=project.path,
                        trusted_paths=self._config.trusted_paths,
                        project_id=project_id,
                    )
                    msg = f"Project path is not within trusted paths: {project.path}"
                    raise ValueError(msg)

                logger.debug(
                    "Retrieved project", project_id=project_id, path=project.path
                )
                return project

        logger.error("Project not found", project_id=project_id)
        raise ProjectNotFoundError(project_id)
