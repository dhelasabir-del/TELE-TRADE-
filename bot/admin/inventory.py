"""Admin country and phone number management."""

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from bot.admin.dashboard import IsAdmin
from bot.database.queries import (
    get_all_countries, get_country_by_id, create_country, update_country, delete_country,
    get_country_stock_count, add_phone_number, add_phone_numbers_bulk,
    get_phone_numbers_by_country, update_phone_number_status, delete_phone_number,
    log_admin_action
)
from bot.keyboards.admin_kb import (
    get_admin_countries_keyboard, get_countries_list_keyboard,
    get_country_actions_keyboard, get_admin_numbers_menu_keyboard,
    get_country_select_keyboard, get_number_actions_keyboard
)
from bot.utils.states import AddCountryStates, AddNumberStates, BulkAddNumberStates, EditCountryStates
from bot.utils.formatters import escape, fmt
from bot.utils.crypto import encrypt_session_string
from bot.utils.logger import logger

router = Router(name="admin_inventory_router")
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


# ─── COUNTRY MANAGEMENT ───────────────────────────────────────────────────────

@router.callback_query(F.data == "admin_countries_menu")
async def countries_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "🌍 <b>COUNTRY MANAGEMENT</b>\n\n"
        "Add or manage countries available for sale:",
        parse_mode="HTML",
        reply_markup=get_admin_countries_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "admin_list_countries")
async def list_countries(callback: CallbackQuery):
    countries = await get_all_countries(active_only=False)
    if not countries:
        await callback.message.edit_text(
            "🌍 No countries added yet.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Add Country", callback_data="admin_add_country")],
                [InlineKeyboardButton(text="🔙 Back", callback_data="admin_countries_menu")]
            ])
        )
        await callback.answer()
        return
    await callback.message.edit_text(
        "🌍 <b>All Countries:</b>\n\nSelect a country to manage:",
        parse_mode="HTML",
        reply_markup=get_countries_list_keyboard(countries)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_country_") & ~F.data.contains("numbers"))
async def show_country_detail(callback: CallbackQuery):
    """Show single country management card."""
    cid = int(callback.data.split("_")[2])
    country = await get_country_by_id(cid)
    if not country:
        await callback.answer("Country not found.", show_alert=True); return

    avail = await get_country_stock_count(cid, "available")
    sold  = await get_country_stock_count(cid, "sold")
    status = "🟢 Active" if country.is_active else "🔴 Disabled"

    text = (
        f"{country.flag_emoji} <b>{escape(country.name)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>Code:</b> <code>{escape(country.code)}</code>\n"
        f"💰 <b>Price:</b> <code>{fmt(country.price)}</code>\n"
        f"📊 <b>Status:</b> {status}\n"
        f"🟢 <b>Available Numbers:</b> <code>{avail}</code>\n"
        f"🔴 <b>Sold Numbers:</b> <code>{sold}</code>\n"
        f"📝 <b>Description:</b> {escape(country.description or 'None')}"
    )
    await callback.message.edit_text(
        text, parse_mode="HTML", reply_markup=get_country_actions_keyboard(country)
    )
    await callback.answer()


# ADD COUNTRY FSM

@router.callback_query(F.data == "admin_add_country")
async def start_add_country(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddCountryStates.waiting_for_name)
    await callback.message.edit_text(
        "🌍 <b>Add New Country — Step 1/5</b>\n\n"
        "Enter the country name (e.g. <i>India</i>, <i>United States</i>):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data="admin_countries_menu")]
        ])
    )
    await callback.answer()


@router.message(AddCountryStates.waiting_for_name)
async def country_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AddCountryStates.waiting_for_code)
    await message.answer(
        "🔤 <b>Step 2/5 — Country Code</b>\n\n"
        "Enter a short 2-letter code (e.g. <code>IN</code>, <code>US</code>, <code>UK</code>):",
        parse_mode="HTML"
    )


@router.message(AddCountryStates.waiting_for_code)
async def country_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    if len(code) < 2 or len(code) > 5:
        await message.answer("⚠️ Code should be 2-5 letters (e.g. IN, US, UK):")
        return
    await state.update_data(code=code)
    await state.set_state(AddCountryStates.waiting_for_flag)
    await message.answer(
        "🏳 <b>Step 3/5 — Flag Emoji</b>\n\n"
        "Paste the flag emoji for this country (e.g. 🇮🇳 🇺🇸 🇬🇧) or send <code>skip</code>:",
        parse_mode="HTML"
    )


