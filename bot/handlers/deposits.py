"""Deposit handler (UPI, FSM, anti-abuse checks, single pending order enforcement)."""

from typing import Union
from datetime import datetime, timedelta, timezone
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from bot.config import config
from bot.database.models import User
from bot.database.queries import (
    create_deposit_request, DuplicateUtrError
)
from bot.keyboards.user_kb import get_deposit_entry_keyboard, get_skip_screenshot_keyboard
from bot.keyboards.admin_kb import get_deposit_decision_keyboard
from bot.services.qr_service import QRService
from bot.services.anti_abuse import (
    get_user_strike_status, get_user_pending_order, add_strike
)
from bot.utils.states import DepositStates
from bot.utils.formatters import escape, fmt, format_deposit_card
from bot.utils.logger import logger

router = Router(name="deposits_router")


@router.message(F.text == "💳 Deposit")
@router.callback_query(F.data == "start_deposit")
async def handle_deposit_entry(event: Union[Message, CallbackQuery], state: FSMContext, db_user: User, bot: Bot):
    await state.clear()

    # 1. Anti-abuse strike & cooldown check
    status = await get_user_strike_status(db_user.id)
    if status["is_banned"]:
        if isinstance(event, CallbackQuery):
            await event.answer("Your account is restricted.", show_alert=True)
        return

    if status["in_cooldown"]:
        cooldown_msg = (
            f"⏳ <b>ACCOUNT UNDER COOLDOWN</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"You received a strike: <i>{escape(status['latest_strike_reason'])}</i>\n\n"
            f"Active Strikes: <b>{status['active_strikes_count']}/3</b>\n"
            f"Cooldown Remaining: <b>{status['cooldown_formatted']}</b>\n\n"
            f"⚠️ <i>Please wait until your cooldown expires before depositing.</i>"
        )
        if isinstance(event, CallbackQuery):
            await event.message.answer(cooldown_msg, parse_mode="HTML")
            await event.answer()
        else:
            await event.answer(cooldown_msg, parse_mode="HTML")
        return

    # 2. Rule 7: One pending order per user. If one exists, show it instead of creating a new one.
    pending_dep = await get_user_pending_order(db_user.id, bot=bot)
    if pending_dep:
        pending_text = (
            f"⚠️ <b>YOU ALREADY HAVE A PENDING ORDER</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{format_deposit_card(pending_dep)}\n\n"
            f"📌 <i>You can only have one pending payment claim at a time. "
            f"Please wait for an administrator to verify this payment before creating a new one.</i>"
        )
        if isinstance(event, CallbackQuery):
            await event.message.answer(pending_text, parse_mode="HTML")
            await event.answer()
        else:
            await event.answer(pending_text, parse_mode="HTML")
        return

    caption = (
        f"💳 <b>DEPOSIT FUNDS — UPI PAYMENT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Send money via any UPI app (GPay / PhonePe / Paytm / BHIM):\n\n"
        f"🔹 <b>UPI ID:</b> <code>{config.UPI_ID}</code>\n"
        f"🔹 <b>Payee:</b> <code>{escape(config.UPI_PAYEE_NAME)}</code>\n"
        f"🔹 <b>Minimum Deposit:</b> <code>{fmt(config.MIN_DEPOSIT_INR)}</code>\n\n"
        f"📌 <b>Steps:</b>\n"
        f"1. Scan QR or copy the UPI ID above.\n"
        f"2. Complete payment in your UPI app.\n"
        f"3. Note the <b>UTR / Reference Number</b>.\n"
        f"4. Tap <b>Submit UTR / Payment Proof</b> below.\n\n"
        f"⚠️ <i>Deposits are manually verified by admin. Funds are credited instantly on approval.</i>"
    )
    qr = QRService.generate_upi_qr()
    photo = BufferedInputFile(qr.read(), filename="upi_qr.png")

    if isinstance(event, CallbackQuery):
        await event.message.answer_photo(photo=photo, caption=caption, parse_mode="HTML",
                                         reply_markup=get_deposit_entry_keyboard())
        await event.answer()
    else:
        await event.answer_photo(photo=photo, caption=caption, parse_mode="HTML",
                                 reply_markup=get_deposit_entry_keyboard())


