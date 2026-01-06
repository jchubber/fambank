"""Tests for Treasury yield fetching and multiplier management."""

from datetime import date, timedelta

import asyncio
import pathlib
import sys

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel import SQLModel

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))

from app.models import User, Child, TreasuryYield, MultiplierHistory, Settings
from app.crud import (
    create_child_for_user,
    fetch_treasury_yield,
    get_treasury_yield_for_date,
    sync_treasury_yields,
    set_multiplier,
    get_multiplier_for_date,
    get_interest_rate_for_date,
    get_settings,
)
from app.auth import get_password_hash


def test_treasury_yield_storage():
    """Test that Treasury yields can be stored and retrieved."""
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        TestSession = async_sessionmaker(engine, expire_on_commit=False)

        async with TestSession() as session:
            # Create a test Treasury yield entry
            test_date = date.today()
            treasury_yield = TreasuryYield(
                date=test_date,
                yield_value=4.11,  # 4.11%
            )
            session.add(treasury_yield)
            await session.commit()
            await session.refresh(treasury_yield)

            # Retrieve it
            retrieved = await get_treasury_yield_for_date(session, test_date)
            assert retrieved == 0.0411, f"Expected 0.0411, got {retrieved}"

            # Test with missing date (should use most recent prior)
            future_date = test_date + timedelta(days=1)
            retrieved_future = await get_treasury_yield_for_date(session, future_date)
            assert retrieved_future == 0.0411, "Should use most recent prior date"

    asyncio.run(run())


def test_multiplier_management():
    """Test multiplier setting and retrieval."""
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        TestSession = async_sessionmaker(engine, expire_on_commit=False)

        async with TestSession() as session:
            # Initialize settings
            settings = Settings()
            session.add(settings)
            await session.commit()

            # Set multiplier
            await set_multiplier(session, "savings", 2.0)
            
            # Retrieve it
            multiplier = await get_multiplier_for_date(session, "savings", date.today())
            assert multiplier == 2.0, f"Expected 2.0, got {multiplier}"

            # Change multiplier
            await set_multiplier(session, "savings", 3.0)
            multiplier = await get_multiplier_for_date(session, "savings", date.today())
            assert multiplier == 3.0, f"Expected 3.0, got {multiplier}"

            # Test historical multiplier
            yesterday = date.today() - timedelta(days=1)
            multiplier_yesterday = await get_multiplier_for_date(session, "savings", yesterday)
            assert multiplier_yesterday == 2.0, "Should get historical multiplier"

    asyncio.run(run())


def test_interest_rate_calculation():
    """Test that interest rates are calculated as Treasury Yield × Multiplier."""
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        TestSession = async_sessionmaker(engine, expire_on_commit=False)

        async with TestSession() as session:
            # Initialize settings
            settings = Settings()
            session.add(settings)
            await session.commit()

            # Create Treasury yield
            test_date = date.today()
            treasury_yield = TreasuryYield(
                date=test_date,
                yield_value=4.11,  # 4.11%
            )
            session.add(treasury_yield)
            await session.commit()

            # Set multiplier
            await set_multiplier(session, "savings", 2.0)

            # Get interest rate (should be 4.11% × 2.0 = 8.22%)
            interest_rate, penalty_rate = await get_interest_rate_for_date(
                session, "savings", test_date
            )
            expected_rate = 0.0411 * 2.0  # 0.0822
            assert abs(interest_rate - expected_rate) < 0.0001, \
                f"Expected {expected_rate}, got {interest_rate}"

    asyncio.run(run())


if __name__ == "__main__":
    test_treasury_yield_storage()
    print("✓ Treasury yield storage test passed")
    
    test_multiplier_management()
    print("✓ Multiplier management test passed")
    
    test_interest_rate_calculation()
    print("✓ Interest rate calculation test passed")
    
    print("\nAll tests passed!")

