"""Purchase checkout — confirm, pay, deliver phone number + 2FA + auto OTP listener."""

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from bot.database.models import User
from bot.database.queries import (
    get_country_by_id, execute_purchase, get_order_by_id,
    InsufficientFundsError, OutOfStockError, UserBlockedError
)
from bot.keyboards.user_kb import get_confirm_purchase_keyboard
from bot.services.session_service import start_auto_otp_listener, fetch_latest_telegram_code
from bot.utils.formatters import escape, fmt, format_order_card
from bot.utils.logger import logger

router = Router(name="purchases_router")


@router.callback_query(F.data.startswith("buy_country_"))
async def handle_buy_intent(callback: CallbackQuery, db_user: User):
    cid_str = callback.data.split("_")[2]
    if not cid_str.isdigit():
        await callback.answer(); return

    cid = int(cid_str)
    country = await get_country_by_id(cid)
    if not country:
        await callback.answer("Country not found.", show_alert=True); return

    price = country.price
    balance = db_user.wallet_balance

    if balance < price:
        diff = price - balance
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Deposit Funds", callback_data="start_deposit")],
            [InlineKeyboardButton(text="🔙 Back", callback_data=f"country_{cid}")]
        ])
        await callback.message.edit_text(
            f"⚠️ <b>Insufficient Balance</b>\n\n"
            f"{country.flag_emoji} <b>{escape(country.name)} Number</b>\n"
            f"💰 <b>Price:</b> <code>{fmt(price)}</code>\n"
            f"💼 <b>Your Balance:</b> <code>{fmt(balance)}</code>\n"
            f"❗ <b>Need:</b> <code>{fmt(diff)}</code> more\n\n"
            f"Please top up your wallet to continue.",
            parse_mode="HTML", reply_markup=kb
        )
        await callback.answer(); return

    confirm_text = (
        f"🛍️ <b>CONFIRM PURCHASE</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌍 <b>Country:</b> {escape(country.flag_emoji)} {escape(country.name)}\n"
        f"💰 <b>Price:</b> <code>{fmt(price)}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💳 <b>Current Balance:</b> <code>{fmt(balance)}</code>\n"
        f"📉 <b>Balance After:</b> <code>{fmt(balance - price)}</code>\n\n"
        f"<i>You will receive the full phone number, 2FA password, and automated OTP delivery "
        f"immediately after payment.</i>"
    )
    await callback.message.edit_text(
        confirm_text, parse_mode="HTML",
        reply_markup=get_confirm_purchase_keyboard(cid)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_buy_"))
async def handle_confirm_purchase(callback: CallbackQuery, db_user: User, bot: Bot):
    cid_str = callback.data.split("_")[2]
    if not cid_str.isdigit():
        await callback.answer(); return

    cid = int(cid_str)
    try:
        order, phone = await execute_purchase(
            user_telegram_id=callback.from_user.id,
            country_id=cid
        )

        card = format_order_card(order, show_sensitive=True)
        session_active = bool(order.has_session or phone.has_session)

        if session_active:
            status_note = (
                f"📱 <b>HOW TO GET YOUR LOGIN CODE / OTP:</b>\n\n"
                f"1️⃣ Open Telegram on your phone/PC and enter: <code>{escape(order.phone_number)}</code>\n"
                f"2️⃣ Tap 'Send Code' in Telegram, then tap <b>⚡ Get OTP</b> button below!\n"
                f"3️⃣ If 2FA password is required, enter: <code>{escape(order.two_fa_password or 'None')}</code>\n"
                f"4️⃣ Once logged in, tap <b>Logout Bot</b> to secure your account."
            )
            buttons = [
                [InlineKeyboardButton(text="⚡ Get OTP", callback_data=f"fetch_otp_{order.id}")],
                [InlineKeyboardButton(text="🚪 Logout Bot from Account", callback_data=f"confirm_logout_{order.id}")],
                [InlineKeyboardButton(text="📦 My Purchases", callback_data="view_my_purchases")],
                [InlineKeyboardButton(text="🌍 Browse More", callback_data="browse_countries")]
            ]
        else:
            status_note = (
                f"ℹ️ <i>If you receive an OTP on this number, contact admin or support to forward it.</i>"
            )
            buttons = [
                [InlineKeyboardButton(text="📦 My Purchases", callback_data="view_my_purchases")],
                [InlineKeyboardButton(text="🌍 Browse More", callback_data="browse_countries")]
            ]

        success_text = (
            f"🎉 <b>PURCHASE SUCCESSFUL!</b>\n\n"
            f"{card}\n\n"
            f"{status_note}"
        )

        await callback.message.edit_text(
            success_text, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
        await callback.answer("Purchase complete!", show_alert=False)

    except InsufficientFundsError as e:
        await callback.answer(str(e), show_alert=True)
    except OutOfStockError as e:
        await callback.answer(str(e), show_alert=True)
    except UserBlockedError as e:
        await callback.answer(str(e), show_alert=True)
    except Exception as e:
        logger.error(f"Purchase error: {e}", exc_info=True)
        await callback.answer("Unexpected error. Please try again.", show_alert=True)


@router.callback_query(F.data.startswith("fetch_otp_"))
async def handle_fetch_otp_manual(callback: CallbackQuery):
    """Fetch and reveal the login code only when buyer explicitly clicks Get OTP."""
    oid_str = callback.data.split("_")[2]
    if not oid_str.isdigit():
        await callback.answer(); return

    oid = int(oid_str)
    order = await get_order_by_id(oid)
    if not order or order.user_telegram_id != callback.from_user.id:
        await callback.answer("Order not found.", show_alert=True); return

    session_id = order.session_string or order.session_file
    if not session_id:
        await callback.answer("No automatic session attached to this order. Contact support if needed.", show_alert=True)
        return

    await callback.answer("🔍 Checking session for login code...", show_alert=False)

    code_info = await fetch_latest_telegram_code(session_id)
    if not code_info:
        await callback.message.answer(
            f"⏳ <b>No login code received yet for {escape(order.phone_number)}</b>\n\n"
            f"Please make sure you entered the number in your Telegram app and pressed 'Send Code'.\n\n"
            f"Then tap <b>⚡ Get OTP</b> again below!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚡ Get OTP (Check Again)", callback_data=f"fetch_otp_{order.id}")],
                [InlineKeyboardButton(text="🚪 Logout Bot from Account", callback_data=f"confirm_logout_{order.id}")],
                [InlineKeyboardButton(text="📦 My Purchases", callback_data="view_my_purchases")]
            ])
        )
        return

    otp = code_info["otp"]
    msg_text = code_info.get("message_text", "")

    delivery_text = (
        f"⚡ <b>TELEGRAM LOGIN CODE</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧾 <b>Order:</b> <code>{escape(order.order_code)}</code>\n"
        f"📞 <b>Phone Number:</b> <code>{escape(order.phone_number)}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔑 <b>Your Login Code:</b>\n\n"
        f"<code>{escape(otp)}</code>\n\n"
    )
    if order.two_fa_password:
        delivery_text += f"🔐 <b>2FA Password:</b> <code>{escape(order.two_fa_password)}</code>\n\n"
    delivery_text += (
        f"📝 <b>Official Notice:</b>\n"
        f"<i>{escape(msg_text[:200])}</i>\n\n"
        f"💡 <i>Once you are logged in on your device, tap <b>Logout Bot</b> below to secure the account.</i>"
    )

    await callback.message.answer(
        delivery_text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Get OTP Again", callback_data=f"fetch_otp_{order.id}")],
            [InlineKeyboardButton(text="🚪 Logout Bot from Account", callback_data=f"confirm_logout_{order.id}")],
            [InlineKeyboardButton(text="📦 My Purchases", callback_data="view_my_purchases")]
        ])
    )


