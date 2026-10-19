"""
All database queries for RYUS MARKET Phone Number Marketplace.
Covers: users, countries, phone_numbers, orders, otp_forwards,
        deposits, transactions, admin_actions.
"""

import uuid
from datetime import datetime
from typing import Optional, List, Tuple

from bot.database.database import get_db
from bot.database.models import (
    User, Country, PhoneNumber, Order, OtpForward,
    Deposit, Transaction, DashboardStats
)
from bot.utils.logger import logger


# ─── Custom Exceptions ────────────────────────────────────────────────────────

class MarketplaceError(Exception):
    pass

class InsufficientFundsError(MarketplaceError):
    pass

class OutOfStockError(MarketplaceError):
    pass

class UserBlockedError(MarketplaceError):
    pass

class DuplicateUtrError(MarketplaceError):
    pass


# ─── USERS ────────────────────────────────────────────────────────────────────

async def get_or_create_user(
    telegram_id: int,
    username: Optional[str],
    first_name: Optional[str]
) -> User:
    async with get_db() as conn:
        cur = await conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cur.fetchone()
        if row:
            if row["username"] != username or row["first_name"] != first_name:
                await conn.execute(
                    "UPDATE users SET username=?, first_name=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (username, first_name, row["id"])
                )
                await conn.commit()
            return _row_to_user(row, username, first_name)

        tmp = f"TMP-{uuid.uuid4().hex[:6].upper()}"
        cur = await conn.execute(
            "INSERT INTO users (internal_id, telegram_id, username, first_name) VALUES (?,?,?,?)",
            (tmp, telegram_id, username, first_name)
        )
        uid = cur.lastrowid
        internal_id = f"USR-{1000 + uid}"
        await conn.execute("UPDATE users SET internal_id=? WHERE id=?", (internal_id, uid))
        await conn.commit()
        cur = await conn.execute("SELECT * FROM users WHERE id=?", (uid,))
        return _row_to_user(await cur.fetchone(), username, first_name)


