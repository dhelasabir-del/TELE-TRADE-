"""End-to-End System & Business Logic Verification Test."""

import asyncio
import sys
from bot.database.database import init_database
from bot.database.queries import (
    get_or_create_user, get_user_by_telegram_id, create_deposit_request,
    approve_deposit, reject_deposit, check_utr_exists, execute_purchase,
    get_products_by_category, get_all_categories, get_user_orders,
    search_orders, get_admin_dashboard_stats, adjust_user_balance,
    set_user_blocked_status, DuplicateUtrError, InsufficientFundsError,
    OutOfStockError
)
from bot.services.qr_service import QRService

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


async def run_tests():
    print("=" * 60)
    print("RUNNING RYUS MARKET E2E VALIDATION SUITE")
    print("=" * 60)

    await init_database()

    # Test 1: User Registration
    test_tg_id = 999888777
    user = await get_or_create_user(
        telegram_id=test_tg_id,
        username="test_buyer",
        first_name="Test Buyer"
    )
    assert user is not None, "User creation failed"
    assert user.internal_id.startswith("USR-"), f"Invalid internal ID: {user.internal_id}"
    print(f" [PASS] User registration: {user.internal_id} (@{user.username})")

    # Test 2: Deposit Submission & UTR Duplicate Protection
    test_utr = "TESTUTR999999"
    deposit = await create_deposit_request(
        user_id=user.id,
        amount=500.0,
        utr=test_utr,
        screenshot_file_id="sample_file_id_123"
    )
    assert deposit.status == "pending", "Deposit status should be pending"
    assert deposit.amount == 500.0, "Deposit amount mismatch"
    print(f" [PASS] Deposit creation: {deposit.deposit_code} for ₹{deposit.amount}")

    try:
        await create_deposit_request(user_id=user.id, amount=500.0, utr=test_utr)
        assert False, "Should have raised DuplicateUtrError"
    except DuplicateUtrError:
        print(" [PASS] Duplicate UTR prevention verified.")

    # Test 3: Admin Approval of Deposit
    approved_dep = await approve_deposit(
        deposit_id=deposit.id,
        admin_telegram_id=123456789,
        admin_notes="Verified via test suite"
    )
    assert approved_dep.status == "approved", "Deposit was not approved"

    updated_user = await get_user_by_telegram_id(test_tg_id)
    assert updated_user.wallet_balance == 500.0, f"Expected 500.0 balance, got {updated_user.wallet_balance}"
    print(f" [PASS] Deposit approval & balance update: ₹{updated_user.wallet_balance:.2f}")

    # Test 4: Product Browsing & Stock Check
    cats = await get_all_categories()
    assert len(cats) > 0, "No categories available"
    prods = await get_products_by_category(cats[0].id)
    assert len(prods) > 0, "No products available in category"
    prod = prods[0]
    initial_stock = prod.stock_count
    assert initial_stock > 0, "Product has 0 stock"
    print(f" [PASS] Product fetched: '{prod.name}' (Price: ₹{prod.price}, Stock: {initial_stock})")

    # Test 5: Atomic Purchase Execution
    order, delivery_data = await execute_purchase(
        user_telegram_id=test_tg_id,
        product_id=prod.id
    )
    assert order.order_code.startswith("ORD-"), f"Invalid order code: {order.order_code}"
    assert order.status == "completed", "Order not completed"
    assert delivery_data != "", "Delivery data should not be empty"

    user_after_buy = await get_user_by_telegram_id(test_tg_id)
    expected_balance = round(500.0 - prod.price, 2)
    assert user_after_buy.wallet_balance == expected_balance, f"Expected balance {expected_balance}, got {user_after_buy.wallet_balance}"

    prods_after = await get_products_by_category(cats[0].id)
    prod_after = next(p for p in prods_after if p.id == prod.id)
    assert prod_after.stock_count == initial_stock - 1, "Stock was not decremented"
    print(f" [PASS] Atomic purchase successful: Order #{order.order_code}, Balance: ₹{user_after_buy.wallet_balance}, Delivered: {delivery_data[:20]}...")

    # Test 6: Order History & Search
    user_orders = await get_user_orders(user.id)
    assert len(user_orders) >= 1, "User order not found in history"
    searched = await search_orders(query_type="order_id", query_value=order.order_code)
    assert len(searched) == 1, "Order search by code failed"
    print(f" [PASS] Order lookup and search verified: {searched[0].order_code}")

    # Test 7: Dashboard Operational Stats
    stats = await get_admin_dashboard_stats()
    assert stats.total_users >= 1, "Total users stat mismatch"
    assert stats.total_orders >= 1, "Total orders stat mismatch"
    assert stats.total_revenue >= prod.price, "Total revenue stat mismatch"
    print(f" [PASS] Dashboard stats: Users: {stats.total_users}, Orders: {stats.total_orders}, Revenue: ₹{stats.total_revenue:.2f}")

    # Test 8: QR Code Generator
    qr_stream = QRService.generate_upi_qr(amount=100.0)
    assert qr_stream.getbuffer().nbytes > 0, "QR code generation failed"
    print(f" [PASS] UPI QR code generated successfully ({qr_stream.getbuffer().nbytes} bytes)")

    # Test 9: Admin Balance Adjustment & Block
    bal_before, bal_after = await adjust_user_balance(
        user_id=user.id,
        amount=50.0,
        direction="credit",
        reason="Test bonus",
        admin_telegram_id=123456789
    )
    assert bal_after == bal_before + 50.0, "Balance credit failed"
    await set_user_blocked_status(user.id, is_blocked=True)
    blocked_user = await get_user_by_telegram_id(test_tg_id)
    assert blocked_user.is_blocked is True, "User should be blocked"
    await set_user_blocked_status(user.id, is_blocked=False)
    print(" [PASS] Admin balance adjustment & user blocking verified.")

    print("=" * 60)
    print("ALL 9 TEST SUITES PASSED FLAWLESSLY!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_tests())
