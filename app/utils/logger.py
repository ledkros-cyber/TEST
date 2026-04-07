"""Centralized app logger — writes to data/ytgen.log (rotating, max 5MB × 3 files).

Usage:
    from app.utils.logger import log
    log.info("message")
    log.error("error happened", exc_info=True)
    log.api("MiniMax", "POST /v1/t2a_v2", status=200)
"""
import logging
import logging.handlers
import os

_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "ytgen.log"
)

def _setup() -> logging.Logger:
    os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
    logger = logging.getLogger("ytgen")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    # Rotating file handler: 5MB per file, keep 3 files
    fh = logging.handlers.RotatingFileHandler(
        _LOG_PATH, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(module)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger

class AppLogger:
    def __init__(self):
        self._logger = _setup()

    def debug(self, msg, **kw):   self._logger.debug(msg, **kw)
    def info(self, msg, **kw):    self._logger.info(msg, **kw)
    def warning(self, msg, **kw): self._logger.warning(msg, **kw)
    def error(self, msg, **kw):   self._logger.error(msg, **kw)

    def api(self, service: str, endpoint: str, status: int = 0, error: str = ""):
        """Log an API call result."""
        if error:
            self._logger.error(f"API [{service}] {endpoint} → ERROR: {error}")
        else:
            self._logger.info(f"API [{service}] {endpoint} → HTTP {status} OK")

    def get_recent(self, lines: int = 200) -> str:
        """Return last N lines from the log file."""
        try:
            with open(_LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
            return "".join(all_lines[-lines:])
        except FileNotFoundError:
            return "(No log file yet)"
        except Exception as e:
            return f"(Error reading log: {e})"

log = AppLogger()
