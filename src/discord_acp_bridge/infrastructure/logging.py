"""Structured logging configuration."""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(log_level: str = "INFO") -> None:
    """
    構造化ロギングを設定する.

    Args:
        log_level: ログレベル（DEBUG, INFO, WARNING, ERROR, CRITICAL）
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

    # ログレベルを設定
    numeric_level = getattr(logging, log_level_upper, logging.INFO)

    # 標準loggingの設定
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
    )

    # structlogの設定
    structlog.configure(
        processors=[
            # イベント辞書にログレベルを追加
            structlog.stdlib.add_log_level,
            # イベント辞書にタイムスタンプを追加
            structlog.processors.TimeStamper(fmt="iso"),
            # スタックトレース情報を追加
            structlog.processors.StackInfoRenderer(),
            # 例外情報をフォーマット
            structlog.processors.format_exc_info,
            # イベント辞書をUnicodeにデコード
            structlog.processors.UnicodeDecoder(),
            # JSONとしてフォーマット
            structlog.processors.JSONRenderer(),
        ],
        # 標準loggingと統合
        wrapper_class=structlog.stdlib.BoundLogger,
        # ロガーファクトリー
        logger_factory=structlog.stdlib.LoggerFactory(),
        # キャッシュを有効化
        cache_logger_on_first_use=True,
    )

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
