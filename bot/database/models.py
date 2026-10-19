"""
Data models for RYUS MARKET — Phone Number Marketplace.

Product model → Country (e.g. 🇮🇳 India)
Inventory model → Individual phone number accounts with 2FA passwords
Order model → tracks which buyer owns which number
OTP Forwarding → admin pastes OTP, bot delivers to buyer
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class User:
    id: int
    internal_id: str
    telegram_id: int
    username: Optional[str]
    first_name: Optional[str]
    wallet_balance: float
    is_blocked: bool
    created_at: str
    updated_at: str

    @property
    def display_name(self) -> str:
        if self.username:
            return f"@{self.username}"
        return self.first_name or f"User {self.telegram_id}"


@dataclass
class Country:
    """A country/region available in the marketplace."""
    id: int
    name: str            # e.g. "India"
    flag_emoji: str      # e.g. "🇮🇳"
    code: str            # e.g. "IN"
    price: float         # price per number in INR
    description: Optional[str]
    is_active: bool
    created_at: str

    @property
    def display_name(self) -> str:
        return f"{self.flag_emoji} {self.name}"


@dataclass
class PhoneNumber:
    """
    An individual phone number account in stock.
    Linked to a Country. Contains the number, optional 2FA password,
    and delivery notes. Status: available → sold → disabled.
    """
    id: int
    number_code: str         # e.g. "NUM-A1B2C3D4"
    country_id: int
    country_name: str
    country_flag: str
    phone_number: str        # the actual phone number
    two_fa_password: Optional[str] = None   # 2FA / backup password if set
    additional_notes: Optional[str] = None  # extra delivery info
    session_file: Optional[str] = None      # path/filename in data/sessions/
    session_string: Optional[str] = None    # optional Telethon string session
    status: str = 'available'               # 'available', 'sold', 'disabled'
    sold_to_user_id: Optional[int] = None
    order_id: Optional[int] = None
    created_at: str = ""
    sold_at: Optional[str] = None

    @property
    def has_session(self) -> bool:
        return bool(self.session_file or self.session_string)

    @property
    def masked_number(self) -> str:
        """Show partial number for catalog display e.g. +91 98765*****"""
        n = self.phone_number.strip()
        if len(n) >= 6:
            return n[:len(n)-5] + "*****"
        return n[:2] + "***"


@dataclass
class Order:
    id: int
    order_code: str
    user_id: int
    user_telegram_id: int
    country_id: int
    country_name: str
    country_flag: str
    phone_number: str
    two_fa_password: Optional[str]
    price: float
    payment_method: str
    additional_notes: Optional[str]
    status: str                             # 'completed', 'refunded', 'cancelled'
    created_at: str
    session_file: Optional[str] = None     # path/filename in data/sessions/
    session_string: Optional[str] = None   # Telethon StringSession (encrypted)

    @property
    def has_session(self) -> bool:
        return bool(self.session_file or self.session_string)


@dataclass
class OtpForward:
    """
    Tracks an OTP forwarded by admin to a buyer for a purchased number.
    Admin submits OTP → bot delivers to buyer's Telegram chat.
    """
    id: int
    order_id: int
    order_code: str
    buyer_telegram_id: int
    otp_code: str
    forwarded_by_admin_id: int
    created_at: str


@dataclass
class Deposit:
    id: int
    deposit_code: str
    user_id: int
    user_telegram_id: int
    user_username: Optional[str]
    user_first_name: Optional[str]
    amount: float
    utr: str
    screenshot_file_id: Optional[str]
    status: str              # 'pending', 'approved', 'rejected', 'expired'
    admin_notes: Optional[str]
    reviewed_by_admin_id: Optional[int]
    created_at: str
    reviewed_at: Optional[str]
    expires_at: Optional[str] = None


@dataclass
class Strike:
    """Anti-abuse strike record."""
    id: int
    user_id: int
    telegram_id: int
    reason: str
    is_active: bool
    created_at: str


@dataclass
class Transaction:
    id: int
    tx_code: str
    user_id: int
    type: str
    amount: float
    balance_before: float
    balance_after: float
    reference_id: Optional[str]
    description: Optional[str]
    created_at: str


@dataclass
class AdminAction:
    id: int
    admin_telegram_id: int
    action_type: str
    target_type: Optional[str]
    target_id: Optional[str]
    details: Optional[str]
    created_at: str


@dataclass
class DashboardStats:
    total_users: int
    total_orders: int
    total_revenue: float
    pending_deposits_count: int
    pending_deposits_amount: float
    available_numbers_count: int
    sold_numbers_count: int
    country_breakdown: list   # list of (country_name, flag, available, sold)
