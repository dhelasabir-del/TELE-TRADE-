"""Purchase history and support."""

from typing import Union

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from bot.config import config
from bot.database.models import User
from bot.database.queries import get_user_orders, get_order_by_id
from bot.keyboards.user_kb import get_orders_keyboard, get_order_detail_keyboard
from bot.utils.formatters import escape, format_order_card

router = Router(name="history_router")


@router.message(F.text.in_({"📦 My Purchases", "🧾 Purchase History"}))
@router.callback_query(F.data == "view_my_purchases")
async def handle_my_purchases(event: Union[Message, CallbackQuery], db_user: User):
    orders = await get_user_orders(db_user.id, limit=10)
    if not orders:
        empty = (
            "📦 <b>No purchases yet.</b>\n\n"
            "<i>Browse available phone numbers via <b>🌍 Browse Numbers</b>.</i>"
        )
        if isinstance(event, CallbackQuery):
            await event.message.edit_text(empty, parse_mode="HTML"); await event.answer()
        else:
            await event.answer(empty, parse_mode="HTML")
        return

    text = (
        "📦 <b>YOUR PURCHASE HISTORY</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Tap any order to view details, phone number, and 2FA password:"
    )
    has_more = len(orders) >= 10
    kb = get_orders_keyboard(orders, page=1, has_more=has_more)

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await event.answer()
    else:
        await event.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("orders_page_"))
async def handle_orders_page(callback: CallbackQuery, db_user: User):
    page = int(callback.data.split("_")[2])
    offset = (page - 1) * 10
    orders = await get_user_orders(db_user.id, limit=10, offset=offset)
    if not orders:
        await callback.answer("No more orders.", show_alert=True); return

    next_page = await get_user_orders(db_user.id, limit=1, offset=offset + 10)
    kb = get_orders_keyboard(orders, page=page, has_more=bool(next_page))
    await callback.message.edit_text(
        f"📦 <b>PURCHASE HISTORY (Page {page})</b>\n\nTap any order for details:",
        parse_mode="HTML", reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data.startswith("order_"))
async def handle_order_detail(callback: CallbackQuery, db_user: User):
    oid = int(callback.data.split("_")[1])
    order = await get_order_by_id(oid)
    if not order or order.user_id != db_user.id:
        await callback.answer("Order not found.", show_alert=True); return

    await callback.message.edit_text(
        format_order_card(order, show_sensitive=True),
        parse_mode="HTML",
        reply_markup=get_order_detail_keyboard(order.id, has_session=bool(order.session_file))
    )
    await callback.answer()


@router.message(F.text == "📞 Support")
async def handle_support(message: Message, db_user: User):
    await message.answer(
        f"📞 <b>CUSTOMER SUPPORT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Need help? Contact us:\n\n"
        f"🔹 <b>Support:</b> {config.SUPPORT_CONTACT}\n"
        f"🔹 <b>Your Account ID:</b> <code>{escape(db_user.internal_id)}</code>\n"
        f"🔹 <b>Your Telegram ID:</b> <code>{db_user.telegram_id}</code>\n\n"
        f"📌 When contacting support, please include:\n"
        f"• Your Order Code (e.g. <code>ORD-20260929-XXXXXX</code>)\n"
        f"• Or your Deposit UTR for deposit issues.",
        parse_mode="HTML"
    )
