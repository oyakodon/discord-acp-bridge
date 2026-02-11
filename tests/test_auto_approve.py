"""Tests for project Auto Approve functionality (FTR-001)."""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from collections.abc import Generator

import pytest

from discord_acp_bridge.application.project import (
    Project,
    ProjectService,
)
from discord_acp_bridge.application.session import (
    SessionService,
    _targets_acp_bridge_dir,
)
from discord_acp_bridge.infrastructure.config import Config


@pytest.fixture
def temp_trusted_root(tmp_path: Path) -> Path:
    """Trusted Pathのルートディレクトリを作成する."""
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()
    return trusted_root


@pytest.fixture
def project(temp_trusted_root: Path) -> Project:
    """テスト用のProjectインスタンスを作成する."""
    project_dir = temp_trusted_root / "test_project"
    project_dir.mkdir()
    return Project(id=1, path=str(project_dir))


@pytest.fixture
def config(temp_trusted_root: Path) -> Config:
    """テスト用のConfigインスタンスを作成する."""
    return Config(
        discord_bot_token="test_token",
        discord_guild_id=123456789,
        discord_allowed_user_id=987654321,
        trusted_paths=[str(temp_trusted_root)],
    )


@pytest.fixture
def project_service(config: Config) -> ProjectService:
    """テスト用のProjectServiceインスタンスを作成する."""
    return ProjectService(config)


@pytest.fixture
def mock_acp_client() -> Generator[MagicMock, None, None]:
    """ACPClientのモックを作成する."""
    with patch("discord_acp_bridge.application.session.ACPClient") as mock:
        instance = MagicMock()
        instance.initialize = AsyncMock(return_value="test_acp_session_id")
        instance.send_prompt = AsyncMock()
        instance.cancel_session = AsyncMock()
        instance.close = AsyncMock()
        instance.get_available_models = MagicMock(return_value=[])
        instance.get_current_model = MagicMock(return_value=None)
        mock.return_value = instance
        yield mock


class TestAutoApprovePatterns:
    """ProjectService の Auto Approve パターン管理テスト."""

    def test_get_patterns_no_file(
        self, project_service: ProjectService, project: Project
    ) -> None:
        """設定ファイルが存在しない場合は空リストを返す."""
        patterns = project_service.get_auto_approve_patterns(project)
        assert patterns == []

    def test_add_pattern(
        self, project_service: ProjectService, project: Project
    ) -> None:
        """パターンを追加できる."""
        added = project_service.add_auto_approve_pattern(project, "Fetch:*")
        assert added is True

        patterns = project_service.get_auto_approve_patterns(project)
        assert patterns == ["Fetch:*"]

    def test_add_pattern_duplicate(
        self, project_service: ProjectService, project: Project
    ) -> None:
        """同じパターンを二重登録しても重複しない."""
        project_service.add_auto_approve_pattern(project, "Fetch:*")
        added = project_service.add_auto_approve_pattern(project, "Fetch:*")
        assert added is False

        patterns = project_service.get_auto_approve_patterns(project)
        assert patterns == ["Fetch:*"]

    def test_add_multiple_patterns(
        self, project_service: ProjectService, project: Project
    ) -> None:
        """複数のパターンを追加できる."""
        project_service.add_auto_approve_pattern(project, "Fetch:*")
        project_service.add_auto_approve_pattern(project, "Read:/path/**")
        project_service.add_auto_approve_pattern(project, "Bash:*")

        patterns = project_service.get_auto_approve_patterns(project)
        assert len(patterns) == 3
        assert "Fetch:*" in patterns
        assert "Read:/path/**" in patterns
        assert "Bash:*" in patterns

    def test_remove_pattern(
        self, project_service: ProjectService, project: Project
    ) -> None:
        """パターンを削除できる."""
        project_service.add_auto_approve_pattern(project, "Fetch:*")
        project_service.add_auto_approve_pattern(project, "Read:*")

        removed = project_service.remove_auto_approve_pattern(project, "Fetch:*")
        assert removed is True

        patterns = project_service.get_auto_approve_patterns(project)
        assert patterns == ["Read:*"]

    def test_remove_pattern_not_found(
        self, project_service: ProjectService, project: Project
    ) -> None:
        """存在しないパターンの削除は False を返す."""
        removed = project_service.remove_auto_approve_pattern(project, "Fetch:*")
        assert removed is False

    def test_patterns_persist(
        self, project_service: ProjectService, project: Project
    ) -> None:
        """パターンがファイルに永続化される."""
        project_service.add_auto_approve_pattern(project, "Fetch:*")

        # ファイルが存在することを確認
        config_file = Path(project.path) / ".acp-bridge" / "auto_approve.json"
        assert config_file.exists()

        data = json.loads(config_file.read_text(encoding="utf-8"))
        assert data == ["Fetch:*"]

    def test_get_patterns_invalid_file(
        self, project_service: ProjectService, project: Project
    ) -> None:
        """壊れたJSONファイルがあっても空リストを返す."""
        config_dir = Path(project.path) / ".acp-bridge"
        config_dir.mkdir(exist_ok=True)
        config_file = config_dir / "auto_approve.json"
        config_file.write_text("invalid json", encoding="utf-8")

        patterns = project_service.get_auto_approve_patterns(project)
        assert patterns == []


