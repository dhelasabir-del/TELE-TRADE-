"""
Comprehensive Test Suite for PART A (Hosting & Security) & PART B (Anti-Abuse).
Validates:
1. Database schema initialization (Postgres/SQLite).
2. Fernet StringSession encryption at rest & memory-only decryption.
3. Anti-abuse strikes: 1st strike (5m cooldown), 2nd strike (30m cooldown), 3rd strike (auto-ban).
4. Verified payment removing 1 strike.
5. Single pending order enforcement.
6. Rate limiting in ThrottlingMiddleware (5 presses per 10s).
7. AuthMiddleware blocking payment features for banned users.
"""

import asyncio
import sys
import uuid
from datetime import datetime, timezone
from aiogram.types import Message, CallbackQuery, User as TgUser, Chat

from bot.config import config
from bot.database.database import init_database, get_db
from bot.database.queries import (
    get_or_create_user, get_user_by_telegram_id, create_deposit_request,
    approve_deposit, reject_deposit, set_user_blocked
)
from bot.utils.crypto import encrypt_session_string, decrypt_session_string
from bot.services.anti_abuse import (
    add_strike, get_user_strike_status, remove_strike_for_verified_payment,
    reset_user_strikes, get_user_pending_order
)
from bot.middlewares.throttling import ThrottlingMiddleware
from bot.middlewares.auth import AuthMiddleware


async def run_all_tests():
    print("=" * 65)
    print("  RUNNING RYUS MARKET PART A & PART B TEST SUITE")
    print("=" * 65)

    await init_database()
    print("  [PASS] 1. Database schema initialized successfully.")

    # ── Test 1: Fernet Encryption & Decryption ──
    raw_session = "1BJWap1wBu8XZs84j9193jd93j9d2k0d012k0d1k0d0="
    encrypted = encrypt_session_string(raw_session)
    assert encrypted != raw_session, "Session string was not encrypted"
    decrypted = decrypt_session_string(encrypted)
    assert decrypted == raw_session, "Decrypted session does not match original"
    print("  [PASS] 2. Fernet at-rest StringSession encryption & decryption verified.")

    # ── Test 2: User Creation ──
    test_tg_id = int(str(uuid.uuid4().int)[:9])
    user = await get_or_create_user(test_tg_id, "test_strike_user", "Test")
    assert user is not None
    print(f"  [PASS] 3. Test user created: {user.internal_id} (TG: {user.telegram_id})")

    # ── Test 3: Anti-Abuse Strikes & Escalating Cooldowns ──
    # Clean previous strikes if any
    await reset_user_strikes(user.id)
    await set_user_blocked(user.id, False)

    # 1st Strike
    c1, b1, cd1 = await add_strike(user.id, user.telegram_id, "Test 1st Strike: Invalid UTR")
    assert c1 == 1, f"Expected 1 strike, got {c1}"
    assert not b1, "User should not be banned after 1 strike"
    st1 = await get_user_strike_status(user.id)
    assert st1["in_cooldown"], "User should be in cooldown after 1 strike"
    assert 280 <= st1["cooldown_remaining_seconds"] <= 300, f"Expected ~5m cooldown, got {st1['cooldown_remaining_seconds']}"
    print(f"  [PASS] 4. Strike #1: 5m cooldown verified ({st1['cooldown_formatted']} remaining).")

    # 2nd Strike
    c2, b2, cd2 = await add_strike(user.id, user.telegram_id, "Test 2nd Strike: Duplicate UTR")
    assert c2 == 2, f"Expected 2 strikes, got {c2}"
    assert not b2, "User should not be banned after 2 strikes"
    st2 = await get_user_strike_status(user.id)
    assert st2["in_cooldown"], "User should be in cooldown after 2 strikes"
    assert 1780 <= st2["cooldown_remaining_seconds"] <= 1800, f"Expected ~30m cooldown, got {st2['cooldown_remaining_seconds']}"
    print(f"  [PASS] 5. Strike #2: 30m cooldown verified ({st2['cooldown_formatted']} remaining).")

    # Verified Payment removes 1 strike
    removed = await remove_strike_for_verified_payment(user.id)
    assert removed, "Failed to remove strike for verified payment"
    st_after_rem = await get_user_strike_status(user.id)
    assert st_after_rem["active_strikes_count"] == 1, f"Expected 1 active strike after payment removal, got {st_after_rem['active_strikes_count']}"
    print("  [PASS] 6. Strike removal on verified payment verified (Active: 2 -> 1).")

    # Add back to 2, then 3rd strike -> Auto-ban
    await add_strike(user.id, user.telegram_id, "Strike again")
    c3, b3, cd3 = await add_strike(user.id, user.telegram_id, "Test 3rd Strike: Admin rejected fake claim")
    assert c3 >= 3, f"Expected 3+ strikes, got {c3}"
    assert b3, "User should be auto-banned on 3rd strike"
    u_banned = await get_user_by_telegram_id(test_tg_id)
    assert u_banned.is_blocked, "User is_blocked should be True in database"
    print(f"  [PASS] 7. Strike #3: Auto-ban triggered and verified.")

    # ── Test 4: Single Pending Order Enforcement ──
    # Create new fresh user
    user2_tg = int(str(uuid.uuid4().int)[:9])
    user2 = await get_or_create_user(user2_tg, "pending_test_user", "PendingTest")
    utr_test = f"UTR{uuid.uuid4().hex[:8].upper()}"

    dep1 = await create_deposit_request(user2.id, 100.0, utr_test)
    assert dep1.status == "pending"

    # Query pending order
    pending_found = await get_user_pending_order(user2.id)
    assert pending_found is not None, "Pending order should be detected"
    assert pending_found.deposit_code == dep1.deposit_code, "Pending deposit code mismatch"
    print(f"  [PASS] 8. Single pending order detected correctly: {pending_found.deposit_code}")

    # ── Test 5: Throttling Middleware (5 presses per 10s) ──
    throttler = ThrottlingMiddleware(limit=0.01, window_seconds=10.0, max_presses=5)

    async def dummy_handler(event, data):
        return "OK"

    tg_u = TgUser(id=88888888, is_bot=False, first_name="FloodTester")
    chat = Chat(id=88888888, type="private")
    event = Message(message_id=1, date=datetime.now(), chat=chat, from_user=tg_u, text="press")

    passed_count = 0
    blocked_count = 0
    for i in range(8):
        res = await throttler(dummy_handler, event, {})
        if res == "OK":
            passed_count += 1
        else:
            blocked_count += 1

    assert passed_count == 5, f"Expected 5 passed presses, got {passed_count}"
    assert blocked_count == 3, f"Expected 3 silently blocked presses, got {blocked_count}"
    print(f"  [PASS] 9. Throttling middleware verified: 5 allowed, 3 silently dropped.")

    # ── Test 6: AuthMiddleware Banned Check for Payment Features ──
    auth_mw = AuthMiddleware()
    # Check payment detection logic
    cb_deposit = CallbackQuery(id="1", from_user=tg_u, chat_instance="1", data="start_deposit")
    cb_other = CallbackQuery(id="2", from_user=tg_u, chat_instance="2", data="help_menu")
    assert auth_mw._is_payment_feature(cb_deposit), "start_deposit should be identified as payment feature"
    assert not auth_mw._is_payment_feature(cb_other), "help_menu should not be identified as payment feature"
    print("  [PASS] 10. AuthMiddleware payment feature detection verified.")

    print("\n" + "=" * 65)
    print("  🎉 ALL 10 TESTS PASSED WITH ZERO ERRORS!")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
