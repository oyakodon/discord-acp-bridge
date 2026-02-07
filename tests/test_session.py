"""Tests for session management service."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator

from discord_acp_bridge.application.project import Project
from discord_acp_bridge.application.session import (
    ACPConnectionError,
    Session,
    SessionNotFoundError,
    SessionService,
    SessionState,
    SessionStateError,
)
from discord_acp_bridge.infrastructure.config import Config


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """テスト用のConfigインスタンスを作成する."""
    config = Config(
        discord_bot_token="test_token",
        discord_guild_id=123456789,
        discord_allowed_user_id=987654321,
        projects_file=tmp_path / "projects.json",
    )
    return config


@pytest.fixture
def project(tmp_path: Path) -> Project:
    """テスト用のProjectインスタンスを作成する."""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    return Project(id=1, path=str(project_dir), is_active=True)


@pytest.fixture
def mock_acp_client() -> Generator[MagicMock, None, None]:
    """ACPClientのモックを作成する."""
    with patch("discord_acp_bridge.application.session.ACPClient") as mock:
        # ACPClientのメソッドをモック化
        instance = MagicMock()
        instance.initialize = AsyncMock(return_value="test_acp_session_id")
        instance.send_prompt = AsyncMock()
        instance.cancel_session = AsyncMock()
        instance.close = AsyncMock()
        instance.set_session_model = AsyncMock()
        instance.get_available_models = MagicMock(
            return_value=[
                "claude-sonnet-4-5",
                "claude-opus-4-6",
                "claude-haiku-4-5",
            ]
        )
        instance.get_current_model = MagicMock(return_value="claude-sonnet-4-5")
        mock.return_value = instance
        yield mock


class TestSession:
    """Sessionモデルのテスト."""

    def test_create_session(self, project: Project) -> None:
        """Sessionインスタンスの作成テスト."""
        session = Session(user_id=123, project=project)
        assert session.user_id == 123
        assert session.project == project
        assert session.state == SessionState.CREATED
        assert session.thread_id is None
        assert session.acp_session_id is None
        assert isinstance(session.created_at, datetime)
        assert isinstance(session.last_activity_at, datetime)

    def test_session_with_thread_id(self, project: Project) -> None:
        """thread_idを指定したSessionの作成テスト."""
        session = Session(user_id=123, project=project, thread_id=456)
        assert session.thread_id == 456

    def test_session_is_active_created(self, project: Project) -> None:
        """Created状態のis_activeテスト."""
        session = Session(user_id=123, project=project, state=SessionState.CREATED)
        assert session.is_active() is False

    def test_session_is_active_active(self, project: Project) -> None:
        """Active状態のis_activeテスト."""
        session = Session(user_id=123, project=project, state=SessionState.ACTIVE)
        assert session.is_active() is True

    def test_session_is_active_prompting(self, project: Project) -> None:
        """Prompting状態のis_activeテスト."""
        session = Session(user_id=123, project=project, state=SessionState.PROMPTING)
        assert session.is_active() is True

    def test_session_is_active_closed(self, project: Project) -> None:
        """Closed状態のis_activeテスト."""
        session = Session(user_id=123, project=project, state=SessionState.CLOSED)
        assert session.is_active() is False


class TestSessionService:
    """SessionServiceのテスト."""

    @pytest.mark.asyncio
    async def test_create_session_success(
        self,
        config: Config,
        project: Project,
        mock_acp_client: MagicMock,
    ) -> None:
        """セッション作成が成功するテスト."""
        service = SessionService(config)
        session = await service.create_session(
            user_id=123, project=project, thread_id=456
        )

        assert session.user_id == 123
        assert session.project == project
        assert session.thread_id == 456
        assert session.state == SessionState.ACTIVE
        assert session.acp_session_id == "test_acp_session_id"

        # ACPClientが適切に呼ばれたことを確認
        mock_acp_client.assert_called_once()
        instance = mock_acp_client.return_value
        instance.initialize.assert_awaited_once_with(working_directory=project.path)

        # セッションが登録されていることを確認
        active_session = service.get_active_session(user_id=123)
        assert active_session is not None
        assert active_session.id == session.id

    @pytest.mark.asyncio
    async def test_create_session_acp_failure(
        self,
        config: Config,
        project: Project,
        mock_acp_client: MagicMock,
    ) -> None:
        """ACP Server接続失敗のテスト."""
        # ACPClientのinitializeが失敗するようにモック
        instance = mock_acp_client.return_value
        instance.initialize.side_effect = Exception("Connection failed")

        service = SessionService(config)
        with pytest.raises(ACPConnectionError, match="Connection failed"):
            await service.create_session(user_id=123, project=project)

        # クリーンアップが呼ばれていることを確認
        instance.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_prompt_success(
        self,
        config: Config,
        project: Project,
        mock_acp_client: MagicMock,
    ) -> None:
        """プロンプト送信が成功するテスト."""
        service = SessionService(config)
        session = await service.create_session(user_id=123, project=project)

        # プロンプトを送信
        await service.send_prompt(session.id, "Hello, agent!")

        # ACPClientのsend_promptが呼ばれたことを確認
        instance = mock_acp_client.return_value
        instance.send_prompt.assert_awaited_once_with(
            "test_acp_session_id", "Hello, agent!"
        )

    @pytest.mark.asyncio
    async def test_send_prompt_session_not_found(
        self,
        config: Config,
    ) -> None:
        """存在しないセッションへのプロンプト送信テスト."""
        service = SessionService(config)

        with pytest.raises(SessionNotFoundError, match="invalid_session_id"):
            await service.send_prompt("invalid_session_id", "Hello")

    @pytest.mark.asyncio
    async def test_send_prompt_closed_session(
        self,
        config: Config,
        project: Project,
        mock_acp_client: MagicMock,
    ) -> None:
        """クローズ済みセッションへのプロンプト送信テスト."""
        service = SessionService(config)
        session = await service.create_session(user_id=123, project=project)

        # セッションをクローズ
        await service.close_session(session.id)

        # クローズ済みセッションにプロンプトを送信
        with pytest.raises(
            SessionStateError, match="Cannot send prompt to closed session"
        ):
            await service.send_prompt(session.id, "Hello")

    @pytest.mark.asyncio
    async def test_send_prompt_created_session(
        self,
        config: Config,
        project: Project,
    ) -> None:
        """CREATED状態のセッションへのプロンプト送信テスト."""
        service = SessionService(config)
        # 手動でCREATED状態のセッションを登録
        session = Session(
            user_id=123,
            project=project,
            state=SessionState.CREATED,
        )
        service._sessions[123] = session
        service._session_map[session.id] = session

        # CREATED状態のセッションにプロンプトを送信
        with pytest.raises(
            SessionStateError,
            match="Cannot send prompt to session that is not yet active",
        ):
            await service.send_prompt(session.id, "Hello")

    def test_get_active_session_exists(
        self,
        config: Config,
        project: Project,
        mock_acp_client: MagicMock,
    ) -> None:
        """アクティブなセッションが存在する場合のテスト."""
        service = SessionService(config)
        # 手動でセッションを登録（テスト用）
        session = Session(
            user_id=123,
            project=project,
            state=SessionState.ACTIVE,
            acp_session_id="test_acp_session_id",
        )
        service._sessions[123] = session
        service._session_map[session.id] = session

        active_session = service.get_active_session(user_id=123)
        assert active_session is not None
        assert active_session.id == session.id

    def test_get_active_session_none(self, config: Config) -> None:
        """アクティブなセッションがない場合のテスト."""
        service = SessionService(config)
        active_session = service.get_active_session(user_id=123)
        assert active_session is None

    def test_get_active_session_closed(
        self,
        config: Config,
        project: Project,
    ) -> None:
        """セッションはあるがClosed状態の場合のテスト."""
        service = SessionService(config)
        # 手動でクローズ済みセッションを登録
        session = Session(
            user_id=123,
            project=project,
            state=SessionState.CLOSED,
        )
        service._sessions[123] = session
        service._session_map[session.id] = session

        active_session = service.get_active_session(user_id=123)
        assert active_session is None

    def test_get_session_by_thread_exists(
        self,
        config: Config,
        project: Project,
    ) -> None:
        """スレッドIDからセッションを取得するテスト."""
        service = SessionService(config)
        # 手動でセッションを登録
        session = Session(
            user_id=123,
            project=project,
            thread_id=456,
            state=SessionState.ACTIVE,
        )
        service._sessions[123] = session
        service._session_map[session.id] = session
        service._thread_sessions[456] = session.id

        found_session = service.get_session_by_thread(thread_id=456)
        assert found_session is not None
        assert found_session.id == session.id

    def test_get_session_by_thread_none(self, config: Config) -> None:
        """存在しないスレッドIDのテスト."""
        service = SessionService(config)
        found_session = service.get_session_by_thread(thread_id=999)
        assert found_session is None

    def test_get_session_by_thread_not_active(
        self,
        config: Config,
        project: Project,
    ) -> None:
        """スレッドに紐づくセッションがアクティブでない場合のテスト."""
        service = SessionService(config)
        # 手動でクローズ済みセッションを登録
        session = Session(
            user_id=123,
            project=project,
            thread_id=456,
            state=SessionState.CLOSED,
        )
        service._sessions[123] = session
        service._session_map[session.id] = session
        service._thread_sessions[456] = session.id

        found_session = service.get_session_by_thread(thread_id=456)
        assert found_session is None

    @pytest.mark.asyncio
    async def test_close_session_success(
        self,
        config: Config,
        project: Project,
        mock_acp_client: MagicMock,
    ) -> None:
        """セッション正常終了のテスト."""
        service = SessionService(config)
        session = await service.create_session(
            user_id=123, project=project, thread_id=456
        )

        # セッションをクローズ
        await service.close_session(session.id)

        # ACPClientのcancel_sessionとcloseが呼ばれたことを確認
        instance = mock_acp_client.return_value
        instance.cancel_session.assert_awaited_once_with("test_acp_session_id")
        instance.close.assert_awaited()

        # セッション状態がClosedになっていることを確認
        assert session.state == SessionState.CLOSED

        # アクティブなセッションとしては取得できないことを確認
        assert service.get_active_session(user_id=123) is None
        assert service.get_session_by_thread(thread_id=456) is None

        # セッションオブジェクト自体はマップに残っている
        assert service._sessions.get(123) is not None
        assert service._sessions[123].state == SessionState.CLOSED

    @pytest.mark.asyncio
    async def test_close_session_not_found(self, config: Config) -> None:
        """存在しないセッションのクローズテスト."""
        service = SessionService(config)

        with pytest.raises(SessionNotFoundError, match="invalid_session_id"):
            await service.close_session("invalid_session_id")

    @pytest.mark.asyncio
    async def test_kill_session_success(
        self,
        config: Config,
        project: Project,
        mock_acp_client: MagicMock,
    ) -> None:
        """セッション強制終了のテスト."""
        service = SessionService(config)
        session = await service.create_session(
            user_id=123, project=project, thread_id=456
        )

        # セッションを強制終了
        await service.kill_session(session.id)

        # ACPClientのcloseが呼ばれたことを確認（cancel_sessionは呼ばれない）
        instance = mock_acp_client.return_value
        instance.cancel_session.assert_not_called()
        instance.close.assert_awaited()

        # セッション状態がClosedになっていることを確認
        assert session.state == SessionState.CLOSED

        # アクティブなセッションとしては取得できないことを確認
        assert service.get_active_session(user_id=123) is None
        assert service.get_session_by_thread(thread_id=456) is None

        # セッションオブジェクト自体はマップに残っている
        assert service._sessions.get(123) is not None
        assert service._sessions[123].state == SessionState.CLOSED

    @pytest.mark.asyncio
    async def test_kill_session_not_found(self, config: Config) -> None:
        """存在しないセッションの強制終了テスト."""
        service = SessionService(config)

        with pytest.raises(SessionNotFoundError, match="invalid_session_id"):
            await service.kill_session("invalid_session_id")


class TestSessionNotFoundError:
    """SessionNotFoundErrorのテスト."""

    def test_error_message(self) -> None:
        """エラーメッセージのテスト."""
        error = SessionNotFoundError("test_session_id")
        assert error.session_id == "test_session_id"
        assert "Session test_session_id not found" in str(error)


class TestSessionStateError:
    """SessionStateErrorのテスト."""

    def test_error_message(self) -> None:
        """エラーメッセージのテスト."""
        error = SessionStateError(
            "test_session_id",
            SessionState.CLOSED,
            "Cannot perform this operation",
        )
        assert error.session_id == "test_session_id"
        assert error.current_state == SessionState.CLOSED
        assert "test_session_id" in str(error)
        assert "SessionState.CLOSED" in str(error) or "closed" in str(error).lower()
        assert "Cannot perform this operation" in str(error)


class TestACPConnectionError:
    """ACPConnectionErrorのテスト."""

    def test_error_message(self) -> None:
        """エラーメッセージのテスト."""
        error = ACPConnectionError("Connection failed")
        assert "ACP connection failed: Connection failed" in str(error)


class TestSessionModelFeatures:
    """モデル切り替え機能のテスト."""

    @pytest.mark.asyncio
    async def test_create_session_with_model_info(
        self,
        config: Config,
        project: Project,
        mock_acp_client: MagicMock,
    ) -> None:
        """モデル情報付きセッション作成のテスト."""
        service = SessionService(config)
        session = await service.create_session(
            user_id=123, project=project, thread_id=456
        )

        # モデル情報が保存されていることを確認
        assert session.available_models == [
            "claude-sonnet-4-5",
            "claude-opus-4-6",
            "claude-haiku-4-5",
        ]
        assert session.current_model_id == "claude-sonnet-4-5"

        # ACPClientのメソッドが呼ばれたことを確認
        instance = mock_acp_client.return_value
        instance.get_available_models.assert_called_once()
        instance.get_current_model.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_model_success(
        self,
        config: Config,
        project: Project,
        mock_acp_client: MagicMock,
    ) -> None:
        """モデル切り替え成功のテスト."""
        service = SessionService(config)
        session = await service.create_session(user_id=123, project=project)

        # 初期モデルを確認
        assert session.current_model_id == "claude-sonnet-4-5"

        # モデルを変更
        await service.set_model(session.id, "claude-opus-4-6")

        # ACPClientのset_session_modelが呼ばれたことを確認
        instance = mock_acp_client.return_value
        instance.set_session_model.assert_awaited_once_with(
            "claude-opus-4-6", "test_acp_session_id"
        )

        # セッションのモデル情報はCurrentModeUpdate通知で更新されるため、
        # この時点ではまだ更新されていない
        assert session.current_model_id == "claude-sonnet-4-5"

    @pytest.mark.asyncio
    async def test_set_model_invalid_model(
        self,
        config: Config,
        project: Project,
        mock_acp_client: MagicMock,
    ) -> None:
        """無効なモデルID指定のテスト."""
        service = SessionService(config)
        session = await service.create_session(user_id=123, project=project)

        # 利用不可能なモデルIDを指定
        with pytest.raises(ValueError, match="not available"):
            await service.set_model(session.id, "invalid-model-id")

        # ACPClientのset_session_modelが呼ばれていないことを確認
        instance = mock_acp_client.return_value
        instance.set_session_model.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_model_session_not_found(
        self,
        config: Config,
    ) -> None:
        """存在しないセッションのモデル変更テスト."""
        service = SessionService(config)

        with pytest.raises(SessionNotFoundError, match="invalid_session_id"):
            await service.set_model("invalid_session_id", "claude-opus-4-6")

    @pytest.mark.asyncio
    async def test_set_model_closed_session(
        self,
        config: Config,
        project: Project,
        mock_acp_client: MagicMock,
    ) -> None:
        """クローズ済みセッションのモデル変更テスト."""
        service = SessionService(config)
        session = await service.create_session(user_id=123, project=project)

        # セッションをクローズ
        await service.close_session(session.id)

        # クローズ済みセッションのモデルを変更
        with pytest.raises(
            SessionStateError, match="Cannot change model of closed session"
        ):
            await service.set_model(session.id, "claude-opus-4-6")

    @pytest.mark.asyncio
    async def test_set_model_created_session(
        self,
        config: Config,
        project: Project,
    ) -> None:
        """CREATED状態のセッションのモデル変更テスト."""
        service = SessionService(config)
        # 手動でCREATED状態のセッションを登録
        session = Session(
            user_id=123,
            project=project,
            state=SessionState.CREATED,
            available_models=["claude-sonnet-4-5", "claude-opus-4-6"],
        )
        service._sessions[123] = session
        service._session_map[session.id] = session

        # CREATED状態のセッションのモデルを変更
        with pytest.raises(
            SessionStateError,
            match="Cannot change model of session that is not yet active",
        ):
            await service.set_model(session.id, "claude-opus-4-6")