class TestIsAutoApproved:
    """ProjectService.is_auto_approved のテスト."""

    def test_no_patterns_not_approved(
        self, project_service: ProjectService, project: Project
    ) -> None:
        """パターンがない場合は自動承認しない."""
        assert project_service.is_auto_approved(project, "fetch", "") is None

    def test_exact_kind_match(
        self, project_service: ProjectService, project: Project
    ) -> None:
        """ツール種別が完全一致（大文字小文字無視）する場合は承認する."""
        project_service.add_auto_approve_pattern(project, "Fetch:*")

        assert project_service.is_auto_approved(project, "fetch", "https://example.com") == "Fetch:*"
        assert project_service.is_auto_approved(project, "FETCH", "https://example.com") == "Fetch:*"
        assert project_service.is_auto_approved(project, "read", "/path/file.txt") is None

    def test_wildcard_kind(
        self, project_service: ProjectService, project: Project
    ) -> None:
        """`*:*` パターンは全てのリクエストにマッチする."""
        project_service.add_auto_approve_pattern(project, "*:*")

        assert project_service.is_auto_approved(project, "fetch", "https://example.com") == "*:*"
        assert project_service.is_auto_approved(project, "bash", "ls -la") == "*:*"
        assert project_service.is_auto_approved(project, "read", "/etc/passwd") == "*:*"

    def test_input_pattern_match(
        self, project_service: ProjectService, project: Project
    ) -> None:
        """入力パターンの glob マッチング."""
        project_service.add_auto_approve_pattern(project, "Read:/trusted/**")

        assert (
            project_service.is_auto_approved(project, "read", "/trusted/project/file.py")
            == "Read:/trusted/**"
        )
        assert project_service.is_auto_approved(project, "read", "/untrusted/file.py") is None

    def test_pattern_without_colon(
        self, project_service: ProjectService, project: Project
    ) -> None:
        """コロンなしのパターンはツール種別のみでマッチする（入力は *）."""
        project_service.add_auto_approve_pattern(project, "Bash")

        assert project_service.is_auto_approved(project, "bash", "ls -la") == "Bash"
        assert project_service.is_auto_approved(project, "bash", "rm -rf /") == "Bash"
        assert project_service.is_auto_approved(project, "fetch", "https://example.com") is None

    def test_input_case_sensitive(
        self, project_service: ProjectService, project: Project
    ) -> None:
        """raw_input のマッチングは大文字小文字を区別する（fnmatchcase）."""
        project_service.add_auto_approve_pattern(project, "Read:/path/File.py")

        # 完全一致はマッチ
        assert (
            project_service.is_auto_approved(project, "read", "/path/File.py")
            == "Read:/path/File.py"
        )
        # 大文字小文字が異なる場合はマッチしない
        assert project_service.is_auto_approved(project, "read", "/path/file.py") is None

    def test_multiple_patterns_any_match(
        self, project_service: ProjectService, project: Project
    ) -> None:
        """複数パターンのいずれかにマッチすれば承認する（最初にマッチしたパターンを返す）."""
        project_service.add_auto_approve_pattern(project, "Fetch:*")
        project_service.add_auto_approve_pattern(project, "Read:/safe/**")

        assert project_service.is_auto_approved(project, "fetch", "https://example.com") == "Fetch:*"
        assert (
            project_service.is_auto_approved(project, "read", "/safe/file.txt") == "Read:/safe/**"
        )
        assert project_service.is_auto_approved(project, "bash", "ls") is None


