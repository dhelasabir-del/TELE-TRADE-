"""
Cryptography utilities for RYUS MARKET.
Provides symmetric at-rest encryption for Telethon StringSession credentials
using Fernet (AES-128-CBC + HMAC-SHA256).
"""

import base64
import hashlib
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken

from bot.config import config
from bot.utils.logger import logger

_fernet_instance: Optional[Fernet] = None


def get_fernet() -> Fernet:
    """Initialize and cache the Fernet instance using ENCRYPTION_KEY."""
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance

    raw_key = config.ENCRYPTION_KEY
    if not raw_key:
        logger.warning(
            "⚠️ ENCRYPTION_KEY is not set in environment! "
            "Falling back to bot-token-derived key. For production, set ENCRYPTION_KEY in .env."
        )
        # Derive a stable 32-byte urlsafe base64 key from BOT_TOKEN if ENCRYPTION_KEY not supplied
        seed = (config.BOT_TOKEN or "RYUS_MARKET_DEFAULT_SECRET_KEY").encode("utf-8")
        digest = hashlib.sha256(seed).digest()
        raw_key = base64.urlsafe_b64encode(digest).decode("utf-8")

    try:
        # Validate Fernet key
        _fernet_instance = Fernet(raw_key.encode("utf-8"))
    except Exception as e:
        logger.error(f"Invalid ENCRYPTION_KEY format: {e}. Deriving safe fallback key.")
        seed = raw_key.encode("utf-8")
        digest = hashlib.sha256(seed).digest()
        fallback_key = base64.urlsafe_b64encode(digest).decode("utf-8")
        _fernet_instance = Fernet(fallback_key.encode("utf-8"))

    return _fernet_instance


def encrypt_session_string(plain_session: str) -> str:
    """
    Encrypt a Telethon StringSession string for storage in PostgreSQL.
    Returns empty string if input is empty. Never logs the plain session.
    """
    if not plain_session:
        return ""
    try:
        f = get_fernet()
        encrypted_bytes = f.encrypt(plain_session.encode("utf-8"))
        return encrypted_bytes.decode("utf-8")
    except Exception as e:
        logger.error(f"Failed to encrypt session string: {e}")
        return plain_session


def decrypt_session_string(encrypted_session: str) -> str:
    """
    Decrypt a stored session string into memory.
    If the string is not encrypted (e.g. legacy plain StringSession),
    gracefully returns the raw string. Never logs the decrypted session.
    """
    if not encrypted_session:
        return ""
    try:
        f = get_fernet()
        decrypted_bytes = f.decrypt(encrypted_session.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except (InvalidToken, Exception):
        # Raw session string or already plain text
        return encrypted_session
