"""
Colored logging configuration for terminal output.

Usage:
    from colors import get_logger, setup_logging

    setup_logging()  # call once in main()
    log = get_logger(__name__)

    log.info("Processing...")
    log.success("✓ Done")       # custom level (25)
    log.warning("⚠ Watch out")
    log.error("✗ Something broke")
"""

import logging
import sys

# Custom SUCCESS level between INFO(20) and WARNING(30)
SUCCESS = 25
logging.addLevelName(SUCCESS, "SUCCESS")


class ColoredLogger(logging.Logger):
    """Logger subclass with a typed ``success()`` method."""

    def success(self, message: object, *args, **kwargs) -> None:
        if self.isEnabledFor(SUCCESS):
            self._log(SUCCESS, message, args, **kwargs)


logging.setLoggerClass(ColoredLogger)


def get_logger(name: str) -> ColoredLogger:
    """Return a logger with the ``success()`` method visible to type checkers."""
    return logging.getLogger(name)  # type: ignore[return-value]


class ColoredFormatter(logging.Formatter):
    """Formatter that adds ANSI colors based on log level."""

    COLORS = {
        logging.DEBUG: "\033[2m",       # dim
        logging.INFO: "\033[36m",       # cyan
        SUCCESS: "\033[32m",            # green
        logging.WARNING: "\033[33m",    # yellow
        logging.ERROR: "\033[31m",      # red
        logging.CRITICAL: "\033[1;31m", # bold red
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, "")
        message = super().format(record)
        if color:
            return f"{color}{message}{self.RESET}"
        return message


def setup_logging(level: int = logging.DEBUG) -> None:
    """Configure the root logger with colored console output."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColoredFormatter("%(message)s"))
    root = logging.getLogger()
    root.setLevel(level)
    # Avoid duplicate handlers on repeated calls
    root.handlers = [handler]