def _row_to_user(row, username=None, first_name=None) -> User:
    return User(
        id=row["id"],
        internal_id=row["internal_id"],
        telegram_id=row["telegram_id"],
        username=username if username is not None else row["username"],
        first_name=first_name if first_name is not None else row["first_name"],
        wallet_balance=float(row["wallet_balance"]),
        is_blocked=bool(row["is_blocked"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"]
    )


async def get_user_by_telegram_id(tg_id: int) -> Optional[User]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM users WHERE telegram_id=?", (tg_id,))
        row = await cur.fetchone()
        return _row_to_user(row) if row else None


async def get_user_by_id(user_id: int) -> Optional[User]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM users WHERE id=?", (user_id,))
        row = await cur.fetchone()
        return _row_to_user(row) if row else None


async def get_user_by_internal_id(internal_id: str) -> Optional[User]:
    async with get_db() as conn:
        cur = await conn.execute(
            "SELECT * FROM users WHERE UPPER(internal_id)=UPPER(?)", (internal_id.strip(),)
        )
        row = await cur.fetchone()
        return _row_to_user(row) if row else None


async def set_user_blocked(user_id: int, is_blocked: bool) -> None:
    async with get_db() as conn:
        await conn.execute(
            "UPDATE users SET is_blocked=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (1 if is_blocked else 0, user_id)
        )
        await conn.commit()


async def search_users(query: str) -> List[User]:
    q = f"%{query.strip()}%"
    async with get_db() as conn:
        cur = await conn.execute(
            """SELECT * FROM users
               WHERE internal_id LIKE ? OR username LIKE ? OR CAST(telegram_id AS TEXT) LIKE ?
               ORDER BY id DESC LIMIT 25""",
            (q, q, q)
        )
        return [_row_to_user(r) for r in await cur.fetchall()]


# ─── COUNTRIES ────────────────────────────────────────────────────────────────

def _row_to_country(r) -> Country:
    return Country(
        id=r["id"],
        name=r["name"],
        flag_emoji=r["flag_emoji"] or "🌐",
        code=r["code"],
        price=float(r["price"]),
        description=r["description"],
        is_active=bool(r["is_active"]),
        created_at=r["created_at"]
    )


async def get_all_countries(active_only: bool = True) -> List[Country]:
    async with get_db() as conn:
        where = "WHERE is_active=1" if active_only else ""
        cur = await conn.execute(
            f"""SELECT c.*,
                    (SELECT COUNT(*) FROM phone_numbers p WHERE p.country_id=c.id AND p.status='available') AS avail
                FROM countries c {where}
                ORDER BY c.name ASC"""
        )
        rows = await cur.fetchall()
        return [_row_to_country(r) for r in rows]


async def get_country_by_id(cid: int) -> Optional[Country]:
    async with get_db() as conn:
        cur = await conn.execute("SELECT * FROM countries WHERE id=?", (cid,))
        r = await cur.fetchone()
        return _row_to_country(r) if r else None


async def get_country_by_code(code: str) -> Optional[Country]:
    async with get_db() as conn:
        cur = await conn.execute(
            "SELECT * FROM countries WHERE UPPER(code)=UPPER(?)", (code.strip(),)
        )
        r = await cur.fetchone()
        return _row_to_country(r) if r else None


async def create_country(
    name: str, flag_emoji: str, code: str, price: float,
    description: Optional[str] = None
) -> Country:
    async with get_db() as conn:
        cur = await conn.execute(
            "INSERT INTO countries (name, flag_emoji, code, price, description) VALUES (?,?,?,?,?)",
            (name.strip(), flag_emoji, code.upper().strip(), price, description)
        )
        await conn.commit()
        return await get_country_by_id(cur.lastrowid)  # type: ignore


async def update_country(
    cid: int,
    name: Optional[str] = None,
    price: Optional[float] = None,
    flag_emoji: Optional[str] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None
) -> Optional[Country]:
    async with get_db() as conn:
        updates, params = [], []
        if name is not None: updates.append("name=?"); params.append(name.strip())
        if price is not None: updates.append("price=?"); params.append(price)
        if flag_emoji is not None: updates.append("flag_emoji=?"); params.append(flag_emoji)
        if description is not None: updates.append("description=?"); params.append(description)
        if is_active is not None: updates.append("is_active=?"); params.append(1 if is_active else 0)
        if updates:
            params.append(cid)
            await conn.execute(f"UPDATE countries SET {', '.join(updates)} WHERE id=?", params)
            await conn.commit()
    return await get_country_by_id(cid)


async def delete_country(cid: int) -> bool:
    async with get_db() as conn:
        # Check if past orders exist for this country
        cur = await conn.execute("SELECT 1 FROM orders WHERE country_id=? LIMIT 1", (cid,))
        has_orders = await cur.fetchone() is not None
        if has_orders:
            # Preserve order history integrity by disabling the country
            await conn.execute("UPDATE countries SET is_active=0 WHERE id=?", (cid,))
            await conn.commit()
            return False
        else:
            await conn.execute("DELETE FROM phone_numbers WHERE country_id=?", (cid,))
            await conn.execute("DELETE FROM countries WHERE id=?", (cid,))
            await conn.commit()
            return True


async def get_country_stock_count(cid: int, status: str = "available") -> int:
    async with get_db() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) as cnt FROM phone_numbers WHERE country_id=? AND status=?",
            (cid, status)
        )
        row = await cur.fetchone()
        return int(row["cnt"])


# ─── PHONE NUMBERS (INVENTORY) ────────────────────────────────────────────────

def _row_to_phone_number(r) -> PhoneNumber:
    keys = r.keys()
    return PhoneNumber(
        id=r["id"],
        number_code=r["number_code"],
        country_id=r["country_id"],
        country_name=r["country_name"] if "country_name" in keys else "",
        country_flag=r["country_flag"] if "country_flag" in keys else "🌐",
        phone_number=r["phone_number"],
        two_fa_password=r["two_fa_password"],
        additional_notes=r["additional_notes"],
        session_file=r["session_file"] if "session_file" in keys else None,
        session_string=r["session_string"] if "session_string" in keys else None,
        status=r["status"],
        sold_to_user_id=r["sold_to_user_id"],
        order_id=r["order_id"],
        created_at=r["created_at"],
        sold_at=r["sold_at"]
    )


