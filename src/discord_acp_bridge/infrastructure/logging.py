"""Structured logging configuration."""

from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import structlog


def configure_logging(
    log_level: str = "INFO",
    log_dir: str = "logs",
    log_backup_count: int = 7,
) -> None:
    """
    構造化ロギングを設定する.

    3つの出力先にログを配信する:
    - コンソール (stderr): ERROR以上
    - logs/latest.log: 全レベル (DEBUG〜)
    - logs/error.log: WARNING以上

    Args:
        log_level: ログレベル（DEBUG, INFO, WARNING, ERROR, CRITICAL）
                   注意: 現在このパラメータは使用されていません。
                   各ハンドラーのレベルは固定です（将来の拡張用に予約）。
        log_dir: ログ出力ディレクトリ
        log_backup_count: ログローテーションの保持日数
    """
    # 無効なログレベルをチェック
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    log_level_upper = log_level.upper()
    if log_level_upper not in valid_levels:
        print(
            f"Warning: Invalid log level '{log_level}', defaulting to INFO",
            file=sys.stderr,
        )
        log_level_upper = "INFO"

    # structlogの共有プロセッサ
    shared_processors: list[structlog.types.Processor] = [
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    # structlogの設定
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # JSONフォーマッター（ファイル出力用）
    json_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    # ルートロガーの設定
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    # 既存のハンドラーをクリア
    root_logger.handlers.clear()

    # 1. コンソールハンドラー (stderr, ERROR以上)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.ERROR)
    console_handler.setFormatter(json_formatter)
    root_logger.addHandler(console_handler)

    # 2-3. ファイルハンドラー
    log_path = Path(log_dir)
    try:
        log_path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(
            f"Warning: Failed to create log directory '{log_dir}': {e}. "
            "Falling back to console-only logging.",
            file=sys.stderr,
        )
        return

    # latest.log: 全レベル、日次ローテーション
    latest_handler = TimedRotatingFileHandler(
        log_path / "latest.log",
        when="midnight",
        backupCount=log_backup_count,
        encoding="utf-8",
    )
    latest_handler.suffix = "%Y-%m-%d"
    latest_handler.setLevel(logging.DEBUG)
    latest_handler.setFormatter(json_formatter)
    root_logger.addHandler(latest_handler)

    # error.log: WARNING以上、日次ローテーション
    error_handler = TimedRotatingFileHandler(
        log_path / "error.log",
        when="midnight",
        backupCount=log_backup_count,
        encoding="utf-8",
    )
    error_handler.suffix = "%Y-%m-%d"
    error_handler.setLevel(logging.WARNING)
    error_handler.setFormatter(json_formatter)
    root_logger.addHandler(error_handler)

    # サードパーティライブラリのログレベル調整
    logging.getLogger("discord").setLevel(logging.INFO)
    logging.getLogger("discord.http").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    構造化ロガーを取得する.

    Args:
        name: ロガー名（通常は __name__ を指定）

    Returns:
        構造化ロガー
    """
    return structlog.get_logger(name)  # type: ignore[no-any-return]
