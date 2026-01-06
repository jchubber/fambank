"""Asynchronous CRUD helpers for the application's data models.

Each function in this module encapsulates a specific database operation
using SQLModel and SQLAlchemy.  Centralizing the logic keeps route
handlers light and makes behavior easier to test.
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, delete
from sqlalchemy.orm import selectinload
from sqlalchemy import func, case
from datetime import datetime, date, timedelta, time
from app.models import (
    User,
    Child,
    ChildUserLink,
    Transaction,
    WithdrawalRequest,
    Account,
    CertificateDeposit,
    RecurringCharge,
    Chore,
    Permission,
    UserPermissionLink,
    Settings,
    ShareCode,
    Loan,
    LoanTransaction,
    Message,
    Coupon,
    CouponRedemption,
    EducationModule,
    QuizQuestion,
    Badge,
    ChildBadge,
    InterestRateHistory,
    TreasuryYield,
    MultiplierHistory,
)
from app.auth import get_password_hash, get_child_by_id
from app.acl import get_default_permissions_for_role, ALL_PERMISSIONS
import uuid
import os
import logging
import httpx

logger = logging.getLogger(__name__)

# FRED API configuration
FRED_API_KEY = os.getenv("FRED_API_KEY")
FRED_API_BASE_URL = "https://api.stlouisfed.org/fred"
FRED_SERIES_ID = "DGS1"  # 1-Year Treasury Constant Maturity Rate

if not FRED_API_KEY:
    logger.warning("FRED_API_KEY environment variable not set. Treasury yield fetching will be disabled. Get a free API key at https://fred.stlouisfed.org/docs/api/api_key.html")


async def ensure_permissions_exist(db: AsyncSession, names: list[str]) -> None:
    """Ensure that a set of permission records exists in the database."""

    for name in names:
        result = await db.execute(
            select(Permission).where(Permission.name == name)
        )
        perm = result.scalar_one_or_none()
        if not perm:
            db.add(Permission(name=name))
    await db.commit()


async def assign_permissions_by_names(
    db: AsyncSession, user: User, names: list[str]
) -> None:
    """Assign named permissions to a user if not already granted."""
    for name in names:
        result = await db.execute(
            select(Permission).where(Permission.name == name)
        )
        perm = result.scalar_one_or_none()
        if perm:
            link_result = await db.execute(
                select(UserPermissionLink)
                    .where(
                        UserPermissionLink.user_id == user.id,
                        UserPermissionLink.permission_id == perm.id,
                    )
            )
            link = link_result.scalar_one_or_none()
            if not link:
                db.add(
                    UserPermissionLink(user_id=user.id, permission_id=perm.id)
                )
    await db.commit()


async def remove_permissions_by_names(
    db: AsyncSession, user: User, names: list[str]
) -> None:
    """Remove the specified permissions from a user."""
    for name in names:
        result = await db.execute(
            select(Permission).where(Permission.name == name)
        )
        perm = result.scalar_one_or_none()
        if perm:
            await db.execute(
                delete(UserPermissionLink)
                .where(
                    UserPermissionLink.user_id == user.id,
                    UserPermissionLink.permission_id == perm.id,
                )
            )
    await db.commit()


async def get_all_permissions(db: AsyncSession) -> list[Permission]:
    """Return all permissions ordered alphabetically."""

    result = await db.execute(select(Permission).order_by(Permission.name))
    return result.scalars().all()


async def get_settings(db: AsyncSession) -> Settings:
    """Fetch the singleton settings record, creating it if necessary."""
    result = await db.execute(select(Settings).where(Settings.id == 1))
    settings = result.scalar_one_or_none()
    if not settings:
        settings = Settings()
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


async def save_settings(db: AsyncSession, settings: Settings) -> Settings:
    """Persist settings changes and return the refreshed object."""

    db.add(settings)
    await db.commit()
    await db.refresh(settings)
    return settings


async def create_user(db: AsyncSession, user: User):
    """Create a new user, hashing the password and assigning defaults."""

    if not user.password_hash.startswith("$2b$"):
        user.password_hash = get_password_hash(user.password_hash)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    defaults = get_default_permissions_for_role(user.role)
    if defaults:
        await assign_permissions_by_names(db, user, defaults)
    return user


async def get_user_by_email(db: AsyncSession, email: str):
    """Return a user by email or ``None`` if not found."""
    result = await db.execute(
        select(User)
        .where(User.email == email)
        .options(selectinload(User.permissions))
    )
    return result.scalar_one_or_none()


async def get_user(db: AsyncSession, user_id: int) -> User | None:
    """Load a user by primary key."""
    result = await db.execute(
        select(User)
        .where(User.id == user_id)
        .options(selectinload(User.permissions))
    )
    return result.scalar_one_or_none()


async def get_all_users(db: AsyncSession) -> list[User]:
    """Return all users with permissions eagerly loaded."""

    result = await db.execute(
        select(User).options(selectinload(User.permissions)).order_by(User.id)
    )
    return result.scalars().all()


async def save_user(db: AsyncSession, user: User) -> User:
    """Persist changes to an existing user."""

    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user: User) -> None:
    """Remove a user from the database."""

    await db.delete(user)
    await db.commit()


async def create_child(db: AsyncSession, child: Child):
    """Persist a new child record."""

    db.add(child)
    await db.commit()
    await db.refresh(child)
    return child


async def create_child_for_user(db: AsyncSession, child: Child, user_id: int):
    """Create a child, associated accounts (checking, savings, college_savings), and link in a single transaction."""
    settings = await get_settings(db)
    db.add(child)
    await db.flush()  # ensure child.id is populated

    # Create checking account (rates are now global, retrieved from Settings/history)
    checking_account = Account(
        child_id=child.id,
        account_type="checking",
        cd_penalty_rate=settings.default_cd_penalty_rate,
    )
    db.add(checking_account)

    # Create savings account (with lockup period, rates are now global)
    savings_account = Account(
        child_id=child.id,
        account_type="savings",
        cd_penalty_rate=settings.default_cd_penalty_rate,
        lockup_period_days=settings.savings_account_lockup_period_days,
    )
    db.add(savings_account)

    # Create college savings account (rates are now global)
    college_savings_account = Account(
        child_id=child.id,
        account_type="college_savings",
        cd_penalty_rate=settings.default_cd_penalty_rate,
    )
    db.add(college_savings_account)

    link = ChildUserLink(
        user_id=user_id,
        child_id=child.id,
        permissions=ALL_PERMISSIONS,
        is_owner=True,
    )
    db.add(link)

    await db.commit()
    await db.refresh(child)
    return child


async def get_children_by_user(db: AsyncSession, user_id: int):
    """Return all children associated with a given parent user."""
    query = (
        select(Child)
        .join(ChildUserLink)
        .where(ChildUserLink.user_id == user_id)
    )
    result = await db.execute(query)
    return result.scalars().all()


async def get_child_by_access_code(db: AsyncSession, access_code: str):
    """Return a child by their unique access code."""
    result = await db.execute(
        select(Child).where(Child.access_code == access_code)
    )
    return result.scalars().first()


async def get_child(db: AsyncSession, child_id: int) -> Child | None:
    """Fetch a child by id or ``None`` if not found."""
    result = await db.execute(select(Child).where(Child.id == child_id))
    return result.scalar_one_or_none()


async def get_all_children(db: AsyncSession) -> list[Child]:
    """Return all children ordered by id."""

    result = await db.execute(select(Child).order_by(Child.id))
    return result.scalars().all()


async def save_child(db: AsyncSession, child: Child) -> Child:
    """Persist changes to a child record."""

    db.add(child)
    await db.commit()
    await db.refresh(child)
    return child


async def delete_child(db: AsyncSession, child: Child) -> None:
    """Remove a child record."""
    await db.execute(
        delete(Transaction).where(Transaction.child_id == child.id)
    )
    await db.execute(
        delete(Account).where(Account.child_id == child.id)
    )
    await db.execute(
        delete(ChildUserLink).where(ChildUserLink.child_id == child.id)
    )
    await db.delete(child)
    await db.commit()


async def set_child_frozen(
    db: AsyncSession, child_id: int, frozen: bool
) -> Child:
    """Toggle whether a child's account is frozen."""
    result = await db.execute(select(Child).where(Child.id == child_id))
    child = result.scalar_one_or_none()
    if not child:
        raise ValueError("Child not found")
    child.account_frozen = frozen
    db.add(child)
    await db.commit()
    await db.refresh(child)
    return child


