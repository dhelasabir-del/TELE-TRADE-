"""Database package exports."""

from bot.database.database import get_db, init_database
from bot.database.models import (
    User, Country, PhoneNumber, Order, OtpForward,
    Deposit, Transaction, AdminAction, DashboardStats
)
from bot.database.queries import (
    MarketplaceError, InsufficientFundsError, OutOfStockError,
    UserBlockedError, DuplicateUtrError,
    # Users
    get_or_create_user, get_user_by_telegram_id, get_user_by_id,
    get_user_by_internal_id, set_user_blocked, search_users,
    # Countries
    get_all_countries, get_country_by_id, get_country_by_code,
    create_country, update_country, delete_country, get_country_stock_count,
    # Phone numbers
    add_phone_number, add_phone_numbers_bulk,
    get_phone_number_by_id, get_phone_numbers_by_country,
    update_phone_number_status, delete_phone_number,
    # Purchase
    execute_purchase,
    # Orders
    get_user_orders, get_order_by_id, get_order_by_code,
    search_orders, update_order_status,
    # OTP forwarding
    log_otp_forward, get_otp_history_for_order,
    # Deposits
    check_utr_exists, create_deposit_request, get_deposit_by_id,
    get_pending_deposits, get_user_deposits, approve_deposit, reject_deposit,
    # Transactions & balance
    get_user_transactions, adjust_user_balance,
    # Admin
    get_admin_dashboard_stats, log_admin_action
)

__all__ = [
    "get_db", "init_database",
    "User", "Country", "PhoneNumber", "Order", "OtpForward",
    "Deposit", "Transaction", "AdminAction", "DashboardStats",
    "MarketplaceError", "InsufficientFundsError", "OutOfStockError",
    "UserBlockedError", "DuplicateUtrError",
    "get_or_create_user", "get_user_by_telegram_id", "get_user_by_id",
    "get_user_by_internal_id", "set_user_blocked", "search_users",
    "get_all_countries", "get_country_by_id", "get_country_by_code",
    "create_country", "update_country", "delete_country", "get_country_stock_count",
    "add_phone_number", "add_phone_numbers_bulk",
    "get_phone_number_by_id", "get_phone_numbers_by_country",
    "update_phone_number_status", "delete_phone_number",
    "execute_purchase",
    "get_user_orders", "get_order_by_id", "get_order_by_code",
    "search_orders", "update_order_status",
    "log_otp_forward", "get_otp_history_for_order",
    "check_utr_exists", "create_deposit_request", "get_deposit_by_id",
    "get_pending_deposits", "get_user_deposits", "approve_deposit", "reject_deposit",
    "get_user_transactions", "adjust_user_balance",
    "get_admin_dashboard_stats", "log_admin_action",
]
