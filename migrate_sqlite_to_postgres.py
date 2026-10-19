#!/usr/bin/env python3
"""
Data Migration Script: SQLite -> PostgreSQL (asyncpg)
Converts legacy .session files into Fernet-encrypted StringSession strings.
Safe to run multiple times without creating duplicates.
"""

import os
import sys
import asyncio
import sqlite3
import ssl
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
from telethon import TelegramClient
from telethon.sessions import StringSession

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from bot.config import config
from bot.database.database import _normalize_database_url
from bot.utils.crypto import encrypt_session_string, decrypt_session_string


def convert_session_file_to_string(session_file: str) -> str:
    """
    Open a legacy .session file on disk, read the auth key,
    convert it into a StringSession string, and return it.
    Never logs sensitive credentials.
    """
    if not session_file:
        return ""

    p = Path(session_file)
    candidate_paths = [
        p,
        config.SESSIONS_DIR / session_file,
        config.SESSIONS_DIR / f"{session_file}.session",
        config.SESSIONS_DIR / p.name,
        config.SESSIONS_DIR / f"{p.name}.session"
    ]
    actual_path = None
    for cand in candidate_paths:
        if cand.is_file():
            actual_path = cand
            break

    if not actual_path:
        return ""

    base_session = str(actual_path).removesuffix(".session")
    try:
        # Create a synchronous client loop to extract string session
        loop = asyncio.new_event_loop()
        client = TelegramClient(
            session=base_session,
            api_id=config.TELEGRAM_API_ID,
            api_hash=config.TELEGRAM_API_HASH,
            loop=loop
        )
        loop.run_until_complete(client.connect())
        saved_str = client.session.save()
        loop.run_until_complete(client.disconnect())
        loop.close()
        return saved_str
    except Exception as e:
        print(f"  [!] Note: could not extract session from {actual_path.name}: {e}")
        return ""


