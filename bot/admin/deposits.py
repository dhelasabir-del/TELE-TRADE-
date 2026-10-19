"""Admin deposit review, approval, and rejection."""

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from bot.admin.dashboard import IsAdmin
from bot.database.queries import (
    get_pending_deposits, get_deposit_by_id,
    approve_deposit, reject_deposit, MarketplaceError
)
from bot.keyboards.admin_kb import get_deposits_list_keyboard, get_deposit_decision_keyboard
from bot.utils.states import RejectDepositStates
from bot.utils.formatters import escape, fmt, format_deposit_card
from bot.utils.logger import logger

router = Router(name="admin_deposits_router")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.callback_query(F.data == "admin_deposits_menu")
async def show_pending_deposits(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    deposits = await get_pending_deposits(limit=20)
    if not deposits:
        await callback.message.edit_text(
            "💳 <b>PENDING DEPOSITS</b>\n\n✨ All clear — no pending deposits.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="admin_dashboard")]
            ])
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        f"💳 <b>PENDING DEPOSITS ({len(deposits)})</b>\n\n"
        "Select a deposit to review:",
        parse_mode="HTML",
        reply_markup=get_deposits_list_keyboard(deposits)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_view_dep_"))
async def view_deposit(callback: CallbackQuery, bot: Bot):
    dep_id = int(callback.data.split("_")[3])
    deposit = await get_deposit_by_id(dep_id)
    if not deposit:
        await callback.answer("Deposit not found.", show_alert=True)
        return

    card = format_deposit_card(deposit)
    note = "\n\n⚠️ <i>Verify payment received in your UPI app before approving!</i>"
    kb = get_deposit_decision_keyboard(deposit.id)

    if deposit.screenshot_file_id:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await bot.send_photo(
            chat_id=callback.from_user.id,
            photo=deposit.screenshot_file_id,
            caption=f"{card}{note}",
            parse_mode="HTML",
            reply_markup=kb
        )
    else:
        await callback.message.edit_text(
            f"{card}{note}",
            parse_mode="HTML",
            reply_markup=kb
        )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_approve_dep_"))
async def approve_dep(callback: CallbackQuery, bot: Bot):
    dep_id = int(callback.data.split("_")[3])
    try:
        deposit = await approve_deposit(
            dep_id=dep_id,
            admin_telegram_id=callback.from_user.id,
            notes=f"Approved by Admin {callback.from_user.id}"
        )
        # Rule 12: Verified payment removes one strike
        from bot.services.anti_abuse import remove_strike_for_verified_payment, add_strike
        strike_removed = await remove_strike_for_verified_payment(deposit.user_id)
        if strike_removed:
            logger.info(f"Strike removed for user {deposit.user_id} following approved deposit {deposit.deposit_code}.")

        await callback.answer("✅ Deposit APPROVED and credited!", show_alert=True)

        # Update admin message
        updated_card = format_deposit_card(deposit)
        back_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back to Pending", callback_data="admin_deposits_menu")]
        ])
        try:
            await callback.message.edit_caption(
                caption=f"✅ <b>APPROVED</b>\n\n{updated_card}",
                parse_mode="HTML", reply_markup=back_kb
            )
        except Exception:
            try:
                await callback.message.edit_text(
                    f"✅ <b>APPROVED</b>\n\n{updated_card}",
                    parse_mode="HTML", reply_markup=back_kb
                )
            except Exception:
                pass

        # Notify buyer
        try:
            strike_note = "\n✨ <i>One active strike has been removed for verified payment!</i>" if strike_removed else ""
            await bot.send_message(
                chat_id=deposit.user_telegram_id,
                text=(
                    f"✅ <b>DEPOSIT APPROVED!</b>\n\n"
                    f"Your deposit of <code>{fmt(deposit.amount)}</code> has been credited to your wallet.\n\n"
                    f"💳 <b>Deposit ID:</b> <code>{escape(deposit.deposit_code)}</code>\n"
                    f"🔢 <b>UTR:</b> <code>{escape(deposit.utr)}</code>\n"
                    f"{strike_note}\n\n"
                    f"You can now purchase numbers from the marketplace!"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Could not notify buyer {deposit.user_telegram_id}: {e}")

    except MarketplaceError as e:
        await callback.answer(str(e), show_alert=True)
    except Exception as e:
        logger.error(f"Approve deposit error: {e}", exc_info=True)
        await callback.answer("Error approving deposit.", show_alert=True)


@router.callback_query(F.data.startswith("adm_reject_dep_"))
async def start_reject_dep(callback: CallbackQuery, state: FSMContext):
    dep_id = int(callback.data.split("_")[3])
    await state.update_data(deposit_id=dep_id)
    await state.set_state(RejectDepositStates.waiting_for_reason)
    await callback.message.answer(
        f"❌ <b>Reject Deposit #{dep_id}</b>\n\n"
        "Enter the rejection reason (e.g. <i>Payment not received</i>, <i>Invalid UTR</i>):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data="admin_deposits_menu")]
        ])
    )
    await callback.answer()


@router.message(RejectDepositStates.waiting_for_reason)
async def process_reject_reason(message: Message, state: FSMContext, bot: Bot):
    reason = message.text.strip()
    data = await state.get_data()
    dep_id = data["deposit_id"]
    await state.clear()

    try:
        deposit = await reject_deposit(
            dep_id=dep_id,
            admin_telegram_id=message.from_user.id,
            reason=reason
        )
        # Rule 8: Add strike when admin rejects a claim
        from bot.services.anti_abuse import add_strike
        active_cnt, was_banned, cd = await add_strike(
            user_id=deposit.user_id,
            telegram_id=deposit.user_telegram_id,
            reason=f"Deposit claim rejected: {reason}",
            bot=bot
        )

        await message.answer(
            f"❌ <b>Deposit #{escape(deposit.deposit_code)} Rejected.</b>\n"
            f"Reason: <i>{escape(reason)}</i>\n"
            f"⚠️ Strike issued to user (Active: <b>{active_cnt}/3</b>)",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Back to Pending", callback_data="admin_deposits_menu")]
            ])
        )
        # Notify buyer
        try:
            ban_warning = (
                "\n⛔ <i>Your account has been suspended for reaching 3 strikes.</i>"
                if was_banned else
                f"\n⚠️ <i>A strike was added to your account (Active Strikes: {active_cnt}/3).</i>"
            )
            await bot.send_message(
                chat_id=deposit.user_telegram_id,
                text=(
                    f"❌ <b>DEPOSIT REJECTED</b>\n\n"
                    f"Your deposit of <code>{fmt(deposit.amount)}</code> was rejected.\n\n"
                    f"💳 <b>Deposit ID:</b> <code>{escape(deposit.deposit_code)}</code>\n"
                    f"🔢 <b>UTR:</b> <code>{escape(deposit.utr)}</code>\n"
                    f"📝 <b>Reason:</b> {escape(reason)}\n"
                    f"{ban_warning}\n\n"
                    f"Contact support if you believe this is an error."
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Could not notify buyer {deposit.user_telegram_id}: {e}")

    except MarketplaceError as e:
        await message.answer(f"⚠️ {escape(str(e))}", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Reject deposit error: {e}", exc_info=True)
        await message.answer("⚠️ Error rejecting deposit.")
