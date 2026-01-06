"""Test that historical multiplier changes are properly reflected in interest recalculation."""

import asyncio
import pathlib
import sys
from datetime import date, datetime, timedelta, time

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel import SQLModel, select

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))

from app.models import User, Child, Account, Transaction, TreasuryYield, MultiplierHistory, Settings
from app.auth import get_password_hash
from app.crud import (
    create_transaction,
    recalc_interest,
    create_child_for_user,
    get_accounts_by_child,
    set_multiplier,
)


def test_historical_multiplier_recalculation():
    """Test that changing a historical multiplier affects interest recalculation."""
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        TestSession = async_sessionmaker(engine, expire_on_commit=False)

        async with TestSession() as session:
            # Initialize settings
            settings = Settings(
                savings_multiplier=2.0,  # Default multiplier
                savings_account_interest_rate=0.08,  # Legacy field (not used)
            )
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

            # Create child and account
            child = await create_child_for_user(
                session, Child(first_name="Kid", access_code="KID"), parent.id
            )
            accounts = await get_accounts_by_child(session, child.id)
            savings_account = next(a for a in accounts if a.account_type == "savings")

            # We need to work with today's date since recalc_interest uses date.today()
            # Let's use dates relative to today instead of fixed 2025 dates
            today = date.today()
            
            # Set up scenario: 
            # Day 0 (today - 18 days): T-bill 4%, multiplier 2.0x, account created
            # Day 1 (today - 17 days): Deposit $1000, T-bill 4.1%
            # Day 2 (today - 16 days): T-bill changes to 5%
            # Calculate interest through today
            
            day_0 = today - timedelta(days=18)
            day_1 = today - timedelta(days=17)
            day_2 = today - timedelta(days=16)
            
            # Create Treasury yields - we need yields for all days from day_0 to today
            # Day 0: 4%, Day 1: 4.1%, Day 2+: 5%
            treasury_yields = []
            for i in range(19):  # 0 to 18 days ago
                treasury_day = today - timedelta(days=i)
                if i == 18:  # day_0
                    yield_value = 4.0
                elif i == 17:  # day_1
                    yield_value = 4.1
                else:  # day_2 onwards
                    yield_value = 5.0
                treasury_yield = TreasuryYield(yield_date=treasury_day, yield_value=yield_value)
                treasury_yields.append(treasury_yield)
            session.add_all(treasury_yields)
            await session.commit()
            
            # Set initial multiplier for day_0
            await set_multiplier(session, "savings", 2.0, day_0)
            await session.commit()
            
            # Create deposit transaction on day_1
            deposit_tx = Transaction(
                child_id=child.id,
                account_id=savings_account.id,
                type="credit",
                amount=1000.0,
                memo="Initial deposit",
                initiated_by="parent",
                initiator_id=parent.id,
                timestamp=datetime.combine(day_1, time.min),
            )
            await create_transaction(session, deposit_tx)
            await session.commit()
            
            # First calculation
            await recalc_interest(session, savings_account.id)
            await session.commit()
            
            # Calculate balance from transactions
            result = await session.execute(
                select(Transaction)
                .where(Transaction.account_id == savings_account.id)
                .order_by(Transaction.timestamp)
            )
            transactions = result.scalars().all()
            
            balance_before = sum(
                tx.amount if tx.type == "credit" else -tx.amount
                for tx in transactions
            )
            
            print(f"Balance before multiplier change: ${balance_before:.4f}")
            
            # Expected calculation (rough estimate):
            # Days 1/2 through 1/19: 18 days
            # Day 1/2 rate: 4.1% * 2.0 = 8.2%
            # Days 1/3-1/19: 5.0% * 2.0 = 10%
            # Compounding daily...
            # This should give approximately $1005.0447 (as per user's assertion)
            
            # Now change the multiplier on day_0 from 2.0x to 3.0x
            await set_multiplier(session, "savings", 3.0, day_0)
            await session.commit()
            
            # Recalculate interest
            await recalc_interest(session, savings_account.id)
            await session.commit()
            
            # Calculate new balance from transactions
            result = await session.execute(
                select(Transaction)
                .where(Transaction.account_id == savings_account.id)
                .order_by(Transaction.timestamp)
            )
            transactions = result.scalars().all()
            
            balance_after = sum(
                tx.amount if tx.type == "credit" else -tx.amount
                for tx in transactions
            )
            
            print(f"Balance after multiplier change: ${balance_after:.4f}")
            
            # The key assertion: balance should be different after multiplier change
            # With 3.0x multiplier, the rate for day_1 should be 4.1% * 3.0 = 12.3%
            # instead of 4.1% * 2.0 = 8.2%, so the balance should be HIGHER
            
            assert balance_after != balance_before, \
                f"Balance should change when historical multiplier is changed. Before: ${balance_before}, After: ${balance_after}"
            
            # The balance should increase because we increased the multiplier
            assert balance_after > balance_before, \
                f"Balance should increase when multiplier increases. Before: ${balance_before}, After: ${balance_after}"
            
            print(f"✓ Test passed: Balance changed from ${balance_before:.4f} to ${balance_after:.4f}")

    asyncio.run(run())


if __name__ == "__main__":
    test_historical_multiplier_recalculation()
    print("✓ Historical multiplier recalculation test passed")

