"""Tests for project management service."""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003

import pytest

from discord_acp_bridge.application.project import (
    Project,
    ProjectNotFoundError,
    ProjectService,
)
from discord_acp_bridge.infrastructure.config import Config


@pytest.fixture
def temp_projects_file(tmp_path: Path) -> Path:
    """一時的なプロジェクト設定ファイルを作成する."""
    return tmp_path / "projects.json"


@pytest.fixture
def temp_project_dirs(tmp_path: Path) -> list[Path]:
    """テスト用のプロジェクトディレクトリを作成する."""
    dirs = [
        tmp_path / "project1",
        tmp_path / "project2",
        tmp_path / "project3",
    ]
    for d in dirs:
        d.mkdir()
    return dirs


@pytest.fixture
def config_with_projects(
    temp_projects_file: Path,
    temp_project_dirs: list[Path],
) -> Config:
    """プロジェクトが登録された設定を作成する."""
    # プロジェクト設定ファイルを作成
    projects = [str(d) for d in temp_project_dirs]
    temp_projects_file.write_text(json.dumps(projects, indent=2), encoding="utf-8")

    # Configインスタンスを作成（環境変数はモック）
    config = Config(
        discord_bot_token="test_token",
        discord_guild_id=123456789,
        discord_allowed_user_id=987654321,
        projects_file=temp_projects_file,
    )
    return config


@pytest.fixture
def config_empty(temp_projects_file: Path) -> Config:
    """プロジェクトが登録されていない設定を作成する."""
    config = Config(
        discord_bot_token="test_token",
        discord_guild_id=123456789,
        discord_allowed_user_id=987654321,
        projects_file=temp_projects_file,
    )
    return config


