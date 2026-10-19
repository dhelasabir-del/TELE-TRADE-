"""Admin user management — search, balance, block/unblock."""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from bot.admin.dashboard import IsAdmin
from bot.database.queries import (
    search_users, get_user_by_id, set_user_blocked,
    adjust_user_balance, get_user_orders, get_user_deposits,
    InsufficientFundsError, MarketplaceError, log_admin_action
)
from bot.keyboards.admin_kb import get_admin_users_keyboard, get_user_actions_keyboard
from bot.utils.states import SearchUserStates, AdjustBalanceStates
from bot.utils.formatters import escape, fmt, format_user_card
from bot.utils.logger import logger

router = Router(name="admin_users_router")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.callback_query(F.data == "admin_users_menu")
async def users_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "👥 <b>USER MANAGEMENT</b>\n\nSearch by Telegram ID, username, or internal ID:",
        parse_mode="HTML",
        reply_markup=get_admin_users_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "adm_search_users")
async def prompt_user_search(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SearchUserStates.waiting_for_query)
    await callback.message.edit_text(
        "🔍 <b>Search Users</b>\n\nEnter Telegram ID, @username, or account ID (e.g. USR-1001):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data="admin_users_menu")]
        ])
    )
    await callback.answer()


@router.message(SearchUserStates.waiting_for_query)
async def process_user_search(message: Message, state: FSMContext):
    query = message.text.strip().replace("@", "")
    await state.clear()

    users = await search_users(query)
    if not users:
        await message.answer(
            f"🔍 No users found for: <code>{escape(query)}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔍 Search Again", callback_data="adm_search_users")],
                [InlineKeyboardButton(text="🔙 Back", callback_data="admin_users_menu")]
            ])
        )
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{'🚫' if u.is_blocked else '🟢'} {u.internal_id}  @{u.username or u.telegram_id}  ₹{u.wallet_balance:.2f}",
            callback_data=f"adm_view_usr_{u.id}"
        )]
        for u in users
    ] + [[InlineKeyboardButton(text="🔙 Back", callback_data="admin_users_menu")]])

    await message.answer(
        f"🔍 <b>Found {len(users)} user(s):</b>",
        parse_mode="HTML", reply_markup=kb
    )


@router.callback_query(F.data.startswith("adm_view_usr_"))
async def show_user_profile(callback: CallbackQuery):
    uid = int(callback.data.split("_")[3])
    user = await get_user_by_id(uid)
    if not user:
        await callback.answer("User not found.", show_alert=True)
        return

    orders = await get_user_orders(uid, limit=200)
    spent = sum(o.price for o in orders if o.status == "completed")

    await callback.message.edit_text(
        format_user_card(user, total_orders=len(orders), total_spent=spent),
        parse_mode="HTML",
        reply_markup=get_user_actions_keyboard(user)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_toggle_block_"))
async def toggle_block(callback: CallbackQuery):
    uid = int(callback.data.split("_")[3])
    user = await get_user_by_id(uid)
    if not user:
        await callback.answer("User not found.", show_alert=True)
        return

    new_state = not user.is_blocked
    await set_user_blocked(uid, new_state)
    word = "BLOCKED" if new_state else "UNBLOCKED"
    await log_admin_action(
        callback.from_user.id, "toggle_block", "user", str(uid), word
    )
    await callback.answer(f"User {word}.", show_alert=True)
    callback.data = f"adm_view_usr_{uid}"
    await show_user_profile(callback)


# ─── BALANCE ADJUSTMENT ───────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_credit_user_") | F.data.startswith("adm_debit_user_"))
async def prompt_balance_adjust(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    direction = parts[1]          # 'credit' or 'debit'
    uid = int(parts[3])

    user = await get_user_by_id(uid)
    if not user:
        await callback.answer("User not found.", show_alert=True)
        return

    await state.update_data(user_id=uid, direction=direction, user_iid=user.internal_id)
    await state.set_state(AdjustBalanceStates.waiting_for_amount)

    label = "ADD FUNDS (Credit)" if direction == "credit" else "DEDUCT FUNDS (Debit)"
    await callback.message.edit_text(
        f"💰 <b>{label}</b>\n\n"
        f"User: <code>{escape(user.internal_id)}</code>\n"
        f"Current Balance: <code>{fmt(user.wallet_balance)}</code>\n\n"
        f"Enter the amount in INR:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data=f"adm_view_usr_{uid}")]
        ])
    )
    await callback.answer()


