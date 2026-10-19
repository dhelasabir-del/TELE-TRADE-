"""User-facing keyboards for the phone number marketplace."""

from typing import List
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.database.models import Country, Order
from bot.config import config


def get_main_menu_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="🌍 Browse Numbers"), KeyboardButton(text="💰 Wallet")],
        [KeyboardButton(text="📦 My Purchases"), KeyboardButton(text="🧾 Purchase History")],
        [KeyboardButton(text="💳 Deposit"),       KeyboardButton(text="📞 Support")],
    ]
    if is_admin:
        buttons.append([KeyboardButton(text="⚙️ Admin Panel")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, is_persistent=True)


def get_countries_keyboard(countries: List[Country]) -> InlineKeyboardMarkup:
    """One button per country showing name, flag, stock count and price."""
    builder = InlineKeyboardBuilder()
    for c in countries:
        builder.button(
            text=f"{c.flag_emoji} {c.name}  •  {config.CURRENCY_SYMBOL}{c.price:,.0f}",
            callback_data=f"country_{c.id}"
        )
    builder.adjust(1)
    return builder.as_markup()


def get_country_detail_keyboard(country: Country, stock: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if stock > 0:
        builder.button(
            text=f"🛍️ Buy Number  •  {config.CURRENCY_SYMBOL}{country.price:,.2f}",
            callback_data=f"buy_country_{country.id}"
        )
    else:
        builder.button(text="🔴 Out of Stock", callback_data="noop")
    builder.button(text="🔙 All Countries", callback_data="browse_countries")
    builder.adjust(1)
    return builder.as_markup()


def get_confirm_purchase_keyboard(country_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Confirm & Pay", callback_data=f"confirm_buy_{country_id}")
    builder.button(text="❌ Cancel", callback_data=f"country_{country_id}")
    builder.adjust(2)
    return builder.as_markup()


def get_wallet_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Deposit Funds", callback_data="start_deposit")
    builder.button(text="📜 Transaction History", callback_data="wallet_tx")
    builder.adjust(1)
    return builder.as_markup()


def get_deposit_entry_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📥 Submit UTR / Payment Proof", callback_data="submit_deposit")
    builder.button(text="❌ Cancel", callback_data="cancel_deposit")
    builder.adjust(1)
    return builder.as_markup()


def get_skip_screenshot_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭️ Skip Screenshot", callback_data="skip_screenshot")
    builder.button(text="❌ Cancel", callback_data="cancel_deposit")
    builder.adjust(1)
    return builder.as_markup()


def get_orders_keyboard(
    orders: List[Order], page: int = 1, has_more: bool = False
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for o in orders:
        builder.button(
            text=f"{o.country_flag} {o.order_code}  •  {o.country_name}",
            callback_data=f"order_{o.id}"
        )
    builder.adjust(1)
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="◀ Prev", callback_data=f"orders_page_{page-1}"))
    if has_more:
        nav.append(InlineKeyboardButton(text="Next ▶", callback_data=f"orders_page_{page+1}"))
    if nav:
        builder.row(*nav)
    return builder.as_markup()


def get_order_detail_keyboard(order_id: int, has_session: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if has_session:
        builder.button(text="⚡ Get OTP", callback_data=f"fetch_otp_{order_id}")
        builder.button(text="🚪 Logout Bot from Account", callback_data=f"confirm_logout_{order_id}")
    builder.button(text="🔙 Back to Orders", callback_data="view_my_purchases")
    builder.adjust(1)
    return builder.as_markup()


def get_logout_confirm_keyboard(order_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Yes, Terminate Bot Session", callback_data=f"do_logout_bot_{order_id}")
    builder.button(text="❌ Cancel", callback_data=f"order_{order_id}")
    builder.adjust(1)
    return builder.as_markup()
