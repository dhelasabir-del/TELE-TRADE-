"""
Telethon Automated Session Service for RYUS MARKET.
Uses in-memory StringSession instances with Fernet at-rest encryption.
Never creates .session files on disk (designed for ephemeral hosting like Render free tier).
Always disconnects clients after each OTP fetch to strictly conserve RAM (512MB limit).
Never logs session strings, tokens, or passwords.
"""

import asyncio
import re
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError,
    PhoneCodeExpiredError, FloodWaitError, PasswordHashInvalidError
)
from aiogram import Bot

from bot.config import config
from bot.database.queries import log_otp_forward
from bot.utils.crypto import encrypt_session_string, decrypt_session_string
from bot.utils.formatters import escape
from bot.utils.logger import logger


def extract_telegram_code(text: str) -> Optional[str]:
    """Extract 5-digit or 6-digit Telegram login code from message text."""
    if not text:
        return None

    patterns = [
        r"(?:login code|telegram code|code is|code:)\s*[:]?\s*(\d{5,6})",
        r"\b(\d{5})\b",
        r"\b(\d{6})\b"
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def resolve_session_path(session_name_or_path: str) -> Optional[Path]:
    """Resolve full path to an existing legacy session file in data/sessions/ if present."""
    if not session_name_or_path:
        return None
    p = Path(session_name_or_path)
    if p.is_file():
        return p

    candidate = config.SESSIONS_DIR / session_name_or_path
    if candidate.is_file():
        return candidate

    candidate_ext = config.SESSIONS_DIR / f"{session_name_or_path}.session"
    if candidate_ext.is_file():
        return candidate_ext

    return None


def _get_client_from_session(session_identifier: str) -> Tuple[Optional[TelegramClient], Optional[Path]]:
    """
    Construct a Telethon TelegramClient using decrypted StringSession,
    or fallback to legacy file path if a file exists.
    Never logs sensitive session data.
    """
    if not session_identifier:
        return None, None

    # First attempt: treat as encrypted or plain StringSession
    try:
        decrypted = decrypt_session_string(session_identifier).strip()
        # Telethon StringSession typically starts with '1' and is a base64 string
        if decrypted and len(decrypted) > 30 and not decrypted.endswith(".session"):
            client = TelegramClient(
                session=StringSession(decrypted),
                api_id=config.TELEGRAM_API_ID,
                api_hash=config.TELEGRAM_API_HASH
            )
            return client, None
    except Exception:
        pass

    # Second attempt: check if it's a legacy session file on disk
    legacy_path = resolve_session_path(session_identifier)
    if legacy_path:
        base_session = str(legacy_path).removesuffix(".session")
        client = TelegramClient(
            session=base_session,
            api_id=config.TELEGRAM_API_ID,
            api_hash=config.TELEGRAM_API_HASH
        )
        return client, legacy_path

    # Fallback attempt: if it looks like a StringSession string without .session
    if not session_identifier.endswith(".session"):
        try:
            client = TelegramClient(
                session=StringSession(session_identifier),
                api_id=config.TELEGRAM_API_ID,
                api_hash=config.TELEGRAM_API_HASH
            )
            return client, None
        except Exception:
            pass

    return None, None


async def fetch_latest_telegram_code(session_identifier: str) -> Optional[Dict[str, Any]]:
    """
    Connect to a session in-memory, inspect messages from official Telegram (777000),
    and return the latest login code.
    ALWAYS disconnects the client in the finally block to save RAM.
    """
    client, _ = _get_client_from_session(session_identifier)
    if not client:
        logger.warning("Session credentials could not be loaded for code fetch.")
        return None

    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.warning("Session is not authorized or has expired.")
            return None

        messages = await client.get_messages(777000, limit=5)
        for msg in messages:
            if not msg.text:
                continue
            code = extract_telegram_code(msg.text)
            if code:
                return {
                    "otp": code,
                    "message_text": msg.text,
                    "date": msg.date
                }
        return None

    except Exception as e:
        logger.error(f"Error fetching code from session: {e}\n{traceback.format_exc()}")
        return None
    finally:
        # Strict RAM management for Render free tier (512MB)
        try:
            await client.disconnect()
        except Exception:
            pass


async def logout_session(session_identifier: str) -> Tuple[bool, str]:
    """
    Log out the bot's session from Telegram servers and cleanup.
    ALWAYS disconnects the client in finally block.
    """
    client, session_path = _get_client_from_session(session_identifier)
    if not client:
        return True, "Session already terminated."

    try:
        await client.connect()
        if await client.is_user_authorized():
            await client.log_out()
        else:
            await client.disconnect()

        # Clean up legacy local session file if any existed
        if session_path and session_path.exists():
            try:
                session_path.unlink()
            except Exception:
                pass

        return True, "Bot device successfully logged out from this Telegram account."

    except Exception as e:
        logger.warning(f"Session logout note: {e}")
        if session_path and session_path.exists():
            try:
                session_path.unlink()
            except Exception:
                pass
        return True, "Session terminated."
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


_ACTIVE_LISTENERS: Dict[str, asyncio.Task] = {}


async def _session_otp_worker(
    bot: Bot,
    order_id: int,
    order_code: str,
    buyer_tg_id: int,
    phone_number: str,
    session_identifier: str,
    two_fa_password: Optional[str] = None,
    timeout_seconds: int = 600
) -> None:
    """Background worker that waits for incoming OTP from 777000 and disconnects."""
    client, _ = _get_client_from_session(session_identifier)
    if not client:
        logger.warning(f"[_session_otp_worker] Session not found for {order_code}")
        return

    otp_found = asyncio.Event()
    received_data = {}

    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.warning(f"Session not authorized during listener startup for {order_code}.")
            return

        start_time = datetime.now(timezone.utc)

        # Check if code already arrived in last 120 seconds
        recent_msgs = await client.get_messages(777000, limit=3)
        for m in recent_msgs:
            if m.text and (datetime.now(timezone.utc) - m.date).total_seconds() < 120:
                code = extract_telegram_code(m.text)
                if code:
                    received_data["otp"] = code
                    received_data["text"] = m.text
                    otp_found.set()
                    break

        if not otp_found.is_set():
            @client.on(events.NewMessage(from_users=777000))
            async def handler(event):
                if event.raw_text:
                    code = extract_telegram_code(event.raw_text)
                    if code:
                        received_data["otp"] = code
                        received_data["text"] = event.raw_text
                        otp_found.set()

            poll_iterations = max(1, timeout_seconds // 3)
            for _ in range(poll_iterations):
                if otp_found.is_set():
                    break
                await asyncio.sleep(3)
                try:
                    msgs = await client.get_messages(777000, limit=2)
                    for m in msgs:
                        if m.text and m.date >= start_time:
                            code = extract_telegram_code(m.text)
                            if code:
                                received_data["otp"] = code
                                received_data["text"] = m.text
                                otp_found.set()
                                break
                except Exception:
                    pass

        if otp_found.is_set() and "otp" in received_data:
            otp = received_data["otp"]
            msg_text = received_data.get("text", "")

            delivery_text = (
                f"⚡ <b>AUTOMATIC LOGIN CODE RECEIVED!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🧾 <b>Order:</b> <code>{escape(order_code)}</code>\n"
                f"📞 <b>Phone Number:</b> <code>{escape(phone_number)}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔑 <b>Your Telegram Login Code:</b>\n\n"
                f"<code>{escape(otp)}</code>\n\n"
            )
            if two_fa_password:
                delivery_text += f"🔐 <b>2FA Password:</b> <code>{escape(two_fa_password)}</code>\n\n"
            delivery_text += (
                f"📝 <b>Official Notice:</b>\n"
                f"<i>{escape(msg_text[:200])}</i>\n\n"
                f"⚠️ <i>Enter this code in your Telegram app now to complete login.</i>"
            )

            try:
                await bot.send_message(
                    chat_id=buyer_tg_id,
                    text=delivery_text,
                    parse_mode="HTML"
                )
                await log_otp_forward(
                    order_id=order_id,
                    order_code=order_code,
                    buyer_telegram_id=buyer_tg_id,
                    otp_code=otp,
                    admin_telegram_id=0
                )
                logger.info(f"Auto-OTP delivered for {order_code} ({phone_number}) -> {buyer_tg_id}")
            except Exception as e:
                logger.error(f"Failed to send auto-OTP message to {buyer_tg_id}: {e}")

    except Exception as e:
        logger.error(f"Error in _session_otp_worker for {order_code}: {e}\n{traceback.format_exc()}")
    finally:
        # Crucial RAM conservation
        try:
            await client.disconnect()
        except Exception:
            pass
        _ACTIVE_LISTENERS.pop(order_code, None)


def start_auto_otp_listener(
    bot: Bot,
    order_id: int,
    order_code: str,
    buyer_tg_id: int,
    phone_number: str,
    session_file: str,
    two_fa_password: Optional[str] = None,
    timeout_seconds: int = 600
) -> Optional[asyncio.Task]:
    """Launch background task to monitor Telegram official codes on this session."""
    if order_code in _ACTIVE_LISTENERS and not _ACTIVE_LISTENERS[order_code].done():
        logger.info(f"Listener already running for {order_code}")
        return _ACTIVE_LISTENERS[order_code]

    task = asyncio.create_task(
        _session_otp_worker(
            bot=bot,
            order_id=order_id,
            order_code=order_code,
            buyer_tg_id=buyer_tg_id,
            phone_number=phone_number,
            session_identifier=session_file,
            two_fa_password=two_fa_password,
            timeout_seconds=timeout_seconds
        )
    )
    _ACTIVE_LISTENERS[order_code] = task
    return task


# ─── IN-BOT INTERACTIVE SESSION CREATION (StringSession ONLY) ────────────────

_ADMIN_LOGIN_CLIENTS: Dict[int, TelegramClient] = {}


async def start_in_bot_login(admin_tg_id: int, phone_number: str) -> Tuple[bool, str, Optional[str]]:
    """
    Step 1: Connect to Telegram using an in-memory StringSession and request verification code.
    Returns (success, message, phone_code_hash).
    """
    # Clean up previous login attempt if any
    old_client = _ADMIN_LOGIN_CLIENTS.pop(admin_tg_id, None)
    if old_client:
        try:
            await old_client.disconnect()
        except Exception:
            pass

    for attempt in range(3):
        client = TelegramClient(
            session=StringSession(),
            api_id=config.TELEGRAM_API_ID,
            api_hash=config.TELEGRAM_API_HASH
        )
        try:
            await client.connect()
            sent_code = await client.send_code_request(phone_number)
            _ADMIN_LOGIN_CLIENTS[admin_tg_id] = client
            return True, "Code sent", sent_code.phone_code_hash

        except FloodWaitError as e:
            try:
                await client.disconnect()
            except Exception:
                pass
            return False, f"Telegram rate limit: Wait {e.seconds} seconds before requesting another code.", None

        except Exception as ex:
            try:
                await client.disconnect()
            except Exception:
                pass
            if "AuthRestartError" in type(ex).__name__ or "restart" in str(ex).lower() or "disconnected" in str(ex).lower():
                await asyncio.sleep(1.5)
                continue
            logger.error(f"In-bot login start failed: {ex}")
            return False, str(ex), None

    return False, "Telegram requested restart. Please try again in a few seconds.", None


async def submit_in_bot_code(
    admin_tg_id: int,
    phone_number: str,
    phone_code_hash: str,
    code: str,
    preset_2fa: Optional[str] = None
) -> Tuple[bool, str, bool, Optional[str]]:
    """
    Step 2: Sign in with the code received.
    Returns (success, display_name_or_error, needs_2fa, encrypted_session_string).
    Disconnects client immediately after login to save memory.
    """
    client = _ADMIN_LOGIN_CLIENTS.get(admin_tg_id)
    if not client:
        return False, "Login session expired. Please start over.", False, None

    clean_phone = phone_number.replace("+", "").replace(" ", "").replace("-", "")

    try:
        await client.sign_in(phone=phone_number, code=code, phone_code_hash=phone_code_hash)
        me = await client.get_me()
        session_str = client.session.save()
        await client.disconnect()
        _ADMIN_LOGIN_CLIENTS.pop(admin_tg_id, None)

        enc_session = encrypt_session_string(session_str)
        return True, me.first_name or f"User {clean_phone}", False, enc_session

    except SessionPasswordNeededError:
        # If admin already entered 2FA, try it automatically
        if preset_2fa:
            try:
                await client.sign_in(password=preset_2fa)
                me = await client.get_me()
                session_str = client.session.save()
                await client.disconnect()
                _ADMIN_LOGIN_CLIENTS.pop(admin_tg_id, None)
                enc_session = encrypt_session_string(session_str)
                return True, me.first_name or f"User {clean_phone}", False, enc_session
            except Exception:
                pass
        # Needs explicit 2FA password prompt
        return False, "2FA Password is required.", True, None

    except PhoneCodeInvalidError:
        return False, "⚠️ Invalid verification code. Please check and try again.", False, None
    except PhoneCodeExpiredError:
        await client.disconnect()
        _ADMIN_LOGIN_CLIENTS.pop(admin_tg_id, None)
        return False, "⚠️ The verification code has expired. Please restart the process.", False, None
    except Exception as e:
        logger.error(f"In-bot sign-in error: {e}")
        return False, str(e), False, None


async def submit_in_bot_2fa(
    admin_tg_id: int,
    phone_number: str,
    password: str
) -> Tuple[bool, str, Optional[str]]:
    """
    Step 3 (if needed): Sign in with 2FA password.
    Returns (success, display_name_or_error, encrypted_session_string).
    Disconnects client immediately after login.
    """
    client = _ADMIN_LOGIN_CLIENTS.get(admin_tg_id)
    if not client:
        return False, "Login session expired. Please start over.", None

    clean_phone = phone_number.replace("+", "").replace(" ", "").replace("-", "")

    try:
        await client.sign_in(password=password)
        me = await client.get_me()
        session_str = client.session.save()
        await client.disconnect()
        _ADMIN_LOGIN_CLIENTS.pop(admin_tg_id, None)

        enc_session = encrypt_session_string(session_str)
        return True, me.first_name or f"User {clean_phone}", enc_session

    except PasswordHashInvalidError:
        return False, "⚠️ Incorrect 2FA password. Please try again.", None
    except Exception as e:
        await client.disconnect()
        _ADMIN_LOGIN_CLIENTS.pop(admin_tg_id, None)
        logger.error(f"In-bot 2FA sign-in error: {e}")
        return False, str(e), None


def cancel_in_bot_login(admin_tg_id: int):
    """Cleanup and disconnect any pending in-bot login client."""
    client = _ADMIN_LOGIN_CLIENTS.pop(admin_tg_id, None)
    if client:
        try:
            asyncio.create_task(client.disconnect())
        except Exception:
            pass
