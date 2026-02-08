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

    # サービス変数をスコープ外で宣言（finally句でアクセスするため）
    session_service = None
    bot = None

    try:
        logger.info("Configuration loaded")

        # サービスを初期化
        project_service = ProjectService(config)

        # Botを初期化（SessionServiceより先に）
        bot = ACPBot(
            config=config,
            project_service=project_service,
            session_service=None,
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
            try:
                await bot.start(config.discord_bot_token)
            except KeyboardInterrupt:
                logger.info("Received keyboard interrupt, shutting down gracefully...")
                # Botがクローズされる前にセッションをクローズ（Discord通知のため）
                if session_service is not None:
                    try:
                        await session_service.close_all_sessions()
                    except Exception:
                        logger.critical("Error during session cleanup", exc_info=True)
                # KeyboardInterruptを再raiseして、async withブロックを抜ける
                raise

    except KeyboardInterrupt:
        # async withブロック内から再raiseされたKeyboardInterruptをキャッチ
        pass  # すでにログ出力とクリーンアップ済み
    except Exception:
        logger.exception("Fatal error occurred")
        sys.exit(1)
    finally:
        logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
