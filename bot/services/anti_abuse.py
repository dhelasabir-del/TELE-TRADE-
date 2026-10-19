"""
Anti-abuse service for RYUS MARKET.
Handles strikes, escalating cooldowns (5 min, 30 min, auto-ban),
30-day strike expiration, verified payment strike removal,
single pending order enforcement, and admin alerts.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List, Tuple
from aiogram import Bot

from bot.config import config
from bot.database.database import get_db, is_postgres
from bot.database.models import User, Deposit
from bot.database.queries import (
    get_user_by_id, get_user_by_telegram_id,
    set_user_blocked, _row_to_deposit, _DEPOSIT_SELECT
)
from bot.utils.formatters import escape, fmt
from bot.utils.logger import logger


def _parse_timestamp(val: Any) -> datetime:
    """Safely parse a datetime or string timestamp into a UTC datetime object."""
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    if not val:
        return datetime.now(timezone.utc)

    # Standard formats
    for fmt_str in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            dt = datetime.strptime(str(val).split("+")[0].strip(), fmt_str)
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


def format_duration(seconds: float) -> str:
    """Format seconds into readable Xm Ys format."""
    secs = max(0, int(seconds))
    mins = secs // 60
    rem_secs = secs % 60
    if mins > 0:
        return f"{mins}m {rem_secs:02d}s"
    return f"{rem_secs}s"


async def get_user_strikes(user_id: int) -> List[Dict[str, Any]]:
    """Retrieve all strike records for a user from database."""
    async with get_db() as conn:
        cur = await conn.execute(
            """SELECT id, user_id, telegram_id, reason, is_active, created_at
               FROM strikes WHERE user_id=? ORDER BY id DESC""",
            (user_id,)
        )
        rows = await cur.fetchall()
        strikes = []
        for r in rows:
            strikes.append({
                "id": r["id"],
                "user_id": r["user_id"],
                "telegram_id": r["telegram_id"],
                "reason": r["reason"],
                "is_active": bool(r["is_active"]),
                "created_at": r["created_at"],
                "dt": _parse_timestamp(r["created_at"])
            })
        return strikes


async def get_user_strike_status(user_id: int) -> Dict[str, Any]:
    """
    Evaluate user strike count, cooldowns, and ban status.
    - Strikes expire after 30 days of good behavior.
    - 1st strike = 5 minutes cooldown from strike timestamp.
    - 2nd strike = 30 minutes cooldown from strike timestamp.
    - 3rd strike = auto-ban.
    """
    user = await get_user_by_id(user_id)
    is_banned = bool(user and user.is_blocked)

    all_strikes = await get_user_strikes(user_id)
    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)

    # Active strikes: is_active == 1 AND within last 30 days
    active_strikes = [
        s for s in all_strikes
        if s["is_active"] and s["dt"] >= thirty_days_ago
    ]
    active_count = len(active_strikes)

    in_cooldown = False
    remaining_secs = 0.0
    latest_reason = ""

    if active_count >= 3:
        is_banned = True
        if active_strikes:
            latest_reason = active_strikes[0]["reason"]
    elif active_count == 2:
        latest = active_strikes[0]
        latest_reason = latest["reason"]
        elapsed = (now - latest["dt"]).total_seconds()
        cooldown_total = 30 * 60.0  # 30 minutes
        if elapsed < cooldown_total:
            in_cooldown = True
            remaining_secs = cooldown_total - elapsed
    elif active_count == 1:
        latest = active_strikes[0]
        latest_reason = latest["reason"]
        elapsed = (now - latest["dt"]).total_seconds()
        cooldown_total = 5 * 60.0  # 5 minutes
        if elapsed < cooldown_total:
            in_cooldown = True
            remaining_secs = cooldown_total - elapsed

    return {
        "user_id": user_id,
        "is_banned": is_banned,
        "active_strikes_count": active_count,
        "total_strikes_count": len(all_strikes),
        "in_cooldown": in_cooldown,
        "cooldown_remaining_seconds": remaining_secs,
        "cooldown_formatted": format_duration(remaining_secs),
        "latest_strike_reason": latest_reason,
        "strikes": all_strikes
    }


async def add_strike(
    user_id: int,
    telegram_id: int,
    reason: str,
    bot: Optional[Bot] = None
) -> Tuple[int, bool, float]:
    """
    Add a strike to a user account.
    Returns: (active_strikes_count, was_auto_banned, cooldown_seconds)
    Triggers auto-ban and notifies admins when strike count reaches 3.
    """
    logger.warning(f"Adding strike to user {user_id} (TG: {telegram_id}): {reason}")
    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO strikes (user_id, telegram_id, reason, is_active)
               VALUES (?, ?, ?, 1)""",
            (user_id, telegram_id, reason)
        )
        await conn.commit()

    status = await get_user_strike_status(user_id)
    active_count = status["active_strikes_count"]
    was_auto_banned = False

    if active_count >= 3:
        # Auto-ban user
        await set_user_blocked(user_id, True)
        was_auto_banned = True
        logger.warning(f"User {user_id} (TG: {telegram_id}) AUTO-BANNED after reaching {active_count} strikes!")

        # Notify admins
        if bot:
            user = await get_user_by_id(user_id)
            user_disp = user.display_name if user else f"User {telegram_id}"
            alert = (
                f"🚨 <b>ANTI-ABUSE ALERT: USER AUTO-BANNED</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>User:</b> {escape(user_disp)} (ID: <code>{user_id}</code>)\n"
                f"🆔 <b>Telegram ID:</b> <code>{telegram_id}</code>\n"
                f"⚠️ <b>Active Strikes:</b> <code>{active_count}/3</code>\n"
                f"📝 <b>Latest Trigger:</b> <i>{escape(reason)}</i>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🛡️ <i>User account has been automatically suspended.</i>"
            )
            for aid in config.ADMIN_IDS:
                try:
                    await bot.send_message(chat_id=aid, text=alert, parse_mode="HTML")
                except Exception as ex:
                    logger.warning(f"Could not alert admin {aid} of auto-ban: {ex}")

    return active_count, was_auto_banned, status["cooldown_remaining_seconds"]