@router.message(AdjustBalanceStates.waiting_for_amount)
async def adjust_amount(message: Message, state: FSMContext):
    txt = message.text.strip().replace("₹", "").replace(",", "")
    try:
        amount = float(txt)
        if amount <= 0:
            raise ValueError()
    except ValueError:
        await message.answer("⚠️ Enter a valid positive number:")
        return

    await state.update_data(amount=amount)
    await state.set_state(AdjustBalanceStates.waiting_for_reason)
    await message.answer(
        f"📝 <b>Reason for Adjustment</b>\n\n"
        f"Amount: <code>{fmt(amount)}</code>\n\n"
        f"Enter a short audit reason (e.g. <i>Manual top-up</i>, <i>Correction</i>):",
        parse_mode="HTML"
    )


@router.message(AdjustBalanceStates.waiting_for_reason)
async def adjust_reason(message: Message, state: FSMContext):
    reason = message.text.strip()
    data = await state.get_data()
    uid = data["user_id"]
    direction = data["direction"]
    amount = data["amount"]
    await state.clear()

    try:
        bb, ba = await adjust_user_balance(
            user_id=uid,
            amount=amount,
            direction=direction,
            reason=reason,
            admin_telegram_id=message.from_user.id
        )
        sign = "+" if direction == "credit" else "-"
        await message.answer(
            f"✅ <b>Balance Adjusted!</b>\n\n"
            f"User: <code>{escape(data['user_iid'])}</code>\n"
            f"Change: <code>{sign}{fmt(amount)}</code>\n"
            f"Before: <code>{fmt(bb)}</code> → After: <code>{fmt(ba)}</code>\n"
            f"Reason: <i>{escape(reason)}</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Back to User", callback_data=f"adm_view_usr_{uid}")]
            ])
        )
    except InsufficientFundsError as e:
        await message.answer(f"⚠️ {escape(str(e))}", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Balance adjust error: {e}", exc_info=True)
        await message.answer("⚠️ Error adjusting balance.")


# ─── USER ORDERS / DEPOSITS ───────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_user_orders_"))
async def user_orders(callback: CallbackQuery):
    uid = int(callback.data.split("_")[3])
    orders = await get_user_orders(uid, limit=20)

    if not orders:
        await callback.message.edit_text(
            f"📦 No orders for user #{uid}.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Back", callback_data=f"adm_view_usr_{uid}")]
            ])
        )
        await callback.answer()
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{o.country_flag} #{o.order_code}  •  ₹{o.price:.0f} ({o.status})",
            callback_data=f"adm_view_ord_{o.id}"
        )]
        for o in orders
    ] + [[InlineKeyboardButton(text="🔙 Back", callback_data=f"adm_view_usr_{uid}")]])

    await callback.message.edit_text(
        f"📦 <b>Orders for user #{uid} ({len(orders)}):</b>",
        parse_mode="HTML", reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_user_deposits_"))
async def user_deposits(callback: CallbackQuery):
    uid = int(callback.data.split("_")[3])
    deposits = await get_user_deposits(uid, limit=15)

    if not deposits:
        await callback.message.edit_text(
            f"💳 No deposits for user #{uid}.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Back", callback_data=f"adm_view_usr_{uid}")]
            ])
        )
        await callback.answer()
        return

    lines = [f"💳 <b>Deposits for user #{uid} ({len(deposits)}):</b>\n━━━━━━━━━━━━━━━━━━━━━━"]
    for d in deposits:
        lines.append(
            f"• <code>{escape(d.deposit_code)}</code>  "
            f"<code>{fmt(d.amount)}</code>  ({d.status.upper()})\n"
            f"  UTR: <code>{escape(d.utr)}</code>  |  <i>{escape(d.created_at[:16])}</i>"
        )

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back", callback_data=f"adm_view_usr_{uid}")]
        ])
    )
    await callback.answer()


# ─── ANTI-ABUSE & STRIKE ADMIN COMMANDS ───────────────────────────────────────

from bot.services.anti_abuse import (
    get_user_strike_status, reset_user_strikes, get_banned_users_list,
    get_recent_strike_log
)
from bot.database.queries import get_user_by_telegram_id, get_user_by_internal_id


async def _resolve_user_arg(raw: str):
    """Find a user by Telegram ID, internal ID (USR-1001), or @username."""
    clean = raw.strip().replace("@", "")
    if clean.isdigit():
        u = await get_user_by_telegram_id(int(clean))
        if u:
            return u
        u = await get_user_by_id(int(clean))
        if u:
            return u
    elif clean.upper().startswith("USR-"):
        u = await get_user_by_internal_id(clean.upper())
        if u:
            return u

    found = await search_users(clean)
    return found[0] if found else None


