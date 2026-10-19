"""Configuration settings for RYUS MARKET Telegram Bot."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
BASE_DIR = Path(__file__).resolve().parent.parent
env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path)


class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()

    # Admin IDs: parse comma-separated integers
    _raw_admin_ids = os.getenv("ADMIN_IDS", "")
    ADMIN_IDS: set[int] = set()
    for aid in _raw_admin_ids.split(","):
        aid = aid.strip()
        if aid.isdigit():
            ADMIN_IDS.add(int(aid))

    # Database: read DATABASE_URL for PostgreSQL; fallback to local SQLite DATABASE_PATH
    DATABASE_URL: str = os.getenv("DATABASE_URL", "").strip()
    DATABASE_PATH: Path = BASE_DIR / os.getenv("DATABASE_PATH", "data/marketplace.db")

    # Payment config (UPI)
    UPI_ID: str = os.getenv("UPI_ID", "sahil69@fam").strip()
    UPI_PAYEE_NAME: str = os.getenv("UPI_PAYEE_NAME", "RYUS MARKET").strip()
    MIN_DEPOSIT_INR: float = float(os.getenv("MIN_DEPOSIT_INR", "50.0"))
    CURRENCY_SYMBOL: str = os.getenv("CURRENCY_SYMBOL", "₹").strip()

    # Support Contact
    SUPPORT_CONTACT: str = os.getenv("SUPPORT_CONTACT", "@Cheenihu").strip()

    # Rate limiting & Anti-abuse
    RATE_LIMIT_DELAY: float = float(os.getenv("RATE_LIMIT_DELAY", "0.5"))
    ORDER_EXPIRY_MINUTES: int = int(os.getenv("ORDER_EXPIRY_MINUTES", "15"))

    # Web service port for Render health check endpoint
    PORT: int = int(os.getenv("PORT", "8080"))

    # Telethon / Telegram Client (API_ID, API_HASH)
    TELEGRAM_API_ID: int = int(os.getenv("TELEGRAM_API_ID", os.getenv("API_ID", "2040")))
    TELEGRAM_API_HASH: str = os.getenv("TELEGRAM_API_HASH", os.getenv("API_HASH", "b18441a1ff607e10a989891a5462e627")).strip()
    SESSIONS_DIR: Path = BASE_DIR / "data" / "sessions"

    # Encryption key for Fernet session strings at rest
    ENCRYPTION_KEY: str = os.getenv("ENCRYPTION_KEY", "").strip()

    @classmethod
    def is_admin(cls, user_id: int) -> bool:
        """Check if a given Telegram user ID is an authorized administrator."""
        return user_id in cls.ADMIN_IDS

    @classmethod
    def ensure_directories(cls):
        """Ensure necessary runtime directories exist."""
        cls.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        (BASE_DIR / "data" / "qr").mkdir(parents=True, exist_ok=True)
        cls.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


config = Config()
config.ensure_directories()