@router.message(AddCountryStates.waiting_for_flag)
async def country_flag(message: Message, state: FSMContext):
    txt = message.text.strip()
    flag = "🌐" if txt.lower() == "skip" else txt
    await state.update_data(flag=flag)
    await state.set_state(AddCountryStates.waiting_for_price)
    await message.answer(
        "💰 <b>Step 4/5 — Price per Number (INR)</b>\n\n"
        "Enter the selling price for one number from this country:",
        parse_mode="HTML"
    )


@router.message(AddCountryStates.waiting_for_price)
async def country_price(message: Message, state: FSMContext):
    txt = message.text.strip().replace("₹", "").replace(",", "")
    try:
        price = float(txt)
        if price < 0: raise ValueError()
    except ValueError:
        await message.answer("⚠️ Enter a valid price (e.g. 299):")
        return
    await state.update_data(price=price)
    await state.set_state(AddCountryStates.waiting_for_description)
    await message.answer(
        "📝 <b>Step 5/5 — Description</b>\n\n"
        "Enter a short description for buyers or send <code>skip</code>:",
        parse_mode="HTML"
    )


@router.message(AddCountryStates.waiting_for_description)
async def country_description(message: Message, state: FSMContext):
    txt = message.text.strip()
    desc = None if txt.lower() == "skip" else txt
    data = await state.get_data()
    await state.clear()

    country = await create_country(
        name=data["name"],
        flag_emoji=data["flag"],
        code=data["code"],
        price=data["price"],
        description=desc
    )
    await log_admin_action(
        message.from_user.id, "create_country", "country", str(country.id),
        f"Created {country.name} ({country.code}) at ₹{country.price}"
    )
    await message.answer(
        f"✅ <b>Country Added!</b>\n\n"
        f"{country.flag_emoji} <b>{escape(country.name)}</b> (<code>{escape(country.code)}</code>)\n"
        f"💰 Price: <code>{fmt(country.price)}</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📱 Add Numbers Now", callback_data="admin_add_number")],
            [InlineKeyboardButton(text="🔙 Back to Countries", callback_data="admin_countries_menu")]
        ])
    )


# EDIT / TOGGLE / DELETE COUNTRY

@router.callback_query(F.data.startswith("adm_edit_cname_"))
async def edit_country_name(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.split("_")[3])
    await state.update_data(country_id=cid, field="name")
    await callback.message.answer(
        "✏️ Enter the new <b>country name</b>:", parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data=f"adm_country_{cid}")]
        ])
    )
    from bot.utils.states import EditCountryStates
    await state.set_state(EditCountryStates.waiting_for_value)
    await callback.answer()


@router.callback_query(F.data.startswith("adm_edit_cprice_"))
async def edit_country_price(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.split("_")[3])
    await state.update_data(country_id=cid, field="price")
    await callback.message.answer(
        "✏️ Enter the new <b>price in INR</b>:", parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data=f"adm_country_{cid}")]
        ])
    )
    from bot.utils.states import EditCountryStates
    await state.set_state(EditCountryStates.waiting_for_value)
    await callback.answer()


@router.callback_query(F.data.startswith("adm_edit_cflag_"))
async def edit_country_flag(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.split("_")[3])
    await state.update_data(country_id=cid, field="flag")
    await callback.message.answer(
        "✏️ Enter the new <b>flag emoji</b> (e.g. 🇮🇳):", parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data=f"adm_country_{cid}")]
        ])
    )
    from bot.utils.states import EditCountryStates
    await state.set_state(EditCountryStates.waiting_for_value)
    await callback.answer()


@router.callback_query(F.data.startswith("adm_edit_cdesc_"))
async def edit_country_desc(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.split("_")[3])
    await state.update_data(country_id=cid, field="description")
    await callback.message.answer(
        "✏️ Enter the new <b>description</b>:", parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data=f"adm_country_{cid}")]
        ])
    )
    from bot.utils.states import EditCountryStates
    await state.set_state(EditCountryStates.waiting_for_value)
    await callback.answer()


