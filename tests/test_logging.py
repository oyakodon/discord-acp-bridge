"""Tests for structured logging configuration."""

from __future__ import annotations

import logging

import pytest

from discord_acp_bridge.infrastructure.logging import configure_logging, get_logger


def test_configure_logging_default() -> None:
    """デフォルト設定でログが正しく設定されることを確認する."""
    configure_logging()

    # ルートロガーにhandlerが設定されていることを確認
    root_logger = logging.getLogger()
    assert len(root_logger.handlers) > 0


def test_configure_logging_custom_level() -> None:
    """カスタムログレベルが正しく設定されることを確認する."""
    # DEBUG設定で初期化
    configure_logging(log_level="DEBUG")

    # ロガーが取得できることを確認
    logger = get_logger(__name__)
    assert logger is not None

    # ルートロガーにhandlerが設定されていることを確認
    root_logger = logging.getLogger()
    assert len(root_logger.handlers) > 0


def test_configure_logging_invalid_level() -> None:
    """無効なログレベルの場合でもエラーが発生しないことを確認する."""
    # 無効なログレベルを指定してもエラーにならないことを確認
    configure_logging(log_level="INVALID")

    # ロガーが取得できることを確認
    logger = get_logger(__name__)
    assert logger is not None


def test_get_logger_returns_logger() -> None:
    """get_logger がロガーを返すことを確認する."""
    configure_logging()

    logger = get_logger(__name__)
    # structlogのロガーであることを確認（プロキシまたはBoundLogger）
    assert hasattr(logger, "info")
    assert hasattr(logger, "debug")
    assert hasattr(logger, "warning")
    assert hasattr(logger, "error")


def test_get_logger_with_name() -> None:
    """ロガー名を指定してロガーを取得できることを確認する."""
    configure_logging()

    logger = get_logger("test.module")
    # ロガーのメソッドが存在することを確認
    assert hasattr(logger, "info")


def test_logger_basic_logging(caplog: pytest.LogCaptureFixture) -> None:
    """基本的なログ出力が機能することを確認する."""
    configure_logging(log_level="INFO")

    # キャプチャのログレベルを設定
    caplog.set_level(logging.INFO)

    logger = get_logger(__name__)
    logger.info("test message", key="value")

    # ログが記録されていることを確認
    assert len(caplog.records) > 0
    # メッセージが含まれることを確認
    assert any("test message" in record.message for record in caplog.records)


def test_logger_respects_log_level(caplog: pytest.LogCaptureFixture) -> None:
    """ログレベルが正しく適用されることを確認する."""
    configure_logging(log_level="WARNING")

    # キャプチャのログレベルを設定
    caplog.set_level(logging.WARNING)

    logger = get_logger(__name__)

    # WARNINGレベルのログは記録される
    logger.warning("warning message")
    warning_count = sum(1 for r in caplog.records if "warning message" in r.message)
    assert warning_count > 0

    # ERRORレベルのログも記録される
    logger.error("error message")
    error_count = sum(1 for r in caplog.records if "error message" in r.message)
    assert error_count > 0
