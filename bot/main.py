"""Main application entry point — RYUS MARKET Phone Number Marketplace Bot."""

import asyncio
import signal
import sys
import traceback
from datetime import datetime, timezone
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

from bot.config import config
from bot.database.database import init_database, close_db
from bot.middlewares.throttling import ThrottlingMiddleware
from bot.middlewares.auth import AuthMiddleware
from bot.utils.logger import logger

# ─── User Handlers ────────────────────────────────────────────────────────────
from bot.handlers import start, products, purchases, wallet
from bot.handlers import deposits as user_deposits
from bot.handlers import history

# ─── Admin Handlers ───────────────────────────────────────────────────────────
from bot.admin import dashboard, inventory, orders
from bot.admin import deposits as admin_deposits
from bot.admin import users


# ─── AIOHTTP HEALTH CHECK SERVER (Render / UptimeRobot) ────────────────────────

async def health_check_handler(request: web.Request) -> web.Response:
    """Lightweight /health endpoint for UptimeRobot / Render web ping."""
    return web.json_response({
        "status": "ok",
        "service": "RYUS MARKET Telegram Bot",
        "timestamp": datetime.now(timezone.utc).isoformat()
    })


async def start_web_server(port: int) -> web.AppRunner:
    """Start lightweight aiohttp HTTP server on 0.0.0.0:$PORT."""
    app = web.Application()
    app.router.add_get("/", health_check_handler)
    app.router.add_get("/health", health_check_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info(f"Health check web server running on port {port} (endpoints: / and /health)")
    return runner


# ─── BACKGROUND CLEANUP TASK (Unpaid Order Expiration) ────────────────────────

async def unpaid_orders_cleaner_loop(bot: Bot, stop_event: asyncio.Event) -> None:
    """Background task to detect expired unpaid orders and record strikes."""
    from bot.services.anti_abuse import expire_unpaid_orders_check
    logger.info("Unpaid orders expiration monitor started.")
    while not stop_event.is_set():
        try:
            await expire_unpaid_orders_check(bot=bot)
        except Exception as e:
            logger.error(f"Error in unpaid_orders_cleaner_loop: {e}")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60.0)
        except asyncio.TimeoutError:
            pass


# ─── BOT LIFECYCLE ────────────────────────────────────────────────────────────

async def on_startup(bot: Bot) -> None:
    logger.info("Initializing RYUS MARKET Bot...")
    await init_database()
    me = await bot.get_me()
    logger.info(f"Bot connected: @{me.username} (ID: {me.id})")
    logger.info(f"Admin IDs: {config.ADMIN_IDS}")
    logger.info(f"UPI: {config.UPI_ID} | Min Deposit: Rs.{config.MIN_DEPOSIT_INR}")
    logger.info("Bot is ready and accepting messages.")


async def on_shutdown(bot: Bot) -> None:
    logger.info("Bot shutting down...")
    await bot.session.close()
    await close_db()


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    # Global error handler — catches ALL unhandled exceptions from handlers
    @dp.errors()
    async def global_error_handler(event: ErrorEvent) -> bool:
        logger.error(
            f"UNHANDLED EXCEPTION in handler:\n"
            f"  Update: {event.update}\n"
            f"  Error: {event.exception}\n"
            f"{traceback.format_exc()}"
        )
        return True

    # Middlewares (Anti-abuse & Throttling)
    dp.message.outer_middleware(ThrottlingMiddleware())
    dp.callback_query.outer_middleware(ThrottlingMiddleware())
    dp.message.middleware(AuthMiddleware())
    dp.callback_query.middleware(AuthMiddleware())

    # Start / main menu router FIRST so /start always executes
    dp.include_router(start.router)

    # Admin routers (IsAdmin filter; unmatched fall through to user routers)
    dp.include_router(dashboard.router)
    dp.include_router(inventory.router)
    dp.include_router(orders.router)
    dp.include_router(admin_deposits.router)
    dp.include_router(users.router)

    # Customer routers
    dp.include_router(products.router)
    dp.include_router(purchases.router)
    dp.include_router(wallet.router)
    dp.include_router(user_deposits.router)
    dp.include_router(history.router)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    return dp


async def main() -> None:
    if not config.BOT_TOKEN or config.BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("\n" + "=" * 60)
        print("ERROR: BOT_TOKEN is not set in .env!")
        print("=" * 60 + "\n")
        sys.exit(1)

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = create_dispatcher()

    stop_event = asyncio.Event()

    # Graceful shutdown handler for SIGTERM (Render container stop) and SIGINT
    loop = asyncio.get_running_loop()
    def _sig_handler(sig_name: str):
        logger.info(f"Received signal {sig_name}. Initiating graceful shutdown...")
        stop_event.set()
        asyncio.create_task(dp.stop_polling())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda s=sig.name: _sig_handler(s))
        except NotImplementedError:
            # Not supported on Windows signal loop
            pass

    # Start aiohttp health check web server alongside bot polling
    web_runner = await start_web_server(config.PORT)

    # Start background cleaner task
    cleaner_task = asyncio.create_task(unpaid_orders_cleaner_loop(bot, stop_event))

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        logger.info("Starting polling...")
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=False
        )
    finally:
        logger.info("Cleaning up running services...")
        stop_event.set()
        cleaner_task.cancel()
        try:
            await cleaner_task
        except asyncio.CancelledError:
            pass

        await web_runner.cleanup()
        await bot.session.close()
        await close_db()
        logger.info("Shutdown completed cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.error(f"Fatal error: {e}\n{traceback.format_exc()}")
        sys.exit(1)
