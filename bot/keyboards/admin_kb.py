"""Admin keyboards for the phone number marketplace."""

from typing import List
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bot.database.models import Country, Deposit, Order, User, PhoneNumber


def get_admin_dashboard_keyboard(pending_count: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Refresh Dashboard", callback_data="admin_dashboard")
    builder.button(text="🌍 Manage Countries", callback_data="admin_countries_menu")
    builder.button(text="📱 Manage Numbers", callback_data="admin_numbers_menu")
    builder.button(text="📋 Orders", callback_data="admin_orders_menu")
    dep_lbl = f"💳 Pending Deposits ({pending_count})" if pending_count else "💳 Deposits"
    builder.button(text=dep_lbl, callback_data="admin_deposits_menu")
    builder.button(text="👥 Users", callback_data="admin_users_menu")
    builder.button(text="📲 Forward OTP to Buyer", callback_data="admin_forward_otp")
    builder.button(text="🔙 Exit Panel", callback_data="admin_exit")
    builder.adjust(1, 2, 2, 2, 1, 1)
    return builder.as_markup()


def get_admin_countries_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Add New Country", callback_data="admin_add_country")
    builder.button(text="📝 Edit / Manage Countries", callback_data="admin_list_countries")
    builder.button(text="🔙 Back to Dashboard", callback_data="admin_dashboard")
    builder.adjust(1)
    return builder.as_markup()


def get_countries_list_keyboard(countries: List[Country]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for c in countries:
        status = "🟢" if c.is_active else "🔴"
        builder.button(
            text=f"{status} {c.flag_emoji} {c.name}  •  ₹{c.price:,.0f}",
            callback_data=f"adm_country_{c.id}"
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Back", callback_data="admin_countries_menu"))
    return builder.as_markup()


def get_country_actions_keyboard(country: Country) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Edit Name", callback_data=f"adm_edit_cname_{country.id}")
    builder.button(text="✏️ Edit Price", callback_data=f"adm_edit_cprice_{country.id}")
    builder.button(text="✏️ Edit Flag/Emoji", callback_data=f"adm_edit_cflag_{country.id}")
    builder.button(text="✏️ Edit Description", callback_data=f"adm_edit_cdesc_{country.id}")
    toggle_lbl = "🔴 Disable Country" if country.is_active else "🟢 Enable Country"
    builder.button(text=toggle_lbl, callback_data=f"adm_toggle_country_{country.id}")
    builder.button(text="🗑️ Delete Country", callback_data=f"adm_delete_country_{country.id}")
    builder.button(text="📱 View Numbers", callback_data=f"adm_country_numbers_{country.id}")
    builder.button(text="🔙 Back to Countries", callback_data="admin_list_countries")
    builder.adjust(2, 2, 2, 1, 1)
    return builder.as_markup()


def get_admin_numbers_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Add Single Number", callback_data="admin_add_number")
    builder.button(text="📦 Bulk Add Numbers", callback_data="admin_bulk_add_numbers")
    builder.button(text="📁 Sync .session Folder", callback_data="admin_sync_sessions")
    builder.button(text="📋 View Available Numbers", callback_data="admin_view_available_numbers")
    builder.button(text="🔴 View Sold Numbers", callback_data="admin_view_sold_numbers")
    builder.button(text="🔙 Back to Dashboard", callback_data="admin_dashboard")
    builder.adjust(1, 2, 2, 1)
    return builder.as_markup()


def get_country_select_keyboard(
    countries: List[Country], callback_prefix: str
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for c in countries:
        builder.button(
            text=f"{c.flag_emoji} {c.name}",
            callback_data=f"{callback_prefix}_{c.id}"
        )
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="❌ Cancel", callback_data="admin_numbers_menu"))
    return builder.as_markup()


def get_number_actions_keyboard(num: PhoneNumber) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if num.status == "available":
        builder.button(text="🔴 Disable", callback_data=f"adm_disable_num_{num.id}")
    elif num.status == "disabled":
        builder.button(text="🟢 Enable", callback_data=f"adm_enable_num_{num.id}")
    builder.button(text="🗑️ Delete", callback_data=f"adm_delete_num_{num.id}")
    builder.button(text="🔙 Back", callback_data="admin_numbers_menu")
    builder.adjust(2, 1)
    return builder.as_markup()


def get_admin_orders_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔍 Search by Order Code", callback_data="adm_search_order_id")
    builder.button(text="🔍 Search by Telegram ID", callback_data="adm_search_user_id")
    builder.button(text="🔍 Search by Country", callback_data="adm_search_country")
    builder.button(text="📋 Recent 15 Orders", callback_data="adm_recent_orders")
    builder.button(text="🔙 Back to Dashboard", callback_data="admin_dashboard")
    builder.adjust(1)
    return builder.as_markup()


def get_admin_order_actions_keyboard(order: Order) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if order.status == "completed":
        builder.button(text="🔄 Refund Order", callback_data=f"adm_refund_order_{order.id}")
        builder.button(text="❌ Cancel Order", callback_data=f"adm_cancel_order_{order.id}")
    builder.button(text="📲 Send OTP to Buyer", callback_data=f"adm_send_otp_{order.id}")
    builder.button(text="🔙 Back to Orders", callback_data="admin_orders_menu")
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def get_deposits_list_keyboard(deposits: List[Deposit]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for d in deposits:
        u = f"@{d.user_username}" if d.user_username else str(d.user_telegram_id)
        builder.button(
            text=f"💳 {d.deposit_code}  •  ₹{d.amount:.2f}  ({u})",
            callback_data=f"adm_view_dep_{d.id}"
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🔙 Back", callback_data="admin_dashboard"))
    return builder.as_markup()


def get_deposit_decision_keyboard(dep_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Approve", callback_data=f"adm_approve_dep_{dep_id}")
    builder.button(text="❌ Reject",  callback_data=f"adm_reject_dep_{dep_id}")
    builder.button(text="🔙 Back",   callback_data="admin_deposits_menu")
    builder.adjust(2, 1)
    return builder.as_markup()


def get_admin_users_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔍 Search User", callback_data="adm_search_users")
    builder.button(text="🚫 Banned Users List", callback_data="adm_banned_users")
    builder.button(text="⚡ System Strike Log", callback_data="adm_strike_log")
    builder.button(text="🔙 Back to Dashboard", callback_data="admin_dashboard")
    builder.adjust(1, 2, 1)
    return builder.as_markup()


def get_user_actions_keyboard(user: User) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Credit Balance", callback_data=f"adm_credit_user_{user.id}")
    builder.button(text="➖ Debit Balance",  callback_data=f"adm_debit_user_{user.id}")
    blk = "🟢 Unban User" if user.is_blocked else "🚫 Ban User"
    builder.button(text=blk, callback_data=f"adm_toggle_block_{user.id}")
    builder.button(text="⚡ Strikes",        callback_data=f"adm_user_strikes_{user.id}")
    builder.button(text="📦 Orders",         callback_data=f"adm_user_orders_{user.id}")
    builder.button(text="💳 Deposits",       callback_data=f"adm_user_deposits_{user.id}")
    builder.button(text="🔙 Back",          callback_data="admin_users_menu")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()