async def get_child_user_link(
    db: AsyncSession, user_id: int, child_id: int
) -> ChildUserLink | None:
    result = await db.execute(
        select(ChildUserLink).where(
            ChildUserLink.user_id == user_id,
            ChildUserLink.child_id == child_id,
        )
    )
    return result.scalar_one_or_none()


async def link_child_to_user(
    db: AsyncSession, child_id: int, user_id: int, permissions: list[str], is_owner=False
) -> ChildUserLink:
    link = ChildUserLink(
        user_id=user_id,
        child_id=child_id,
        permissions=permissions,
        is_owner=is_owner,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return link


async def remove_child_link(db: AsyncSession, child_id: int, user_id: int) -> None:
    await db.execute(
        delete(ChildUserLink).where(
            ChildUserLink.child_id == child_id,
            ChildUserLink.user_id == user_id,
        )
    )
    await db.commit()


async def get_parents_for_child(
    db: AsyncSession, child_id: int
) -> list[ChildUserLink]:
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(ChildUserLink)
        .where(ChildUserLink.child_id == child_id)
        .options(selectinload(ChildUserLink.user))
    )
    return result.scalars().all()


async def create_share_code(
    db: AsyncSession, child_id: int, creator_id: int, permissions: list[str]
) -> ShareCode:
    code = uuid.uuid4().hex[:8]
    share = ShareCode(
        code=code, child_id=child_id, created_by=creator_id, permissions=permissions
    )
    db.add(share)
    await db.commit()
    await db.refresh(share)
    return share


async def get_share_code(db: AsyncSession, code: str) -> ShareCode | None:
    result = await db.execute(select(ShareCode).where(ShareCode.code == code))
    return result.scalar_one_or_none()


async def mark_share_code_used(
    db: AsyncSession, share: ShareCode, user_id: int
) -> ShareCode:
    share.used_by = user_id
    db.add(share)
    await db.commit()
    await db.refresh(share)
    return share


async def get_accounts_by_child(
    db: AsyncSession, child_id: int
) -> list[Account]:
    """Return all accounts associated with a child."""
    result = await db.execute(
        select(Account).where(Account.child_id == child_id)
    )
    return result.scalars().all()


async def get_account_by_child_and_type(
    db: AsyncSession, child_id: int, account_type: str
) -> Account | None:
    """Return a specific account type for a child."""
    result = await db.execute(
        select(Account).where(
            Account.child_id == child_id,
            Account.account_type == account_type
        )
    )
    return result.scalar_one_or_none()


async def get_checking_account_by_child(
    db: AsyncSession, child_id: int
) -> Account | None:
    """Return the checking account for a child (for backward compatibility)."""
    return await get_account_by_child_and_type(db, child_id, "checking")


async def get_account(db: AsyncSession, account_id: int) -> Account | None:
    """Get an account by its ID."""
    return await db.get(Account, account_id)


async def get_account_by_child(
    db: AsyncSession, child_id: int
) -> Account | None:
    """Return the checking account associated with a child (backward compatibility)."""
    return await get_checking_account_by_child(db, child_id)


async def get_all_accounts(db: AsyncSession) -> list[Account]:
    """Return all account records."""

    result = await db.execute(select(Account))
    return result.scalars().all()


async def get_interest_rate_for_date(
    db: AsyncSession, account_type: str, target_date: date
) -> tuple[float, float]:
    """Get the interest rate and penalty interest rate that were effective on a given date for an account type.
    
    For savings and college_savings accounts, calculates interest rate as: Treasury Yield × Multiplier.
    Penalty rates remain manual (from InterestRateHistory or Settings).
    
    Returns (interest_rate, penalty_interest_rate) tuple.
    """
    # Get penalty rate from history or Settings (penalty rates remain manual)
    penalty_result = await db.execute(
        select(InterestRateHistory)
        .where(
            InterestRateHistory.account_type == account_type,
            InterestRateHistory.date <= target_date,
        )
        .order_by(InterestRateHistory.date.desc(), InterestRateHistory.created_at.desc())
        .limit(1)
    )
    penalty_history = penalty_result.scalar_one_or_none()
    
    settings = await get_settings(db)
    
    # Get penalty rate
    if penalty_history:
        penalty_rate = penalty_history.penalty_interest_rate
    else:
        if account_type == "savings":
            penalty_rate = settings.savings_penalty_interest_rate
        elif account_type == "college_savings":
            penalty_rate = settings.college_savings_penalty_interest_rate
        elif account_type == "checking":
            penalty_rate = settings.checking_penalty_interest_rate
        else:
            penalty_rate = 0.02  # Default fallback
    
    # Calculate interest rate based on account type
    if account_type in ("savings", "college_savings"):
        # Calculate as Treasury Yield × Multiplier
        try:
            treasury_yield = await get_treasury_yield_for_date(db, target_date)
            multiplier = await get_multiplier_for_date(db, account_type, target_date)
            interest_rate = treasury_yield * multiplier
            
            # Cache the calculated rate in InterestRateHistory for performance
            # Check if we already have a cached entry for this date
            cached_result = await db.execute(
                select(InterestRateHistory)
                .where(
                    InterestRateHistory.account_type == account_type,
                    InterestRateHistory.date == target_date,
                )
                .limit(1)
            )
            cached_entry = cached_result.scalar_one_or_none()
            
            if cached_entry:
                # Update existing cached entry
                if abs(cached_entry.interest_rate - interest_rate) > 0.0001:  # Only update if significantly different
                    cached_entry.interest_rate = interest_rate
                    cached_entry.penalty_interest_rate = penalty_rate
                    db.add(cached_entry)
                    await db.commit()
            else:
                # Create new cached entry
                cached_entry = InterestRateHistory(
                    account_type=account_type,
                    date=target_date,
                    interest_rate=interest_rate,
                    penalty_interest_rate=penalty_rate,
                )
                db.add(cached_entry)
                await db.commit()
            
            return (interest_rate, penalty_rate)
        except Exception as e:
            logger.warning(f"Error calculating Treasury-based rate for {account_type} on {target_date}: {e}, falling back to Settings")
            # Fallback to Settings defaults
            if account_type == "savings":
                return (settings.savings_account_interest_rate, penalty_rate)
            elif account_type == "college_savings":
                return (settings.college_savings_account_interest_rate, penalty_rate)
    elif account_type == "checking":
        return (0.0, penalty_rate)
    
    # Default fallback
    return (0.01, penalty_rate)


