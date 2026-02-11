"""Main entry point for the Discord ACP Bridge application."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from discord_acp_bridge.application.project import ProjectService
from discord_acp_bridge.application.session import SessionService
from discord_acp_bridge.infrastructure.config import get_config
from discord_acp_bridge.infrastructure.logging import configure_logging, get_logger


async def main() -> None:
    """アプリケーションのメインエントリポイント."""
    # 設定を読み込み（ロギング設定より前に必要）
    config = get_config()

    # 構造化ロギングを設定
    configure_logging(
        log_level=config.log_level,
        log_dir=config.log_dir,
        log_backup_count=config.log_backup_count,
    )

    logger = get_logger(__name__)

    logger.info("Starting Discord ACP Bridge...")

    # シャットダウンイベント
    shutdown_event = asyncio.Event()

    def signal_handler() -> None:
        if shutdown_event.is_set():
            return  # 二重呼び出しを防止
        logger.info("Received shutdown signal, shutting down gracefully...")
        shutdown_event.set()

    # シグナルハンドラーを登録（SIGINT + SIGTERM）
    # Windows では loop.add_signal_handler が未実装のため signal.signal にフォールバック
    loop = asyncio.get_running_loop()
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)
    except NotImplementedError:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda s, f: loop.call_soon_threadsafe(signal_handler))

    session_service: SessionService | None = None
    bot = None
    bot_task: asyncio.Task[None] | None = None
    shutdown_task: asyncio.Task[bool] | None = None

    try:
        logger.info("Configuration loaded")

        # サービスを初期化
        project_service = ProjectService(config)

        # Botを初期化（SessionServiceより先に）
        from discord_acp_bridge.presentation.bot import ACPBot

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
            on_permission_request=bot.send_permission_request,
        )

        # BotにSessionServiceを設定
        bot.session_service = session_service

        logger.info("Services initialized")

        # Botを起動（タスクとして）
        bot_task = asyncio.create_task(bot.start(config.discord_bot_token))
        shutdown_task = asyncio.create_task(shutdown_event.wait())

        # bot_taskの完了 or シャットダウンイベントを待つ
        done, pending = await asyncio.wait(
            [bot_task, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # bot_taskが例外で終了した場合は例外を伝播
        if bot_task in done:
            bot_task.result()  # 例外があればここでraise

    except Exception:
        logger.exception("Fatal error occurred")
        sys.exit(1)
    finally:
        # クリーンアップ（セッション → Bot の順序で実行）
        # セッションクリーンアップはBotが生存中に行う（Discord通知のため）
        if session_service is not None:
            try:
                await session_service.close_all_sessions()
            except Exception:
                logger.critical("Error during session cleanup", exc_info=True)

        if bot is not None:
            try:
                await asyncio.wait_for(bot.close(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Bot close timed out")
            except Exception:
                logger.exception("Error during bot cleanup")

        # 残タスクのキャンセル
        for task in (bot_task, shutdown_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # シグナルハンドラーの解除
        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.remove_signal_handler(sig)
        except NotImplementedError:
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, signal.SIG_DFL)

        logger.info("Shutdown complete")

        # ログのフラッシュと確実なクローズ
        logging.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
