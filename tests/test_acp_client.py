"""Test cases for ACP Client."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from discord_acp_bridge.infrastructure.acp_client import ACPClient

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture
def mock_spawn_agent_process() -> Generator[MagicMock, None, None]:
    """spawn_agent_process のモック."""
    with patch(
        "discord_acp_bridge.infrastructure.acp_client.spawn_agent_process"
    ) as mock:
        # コンテキストマネージャーのモック
        mock_context = MagicMock()
        mock_connection = MagicMock()
        mock_process = MagicMock()

        # SessionModelState のモック（NewSessionResponse.models として返す）
        mock_model_info_sonnet = MagicMock()
        mock_model_info_sonnet.model_id = "claude-sonnet-4-5"
        mock_model_info_opus = MagicMock()
        mock_model_info_opus.model_id = "claude-opus-4-6"
        mock_model_info_haiku = MagicMock()
        mock_model_info_haiku.model_id = "claude-haiku-4-5"

        mock_session_model_state = MagicMock()
        mock_session_model_state.available_models = [
            mock_model_info_sonnet,
            mock_model_info_opus,
            mock_model_info_haiku,
        ]
        mock_session_model_state.current_model_id = "claude-sonnet-4-5"

        # ClientSideConnection のモック
        mock_connection.initialize = AsyncMock(
            return_value=MagicMock(
                server_info={"name": "test-server"},
            )
        )
        mock_connection.new_session = AsyncMock(
            return_value=MagicMock(
                session_id="test-session-123",
                models=mock_session_model_state,
            )
        )
        mock_connection.prompt = AsyncMock()
        mock_connection.cancel = AsyncMock()
        mock_connection.close = AsyncMock()
        mock_connection.set_session_model = AsyncMock()

        # Process のモック
        mock_process.returncode = None
        mock_process.terminate = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock()

        # __aenter__ で connection と process を返す
        mock_context.__aenter__ = AsyncMock(
            return_value=(mock_connection, mock_process)
        )
        mock_context.__aexit__ = AsyncMock()

        mock.return_value = mock_context
        yield mock


@pytest.fixture
def acp_client() -> ACPClient:
    """テスト用の ACP Client インスタンス."""
    return ACPClient(command=["claude-code-acp"])


@pytest.mark.asyncio
async def test_initialize(
    acp_client: ACPClient,
    mock_spawn_agent_process: MagicMock,
) -> None:
    """初期化とセッション作成のテスト."""
    session_id = await acp_client.initialize("/path/to/project")

    # spawn_agent_process が呼ばれたことを確認
    mock_spawn_agent_process.assert_called_once()
    call_args = mock_spawn_agent_process.call_args
    assert call_args[0][1] == "claude-code-acp"  # command
    assert call_args[1]["cwd"] == "/path/to/project"

    # セッション ID が返されたことを確認
    assert session_id == "test-session-123"
    assert acp_client._acp_session_id == "test-session-123"

    # Watchdog Timer が開始されたことを確認
    assert acp_client._watchdog_task is not None
    assert not acp_client._watchdog_task.done()

    # クリーンアップ
    await acp_client.close()


@pytest.mark.asyncio
async def test_send_prompt(
    acp_client: ACPClient,
    mock_spawn_agent_process: MagicMock,
) -> None:
    """プロンプト送信のテスト."""
    # 初期化
    await acp_client.initialize("/path/to/project")

    # プロンプトを送信
    await acp_client.send_prompt("test-session-123", "Hello, world!")

    # prompt メソッドが呼ばれたことを確認
    mock_connection = mock_spawn_agent_process.return_value.__aenter__.return_value[0]
    mock_connection.prompt.assert_called_once()
    call_args = mock_connection.prompt.call_args
    assert call_args[1]["session_id"] == "test-session-123"

    # クリーンアップ
    await acp_client.close()


@pytest.mark.asyncio
async def test_send_prompt_not_initialized() -> None:
    """初期化前のプロンプト送信エラーのテスト."""
    client = ACPClient(command=["claude-code-acp"])

    with pytest.raises(RuntimeError, match="not initialized"):
        await client.send_prompt("test-session-123", "Hello!")


@pytest.mark.asyncio
async def test_cancel_session(
    acp_client: ACPClient,
    mock_spawn_agent_process: MagicMock,
) -> None:
    """セッションキャンセルのテスト."""
    # 初期化
    await acp_client.initialize("/path/to/project")

    # セッションをキャンセル
    await acp_client.cancel_session("test-session-123")

    # cancel メソッドが呼ばれたことを確認
    mock_connection = mock_spawn_agent_process.return_value.__aenter__.return_value[0]
    mock_connection.cancel.assert_called_once_with(session_id="test-session-123")

    # セッション ID がクリアされたことを確認
    assert acp_client._acp_session_id is None

    # Watchdog Timer が停止されたことを確認
    assert acp_client._watchdog_task is None or acp_client._watchdog_task.done()

    # クリーンアップ
    await acp_client.close()


@pytest.mark.asyncio
async def test_close(
    acp_client: ACPClient,
    mock_spawn_agent_process: MagicMock,
) -> None:
    """クローズ処理のテスト."""
    # 初期化
    await acp_client.initialize("/path/to/project")

    # クローズ
    await acp_client.close()

    # Connection がクローズされたことを確認
    mock_connection = mock_spawn_agent_process.return_value.__aenter__.return_value[0]
    mock_connection.close.assert_called_once()

    # Process が終了されたことを確認
    mock_process = mock_spawn_agent_process.return_value.__aenter__.return_value[1]
    mock_process.terminate.assert_called_once()

    # 状態がクリアされたことを確認
    assert acp_client._connection is None
    assert acp_client._process is None
    assert acp_client._acp_session_id is None
    assert acp_client._watchdog_task is None or acp_client._watchdog_task.done()


@pytest.mark.asyncio
async def test_set_session_model(
    acp_client: ACPClient,
    mock_spawn_agent_process: MagicMock,
) -> None:
    """モデル変更のテスト."""
    # 初期化
    await acp_client.initialize("/path/to/project")

    # 変更前の状態を確認
    assert acp_client.get_current_model() == "claude-sonnet-4-5"

    # モデルを変更
    await acp_client.set_session_model("claude-opus-4-6", "test-session-123")

    # set_session_model メソッドが呼ばれたことを確認
    mock_connection = mock_spawn_agent_process.return_value.__aenter__.return_value[0]
    mock_connection.set_session_model.assert_called_once_with(
        model_id="claude-opus-4-6", session_id="test-session-123"
    )

    # 楽観的更新が反映されていることを確認
    assert acp_client._current_model_id_override == "claude-opus-4-6"
    assert acp_client.get_current_model() == "claude-opus-4-6"

    # クリーンアップ
    await acp_client.close()


@pytest.mark.asyncio
async def test_set_session_model_not_initialized() -> None:
    """初期化前のモデル変更エラーのテスト."""
    client = ACPClient(command=["claude-code-acp"])

    with pytest.raises(RuntimeError, match="not initialized"):
        await client.set_session_model("claude-opus-4-6", "test-session-123")


@pytest.mark.asyncio
async def test_get_available_models(
    acp_client: ACPClient,
    mock_spawn_agent_process: MagicMock,
) -> None:
    """利用可能なモデル一覧取得のテスト."""
    # 初期化
    await acp_client.initialize("/path/to/project")

    # 利用可能なモデル一覧を取得
    models = acp_client.get_available_models()

    assert models == [
        "claude-sonnet-4-5",
        "claude-opus-4-6",
        "claude-haiku-4-5",
    ]

    # クリーンアップ
    await acp_client.close()


def test_get_available_models_not_initialized() -> None:
    """初期化前のモデル一覧取得エラーのテスト."""
    client = ACPClient(command=["claude-code-acp"])

    with pytest.raises(RuntimeError, match="not initialized"):
        client.get_available_models()


@pytest.mark.asyncio
async def test_get_current_model(
    acp_client: ACPClient,
    mock_spawn_agent_process: MagicMock,
) -> None:
    """現在のモデル取得のテスト."""
    # 初期化
    await acp_client.initialize("/path/to/project")

    # 現在のモデルを取得
    current_model = acp_client.get_current_model()

    assert current_model == "claude-sonnet-4-5"

    # クリーンアップ
    await acp_client.close()


def test_get_current_model_not_initialized() -> None:
    """初期化前の現在のモデル取得エラーのテスト."""
    client = ACPClient(command=["claude-code-acp"])

    with pytest.raises(RuntimeError, match="not initialized"):
        client.get_current_model()


@pytest.mark.asyncio
async def test_get_available_models_no_session_model_state(
    acp_client: ACPClient,
    mock_spawn_agent_process: MagicMock,
) -> None:
    """NewSessionResponse.modelsがNoneの場合のget_available_models()テスト."""
    # new_session の戻り値の models を None に設定
    mock_spawn_agent_process.return_value.__aenter__.return_value[
        0
    ].new_session.return_value = MagicMock(
        session_id="test-session-123",
        models=None,
    )

    # 初期化
    await acp_client.initialize("/path/to/project")

    # 利用可能なモデル一覧を取得（空リストが返ることを期待）
    models = acp_client.get_available_models()
    assert models == []

    # クリーンアップ
    await acp_client.close()


@pytest.mark.asyncio
async def test_get_current_model_no_session_model_state(
    acp_client: ACPClient,
    mock_spawn_agent_process: MagicMock,
) -> None:
    """NewSessionResponse.modelsがNoneの場合のget_current_model()テスト."""
    # new_session の戻り値の models を None に設定
    mock_spawn_agent_process.return_value.__aenter__.return_value[
        0
    ].new_session.return_value = MagicMock(
        session_id="test-session-123",
        models=None,
    )

    # 初期化
    await acp_client.initialize("/path/to/project")

    # 現在のモデルを取得（Noneが返ることを期待）
    current_model = acp_client.get_current_model()
    assert current_model is None

    # クリーンアップ
    await acp_client.close()


@pytest.mark.asyncio
async def test_request_permission_with_options() -> None:
    """request_permission: オプションありで自動承認されるテスト."""
    client = ACPClient(command=["claude-code-acp"])
    client_impl = client._client_impl

    # PermissionOption のモック
    option1 = MagicMock()
    option1.option_id = "opt-1"
    option1.kind = "allow_once"

    option2 = MagicMock()
    option2.option_id = "opt-2"
    option2.kind = "allow_always"

    tool_call = MagicMock()
    tool_call.name = "bash"

    result = await client_impl.request_permission(
        options=[option1, option2],
        session_id="test-session",
        tool_call=tool_call,
    )

    # allow_always が優先されること
    assert result.outcome.outcome == "selected"
    assert result.outcome.option_id == "opt-2"


@pytest.mark.asyncio
async def test_request_permission_no_allow_always() -> None:
    """request_permission: allow_alwaysがない場合は最初のオプションを選択."""
    client = ACPClient(command=["claude-code-acp"])
    client_impl = client._client_impl

    option1 = MagicMock()
    option1.option_id = "opt-1"
    option1.kind = "allow_once"

    tool_call = MagicMock()

    result = await client_impl.request_permission(
        options=[option1],
        session_id="test-session",
        tool_call=tool_call,
    )

    assert result.outcome.outcome == "selected"
    assert result.outcome.option_id == "opt-1"


@pytest.mark.asyncio
async def test_request_permission_no_options() -> None:
    """request_permission: オプションなしの場合はcancelledを返すテスト."""
    client = ACPClient(command=["claude-code-acp"])
    client_impl = client._client_impl

    tool_call = MagicMock()

    result = await client_impl.request_permission(
        options=[],
        session_id="test-session",
        tool_call=tool_call,
    )

    assert result.outcome.outcome == "cancelled"


@pytest.mark.asyncio
async def test_close_with_context_timeout(
    acp_client: ACPClient,
    mock_spawn_agent_process: MagicMock,
) -> None:
    """close()でコンテキストクローズがタイムアウトした場合のテスト."""
    # 初期化
    await acp_client.initialize("/path/to/project")

    # __aexit__ がタイムアウトするようにモック
    async def slow_aexit(*args: Any) -> None:
        await asyncio.sleep(10)  # 3秒のタイムアウトを超える

    mock_spawn_agent_process.return_value.__aexit__ = slow_aexit

    # close()がタイムアウトしても正常に完了すること
    await acp_client.close()

    # 状態がクリアされたことを確認
    assert acp_client._context is None
    assert acp_client._connection is None
    assert acp_client._process is None
    assert acp_client._acp_session_id is None


@pytest.mark.asyncio
async def test_close_with_context_error(
    acp_client: ACPClient,
    mock_spawn_agent_process: MagicMock,
) -> None:
    """close()でコンテキストクローズがエラーを起こした場合のテスト."""
    # 初期化
    await acp_client.initialize("/path/to/project")

    # __aexit__ がエラーを起こすようにモック
    mock_spawn_agent_process.return_value.__aexit__ = AsyncMock(
        side_effect=RuntimeError("async generator error")
    )

    # close()がエラーでも正常に完了すること
    await acp_client.close()

    # 状態がクリアされたことを確認
    assert acp_client._context is None
    assert acp_client._acp_session_id is None


@pytest.mark.asyncio
async def test_request_permission_with_callback() -> None:
    """request_permission: コールバックがある場合に委譲されるテスト."""
    from acp import RequestPermissionResponse
    from acp.schema import AllowedOutcome

    expected_response = RequestPermissionResponse(
        outcome=AllowedOutcome(outcome="selected", option_id="opt-1")
    )
    callback = AsyncMock(return_value=expected_response)

    client = ACPClient(
        command=["claude-code-acp"],
        on_permission_request=callback,
    )
    client_impl = client._client_impl

    option1 = MagicMock()
    option1.option_id = "opt-1"
    option1.kind = "allow_once"

    tool_call = MagicMock()
    tool_call.title = "bash"

    result = await client_impl.request_permission(
        options=[option1],
        session_id="test-session",
        tool_call=tool_call,
    )

    callback.assert_awaited_once_with("test-session", [option1], tool_call)
    assert result.outcome.outcome == "selected"
    assert result.outcome.option_id == "opt-1"


@pytest.mark.asyncio
async def test_request_permission_callback_none_falls_back() -> None:
    """request_permission: コールバックがNoneの場合は自動承認にフォールバック."""
    client = ACPClient(command=["claude-code-acp"], on_permission_request=None)
    client_impl = client._client_impl

    option1 = MagicMock()
    option1.option_id = "opt-1"
    option1.kind = "allow_always"

    tool_call = MagicMock()
    tool_call.title = "bash"

    result = await client_impl.request_permission(
        options=[option1],
        session_id="test-session",
        tool_call=tool_call,
    )

    assert result.outcome.outcome == "selected"
    assert result.outcome.option_id == "opt-1"


@pytest.mark.asyncio
async def test_request_permission_callback_error_falls_back() -> None:
    """request_permission: コールバックがエラーの場合は自動承認にフォールバック."""
    callback = AsyncMock(side_effect=RuntimeError("callback error"))

    client = ACPClient(
        command=["claude-code-acp"],
        on_permission_request=callback,
    )
    client_impl = client._client_impl

    option1 = MagicMock()
    option1.option_id = "opt-1"
    option1.kind = "allow_once"

    option2 = MagicMock()
    option2.option_id = "opt-2"
    option2.kind = "allow_always"

    tool_call = MagicMock()
    tool_call.title = "bash"

    result = await client_impl.request_permission(
        options=[option1, option2],
        session_id="test-session",
        tool_call=tool_call,
    )

    # エラー時は自動承認（allow_always優先）
    assert result.outcome.outcome == "selected"
    assert result.outcome.option_id == "opt-2"


# Watchdog timeout と session_update のテストは複雑なモックが必要なため省略
# 実際の統合テストで検証する