async def get_current_rate_for_account_type(
    db: AsyncSession, account_type: str
) -> tuple[float, float]:
    """Get the current interest rate and penalty rate for an account type.
    
    Returns (interest_rate, penalty_interest_rate) tuple from history or Settings defaults.
    """
    today = date.today()
    return await get_interest_rate_for_date(db, account_type, today)


async def set_global_interest_rate(
    db: AsyncSession, account_type: str, rate: float
) -> None:
    """Update the global interest rate for an account type (savings or college_savings only)."""
    if account_type not in ("savings", "college_savings"):
        raise ValueError("Interest rates only apply to savings and college_savings accounts")
    
    today = date.today()
    
    # Get current rate to check if it changed
    current_rate, current_penalty = await get_current_rate_for_account_type(db, account_type)
    
    # Only create history entry if rate actually changed
    if current_rate != rate:
        # Check if we already have an entry for today
        existing_result = await db.execute(
            select(InterestRateHistory)
            .where(
                InterestRateHistory.account_type == account_type,
                InterestRateHistory.date == today,
            )
            .order_by(InterestRateHistory.created_at.desc())
            .limit(1)
        )
        existing_entry = existing_result.scalar_one_or_none()
        
        if existing_entry:
            # Update existing entry
            existing_entry.interest_rate = rate
        else:
            # Check if this is the first history entry for this account type
            first_history_result = await db.execute(
                select(InterestRateHistory)
                .where(InterestRateHistory.account_type == account_type)
                .order_by(InterestRateHistory.date)
                .limit(1)
            )
            first_history = first_history_result.scalar_one_or_none()
            
            if not first_history:
                # This is the first history entry - create entry for OLD rate backdated
                history_date = today - timedelta(days=1)
                
                # Create history entry for the OLD rate (backdated)
                old_history = InterestRateHistory(
                    account_type=account_type,
                    date=history_date,
                    interest_rate=current_rate,
                    penalty_interest_rate=current_penalty,
                )
                db.add(old_history)
            
            # Create new history entry for the NEW rate (today)
            new_history = InterestRateHistory(
                account_type=account_type,
                date=today,
                interest_rate=rate,
                penalty_interest_rate=current_penalty,
            )
            db.add(new_history)
        
        await db.commit()
    
    # Update Settings for backward compatibility
    settings = await get_settings(db)
    if account_type == "savings":
        settings.savings_account_interest_rate = rate
    elif account_type == "college_savings":
        settings.college_savings_account_interest_rate = rate
    db.add(settings)
    await db.commit()


async def set_global_penalty_rate(
    db: AsyncSession, account_type: str, rate: float
) -> None:
    """Update the global penalty interest rate for an account type."""
    if account_type not in ("checking", "savings", "college_savings"):
        raise ValueError("Invalid account type")
    
    today = date.today()
    
    # Get current rates to check if penalty rate changed
    current_interest, current_penalty = await get_current_rate_for_account_type(db, account_type)
    
    # Only create history entry if rate actually changed
    if current_penalty != rate:
        # Check if we already have an entry for today
        existing_result = await db.execute(
            select(InterestRateHistory)
            .where(
                InterestRateHistory.account_type == account_type,
                InterestRateHistory.date == today,
            )
            .order_by(InterestRateHistory.created_at.desc())
            .limit(1)
        )
        existing_entry = existing_result.scalar_one_or_none()
        
        if existing_entry:
            # Update existing entry
            existing_entry.penalty_interest_rate = rate
        else:
            # Check if this is the first history entry for this account type
            first_history_result = await db.execute(
                select(InterestRateHistory)
                .where(InterestRateHistory.account_type == account_type)
                .order_by(InterestRateHistory.date)
                .limit(1)
            )
            first_history = first_history_result.scalar_one_or_none()
            
            if not first_history:
                # This is the first history entry - create entry for OLD rate backdated
                history_date = today - timedelta(days=1)
                
                # Create history entry for the OLD rates (backdated)
                old_history = InterestRateHistory(
                    account_type=account_type,
                    date=history_date,
                    interest_rate=current_interest,
                    penalty_interest_rate=current_penalty,
                )
                db.add(old_history)
            
            # Create new history entry with updated penalty rate (today)
            new_history = InterestRateHistory(
                account_type=account_type,
                date=today,
                interest_rate=current_interest,
                penalty_interest_rate=rate,
            )
            db.add(new_history)
        
        await db.commit()
    
    # Update Settings
    settings = await get_settings(db)
    if account_type == "checking":
        settings.checking_penalty_interest_rate = rate
    elif account_type == "savings":
        settings.savings_penalty_interest_rate = rate
    elif account_type == "college_savings":
        settings.college_savings_penalty_interest_rate = rate
    db.add(settings)
    await db.commit()


async def set_cd_penalty_rate(
    db: AsyncSession, child_id: int, rate: float
) -> Account:
    """Update the early withdrawal penalty rate for certificates."""
    account = await get_account_by_child(db, child_id)
    if not account:
        raise ValueError("Account not found")
    account.cd_penalty_rate = rate
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


