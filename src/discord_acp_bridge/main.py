"""Main entry point for the Discord ACP Bridge application."""

from __future__ import annotations

import asyncio
import logging
import sys

from discord_acp_bridge.application.project import ProjectService
from discord_acp_bridge.application.session import SessionService
from discord_acp_bridge.infrastructure.config import get_config
from discord_acp_bridge.presentation.bot import ACPBot


def setup_logging() -> None:
    """ロギングを設定する."""
    # ログフォーマット
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # ルートロガーの設定
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt=date_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    # discord.pyのログレベルを調整（デバッグ時はDEBUGに変更可能）
    logging.getLogger("discord").setLevel(logging.INFO)
    logging.getLogger("discord.http").setLevel(logging.WARNING)


async def main() -> None:
    """アプリケーションのメインエントリポイント."""
    # ロギング設定
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("Starting Discord ACP Bridge...")

    try:
        # 設定を読み込み
        config = get_config()
        logger.info("Configuration loaded")

        # サービスを初期化
        project_service = ProjectService(config)
        session_service = SessionService(config)
        logger.info("Services initialized")

        # Botを初期化
        bot = ACPBot(
            config=config,
            project_service=project_service,
            session_service=session_service,
        )

        # SessionServiceにコールバックを設定
        session_service._on_message_callback = bot.send_message_to_thread
        session_service._on_timeout_callback = bot.send_timeout_notification

        logger.info("Bot initialized with callbacks")

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
