"""Authentication, registration, and user-blocking check middleware."""

import traceback
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from bot.config import config
from bot.database.queries import get_or_create_user
from bot.utils.logger import logger


class AuthMiddleware(BaseMiddleware):
    @staticmethod
    def _is_payment_feature(event: TelegramObject) -> bool:
        """Check if an incoming event targets payment, deposit, or purchase features."""
        if isinstance(event, CallbackQuery):
            data = event.data or ""
            payment_prefixes = (
                "start_deposit", "submit_deposit", "skip_screenshot", "cancel_deposit",
                "buy_country_", "confirm_buy_", "fetch_otp_", "confirm_logout_", "do_logout_bot_",
                "deposit", "wallet", "pay"
            )
            return any(data.startswith(prefix) for prefix in payment_prefixes)

        if isinstance(event, Message):
            text = (event.text or "").strip()
            payment_triggers = ("💳 Deposit", "💰 Wallet", "/deposit", "/wallet", "/pay")
            if any(text.startswith(trigger) for trigger in payment_triggers):
                return True

        return False

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        tg_user = None
        if isinstance(event, Message) and event.from_user:
            tg_user = event.from_user
        elif isinstance(event, CallbackQuery) and event.from_user:
            tg_user = event.from_user

        if tg_user and not tg_user.is_bot:
            try:
                db_user = await get_or_create_user(
                    telegram_id=tg_user.id,
                    username=tg_user.username,
                    first_name=tg_user.first_name
                )
                data["db_user"] = db_user

                # Block check (admins bypass)
                if db_user.is_blocked and not config.is_admin(tg_user.id):
                    # Rule 11: Banned users get NO response from payment features
                    if self._is_payment_feature(event):
                        if isinstance(event, CallbackQuery):
                            try:
                                await event.answer()
                            except Exception:
                                pass
                        return None  # Silently drop with zero response

                    # General commands: inform about account suspension
                    if isinstance(event, CallbackQuery):
                        await event.answer("Your account is restricted.", show_alert=True)
                    elif isinstance(event, Message):
                        await event.answer(
                            "⛔ <b>Your account has been suspended.</b>\n"
                            "Contact support if this is an error.",
                            parse_mode="HTML"
                        )
                    return None

            except Exception as e:
                logger.error(f"AuthMiddleware error for {tg_user.id}: {e}\n{traceback.format_exc()}")

        try:
            return await handler(event, data)
        except Exception as e:
            logger.error(
                f"Handler error [{type(event).__name__}]: {e}\n{traceback.format_exc()}"
            )
            # Gracefully notify user
            try:
                if isinstance(event, CallbackQuery):
                    await event.answer("⚠️ An error occurred. Please try again.", show_alert=True)
                elif isinstance(event, Message):
                    await event.answer("⚠️ An error occurred. Please try again.")
            except Exception:
                pass
