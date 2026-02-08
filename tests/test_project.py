"""Tests for project management service."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

import pytest

from discord_acp_bridge.application.project import (
    Project,
    ProjectCreationError,
    ProjectNotFoundError,
    ProjectService,
)
from discord_acp_bridge.infrastructure.config import Config


@pytest.fixture
def temp_trusted_root(tmp_path: Path) -> Path:
    """Trusted Pathのルートディレクトリを作成する."""
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()
    return trusted_root


@pytest.fixture
def temp_project_dirs(temp_trusted_root: Path) -> list[Path]:
    """テスト用のプロジェクトディレクトリをTrusted Path配下に作成する."""
    dirs = [
        temp_trusted_root / "project1",
        temp_trusted_root / "project2",
        temp_trusted_root / "project3",
    ]
    for d in dirs:
        d.mkdir()
    return dirs


@pytest.fixture
def config_with_trusted_paths(
    temp_trusted_root: Path,
) -> Config:
    """Trusted Pathsが設定された設定を作成する."""
    config = Config(
        discord_bot_token="test_token",
        discord_guild_id=123456789,
        discord_allowed_user_id=987654321,
        trusted_paths=[str(temp_trusted_root)],
    )
    return config


@pytest.fixture
def config_empty() -> Config:
    """Trusted Pathsが空の設定を作成する."""
    config = Config(
        discord_bot_token="test_token",
        discord_guild_id=123456789,
        discord_allowed_user_id=987654321,
        trusted_paths=[],
    )
    return config


class TestProjectService:
    """ProjectServiceのテスト."""

    def test_list_projects_empty(self, config_empty: Config) -> None:
        """Trusted Pathsが空の場合のテスト."""
        service = ProjectService(config_empty)
        projects = service.list_projects()
        assert projects == []

    def test_list_projects_with_data(
        self,
        config_with_trusted_paths: Config,
        temp_project_dirs: list[Path],
    ) -> None:
        """プロジェクトが複数ある場合のテスト."""
        service = ProjectService(config_with_trusted_paths)
        projects = service.list_projects()

        assert len(projects) == 3
        # パス名でソートされる
        sorted_dirs = sorted(temp_project_dirs, key=lambda p: str(p))
        for idx, project in enumerate(projects):
            assert project.id == idx + 1
            assert project.path == str(sorted_dirs[idx])

    def test_list_projects_ignores_hidden_dirs(
        self,
        temp_trusted_root: Path,
    ) -> None:
        """隠しディレクトリを無視することを確認する."""
        # 通常のディレクトリと隠しディレクトリを作成
        (temp_trusted_root / "visible_project").mkdir()
        (temp_trusted_root / ".hidden_project").mkdir()

        config = Config(
            discord_bot_token="test_token",
            discord_guild_id=123456789,
            discord_allowed_user_id=987654321,
            trusted_paths=[str(temp_trusted_root)],
        )
        service = ProjectService(config)
        projects = service.list_projects()

        # 隠しディレクトリは含まれない
        assert len(projects) == 1
        assert projects[0].path == str(temp_trusted_root / "visible_project")

    def test_list_projects_nonexistent_trusted_path(
        self,
        tmp_path: Path,
    ) -> None:
        """存在しないTrusted Pathを指定した場合のテスト."""
        config = Config(
            discord_bot_token="test_token",
            discord_guild_id=123456789,
            discord_allowed_user_id=987654321,
            trusted_paths=[str(tmp_path / "nonexistent")],
        )
        service = ProjectService(config)
        projects = service.list_projects()

        # 警告ログが出力されるが、空のリストが返る
        assert projects == []

    def test_get_project_by_id_success(
        self,
        config_with_trusted_paths: Config,
        temp_project_dirs: list[Path],
    ) -> None:
        """プロジェクトIDでプロジェクトを取得できることを確認する."""
        service = ProjectService(config_with_trusted_paths)
        project = service.get_project_by_id(2)

        assert project.id == 2
        sorted_dirs = sorted(temp_project_dirs, key=lambda p: str(p))
        assert project.path == str(sorted_dirs[1])

    def test_get_project_by_id_not_found(
        self, config_with_trusted_paths: Config
    ) -> None:
        """存在しないIDを指定した場合のテスト."""
        service = ProjectService(config_with_trusted_paths)

        with pytest.raises(ProjectNotFoundError) as exc_info:
            service.get_project_by_id(999)

        assert exc_info.value.project_id == 999
        assert "Project #999 not found" in str(exc_info.value)

    def test_is_path_trusted_valid(
        self,
        config_with_trusted_paths: Config,
        temp_trusted_root: Path,
    ) -> None:
        """Trusted Path配下のパスが正しく検証されることを確認する."""
        service = ProjectService(config_with_trusted_paths)

        # Trusted Path配下のパス
        valid_path = temp_trusted_root / "some_project"
        assert service._is_path_trusted(valid_path) is True

    def test_is_path_trusted_invalid(
        self,
        config_with_trusted_paths: Config,
        tmp_path: Path,
    ) -> None:
        """Trusted Path配下にないパスが正しく検証されることを確認する."""
        service = ProjectService(config_with_trusted_paths)

        # Trusted Path外のパス
        invalid_path = tmp_path / "untrusted" / "project"
        assert service._is_path_trusted(invalid_path) is False

    def test_is_path_trusted_multiple_trusted_paths(
        self,
        tmp_path: Path,
    ) -> None:
        """複数のTrusted Pathsが設定されている場合のテスト."""
        trusted1 = tmp_path / "trusted1"
        trusted2 = tmp_path / "trusted2"
        trusted1.mkdir()
        trusted2.mkdir()

        config = Config(
            discord_bot_token="test_token",
            discord_guild_id=123456789,
            discord_allowed_user_id=987654321,
            trusted_paths=[str(trusted1), str(trusted2)],
        )
        service = ProjectService(config)

        # 両方のTrusted Path配下のパスが有効
        assert service._is_path_trusted(trusted1 / "project1") is True
        assert service._is_path_trusted(trusted2 / "project2") is True

        # それ以外は無効
        untrusted = tmp_path / "untrusted"
        assert service._is_path_trusted(untrusted / "project") is False


class TestProject:
    """Projectモデルのテスト."""

    def test_create_project(self) -> None:
        """Projectインスタンスの作成テスト."""
        project = Project(id=1, path="/path/to/project")
        assert project.id == 1
        assert project.path == "/path/to/project"


class TestProjectNotFoundError:
    """ProjectNotFoundErrorのテスト."""

    def test_error_message(self) -> None:
        """エラーメッセージのテスト."""
        error = ProjectNotFoundError(42)
        assert error.project_id == 42
        assert "Project #42 not found" in str(error)


class TestCreateProject:
    """create_projectメソッドのテスト."""

    def test_create_project_success(
        self,
        config_with_trusted_paths: Config,
        temp_trusted_root: Path,
    ) -> None:
        """正常にプロジェクトを作成できることを確認する."""
        service = ProjectService(config_with_trusted_paths)
        project = service.create_project("new_project")

        assert project.path == str(temp_trusted_root / "new_project")
        assert (temp_trusted_root / "new_project").is_dir()

    def test_create_project_returns_correct_id(
        self,
        config_with_trusted_paths: Config,
        temp_trusted_root: Path,
        temp_project_dirs: list[Path],
    ) -> None:
        """作成後のプロジェクトIDがソート順で正しく割り当てられることを確認する."""
        service = ProjectService(config_with_trusted_paths)
        # 既存: project1, project2, project3
        # "aaa_project" はソート順で最初になる
        project = service.create_project("aaa_project")

        assert project.id == 1
        assert project.path == str(temp_trusted_root / "aaa_project")

    def test_create_project_strips_whitespace(
        self,
        config_with_trusted_paths: Config,
        temp_trusted_root: Path,
    ) -> None:
        """前後の空白がトリムされることを確認する."""
        service = ProjectService(config_with_trusted_paths)
        project = service.create_project("  my_project  ")

        assert project.path == str(temp_trusted_root / "my_project")
        assert (temp_trusted_root / "my_project").is_dir()

    def test_create_project_empty_name(
        self,
        config_with_trusted_paths: Config,
    ) -> None:
        """空の名前でエラーになることを確認する."""
        service = ProjectService(config_with_trusted_paths)

        with pytest.raises(ProjectCreationError, match="プロジェクト名を指定"):
            service.create_project("")

    def test_create_project_whitespace_only_name(
        self,
        config_with_trusted_paths: Config,
    ) -> None:
        """空白のみの名前でエラーになることを確認する."""
        service = ProjectService(config_with_trusted_paths)

        with pytest.raises(ProjectCreationError, match="プロジェクト名を指定"):
            service.create_project("   ")

    def test_create_project_path_traversal_slash(
        self,
        config_with_trusted_paths: Config,
    ) -> None:
        """パストラバーサル（/）でエラーになることを確認する."""
        service = ProjectService(config_with_trusted_paths)

        with pytest.raises(ProjectCreationError, match="パス区切り文字"):
            service.create_project("../escape")

    def test_create_project_path_traversal_backslash(
        self,
        config_with_trusted_paths: Config,
    ) -> None:
        """パストラバーサル（\\）でエラーになることを確認する."""
        service = ProjectService(config_with_trusted_paths)

        with pytest.raises(ProjectCreationError, match="パス区切り文字"):
            service.create_project("..\\escape")

    def test_create_project_hidden_directory(
        self,
        config_with_trusted_paths: Config,
    ) -> None:
        """隠しディレクトリ名でエラーになることを確認する."""
        service = ProjectService(config_with_trusted_paths)

        with pytest.raises(ProjectCreationError, match="`.`"):
            service.create_project(".hidden")

    def test_create_project_already_exists(
        self,
        config_with_trusted_paths: Config,
        temp_trusted_root: Path,
    ) -> None:
        """既存のディレクトリ名でエラーになることを確認する."""
        (temp_trusted_root / "existing").mkdir()
        service = ProjectService(config_with_trusted_paths)

        with pytest.raises(ProjectCreationError, match="既に存在します"):
            service.create_project("existing")

    def test_create_project_no_trusted_paths(
        self,
        config_empty: Config,
    ) -> None:
        """Trusted Pathsが空でエラーになることを確認する."""
        service = ProjectService(config_empty)

        with pytest.raises(ProjectCreationError, match="Trusted Paths"):
            service.create_project("any_project")

    def test_create_project_null_byte_in_name(
        self,
        config_with_trusted_paths: Config,
    ) -> None:
        """ヌルバイトを含む名前でエラーになることを確認する."""
        service = ProjectService(config_with_trusted_paths)

        with pytest.raises(ProjectCreationError, match="パス区切り文字"):
            service.create_project("bad\0name")

    def test_create_project_nonexistent_trusted_path(
        self,
        tmp_path: Path,
    ) -> None:
        """Trusted Pathが存在しない場合にエラーになることを確認する."""
        config = Config(
            discord_bot_token="test_token",
            discord_guild_id=123456789,
            discord_allowed_user_id=987654321,
            trusted_paths=[str(tmp_path / "nonexistent")],
        )
        service = ProjectService(config)

        with pytest.raises(ProjectCreationError, match="Trusted Pathが存在しません"):
            service.create_project("new_project")


class TestProjectCreationError:
    """ProjectCreationErrorのテスト."""

    def test_error_message(self) -> None:
        """エラーメッセージのテスト."""
        error = ProjectCreationError("test error")
        assert str(error) == "test error"
