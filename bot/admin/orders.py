"""Admin order management."""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from bot.admin.dashboard import IsAdmin
from bot.database.queries import get_order_by_id, search_orders, update_order_status
from bot.keyboards.admin_kb import get_admin_orders_keyboard, get_admin_order_actions_keyboard
from bot.utils.states import SearchOrderStates
from bot.utils.formatters import escape, format_order_card

router = Router(name="admin_orders_router")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.callback_query(F.data == "admin_orders_menu")
async def orders_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "📋 <b>ORDERS MANAGEMENT</b>\n\nSearch or view recent orders:",
        parse_mode="HTML",
        reply_markup=get_admin_orders_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "adm_recent_orders")
async def recent_orders(callback: CallbackQuery):
    orders = await search_orders("all", "", limit=15)
    if not orders:
        await callback.message.edit_text(
            "📋 No orders yet.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Back", callback_data="admin_orders_menu")]
            ])
        )
        await callback.answer(); return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{o.country_flag} #{o.order_code} • ₹{o.price:.0f} ({o.status})",
            callback_data=f"adm_view_ord_{o.id}"
        )]
        for o in orders
    ] + [[InlineKeyboardButton(text="🔙 Back", callback_data="admin_orders_menu")]])

    await callback.message.edit_text(
        "📋 <b>Recent 15 Orders:</b>", parse_mode="HTML", reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data.in_({"adm_search_order_id", "adm_search_user_id", "adm_search_country"}))
async def prompt_search(callback: CallbackQuery, state: FSMContext):
    qt = {
        "adm_search_order_id": "order_id",
        "adm_search_user_id": "telegram_id",
        "adm_search_country": "country"
    }[callback.data]
    label = {
        "order_id": "Order Code (e.g. ORD-...)",
        "telegram_id": "Telegram User ID",
        "country": "Country Name (e.g. India)"
    }[qt]
    await state.update_data(query_type=qt)
    await state.set_state(SearchOrderStates.waiting_for_query)
    await callback.message.edit_text(
        f"🔍 <b>Search by {label}:</b>\n\nEnter your search term:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data="admin_orders_menu")]
        ])
    )
    await callback.answer()


@router.message(SearchOrderStates.waiting_for_query)
async def process_order_search(message: Message, state: FSMContext):
    data = await state.get_data()
    qt = data.get("query_type", "order_id")
    qv = message.text.strip()
    await state.clear()

    orders = await search_orders(qt, qv, limit=20)
    if not orders:
        await message.answer(
            f"🔍 No orders found for: <code>{escape(qv)}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Back to Orders", callback_data="admin_orders_menu")]
            ])
        )
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{o.country_flag} #{o.order_code} • ₹{o.price:.0f} ({o.status})",
            callback_data=f"adm_view_ord_{o.id}"
        )]
        for o in orders
    ] + [[InlineKeyboardButton(text="🔙 Back", callback_data="admin_orders_menu")]])

    await message.answer(
        f"🔍 <b>{len(orders)} order(s) found:</b>",
        parse_mode="HTML", reply_markup=kb
    )


@router.callback_query(F.data.startswith("adm_view_ord_"))
async def view_order(callback: CallbackQuery):
    oid = int(callback.data.split("_")[3])
    order = await get_order_by_id(oid)
    if not order:
        await callback.answer("Order not found.", show_alert=True); return

    card = format_order_card(order, show_sensitive=True)
    card += f"\n\n👤 <b>Buyer Telegram ID:</b> <code>{order.user_telegram_id}</code>"

    await callback.message.edit_text(
        card, parse_mode="HTML",
        reply_markup=get_admin_order_actions_keyboard(order)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_refund_order_"))
async def refund_order(callback: CallbackQuery):
    oid = int(callback.data.split("_")[3])
    ok = await update_order_status(oid, "refunded", callback.from_user.id)
    await callback.answer("Order REFUNDED and wallet credited!" if ok else "Failed.", show_alert=True)
    if ok:
        callback.data = f"adm_view_ord_{oid}"
        await view_order(callback)


@router.callback_query(F.data.startswith("adm_cancel_order_"))
async def cancel_order(callback: CallbackQuery):
    oid = int(callback.data.split("_")[3])
    ok = await update_order_status(oid, "cancelled", callback.from_user.id)
    await callback.answer("Order CANCELLED." if ok else "Failed.", show_alert=True)
    if ok:
        callback.data = f"adm_view_ord_{oid}"
        await view_order(callback)
