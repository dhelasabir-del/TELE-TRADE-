"""FSM states for phone number marketplace."""

from aiogram.fsm.state import State, StatesGroup


class DepositStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_utr = State()
    waiting_for_screenshot = State()


class AddCountryStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_code = State()
    waiting_for_flag = State()
    waiting_for_price = State()
    waiting_for_description = State()


class EditCountryStates(StatesGroup):
    waiting_for_field = State()
    waiting_for_value = State()

    # Convenience alias used in inventory.py imports
    @classmethod
    def value_state(cls):
        return cls.waiting_for_value


class AddNumberStates(StatesGroup):
    waiting_for_country = State()
    waiting_for_phone = State()
    waiting_for_2fa = State()
    waiting_for_session = State()
    waiting_for_tg_code = State()
    waiting_for_tg_2fa = State()
    waiting_for_notes = State()


class BulkAddNumberStates(StatesGroup):
    waiting_for_country = State()
    waiting_for_data = State()


class ForwardOtpStates(StatesGroup):
    waiting_for_order_code = State()
    waiting_for_otp = State()


class RejectDepositStates(StatesGroup):
    waiting_for_reason = State()


class AdjustBalanceStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_reason = State()


class SearchOrderStates(StatesGroup):
    waiting_for_query = State()


class SearchUserStates(StatesGroup):
    waiting_for_query = State()
