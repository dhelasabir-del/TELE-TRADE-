"""Logging configuration for RYUS MARKET Bot."""

import logging
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


# Create logs directory
log_dir = Path(__file__).resolve().parent.parent.parent / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / "bot.log"

logger = logging.getLogger("ryus_market")
logger.setLevel(logging.INFO)

# Formatter
formatter = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# Console handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# File handler
try:
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
except Exception:
    pass
