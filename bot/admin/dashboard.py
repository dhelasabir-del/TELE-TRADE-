"""Admin dashboard with OTP forwarding."""

from typing import Union
from aiogram import Router, F, Bot
from aiogram.filters import Command, BaseFilter
from aiogram.types import Message, CallbackQuery, TelegramObject, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from bot.config import config
from bot.database.queries import (
    get_admin_dashboard_stats, get_order_by_code, get_order_by_id,
    log_otp_forward
)
from bot.keyboards.admin_kb import get_admin_dashboard_keyboard
from bot.keyboards.user_kb import get_main_menu_keyboard
from bot.utils.states import ForwardOtpStates
from bot.utils.formatters import escape, fmt, format_dashboard_card, format_order_card
from bot.utils.logger import logger


class IsAdmin(BaseFilter):
    async def __call__(self, obj: TelegramObject) -> bool:
        u = getattr(obj, "from_user", None)
        return bool(u and config.is_admin(u.id))


router = Router(name="admin_dashboard_router")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.message(Command("admin"))
@router.message(F.text.in_({"⚙️ Admin Panel", "⚙️ Admin Dashboard"}))
@router.callback_query(F.data == "admin_dashboard")
async def show_dashboard(event: Union[Message, CallbackQuery], state: FSMContext):
    await state.clear()
    stats = await get_admin_dashboard_stats()
    text = format_dashboard_card(stats)
    kb = get_admin_dashboard_keyboard(pending_count=stats.pending_deposits_count)

    if isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            await event.message.answer(text, parse_mode="HTML", reply_markup=kb)
        await event.answer()
    else:
        await event.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "admin_exit")
async def exit_admin(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        "👋 Back to customer view.",
        reply_markup=get_main_menu_keyboard(is_admin=True)
    )
    await callback.answer()


# ─── OTP FORWARDING (CORE FEATURE) ────────────────────────────────────────────

@router.callback_query(F.data == "admin_forward_otp")
async def start_otp_forward(callback: CallbackQuery, state: FSMContext):
    """Admin initiates OTP forwarding by entering the buyer's order code."""
    await state.set_state(ForwardOtpStates.waiting_for_order_code)
    await callback.message.answer(
        "📲 <b>FORWARD OTP TO BUYER</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Enter the <b>Order Code</b> of the buyer who purchased this number\n"
        "<i>(e.g. ORD-20260929-XXXXXX)</i>:\n\n"
        "<i>Tip: Check the buyer's order via Orders → Search if needed.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data="admin_dashboard")]
        ])
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_send_otp_"))
async def start_otp_forward_from_order(callback: CallbackQuery, state: FSMContext):
    """Admin taps 'Send OTP' directly from order view."""
    oid = int(callback.data.split("_")[3])
    from bot.database.queries import get_order_by_id as _get_order
    order = await _get_order(oid)
    if not order:
        await callback.answer("Order not found.", show_alert=True); return

    await state.update_data(
        order_id=order.id,
        order_code=order.order_code,
        buyer_telegram_id=order.user_telegram_id,
        phone_number=order.phone_number,
        country_name=order.country_name,
        country_flag=order.country_flag
    )
    await state.set_state(ForwardOtpStates.waiting_for_otp)

    await callback.message.answer(
        f"📲 <b>FORWARD OTP</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧾 <b>Order:</b> <code>{escape(order.order_code)}</code>\n"
        f"🌍 <b>Country:</b> {escape(order.country_flag)} {escape(order.country_name)}\n"
        f"📞 <b>Phone:</b> <code>{escape(order.phone_number)}</code>\n"
        f"👤 <b>Buyer ID:</b> <code>{order.user_telegram_id}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Now enter the <b>OTP code</b> you received on this number to forward to the buyer:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data="admin_dashboard")]
        ])
    )
    await callback.answer()


