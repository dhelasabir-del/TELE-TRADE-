"""
Throttling / Anti-spam middleware to protect bot from flood attacks.
Enforces: Max 5 presses per 10 seconds per user (extra presses ignored silently).
"""

import time
from typing import Any, Awaitable, Callable, Dict, List
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery
from bot.config import config


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, limit: float = config.RATE_LIMIT_DELAY, window_seconds: float = 10.0, max_presses: int = 5):
        super().__init__()
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_presses = max_presses
        self.user_windows: Dict[int, List[float]] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user_id = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id and not config.is_admin(user_id):
            now = time.monotonic()

            # Clean up timestamps older than window_seconds (10 seconds)
            recent_presses = [
                t for t in self.user_windows.get(user_id, [])
                if now - t < self.window_seconds
            ]

            # Rule 10: Max 5 presses per 10 seconds per user; extra presses ignored silently
            if len(recent_presses) >= self.max_presses:
                self.user_windows[user_id] = recent_presses
                if isinstance(event, CallbackQuery):
                    try:
                        await event.answer()
                    except Exception:
                        pass
                return None  # Silently drop

            recent_presses.append(now)
            self.user_windows[user_id] = recent_presses

        return await handler(event, data)
