"""Permission request UI components for Discord."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    import asyncio

from discord_acp_bridge.application.models import (
    PermissionRequest,  # noqa: TC001
    PermissionResponse,
)
from discord_acp_bridge.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Embed色定義
EMBED_COLOR_PERMISSION = 0xFFA500  # オレンジ


def build_permission_embed(request: PermissionRequest) -> discord.Embed:
    """パーミッション要求のEmbedを構築する."""
    tool = request.tool_call

    embed = discord.Embed(
        title=f"Permission: {tool.title}",
        color=EMBED_COLOR_PERMISSION,
    )
    embed.add_field(name="Tool", value=tool.kind, inline=True)
    embed.add_field(name="Tool Call ID", value=tool.tool_call_id[:12], inline=True)

    if tool.raw_input:
        # コードブロックで表示（長い場合は切り詰め）
        display_input = tool.raw_input[:400]
        if len(tool.raw_input) > 400:
            display_input += "\n..."
        embed.add_field(name="Input", value=f"```\n{display_input}\n```", inline=False)

    if tool.content_summary:
        display_summary = tool.content_summary[:400]
        if len(tool.content_summary) > 400:
            display_summary += "\n..."
        embed.add_field(
            name="Content", value=f"```\n{display_summary}\n```", inline=False
        )

    return embed


class InstructionModal(discord.ui.Modal, title="修正指示"):
    """拒否+指示用のモーダル."""

    instructions: discord.ui.TextInput[InstructionModal] = discord.ui.TextInput(
        label="エージェントへの指示",
        style=discord.TextStyle.paragraph,
        placeholder="代わりにこうしてください...",
        required=True,
        max_length=2000,
    )

    def __init__(self, future: asyncio.Future[PermissionResponse]) -> None:
        super().__init__()
        self._future = future

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """モーダル送信時の処理."""
        if not self._future.done():
            self._future.set_result(
                PermissionResponse(
                    approved=False,
                    instructions=self.instructions.value,
                )
            )
        await interaction.response.send_message(
            "拒否+指示を送信しました。", ephemeral=True
        )


class PermissionView(discord.ui.View):
    """パーミッション要求のボタンUI."""

    def __init__(
        self,
        request: PermissionRequest,
        future: asyncio.Future[PermissionResponse],
        *,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self._request = request
        self._future = future

    def _resolve(self, response: PermissionResponse) -> None:
        """Futureに結果をセットする（二重セット防止）."""
        if not self._future.done():
            self._future.set_result(response)

    def _find_option_id(self, kind: str) -> str | None:
        """指定された種別のoption_idを返す."""
        for o in self._request.options:
            if o.kind == kind:
                return o.option_id
        return None

    @discord.ui.button(label="承認", style=discord.ButtonStyle.success)
    async def approve_once(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[PermissionView],
    ) -> None:
        """一回承認ボタン."""
        option_id = self._find_option_id("allow_once") or self._find_option_id(
            "allow_always"
        )
        self._resolve(PermissionResponse(approved=True, option_id=option_id))
        self.stop()
        await interaction.response.edit_message(content="✅ 承認しました。", view=None)

    @discord.ui.button(label="常に承認", style=discord.ButtonStyle.primary)
    async def approve_always(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[PermissionView],
    ) -> None:
        """常に承認ボタン."""
        option_id = self._find_option_id("allow_always") or self._find_option_id(
            "allow_once"
        )
        self._resolve(PermissionResponse(approved=True, option_id=option_id))
        self.stop()
        await interaction.response.edit_message(
            content="✅ 常に承認しました。", view=None
        )

    @discord.ui.button(label="拒否", style=discord.ButtonStyle.danger)
    async def deny(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[PermissionView],
    ) -> None:
        """拒否ボタン."""
        self._resolve(PermissionResponse(approved=False))
        self.stop()
        await interaction.response.edit_message(content="❌ 拒否しました。", view=None)

    @discord.ui.button(label="拒否+指示", style=discord.ButtonStyle.secondary)
    async def deny_with_instructions(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button[PermissionView],
    ) -> None:
        """拒否+指示ボタン（モーダル表示）."""
        modal = InstructionModal(self._future)
        await interaction.response.send_modal(modal)
        self.stop()

    async def on_timeout(self) -> None:
        """タイムアウト時の処理（Futureにはセットしない→SessionServiceのwait_forでTimeoutError）."""
        logger.info(
            "Permission view timed out",
            session_id=self._request.session_id,
        )