class TestSessionServiceAutoApprove:
    """SessionService の Auto Approve 統合テスト."""

    @pytest.mark.asyncio
    async def test_permission_auto_approved_by_pattern(
        self,
        config: Config,
        project: Project,
        project_service: ProjectService,
        mock_acp_client: MagicMock,
    ) -> None:
        """Auto Approve パターンにマッチした場合、Discord UI を呼ばずに自動承認する."""
        from acp.schema import PermissionOption

        # パターンを設定
        project_service.add_auto_approve_pattern(project, "Fetch:*")

        # コールバックモック（呼ばれないはず）
        permission_callback = AsyncMock()

        service = SessionService(
            config,
            project_service=project_service,
            on_permission_request=permission_callback,
        )

        # セッションを作成
        session = await service.create_session(
            user_id=123, project=project, thread_id=456
        )

        # PermissionOption モック
        option = MagicMock(spec=PermissionOption)
        option.option_id = "opt_1"
        option.name = "Allow"
        option.kind = "allow_always"

        # ToolCallUpdate モック
        tool_call = MagicMock()
        tool_call.tool_call_id = "tc_1"
        tool_call.title = "Fetch"
        tool_call.kind = "fetch"
        tool_call.raw_input = "https://example.com"
        tool_call.content = None

        # _handle_permission_request を直接呼び出す
        assert session.acp_session_id is not None
        result = await service._handle_permission_request(
            session.acp_session_id, [option], tool_call
        )

        # Discord UI は呼ばれていない
        permission_callback.assert_not_called()

        # 自動承認されていることを確認
        from acp.schema import AllowedOutcome
        assert isinstance(result.outcome, AllowedOutcome)

    @pytest.mark.asyncio
    async def test_permission_not_auto_approved_when_no_match(
        self,
        config: Config,
        project: Project,
        project_service: ProjectService,
        mock_acp_client: MagicMock,
    ) -> None:
        """Auto Approve パターンにマッチしない場合、Discord UI に委譲する."""
        from acp.schema import PermissionOption

        from discord_acp_bridge.application.models import PermissionResponse

        # Fetch のみをパターンに設定
        project_service.add_auto_approve_pattern(project, "Fetch:*")

        # コールバックモック（呼ばれるはず）
        permission_callback = AsyncMock(
            return_value=PermissionResponse(approved=True, option_id="opt_1")
        )

        service = SessionService(
            config,
            project_service=project_service,
            on_permission_request=permission_callback,
        )

        session = await service.create_session(
            user_id=123, project=project, thread_id=456
        )

        option = MagicMock(spec=PermissionOption)
        option.option_id = "opt_1"
        option.name = "Allow"
        option.kind = "allow_always"

        tool_call = MagicMock()
        tool_call.tool_call_id = "tc_1"
        tool_call.title = "Bash"
        tool_call.kind = "bash"  # Fetch ではないのでマッチしない
        tool_call.raw_input = "ls -la"
        tool_call.content = None

        assert session.acp_session_id is not None
        await service._handle_permission_request(
            session.acp_session_id, [option], tool_call
        )

        # Discord UI が呼ばれていることを確認
        permission_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_permission_no_project_service(
        self,
        config: Config,
        project: Project,
        mock_acp_client: MagicMock,
    ) -> None:
        """project_service が None の場合は通常のフローを使用する."""
        from acp.schema import PermissionOption

        from discord_acp_bridge.application.models import PermissionResponse

        permission_callback = AsyncMock(
            return_value=PermissionResponse(approved=True, option_id="opt_1")
        )

        service = SessionService(
            config,
            project_service=None,  # project_service なし
            on_permission_request=permission_callback,
        )

        session = await service.create_session(
            user_id=123, project=project, thread_id=456
        )

        option = MagicMock(spec=PermissionOption)
        option.option_id = "opt_1"
        option.name = "Allow"
        option.kind = "allow_always"

        tool_call = MagicMock()
        tool_call.tool_call_id = "tc_1"
        tool_call.title = "Fetch"
        tool_call.kind = "fetch"
        tool_call.raw_input = "https://example.com"
        tool_call.content = None

        assert session.acp_session_id is not None
        await service._handle_permission_request(
            session.acp_session_id, [option], tool_call
        )

        # project_service がない場合は Discord UI に委譲する
        permission_callback.assert_called_once()