@router.callback_query(F.data == "submit_deposit")
async def start_deposit_fsm(callback: CallbackQuery, state: FSMContext, db_user: User, bot: Bot):
    # Cooldown & pending order verification before entering FSM
    status = await get_user_strike_status(db_user.id)
    if status["in_cooldown"]:
        await callback.answer(f"In cooldown: {status['cooldown_formatted']} remaining.", show_alert=True)
        return

    pending_dep = await get_user_pending_order(db_user.id, bot=bot)
    if pending_dep:
        await callback.answer("You already have a pending deposit awaiting verification.", show_alert=True)
        return

    await state.set_state(DepositStates.waiting_for_amount)
    await callback.message.answer(
        f"💰 <b>Step 1/3 — Enter Amount</b>\n\n"
        f"Type the exact amount you paid in INR "
        f"(minimum <code>{fmt(config.MIN_DEPOSIT_INR)}</code>):",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(DepositStates.waiting_for_amount)
async def process_amount(message: Message, state: FSMContext):
    txt = message.text.strip().replace("₹", "").replace(",", "")
    try:
        amount = float(txt)
        if amount < config.MIN_DEPOSIT_INR:
            await message.answer(
                f"⚠️ Minimum deposit is <code>{fmt(config.MIN_DEPOSIT_INR)}</code>. Please re-enter:",
                parse_mode="HTML"
            )
            return
    except ValueError:
        await message.answer("⚠️ Enter a valid number (e.g. 100):")
        return

    await state.update_data(amount=amount)
    await state.set_state(DepositStates.waiting_for_utr)
    await message.answer(
        f"🔢 <b>Step 2/3 — UTR / Reference Number</b>\n\n"
        f"Amount: <code>{fmt(amount)}</code>\n\n"
        f"Enter the UTR / Transaction Reference from your payment receipt "
        f"(found in GPay/PhonePe payment details):",
        parse_mode="HTML"
    )


@router.message(DepositStates.waiting_for_utr)
async def process_utr(message: Message, state: FSMContext, db_user: User, bot: Bot):
    utr = message.text.strip().upper()

    # Rule 8: Strike when UTR is invalid
    if len(utr) < 6 or not utr.isalnum():
        active_cnt, was_banned, cd = await add_strike(
            user_id=db_user.id,
            telegram_id=message.from_user.id,
            reason=f"Invalid UTR submitted: '{utr}'",
            bot=bot
        )
        if was_banned:
            await state.clear()
            await message.answer(
                "⛔ <b>Account Suspended</b>\n"
                "You reached 3 strikes and your account has been automatically banned.",
                parse_mode="HTML"
            )
            return

        await message.answer(
            f"⚠️ <b>Invalid UTR Format!</b>\n\n"
            f"A strike has been added to your account (Active Strikes: <b>{active_cnt}/3</b>).\n"
            f"Please enter a valid alphanumeric UTR (at least 6 characters):",
            parse_mode="HTML"
        )
        return

    await state.update_data(utr=utr)
    await state.set_state(DepositStates.waiting_for_screenshot)
    data = await state.get_data()
    await message.answer(
        f"📸 <b>Step 3/3 — Payment Screenshot (Optional)</b>\n\n"
        f"Amount: <code>{fmt(data['amount'])}</code>\n"
        f"UTR: <code>{escape(utr)}</code>\n\n"
        f"Send a screenshot of your payment, or tap <b>Skip Screenshot</b>:",
        parse_mode="HTML",
        reply_markup=get_skip_screenshot_keyboard()
    )


@router.callback_query(F.data == "skip_screenshot", DepositStates.waiting_for_screenshot)
async def skip_screenshot(callback: CallbackQuery, state: FSMContext, db_user: User, bot: Bot):
    data = await state.get_data()
    await state.clear()
    await _finalize_deposit(callback, db_user, data["amount"], data["utr"], None, bot)


@router.message(DepositStates.waiting_for_screenshot, F.photo)
async def capture_screenshot(message: Message, state: FSMContext, db_user: User, bot: Bot):
    data = await state.get_data()
    await state.clear()
    photo_id = message.photo[-1].file_id
    await _finalize_deposit(message, db_user, data["amount"], data["utr"], photo_id, bot)


async def _finalize_deposit(
    event, user: User, amount: float, utr: str,
    screenshot_file_id, bot: Bot
):
    try:
        # Unpaid order expiration calculation
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=config.ORDER_EXPIRY_MINUTES)
        deposit = await create_deposit_request(
            user_id=user.id, amount=amount, utr=utr,
            screenshot_file_id=screenshot_file_id,
            expires_at=expires_at
        )
        confirm_text = (
            f"✅ <b>Deposit Submitted!</b>\n\n"
            f"💳 <b>Deposit ID:</b> <code>{escape(deposit.deposit_code)}</code>\n"
            f"💰 <b>Amount:</b> <code>{fmt(deposit.amount)}</code>\n"
            f"🔢 <b>UTR:</b> <code>{escape(deposit.utr)}</code>\n"
            f"📊 <b>Status:</b> ⏳ Pending Admin Verification\n\n"
            f"<i>You will be notified instantly once funds are credited.</i>"
        )
        if isinstance(event, CallbackQuery):
            await event.message.answer(confirm_text, parse_mode="HTML")
            await event.answer()
        else:
            await event.answer(confirm_text, parse_mode="HTML")

        # Alert all admins
        alert = (
            f"🚨 <b>NEW DEPOSIT REQUEST</b>\n\n"
            f"{format_deposit_card(deposit)}\n\n"
            f"⚠️ <i>Verify in UPI app before approving!</i>"
        )
        kb = get_deposit_decision_keyboard(deposit.id)
        for admin_id in config.ADMIN_IDS:
            try:
                if screenshot_file_id:
                    await bot.send_photo(chat_id=admin_id, photo=screenshot_file_id,
                                         caption=alert, parse_mode="HTML", reply_markup=kb)
                else:
                    await bot.send_message(chat_id=admin_id, text=alert,
                                           parse_mode="HTML", reply_markup=kb)
            except Exception as e:
                logger.warning(f"Cannot alert admin {admin_id}: {e}")

    except DuplicateUtrError as e:
        # Rule 8: Strike when UTR is already used
        tg_id = event.from_user.id
        active_cnt, was_banned, cd = await add_strike(
            user_id=user.id,
            telegram_id=tg_id,
            reason=f"Duplicate UTR already used: '{utr}'",
            bot=bot
        )
        if was_banned:
            msg = "⛔ <b>Account Suspended</b>\nYou reached 3 strikes and have been automatically banned."
        else:
            msg = (
                f"⚠️ <b>Duplicate UTR Error!</b>\n\n"
                f"This UTR (<code>{escape(utr)}</code>) was already submitted previously.\n"
                f"⚠️ <i>A strike has been added to your account (Active Strikes: <b>{active_cnt}/3</b>).</i>"
            )

        if isinstance(event, CallbackQuery):
            await event.message.answer(msg, parse_mode="HTML")
            await event.answer()
        else:
            await event.answer(msg, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Deposit finalize error: {e}", exc_info=True)
        err = "⚠️ An error occurred. Please try again or contact support."
        if isinstance(event, CallbackQuery):
            await event.message.answer(err)
            await event.answer()
        else:
            await event.answer(err)


@router.callback_query(F.data == "cancel_deposit")
async def cancel_deposit(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Deposit cancelled.")
    await callback.answer()
