"""
Helper script to generate Telethon .session files for your inventory.
Usage:
    python create_session.py
"""

import asyncio
from pathlib import Path
from telethon import TelegramClient
from bot.config import config

async def main():
    print("=" * 60)
    print("  RYUS MARKET — Telegram .session Creator")
    print("=" * 60)
    
    phone = input("\nEnter phone number with country code (e.g. +919876543210): ").strip()
    if not phone:
        print("Phone number is required.")
        return
    
    clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "")
    session_path = config.SESSIONS_DIR / f"+{clean_phone}"
    
    print(f"\nConnecting to Telegram servers...")
    client = TelegramClient(
        session=str(session_path),
        api_id=config.TELEGRAM_API_ID,
        api_hash=config.TELEGRAM_API_HASH
    )
    
    await client.start(phone=lambda: phone)
    
    me = await client.get_me()
    print("\n" + "━" * 60)
    print(f"✅ SUCCESS! Logged in as: {me.first_name} (@{me.username or 'No Username'})")
    print(f"📁 Session saved at: {session_path}.session")
    print("━" * 60)
    print(f"\nYou can now:")
    print(f"1. Send '+{clean_phone}.session' when adding a number in the bot, OR")
    print(f"2. Use '📁 Sync .session Folder' in Admin Panel to auto-import it!")
    
    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