@router.message(F.text.startswith("/ban"))
async def admin_ban_cmd(message: Message):
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("⚠️ Usage: <code>/ban &lt;user_id | @username | USR-1001&gt;</code>", parse_mode="HTML")
        return

    user = await _resolve_user_arg(parts[1])
    if not user:
        await message.answer(f"❌ User not found for: <code>{escape(parts[1])}</code>", parse_mode="HTML")
        return

    await set_user_blocked(user.id, True)
    await log_admin_action(message.from_user.id, "ban_user", "user", str(user.id), f"Admin banned {user.internal_id}")
    await message.answer(
        f"🚫 <b>USER BANNED</b>\n\n"
        f"👤 <b>User:</b> {escape(user.display_name)} (<code>{user.internal_id}</code>)\n"
        f"🆔 <b>Telegram ID:</b> <code>{user.telegram_id}</code>\n"
        f"🛡️ <i>User account has been blocked from all purchases & deposits.</i>",
        parse_mode="HTML"
    )


@router.message(F.text.startswith("/unban"))
async def admin_unban_cmd(message: Message):
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("⚠️ Usage: <code>/unban &lt;user_id | @username | USR-1001&gt;</code>", parse_mode="HTML")
        return

    user = await _resolve_user_arg(parts[1])
    if not user:
        await message.answer(f"❌ User not found for: <code>{escape(parts[1])}</code>", parse_mode="HTML")
        return

    await set_user_blocked(user.id, False)
    await log_admin_action(message.from_user.id, "unban_user", "user", str(user.id), f"Admin unbanned {user.internal_id}")
    await message.answer(
        f"🟢 <b>USER UNBANNED</b>\n\n"
        f"👤 <b>User:</b> {escape(user.display_name)} (<code>{user.internal_id}</code>)\n"
        f"🆔 <b>Telegram ID:</b> <code>{user.telegram_id}</code>\n"
        f"✨ <i>Account restrictions removed.</i>",
        parse_mode="HTML"
    )


@router.message(F.text.startswith("/strikes"))
async def admin_strikes_cmd(message: Message):
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        # No user specified -> display recent system-wide strike log
        await show_strike_log_message(message)
        return

    user = await _resolve_user_arg(parts[1])
    if not user:
        await message.answer(f"❌ User not found for: <code>{escape(parts[1])}</code>", parse_mode="HTML")
        return

    await show_user_strikes_detail(message, user)


@router.message(F.text.startswith("/resetstrikes"))
async def admin_reset_strikes_cmd(message: Message):
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("⚠️ Usage: <code>/resetstrikes &lt;user_id | @username | USR-1001&gt;</code>", parse_mode="HTML")
        return

    user = await _resolve_user_arg(parts[1])
    if not user:
        await message.answer(f"❌ User not found for: <code>{escape(parts[1])}</code>", parse_mode="HTML")
        return

    reset_count = await reset_user_strikes(user.id)
    await log_admin_action(message.from_user.id, "reset_strikes", "user", str(user.id), f"Reset {reset_count} strikes")
    await message.answer(
        f"✨ <b>STRIKES RESET</b>\n\n"
        f"👤 <b>User:</b> {escape(user.display_name)} (<code>{user.internal_id}</code>)\n"
        f"Cleared <b>{reset_count}</b> strike(s). Cooldowns reset.",
        parse_mode="HTML"
    )


@router.message(F.text.in_({"/banned", "/bannedusers"}))
@router.callback_query(F.data == "adm_banned_users")
async def admin_banned_users(event: Union[Message, CallbackQuery]):
    users = await get_banned_users_list()
    if not users:
        text = "🚫 <b>BANNED USERS LIST</b>\n\n✨ All clear — no users are currently banned."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back to Users", callback_data="admin_users_menu")]
        ])
    else:
        lines = [f"🚫 <b>BANNED USERS ({len(users)})</b>\n━━━━━━━━━━━━━━━━━━━━━━"]
        buttons = []
        for u in users:
            lines.append(
                f"• <code>{u.internal_id}</code> | <b>{escape(u.display_name)}</b> | TG: <code>{u.telegram_id}</code>"
            )
            buttons.append([InlineKeyboardButton(
                text=f"🟢 Unban {u.internal_id} ({u.display_name})",
                callback_data=f"adm_toggle_block_{u.id}"
            )])
        buttons.append([InlineKeyboardButton(text="🔙 Back to Users", callback_data="admin_users_menu")])
        text = "\n".join(lines)
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await event.answer()
    else:
        await event.answer(text, parse_mode="HTML", reply_markup=kb)