@router.message(EditCountryStates.waiting_for_value)
async def process_country_edit(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    cid = data["country_id"]
    field = data["field"]
    val = message.text.strip()

    kwargs = {}
    if field == "name": kwargs["name"] = val
    elif field == "price":
        try: kwargs["price"] = float(val.replace("₹","").replace(",",""))
        except ValueError:
            await message.answer("⚠️ Invalid price."); return
    elif field == "flag": kwargs["flag_emoji"] = val
    elif field == "description": kwargs["description"] = val

    await update_country(cid, **kwargs)
    await log_admin_action(message.from_user.id, f"edit_country_{field}", "country", str(cid))
    await message.answer(
        f"✅ <b>Country updated!</b> ({field} → {escape(val)})",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 View Country", callback_data=f"adm_country_{cid}")]
        ])
    )


@router.callback_query(F.data.startswith("adm_toggle_country_"))
async def toggle_country(callback: CallbackQuery):
    cid = int(callback.data.split("_")[3])
    country = await get_country_by_id(cid)
    if not country:
        await callback.answer("Not found.", show_alert=True); return

    new_active = not country.is_active
    await update_country(cid, is_active=new_active)
    status_word = "enabled" if new_active else "disabled"
    await callback.answer(f"Country {status_word}.", show_alert=True)

    # Refresh country card with updated status
    updated_country = await get_country_by_id(cid)
    if not updated_country:
        await list_countries(callback); return

    avail = await get_country_stock_count(cid, "available")
    sold  = await get_country_stock_count(cid, "sold")
    status = "🟢 Active" if updated_country.is_active else "🔴 Disabled"

    text = (
        f"{updated_country.flag_emoji} <b>{escape(updated_country.name)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>Code:</b> <code>{escape(updated_country.code)}</code>\n"
        f"💰 <b>Price:</b> <code>{fmt(updated_country.price)}</code>\n"
        f"📊 <b>Status:</b> {status}\n"
        f"🟢 <b>Available Numbers:</b> <code>{avail}</code>\n"
        f"🔴 <b>Sold Numbers:</b> <code>{sold}</code>\n"
        f"📝 <b>Description:</b> {escape(updated_country.description or 'None')}"
    )
    await callback.message.edit_text(
        text, parse_mode="HTML", reply_markup=get_country_actions_keyboard(updated_country)
    )


@router.callback_query(F.data.startswith("adm_delete_country_"))
async def delete_country_cb(callback: CallbackQuery):
    cid = int(callback.data.split("_")[3])
    country = await get_country_by_id(cid)
    if not country:
        await callback.answer("Not found.", show_alert=True); return

    deleted = await delete_country(cid)
    if deleted:
        msg = f"Deleted {country.name}"
        await callback.answer("Country deleted from database.", show_alert=True)
    else:
        msg = f"Disabled {country.name} (has order history)"
        await callback.answer("Country has order history, so it was disabled/archived.", show_alert=True)

    await log_admin_action(callback.from_user.id, "delete_country", "country", str(cid), msg)
    await list_countries(callback)


# ─── PHONE NUMBER MANAGEMENT ──────────────────────────────────────────────────

@router.callback_query(F.data == "admin_numbers_menu")
async def numbers_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "📱 <b>PHONE NUMBER MANAGEMENT</b>\n\n"
        "Add, view, and manage phone number inventory:",
        parse_mode="HTML",
        reply_markup=get_admin_numbers_menu_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "admin_add_number")
