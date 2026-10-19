"""Optional helper script to seed demo categories, products, and authorized stock for immediate testing."""

import asyncio
import sys
from bot.database.database import init_database
from bot.database.queries import (
    create_category, create_product, add_inventory_items,
    get_all_categories
)
from bot.utils.logger import logger

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass



async def seed_data():
    logger.info("Initializing database schema...")
    await init_database()

    existing_cats = await get_all_categories()
    if existing_cats:
        print(f"Database already contains {len(existing_cats)} categories. Skipping demo seed.")
        return

    print("Seeding demo marketplace data...")

    # 1. Categories
    cat_vpn = await create_category(
        name="VPN & Security",
        description="High-speed private VPN licenses and internet security tools.",
        icon="🛡️"
    )
    cat_gaming = await create_category(
        name="Gaming & Entertainment",
        description="Legitimate gaming gift cards, wallet codes, and subscriptions.",
        icon="🎮"
    )
    cat_dev = await create_category(
        name="Developer & Cloud",
        description="Cloud vouchers, API credits, and authorized developer subscriptions.",
        icon="⚡"
    )

    # 2. Products
    p1 = await create_product(
        name="NordVPN Premium (30-Day License)",
        category_id=cat_vpn.id,
        price=199.0,
        country_region="Global 🌐",
        description="Official 30-day NordVPN activation key. Ultra-fast speeds and strict no-logs policy."
    )
    await add_inventory_items(
        product_id=p1.id,
        items=[
            "NORD-ACT-2026-X89J-91FA-001\nInstructions: Redeem at https://my.nordaccount.com/activate",
            "NORD-ACT-2026-B44T-62PQ-002\nInstructions: Redeem at https://my.nordaccount.com/activate",
            "NORD-ACT-2026-C19L-38ZZ-003\nInstructions: Redeem at https://my.nordaccount.com/activate"
        ]
    )

    p2 = await create_product(
        name="Steam ₹250 Wallet Card (India)",
        category_id=cat_gaming.id,
        price=250.0,
        country_region="India 🇮🇳",
        description="Official Steam Prepaid Wallet Code redeemable in INR on Indian Steam accounts."
    )
    await add_inventory_items(
        product_id=p2.id,
        items=[
            "STEAM-IN-98F1-4402-A901\nInstructions: Redeem in Steam client > Add Funds > Redeem Steam Card",
            "STEAM-IN-22C3-7711-K332\nInstructions: Redeem in Steam client > Add Funds > Redeem Steam Card"
        ]
    )

    p3 = await create_product(
        name="Discord Nitro (1-Month Link)",
        category_id=cat_gaming.id,
        price=299.0,
        country_region="Global 🌐",
        description="1-Month Discord Nitro gift link. Includes HD streaming, custom emojis, and 2 server boosts."
    )
    await add_inventory_items(
        product_id=p3.id,
        items=[
            "https://discord.gift/SAMPLE-NITRO-GIFT-CODE-ALPHA-01\nInstructions: Open link in browser while logged in",
            "https://discord.gift/SAMPLE-NITRO-GIFT-CODE-BRAVO-02\nInstructions: Open link in browser while logged in"
        ]
    )

    p4 = await create_product(
        name="ChatGPT Plus Subscription Voucher",
        category_id=cat_dev.id,
        price=349.0,
        country_region="Global 🌐",
        description="Official OpenAI activation voucher for 1-month ChatGPT Plus access."
    )
    await add_inventory_items(
        product_id=p4.id,
        items=[
            "OPENAI-VOUCHER-PLUS-9091-884\nInstructions: Redeem at https://chatgpt.com/redeem"
        ]
    )

    print("✅ Demo marketplace data seeded successfully!")
    print(f"• 3 Categories: VPN & Security, Gaming & Entertainment, Developer & Cloud")
    print(f"• 4 Products with initial inventory stock items loaded.")


if __name__ == "__main__":
    asyncio.run(seed_data())
