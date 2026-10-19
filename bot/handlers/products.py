"""Country catalog browsing handler."""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from bot.database.queries import get_all_countries, get_country_by_id, get_country_stock_count
from bot.keyboards.user_kb import get_countries_keyboard, get_country_detail_keyboard
from bot.utils.formatters import escape, fmt

router = Router(name="products_router")


@router.message(F.text.in_({"🌍 Browse Numbers", "🛒 Browse Products"}))
async def handle_browse(message: Message):
    await _show_country_list(message)


@router.callback_query(F.data == "browse_countries")
async def handle_browse_cb(callback: CallbackQuery):
    countries = await get_all_countries(active_only=True)
    if not countries:
        await callback.message.edit_text(
            "🌍 <b>No countries are available right now.</b>\n"
            "<i>Please check back shortly.</i>",
            parse_mode="HTML"
        )
        await callback.answer()
        return
    await callback.message.edit_text(
        "🌍 <b>SELECT A COUNTRY</b>\n\n"
        "Choose a country to see available numbers and pricing:",
        parse_mode="HTML",
        reply_markup=get_countries_keyboard(countries)
    )
    await callback.answer()


async def _show_country_list(message: Message):
    countries = await get_all_countries(active_only=True)
    if not countries:
        await message.answer(
            "🌍 <b>No countries available yet.</b>\n<i>Check back soon!</i>",
            parse_mode="HTML"
        )
        return
    await message.answer(
        "🌍 <b>SELECT A COUNTRY</b>\n\n"
        "Choose a country below to see available phone numbers and pricing:",
        parse_mode="HTML",
        reply_markup=get_countries_keyboard(countries)
    )


@router.callback_query(F.data.startswith("country_"))
async def handle_country_selected(callback: CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) < 2 or not parts[1].isdigit():
        await callback.answer()
        return

    cid = int(parts[1])
    country = await get_country_by_id(cid)
    if not country:
        await callback.answer("Country not found.", show_alert=True)
        return

    stock = await get_country_stock_count(cid, status="available")
    stock_badge = (
        f"🟢 <b>{stock} number(s) available</b>"
        if stock > 0 else "🔴 <b>Currently out of stock</b>"
    )

    desc = country.description or "Verified phone numbers from this country. Instant delivery upon purchase."

    text = (
        f"{country.flag_emoji} <b>{escape(country.name)} Phone Numbers</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Price per Number:</b> <code>{fmt(country.price)}</code>\n"
        f"📊 <b>Stock Status:</b> {stock_badge}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 {escape(desc)}\n\n"
        f"<i>After purchase, you receive the full phone number and 2FA password instantly.</i>"
    )

    await callback.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=get_country_detail_keyboard(country, stock)
    )
    await callback.answer()