async def start_add_number(callback: CallbackQuery, state: FSMContext):
    countries = await get_all_countries(active_only=False)
    if not countries:
        await callback.message.edit_text(
            "⚠️ Add a country first.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Add Country", callback_data="admin_add_country")]
            ])
        )
        await callback.answer(); return
    await state.set_state(AddNumberStates.waiting_for_country)
    await callback.message.edit_text(
        "📱 <b>Add Number — Step 1/4</b>\n\nSelect the country for this number:",
        parse_mode="HTML",
        reply_markup=get_country_select_keyboard(countries, "adm_numcountry")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_numcountry_"), AddNumberStates.waiting_for_country)
async def number_country_selected(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.split("_")[2])
    country = await get_country_by_id(cid)
    if not country:
        await callback.answer("Country not found.", show_alert=True); return
    await state.update_data(country_id=cid, country_name=country.name)
    await state.set_state(AddNumberStates.waiting_for_phone)
    await callback.message.edit_text(
        f"📱 <b>Add Number — Step 2/4</b>\n\n"
        f"Country: {escape(country.flag_emoji)} {escape(country.name)}\n\n"
        f"Enter the <b>full phone number</b> (e.g. <code>+919876543210</code>):",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(AddNumberStates.waiting_for_phone)
async def number_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    if len(phone) < 6:
        await message.answer("⚠️ Enter a valid phone number (at least 6 digits):"); return
    await state.update_data(phone=phone)
    await state.set_state(AddNumberStates.waiting_for_2fa)
    await message.answer(
        "🔐 <b>Step 3/4 — 2FA Password</b>\n\n"
        "Enter the <b>2FA / Two-Factor password</b> for this account, or send <code>none</code> if none:",
        parse_mode="HTML"
    )


@router.message(AddNumberStates.waiting_for_2fa)
async def number_2fa(message: Message, state: FSMContext):
    txt = message.text.strip() if message.text else ""
    two_fa = None if txt.lower() == "none" else txt
    await state.update_data(two_fa=two_fa)
    await state.set_state(AddNumberStates.waiting_for_session)

    data = await state.get_data()
    phone = data.get("phone", "")

    await message.answer(
        f"📁 <b>Step 4/5 — Telegram .session (Automated OTP)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📞 <b>Phone:</b> <code>{escape(phone)}</code>\n\n"
        f"Choose how to attach a <code>.session</code> file for <b>Automated OTP</b>:\n\n"
        f"1️⃣ <b>Direct Bot Login (Easiest):</b> Tap button below — Telegram will send an OTP to this number and the bot will create the session directly!\n"
        f"2️⃣ <b>Upload File:</b> Send an existing <code>.session</code> file as a document.\n"
        f"3️⃣ <b>Skip:</b> Use manual admin OTP forwarding.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔐 Login & Create Session in Bot", callback_data="adm_login_session")],
            [InlineKeyboardButton(text="⏭️ Skip .session (Manual OTP)", callback_data="adm_skip_session")]
        ])
    )


@router.callback_query(F.data == "adm_login_session", AddNumberStates.waiting_for_session)
async def start_bot_session_login(callback: CallbackQuery, state: FSMContext):
    """Admin clicked 'Login & Create Session in Bot' — requests Telegram OTP."""
    data = await state.get_data()
    phone = data.get("phone", "").strip()

    await callback.message.edit_text(
        f"🔄 <b>Connecting to Telegram servers...</b>\n\n"
        f"Requesting login code for <code>{escape(phone)}</code>...",
        parse_mode="HTML"
    )
    await callback.answer()

    from bot.services.session_service import start_in_bot_login
    success, msg, code_hash = await start_in_bot_login(callback.from_user.id, phone)

    if not success:
        await callback.message.edit_text(
            f"⚠️ <b>Failed to send login code</b>\n\n"
            f"Error: <code>{escape(msg)}</code>\n\n"
            f"You can try again or skip this step:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Try Again", callback_data="adm_login_session")],
                [InlineKeyboardButton(text="⏭️ Skip (Manual OTP)", callback_data="adm_skip_session")]
            ])
        )
        return

    await state.update_data(phone_code_hash=code_hash)
    await state.set_state(AddNumberStates.waiting_for_tg_code)
    await callback.message.edit_text(
        f"📲 <b>TELEGRAM LOGIN CODE SENT!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📞 <b>Phone:</b> <code>{escape(phone)}</code>\n\n"
        f"Telegram has sent an SMS or App Code to this phone number.\n\n"
        f"👇 <b>Type and send the verification code here</b> (e.g. <code>12345</code>):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data="adm_skip_session")]
        ])
    )