@router.callback_query(F.data.startswith("confirm_logout_"))
async def handle_confirm_logout(callback: CallbackQuery):
    """Show confirmation prompt before terminating bot device session."""
    oid_str = callback.data.split("_")[2]
    if not oid_str.isdigit():
        await callback.answer(); return

    oid = int(oid_str)
    order = await get_order_by_id(oid)
    if not order or order.user_telegram_id != callback.from_user.id:
        await callback.answer("Order not found.", show_alert=True); return

    if not (order.session_string or order.session_file):
        await callback.answer("Bot session is already logged out / not present.", show_alert=True)
        return

    from bot.keyboards.user_kb import get_logout_confirm_keyboard
    confirm_text = (
        f"🚪 <b>TERMINATE BOT DEVICE SESSION</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧾 <b>Order:</b> <code>{escape(order.order_code)}</code>\n"
        f"📞 <b>Phone:</b> <code>{escape(order.phone_number)}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <b>IMPORTANT:</b>\n"
        f"• Make sure you have <b>already logged in</b> on your Telegram app first!\n"
        f"• Terminating this session will log out the bot device from Telegram servers permanently.\n"
        f"• After logout, the bot will <b>no longer receive OTPs</b> for this number.\n\n"
        f"Do you want to terminate the bot's session now?"
    )
    await callback.message.edit_text(
        confirm_text, parse_mode="HTML",
        reply_markup=get_logout_confirm_keyboard(order.id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("do_logout_bot_"))
async def handle_do_logout_bot(callback: CallbackQuery):
    """Execute Telegram client logout and remove session credentials."""
    oid_str = callback.data.split("_")[3]
    if not oid_str.isdigit():
        await callback.answer(); return

    oid = int(oid_str)
    order = await get_order_by_id(oid)
    if not order or order.user_telegram_id != callback.from_user.id:
        await callback.answer("Order not found.", show_alert=True); return

    session_id = order.session_string or order.session_file
    if not session_id:
        await callback.answer("Bot session is already logged out.", show_alert=True)
        return

    await callback.answer("🔄 Terminating bot session...", show_alert=False)

    from bot.services.session_service import logout_session
    from bot.database.database import get_db

    # Execute logout on Telegram servers
    await logout_session(session_id)

    # Clear session credentials on order
    async with get_db() as conn:
        await conn.execute("UPDATE orders SET session_string=NULL, session_file=NULL WHERE id=?", (order.id,))
        await conn.commit()

    success_text = (
        f"✅ <b>BOT SESSION TERMINATED!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧾 <b>Order:</b> <code>{escape(order.order_code)}</code>\n"
        f"📞 <b>Phone:</b> <code>{escape(order.phone_number)}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛡️ The bot device has been logged out from Telegram servers.\n"
        f"🔒 You now have <b>100% exclusive access</b> to this account."
    )
    await callback.message.edit_text(
        success_text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📦 My Purchases", callback_data="view_my_purchases")],
            [InlineKeyboardButton(text="🌍 Browse More", callback_data="browse_countries")]
        ])
    )


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    await callback.answer()