@router.message(F.text.in_({"/strikelog", "/strikeslog"}))
@router.callback_query(F.data == "adm_strike_log")
async def admin_strike_log_cb(event: Union[Message, CallbackQuery]):
    if isinstance(event, CallbackQuery):
        await show_strike_log_message(event.message)
        await event.answer()
    else:
        await show_strike_log_message(event)


async def show_strike_log_message(target: Message):
    logs = await get_recent_strike_log(limit=25)
    if not logs:
        text = "⚡ <b>SYSTEM STRIKE LOG</b>\n\n✨ No strikes recorded in the system yet."
    else:
        lines = [f"⚡ <b>SYSTEM STRIKE LOG (Recent {len(logs)})</b>\n━━━━━━━━━━━━━━━━━━━━━━"]
        for entry in logs:
            status_ico = "🔴" if entry["is_active"] else "⚪"
            u_disp = f"@{entry['username']}" if entry["username"] else str(entry["telegram_id"])
            lines.append(
                f"{status_ico} <b>{escape(u_disp)}</b> (<code>{entry['internal_id']}</code>):\n"
                f"  📝 <i>{escape(entry['reason'])}</i>\n"
                f"  🕒 <code>{escape(str(entry['created_at'])[:16])}</code>"
            )
        text = "\n".join(lines)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back to Users", callback_data="admin_users_menu")]
    ])
    try:
        await target.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await target.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("adm_user_strikes_"))
async def adm_user_strikes_cb(callback: CallbackQuery):
    uid = int(callback.data.split("_")[3])
    user = await get_user_by_id(uid)
    if not user:
        await callback.answer("User not found.", show_alert=True)
        return
    await show_user_strikes_detail(callback.message, user, edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith("adm_reset_strikes_"))
async def adm_reset_strikes_cb(callback: CallbackQuery):
    uid = int(callback.data.split("_")[3])
    user = await get_user_by_id(uid)
    if not user:
        await callback.answer("User not found.", show_alert=True)
        return

    count = await reset_user_strikes(uid)
    await callback.answer(f"Reset {count} strikes.", show_alert=True)
    await show_user_strikes_detail(callback.message, user, edit=True)


async def show_user_strikes_detail(target: Message, user: User, edit: bool = False):
    status = await get_user_strike_status(user.id)
    active_cnt = status["active_strikes_count"]
    total_cnt = status["total_strikes_count"]

    cd_text = f"⏳ <b>Cooldown:</b> {status['cooldown_formatted']} remaining\n" if status["in_cooldown"] else "🟢 <b>Cooldown:</b> None (Active)\n"
    ban_text = "🚫 <b>Banned:</b> YES\n" if status["is_banned"] else "🟢 <b>Banned:</b> No\n"

    lines = [
        f"⚡ <b>STRIKE RECORD — {escape(user.display_name)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>Account ID:</b> <code>{escape(user.internal_id)}</code>\n"
        f"📱 <b>Telegram ID:</b> <code>{user.telegram_id}</code>\n"
        f"⚠️ <b>Active Strikes:</b> <b>{active_cnt}/3</b> (Last 30 Days)\n"
        f"📊 <b>Total Recorded:</b> <code>{total_cnt}</code>\n"
        f"{cd_text}"
        f"{ban_text}"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    ]

    if not status["strikes"]:
        lines.append("✨ <i>No strikes on record for this user.</i>")
    else:
        for s in status["strikes"][:10]:
            act_badge = "🔴 Active" if s["is_active"] else "⚪ Resolved/Expired"
            lines.append(
                f"• [{act_badge}] <code>{escape(str(s['created_at'])[:16])}</code>\n"
                f"  <i>{escape(s['reason'])}</i>"
            )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Reset Strikes", callback_data=f"adm_reset_strikes_{user.id}")],
        [InlineKeyboardButton(text=f"{'🟢 Unban' if user.is_blocked else '🚫 Ban'}", callback_data=f"adm_toggle_block_{user.id}")],
        [InlineKeyboardButton(text="🔙 Back to Profile", callback_data=f"adm_view_usr_{user.id}")]
    ])

    text = "\n".join(lines)
    if edit:
        try:
            await target.edit_text(text, parse_mode="HTML", reply_markup=kb)
            return
        except Exception:
            pass
    await target.answer(text, parse_mode="HTML", reply_markup=kb)