@router.message(AddNumberStates.waiting_for_tg_code)
async def process_tg_login_code(message: Message, state: FSMContext):
    """Admin enters the OTP code received from Telegram."""
    code = message.text.strip().replace(" ", "").replace("-", "")
    data = await state.get_data()
    phone = data.get("phone", "")
    code_hash = data.get("phone_code_hash", "")
    preset_2fa = data.get("two_fa")

    from bot.services.session_service import submit_in_bot_code
    success, result_text, needs_2fa, session_file = await submit_in_bot_code(
        admin_tg_id=message.from_user.id,
        phone_number=phone,
        phone_code_hash=code_hash,
        code=code,
        preset_2fa=preset_2fa
    )

    if needs_2fa:
        await state.set_state(AddNumberStates.waiting_for_tg_2fa)
        await message.answer(
            f"🔐 <b>2FA Password Required</b>\n\n"
            f"This account is protected with Two-Factor Authentication.\n\n"
            f"Please enter the <b>2FA Password</b> for <code>{escape(phone)}</code>:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Cancel", callback_data="adm_skip_session")]
            ])
        )
        return

    if not success:
        await message.answer(
            f"{result_text}\n\nPlease enter the correct code:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Skip / Cancel", callback_data="adm_skip_session")]
            ])
        )
        return

    # Success!
    await state.update_data(session_string=session_file, session_file=None)
    await state.set_state(AddNumberStates.waiting_for_notes)
    await message.answer(
        f"✅ <b>Telegram Session Created & Linked!</b>\n\n"
        f"👤 <b>Account Name:</b> {escape(result_text)}\n"
        f"📁 <b>Session:</b> <code>[Encrypted StringSession Attached ⚡]</code>\n"
        f"⚡ <i>Automated OTP delivery is now 100% active for this number.</i>\n\n"
        f"📝 <b>Step 5/5 — Additional Notes</b>\n"
        f"Enter any delivery notes for buyers or send <code>none</code>:",
        parse_mode="HTML"
    )


@router.message(AddNumberStates.waiting_for_tg_2fa)
async def process_tg_2fa_password(message: Message, state: FSMContext):
    """Admin enters the 2FA password during interactive login."""
    pwd = message.text.strip()
    data = await state.get_data()
    phone = data.get("phone", "")

    from bot.services.session_service import submit_in_bot_2fa
    success, result_text, session_file = await submit_in_bot_2fa(
        admin_tg_id=message.from_user.id,
        phone_number=phone,
        password=pwd
    )

    if not success:
        await message.answer(
            f"{result_text}\n\nPlease re-enter the 2FA password:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Cancel", callback_data="adm_skip_session")]
            ])
        )
        return

    await state.update_data(session_string=session_file, session_file=None, two_fa=pwd)
    await state.set_state(AddNumberStates.waiting_for_notes)
    await message.answer(
        f"✅ <b>Telegram Session Created & Linked!</b>\n\n"
        f"👤 <b>Account Name:</b> {escape(result_text)}\n"
        f"📁 <b>Session:</b> <code>[Encrypted StringSession Attached ⚡]</code>\n"
        f"⚡ <i>Automated OTP delivery is now 100% active for this number.</i>\n\n"
        f"📝 <b>Step 5/5 — Additional Notes</b>\n"
        f"Enter any delivery notes for buyers or send <code>none</code>:",
        parse_mode="HTML"
    )


