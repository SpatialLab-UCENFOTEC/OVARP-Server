"""
Open Virtual Agent Research Platform (OVARP) — Logging Setup

Wires the two logging channels the platform relies on: a rotating file handler
for post-hoc review, and a WebSocket handler that streams every record to the
WoZ console's System Logs tab.

Author: Alexander Barquero Elizondo, Ph.D. — UCR, ECCI/CITIC
License: MIT
"""

import asyncio
import json
import logging
import os
from logging.handlers import RotatingFileHandler

LOG_FORMAT = "%(asctime)s - [%(levelname)s] - %(name)s - %(message)s"
MAX_LOG_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 5

# Sockets currently subscribed to /ws/logs
log_subscribers = []


class WebsocketLogHandler(logging.Handler):
    """Fans every log record out to the consoles listening on /ws/logs."""

    def emit(self, record):
        try:
            if not log_subscribers:
                return
            payload = json.dumps({
                "level": record.levelname,
                "name": record.name,
                "message": self.format(record),
            })
            loop = asyncio.get_running_loop()
            for conn in list(log_subscribers):
                try:
                    loop.create_task(conn.send_text(payload))
                except Exception:
                    pass
        except Exception:
            pass


def configure_logging():
    """Attach the file and WebSocket handlers to the root and OVARP loggers."""
    log_dir = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file_path = os.path.join(log_dir, "OVARP_server.log")

    formatter = logging.Formatter(LOG_FORMAT)

    ws_handler = WebsocketLogHandler()
    ws_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_file_path, maxBytes=MAX_LOG_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(ws_handler)
    root_logger.addHandler(file_handler)

    # OVARP.<module> loggers do not propagate, so they need the handlers directly
    ovarp_logger = logging.getLogger("OVARP")
    ovarp_logger.setLevel(logging.DEBUG)
    ovarp_logger.addHandler(ws_handler)
    ovarp_logger.addHandler(file_handler)
    ovarp_logger.propagate = False

    for name in ("uvicorn.access", "uvicorn.error", "fastapi"):
        logging.getLogger(name).addHandler(ws_handler)
        logging.getLogger(name).addHandler(file_handler)