async def add_phone_number(
    country_id: int,
    phone_number: str,
    two_fa_password: Optional[str] = None,
    additional_notes: Optional[str] = None,
    session_file: Optional[str] = None,
    session_string: Optional[str] = None
) -> PhoneNumber:
    number_code = f"NUM-{uuid.uuid4().hex[:8].upper()}"
    async with get_db() as conn:
        cur = await conn.execute(
            """INSERT INTO phone_numbers
               (number_code, country_id, phone_number, two_fa_password, additional_notes,
                session_file, session_string, status)
               VALUES (?,?,?,?,?,?,?,'available')""",
            (number_code, country_id, phone_number.strip(), two_fa_password, additional_notes,
             session_file, session_string)
        )
        await conn.commit()
        nid = cur.lastrowid

    return await get_phone_number_by_id(nid)  # type: ignore


async def add_phone_numbers_bulk(
    country_id: int,
    numbers: List[dict]  # list of {phone_number, two_fa_password, notes, session_file, session_string}
) -> int:
    inserted = 0
    async with get_db() as conn:
        for item in numbers:
            nc = f"NUM-{uuid.uuid4().hex[:8].upper()}"
            await conn.execute(
                """INSERT INTO phone_numbers
                   (number_code, country_id, phone_number, two_fa_password, additional_notes,
                    session_file, session_string, status)
                   VALUES (?,?,?,?,?,?,?,'available')""",
                (nc, country_id, item["phone_number"].strip(),
                 item.get("two_fa_password"), item.get("notes"),
                 item.get("session_file"), item.get("session_string"))
            )
            inserted += 1
        await conn.commit()
    return inserted


async def get_phone_number_by_id(nid: int) -> Optional[PhoneNumber]:
    async with get_db() as conn:
        cur = await conn.execute(
            """SELECT p.*, c.name as country_name, c.flag_emoji as country_flag
               FROM phone_numbers p
               JOIN countries c ON c.id=p.country_id
               WHERE p.id=?""",
            (nid,)
        )
        r = await cur.fetchone()
        return _row_to_phone_number(r) if r else None


async def get_phone_numbers_by_country(
    country_id: int,
    status: str = "available",
    limit: int = 50,
    offset: int = 0
) -> List[PhoneNumber]:
    async with get_db() as conn:
        cur = await conn.execute(
            """SELECT p.*, c.name as country_name, c.flag_emoji as country_flag
               FROM phone_numbers p
               JOIN countries c ON c.id=p.country_id
               WHERE p.country_id=? AND p.status=?
               ORDER BY p.id ASC
               LIMIT ? OFFSET ?""",
            (country_id, status, limit, offset)
        )
        return [_row_to_phone_number(r) for r in await cur.fetchall()]


async def update_phone_number_status(nid: int, new_status: str) -> None:
    async with get_db() as conn:
        await conn.execute(
            "UPDATE phone_numbers SET status=? WHERE id=?", (new_status, nid)
        )
        await conn.commit()


async def delete_phone_number(nid: int) -> None:
    async with get_db() as conn:
        await conn.execute("DELETE FROM phone_numbers WHERE id=?", (nid,))
        await conn.commit()


# ─── PURCHASE (ATOMIC) ────────────────────────────────────────────────────────