@router.callback_query(F.data == "adm_skip_session")
async def skip_session_cb(callback: CallbackQuery, state: FSMContext):
    from bot.services.session_service import cancel_in_bot_login
    cancel_in_bot_login(callback.from_user.id)
    await state.update_data(session_file=None)
    await state.set_state(AddNumberStates.waiting_for_notes)
    await callback.message.answer(
        "📝 <b>Step 5/5 — Additional Notes</b>\n\n"
        "Enter any extra delivery info (login instructions, account details, etc.) "
        "or send <code>none</code>:",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(AddNumberStates.waiting_for_session)
async def number_session(message: Message, state: FSMContext, bot: Bot):
    session_string = None
    data = await state.get_data()
    phone = data.get("phone", "phone").replace("+", "").replace(" ", "").replace("-", "")

    if message.document:
        doc = message.document
        import tempfile
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from bot.config import config
        
        # Download temp file to convert to StringSession in memory
        with tempfile.NamedTemporaryFile(suffix=".session", delete=False) as tmp_f:
            tmp_path = tmp_f.name
        try:
            await bot.download(doc.file_id, destination=tmp_path)
            base_sess = tmp_path.removesuffix(".session")
            temp_client = TelegramClient(base_sess, config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH)
            await temp_client.connect()
            raw_str = temp_client.session.save()
            await temp_client.disconnect()
            session_string = encrypt_session_string(raw_str)
            await message.answer("✅ <b>Session converted & encrypted into memory!</b>", parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Could not convert uploaded session: {e}")
            await message.answer("⚠️ Could not read session file. Continuing without auto-OTP.")
        finally:
            try:
                import os
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass

    elif message.text:
        txt = message.text.strip()
        if txt.lower() != "skip":
            # Check if admin provided raw or StringSession
            session_string = encrypt_session_string(txt)
            await message.answer("✅ <b>Encrypted session string linked!</b>", parse_mode="HTML")

    await state.update_data(session_string=session_string, session_file=None)
    await state.set_state(AddNumberStates.waiting_for_notes)
    await message.answer(
        "📝 <b>Step 5/5 — Additional Notes</b>\n\n"
        "Enter any extra delivery info (login instructions, account details, etc.) "
        "or send <code>none</code>:",
        parse_mode="HTML"
    )


@router.message(AddNumberStates.waiting_for_notes)
async def number_notes(message: Message, state: FSMContext):
    txt = message.text.strip() if message.text else ""
    notes = None if txt.lower() == "none" else txt
    data = await state.get_data()
    await state.clear()

    num = await add_phone_number(
        country_id=data["country_id"],
        phone_number=data["phone"],
        two_fa_password=data.get("two_fa"),
        additional_notes=notes,
        session_file=data.get("session_file"),
        session_string=data.get("session_string")
    )
    avail = await get_country_stock_count(data["country_id"], "available")
    session_badge = "⚡ Auto-OTP (StringSession linked)" if (num.session_string or num.session_file) else "Manual OTP"
    await log_admin_action(
        message.from_user.id, "add_phone_number", "phone_number", str(num.id),
        f"Added {data['phone']} ({data['country_name']}) with session linked: {bool(num.session_string or num.session_file)}"
    )
    await message.answer(
        f"✅ <b>Number Added Successfully!</b>\n\n"
        f"🆔 <b>Code:</b> <code>{escape(num.number_code)}</code>\n"
        f"📞 <b>Phone:</b> <code>{escape(num.phone_number)}</code>\n"
        f"🔐 <b>2FA:</b> <code>{'Set' if num.two_fa_password else 'None'}</code>\n"
        f"⚡ <b>OTP Mode:</b> <code>{session_badge}</code>\n"
        f"🌍 <b>Country:</b> {escape(data['country_name'])}\n"
        f"🟢 <b>Total Available in Country:</b> {avail}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Add Another", callback_data="admin_add_number")],
            [InlineKeyboardButton(text="📁 Sync .session Folder", callback_data="admin_sync_sessions")],
            [InlineKeyboardButton(text="🔙 Numbers Menu", callback_data="admin_numbers_menu")]
        ])
    )


# BULK ADD NUMBERS