async def fetch_treasury_yield(
    db: AsyncSession, target_date: date | None = None
) -> TreasuryYield | None:
    """Fetch Treasury yield for a specific date from FRED API.
    
    If target_date is None, fetches the latest available yield.
    Returns None if API call fails or data is unavailable.
    """
    if not FRED_API_KEY:
        logger.warning("FRED_API_KEY not set, cannot fetch Treasury yield")
        return None
    
    try:
        async with httpx.AsyncClient() as client:
            if target_date is None:
                # Fetch latest available observation
                url = f"{FRED_API_BASE_URL}/series/observations"
                params = {
                    "series_id": FRED_SERIES_ID,
                    "api_key": FRED_API_KEY,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 1,
                }
            else:
                # Fetch observation for specific date
                url = f"{FRED_API_BASE_URL}/series/observations"
                params = {
                    "series_id": FRED_SERIES_ID,
                    "api_key": FRED_API_KEY,
                    "file_type": "json",
                    "observation_start": target_date.isoformat(),
                    "observation_end": target_date.isoformat(),
                    "limit": 1,
                }
            
            response = await client.get(url, params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()
            
            observations = data.get("observations", [])
            if not observations:
                logger.warning(f"No Treasury yield data found for date {target_date}")
                return None
            
            # Get the first (most recent) observation
            obs = observations[0]
            yield_str = obs.get("value", ".")
            obs_date_str = obs.get("date")
            
            # Validate date is present
            if not obs_date_str:
                logger.error(f"Treasury yield observation missing date field: {obs}")
                return None
            
            # Handle missing data (FRED returns "." for missing dates)
            if yield_str == "." or yield_str is None:
                logger.warning(f"Treasury yield data missing for date {obs_date_str}")
                return None
            
            try:
                yield_value = float(yield_str)
                obs_date = date.fromisoformat(obs_date_str)
            except (ValueError, TypeError) as e:
                logger.error(f"Error parsing Treasury yield data: yield_str={yield_str}, date_str={obs_date_str}, error={e}")
                return None
            
            # Check if we already have this yield in the database
            existing = await db.execute(
                select(TreasuryYield).where(TreasuryYield.yield_date == obs_date)
            )
            existing_yield = existing.scalar_one_or_none()
            
            if existing_yield:
                # Update existing entry
                existing_yield.yield_value = yield_value
                db.add(existing_yield)
                await db.commit()
                await db.refresh(existing_yield)
                return existing_yield
            else:
                # Validate obs_date is not None before creating
                if obs_date is None:
                    logger.error(f"obs_date is None after parsing. obs_date_str={obs_date_str}, obs={obs}")
                    return None
                
                # Create new entry
                treasury_yield = TreasuryYield(
                    yield_date=obs_date,
                    yield_value=yield_value,
                )
                db.add(treasury_yield)
                await db.commit()
                await db.refresh(treasury_yield)
                return treasury_yield
                
    except httpx.HTTPError as e:
        logger.error(f"HTTP error fetching Treasury yield: {e}")
        await db.rollback()
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching Treasury yield: {e}", exc_info=True)
        await db.rollback()
        return None


async def get_treasury_yield_for_date(
    db: AsyncSession, target_date: date
) -> float:
    """Get Treasury yield for a specific date.
    
    If exact date not found (weekends/holidays), uses most recent prior date.
    Returns yield as decimal (e.g., 0.0411 for 4.11%).
    Raises ValueError if no data available.
    """
    # First, try to get exact date
    result = await db.execute(
        select(TreasuryYield)
        .where(TreasuryYield.yield_date == target_date)
    )
    yield_obj = result.scalar_one_or_none()
    
    if yield_obj:
        return yield_obj.yield_value / 100.0  # Convert percentage to decimal
    
    # If not found, get most recent prior date
    result = await db.execute(
        select(TreasuryYield)
        .where(TreasuryYield.yield_date <= target_date)
        .order_by(TreasuryYield.yield_date.desc())
        .limit(1)
    )
    yield_obj = result.scalar_one_or_none()
    
    if yield_obj:
        return yield_obj.yield_value / 100.0  # Convert percentage to decimal
    
    # Try fetching from API for this date or recent dates
    fetched = await fetch_treasury_yield(db, target_date)
    if fetched:
        return fetched.yield_value / 100.0
    
    # If still no data, try fetching latest available
    fetched = await fetch_treasury_yield(db, None)
    if fetched:
        return fetched.yield_value / 100.0
    
    # Fallback: get Settings defaults and convert to approximate yield
    # This is a last resort - ideally we should have Treasury data
    settings = await get_settings(db)
    # Use savings rate as fallback (divide by typical multiplier of 1.0)
    fallback_rate = settings.savings_account_interest_rate
    logger.warning(f"No Treasury yield data available for {target_date}, using fallback rate {fallback_rate}")
    return fallback_rate


async def sync_treasury_yields(
    db: AsyncSession, start_date: date, end_date: date
) -> int:
    """Fetch and store Treasury yields for a date range.
    
    Returns count of new entries created.
    Useful for backfilling historical data.
    """
    if not FRED_API_KEY:
        logger.warning("FRED_API_KEY not set, cannot sync Treasury yields")
        return 0
    
    try:
        async with httpx.AsyncClient() as client:
            url = f"{FRED_API_BASE_URL}/series/observations"
            params = {
                "series_id": FRED_SERIES_ID,
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "observation_start": start_date.isoformat(),
                "observation_end": end_date.isoformat(),
                "sort_order": "asc",
                "limit": 100000,  # FRED allows up to 100k observations
            }
            
            response = await client.get(url, params=params, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            
            observations = data.get("observations", [])
            new_count = 0
            
            for obs in observations:
                yield_str = obs.get("value", ".")
                
                # Skip missing data
                if yield_str == "." or yield_str is None:
                    continue
                
                try:
                    yield_value = float(yield_str)
                    obs_date_str = obs.get("date")
                    obs_date = date.fromisoformat(obs_date_str)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Error parsing observation {obs}: {e}")
                    continue
                
                # Check if we already have this date
                existing = await db.execute(
                    select(TreasuryYield).where(TreasuryYield.yield_date == obs_date)
                )
                if existing.scalar_one_or_none():
                    continue  # Skip if already exists
                
                # Create new entry
                treasury_yield = TreasuryYield(
                    yield_date=obs_date,
                    yield_value=yield_value,
                )
                db.add(treasury_yield)
                new_count += 1
            
            await db.commit()
            logger.info(f"Synced {new_count} new Treasury yield entries from {start_date} to {end_date}")
            return new_count
            
    except httpx.HTTPError as e:
        logger.error(f"HTTP error syncing Treasury yields: {e}")
        await db.rollback()
        return 0
    except Exception as e:
        logger.error(f"Unexpected error syncing Treasury yields: {e}")
        await db.rollback()
        return 0


async def set_multiplier(
    db: AsyncSession, account_type: str, multiplier: float, effective_date: date | None = None
) -> None:
    """Update the multiplier for savings or college_savings account type.
    
    Creates a MultiplierHistory entry with the specified date (or today's date if not provided).
    Updates Settings table for backward compatibility.
    
    Args:
        db: Database session
        account_type: "savings" or "college_savings"
        multiplier: The multiplier value
        effective_date: Optional date for back-dating. If None, uses today's date.
    """
    if account_type not in ("savings", "college_savings"):
        raise ValueError("Multipliers only apply to savings and college_savings accounts")
    
    effective_date = effective_date or date.today()
    
    # Get current multiplier for the effective date to check if it changed
    current_multiplier = await get_multiplier_for_date(db, account_type, effective_date)
    
    # Check if we already have an entry for this date
    existing_result = await db.execute(
        select(MultiplierHistory)
        .where(
            MultiplierHistory.account_type == account_type,
            MultiplierHistory.date == effective_date,
        )
        .order_by(MultiplierHistory.created_at.desc())
        .limit(1)
    )
    existing_entry = existing_result.scalar_one_or_none()
    
    if existing_entry:
        # Update existing entry for this date
        existing_entry.multiplier = multiplier
    else:
        # Create new history entry for the specified date
        new_history = MultiplierHistory(
            account_type=account_type,
            date=effective_date,
            multiplier=multiplier,
        )
        db.add(new_history)
    
    await db.commit()
    
    # Update Settings for backward compatibility (only if effective_date is today or in the future)
    if effective_date >= date.today():
        settings = await get_settings(db)
        if account_type == "savings":
            settings.savings_multiplier = multiplier
        elif account_type == "college_savings":
            settings.college_savings_multiplier = multiplier
        db.add(settings)
        await db.commit()


async def get_multiplier_for_date(
    db: AsyncSession, account_type: str, target_date: date
) -> float:
    """Get multiplier effective on a given date.
    
    Queries MultiplierHistory for most recent entry on or before target_date.
    Falls back to Settings defaults if no history exists.
    """
    result = await db.execute(
        select(MultiplierHistory)
        .where(
            MultiplierHistory.account_type == account_type,
            MultiplierHistory.date <= target_date,
        )
        .order_by(MultiplierHistory.date.desc(), MultiplierHistory.created_at.desc())
        .limit(1)
    )
    history = result.scalar_one_or_none()
    if history:
        return history.multiplier
    
    # Fallback to Settings defaults
    settings = await get_settings(db)
    if account_type == "savings":
        return settings.savings_multiplier
    elif account_type == "college_savings":
        return settings.college_savings_multiplier
    else:
        return 1.0  # Default multiplier


async def create_transaction(db: AsyncSession, tx: Transaction) -> Transaction:
    """Persist a ledger transaction."""
    db.add(tx)
    await db.commit()
    await db.refresh(tx)
    return tx


async def get_transaction(
    db: AsyncSession, transaction_id: int
) -> Transaction | None:
    """Return a transaction by id or ``None`` if missing."""
    result = await db.execute(
        select(Transaction).where(Transaction.id == transaction_id)
    )
    return result.scalar_one_or_none()


async def save_transaction(db: AsyncSession, tx: Transaction) -> Transaction:
    """Persist updates to a transaction."""

    db.add(tx)
    await db.commit()
    await db.refresh(tx)
    return tx


async def delete_transaction(db: AsyncSession, tx: Transaction) -> None:
    """Remove a transaction from the ledger."""

    await db.delete(tx)
    await db.commit()


async def get_transactions_by_child(
    db: AsyncSession, child_id: int
) -> list[Transaction]:
    """Return all transactions for a child ordered by time."""

    result = await db.execute(
        select(Transaction)
        .where(Transaction.child_id == child_id)
        .order_by(Transaction.timestamp)
    )
    return result.scalars().all()


async def get_transactions_by_account(
    db: AsyncSession, account_id: int
) -> list[Transaction]:
    """Return all transactions for a specific account ordered by time."""

    result = await db.execute(
        select(Transaction)
        .where(Transaction.account_id == account_id)
        .order_by(Transaction.timestamp)
    )
    return result.scalars().all()


async def get_all_transactions(db: AsyncSession) -> list[Transaction]:
    """Return the full ledger across all children."""

    result = await db.execute(
        select(Transaction).order_by(Transaction.timestamp)
    )
    return result.scalars().all()


async def calculate_balance(db: AsyncSession, account_id: int) -> float:
    """Calculate the running balance for a specific account."""

    total = func.coalesce(
        func.sum(
            case(
                (Transaction.type == "credit", Transaction.amount),
                else_=-Transaction.amount,
            )
        ),
        0.0,
    )
    result = await db.execute(
        select(total).where(Transaction.account_id == account_id)
    )
    return float(result.scalar_one())


async def calculate_total_balance(db: AsyncSession, child_id: int) -> float:
    """Calculate the total balance across all accounts for a child."""
    accounts = await get_accounts_by_child(db, child_id)
    total = 0.0
    for account in accounts:
        total += await calculate_balance(db, account.id)
    return total


async def calculate_available_balance(db: AsyncSession, account_id: int) -> float:
    """Calculate available balance for a savings account (respects lockup period)."""
    account = await db.get(Account, account_id)
    if not account:
        return 0.0
    
    if account.account_type != "savings" or account.lockup_period_days is None:
        # For non-savings accounts or savings without lockup, return current balance
        return await calculate_balance(db, account_id)
    
    # For savings accounts with lockup period
    current_balance = await calculate_balance(db, account_id)
    lockup_date = date.today() - timedelta(days=account.lockup_period_days)
    
    # Calculate balance at lockup_date
    total_before = func.coalesce(
        func.sum(
            case(
                (Transaction.type == "credit", Transaction.amount),
                else_=-Transaction.amount,
            )
        ),
        0.0,
    )
    result = await db.execute(
        select(total_before).where(
            Transaction.account_id == account_id,
            Transaction.timestamp < datetime.combine(lockup_date, time.min)
        )
    )
    balance_at_lockup = float(result.scalar_one())
    
    # Available balance is the minimum of current balance and balance at lockup date
    return min(current_balance, balance_at_lockup)


async def recalc_interest(db: AsyncSession, account_id: int) -> None:
    """Recalculate and post daily interest transactions for a specific account.
    
    This function always recalculates ALL interest from the first transaction to today,
    using an optimized single-pass approach:
    1. Single query to get all transactions
    2. Batch delete all existing interest transactions
    3. Single in-memory pass to calculate all interest
    4. Batch insert all new interest transactions
    """
    account = await db.get(Account, account_id)
    if not account:
        raise ValueError("Account not found")
    
    # Only calculate interest for savings and college_savings accounts
    if account.account_type == "checking":
        return

    # Single query: Get ALL transactions for account (including old interest) ordered by timestamp
    result = await db.execute(
        select(Transaction)
        .where(Transaction.account_id == account_id)
        .order_by(Transaction.timestamp)
    )
    all_transactions = list(result.scalars().all())
    
    if not all_transactions:
        # No transactions, just update last_interest_applied
        account.last_interest_applied = date.today()
        account.total_interest_earned = 0.0
        db.add(account)
        await db.commit()
        return

    # Batch delete: Delete all existing interest transactions
    await db.execute(
        delete(Transaction).where(
            Transaction.account_id == account_id,
            Transaction.memo == "Interest",
            Transaction.initiated_by == "system",
        )
    )
    await db.commit()

    # Create a function to get rates for a given date (dynamically calculated)
    # This ensures that when multipliers change historically, the recalculation uses the new values
    async def get_rates_for_date(target_date: date) -> tuple[float, float]:
        """Get rates for a date by dynamically calculating from Treasury yields and multipliers."""
        return await get_interest_rate_for_date(db, account.account_type, target_date)

    # Single in-memory pass: Calculate all interest
    current_balance = 0.0
    total_interest = 0.0
    current_day = None
    interest_transactions = []
    today = date.today()

    for tx in all_transactions:
        # Skip old interest transactions (we just deleted them, but they're still in the list)
        if tx.memo == "Interest" and tx.initiated_by == "system":
            continue

        tx_day = tx.timestamp.date()

        # If we've moved to a new day, calculate interest for the previous day
        if current_day is not None and tx_day > current_day:
            # Calculate interest for all days between current_day and tx_day
            day = current_day
            while day < tx_day and day < today:
                # Get historical rate for this day (dynamically calculated)
                interest_rate, penalty_rate = await get_rates_for_date(day)
                
                # Determine which rate to use based on balance
                annual_rate = interest_rate if current_balance >= 0 else penalty_rate
                
                # Convert annualized rate to daily rate using compound interest formula
                # daily_rate = ((1 + annual_rate)^(1/365)) - 1
                daily_rate = ((1 + annual_rate) ** (1/365)) - 1
                
                interest = current_balance * daily_rate
                
                if interest != 0:
                    # Interest transaction timestamped at start of next day
                    tx_time = datetime.combine(day + timedelta(days=1), time.min)
                    interest_tx = Transaction(
                        child_id=account.child_id,
                        account_id=account_id,
                        type="credit" if interest >= 0 else "debit",
                        amount=abs(interest),
                        memo="Interest",
                        initiated_by="system",
                        initiator_id=0,
                        timestamp=tx_time,
                    )
                    interest_transactions.append(interest_tx)
                    current_balance += interest  # Compound it
                    total_interest += interest

                day += timedelta(days=1)

        # Process the transaction
        if tx.type == "credit":
            current_balance += tx.amount
        else:
            current_balance -= tx.amount

        current_day = tx_day

    # Calculate interest for remaining days up to today
    if current_day and current_day < today:
        day = current_day
        while day < today:
            # Get historical rate for this day (dynamically calculated)
            interest_rate, penalty_rate = await get_rates_for_date(day)
            
            # Determine which rate to use based on balance
            annual_rate = interest_rate if current_balance >= 0 else penalty_rate
            
            # Convert annualized rate to daily rate using compound interest formula
            # daily_rate = ((1 + annual_rate)^(1/365)) - 1
            daily_rate = ((1 + annual_rate) ** (1/365)) - 1
            
            interest = current_balance * daily_rate
            
            if interest != 0:
                # Interest transaction timestamped at start of next day
                tx_time = datetime.combine(day + timedelta(days=1), time.min)
                interest_tx = Transaction(
                    child_id=account.child_id,
                    account_id=account_id,
                    type="credit" if interest >= 0 else "debit",
                    amount=abs(interest),
                    memo="Interest",
                    initiated_by="system",
                    initiator_id=0,
                    timestamp=tx_time,
                )
                interest_transactions.append(interest_tx)
                current_balance += interest  # Compound it
                total_interest += interest

            day += timedelta(days=1)

    # Batch insert: Add all new interest transactions
    if interest_transactions:
        db.add_all(interest_transactions)

    # Update account metadata
    account.total_interest_earned = total_interest
    account.last_interest_applied = today
    db.add(account)
    await db.commit()


async def apply_service_fee(
    db: AsyncSession, account: Account, settings: Settings, today: date
) -> None:
    """Apply a monthly service fee on the first day of the month."""
    if today.day != 1:
        return
    if account.service_fee_last_charged and account.service_fee_last_charged.month == today.month and account.service_fee_last_charged.year == today.year:
        return
    balance = await calculate_balance(db, account.id)
    fee = (
        abs(balance) * settings.service_fee_amount
        if settings.service_fee_is_percentage
        else settings.service_fee_amount
    )
    fee = round(fee, 2)
    if fee <= 0:
        return
    tx = Transaction(
        child_id=account.child_id,
        account_id=account.id,
        type="debit",
        amount=fee,
        memo="Service Fee",
        initiated_by="system",
        initiator_id=0,
        timestamp=datetime.combine(today, time.min),
    )
    await create_transaction(db, tx)
    account.service_fee_last_charged = today
    db.add(account)
    await db.commit()


async def apply_overdraft_fee(
    db: AsyncSession, account: Account, settings: Settings, today: date
) -> None:
    """Charge an overdraft fee when an account balance is negative."""
    balance = await calculate_balance(db, account.id)
    if balance < 0:
        fee = (
            abs(balance) * settings.overdraft_fee_amount
            if settings.overdraft_fee_is_percentage
            else settings.overdraft_fee_amount
        )
        fee = round(fee, 2)
        if fee > 0:
            if settings.overdraft_fee_daily:
                if account.overdraft_fee_last_charged != today:
                    tx = Transaction(
                        child_id=account.child_id,
                        account_id=account.id,
                        type="debit",
                        amount=fee,
                        memo="Overdraft Fee",
                        initiated_by="system",
                        initiator_id=0,
                    )
                    await create_transaction(db, tx)
                    account.overdraft_fee_last_charged = today
            else:
                if not account.overdraft_fee_charged:
                    tx = Transaction(
                        child_id=account.child_id,
                        account_id=account.id,
                        type="debit",
                        amount=fee,
                        memo="Overdraft Fee",
                        initiated_by="system",
                        initiator_id=0,
                    )
                    await create_transaction(db, tx)
                    account.overdraft_fee_charged = True
                    account.overdraft_fee_last_charged = today
    else:
        if account.overdraft_fee_charged or account.overdraft_fee_last_charged:
            account.overdraft_fee_charged = False
            account.overdraft_fee_last_charged = None
    db.add(account)
    await db.commit()


async def post_transaction_update(db: AsyncSession, child_id: int) -> None:
    """Recalculate interest for all accounts and apply fees after a transaction.
    
    The optimized recalc_interest() handles all edge cases including back-dated
    transactions, so we always call it for savings/college_savings accounts.
    """
    accounts = await get_accounts_by_child(db, child_id)
    for account in accounts:
        if account.account_type in ("savings", "college_savings"):
            await recalc_interest(db, account.id)
    settings = await get_settings(db)
    # Apply fees to checking account only (or all accounts if needed)
    checking_account = await get_checking_account_by_child(db, child_id)
    if checking_account:
        await apply_overdraft_fee(db, checking_account, settings, date.today())


async def apply_promotion(
    db: AsyncSession,
    amount: float,
    is_percentage: bool,
    credit: bool,
    memo: str | None = None,
) -> int:
    """Apply a promotional credit or debit to every checking account."""

    accounts = await get_all_accounts(db)
    count = 0
    for account in accounts:
        # Only apply promotions to checking accounts
        if account.account_type != "checking":
            continue
        balance = await calculate_balance(db, account.id)
        adj = amount * balance if is_percentage else amount
        adj = round(adj, 2)
        if adj == 0:
            continue
        tx = Transaction(
            child_id=account.child_id,
            account_id=account.id,
            type="credit" if credit else "debit",
            amount=abs(adj),
            memo=memo or "Promotion",
            initiated_by="system",
            initiator_id=0,
        )
        await create_transaction(db, tx)
        await post_transaction_update(db, account.child_id)
        count += 1
    return count


async def create_withdrawal_request(
    db: AsyncSession, req: WithdrawalRequest
) -> WithdrawalRequest:
    """Persist a pending withdrawal request."""

    db.add(req)
    await db.commit()
    await db.refresh(req)
    return req


async def get_pending_withdrawals_for_parent(
    db: AsyncSession, parent_id: int
) -> list[WithdrawalRequest]:
    """Return pending withdrawal requests for children of a parent."""
    query = (
        select(WithdrawalRequest)
        .join(Child)
        .join(ChildUserLink)
        .where(
            ChildUserLink.user_id == parent_id,
            WithdrawalRequest.status == "pending",
        )
        .order_by(WithdrawalRequest.requested_at)
    )
    result = await db.execute(query)
    return result.scalars().all()


async def get_withdrawal_requests_by_child(
    db: AsyncSession, child_id: int
) -> list[WithdrawalRequest]:
    """Return withdrawal requests for a specific child."""
    result = await db.execute(
        select(WithdrawalRequest)
        .where(WithdrawalRequest.child_id == child_id)
        .order_by(WithdrawalRequest.requested_at.desc())
    )
    return result.scalars().all()


async def get_withdrawal_request(
    db: AsyncSession, request_id: int
) -> WithdrawalRequest | None:
    """Return a single withdrawal request by id."""
    result = await db.execute(
        select(WithdrawalRequest).where(WithdrawalRequest.id == request_id)
    )
    return result.scalar_one_or_none()


async def save_withdrawal_request(
    db: AsyncSession, req: WithdrawalRequest
) -> WithdrawalRequest:
    """Persist changes to a withdrawal request."""

    db.add(req)
    await db.commit()
    await db.refresh(req)
    return req


async def create_cd(
    db: AsyncSession, cd: CertificateDeposit
) -> CertificateDeposit:
    """Create a certificate of deposit record."""

    db.add(cd)
    await db.commit()
    await db.refresh(cd)
    return cd


async def get_cd(db: AsyncSession, cd_id: int) -> CertificateDeposit | None:
    """Return a CD by id or ``None`` if not found."""
    result = await db.execute(
        select(CertificateDeposit).where(CertificateDeposit.id == cd_id)
    )
    return result.scalar_one_or_none()


async def save_cd(
    db: AsyncSession, cd: CertificateDeposit
) -> CertificateDeposit:
    """Persist updates to a certificate of deposit."""

    db.add(cd)
    await db.commit()
    await db.refresh(cd)
    return cd


async def get_cds_by_child(
    db: AsyncSession, child_id: int
) -> list[CertificateDeposit]:
    """Return all CDs for a particular child."""
    result = await db.execute(
        select(CertificateDeposit)
        .where(CertificateDeposit.child_id == child_id)
        .order_by(CertificateDeposit.created_at)
    )
    return result.scalars().all()


async def redeem_cd(
    db: AsyncSession, cd: CertificateDeposit, treat_as_mature: bool = False
) -> CertificateDeposit:
    """Redeem a CD either at maturity or early.

    When ``treat_as_mature`` is ``True`` the CD pays out as though it reached
    maturity even if the ``matures_at`` date is in the future. This is used by
    the testing helper.
    """

    from .crud import create_transaction, recalc_interest  # avoid circular

    if cd.status != "accepted":
        return cd

    matured = treat_as_mature
    if cd.matures_at:
        matured = matured or datetime.utcnow() >= cd.matures_at

    checking_account = await get_checking_account_by_child(db, cd.child_id)
    if not checking_account:
        return cd
    
    if matured:
        payout = round(cd.amount * (1 + cd.interest_rate), 2)
        payout_time = (
            cd.matures_at if cd.matures_at and cd.matures_at <= datetime.utcnow() else datetime.utcnow()
        )
        await create_transaction(
            db,
            Transaction(
                child_id=cd.child_id,
                account_id=checking_account.id,
                type="credit",
                amount=payout,
                memo=f"CD #{cd.id} maturity",
                initiated_by="system",
                initiator_id=0,
                timestamp=payout_time,
            ),
        )
    else:
        await create_transaction(
            db,
            Transaction(
                child_id=cd.child_id,
                account_id=checking_account.id,
                type="credit",
                amount=cd.amount,
                memo=f"CD #{cd.id} early withdrawal",
                initiated_by="system",
                initiator_id=0,
            ),
        )
        penalty_rate = checking_account.cd_penalty_rate
        await create_transaction(
            db,
            Transaction(
                child_id=cd.child_id,
                account_id=checking_account.id,
                type="debit",
                amount=round(cd.amount * penalty_rate, 2),
                memo=f"CD #{cd.id} early withdrawal penalty",
                initiated_by="system",
                initiator_id=0,
            ),
        )

    cd.status = "redeemed"
    cd.redeemed_at = datetime.utcnow()
    await save_cd(db, cd)
    await post_transaction_update(db, cd.child_id)
    return cd


async def redeem_matured_cds(db: AsyncSession) -> None:
    """Redeem all CDs that have reached their maturity date."""
    result = await db.execute(
        select(CertificateDeposit).where(
            CertificateDeposit.status == "accepted",
            CertificateDeposit.matures_at <= datetime.utcnow(),
        )
    )
    cds = result.scalars().all()
    for cd in cds:
        await redeem_cd(db, cd)


async def create_recurring_charge(db: AsyncSession, rc: RecurringCharge) -> RecurringCharge:
    """Store a new recurring charge definition."""

    db.add(rc)
    await db.commit()
    await db.refresh(rc)
    return rc


async def get_recurring_charge(db: AsyncSession, rc_id: int) -> RecurringCharge | None:
    """Fetch a recurring charge by id."""
    result = await db.execute(
        select(RecurringCharge).where(RecurringCharge.id == rc_id)
    )
    return result.scalar_one_or_none()


async def get_recurring_charges_by_child(
    db: AsyncSession, child_id: int
) -> list[RecurringCharge]:
    """List all recurring charges scheduled for a child."""
    result = await db.execute(
        select(RecurringCharge).where(RecurringCharge.child_id == child_id)
    )
    return result.scalars().all()


async def save_recurring_charge(db: AsyncSession, rc: RecurringCharge) -> RecurringCharge:
    db.add(rc)
    await db.commit()
    await db.refresh(rc)
    return rc


async def delete_recurring_charge(db: AsyncSession, rc: RecurringCharge) -> None:
    """Remove a recurring charge from the database."""

    await db.delete(rc)
    await db.commit()


async def process_due_recurring_charges(db: AsyncSession) -> None:
    """Process and apply any recurring charges that are due today."""

    today = date.today()
    result = await db.execute(
        select(RecurringCharge).where(
            RecurringCharge.active == True,  # noqa: E712
            RecurringCharge.next_run <= today,
        )
    )
    charges = result.scalars().all()
    for charge in charges:
        while charge.next_run <= today and charge.active:
            checking_account = await get_checking_account_by_child(db, charge.child_id)
            if not checking_account:
                continue
            await create_transaction(
                db,
                Transaction(
                    child_id=charge.child_id,
                    account_id=checking_account.id,
                    type=charge.type,
                    amount=charge.amount,
                    memo=charge.memo,
                    initiated_by="system",
                    initiator_id=0,
                ),
            )
            charge.next_run = charge.next_run + timedelta(days=charge.interval_days)
            db.add(charge)
            await db.commit()
            await db.refresh(charge)


# --- Loan helpers -------------------------------------------------------


async def create_loan(db: AsyncSession, loan: Loan) -> Loan:
    """Persist a new loan request."""

    db.add(loan)
    await db.commit()
    await db.refresh(loan)
    return loan


async def get_loan(db: AsyncSession, loan_id: int) -> Loan | None:
    result = await db.execute(select(Loan).where(Loan.id == loan_id))
    return result.scalar_one_or_none()


async def get_loans_by_child(db: AsyncSession, child_id: int) -> list[Loan]:
    result = await db.execute(select(Loan).where(Loan.child_id == child_id))
    return result.scalars().all()


async def save_loan(db: AsyncSession, loan: Loan) -> Loan:
    db.add(loan)
    await db.commit()
    await db.refresh(loan)
    return loan


async def record_loan_transaction(db: AsyncSession, tx: LoanTransaction) -> LoanTransaction:
    db.add(tx)
    await db.commit()
    await db.refresh(tx)
    return tx


async def recalc_loan_interest(db: AsyncSession, loan: Loan) -> None:
    """Accrue interest on a loan for any missed days."""

    today = date.today()
    if loan.status != "active":
        return

    start_day = loan.last_interest_applied or loan.created_at.date()
    if start_day >= today:
        return

    day = start_day
    while day < today:
        interest = round(loan.principal_remaining * loan.interest_rate, 2)
        if interest != 0:
            loan.principal_remaining += interest
            await record_loan_transaction(
                db,
                LoanTransaction(
                    loan_id=loan.id,
                    type="interest",
                    amount=interest,
                    memo="Interest",
                    timestamp=datetime.combine(day + timedelta(days=1), time.min),
                ),
            )
        day += timedelta(days=1)

    loan.last_interest_applied = today
    await save_loan(db, loan)


async def get_active_loans(db: AsyncSession) -> list[Loan]:
    result = await db.execute(select(Loan).where(Loan.status == "active"))
    return result.scalars().all()


async def process_loan_interest(db: AsyncSession) -> None:
    loans = await get_active_loans(db)
    for loan in loans:
        await recalc_loan_interest(db, loan)


# --- Chore helpers ------------------------------------------------------


async def create_chore(db: AsyncSession, chore: Chore) -> Chore:
    """Persist a new chore."""

    db.add(chore)
    await db.commit()
    await db.refresh(chore)
    return chore


async def get_chore(db: AsyncSession, chore_id: int) -> Chore | None:
    result = await db.execute(select(Chore).where(Chore.id == chore_id))
    return result.scalar_one_or_none()


async def get_chores_by_child(db: AsyncSession, child_id: int) -> list[Chore]:
    result = await db.execute(select(Chore).where(Chore.child_id == child_id))
    return result.scalars().all()


async def save_chore(db: AsyncSession, chore: Chore) -> Chore:
    db.add(chore)
    await db.commit()
    await db.refresh(chore)
    return chore


async def delete_chore(db: AsyncSession, chore: Chore) -> None:
    await db.delete(chore)
    await db.commit()


# --- Messaging helpers ----------------------------------------------------

async def create_message(db: AsyncSession, message: Message) -> Message:
    """Persist a new message."""

    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


async def get_message(db: AsyncSession, message_id: int) -> Message | None:
    result = await db.execute(select(Message).where(Message.id == message_id))
    return result.scalar_one_or_none()


async def list_inbox(
    db: AsyncSession, *, user_id: int | None = None, child_id: int | None = None, archived: bool = False
) -> list[Message]:
    stmt = select(Message).where(Message.recipient_archived == archived)
    if user_id is not None:
        stmt = stmt.where(Message.recipient_user_id == user_id)
    if child_id is not None:
        stmt = stmt.where(Message.recipient_child_id == child_id)
    stmt = stmt.order_by(Message.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


async def list_sent(
    db: AsyncSession, *, user_id: int | None = None, child_id: int | None = None, archived: bool = False
) -> list[Message]:
    stmt = select(Message).where(Message.sender_archived == archived)
    if user_id is not None:
        stmt = stmt.where(Message.sender_user_id == user_id)
    if child_id is not None:
        stmt = stmt.where(Message.sender_child_id == child_id)
    stmt = stmt.order_by(Message.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


async def archive_message(
    db: AsyncSession,
    message: Message,
    *,
    as_sender: bool = False,
) -> Message:
    if as_sender:
        message.sender_archived = True
    else:
        message.recipient_archived = True
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


async def get_all_messages(db: AsyncSession) -> list[Message]:
    result = await db.execute(select(Message).order_by(Message.created_at.desc()))
    return result.scalars().all()


# Coupon utilities

async def create_coupon(db: AsyncSession, coupon: Coupon) -> Coupon:
    db.add(coupon)
    await db.commit()
    await db.refresh(coupon)
    return coupon


async def get_coupon_by_code(db: AsyncSession, code: str) -> Coupon | None:
    result = await db.execute(select(Coupon).where(Coupon.code == code))
    return result.scalar_one_or_none()


async def get_coupon(db: AsyncSession, coupon_id: int) -> Coupon | None:
    result = await db.execute(select(Coupon).where(Coupon.id == coupon_id))
    return result.scalar_one_or_none()


async def list_all_coupons(
    db: AsyncSession, search: str | None = None, scope: str | None = None
) -> list[Coupon]:
    stmt = select(Coupon).order_by(Coupon.created_at.desc())
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            Coupon.code.ilike(like) | Coupon.memo.ilike(like)
        )
    if scope:
        stmt = stmt.where(Coupon.scope == scope)
    result = await db.execute(stmt)
    return result.scalars().all()


async def delete_coupon(db: AsyncSession, coupon: Coupon) -> None:
    await db.delete(coupon)
    await db.commit()


async def list_coupons_by_creator(db: AsyncSession, user_id: int) -> list[Coupon]:
    result = await db.execute(
        select(Coupon)
        .where(Coupon.created_by == user_id)
        .order_by(Coupon.created_at.desc())
    )
    return result.scalars().all()


async def save_coupon(db: AsyncSession, coupon: Coupon) -> Coupon:
    db.add(coupon)
    await db.commit()
    await db.refresh(coupon)
    return coupon


async def create_coupon_redemption(
    db: AsyncSession, redemption: CouponRedemption
) -> CouponRedemption:
    db.add(redemption)
    await db.commit()
    await db.refresh(redemption)
    return redemption


async def list_redemptions_by_child(
    db: AsyncSession, child_id: int
) -> list[CouponRedemption]:
    result = await db.execute(
        select(CouponRedemption)
        .where(CouponRedemption.child_id == child_id)
        .options(selectinload(CouponRedemption.coupon))
        .order_by(CouponRedemption.redeemed_at.desc())
    )
    return result.scalars().all()


async def ensure_education_content(db: AsyncSession) -> None:
    """Seed the database with built-in educational modules and badges."""

    from app.education_content import EDUCATION_MODULES

    for data in EDUCATION_MODULES:
        result = await db.execute(
            select(EducationModule).where(EducationModule.slug == data["slug"])
        )
        module = result.scalar_one_or_none()
        if not module:
            module = EducationModule(
                slug=data["slug"], title=data["title"], content=data["content"], enabled=True
            )
            db.add(module)
            await db.flush()
            badge = Badge(name=data["badge"], module_id=module.id)
            db.add(badge)
            for q in data["questions"]:
                db.add(
                    QuizQuestion(
                        module_id=module.id,
                        prompt=q["prompt"],
                        options=q["options"],
                        answer_index=q["answer"],
                    )
                )
    await db.commit()


async def get_enabled_modules(db: AsyncSession) -> list[EducationModule]:
    result = await db.execute(
        select(EducationModule)
        .where(EducationModule.enabled == True)  # noqa: E712
        .options(selectinload(EducationModule.questions))
        .order_by(EducationModule.id)
    )
    return result.scalars().all()


async def get_questions_for_module(db: AsyncSession, module_id: int) -> list[QuizQuestion]:
    result = await db.execute(
        select(QuizQuestion).where(QuizQuestion.module_id == module_id).order_by(QuizQuestion.id)
    )
    return result.scalars().all()


async def get_badge_for_module(db: AsyncSession, module_id: int) -> Badge | None:
    result = await db.execute(select(Badge).where(Badge.module_id == module_id))
    return result.scalar_one_or_none()


async def get_child_badges(db: AsyncSession, child_id: int) -> list[Badge]:
    result = await db.execute(
        select(Badge)
        .join(ChildBadge, ChildBadge.badge_id == Badge.id)
        .where(ChildBadge.child_id == child_id)
        .order_by(Badge.id)
    )
    return result.scalars().all()


async def award_badge_for_module(
    db: AsyncSession,
    child_id: int,
    module_id: int,
    awarded_by: int | None = None,
    source: str = "quiz",
) -> bool:
    badge = await get_badge_for_module(db, module_id)
    if not badge:
        return False
    result = await db.execute(
        select(ChildBadge).where(
            ChildBadge.child_id == child_id, ChildBadge.badge_id == badge.id
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return False
    db.add(
        ChildBadge(
            child_id=child_id,
            badge_id=badge.id,
            awarded_by_user_id=awarded_by,
            source=source,
        )
    )
    await db.commit()
    return True
