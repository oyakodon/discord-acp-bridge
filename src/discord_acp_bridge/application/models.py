"""Data models for cross-layer communication."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PermissionOptionInfo:
    """パーミッション選択肢の情報."""

    option_id: str
    name: str
    kind: str  # "allow_once", "allow_always", "deny" etc.


@dataclass(frozen=True)
class ToolCallInfo:
    """ツール呼び出しの情報."""

    tool_call_id: str
    title: str
    kind: str  # "bash", "edit", "write" etc.
    raw_input: str
    content_summary: str


@dataclass(frozen=True)
class PermissionRequest:
    """パーミッション要求（SessionService → Bot）."""

    session_id: str
    acp_session_id: str
    thread_id: int
    tool_call: ToolCallInfo
    options: list[PermissionOptionInfo] = field(default_factory=list)


@dataclass
class PermissionResponse:
    """パーミッション応答（Bot → SessionService）."""

    approved: bool
    option_id: str | None = None
    instructions: str | None = None