@router.callback_query(F.data == "admin_bulk_add_numbers")
async def start_bulk_add(callback: CallbackQuery, state: FSMContext):
    countries = await get_all_countries(active_only=False)
    if not countries:
        await callback.answer("Add a country first.", show_alert=True); return
    await state.set_state(BulkAddNumberStates.waiting_for_country)
    await callback.message.edit_text(
        "📦 <b>Bulk Add Numbers — Select Country:</b>",
        parse_mode="HTML",
        reply_markup=get_country_select_keyboard(countries, "adm_bulkcountry")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_bulkcountry_"), BulkAddNumberStates.waiting_for_country)
async def bulk_country_selected(callback: CallbackQuery, state: FSMContext):
    cid = int(callback.data.split("_")[2])
    country = await get_country_by_id(cid)
    if not country:
        await callback.answer("Not found.", show_alert=True); return
    await state.update_data(country_id=cid, country_name=country.name)
    await state.set_state(BulkAddNumberStates.waiting_for_data)
    await callback.message.edit_text(
        f"📦 <b>Bulk Add for {escape(country.flag_emoji)} {escape(country.name)}</b>\n\n"
        f"Paste numbers in this format — <b>each line = 1 number</b>:\n\n"
        f"<pre>+919876543210|password123|optional notes\n"
        f"+919876543211|none|optional notes\n"
        f"+919876543212|password456</pre>\n\n"
        f"• Use <code>|</code> to separate: phone | 2FA password | notes\n"
        f"• 2FA password: <code>none</code> if not set\n"
        f"• Notes field is optional",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(BulkAddNumberStates.waiting_for_data)
async def process_bulk_numbers(message: Message, state: FSMContext):
    raw_lines = [l.strip() for l in message.text.strip().splitlines() if l.strip()]
    data = await state.get_data()
    country_id = data["country_id"]
    await state.clear()

    items = []
    errors = []
    for i, line in enumerate(raw_lines):
        parts = [p.strip() for p in line.split("|")]
        phone = parts[0] if parts else ""
        if len(phone) < 6:
            errors.append(f"Line {i+1}: invalid phone '{phone}'")
            continue
        two_fa = parts[1] if len(parts) > 1 and parts[1].lower() != "none" else None
        notes  = parts[2] if len(parts) > 2 else None
        items.append({"phone_number": phone, "two_fa_password": two_fa, "notes": notes})

    if not items:
        await message.answer("⚠️ No valid numbers found. Please check the format and try again.")
        return

    count = await add_phone_numbers_bulk(country_id=country_id, numbers=items)
    await log_admin_action(
        message.from_user.id, "bulk_add_numbers", "country", str(country_id),
        f"Bulk added {count} numbers to {data['country_name']}"
    )

    avail = await get_country_stock_count(country_id, "available")
    result = (
        f"✅ <b>Bulk Import Complete!</b>\n\n"
        f"🌍 <b>Country:</b> {escape(data['country_name'])}\n"
        f"📦 <b>Numbers Added:</b> <code>{count}</code>\n"
        f"🟢 <b>Total Available:</b> <code>{avail}</code>\n"
    )
    if errors:
        result += f"\n⚠️ <b>Skipped ({len(errors)}):</b>\n"
        result += "\n".join(f"• {escape(e)}" for e in errors[:5])

    await message.answer(
        result, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📦 Bulk Add More", callback_data="admin_bulk_add_numbers")],
            [InlineKeyboardButton(text="🔙 Numbers Menu", callback_data="admin_numbers_menu")]
        ])
    )


@router.callback_query(F.data == "admin_sync_sessions")
async def sync_sessions_folder(callback: CallbackQuery):
    """Scan data/sessions/ folder and automatically import new .session files into stock."""
    from bot.config import config
    countries = await get_all_countries(active_only=False)
    if not countries:
        await callback.answer("Please add at least one Country first before syncing.", show_alert=True)
        return

    session_files = list(config.SESSIONS_DIR.glob("*.session"))
    if not session_files:
        await callback.message.edit_text(
            f"📁 <b>Sessions Folder is Empty</b>\n\n"
            f"Path: <code>{escape(str(config.SESSIONS_DIR))}</code>\n\n"
            f"Place your <code>.session</code> files (named by phone number, e.g. <code>+919876543210.session</code>) "
            f"inside this folder and tap <b>Sync</b> again.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Scan Again", callback_data="admin_sync_sessions")],
                [InlineKeyboardButton(text="🔙 Numbers Menu", callback_data="admin_numbers_menu")]
            ])
        )
        await callback.answer(); return

    # Get all already existing numbers/sessions
    from bot.database.database import get_db
    async with get_db() as conn:
        cur = await conn.execute("SELECT phone_number, session_file FROM phone_numbers")
        existing_rows = await cur.fetchall()
        existing_phones = {r["phone_number"].replace("+", "").strip() for r in existing_rows}
        existing_files = {r["session_file"] for r in existing_rows if r["session_file"]}

    imported = 0
    skipped = 0

    for s_file in session_files:
        filename = s_file.name
        phone_stem = s_file.stem.strip()
        clean_phone = phone_stem if phone_stem.startswith("+") else f"+{phone_stem}"
        raw_digits = phone_stem.replace("+", "")

        if filename in existing_files or raw_digits in existing_phones:
            skipped += 1
            continue

        # Match country by prefix
        matched_country = None
        for c in countries:
            if c.code and raw_digits.startswith(c.code):
                matched_country = c; break
            # Common prefix matching
            if c.name.lower() in ("india", "in") and raw_digits.startswith("91"):
                matched_country = c; break
            elif c.name.lower() in ("united states", "usa", "us") and raw_digits.startswith("1"):
                matched_country = c; break
            elif c.name.lower() in ("united kingdom", "uk") and raw_digits.startswith("44"):
                matched_country = c; break
            elif c.name.lower() in ("russia", "ru") and raw_digits.startswith("7"):
                matched_country = c; break

        if not matched_country:
            matched_country = countries[0]  # default to first country

        await add_phone_number(
            country_id=matched_country.id,
            phone_number=clean_phone,
            session_file=filename,
            additional_notes="Auto-synced from sessions folder"
        )
        imported += 1

    await callback.message.edit_text(
        f"📁 <b>SESSION FOLDER SYNC COMPLETE!</b>\n\n"
        f"📂 Total <code>.session</code> Files Found: <code>{len(session_files)}</code>\n"
        f"✅ Newly Imported to Stock: <code>{imported}</code>\n"
        f"⏭️ Already in Stock (Skipped): <code>{skipped}</code>\n\n"
        f"<i>All newly imported numbers have 100% Automated OTP Forwarding enabled.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 View Available Numbers", callback_data="admin_view_available_numbers")],
            [InlineKeyboardButton(text="🔙 Numbers Menu", callback_data="admin_numbers_menu")]
        ])
    )
    await callback.answer()