class TestTargetsAcpBridgeDir:
    """_targets_acp_bridge_dir ヘルパー関数のテスト."""

    def test_unix_path(self) -> None:
        """Unix形式のパスで .acp-bridge/ を検出する."""
        assert _targets_acp_bridge_dir("/project/.acp-bridge/auto_approve.json") is True

    def test_windows_path(self) -> None:
        """Windows形式のパスで .acp-bridge/ を検出する."""
        assert (
            _targets_acp_bridge_dir(
                "C:\\Users\\user\\project\\.acp-bridge\\auto_approve.json"
            )
            is True
        )

    def test_relative_path(self) -> None:
        """相対パスで .acp-bridge/ を検出する."""
        assert _targets_acp_bridge_dir(".acp-bridge/auto_approve.json") is True

    def test_directory_without_trailing_slash(self) -> None:
        """末尾スラッシュなし（ディレクトリ自体への操作）を検出する."""
        assert _targets_acp_bridge_dir("/project/.acp-bridge") is True
        assert _targets_acp_bridge_dir(".acp-bridge") is True

    def test_bash_command_with_space(self) -> None:
        """bash コマンド内のパス（空白区切り）を検出する."""
        assert _targets_acp_bridge_dir("rm -rf .acp-bridge") is True
        assert _targets_acp_bridge_dir("ls /project/.acp-bridge") is True

    def test_quoted_path(self) -> None:
        """引用符で囲まれたパスを検出する."""
        assert _targets_acp_bridge_dir('cat ".acp-bridge/auto_approve.json"') is True
        assert _targets_acp_bridge_dir("cat '.acp-bridge/auto_approve.json'") is True

    def test_no_false_positive_similar_name(self) -> None:
        """類似名を誤検出しない."""
        assert _targets_acp_bridge_dir("/project/acp-bridge/file.txt") is False
        assert _targets_acp_bridge_dir("/project/.acp-bridge-old/file.txt") is False

    def test_no_false_positive_normal_path(self) -> None:
        """通常のパスを誤検出しない."""
        assert _targets_acp_bridge_dir("/project/src/main.py") is False
        assert _targets_acp_bridge_dir("echo hello") is False

    def test_json_containing_path(self) -> None:
        """JSON文字列内のパスを検出する."""
        json_input = '{"file_path": "/project/.acp-bridge/auto_approve.json"}'
        assert _targets_acp_bridge_dir(json_input) is True

    def test_empty_string(self) -> None:
        """空文字列はFalseを返す."""
        assert _targets_acp_bridge_dir("") is False


class TestAcpBridgeProtection:
    """.acp-bridge/ ディレクトリへの操作は Auto Approve をバイパスするテスト."""

    @pytest.mark.asyncio
    async def test_acp_bridge_target_bypasses_auto_approve(
        self,
        config: Config,
        project: Project,
        project_service: ProjectService,
        mock_acp_client: MagicMock,
    ) -> None:
        """*:* パターンがあっても .acp-bridge/ 操作は Discord UI に委譲される."""
        from discord_acp_bridge.application.models import PermissionResponse

        # 全許可パターンを設定
        project_service.add_auto_approve_pattern(project, "*:*")

        # コールバックモック（呼ばれるはず）
        permission_callback = AsyncMock(
            return_value=PermissionResponse(approved=True, option_id="opt_1")
        )

        service = SessionService(
            config,
            project_service=project_service,
            on_permission_request=permission_callback,
        )

        session = await service.create_session(
            user_id=123, project=project, thread_id=456
        )

        option = MagicMock()
        option.option_id = "opt_1"
        option.kind = "allow_always"
        option.name = "Allow Always"

        tool_call = MagicMock()
        tool_call.tool_call_id = "tc_1"
        tool_call.title = "Write"
        tool_call.kind = "write"
        tool_call.raw_input = f"{project.path}/.acp-bridge/auto_approve.json"
        tool_call.content = None

        assert session.acp_session_id is not None
        await service._handle_permission_request(
            session.acp_session_id, [option], tool_call
        )

        # .acp-bridge/ 操作は Discord UI に委譲される
        permission_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_acp_bridge_target_auto_approved(
        self,
        config: Config,
        project: Project,
        project_service: ProjectService,
        mock_acp_client: MagicMock,
    ) -> None:
        """通常のパスは Auto Approve パターンで自動承認される."""
        # 全許可パターンを設定
        project_service.add_auto_approve_pattern(project, "*:*")

        # コールバックモック（呼ばれないはず）
        permission_callback = AsyncMock()

        service = SessionService(
            config,
            project_service=project_service,
            on_permission_request=permission_callback,
        )

        session = await service.create_session(
            user_id=123, project=project, thread_id=456
        )

        option = MagicMock()
        option.option_id = "opt_1"
        option.kind = "allow_always"
        option.name = "Allow Always"

        tool_call = MagicMock()
        tool_call.tool_call_id = "tc_1"
        tool_call.title = "Read"
        tool_call.kind = "read"
        tool_call.raw_input = f"{project.path}/src/main.py"
        tool_call.content = None

        assert session.acp_session_id is not None
        result = await service._handle_permission_request(
            session.acp_session_id, [option], tool_call
        )

        # 通常のパスは自動承認される
        permission_callback.assert_not_called()
        from acp.schema import AllowedOutcome

        assert isinstance(result.outcome, AllowedOutcome)


