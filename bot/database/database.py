"""
Database schema and connection manager for RYUS MARKET Phone Number Marketplace.
Supports PostgreSQL (asyncpg) with connection pooling and SSL (Neon/Supabase/Render)
with seamless fallback to SQLite (aiosqlite) for local development if DATABASE_URL is not set.

Tables: users, countries, phone_numbers, orders, otp_forwards,
        deposits, transactions, admin_actions, strikes
"""

import os
import ssl
import re
from decimal import Decimal
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional, List, Dict, Any, Union

import asyncpg
import aiosqlite

from bot.config import config
from bot.utils.logger import logger

# Global connection pool for asyncpg
_pg_pool: Optional[asyncpg.Pool] = None


def is_postgres() -> bool:
    """Return True if DATABASE_URL is set and targeting PostgreSQL."""
    return bool(config.DATABASE_URL and config.DATABASE_URL.startswith(("postgres://", "postgresql://")))


def _normalize_database_url(url: str) -> tuple[str, Optional[ssl.SSLContext]]:
    """
    Format DSN for asyncpg and configure SSL for remote cloud hosts (Supabase, Neon, Render).
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]

    parsed = urlparse(url)
    qs = parse_qs(parsed.query)

    # Remote hosts need SSL (Neon, Supabase, Render, Heroku)
    needs_ssl = False
    host = (parsed.hostname or "").lower()
    if host and host not in ("localhost", "127.0.0.1"):
        needs_ssl = True

    if "sslmode" in qs:
        mode = qs.pop("sslmode")[0].lower()
        if mode in ("require", "verify-ca", "verify-full"):
            needs_ssl = True

    # Rebuild URL without sslmode parameter (asyncpg handles SSL context explicitly)
    new_query = urlencode(qs, doseq=True)
    clean_url = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment
    ))

    ssl_context = None
    if needs_ssl:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

    return clean_url, ssl_context


def _convert_query_placeholders(query: str) -> str:
    """Convert SQLite ? placeholders to PostgreSQL $1, $2, ... positional parameters."""
    parts = []
    param_idx = 1
    in_single = False
    in_double = False
    i = 0
    while i < len(query):
        ch = query[i]
        if ch == "'" and not in_double:
            in_single = not in_single
            parts.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            parts.append(ch)
        elif ch == '?' and not in_single and not in_double:
            parts.append(f"${param_idx}")
            param_idx += 1
        else:
            parts.append(ch)
        i += 1
    return "".join(parts)


class RecordWrapper:
    """Wraps asyncpg.Record or dict to provide a consistent dictionary-like and row-like interface."""
    def __init__(self, record: Union[asyncpg.Record, dict]):
        self._record = record
        if isinstance(record, dict):
            self._dict = record
        else:
            self._dict = dict(record)

    def __getitem__(self, key: Union[str, int]) -> Any:
        val = self._record[key]
        if isinstance(val, Decimal):
            return float(val)
        if isinstance(val, datetime):
            return val.strftime("%Y-%m-%d %H:%M:%S")
        return val

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._dict:
            return self[key]
        return default

    def keys(self):
        return self._dict.keys()

    def values(self):
        return [self[k] for k in self.keys()]

    def items(self):
        return [(k, self[k]) for k in self.keys()]

    def __contains__(self, key: str) -> bool:
        return key in self._dict

    def __repr__(self) -> str:
        return repr(dict(self.items()))


class CursorWrapper:
    """Wraps query results to emulate a standard database cursor."""
    def __init__(self, rows: List[RecordWrapper], lastrowid: Optional[int] = None, rowcount: int = 0):
        self._rows = rows
        self.lastrowid = lastrowid
        self.rowcount = rowcount
        self._idx = 0

    async def fetchone(self) -> Optional[RecordWrapper]:
        if self._idx < len(self._rows):
            row = self._rows[self._idx]
            self._idx += 1
            return row
        return None

    async def fetchall(self) -> List[RecordWrapper]:
        remaining = self._rows[self._idx:]
        self._idx = len(self._rows)
        return remaining


class AsyncPgConnectionWrapper:
    """Wraps an asyncpg connection to match aiosqlite connection usage."""
    def __init__(self, conn: asyncpg.Connection):
        self.conn = conn
        self._tx = None

    async def execute(self, query: str, *args) -> CursorWrapper:
        # Flatten params: either execute(q, (a, b)) or execute(q, a, b)
        if len(args) == 1 and isinstance(args[0], (tuple, list)):
            params = tuple(args[0])
        else:
            params = args

        clean_q = _convert_query_placeholders(query.strip())
        is_insert = clean_q.lstrip().upper().startswith("INSERT INTO")
        has_returning = "RETURNING" in clean_q.upper()

        if is_insert and not has_returning:
            # Append RETURNING id so we can capture lastrowid
            q_returning = f"{clean_q.rstrip(';')} RETURNING id;"
            try:
                records = await self.conn.fetch(q_returning, *params)
                lastrowid = records[0]["id"] if records else None
                rows = [RecordWrapper(r) for r in records]
                return CursorWrapper(rows=rows, lastrowid=lastrowid, rowcount=len(records))
            except Exception:
                # If table does not have 'id', fall back to plain execute
                pass

        # Check if query is a SELECT or has RETURNING
        is_select = clean_q.lstrip().upper().startswith("SELECT")
        if is_select or has_returning:
            records = await self.conn.fetch(clean_q, *params)
            rows = [RecordWrapper(r) for r in records]
            lastrowid = None
            if has_returning and records and "id" in records[0]:
                lastrowid = records[0]["id"]
            return CursorWrapper(rows=rows, lastrowid=lastrowid, rowcount=len(records))

        # Other non-select queries (UPDATE, DELETE, CREATE, etc.)
        status = await self.conn.execute(clean_q, *params)
        rowcount = 0
        m = re.search(r"(\d+)$", status)
        if m:
            rowcount = int(m.group(1))
        return CursorWrapper(rows=[], lastrowid=None, rowcount=rowcount)

    async def commit(self) -> None:
        """Transactions in asyncpg are committed automatically or via context."""
        pass

    async def rollback(self) -> None:
        pass


@asynccontextmanager
async def get_db() -> AsyncGenerator[Any, None]:
    """
    Get a database connection from the asyncpg pool (PostgreSQL) or aiosqlite (SQLite).
    Yields a connection interface compatible with existing code.
    """
    if is_postgres():
        global _pg_pool
        if _pg_pool is None:
            await init_database()

        async with _pg_pool.acquire() as pg_conn:
            wrapped = AsyncPgConnectionWrapper(pg_conn)
            yield wrapped
    else:
        # SQLite fallback for local development
        conn = await aiosqlite.connect(config.DATABASE_PATH)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON;")
        await conn.execute("PRAGMA journal_mode = WAL;")
        try:
            yield conn
        finally:
            await conn.close()


async def init_database() -> None:
    """
    Initialize database connection pool and create tables without wiping existing data.
    """
    if is_postgres():
        global _pg_pool
        clean_url, ssl_ctx = _normalize_database_url(config.DATABASE_URL)
        logger.info(f"Connecting to PostgreSQL database pool (host: {urlparse(clean_url).hostname})...")

        if _pg_pool is None:
            _pg_pool = await asyncpg.create_pool(
                dsn=clean_url,
                min_size=1,
                max_size=10,
                ssl=ssl_ctx
            )

        async with _pg_pool.acquire() as conn:
            # 1. Users
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id              SERIAL PRIMARY KEY,
                    internal_id     TEXT UNIQUE NOT NULL,
                    telegram_id     BIGINT UNIQUE NOT NULL,
                    username        TEXT,
                    first_name      TEXT,
                    wallet_balance  DOUBLE PRECISION DEFAULT 0.0 CHECK (wallet_balance >= 0),
                    is_blocked      INTEGER DEFAULT 0,
                    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_users_tg ON users(telegram_id);
            """)

            # 2. Countries
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS countries (
                    id          SERIAL PRIMARY KEY,
                    name        TEXT NOT NULL,
                    flag_emoji  TEXT DEFAULT '🌐',
                    code        TEXT UNIQUE NOT NULL,
                    price       DOUBLE PRECISION NOT NULL DEFAULT 0.0 CHECK (price >= 0),
                    description TEXT,
                    is_active   INTEGER DEFAULT 1,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_countries_code ON countries(code);
            """)

            # 3. Phone Numbers
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS phone_numbers (
                    id                SERIAL PRIMARY KEY,
                    number_code       TEXT UNIQUE NOT NULL,
                    country_id        INTEGER NOT NULL REFERENCES countries(id) ON DELETE CASCADE,
                    phone_number      TEXT NOT NULL,
                    two_fa_password   TEXT,
                    additional_notes  TEXT,
                    session_file      TEXT,
                    session_string    TEXT,
                    status            TEXT DEFAULT 'available',
                    sold_to_user_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    order_id          INTEGER,
                    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    sold_at           TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_pn_country_status ON phone_numbers(country_id, status);
                CREATE INDEX IF NOT EXISTS idx_pn_code ON phone_numbers(number_code);
            """)

            # 4. Orders
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id                SERIAL PRIMARY KEY,
                    order_code        TEXT UNIQUE NOT NULL,
                    user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                    country_id        INTEGER NOT NULL REFERENCES countries(id) ON DELETE RESTRICT,
                    country_name      TEXT NOT NULL,
                    country_flag      TEXT NOT NULL,
                    phone_number      TEXT NOT NULL,
                    two_fa_password   TEXT,
                    session_file      TEXT,
                    session_string    TEXT,
                    price             DOUBLE PRECISION NOT NULL,
                    payment_method    TEXT DEFAULT 'wallet',
                    additional_notes  TEXT,
                    status            TEXT DEFAULT 'completed',
                    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_orders_code ON orders(order_code);
                CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
                CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);
            """)

            # 5. OTP Forwards
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS otp_forwards (
                    id                    SERIAL PRIMARY KEY,
                    order_id              INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                    order_code            TEXT NOT NULL,
                    buyer_telegram_id     BIGINT NOT NULL,
                    otp_code              TEXT NOT NULL,
                    forwarded_by_admin_id BIGINT NOT NULL,
                    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_otpf_order ON otp_forwards(order_id);
                CREATE INDEX IF NOT EXISTS idx_otpf_buyer ON otp_forwards(buyer_telegram_id);
            """)

            # 6. Deposits
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS deposits (
                    id                    SERIAL PRIMARY KEY,
                    deposit_code          TEXT UNIQUE NOT NULL,
                    user_id               INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                    amount                DOUBLE PRECISION NOT NULL CHECK (amount > 0),
                    utr                   TEXT NOT NULL,
                    screenshot_file_id    TEXT,
                    status                TEXT DEFAULT 'pending',
                    admin_notes           TEXT,
                    reviewed_by_admin_id  BIGINT,
                    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reviewed_at           TIMESTAMP,
                    expires_at            TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_dep_code ON deposits(deposit_code);
                CREATE INDEX IF NOT EXISTS idx_dep_user ON deposits(user_id);
                CREATE INDEX IF NOT EXISTS idx_dep_utr ON deposits(utr);
                CREATE INDEX IF NOT EXISTS idx_dep_status ON deposits(status);
            """)

            # 7. Transactions
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id              SERIAL PRIMARY KEY,
                    tx_code         TEXT UNIQUE NOT NULL,
                    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                    type            TEXT NOT NULL,
                    amount          DOUBLE PRECISION NOT NULL,
                    balance_before  DOUBLE PRECISION NOT NULL,
                    balance_after   DOUBLE PRECISION NOT NULL,
                    reference_id    TEXT,
                    description     TEXT,
                    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id);
            """)

            # 8. Admin Actions
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS admin_actions (
                    id                  SERIAL PRIMARY KEY,
                    admin_telegram_id   BIGINT NOT NULL,
                    action_type         TEXT NOT NULL,
                    target_type         TEXT,
                    target_id           TEXT,
                    details             TEXT,
                    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 9. Strikes (Anti-Abuse System)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS strikes (
                    id                  SERIAL PRIMARY KEY,
                    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    telegram_id         BIGINT NOT NULL,
                    reason              TEXT NOT NULL,
                    is_active           INTEGER DEFAULT 1,
                    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_strikes_user ON strikes(user_id);
                CREATE INDEX IF NOT EXISTS idx_strikes_tg ON strikes(telegram_id);
                CREATE INDEX IF NOT EXISTS idx_strikes_created ON strikes(created_at);
            """)

            # Add missing columns safely for upgrades
            migrations = [
                "ALTER TABLE phone_numbers ADD COLUMN IF NOT EXISTS session_file TEXT;",
                "ALTER TABLE phone_numbers ADD COLUMN IF NOT EXISTS session_string TEXT;",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS session_file TEXT;",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS session_string TEXT;",
                "ALTER TABLE deposits ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP;",
                "ALTER TABLE strikes ADD COLUMN IF NOT EXISTS is_active INTEGER DEFAULT 1;"
            ]
            for mig in migrations:
                try:
                    await conn.execute(mig)
                except Exception:
                    pass

        logger.info("PostgreSQL database schema verified successfully.")
    else:
        # SQLite schema initialization (for fallback or local testing)
        logger.info(f"Initializing SQLite fallback database at: {config.DATABASE_PATH}")
        conn = await aiosqlite.connect(config.DATABASE_PATH)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON;")
        await conn.execute("PRAGMA journal_mode = WAL;")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                internal_id     TEXT UNIQUE NOT NULL,
                telegram_id     INTEGER UNIQUE NOT NULL,
                username        TEXT,
                first_name      TEXT,
                wallet_balance  REAL DEFAULT 0.0 CHECK (wallet_balance >= 0),
                is_blocked      INTEGER DEFAULT 0,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_tg ON users(telegram_id);")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS countries (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                flag_emoji  TEXT DEFAULT '🌐',
                code        TEXT UNIQUE NOT NULL,
                price       REAL NOT NULL DEFAULT 0.0 CHECK (price >= 0),
                description TEXT,
                is_active   INTEGER DEFAULT 1,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_countries_code ON countries(code);")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS phone_numbers (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                number_code       TEXT UNIQUE NOT NULL,
                country_id        INTEGER NOT NULL REFERENCES countries(id) ON DELETE CASCADE,
                phone_number      TEXT NOT NULL,
                two_fa_password   TEXT,
                additional_notes  TEXT,
                session_file      TEXT,
                session_string    TEXT,
                status            TEXT DEFAULT 'available',
                sold_to_user_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
                order_id          INTEGER,
                created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sold_at           TIMESTAMP
            );
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_pn_country_status ON phone_numbers(country_id, status);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_pn_code ON phone_numbers(number_code);")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                order_code        TEXT UNIQUE NOT NULL,
                user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                country_id        INTEGER NOT NULL REFERENCES countries(id) ON DELETE RESTRICT,
                country_name      TEXT NOT NULL,
                country_flag      TEXT NOT NULL,
                phone_number      TEXT NOT NULL,
                two_fa_password   TEXT,
                session_file      TEXT,
                session_string    TEXT,
                price             REAL NOT NULL,
                payment_method    TEXT DEFAULT 'wallet',
                additional_notes  TEXT,
                status            TEXT DEFAULT 'completed',
                created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_code ON orders(order_code);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);")

        for col_def in ["session_file TEXT", "session_string TEXT"]:
            try:
                await conn.execute(f"ALTER TABLE phone_numbers ADD COLUMN {col_def};")
            except Exception:
                pass
        for col_def in ["session_file TEXT", "session_string TEXT"]:
            try:
                await conn.execute(f"ALTER TABLE orders ADD COLUMN {col_def};")
            except Exception:
                pass

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS otp_forwards (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id              INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                order_code            TEXT NOT NULL,
                buyer_telegram_id     INTEGER NOT NULL,
                otp_code              TEXT NOT NULL,
                forwarded_by_admin_id INTEGER NOT NULL,
                created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_otpf_order ON otp_forwards(order_id);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_otpf_buyer ON otp_forwards(buyer_telegram_id);")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS deposits (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                deposit_code          TEXT UNIQUE NOT NULL,
                user_id               INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                amount                REAL NOT NULL CHECK (amount > 0),
                utr                   TEXT NOT NULL,
                screenshot_file_id    TEXT,
                status                TEXT DEFAULT 'pending',
                admin_notes           TEXT,
                reviewed_by_admin_id  INTEGER,
                created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_at           TIMESTAMP,
                expires_at            TIMESTAMP
            );
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_dep_code ON deposits(deposit_code);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_dep_user ON deposits(user_id);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_dep_utr ON deposits(utr);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_dep_status ON deposits(status);")

        try:
            await conn.execute("ALTER TABLE deposits ADD COLUMN expires_at TIMESTAMP;")
        except Exception:
            pass

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                tx_code         TEXT UNIQUE NOT NULL,
                user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                type            TEXT NOT NULL,
                amount          REAL NOT NULL,
                balance_before  REAL NOT NULL,
                balance_after   REAL NOT NULL,
                reference_id    TEXT,
                description     TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id);")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_actions (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_telegram_id   INTEGER NOT NULL,
                action_type         TEXT NOT NULL,
                target_type         TEXT,
                target_id           TEXT,
                details             TEXT,
                created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS strikes (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                telegram_id         INTEGER NOT NULL,
                reason              TEXT NOT NULL,
                is_active           INTEGER DEFAULT 1,
                created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_strikes_user ON strikes(user_id);")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_strikes_tg ON strikes(telegram_id);")

        await conn.commit()
        await conn.close()
        logger.info("SQLite fallback schema verified successfully.")


async def close_db() -> None:
    """Gracefully close the PostgreSQL connection pool."""
    global _pg_pool
    if _pg_pool is not None:
        logger.info("Closing PostgreSQL connection pool...")
        await _pg_pool.close()
        _pg_pool = None
