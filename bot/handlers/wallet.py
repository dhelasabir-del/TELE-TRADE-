"""Wallet and transaction history."""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from bot.database.models import User
from bot.database.queries import get_user_transactions
from bot.keyboards.user_kb import get_wallet_keyboard
from bot.utils.formatters import escape, fmt

router = Router(name="wallet_router")


@router.message(F.text == "💰 Wallet")
async def handle_wallet(message: Message, db_user: User):
    await message.answer(_wallet_text(db_user), parse_mode="HTML",
                         reply_markup=get_wallet_keyboard())


@router.callback_query(F.data == "back_to_wallet")
async def back_to_wallet(callback: CallbackQuery, db_user: User):
    await callback.message.edit_text(
        _wallet_text(db_user), parse_mode="HTML", reply_markup=get_wallet_keyboard()
    )
    await callback.answer()


def _wallet_text(user: User) -> str:
    return (
        f"💼 <b>YOUR WALLET</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>Account ID:</b> <code>{escape(user.internal_id)}</code>\n"
        f"💬 <b>Telegram ID:</b> <code>{user.telegram_id}</code>\n"
        f"💰 <b>Balance:</b> <code>{fmt(user.wallet_balance)}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Use your balance to purchase phone numbers instantly."
    )


@router.callback_query(F.data == "wallet_tx")
async def handle_wallet_tx(callback: CallbackQuery, db_user: User):
    txs = await get_user_transactions(db_user.id, limit=10)
    if not txs:
        await callback.message.edit_text(
            "📜 <b>No transactions yet.</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Deposit", callback_data="start_deposit")],
                [InlineKeyboardButton(text="🔙 Back", callback_data="back_to_wallet")]
            ])
        )
        await callback.answer()
        return

    type_emojis = {
        "deposit": "💳", "purchase": "🛍️",
        "refund": "🔄", "admin_credit": "➕", "admin_debit": "➖"
    }
    lines = ["📜 <b>TRANSACTION HISTORY</b>\n━━━━━━━━━━━━━━━━━━━━━━"]
    for tx in txs:
        sign = "+" if tx.type in ("deposit", "refund", "admin_credit") else "-"
        icon = type_emojis.get(tx.type, "•")
        lines.append(
            f"{icon} {tx.type.replace('_',' ').title()}: <code>{sign}{fmt(tx.amount)}</code>\n"
            f"  Bal: <code>{fmt(tx.balance_before)} → {fmt(tx.balance_after)}</code>\n"
            f"  <i>{escape(tx.created_at[:16])}</i>\n"
        )
    lines.append(f"\n💰 <b>Current Balance:</b> <code>{fmt(db_user.wallet_balance)}</code>")

    await callback.message.edit_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Deposit", callback_data="start_deposit")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="back_to_wallet")]
        ])
    )
    await callback.answer()