# VIEW NUMBERS

@router.callback_query(F.data == "admin_view_available_numbers")
async def view_available_numbers(callback: CallbackQuery):
    await _view_numbers_by_status(callback, "available")


@router.callback_query(F.data == "admin_view_sold_numbers")
async def view_sold_numbers(callback: CallbackQuery):
    await _view_numbers_by_status(callback, "sold")


async def _view_numbers_by_status(callback: CallbackQuery, status: str):
    countries = await get_all_countries(active_only=False)
    lines = [f"📱 <b>{'AVAILABLE' if status=='available' else 'SOLD'} NUMBERS BY COUNTRY</b>\n"]
    for c in countries:
        nums = await get_phone_numbers_by_country(c.id, status=status, limit=20)
        if not nums:
            continue
        lines.append(f"\n{c.flag_emoji} <b>{escape(c.name)}</b> ({len(nums)}):")
        for n in nums:
            two_fa_badge = " 🔐" if n.two_fa_password else ""
            session_badge = " ⚡" if (n.session_string or n.session_file) else ""
            lines.append(f"  • <code>{escape(n.phone_number)}</code>{two_fa_badge}{session_badge}"
                         f" | <code>{escape(n.number_code)}</code>")
    if len(lines) == 1:
        lines.append("<i>None found.</i>")
    await callback.message.edit_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back", callback_data="admin_numbers_menu")]
        ])
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_country_numbers_"))
async def view_country_numbers(callback: CallbackQuery):
    cid = int(callback.data.split("_")[3])
    country = await get_country_by_id(cid)
    if not country:
        await callback.answer("Not found.", show_alert=True); return

    nums = await get_phone_numbers_by_country(cid, status="available", limit=30)
    if not nums:
        await callback.message.edit_text(
            f"{country.flag_emoji} <b>{escape(country.name)}</b>\n\n<i>No available numbers in stock.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Add Number", callback_data="admin_add_number")],
                [InlineKeyboardButton(text="🔙 Back", callback_data=f"adm_country_{cid}")]
            ])
        )
        await callback.answer(); return

    lines = [f"{country.flag_emoji} <b>{escape(country.name)} — Available Numbers ({len(nums)}):</b>\n"]
    for n in nums:
        two_fa_badge = " 🔐" if n.two_fa_password else ""
        session_badge = " ⚡ Auto-OTP" if (n.session_string or n.session_file) else ""
        lines.append(
            f"• <code>{escape(n.phone_number)}</code>{two_fa_badge}{session_badge}\n"
            f"  Code: <code>{escape(n.number_code)}</code>\n"
        )

    await callback.message.edit_text(
        "\n".join(lines), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Add More", callback_data="admin_add_number")],
            [InlineKeyboardButton(text="🔙 Back", callback_data=f"adm_country_{cid}")]
        ])
    )
    await callback.answer()