@router.message(ForwardOtpStates.waiting_for_order_code)
async def process_order_code_for_otp(message: Message, state: FSMContext):
    order_code = message.text.strip().upper()
    order = await get_order_by_code(order_code)
    if not order:
        await message.answer(
            f"⚠️ Order <code>{escape(order_code)}</code> not found. "
            f"Please check and re-enter the order code:",
            parse_mode="HTML"
        )
        return

    await state.update_data(
        order_id=order.id,
        order_code=order.order_code,
        buyer_telegram_id=order.user_telegram_id,
        phone_number=order.phone_number,
        country_name=order.country_name,
        country_flag=order.country_flag
    )
    await state.set_state(ForwardOtpStates.waiting_for_otp)

    await message.answer(
        f"✅ <b>Order Found!</b>\n\n"
        f"🧾 <b>Order:</b> <code>{escape(order.order_code)}</code>\n"
        f"🌍 <b>Country:</b> {escape(order.country_flag)} {escape(order.country_name)}\n"
        f"📞 <b>Phone:</b> <code>{escape(order.phone_number)}</code>\n"
        f"👤 <b>Buyer ID:</b> <code>{order.user_telegram_id}</code>\n\n"
        f"Now enter the <b>OTP / Verification Code</b> received on this number:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data="admin_dashboard")]
        ])
    )


@router.message(ForwardOtpStates.waiting_for_otp)
async def process_otp_and_forward(message: Message, state: FSMContext, bot: Bot):
    """Forward the OTP to the buyer's Telegram and log it."""
    otp = message.text.strip()
    data = await state.get_data()
    await state.clear()

    order_id = data["order_id"]
    order_code = data["order_code"]
    buyer_tg_id = data["buyer_telegram_id"]
    phone = data["phone_number"]
    country_name = data["country_name"]
    country_flag = data["country_flag"]

    # Compose delivery message to buyer
    buyer_message = (
        f"🔔 <b>OTP RECEIVED ON YOUR NUMBER</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧾 <b>Order:</b> <code>{escape(order_code)}</code>\n"
        f"🌍 <b>Country:</b> {escape(country_flag)} {escape(country_name)}\n"
        f"📞 <b>Phone Number:</b> <code>{escape(phone)}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔑 <b>OTP / Verification Code:</b>\n\n"
        f"<code>{escape(otp)}</code>\n\n"
        f"⚠️ <i>This code is time-sensitive. Use it immediately.</i>"
    )

    try:
        await bot.send_message(chat_id=buyer_tg_id, text=buyer_message, parse_mode="HTML")

        # Log the OTP forward in DB
        await log_otp_forward(
            order_id=order_id,
            order_code=order_code,
            buyer_telegram_id=buyer_tg_id,
            otp_code=otp,
            admin_telegram_id=message.from_user.id
        )

        # Confirm to admin
        await message.answer(
            f"✅ <b>OTP Forwarded Successfully!</b>\n\n"
            f"🔑 <b>OTP:</b> <code>{escape(otp)}</code>\n"
            f"🧾 <b>Order:</b> <code>{escape(order_code)}</code>\n"
            f"👤 <b>Sent To:</b> <code>{buyer_tg_id}</code>\n\n"
            f"<i>The buyer has been notified in their Telegram chat.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📲 Forward Another OTP", callback_data="admin_forward_otp")],
                [InlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="admin_dashboard")]
            ])
        )
        logger.info(f"OTP forwarded: Order {order_code} → Buyer {buyer_tg_id} by Admin {message.from_user.id}")

    except Exception as e:
        logger.error(f"OTP forward failed: {e}", exc_info=True)
        await message.answer(
            f"⚠️ <b>Failed to deliver OTP to buyer!</b>\n\n"
            f"Error: <code>{escape(str(e))}</code>\n\n"
            f"The buyer's Telegram ID (<code>{buyer_tg_id}</code>) may have blocked the bot. "
            f"Please contact them manually.\n\n"
            f"OTP to pass: <code>{escape(otp)}</code>",
            parse_mode="HTML"
        )