async def remove_strike_for_verified_payment(user_id: int) -> bool:
    """
    Rule 12: A verified payment removes one strike.
    Deactivates the most recent active strike for this user.
    """
    all_strikes = await get_user_strikes(user_id)
    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)

    for s in all_strikes:
        if s["is_active"] and s["dt"] >= thirty_days_ago:
            async with get_db() as conn:
                await conn.execute("UPDATE strikes SET is_active=0 WHERE id=?", (s["id"],))
                await conn.commit()
            logger.info(f"Removed 1 strike (ID: {s['id']}) for user {user_id} due to verified payment.")
            return True
    return False


async def reset_user_strikes(user_id: int) -> int:
    """Reset all active strikes for a user."""
    async with get_db() as conn:
        cur = await conn.execute("UPDATE strikes SET is_active=0 WHERE user_id=?", (user_id,))
        await conn.commit()
        return cur.rowcount


# ─── PENDING ORDERS / DEPOSITS ENFORCEMENT ───────────────────────────────────

async def get_user_pending_order(user_id: int, bot: Optional[Bot] = None) -> Optional[Deposit]:
    """
    Rule 7: One pending order per user. If one exists, show it instead of creating a new one.
    Also handles Rule 8 unpaid order expiration (expires after config.ORDER_EXPIRY_MINUTES).
    """
    async with get_db() as conn:
        cur = await conn.execute(
            f"{_DEPOSIT_SELECT} WHERE d.user_id=? AND d.status='pending' ORDER BY d.id DESC LIMIT 1",
            (user_id,)
        )
        row = await cur.fetchone()
        if not row:
            return None

        deposit = _row_to_deposit(row)

        # Check if deposit has an expiration timestamp that passed
        now = datetime.now(timezone.utc)
        if deposit.expires_at:
            exp_dt = _parse_timestamp(deposit.expires_at)
            if now > exp_dt:
                # Mark as expired unpaid order and issue a strike
                await conn.execute("UPDATE deposits SET status='expired' WHERE id=?", (deposit.id,))
                await conn.commit()
                logger.info(f"Pending deposit {deposit.deposit_code} expired unpaid for user {user_id}.")
                await add_strike(
                    user_id=deposit.user_id,
                    telegram_id=deposit.user_telegram_id,
                    reason=f"Payment order {deposit.deposit_code} expired unpaid",
                    bot=bot
                )
                return None

        return deposit


async def expire_unpaid_orders_check(bot: Optional[Bot] = None) -> int:
    """
    Periodic check for all expired unpaid orders.
    Marks them as expired and adds strikes.
    """
    count = 0
    now = datetime.now(timezone.utc)
    async with get_db() as conn:
        cur = await conn.execute(
            f"{_DEPOSIT_SELECT} WHERE d.status='pending' AND d.expires_at IS NOT NULL",
        )
        rows = await cur.fetchall()
        for r in rows:
            dep = _row_to_deposit(r)
            if dep.expires_at and now > _parse_timestamp(dep.expires_at):
                await conn.execute("UPDATE deposits SET status='expired' WHERE id=?", (dep.id,))
                await conn.commit()
                await add_strike(
                    user_id=dep.user_id,
                    telegram_id=dep.user_telegram_id,
                    reason=f"Payment order {dep.deposit_code} expired unpaid",
                    bot=bot
                )
                count += 1
    return count


async def get_banned_users_list() -> List[User]:
    """Retrieve all currently banned/blocked users."""
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM users WHERE is_blocked=1 ORDER BY id DESC")
        from bot.database.queries import _row_to_user
        return [_row_to_user(r) for r in await cur.fetchall()]


async def get_recent_strike_log(limit: int = 20) -> List[Dict[str, Any]]:
    """Retrieve system-wide recent strikes for admin inspection."""
    async with get_db() as conn:
        cur = await conn.execute(
            """SELECT s.*, u.username, u.first_name, u.internal_id
               FROM strikes s JOIN users u ON u.id=s.user_id
               ORDER BY s.id DESC LIMIT ?""",
            (limit,)
        )
        rows = await cur.fetchall()
        return [
            {
                "id": r["id"],
                "user_id": r["user_id"],
                "internal_id": r["internal_id"],
                "telegram_id": r["telegram_id"],
                "username": r["username"],
                "first_name": r["first_name"],
                "reason": r["reason"],
                "is_active": bool(r["is_active"]),
                "created_at": r["created_at"]
            }
            for r in rows
        ]
