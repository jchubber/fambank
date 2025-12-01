"""Regression test for recalculating interest after rate changes."""

from datetime import datetime, timedelta

import asyncio
import pathlib
import sys

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel import SQLModel

sys.path.append(str(pathlib.Path(__file__).resolve().parents[2]))

from app.models import User, Child, Transaction
from app.crud import (
    create_child_for_user,
    create_transaction,
    recalc_interest,
    set_interest_rate,
    get_transactions_by_child,
)
from app.auth import get_password_hash


def test_interest_rate_change_not_retroactive():
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        TestSession = async_sessionmaker(engine, expire_on_commit=False)

        async with TestSession() as session:
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

            from app.crud import get_accounts_by_child
            accounts = await get_accounts_by_child(session, child.id)
            savings_account = next(a for a in accounts if a.account_type == "savings")

            start_time = datetime.utcnow() - timedelta(days=5)
            await create_transaction(
                session,
                Transaction(
                    child_id=child.id,
                    account_id=savings_account.id,
                    type="credit",
                    amount=100,
                    memo="Deposit",
                    initiated_by="parent",
                    initiator_id=parent.id,
                    timestamp=start_time,
                ),
            )

            # Get initial rate
            initial_rate = savings_account.interest_rate
            
            # Create initial history entry by setting rate to a different value first,
            # then setting it back to initial (this creates history)
            # Or set it to initial explicitly if different from default
            if initial_rate != 0.01:
                await set_interest_rate(session, child.id, 0.01, "savings")
                await set_interest_rate(session, child.id, initial_rate, "savings")
            else:
                # Set to something different first to create history, then back to initial
                await set_interest_rate(session, child.id, 0.015, "savings")
                await set_interest_rate(session, child.id, initial_rate, "savings")
            
            await recalc_interest(session, savings_account.id)
            txs_before = await get_transactions_by_child(session, child.id)
            interest_before = [t.amount for t in txs_before if t.memo == "Interest"]

            # Change rate - this creates a history entry for today
            await set_interest_rate(session, child.id, 0.02, "savings")
            await recalc_interest(session, savings_account.id)
            txs_after = await get_transactions_by_child(session, child.id)
            interest_after = [t.amount for t in txs_after if t.memo == "Interest"]

            # With historical rate tracking, past days should use the rate from history
            # Since we created a history entry for the initial rate (backdated to account creation),
            # and a new entry for today with the new rate, past days should use the initial rate
            # and today should use the new rate. But since the transaction was 5 days ago,
            # all interest calculations should use the initial rate, so amounts should be the same.
            # However, if the rate change entry is dated today, and we're calculating interest
            # for days before today, we should use the rate from before the change.
            # The test expects non-retroactive changes, so past interest should remain the same.
            assert interest_after == interest_before

    asyncio.run(run())