async def execute_purchase(
    user_telegram_id: int,
    country_id: int
) -> Tuple[Order, PhoneNumber]:
    """
    Atomically:
    1. Lock & validate user (blocked? balance?)
    2. Lock & find 1 available number in the country
    3. Deduct wallet balance
    4. Mark number as SOLD
    5. Create Order record
    6. Record Transaction
    7. Commit
    Returns (Order, PhoneNumber-snapshot-with-full-details)
    """
    async with get_db() as conn:
        await conn.execute("BEGIN IMMEDIATE;")
        try:
            # User
            cur = await conn.execute(
                "SELECT * FROM users WHERE telegram_id=?", (user_telegram_id,)
            )
            user_row = await cur.fetchone()
            if not user_row:
                raise MarketplaceError("User not found.")
            if user_row["is_blocked"]:
                raise UserBlockedError("Your account has been restricted.")

            user_db_id = user_row["id"]
            balance = float(user_row["wallet_balance"])

            # Country + price
            cur = await conn.execute(
                "SELECT * FROM countries WHERE id=? AND is_active=1", (country_id,)
            )
            country_row = await cur.fetchone()
            if not country_row:
                raise MarketplaceError("This country is unavailable.")

            price = float(country_row["price"])
            if balance < price:
                raise InsufficientFundsError(
                    f"You need ₹{price:.2f} but only have ₹{balance:.2f} in your wallet."
                )

            # Find 1 available number
            cur = await conn.execute(
                """SELECT * FROM phone_numbers
                   WHERE country_id=? AND status='available'
                   ORDER BY id ASC LIMIT 1""",
                (country_id,)
            )
            num_row = await cur.fetchone()
            if not num_row:
                raise OutOfStockError("No numbers available for this country right now.")

            num_id = num_row["id"]
            phone_number = num_row["phone_number"]
            two_fa = num_row["two_fa_password"]
            notes = num_row["additional_notes"]
            session_file = num_row["session_file"] if "session_file" in num_row.keys() else None
            session_string = num_row["session_string"] if "session_string" in num_row.keys() else None

            # Deduct balance
            new_balance = round(balance - price, 2)
            await conn.execute(
                "UPDATE users SET wallet_balance=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (new_balance, user_db_id)
            )

            # Create order
            date_str = datetime.now().strftime("%Y%m%d")
            order_code = f"ORD-{date_str}-{uuid.uuid4().hex[:6].upper()}"
            cur = await conn.execute(
                """INSERT INTO orders
                   (order_code, user_id, country_id, country_name, country_flag,
                    phone_number, two_fa_password, session_file, session_string, price, payment_method, additional_notes, status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,'wallet',?,'completed')""",
                (order_code, user_db_id, country_id,
                 country_row["name"], country_row["flag_emoji"],
                 phone_number, two_fa, session_file, session_string, price, notes)
            )
            order_db_id = cur.lastrowid

            # Mark number as sold
            await conn.execute(
                """UPDATE phone_numbers
                   SET status='sold', sold_to_user_id=?, order_id=?, sold_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (user_db_id, order_db_id, num_id)
            )

            # Transaction ledger
            tx_code = f"TX-{uuid.uuid4().hex[:8].upper()}"
            await conn.execute(
                """INSERT INTO transactions
                   (tx_code, user_id, type, amount, balance_before, balance_after, reference_id, description)
                   VALUES (?,?,'purchase',?,?,?,?,?)""",
                (tx_code, user_db_id, price, balance, new_balance,
                 order_code, f"Purchased {country_row['flag_emoji']} {country_row['name']} number")
            )

            await conn.commit()

            order = Order(
                id=order_db_id,
                order_code=order_code,
                user_id=user_db_id,
                user_telegram_id=user_telegram_id,
                country_id=country_id,
                country_name=country_row["name"],
                country_flag=country_row["flag_emoji"],
                phone_number=phone_number,
                two_fa_password=two_fa,
                price=price,
                payment_method="wallet",
                additional_notes=notes,
                status="completed",
                created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                session_file=session_file
            )

            phone = PhoneNumber(
                id=num_id,
                number_code=num_row["number_code"],
                country_id=country_id,
                country_name=country_row["name"],
                country_flag=country_row["flag_emoji"],
                phone_number=phone_number,
                two_fa_password=two_fa,
                additional_notes=notes,
                session_file=session_file,
                session_string=num_row["session_string"] if "session_string" in num_row.keys() else None,
                status="sold",
                sold_to_user_id=user_db_id,
                order_id=order_db_id,
                created_at=num_row["created_at"],
                sold_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )

            logger.info(f"Purchase: {order_code} by {user_telegram_id} "
                        f"({country_row['name']}) for ₹{price}")
            return order, phone

        except Exception:
            await conn.rollback()
            raise


# ─── ORDERS ───────────────────────────────────────────────────────────────────

def _row_to_order(r) -> Order:
    keys = r.keys()
    return Order(
        id=r["id"],
        order_code=r["order_code"],
        user_id=r["user_id"],
        user_telegram_id=r["user_telegram_id"] if "user_telegram_id" in keys else 0,
        country_id=r["country_id"],
        country_name=r["country_name"],
        country_flag=r["country_flag"],
        phone_number=r["phone_number"],
        two_fa_password=r["two_fa_password"],
        price=float(r["price"]),
        payment_method=r["payment_method"],
        additional_notes=r["additional_notes"],
        status=r["status"],
        created_at=r["created_at"],
        session_file=r["session_file"] if "session_file" in keys else None,
        session_string=r["session_string"] if "session_string" in keys else None
    )


async def get_user_orders(user_id: int, limit: int = 15, offset: int = 0) -> List[Order]:
    async with get_db() as conn:
        cur = await conn.execute(
            """SELECT o.*, u.telegram_id as user_telegram_id
               FROM orders o JOIN users u ON u.id=o.user_id
               WHERE o.user_id=? ORDER BY o.id DESC LIMIT ? OFFSET ?""",
            (user_id, limit, offset)
        )
        return [_row_to_order(r) for r in await cur.fetchall()]


async def get_order_by_id(oid: int) -> Optional[Order]:
    async with get_db() as conn:
        cur = await conn.execute(
            """SELECT o.*, u.telegram_id as user_telegram_id
               FROM orders o JOIN users u ON u.id=o.user_id
               WHERE o.id=?""",
            (oid,)
        )
        r = await cur.fetchone()
        return _row_to_order(r) if r else None


async def get_order_by_code(code: str) -> Optional[Order]:
    async with get_db() as conn:
        cur = await conn.execute(
            """SELECT o.*, u.telegram_id as user_telegram_id
               FROM orders o JOIN users u ON u.id=o.user_id
               WHERE UPPER(o.order_code)=UPPER(?)""",
            (code.strip(),)
        )
        r = await cur.fetchone()
        return _row_to_order(r) if r else None


async def search_orders(query_type: str, query_value: str, limit: int = 20) -> List[Order]:
    qv = query_value.strip()
    async with get_db() as conn:
        base = """SELECT o.*, u.telegram_id as user_telegram_id
                  FROM orders o JOIN users u ON u.id=o.user_id"""
        if query_type == "order_id":
            sql = f"{base} WHERE UPPER(o.order_code) LIKE UPPER(?) ORDER BY o.id DESC LIMIT {limit}"
            params = (f"%{qv}%",)
        elif query_type == "telegram_id":
            sql = f"{base} WHERE CAST(u.telegram_id AS TEXT) LIKE ? ORDER BY o.id DESC LIMIT {limit}"
            params = (f"%{qv}%",)
        elif query_type == "country":
            sql = f"{base} WHERE o.country_name LIKE ? ORDER BY o.id DESC LIMIT {limit}"
            params = (f"%{qv}%",)
        elif query_type == "status":
            sql = f"{base} WHERE o.status=? ORDER BY o.id DESC LIMIT {limit}"
            params = (qv.lower(),)
        else:
            sql = f"{base} ORDER BY o.id DESC LIMIT {limit}"
            params = ()
        cur = await conn.execute(sql, params)
        return [_row_to_order(r) for r in await cur.fetchall()]


async def update_order_status(
    order_id: int, new_status: str, admin_telegram_id: int
) -> bool:
    async with get_db() as conn:
        await conn.execute("BEGIN IMMEDIATE;")
        cur = await conn.execute("SELECT * FROM orders WHERE id=?", (order_id,))
        row = await cur.fetchone()
        if not row:
            await conn.rollback()
            return False

        old_status = row["status"]
        if old_status == new_status:
            await conn.rollback()
            return True

        # Refund: credit buyer wallet
        if new_status == "refunded" and old_status == "completed":
            uid = row["user_id"]
            price = float(row["price"])
            ucur = await conn.execute("SELECT wallet_balance FROM users WHERE id=?", (uid,))
            urow = await ucur.fetchone()
            if urow:
                bb = float(urow["wallet_balance"])
                ba = round(bb + price, 2)
                await conn.execute(
                    "UPDATE users SET wallet_balance=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (ba, uid)
                )
                tc = f"TX-{uuid.uuid4().hex[:8].upper()}"
                await conn.execute(
                    """INSERT INTO transactions
                       (tx_code, user_id, type, amount, balance_before, balance_after, reference_id, description)
                       VALUES (?,?,'refund',?,?,?,?,?)""",
                    (tc, uid, price, bb, ba, row["order_code"],
                     f"Refund for Order {row['order_code']}")
                )

        await conn.execute(
            "UPDATE orders SET status=? WHERE id=?", (new_status, order_id)
        )
        await conn.execute(
            """INSERT INTO admin_actions
               (admin_telegram_id, action_type, target_type, target_id, details)
               VALUES (?,'update_order_status','order',?,?)""",
            (admin_telegram_id, str(order_id),
             f"{old_status} → {new_status}")
        )
        await conn.commit()
        return True


# ─── OTP FORWARDING ───────────────────────────────────────────────────────────

async def log_otp_forward(
    order_id: int,
    order_code: str,
    buyer_telegram_id: int,
    otp_code: str,
    admin_telegram_id: int
) -> OtpForward:
    async with get_db() as conn:
        cur = await conn.execute(
            """INSERT INTO otp_forwards
               (order_id, order_code, buyer_telegram_id, otp_code, forwarded_by_admin_id)
               VALUES (?,?,?,?,?)""",
            (order_id, order_code, buyer_telegram_id, otp_code.strip(), admin_telegram_id)
        )
        await conn.commit()
        fwd_id = cur.lastrowid

        cur = await conn.execute("SELECT * FROM otp_forwards WHERE id=?", (fwd_id,))
        r = await cur.fetchone()
        return OtpForward(
            id=r["id"],
            order_id=r["order_id"],
            order_code=r["order_code"],
            buyer_telegram_id=r["buyer_telegram_id"],
            otp_code=r["otp_code"],
            forwarded_by_admin_id=r["forwarded_by_admin_id"],
            created_at=r["created_at"]
        )


async def get_otp_history_for_order(order_id: int) -> List[OtpForward]:
    async with get_db() as conn:
        cur = await conn.execute(
            "SELECT * FROM otp_forwards WHERE order_id=? ORDER BY id DESC",
            (order_id,)
        )
        rows = await cur.fetchall()
        return [
            OtpForward(
                id=r["id"],
                order_id=r["order_id"],
                order_code=r["order_code"],
                buyer_telegram_id=r["buyer_telegram_id"],
                otp_code=r["otp_code"],
                forwarded_by_admin_id=r["forwarded_by_admin_id"],
                created_at=r["created_at"]
            )
            for r in rows
        ]


# ─── DEPOSITS ─────────────────────────────────────────────────────────────────

def _row_to_deposit(r) -> Deposit:
    return Deposit(
        id=r["id"],
        deposit_code=r["deposit_code"],
        user_id=r["user_id"],
        user_telegram_id=r["user_telegram_id"],
        user_username=r["user_username"],
        user_first_name=r["user_first_name"],
        amount=float(r["amount"]),
        utr=r["utr"],
        screenshot_file_id=r["screenshot_file_id"],
        status=r["status"],
        admin_notes=r["admin_notes"],
        reviewed_by_admin_id=r["reviewed_by_admin_id"],
        created_at=r["created_at"],
        reviewed_at=r["reviewed_at"],
        expires_at=r["expires_at"] if "expires_at" in r.keys() else None
    )


_DEPOSIT_SELECT = """
    SELECT d.*,
           u.telegram_id as user_telegram_id,
           u.username as user_username,
           u.first_name as user_first_name
    FROM deposits d JOIN users u ON u.id=d.user_id
"""


async def check_utr_exists(utr: str) -> bool:
    async with get_db() as conn:
        cur = await conn.execute(
            "SELECT 1 FROM deposits WHERE UPPER(utr)=UPPER(?) LIMIT 1", (utr.strip(),)
        )
        return await cur.fetchone() is not None


async def create_deposit_request(
    user_id: int, amount: float, utr: str,
    screenshot_file_id: Optional[str] = None,
    expires_at: Optional[Any] = None
) -> Deposit:
    utr_clean = utr.strip().upper()
    if await check_utr_exists(utr_clean):
        raise DuplicateUtrError(f"UTR '{utr_clean}' already submitted.")

    date_str = datetime.now().strftime("%Y%m%d")
    dep_code = f"DEP-{date_str}-{uuid.uuid4().hex[:6].upper()}"

    async with get_db() as conn:
        cur = await conn.execute(
            "INSERT INTO deposits (deposit_code, user_id, amount, utr, screenshot_file_id, expires_at) VALUES (?,?,?,?,?,?)",
            (dep_code, user_id, amount, utr_clean, screenshot_file_id, expires_at)
        )
        await conn.commit()
        did = cur.lastrowid

    return await get_deposit_by_id(did)  # type: ignore


async def get_deposit_by_id(did: int) -> Optional[Deposit]:
    async with get_db() as conn:
        cur = await conn.execute(f"{_DEPOSIT_SELECT} WHERE d.id=?", (did,))
        r = await cur.fetchone()
        return _row_to_deposit(r) if r else None


async def get_pending_deposits(limit: int = 20) -> List[Deposit]:
    async with get_db() as conn:
        cur = await conn.execute(
            f"{_DEPOSIT_SELECT} WHERE d.status='pending' ORDER BY d.id ASC LIMIT ?",
            (limit,)
        )
        return [_row_to_deposit(r) for r in await cur.fetchall()]


async def get_user_deposits(user_id: int, limit: int = 10) -> List[Deposit]:
    async with get_db() as conn:
        cur = await conn.execute(
            f"{_DEPOSIT_SELECT} WHERE d.user_id=? ORDER BY d.id DESC LIMIT ?",
            (user_id, limit)
        )
        return [_row_to_deposit(r) for r in await cur.fetchall()]


async def approve_deposit(
    dep_id: int, admin_telegram_id: int, notes: str = "Approved"
) -> Deposit:
    async with get_db() as conn:
        await conn.execute("BEGIN IMMEDIATE;")
        cur = await conn.execute("SELECT * FROM deposits WHERE id=?", (dep_id,))
        row = await cur.fetchone()
        if not row:
            await conn.rollback()
            raise MarketplaceError("Deposit not found.")
        if row["status"] != "pending":
            await conn.rollback()
            raise MarketplaceError(f"Deposit already {row['status']}.")

        uid = row["user_id"]
        amount = float(row["amount"])
        ucur = await conn.execute("SELECT wallet_balance FROM users WHERE id=?", (uid,))
        urow = await ucur.fetchone()
        bb = float(urow["wallet_balance"])
        ba = round(bb + amount, 2)

        await conn.execute(
            "UPDATE users SET wallet_balance=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (ba, uid)
        )
        await conn.execute(
            """UPDATE deposits
               SET status='approved', admin_notes=?, reviewed_by_admin_id=?, reviewed_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (notes, admin_telegram_id, dep_id)
        )
        tc = f"TX-{uuid.uuid4().hex[:8].upper()}"
        await conn.execute(
            """INSERT INTO transactions
               (tx_code, user_id, type, amount, balance_before, balance_after, reference_id, description)
               VALUES (?,?,'deposit',?,?,?,?,?)""",
            (tc, uid, amount, bb, ba, row["deposit_code"], f"UPI Deposit {row['deposit_code']}")
        )
        await conn.execute(
            """INSERT INTO admin_actions
               (admin_telegram_id, action_type, target_type, target_id, details)
               VALUES (?,'approve_deposit','deposit',?,?)""",
            (admin_telegram_id, str(dep_id), f"Approved ₹{amount} (UTR: {row['utr']})")
        )
        await conn.commit()

    dep = await get_deposit_by_id(dep_id)
    logger.info(f"Deposit {row['deposit_code']} approved for ₹{amount}")
    return dep  # type: ignore


