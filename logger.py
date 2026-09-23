"""集中式 logging 設定模組。

提供 `setup_logging()` 建立 console 與 RotatingFileHandler 雙通道,
以及 `get_logger(name)` 給各模組取得統一格式的 logger。所有模組皆應
透過本模組取得 logger,禁止在其他模組呼叫 `logging.basicConfig`。
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_FILE = LOG_DIR / "fall_detect.log"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s %(filename)s:%(lineno)d - %(message)s"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5

_configured = False


def _ensure_utf8_streams() -> None:
    """將 stdout/stderr 重新設為 UTF-8。

    Windows 主控台預設編碼可能是 Big5(cp950)等非 UTF-8 編碼,中文字元
    輸出到終端或被外部程序擷取時會出現亂碼,故在程式進入點統一修正。
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def setup_logging(level: int = logging.INFO) -> None:
    """設定 root logger 的 console 與檔案雙輸出通道。

    應在程式進入點呼叫一次;重複呼叫不會疊加 handler,避免日誌重複輸出。

    Args:
        level: 記錄等級,預設 INFO。
    """
    global _configured
    if _configured:
        return

    _ensure_utf8_streams()
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """取得指定名稱的 logger。

    Args:
        name: 通常傳入呼叫端模組的 `__name__`。

    Returns:
        對應名稱的 logger 實例;實際輸出行為由 `setup_logging()` 決定。
    """
    return logging.getLogger(name)
