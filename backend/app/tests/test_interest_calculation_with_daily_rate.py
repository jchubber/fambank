"""Test that interest calculation uses daily rates correctly."""

import asyncio
import pathlib
import sys
from datetime import date, datetime, timedelta, time

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel import SQLModel, select

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))

from app.models import User, Child, Account, Transaction, TreasuryYield, Settings
from app.auth import get_password_hash
from app.crud import (
    create_transaction,
    recalc_interest,
    create_child_for_user,
    get_accounts_by_child,
    set_multiplier,
)


def test_interest_with_daily_rate_conversion():
    """Test that interest is calculated using daily rates, not annual rates."""
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        TestSession = async_sessionmaker(engine, expire_on_commit=False)

        async with TestSession() as session:
            # Initialize settings
            settings = Settings(savings_multiplier=1.5)
            session.add(settings)
            await session.commit()

            # Create parent and child
            parent = User(
                name="Parent",
                email="parent@example.com",
                password_hash=get_password_hash("pass"),
                role="parent",
            )
            session.add(parent)
            await session.commit()
            await session.refresh(parent)

            child = await create_child_for_user(
                session, Child(first_name="Kid", access_code="KID"), parent.id
            )
            accounts = await get_accounts_by_child(session, child.id)
            savings_account = next(a for a in accounts if a.account_type == "savings")

            today = date.today()
            deposit_date = today - timedelta(days=365)  # Exactly 1 year ago
            
            # Set up: T-bill 4%, multiplier 1.5x = 6% annual rate
            # Daily rate should be: ((1 + 0.06)^(1/365)) - 1 ≈ 0.0001596
            # Create Treasury yields for all days from deposit_date to today-1 (all at 4%)
            # Note: We go to today-1 because today might already have a yield
            treasury_yields = []
            current_date = deposit_date
            while current_date < today:
                treasury = TreasuryYield(yield_date=current_date, yield_value=4.0)
                treasury_yields.append(treasury)
                current_date += timedelta(days=1)
            session.add_all(treasury_yields)
            await session.commit()
            
            # Set multiplier to 1.5x
            await set_multiplier(session, "savings", 1.5, deposit_date)
            await session.commit()
            
            # Deposit $1000 exactly 365 days ago
            deposit_tx = Transaction(
                child_id=child.id,
                account_id=savings_account.id,
                type="credit",
                amount=1000.0,
                memo="Initial deposit",
                initiated_by="parent",
                initiator_id=parent.id,
                timestamp=datetime.combine(deposit_date, time.min),
            )
            await create_transaction(session, deposit_tx)
            await session.commit()
            
            # Calculate interest
            await recalc_interest(session, savings_account.id)
            await session.commit()
            
            # Calculate final balance from transactions
            result = await session.execute(
                select(Transaction)
                .where(Transaction.account_id == savings_account.id)
                .order_by(Transaction.timestamp)
            )
            transactions = result.scalars().all()
            
            final_balance = sum(
                tx.amount if tx.type == "credit" else -tx.amount
                for tx in transactions
            )
            
            # With 6% annual rate, after 365 days of daily compounding:
            # Expected: $1000 * (1 + 0.06) = $1060.00
            expected_balance = 1000.0 * 1.06
            
            print(f"Initial deposit: $1000.00")
            print(f"Annual rate: 4% * 1.5 = 6%")
            print(f"Days: 365")
            print(f"Final balance: ${final_balance:.2f}")
            print(f"Expected balance: ${expected_balance:.2f}")
            
            # Allow some tolerance for floating point precision
            tolerance = 0.10  # Allow $0.10 difference
            assert abs(final_balance - expected_balance) < tolerance, \
                f"Expected balance ~${expected_balance:.2f}, got ${final_balance:.2f}. " \
                f"Difference: ${abs(final_balance - expected_balance):.2f}"
            
            print(f"✓ Test passed: Balance is within expected range")
            
            # Also verify that using annual rate directly would give wrong result
            # If we mistakenly used annual rate: $1000 * 0.06 * 365 / 365 = $60/year = wrong
            # The correct way compounds daily, so we get $60 total but calculated correctly

    asyncio.run(run())


if __name__ == "__main__":
    test_interest_with_daily_rate_conversion()
    print("\n✓ Interest calculation with daily rate conversion test passed!")

