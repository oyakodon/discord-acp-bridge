"""Main entry point for the Discord ACP Bridge application."""

from __future__ import annotations

import asyncio
import sys

from discord_acp_bridge.application.project import ProjectService
from discord_acp_bridge.application.session import SessionService
from discord_acp_bridge.infrastructure.config import get_config
from discord_acp_bridge.infrastructure.logging import configure_logging, get_logger
from discord_acp_bridge.presentation.bot import ACPBot


async def main() -> None:
    """アプリケーションのメインエントリポイント."""
    # 設定を読み込み（ロギング設定より前に必要）
    config = get_config()

    # 構造化ロギングを設定
    configure_logging(log_level=config.log_level)

    logger = get_logger(__name__)

    logger.info("Starting Discord ACP Bridge...")

    try:
        logger.info("Configuration loaded")

        # サービスを初期化
        project_service = ProjectService(config)

        # Botを初期化（SessionServiceより先に）
        bot = ACPBot(
            config=config,
            project_service=project_service,
            session_service=None,  # type: ignore[arg-type]
        )

        # SessionServiceを初期化（コールバックを渡す）
        session_service = SessionService(
            config,
            on_message=bot.send_message_to_thread,
            on_timeout=bot.send_timeout_notification,
            on_typing=bot.set_typing_indicator,
        )

        # BotにSessionServiceを設定
        bot.session_service = session_service

        logger.info("Services initialized")

        # Botを起動
        async with bot:
            await bot.start(config.discord_bot_token)

    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception:
        logger.exception("Fatal error occurred")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
