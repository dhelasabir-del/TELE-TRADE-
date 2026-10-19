# 🛒 RYUS MARKET — Telegram Marketplace Bot (Render & PostgreSQL Ready)

A production-ready Telegram phone number marketplace bot built with **aiogram 3**, **asyncpg (PostgreSQL)**, **Telethon StringSession** with **Fernet at-rest encryption**, and a comprehensive **Anti-Abuse & Strike System**.

Designed specifically for zero-disk hosting environments such as **Render Free Tier (512 MB RAM)**, **Supabase**, and **Neon**.

---

## 🌟 Key Features

### 1. ☁️ Render Free Tier Ready (No Persistent Disk Required)
* **PostgreSQL Engine (`asyncpg`):** Connection pooling with SSL support (`ssl="require"` for Neon, Supabase, and Render).
* **Zero `.session` Files on Disk:** Telethon sessions are generated and stored strictly as encrypted `StringSession` strings in PostgreSQL.
* **At-Rest Fernet Encryption:** Encrypted at rest using `ENCRYPTION_KEY`; decrypted strictly in volatile memory.
* **Strict 512 MB RAM Management:** Telethon clients are disconnected immediately after each OTP fetch.
* **Built-in Web Server & `/health` Endpoint:** Runs an `aiohttp` web server bound to `$PORT` alongside bot polling, allowing **UptimeRobot** to keep the bot alive 24/7.
* **Graceful `SIGTERM` Shutdown:** Handles container restarts cleanly, closing sessions and database pools gracefully.

### 2. 🛡️ Anti-Abuse & Anti-Fraud System
* **Single Pending Order Rule:** Users can only have **one** pending deposit/claim at a time. Trying to create another shows their existing pending claim.
* **Escalating Strikes & Cooldowns:**
  * **Strike 1:** 5-minute cooldown with live countdown displayed to the user.
  * **Strike 2:** 30-minute cooldown with live countdown.
  * **Strike 3:** **Auto-ban** (`is_blocked = 1`) with instant push alert sent to all admins.
* **Automatic Strike Triggers:**
  * When a deposit order expires unpaid (default 15 minutes).
  * When an administrator rejects a fake payment claim.
  * When an invalid or already-used UTR is submitted.
* **Strike Forgiveness:**
  * Strikes automatically expire after **30 days of good behavior**.
  * Each **verified payment** approved by admin **removes one active strike**.
* **Anti-Flood Rate Limiting:** Enforces a maximum of **5 button presses per 10 seconds** per user; excess presses are silently dropped.
* **Silent Ban Enforcement:** Banned users receive **no response** from payment, deposit, and purchase features.

### 3. 👥 Customer Features
* **Interactive Catalog:** Country/region categories with flags, prices in INR, and live stock counts.
* **Automated OTP Delivery:** One-tap `[⚡ Get OTP]` button fetches official Telegram (777000) verification codes from memory.
* **Exclusive Access Logout:** Buyers can tap `[🚪 Logout Bot from Account]` to revoke the bot device session from Telegram servers.
* **Native UPI Deposits:** Dynamic QR generation, minimum deposit validation, and UTR reference tracking.
* **Transaction Ledger:** Complete balance history with credits, debits, and purchases.

### 4. ⚙️ Administrator Control Panel (`/admin`)
* **Real-time Analytics:** User count, completed orders, gross revenue, and pending deposit totals.
* **Admin-Only Commands:**
  * `/ban <user_id | @username | USR-1001>` — Ban a user.
  * `/unban <user_id | @username | USR-1001>` — Lift a user's ban.
  * `/strikes [user_id]` — View active strikes, cooldown status, and history (or view system strike log if omitted).
  * `/resetstrikes <user_id>` — Clear all active strikes and remove cooldown.
  * `/banned` — List all currently banned users with one-tap unban buttons.
  * `/strikelog` — View the 25 most recent system-wide strikes.
* **Interactive Number Adding:** Add Telegram numbers via in-bot interactive OTP login without generating `.session` files.

---

## 📁 Project Architecture

