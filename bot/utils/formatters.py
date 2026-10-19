"""Formatters for phone number marketplace messages."""

import html
from bot.config import config
from bot.database.models import Order, Deposit, User, Country, DashboardStats


def escape(text) -> str:
    return html.escape(str(text)) if text else ""


def fmt(amount: float) -> str:
    return f"{config.CURRENCY_SYMBOL}{amount:,.2f}"


def format_order_card(order: Order, show_sensitive: bool = True) -> str:
    status_label = {
        "completed": "✅ Completed",
        "refunded": "🔄 Refunded",
        "cancelled": "❌ Cancelled"
    }.get(order.status, order.status.title())

    lines = [
        f"🧾 <b>ORDER #{escape(order.order_code)}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"🌍 <b>Country:</b> {escape(order.country_flag)} {escape(order.country_name)}",
        f"💰 <b>Amount Paid:</b> <code>{fmt(order.price)}</code>",
        f"📅 <b>Purchased:</b> <code>{escape(order.created_at)}</code>",
        f"📊 <b>Status:</b> {status_label}",
    ]
    if show_sensitive:
        lines += [
            "━━━━━━━━━━━━━━━━━━━━━━",
            "📱 <b>YOUR ACCOUNT DETAILS:</b>",
            f"📞 <b>Phone Number:</b> <code>{escape(order.phone_number)}</code>",
        ]
        if order.two_fa_password:
            lines.append(
                f"🔐 <b>2FA Password:</b> <code>{escape(order.two_fa_password)}</code>"
            )
        if order.additional_notes:
            lines.append(
                f"📝 <b>Notes / Instructions:</b>\n<pre>{escape(order.additional_notes)}</pre>"
            )
        lines.append("\n⚠️ <i>Keep these details private and secure.</i>")
    return "\n".join(lines)


def format_deposit_card(deposit: Deposit) -> str:
    status_label = {
        "pending": "⏳ Pending",
        "approved": "✅ Approved",
        "rejected": "❌ Rejected"
    }.get(deposit.status, deposit.status.title())

    user_info = (
        f"@{escape(deposit.user_username)}"
        if deposit.user_username
        else f"User {deposit.user_telegram_id}"
    )
    lines = [
        f"💳 <b>DEPOSIT #{escape(deposit.deposit_code)}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"👤 <b>User:</b> {user_info} (<code>{deposit.user_telegram_id}</code>)",
        f"💰 <b>Amount:</b> <code>{fmt(deposit.amount)}</code>",
        f"🔢 <b>UTR/Ref:</b> <code>{escape(deposit.utr)}</code>",
        f"📊 <b>Status:</b> {status_label}",
        f"📅 <b>Submitted:</b> <code>{escape(deposit.created_at)}</code>",
    ]
    if deposit.admin_notes:
        lines.append(f"📝 <b>Note:</b> {escape(deposit.admin_notes)}")
    if deposit.reviewed_at:
        lines.append(f"⏱ <b>Reviewed:</b> <code>{escape(deposit.reviewed_at)}</code>")
    return "\n".join(lines)


def format_user_card(user: User, total_orders: int = 0, total_spent: float = 0.0) -> str:
    status = "🚫 <b>Blocked</b>" if user.is_blocked else "🟢 <b>Active</b>"
    uname = f"@{escape(user.username)}" if user.username else "<i>None</i>"
    lines = [
        f"👤 <b>USER: {escape(user.internal_id)}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"🆔 <b>Internal ID:</b> <code>{escape(user.internal_id)}</code>",
        f"💬 <b>Telegram ID:</b> <code>{user.telegram_id}</code>",
        f"🏷 <b>Username:</b> {uname}",
        f"👤 <b>Name:</b> {escape(user.first_name or 'N/A')}",
        f"💰 <b>Wallet:</b> <code>{fmt(user.wallet_balance)}</code>",
        f"🔒 <b>Status:</b> {status}",
        f"📅 <b>Joined:</b> <code>{escape(user.created_at)}</code>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📦 <b>Completed Orders:</b> {total_orders}",
        f"💸 <b>Total Spent:</b> {fmt(total_spent)}",
    ]
    return "\n".join(lines)


def format_dashboard_card(stats: DashboardStats) -> str:
    lines = [
        "📊 <b>RYUS MARKET — ADMIN DASHBOARD</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"👥 <b>Total Users:</b> <code>{stats.total_users:,}</code>",
        f"📦 <b>Total Orders:</b> <code>{stats.total_orders:,}</code>",
        f"💰 <b>Total Revenue:</b> <code>{fmt(stats.total_revenue)}</code>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"⏳ <b>Pending Deposits:</b> <code>{stats.pending_deposits_count}</code>"
        f" (<code>{fmt(stats.pending_deposits_amount)}</code>)",
        f"🟢 <b>Numbers Available:</b> <code>{stats.available_numbers_count:,}</code>",
        f"🔴 <b>Numbers Sold:</b> <code>{stats.sold_numbers_count:,}</code>",
    ]
    if stats.country_breakdown:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("🌍 <b>STOCK BY COUNTRY:</b>")
        for cname, cflag, avail, sold in stats.country_breakdown:
            lines.append(
                f"  {escape(cflag)} <b>{escape(cname)}:</b> "
                f"<code>{avail}</code> avail / <code>{sold}</code> sold"
            )
    return "\n".join(lines)