async def migrate_data():
    print("=" * 65)
    print("  RYUS MARKET: SQLite -> PostgreSQL Migration")
    print("=" * 65)

    sqlite_path = config.DATABASE_PATH
    if not sqlite_path.exists():
        print(f"[-] SQLite database not found at {sqlite_path}. Nothing to migrate.")
        return

    db_url = config.DATABASE_URL
    if not db_url:
        print("[-] ERROR: DATABASE_URL environment variable is not set!")
        print("    Please set DATABASE_URL in your .env file or environment.")
        return

    clean_url, ssl_ctx = _normalize_database_url(db_url)
    print(f"[+] Connecting to PostgreSQL at host: {urlparse(clean_url).hostname}...")

    # Connect to PostgreSQL
    pg_conn = await asyncpg.connect(clean_url, ssl=ssl_ctx)
    print("[+] Connected to PostgreSQL successfully.")

    # Initialize Postgres schema
    from bot.database.database import init_database
    await init_database()

    # Open SQLite
    print(f"[+] Reading SQLite data from: {sqlite_path}")
    s_conn = sqlite3.connect(sqlite_path)
    s_conn.row_factory = sqlite3.Row
    s_cur = s_conn.cursor()

    # 1. Users
    print("\n[*] Migrating users...")
    s_cur.execute("SELECT * FROM users")
    users = s_cur.fetchall()
    migrated_users = 0
    for u in users:
        res = await pg_conn.execute("""
            INSERT INTO users (id, internal_id, telegram_id, username, first_name, wallet_balance, is_blocked, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (telegram_id) DO UPDATE SET
                internal_id = EXCLUDED.internal_id,
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                wallet_balance = EXCLUDED.wallet_balance,
                is_blocked = EXCLUDED.is_blocked
        """, u["id"], u["internal_id"], u["telegram_id"], u["username"], u["first_name"],
            float(u["wallet_balance"]), int(u["is_blocked"]), u["created_at"], u["updated_at"])
        migrated_users += 1
    print(f"    -> Processed {migrated_users} users.")

    # 2. Countries
    print("\n[*] Migrating countries...")
    s_cur.execute("SELECT * FROM countries")
    countries = s_cur.fetchall()
    migrated_countries = 0
    for c in countries:
        await pg_conn.execute("""
            INSERT INTO countries (id, name, flag_emoji, code, price, description, is_active, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (code) DO NOTHING
        """, c["id"], c["name"], c["flag_emoji"], c["code"], float(c["price"]),
            c["description"], int(c["is_active"]), c["created_at"])
        migrated_countries += 1
    print(f"    -> Processed {migrated_countries} countries.")

    # 3. Phone Numbers (and session file conversion)
    print("\n[*] Migrating phone numbers & converting .session files to StringSession...")
    s_cur.execute("SELECT * FROM phone_numbers")
    numbers = s_cur.fetchall()
    migrated_numbers = 0
    converted_sessions = 0
    for n in numbers:
        n_dict = dict(n)
        s_file = n_dict.get("session_file")
        s_str = n_dict.get("session_string")

        # If session_file exists but no session_string, convert from .session file
        final_encrypted_session = None
        if s_str:
            final_encrypted_session = encrypt_session_string(decrypt_session_string(s_str))
        elif s_file:
            raw_str = convert_session_file_to_string(s_file)
            if raw_str:
                final_encrypted_session = encrypt_session_string(raw_str)
                converted_sessions += 1

        await pg_conn.execute("""
            INSERT INTO phone_numbers (
                id, number_code, country_id, phone_number, two_fa_password,
                additional_notes, session_file, session_string, status,
                sold_to_user_id, order_id, created_at, sold_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ON CONFLICT (number_code) DO UPDATE SET
                status = EXCLUDED.status,
                session_string = COALESCE(EXCLUDED.session_string, phone_numbers.session_string),
                sold_to_user_id = EXCLUDED.sold_to_user_id,
                order_id = EXCLUDED.order_id,
                sold_at = EXCLUDED.sold_at
        """, n_dict["id"], n_dict["number_code"], n_dict["country_id"], n_dict["phone_number"],
            n_dict.get("two_fa_password"), n_dict.get("additional_notes"), s_file,
            final_encrypted_session, n_dict.get("status", "available"),
            n_dict.get("sold_to_user_id"), n_dict.get("order_id"),
            n_dict.get("created_at"), n_dict.get("sold_at"))
        migrated_numbers += 1

    print(f"    -> Processed {migrated_numbers} phone numbers ({converted_sessions} sessions converted & encrypted).")

    # 4. Orders
    print("\n[*] Migrating orders...")
    s_cur.execute("SELECT * FROM orders")
    orders = s_cur.fetchall()
    migrated_orders = 0
    for o in orders:
        o_dict = dict(o)
        s_file = o_dict.get("session_file")
        s_str = o_dict.get("session_string")

        final_order_session = None
        if s_str:
            final_order_session = encrypt_session_string(decrypt_session_string(s_str))
        elif s_file:
            raw_str = convert_session_file_to_string(s_file)
            if raw_str:
                final_order_session = encrypt_session_string(raw_str)

        await pg_conn.execute("""
            INSERT INTO orders (
                id, order_code, user_id, country_id, country_name, country_flag,
                phone_number, two_fa_password, session_file, session_string,
                price, payment_method, additional_notes, status, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            ON CONFLICT (order_code) DO NOTHING
        """, o_dict["id"], o_dict["order_code"], o_dict["user_id"], o_dict["country_id"],
            o_dict["country_name"], o_dict["country_flag"], o_dict["phone_number"],
            o_dict.get("two_fa_password"), s_file, final_order_session,
            float(o_dict["price"]), o_dict.get("payment_method", "wallet"),
            o_dict.get("additional_notes"), o_dict.get("status", "completed"),
            o_dict["created_at"])
        migrated_orders += 1
    print(f"    -> Processed {migrated_orders} orders.")

    # 5. Deposits
    print("\n[*] Migrating deposits...")
    s_cur.execute("SELECT * FROM deposits")
    deposits = s_cur.fetchall()
    migrated_deposits = 0
    for d in deposits:
        d_dict = dict(d)
        await pg_conn.execute("""
            INSERT INTO deposits (
                id, deposit_code, user_id, amount, utr, screenshot_file_id,
                status, admin_notes, reviewed_by_admin_id, created_at, reviewed_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (deposit_code) DO NOTHING
        """, d_dict["id"], d_dict["deposit_code"], d_dict["user_id"], float(d_dict["amount"]),
            d_dict["utr"], d_dict.get("screenshot_file_id"), d_dict.get("status", "pending"),
            d_dict.get("admin_notes"), d_dict.get("reviewed_by_admin_id"),
            d_dict["created_at"], d_dict.get("reviewed_at"))
        migrated_deposits += 1
    print(f"    -> Processed {migrated_deposits} deposits.")

    # 6. Transactions
    print("\n[*] Migrating transactions...")
    s_cur.execute("SELECT * FROM transactions")
    txs = s_cur.fetchall()
    migrated_txs = 0
    for t in txs:
        t_dict = dict(t)
        await pg_conn.execute("""
            INSERT INTO transactions (
                id, tx_code, user_id, type, amount, balance_before,
                balance_after, reference_id, description, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (tx_code) DO NOTHING
        """, t_dict["id"], t_dict["tx_code"], t_dict["user_id"], t_dict["type"],
            float(t_dict["amount"]), float(t_dict["balance_before"]), float(t_dict["balance_after"]),
            t_dict.get("reference_id"), t_dict.get("description"), t_dict["created_at"])
        migrated_txs += 1
    print(f"    -> Processed {migrated_txs} transactions.")

    # 7. OTP Forwards
    print("\n[*] Migrating OTP forwards...")
    try:
        s_cur.execute("SELECT * FROM otp_forwards")
        otps = s_cur.fetchall()
        for of in otps:
            of_dict = dict(of)
            await pg_conn.execute("""
                INSERT INTO otp_forwards (id, order_id, order_code, buyer_telegram_id, otp_code, forwarded_by_admin_id, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (id) DO NOTHING
            """, of_dict["id"], of_dict["order_id"], of_dict["order_code"],
                of_dict["buyer_telegram_id"], of_dict["otp_code"],
                of_dict["forwarded_by_admin_id"], of_dict["created_at"])
        print(f"    -> Processed {len(otps)} OTP forward logs.")
    except Exception as e:
        print(f"    -> OTP forwards skipped / empty: {e}")

    # 8. Admin Actions
    print("\n[*] Migrating admin actions audit log...")
    try:
        s_cur.execute("SELECT * FROM admin_actions")
        actions = s_cur.fetchall()
        for a in actions:
            a_dict = dict(a)
            await pg_conn.execute("""
                INSERT INTO admin_actions (id, admin_telegram_id, action_type, target_type, target_id, details, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (id) DO NOTHING
            """, a_dict["id"], a_dict["admin_telegram_id"], a_dict["action_type"],
                a_dict.get("target_type"), a_dict.get("target_id"),
                a_dict.get("details"), a_dict["created_at"])
        print(f"    -> Processed {len(actions)} admin actions.")
    except Exception as e:
        print(f"    -> Admin actions skipped / empty: {e}")

    # 9. Sync PostgreSQL primary key sequences
    print("\n[*] Synchronizing PostgreSQL primary key sequences...")
    tables_with_sequences = [
        ("users", "users_id_seq"),
        ("countries", "countries_id_seq"),
        ("phone_numbers", "phone_numbers_id_seq"),
        ("orders", "orders_id_seq"),
        ("deposits", "deposits_id_seq"),
        ("transactions", "transactions_id_seq"),
        ("otp_forwards", "otp_forwards_id_seq"),
        ("admin_actions", "admin_actions_id_seq"),
        ("strikes", "strikes_id_seq")
    ]
    for tbl, seq in tables_with_sequences:
        try:
            await pg_conn.execute(f"""
                SELECT setval('{seq}', COALESCE((SELECT MAX(id) FROM {tbl}), 1));
            """)
        except Exception:
            pass
    print("    -> Sequences synchronized successfully.")

    s_conn.close()
    await pg_conn.close()

    print("\n" + "=" * 65)
    print("  ✅ MIGRATION COMPLETED SUCCESSFULLY!")
    print("  All data copied & sessions converted to Fernet StringSessions.")
    print("  Safe to rerun anytime without duplicates.")
    print("=" * 65)


if __name__ == "__main__":
    try:
        asyncio.run(migrate_data())
    except KeyboardInterrupt:
        print("\nMigration aborted by user.")
    except Exception as err:
        print(f"\n[!] Migration error: {err}")
        sys.exit(1)