```
RYUS MARKET/
├── bot/
│   ├── main.py                  # Entry point, aiohttp health server & SIGTERM handler
│   ├── config.py                # Environment configuration & validation
│   ├── database/
│   │   ├── database.py          # asyncpg connection pool & schema migration
│   │   ├── models.py            # Dataclass models (User, Order, Strike, etc.)
│   │   └── queries.py           # Atomic queries, purchases, & audit logging
│   ├── services/
│   │   ├── anti_abuse.py        # Strikes, escalating cooldowns, & order expiry
│   │   ├── session_service.py   # In-memory Telethon StringSession & auto-OTP
│   │   └── qr_service.py        # UPI QR code generator
│   ├── middlewares/
│   │   ├── throttling.py        # 5 presses per 10s anti-flood middleware
│   │   └── auth.py              # User registration & silent payment ban check
│   ├── handlers/                # Customer routers (catalog, wallet, deposits)
│   ├── admin/                   # Admin panel routers (inventory, users, orders)
│   ├── keyboards/               # Customer & Admin inline/reply keyboards
│   └── utils/
│       ├── crypto.py            # Fernet at-rest session encryption
│       ├── formatters.py        # Cards, escaping & currency formatting
│       └── logger.py            # Safe logging (never logs tokens or credentials)
├── migrate_sqlite_to_postgres.py# Safe idempotent data migration script
├── test_new_features.py         # Automated test suite
├── render.yaml                  # Render Blueprint deployment specification
├── requirements.txt             # Python dependencies
├── .env.example                 # Environment variables template
└── .gitignore                   # Prevents leaking secrets, .session, and DBs
```

---

## 🚀 Quick Start (Local Testing)

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Fill in your credentials:
```env
BOT_TOKEN=your_bot_token_from_botfather
ADMIN_IDS=123456789
API_ID=2040
API_HASH=b18441a1ff607e10a989891a5462e627
ENCRYPTION_KEY=your_generated_fernet_key=
PORT=8080
```
*(If `DATABASE_URL` is omitted locally, the bot automatically falls back to local SQLite at `data/marketplace.db` with identical features).*

### 3. Run Automated Tests
```bash
python test_new_features.py
```

### 4. Start the Bot
```bash
python -m bot.main
```
Verify the health endpoint in your browser or curl:
```bash
curl http://127.0.0.1:8080/health
```

---

## 📦 Deploying to Render Free Tier

### Step 1: Create a PostgreSQL Database
Create a free database on [Neon.tech](https://neon.tech) or [Supabase.com](https://supabase.com). Copy the connection URL (`DATABASE_URL`).

### Step 2: Migrate Local SQLite & `.session` Files
Set `DATABASE_URL` in your `.env` and run the migration script:
```bash
python migrate_sqlite_to_postgres.py
```
This transfers existing users, countries, orders, deposits, and converts `.session` files into encrypted `StringSession` records.

### Step 3: Push to GitHub
```bash
git add .
git commit -m "Production release: PostgreSQL, Fernet, and Anti-Abuse"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo-name>.git
git push -u origin main
```

### Step 4: Deploy on Render
1. Go to [dashboard.render.com](https://dashboard.render.com) ➔ **New +** ➔ **Web Service**.
2. Select your repository.
3. Configure settings:
   * **Runtime:** `Python 3`
   * **Build Command:** `pip install -r requirements.txt`
   * **Start Command:** `python -m bot.main`
   * **Health Check Path:** `/health`
4. Set Environment Variables:
   * `BOT_TOKEN`, `ADMIN_IDS`, `DATABASE_URL`, `API_ID`, `API_HASH`, `ENCRYPTION_KEY`, `UPI_ID`, `UPI_PAYEE_NAME`, `MIN_DEPOSIT_INR`.
5. Deploy.

### Step 5: Keep Alive with UptimeRobot
Add a free HTTP monitor at [UptimeRobot.com](https://uptimerobot.com) pointing to:
`https://<your-render-service>.onrender.com/health` (ping every 5 minutes).

---

## 🛡️ License & Security
Private proprietary software for **RYUS MARKET**.
All credentials, tokens, and session keys are encrypted with Fernet and never logged.