class TestProjectService:
    """ProjectServiceのテスト."""

    def test_list_projects_empty(self, config_empty: Config) -> None:
        """プロジェクトが空の場合のテスト."""
        service = ProjectService(config_empty)
        projects = service.list_projects()
        assert projects == []

    def test_list_projects_with_data(
        self,
        config_with_projects: Config,
        temp_project_dirs: list[Path],
    ) -> None:
        """プロジェクトが複数ある場合のテスト."""
        service = ProjectService(config_with_projects)
        projects = service.list_projects()

        assert len(projects) == 3
        for idx, project in enumerate(projects):
            assert project.id == idx + 1
            assert project.path == str(temp_project_dirs[idx])
            assert project.is_active is False

    def test_list_projects_with_active(
        self,
        config_with_projects: Config,
        temp_project_dirs: list[Path],
    ) -> None:
        """アクティブなプロジェクトがある場合のテスト."""
        service = ProjectService(config_with_projects)
        service.switch_project(2)

        projects = service.list_projects()

        assert len(projects) == 3
        assert projects[0].is_active is False
        assert projects[1].is_active is True
        assert projects[2].is_active is False

    def test_get_active_project_none(self, config_with_projects: Config) -> None:
        """アクティブなプロジェクトがない場合のテスト."""
        service = ProjectService(config_with_projects)
        active = service.get_active_project()
        assert active is None

    def test_get_active_project_exists(
        self,
        config_with_projects: Config,
        temp_project_dirs: list[Path],
    ) -> None:
        """アクティブなプロジェクトがある場合のテスト."""
        service = ProjectService(config_with_projects)
        service.switch_project(2)

        active = service.get_active_project()

        assert active is not None
        assert active.id == 2
        assert active.path == str(temp_project_dirs[1])
        assert active.is_active is True

    def test_get_active_project_invalid_id(
        self,
        config_with_projects: Config,
    ) -> None:
        """アクティブIDが設定されているが、リストに存在しない場合のテスト."""
        service = ProjectService(config_with_projects)
        # 強制的に無効なIDを設定
        service._active_project_id = 999

        active = service.get_active_project()

        # 無効なIDの場合、Noneが返り、内部状態もリセットされる
        assert active is None
        assert service._active_project_id is None

    def test_switch_project_success(
        self,
        config_with_projects: Config,
        temp_project_dirs: list[Path],
    ) -> None:
        """プロジェクトの切り替えが成功するテスト."""
        service = ProjectService(config_with_projects)
        project = service.switch_project(2)

        assert project.id == 2
        assert project.path == str(temp_project_dirs[1])
        assert project.is_active is True
        assert service._active_project_id == 2

    def test_switch_project_not_found(self, config_with_projects: Config) -> None:
        """存在しないIDを指定した場合のテスト."""
        service = ProjectService(config_with_projects)

        with pytest.raises(ProjectNotFoundError) as exc_info:
            service.switch_project(999)

        assert exc_info.value.project_id == 999
        assert "Project #999 not found" in str(exc_info.value)

    def test_add_project_success(
        self,
        config_empty: Config,
        tmp_path: Path,
    ) -> None:
        """プロジェクトの追加が成功するテスト."""
        service = ProjectService(config_empty)
        new_dir = tmp_path / "new_project"
        new_dir.mkdir()

        project = service.add_project(str(new_dir))

        assert project.id == 1
        assert project.path == str(new_dir.resolve())
        assert project.is_active is False

        # 設定ファイルに保存されていることを確認
        projects = config_empty.load_projects()
        assert len(projects) == 1
        assert projects[0] == str(new_dir.resolve())

    def test_add_project_multiple(
        self,
        config_empty: Config,
        tmp_path: Path,
    ) -> None:
        """複数のプロジェクトを追加するテスト."""
        service = ProjectService(config_empty)

        # 1つ目を追加
        dir1 = tmp_path / "project1"
        dir1.mkdir()
        project1 = service.add_project(str(dir1))
        assert project1.id == 1

        # 2つ目を追加
        dir2 = tmp_path / "project2"
        dir2.mkdir()
        project2 = service.add_project(str(dir2))
        assert project2.id == 2

        # 設定ファイルを確認
        projects = config_empty.load_projects()
        assert len(projects) == 2

    def test_add_project_not_exists(self, config_empty: Config) -> None:
        """存在しないパスを指定した場合のテスト."""
        service = ProjectService(config_empty)

        with pytest.raises(ValueError, match=r"does not exist"):
            service.add_project("/path/that/does/not/exist")

    def test_add_project_not_directory(
        self,
        config_empty: Config,
        tmp_path: Path,
    ) -> None:
        """ディレクトリでないパスを指定した場合のテスト."""
        service = ProjectService(config_empty)
        file_path = tmp_path / "file.txt"
        file_path.write_text("test")

        with pytest.raises(ValueError, match=r"not a directory"):
            service.add_project(str(file_path))

    def test_add_project_duplicate(
        self,
        config_with_projects: Config,
        temp_project_dirs: list[Path],
    ) -> None:
        """既に登録済みのパスを指定した場合のテスト."""
        service = ProjectService(config_with_projects)

        # 既存のプロジェクトを再度追加
        project = service.add_project(str(temp_project_dirs[0]))

        # 既存のプロジェクト情報が返される
        assert project.id == 1
        assert project.path == str(temp_project_dirs[0])

        # プロジェクト数は変わらない
        projects = config_with_projects.load_projects()
        assert len(projects) == 3

    def test_add_project_with_active(
        self,
        config_with_projects: Config,
        tmp_path: Path,
    ) -> None:
        """アクティブなプロジェクトがある状態での追加テスト."""
        service = ProjectService(config_with_projects)
        service.switch_project(2)

        # 新しいプロジェクトを追加
        new_dir = tmp_path / "new_project"
        new_dir.mkdir()
        project = service.add_project(str(new_dir))

        # 新しいプロジェクトはアクティブでない
        assert project.is_active is False

        # 既存のアクティブなプロジェクトは変わらない
        active = service.get_active_project()
        assert active is not None
        assert active.id == 2


class TestProject:
    """Projectモデルのテスト."""

    def test_create_project(self) -> None:
        """Projectインスタンスの作成テスト."""
        project = Project(id=1, path="/path/to/project", is_active=False)
        assert project.id == 1
        assert project.path == "/path/to/project"
        assert project.is_active is False

    def test_project_default_active(self) -> None:
        """is_activeのデフォルト値のテスト."""
        project = Project(id=1, path="/path/to/project")
        assert project.is_active is False


class TestProjectNotFoundError:
    """ProjectNotFoundErrorのテスト."""

    def test_error_message(self) -> None:
        """エラーメッセージのテスト."""
        error = ProjectNotFoundError(42)
        assert error.project_id == 42
        assert "Project #42 not found" in str(error)
