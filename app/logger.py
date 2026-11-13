"""统一日志配置（带轮转，防磁盘爆满）。"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from config import settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def get_logger(name: str = "rag") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(logging.Formatter(_LOG_FORMAT))
        logger.addHandler(stream)
        # 文件日志（轮转：单文件 50MB，最多保留 5 个备份）
        try:
            log_file = settings.docs_dir.parent / "rag_server.log"
            fh = RotatingFileHandler(
                str(log_file),
                maxBytes=50 * 1024 * 1024,  # 50 MB
                backupCount=5,
                encoding="utf-8",
            )
            fh.setFormatter(logging.Formatter(_LOG_FORMAT))
            logger.addHandler(fh)
        except Exception:
            pass
        logger.propagate = False
    return logger