class TestAutoApprovePatternSaving:
    """「常に承認」応答時のパターン自動保存テスト."""

    @pytest.mark.asyncio
    async def test_always_approve_saves_pattern(
        self,
        config: Config,
        project: Project,
        project_service: ProjectService,
        mock_acp_client: MagicMock,
    ) -> None:
        """「常に承認」応答時にパターンが auto_approve.json に保存される."""
        from discord_acp_bridge.application.models import PermissionResponse

        # コールバック: auto_approve_pattern 付きの応答を返す
        permission_callback = AsyncMock(
            return_value=PermissionResponse(
                approved=True,
                option_id="opt_1",
                auto_approve_pattern="fetch:https://example.com",
            )
        )

        service = SessionService(
            config,
            project_service=project_service,
            on_permission_request=permission_callback,
        )

        session = await service.create_session(
            user_id=123, project=project, thread_id=456
        )

        option = MagicMock()
        option.option_id = "opt_1"
        option.kind = "allow_always"
        option.name = "Allow Always"

        tool_call = MagicMock()
        tool_call.tool_call_id = "tc_1"
        tool_call.title = "Fetch"
        tool_call.kind = "fetch"
        tool_call.raw_input = "https://example.com"
        tool_call.content = None

        assert session.acp_session_id is not None
        await service._handle_permission_request(
            session.acp_session_id, [option], tool_call
        )

        # パターンが保存されていることを確認
        patterns = project_service.get_auto_approve_patterns(project)
        assert "fetch:https://example.com" in patterns

    @pytest.mark.asyncio
    async def test_single_approve_does_not_save_pattern(
        self,
        config: Config,
        project: Project,
        project_service: ProjectService,
        mock_acp_client: MagicMock,
    ) -> None:
        """「承認」応答（auto_approve_pattern=None）ではパターンが保存されない."""
        from discord_acp_bridge.application.models import PermissionResponse

        # コールバック: auto_approve_pattern なしの応答を返す
        permission_callback = AsyncMock(
            return_value=PermissionResponse(
                approved=True,
                option_id="opt_1",
                auto_approve_pattern=None,
            )
        )

        service = SessionService(
            config,
            project_service=project_service,
            on_permission_request=permission_callback,
        )

        session = await service.create_session(
            user_id=123, project=project, thread_id=456
        )

        option = MagicMock()
        option.option_id = "opt_1"
        option.kind = "allow_once"
        option.name = "Allow Once"

        tool_call = MagicMock()
        tool_call.tool_call_id = "tc_1"
        tool_call.title = "Fetch"
        tool_call.kind = "fetch"
        tool_call.raw_input = "https://example.com"
        tool_call.content = None

        assert session.acp_session_id is not None
        await service._handle_permission_request(
            session.acp_session_id, [option], tool_call
        )

        # パターンが保存されていないことを確認
        patterns = project_service.get_auto_approve_patterns(project)
        assert patterns == []

    @pytest.mark.asyncio
    async def test_pattern_save_failure_does_not_block_response(
        self,
        config: Config,
        project: Project,
        mock_acp_client: MagicMock,
    ) -> None:
        """パターン保存失敗時も ACP 応答はブロックされない."""
        from discord_acp_bridge.application.models import PermissionResponse

        # add_auto_approve_pattern が例外を投げるモック
        mock_project_service = MagicMock(spec=ProjectService)
        mock_project_service.is_auto_approved.return_value = None
        mock_project_service.add_auto_approve_pattern.side_effect = OSError(
            "disk full"
        )

        permission_callback = AsyncMock(
            return_value=PermissionResponse(
                approved=True,
                option_id="opt_1",
                auto_approve_pattern="fetch:https://example.com",
            )
        )

        service = SessionService(
            config,
            project_service=mock_project_service,
            on_permission_request=permission_callback,
        )

        session = await service.create_session(
            user_id=123, project=project, thread_id=456
        )

        option = MagicMock()
        option.option_id = "opt_1"
        option.kind = "allow_always"
        option.name = "Allow Always"

        tool_call = MagicMock()
        tool_call.tool_call_id = "tc_1"
        tool_call.title = "Fetch"
        tool_call.kind = "fetch"
        tool_call.raw_input = "https://example.com"
        tool_call.content = None

        assert session.acp_session_id is not None

        # 例外が発生しても ACP 応答は正常に返る
        from acp.schema import AllowedOutcome

        result = await service._handle_permission_request(
            session.acp_session_id, [option], tool_call
        )
        assert isinstance(result.outcome, AllowedOutcome)
