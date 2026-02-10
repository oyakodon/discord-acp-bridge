"""Tests for permission UI components."""

from __future__ import annotations

import asyncio

import pytest

from discord_acp_bridge.application.models import (
    PermissionOptionInfo,
    PermissionRequest,
    PermissionResponse,
    ToolCallInfo,
)
from discord_acp_bridge.presentation.views.permission import (
    PermissionView,
    build_permission_embed,
)


def _make_request(
    raw_input: str = "echo hello",
    content_summary: str = "",
    options: list[PermissionOptionInfo] | None = None,
) -> PermissionRequest:
    """テスト用のPermissionRequestを作成する."""
    return PermissionRequest(
        session_id="session-1",
        acp_session_id="acp-session-1",
        thread_id=12345,
        tool_call=ToolCallInfo(
            tool_call_id="tc-001",
            title="Bash: echo hello",
            kind="bash",
            raw_input=raw_input,
            content_summary=content_summary,
        ),
        options=options
        or [
            PermissionOptionInfo(
                option_id="opt-1", name="Allow Once", kind="allow_once"
            ),
            PermissionOptionInfo(
                option_id="opt-2", name="Allow Always", kind="allow_always"
            ),
        ],
    )


class TestBuildPermissionEmbed:
    """build_permission_embed のテスト."""

    def test_basic_embed(self) -> None:
        """基本的なEmbed構築テスト."""
        request = _make_request()
        embed = build_permission_embed(request)

        assert embed.title == "Permission: Bash: echo hello"
        assert embed.color is not None
        assert len(embed.fields) >= 2

        field_names = [f.name for f in embed.fields]
        assert "Tool" in field_names
        assert "Tool Call ID" in field_names

    def test_embed_with_raw_input(self) -> None:
        """raw_inputありのEmbed構築テスト."""
        request = _make_request(raw_input="ls -la")
        embed = build_permission_embed(request)

        field_names = [f.name for f in embed.fields]
        assert "Input" in field_names

    def test_embed_without_raw_input(self) -> None:
        """raw_inputなしのEmbed構築テスト."""
        request = _make_request(raw_input="")
        embed = build_permission_embed(request)

        field_names = [f.name for f in embed.fields]
        assert "Input" not in field_names

    def test_embed_with_content_summary(self) -> None:
        """content_summaryありのEmbed構築テスト."""
        request = _make_request(content_summary="File content here")
        embed = build_permission_embed(request)

        field_names = [f.name for f in embed.fields]
        assert "Content" in field_names

    def test_embed_long_input_truncated(self) -> None:
        """長いraw_inputが切り詰められるテスト."""
        long_input = "x" * 500
        request = _make_request(raw_input=long_input)
        embed = build_permission_embed(request)

        input_field = next(f for f in embed.fields if f.name == "Input")
        assert input_field.value is not None
        assert "..." in input_field.value


class TestPermissionResponse:
    """PermissionResponseのテスト."""

    def test_approved_response(self) -> None:
        """承認レスポンスの作成テスト."""
        response = PermissionResponse(approved=True, option_id="opt-1")
        assert response.approved is True
        assert response.option_id == "opt-1"
        assert response.instructions is None

    def test_denied_response(self) -> None:
        """拒否レスポンスの作成テスト."""
        response = PermissionResponse(approved=False)
        assert response.approved is False
        assert response.option_id is None
        assert response.instructions is None

    def test_denied_with_instructions(self) -> None:
        """拒否+指示レスポンスの作成テスト."""
        response = PermissionResponse(
            approved=False, instructions="Use a different approach"
        )
        assert response.approved is False
        assert response.instructions == "Use a different approach"


class TestPermissionView:
    """PermissionViewのテスト."""

    @pytest.mark.asyncio
    async def test_view_creation(self) -> None:
        """View作成テスト."""
        request = _make_request()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[PermissionResponse] = loop.create_future()
        view = PermissionView(request, future, timeout=60.0)

        assert view.timeout == 60.0
        # ボタンが4つあることを確認
        assert len(view.children) == 4

    @pytest.mark.asyncio
    async def test_find_option_id(self) -> None:
        """option_id検索テスト."""
        request = _make_request()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[PermissionResponse] = loop.create_future()
        view = PermissionView(request, future)

        assert view._find_option_id("allow_once") == "opt-1"
        assert view._find_option_id("allow_always") == "opt-2"
        assert view._find_option_id("deny") is None

    @pytest.mark.asyncio
    async def test_resolve_sets_future(self) -> None:
        """Future解決テスト."""
        request = _make_request()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[PermissionResponse] = loop.create_future()
        view = PermissionView(request, future)

        response = PermissionResponse(approved=True, option_id="opt-1")
        view._resolve(response)

        assert future.done()
        assert future.result() == response

    @pytest.mark.asyncio
    async def test_resolve_no_double_set(self) -> None:
        """二重セット防止テスト."""
        request = _make_request()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[PermissionResponse] = loop.create_future()
        view = PermissionView(request, future)

        response1 = PermissionResponse(approved=True, option_id="opt-1")
        response2 = PermissionResponse(approved=False)

        view._resolve(response1)
        view._resolve(response2)  # 二回目は無視される

        assert future.result() == response1


class TestToolCallInfo:
    """ToolCallInfoのテスト."""

    def test_creation(self) -> None:
        """ToolCallInfo作成テスト."""
        info = ToolCallInfo(
            tool_call_id="tc-001",
            title="Bash",
            kind="bash",
            raw_input="echo hello",
            content_summary="",
        )
        assert info.tool_call_id == "tc-001"
        assert info.title == "Bash"
        assert info.kind == "bash"

    def test_frozen(self) -> None:
        """ToolCallInfoがfrozenであることを確認."""
        info = ToolCallInfo(
            tool_call_id="tc-001",
            title="Bash",
            kind="bash",
            raw_input="echo hello",
            content_summary="",
        )
        with pytest.raises(AttributeError):
            info.title = "New Title"  # type: ignore[misc]
