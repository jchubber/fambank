import os
"""Database configuration and helper utilities.

This module configures the asynchronous SQLAlchemy engine and provides
session helpers along with a small migration routine to keep the SQLite
schema in sync.  Comments are added throughout to clarify the startup
sequence and purpose of each block.
"""

import os
import logging
from sqlmodel import SQLModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)

DATABASE_URL = (
    "sqlite+aiosqlite:///./uncle_jons_bank.db"  # swap with Postgres URL if needed
)


# Control SQL echo via environment variable and route output through logging
SQL_ECHO = os.getenv("SQL_ECHO", "false").lower() == "true"
if SQL_ECHO:
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)

engine = create_async_engine(DATABASE_URL, echo=SQL_ECHO)

async_session = async_sessionmaker(engine, expire_on_commit=False)


async def create_db_and_tables() -> None:
    """Create initial tables and apply simple schema migrations."""

    from .models import (
        User,
        Child,
        ChildUserLink,
        Account,
        Transaction,
        WithdrawalRequest,
        Permission,
        UserPermissionLink,
        Settings,
        Message,
    )

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

        # --- simple schema migration for existing installs ---
        # add new fee-related columns if they don't exist yet
        pragma = "PRAGMA table_info('{table}')"

        async def has_column(table: str, column: str) -> bool:
            result = await conn.execute(text(pragma.format(table=table)))
            cols = [row[1] for row in result.fetchall()]
            return column in cols

        # Settings table columns
        if not await has_column("settings", "service_fee_amount"):
            await conn.execute(
                text(
                    "ALTER TABLE settings ADD COLUMN service_fee_amount FLOAT DEFAULT 0"
                )
            )
        if not await has_column("settings", "service_fee_is_percentage"):
            await conn.execute(
                text(
                    "ALTER TABLE settings ADD COLUMN service_fee_is_percentage BOOLEAN DEFAULT 0"
                )
            )
        if not await has_column("settings", "overdraft_fee_amount"):
            await conn.execute(
                text(
                    "ALTER TABLE settings ADD COLUMN overdraft_fee_amount FLOAT DEFAULT 0"
                )
            )
        if not await has_column("settings", "overdraft_fee_is_percentage"):
            await conn.execute(
                text(
                    "ALTER TABLE settings ADD COLUMN overdraft_fee_is_percentage BOOLEAN DEFAULT 0"
                )
            )
        if not await has_column("settings", "overdraft_fee_daily"):
            await conn.execute(
                text(
                    "ALTER TABLE settings ADD COLUMN overdraft_fee_daily BOOLEAN DEFAULT 0"
                )
            )
        if not await has_column("settings", "currency_symbol"):
            await conn.execute(
                text(
                    "ALTER TABLE settings ADD COLUMN currency_symbol VARCHAR DEFAULT '$'"
                )
            )
        if not await has_column("settings", "chores_ui_enabled"):
            await conn.execute(
                text(
                    "ALTER TABLE settings ADD COLUMN chores_ui_enabled BOOLEAN DEFAULT 1"
                )
            )
        if not await has_column("settings", "loans_ui_enabled"):
            await conn.execute(
                text(
                    "ALTER TABLE settings ADD COLUMN loans_ui_enabled BOOLEAN DEFAULT 1"
                )
            )
        if not await has_column("settings", "coupons_ui_enabled"):
            await conn.execute(
                text(
                    "ALTER TABLE settings ADD COLUMN coupons_ui_enabled BOOLEAN DEFAULT 1"
                )
            )
        if not await has_column("settings", "messages_ui_enabled"):
            await conn.execute(
                text(
                    "ALTER TABLE settings ADD COLUMN messages_ui_enabled BOOLEAN DEFAULT 1"
                )
            )

        # RecurringCharge table columns
        if not await has_column("recurringcharge", "type"):
            await conn.execute(
                text(
                    "ALTER TABLE recurringcharge ADD COLUMN type VARCHAR DEFAULT 'debit'"
                )
            )

        # Account table columns
        if not await has_column("account", "service_fee_last_charged"):
            await conn.execute(
                text(
                    "ALTER TABLE account ADD COLUMN service_fee_last_charged DATE"
                )
            )
        if not await has_column("account", "overdraft_fee_last_charged"):
            await conn.execute(
                text(
                    "ALTER TABLE account ADD COLUMN overdraft_fee_last_charged DATE"
                )
            )
        if not await has_column("account", "overdraft_fee_charged"):
            await conn.execute(
                text(
                    "ALTER TABLE account ADD COLUMN overdraft_fee_charged BOOLEAN DEFAULT 0"
                )
            )
        if not await has_column("account", "account_type"):
            await conn.execute(
                text(
                    "ALTER TABLE account ADD COLUMN account_type VARCHAR DEFAULT 'checking'"
                )
            )
        if not await has_column("account", "lockup_period_days"):
            await conn.execute(
                text(
                    "ALTER TABLE account ADD COLUMN lockup_period_days INTEGER"
                )
            )
        if not await has_column("transaction", "account_id"):
            await conn.execute(
                text(
                    'ALTER TABLE "transaction" ADD COLUMN account_id INTEGER'
                )
            )
        if not await has_column("withdrawalrequest", "account_type"):
            await conn.execute(
                text(
                    "ALTER TABLE withdrawalrequest ADD COLUMN account_type VARCHAR DEFAULT 'checking'"
                )
            )
        
        # Settings table migrations for new rate fields (must be done before account creation)
        if not await has_column("settings", "savings_account_interest_rate"):
            await conn.execute(
                text(
                    "ALTER TABLE settings ADD COLUMN savings_account_interest_rate FLOAT DEFAULT 0.01"
                )
            )
            # Copy existing default_interest_rate to savings_account_interest_rate if it exists
            if await has_column("settings", "default_interest_rate"):
                await conn.execute(
                    text("""
                        UPDATE settings 
                        SET savings_account_interest_rate = default_interest_rate 
                        WHERE savings_account_interest_rate = 0.01
                    """)
                )
        if not await has_column("settings", "college_savings_account_interest_rate"):
            await conn.execute(
                text(
                    "ALTER TABLE settings ADD COLUMN college_savings_account_interest_rate FLOAT DEFAULT 0.01"
                )
            )
            # Copy existing default_interest_rate to college_savings_account_interest_rate if it exists
            if await has_column("settings", "default_interest_rate"):
                await conn.execute(
                    text("""
                        UPDATE settings 
                        SET college_savings_account_interest_rate = default_interest_rate 
                        WHERE college_savings_account_interest_rate = 0.01
                    """)
                )
        if not await has_column("settings", "savings_account_lockup_period_days"):
            await conn.execute(
                text(
                    "ALTER TABLE settings ADD COLUMN savings_account_lockup_period_days INTEGER DEFAULT 30"
                )
            )
        
        # Migrate existing data: convert single accounts to checking accounts
        # and create savings/college_savings accounts for existing children
        if await has_column("account", "account_type"):
            # Check if we've already run the account creation migration
            result = await conn.execute(
                text("SELECT COUNT(*) FROM account WHERE account_type = 'savings'")
            )
            savings_count = result.scalar()
            if savings_count == 0:
                # Get settings values for interest rates and lockup period
                settings_result = await conn.execute(
                    text("SELECT savings_account_interest_rate, college_savings_account_interest_rate, savings_account_lockup_period_days FROM settings WHERE id = 1")
                )
                settings_row = settings_result.fetchone()
                if settings_row:
                    savings_rate = settings_row[0] if settings_row[0] is not None else 0.01
                    college_rate = settings_row[1] if settings_row[1] is not None else 0.01
                    lockup_days = settings_row[2] if settings_row[2] is not None else 30
                else:
                    # Fallback if settings don't exist yet
                    savings_rate = 0.01
                    college_rate = 0.01
                    lockup_days = 30
                
                # Get all existing children
                children_result = await conn.execute(text("SELECT id FROM child"))
                children = children_result.fetchall()
                
                for (child_id,) in children:
                    # Ensure existing account is marked as checking
                    await conn.execute(
                        text("UPDATE account SET account_type = 'checking' WHERE child_id = :child_id AND (account_type IS NULL OR account_type = '')"),
                        {"child_id": child_id}
                    )
                    
                    # Check if child already has all three account types
                    accounts_result = await conn.execute(
                        text("SELECT account_type FROM account WHERE child_id = :child_id"),
                        {"child_id": child_id}
                    )
                    existing_types = {row[0] for row in accounts_result.fetchall() if row[0]}
                    
                    # Create savings account if missing
                    if "savings" not in existing_types:
                        await conn.execute(
                            text("""
                                INSERT INTO account (child_id, account_type, interest_rate, lockup_period_days, balance, 
                                penalty_interest_rate, cd_penalty_rate, last_interest_applied, total_interest_earned,
                                service_fee_last_charged, overdraft_fee_last_charged, overdraft_fee_charged)
                                VALUES (:child_id, 'savings', :rate, :lockup, 0.0, 0.02, 0.1, NULL, 0.0, NULL, NULL, 0)
                            """),
                            {
                                "child_id": child_id,
                                "rate": savings_rate,
                                "lockup": lockup_days
                            }
                        )
                    
                    # Create college_savings account if missing
                    if "college_savings" not in existing_types:
                        await conn.execute(
                            text("""
                                INSERT INTO account (child_id, account_type, interest_rate, lockup_period_days, balance,
                                penalty_interest_rate, cd_penalty_rate, last_interest_applied, total_interest_earned,
                                service_fee_last_charged, overdraft_fee_last_charged, overdraft_fee_charged)
                                VALUES (:child_id, 'college_savings', :rate, NULL, 0.0, 0.02, 0.1, NULL, 0.0, NULL, NULL, 0)
                            """),
                            {
                                "child_id": child_id,
                                "rate": college_rate
                            }
                        )
                
                # Backfill account_id in transactions to point to checking accounts
                await conn.execute(
                    text("""
                        UPDATE "transaction" 
                        SET account_id = (
                            SELECT id FROM account 
                            WHERE account.child_id = "transaction".child_id 
                            AND account.account_type = 'checking'
                            LIMIT 1
                        )
                        WHERE account_id IS NULL
                    """)
                )


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