async def reject_deposit(
    dep_id: int, admin_telegram_id: int, reason: str
) -> Deposit:
    async with get_db() as conn:
        await conn.execute("BEGIN IMMEDIATE;")
        cur = await conn.execute("SELECT * FROM deposits WHERE id=?", (dep_id,))
        row = await cur.fetchone()
        if not row:
            await conn.rollback()
            raise MarketplaceError("Deposit not found.")
        if row["status"] != "pending":
            await conn.rollback()
            raise MarketplaceError(f"Deposit already {row['status']}.")

        await conn.execute(
            """UPDATE deposits
               SET status='rejected', admin_notes=?, reviewed_by_admin_id=?, reviewed_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (reason, admin_telegram_id, dep_id)
        )
        await conn.execute(
            """INSERT INTO admin_actions
               (admin_telegram_id, action_type, target_type, target_id, details)
               VALUES (?,'reject_deposit','deposit',?,?)""",
            (admin_telegram_id, str(dep_id), f"Rejected: {reason}")
        )
        await conn.commit()

    logger.info(f"Deposit {row['deposit_code']} rejected.")
    return await get_deposit_by_id(dep_id)  # type: ignore


# ─── TRANSACTIONS ─────────────────────────────────────────────────────────────

async def get_user_transactions(user_id: int, limit: int = 15) -> List[Transaction]:
    async with get_db() as conn:
        cur = await conn.execute(
            "SELECT * FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        )
        return [
            Transaction(
                id=r["id"], tx_code=r["tx_code"], user_id=r["user_id"],
                type=r["type"], amount=float(r["amount"]),
                balance_before=float(r["balance_before"]),
                balance_after=float(r["balance_after"]),
                reference_id=r["reference_id"], description=r["description"],
                created_at=r["created_at"]
            )
            for r in await cur.fetchall()
        ]


# ─── ADMIN BALANCE ADJUSTMENT ─────────────────────────────────────────────────

async def adjust_user_balance(
    user_id: int, amount: float, direction: str,
    reason: str, admin_telegram_id: int
) -> Tuple[float, float]:
    async with get_db() as conn:
        await conn.execute("BEGIN IMMEDIATE;")
        cur = await conn.execute("SELECT wallet_balance FROM users WHERE id=?", (user_id,))
        row = await cur.fetchone()
        if not row:
            await conn.rollback()
            raise MarketplaceError("User not found.")
        bb = float(row["wallet_balance"])
        if direction == "credit":
            ba = round(bb + amount, 2)
            tx_type = "admin_credit"
        else:
            if bb < amount:
                await conn.rollback()
                raise InsufficientFundsError(f"Cannot debit ₹{amount}; balance is ₹{bb}.")
            ba = round(bb - amount, 2)
            tx_type = "admin_debit"

        await conn.execute(
            "UPDATE users SET wallet_balance=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (ba, user_id)
        )
        tc = f"TX-{uuid.uuid4().hex[:8].upper()}"
        await conn.execute(
            """INSERT INTO transactions
               (tx_code, user_id, type, amount, balance_before, balance_after, reference_id, description)
               VALUES (?,?,?,?,?,?,?,?)""",
            (tc, user_id, tx_type, amount, bb, ba, f"ADMIN-{admin_telegram_id}", reason)
        )
        await conn.execute(
            """INSERT INTO admin_actions
               (admin_telegram_id, action_type, target_type, target_id, details)
               VALUES (?,'adjust_balance','user',?,?)""",
            (admin_telegram_id, str(user_id),
             f"{direction.upper()} ₹{amount}. Reason: {reason}")
        )
        await conn.commit()
        return bb, ba


# ─── DASHBOARD STATS ──────────────────────────────────────────────────────────

async def get_admin_dashboard_stats() -> DashboardStats:
    async with get_db() as conn:
        cur = await conn.execute("SELECT COUNT(*) as c FROM users")
        total_users = (await cur.fetchone())["c"]

        cur = await conn.execute(
            "SELECT COUNT(*) as c, COALESCE(SUM(price),0) as rev FROM orders WHERE status='completed'"
        )
        r = await cur.fetchone()
        total_orders, total_revenue = r["c"], float(r["rev"])

        cur = await conn.execute(
            "SELECT COUNT(*) as c, COALESCE(SUM(amount),0) as amt FROM deposits WHERE status='pending'"
        )
        r = await cur.fetchone()
        pdc, pda = r["c"], float(r["amt"])

        cur = await conn.execute(
            "SELECT COUNT(*) as c FROM phone_numbers WHERE status='available'"
        )
        available = (await cur.fetchone())["c"]

        cur = await conn.execute(
            "SELECT COUNT(*) as c FROM phone_numbers WHERE status='sold'"
        )
        sold = (await cur.fetchone())["c"]

        # Per-country breakdown
        cur = await conn.execute(
            """SELECT c.name, c.flag_emoji,
                      SUM(CASE WHEN p.status='available' THEN 1 ELSE 0 END) as avail,
                      SUM(CASE WHEN p.status='sold'      THEN 1 ELSE 0 END) as sold_cnt
               FROM countries c
               LEFT JOIN phone_numbers p ON p.country_id=c.id
               GROUP BY c.id
               ORDER BY c.name ASC"""
        )
        breakdown = [
            (r["name"], r["flag_emoji"], r["avail"] or 0, r["sold_cnt"] or 0)
            for r in await cur.fetchall()
        ]

        return DashboardStats(
            total_users=total_users,
            total_orders=total_orders,
            total_revenue=total_revenue,
            pending_deposits_count=pdc,
            pending_deposits_amount=pda,
            available_numbers_count=available,
            sold_numbers_count=sold,
            country_breakdown=breakdown
        )


# ─── ADMIN ACTIONS LOG ────────────────────────────────────────────────────────

async def log_admin_action(
    admin_telegram_id: int, action_type: str,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    details: Optional[str] = None
) -> None:
    async with get_db() as conn:
        await conn.execute(
            """INSERT INTO admin_actions
               (admin_telegram_id, action_type, target_type, target_id, details)
               VALUES (?,?,?,?,?)""",
            (admin_telegram_id, action_type, target_type, target_id, details)
        )
        await conn.commit()
