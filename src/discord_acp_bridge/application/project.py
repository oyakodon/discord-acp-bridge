"""Project management service."""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from discord_acp_bridge.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from discord_acp_bridge.infrastructure.config import Config

logger = get_logger(__name__)

_AUTO_APPROVE_DIR = ".acp-bridge"
_AUTO_APPROVE_FILE = "auto_approve.json"


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

    def _auto_approve_path(self, project: Project) -> Path:
        """プロジェクトの Auto Approve 設定ファイルパスを返す."""
        return Path(project.path) / _AUTO_APPROVE_DIR / _AUTO_APPROVE_FILE

    def get_auto_approve_patterns(self, project: Project) -> list[str]:
        """
        プロジェクトの Auto Approve パターン一覧を取得する.

        Args:
            project: 対象プロジェクト

        Returns:
            Auto Approve パターンのリスト（未設定の場合は空リスト）
        """
        if not self._is_path_trusted(Path(project.path)):
            logger.error(
                "SECURITY: Attempted to read auto_approve outside trusted paths",
                project_path=project.path,
            )
            return []
        path = self._auto_approve_path(project)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [str(p) for p in data if isinstance(p, str)]
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            logger.warning(
                "Failed to read auto_approve.json", path=str(path), exc_info=True
            )
        return []

    def add_auto_approve_pattern(self, project: Project, pattern: str) -> bool:
        """
        プロジェクトに Auto Approve パターンを追加する.

        Args:
            project: 対象プロジェクト
            pattern: 追加するパターン（例: "Fetch:*"）

        Returns:
            新規追加された場合 True、既に存在していた場合 False

        Raises:
            ValueError: project.path が Trusted Path 配下にない場合、またはパターンが不正な場合
            OSError: ファイルへの書き込みに失敗した場合
        """
        if not self._is_path_trusted(Path(project.path)):
            logger.error(
                "SECURITY: Attempted to write auto_approve outside trusted paths",
                project_path=project.path,
            )
            msg = f"Project path is not within trusted paths: {project.path}"
            raise ValueError(msg)
        if not pattern or len(pattern) > 200:
            msg = f"Pattern must be 1-200 characters, got {len(pattern)}"
            raise ValueError(msg)
        if "\n" in pattern or "\r" in pattern:
            msg = "Pattern must not contain newlines"
            raise ValueError(msg)
        patterns = self.get_auto_approve_patterns(project)
        if pattern in patterns:
            return False
        patterns.append(pattern)
        path = self._auto_approve_path(project)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(patterns, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            logger.exception(
                "Failed to write auto_approve.json", path=str(path)
            )
            raise
        logger.info(
            "Added auto_approve pattern",
            project_path=project.path,
            pattern=pattern,
        )
        return True

    def remove_auto_approve_pattern(self, project: Project, pattern: str) -> bool:
        """
        プロジェクトから Auto Approve パターンを削除する.

        Args:
            project: 対象プロジェクト
            pattern: 削除するパターン

        Returns:
            削除された場合 True、見つからなかった場合 False

        Raises:
            ValueError: project.path が Trusted Path 配下にない場合
            OSError: ファイルへの書き込みに失敗した場合
        """
        if not self._is_path_trusted(Path(project.path)):
            logger.error(
                "SECURITY: Attempted to modify auto_approve outside trusted paths",
                project_path=project.path,
            )
            msg = f"Project path is not within trusted paths: {project.path}"
            raise ValueError(msg)
        patterns = self.get_auto_approve_patterns(project)
        if pattern not in patterns:
            return False
        patterns.remove(pattern)
        path = self._auto_approve_path(project)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(patterns, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            logger.exception(
                "Failed to write auto_approve.json", path=str(path)
            )
            raise
        logger.info(
            "Removed auto_approve pattern",
            project_path=project.path,
            pattern=pattern,
        )
        return True

    def is_auto_approved(
        self, project: Project, kind: str, raw_input: str
    ) -> str | None:
        """
        ツール呼び出しが Auto Approve パターンにマッチするか判定する.

        パターン形式: ``{kind_pattern}:{input_pattern}``
        - ``kind_pattern``: ツール種別の fnmatch パターン（大文字小文字無視）
        - ``input_pattern``: raw_input の fnmatch パターン（大文字小文字区別あり）
        - 注意: ``**`` は ``*`` と同様に全文字（パス区切り含む）にマッチします。
          fnmatch は ``**`` を再帰グロブとして解釈しません。
        - コロンなしのパターン（例: ``Bash``）は ``Bash:*`` と同等。
        - 例: ``Fetch:*``、``Read:/path/*``、``*:*``

        Args:
            project: 対象プロジェクト
            kind: ツール種別（例: "fetch", "read", "bash"）
            raw_input: ツール呼び出しの入力文字列

        Returns:
            マッチしたパターン文字列。マッチしない場合は None
        """
        patterns = self.get_auto_approve_patterns(project)
        for pattern in patterns:
            if ":" in pattern:
                kind_pat, input_pat = pattern.split(":", 1)
            else:
                kind_pat, input_pat = pattern, "*"
            if fnmatch.fnmatch(kind.lower(), kind_pat.lower()) and fnmatch.fnmatchcase(
                raw_input, input_pat
            ):
                return pattern
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
