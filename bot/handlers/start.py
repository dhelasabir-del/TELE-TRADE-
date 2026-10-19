"""Start handler — /start and main menu."""

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from bot.config import config
from bot.database.models import User
from bot.keyboards.user_kb import get_main_menu_keyboard
from bot.utils.formatters import escape, fmt

router = Router(name="start_router")


@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext, db_user: User):
    await state.clear()
    is_admin = config.is_admin(message.from_user.id)
    text = (
        f"✨ ━━━━━━━━━━━━━━━━━━━━━━ ✨\n"
        f"  🌟 <b>WELCOME TO TELETRADE !</b> 🌟\n"
        f"✨ ━━━━━━━━━━━━━━━━━━━━━━ ✨\n\n"
        f"🚀 <i>The premier marketplace for verified Telegram accounts & international numbers.</i>\n\n"
        f"👤 <b>ACCOUNT OVERVIEW</b>\n"
        f" ├ 🆔 <b>Account ID:</b> <code>{escape(db_user.internal_id)}</code>\n"
        f" └ 💰 <b>Wallet Balance:</b> <code>{fmt(db_user.wallet_balance)}</code>\n\n"
        f"⚡ <b>WHY CHOOSE TELETRADE?</b>\n"
        f" • 🌐 <b>Global Selection:</b> High quality verified numbers\n"
        f" • ⚡ <b>Instant Delivery:</b> Phone & 2FA delivered in seconds\n"
        f" • 🔑 <b>On-Demand OTP:</b> Fetch login codes when ready\n"
        f" • 🛡️ <b>100% Privacy:</b> One-click bot session logout\n\n"
        f"👇 <i>Select an option below to get started:</i>"
    )
    await message.answer(text, parse_mode="HTML",
                         reply_markup=get_main_menu_keyboard(is_admin=is_admin))


@router.callback_query(F.data == "close_view")
async def close_view(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()
