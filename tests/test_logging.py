"""Tests for structured logging configuration."""

from __future__ import annotations

import json
import logging
from logging.handlers import TimedRotatingFileHandler
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from discord_acp_bridge.infrastructure.logging import configure_logging, get_logger


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    """各テスト前にルートロガーのハンドラーをリセットする."""
    root = logging.getLogger()
    root.handlers.clear()


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    """テスト用の一時ログディレクトリを返す."""
    return tmp_path / "logs"


class TestConfigureLogging:
    """configure_logging のテスト."""

    def test_creates_log_directory(self, log_dir: Path) -> None:
        """ログディレクトリが自動作成されることを確認する."""
        assert not log_dir.exists()
        configure_logging(log_dir=str(log_dir))
        assert log_dir.is_dir()

    def test_creates_nested_log_directory(self, tmp_path: Path) -> None:
        """ネストされたログディレクトリが自動作成されることを確認する."""
        nested = tmp_path / "a" / "b" / "logs"
        configure_logging(log_dir=str(nested))
        assert nested.is_dir()

    def test_three_handlers_added(self, log_dir: Path) -> None:
        """ルートロガーに3つのハンドラーが追加されることを確認する."""
        configure_logging(log_dir=str(log_dir))
        root = logging.getLogger()
        assert len(root.handlers) == 3

    def test_console_handler_stderr(self, log_dir: Path) -> None:
        """コンソールハンドラーがstderrに出力することを確認する."""
        configure_logging(log_dir=str(log_dir))
        root = logging.getLogger()
        stream_handlers = [
            h
            for h in root.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, TimedRotatingFileHandler)
        ]
        assert len(stream_handlers) == 1
        assert stream_handlers[0].level == logging.ERROR

    def test_latest_log_handler(self, log_dir: Path) -> None:
        """latest.logハンドラーが全レベルで設定されることを確認する."""
        configure_logging(log_dir=str(log_dir))
        root = logging.getLogger()
        file_handlers = [
            h for h in root.handlers if isinstance(h, TimedRotatingFileHandler)
        ]
        latest_handlers = [
            h for h in file_handlers if "latest.log" in str(h.baseFilename)
        ]
        assert len(latest_handlers) == 1
        assert latest_handlers[0].level == logging.DEBUG

    def test_error_log_handler(self, log_dir: Path) -> None:
        """error.logハンドラーがWARNING以上で設定されることを確認する."""
        configure_logging(log_dir=str(log_dir))
        root = logging.getLogger()
        file_handlers = [
            h for h in root.handlers if isinstance(h, TimedRotatingFileHandler)
        ]
        error_handlers = [
            h for h in file_handlers if "error.log" in str(h.baseFilename)
        ]
        assert len(error_handlers) == 1
        assert error_handlers[0].level == logging.WARNING

    def test_file_handler_rotation_config(self, log_dir: Path) -> None:
        """ファイルハンドラーのローテーション設定を確認する."""
        configure_logging(log_dir=str(log_dir), log_backup_count=14)
        root = logging.getLogger()
        file_handlers = [
            h for h in root.handlers if isinstance(h, TimedRotatingFileHandler)
        ]
        for handler in file_handlers:
            assert handler.when == "MIDNIGHT"  # TimedRotatingFileHandler normalizes
            assert handler.backupCount == 14
            assert handler.suffix == "%Y-%m-%d"

    def test_invalid_log_level_defaults_to_info(
        self,
        log_dir: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """無効なログレベルの場合INFOにフォールバックすることを確認する."""
        configure_logging(log_level="INVALID", log_dir=str(log_dir))
        captured = capsys.readouterr()
        assert "Invalid log level" in captured.err

    def test_clears_existing_handlers(self, log_dir: Path) -> None:
        """既存のハンドラーがクリアされることを確認する."""
        root = logging.getLogger()
        marker = logging.StreamHandler()
        root.addHandler(marker)

        configure_logging(log_dir=str(log_dir))
        # マーカーハンドラーがクリアされていることを確認
        assert marker not in root.handlers

    def test_discord_log_levels(self, log_dir: Path) -> None:
        """サードパーティライブラリのログレベルが調整されることを確認する."""
        configure_logging(log_dir=str(log_dir))
        assert logging.getLogger("discord").level == logging.INFO
        assert logging.getLogger("discord.http").level == logging.WARNING

    def test_fallback_on_directory_creation_failure(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """ログディレクトリ作成失敗時にコンソールのみで継続することを確認する."""
        # 書き込み不可なファイルを作成してディレクトリ作成を阻害
        blocker = tmp_path / "blocked"
        blocker.write_text("")
        blocker.chmod(0o444)
        bad_dir = str(blocker / "logs")

        configure_logging(log_dir=bad_dir)

        captured = capsys.readouterr()
        assert "Failed to create log directory" in captured.err
        # コンソールハンドラーのみが残る（ファイルハンドラーなし）
        root = logging.getLogger()
        file_handlers = [
            h for h in root.handlers if isinstance(h, TimedRotatingFileHandler)
        ]
        assert len(file_handlers) == 0


class TestFileOutput:
    """ファイル出力のテスト."""

    def test_latest_log_receives_all_levels(self, log_dir: Path) -> None:
        """latest.logに全レベルのログが書き込まれることを確認する."""
        configure_logging(log_level="DEBUG", log_dir=str(log_dir))
        logger = get_logger("test")

        logger.debug("debug msg")
        logger.info("info msg")
        logger.warning("warning msg")
        logger.error("error msg")

        # ハンドラーをフラッシュ
        for handler in logging.getLogger().handlers:
            handler.flush()

        latest = (log_dir / "latest.log").read_text()
        assert "debug msg" in latest
        assert "info msg" in latest
        assert "warning msg" in latest
        assert "error msg" in latest

    def test_error_log_receives_warning_and_above(self, log_dir: Path) -> None:
        """error.logにWARNING以上のログのみ書き込まれることを確認する."""
        configure_logging(log_level="DEBUG", log_dir=str(log_dir))
        logger = get_logger("test")

        logger.debug("debug msg")
        logger.info("info msg")
        logger.warning("warning msg")
        logger.error("error msg")

        for handler in logging.getLogger().handlers:
            handler.flush()

        error_log = (log_dir / "error.log").read_text()
        assert "debug msg" not in error_log
        assert "info msg" not in error_log
        assert "warning msg" in error_log
        assert "error msg" in error_log

    def test_log_output_is_json(self, log_dir: Path) -> None:
        """ログ出力がJSON形式であることを確認する."""
        configure_logging(log_dir=str(log_dir))
        logger = get_logger("test")
        logger.error("json test", key="value")

        for handler in logging.getLogger().handlers:
            handler.flush()

        latest = (log_dir / "latest.log").read_text().strip()
        # 各行が有効なJSONであることを確認
        for line in latest.splitlines():
            data = json.loads(line)
            assert "event" in data


class TestGetLogger:
    """get_logger のテスト."""

    def test_returns_logger(self, log_dir: Path) -> None:
        """get_loggerがロガーを返すことを確認する."""
        configure_logging(log_dir=str(log_dir))
        logger = get_logger(__name__)
        assert hasattr(logger, "info")
        assert hasattr(logger, "debug")
        assert hasattr(logger, "warning")
        assert hasattr(logger, "error")

    def test_with_name(self, log_dir: Path) -> None:
        """ロガー名を指定してロガーを取得できることを確認する."""
        configure_logging(log_dir=str(log_dir))
        logger = get_logger("test.module")
        assert hasattr(logger, "info")
