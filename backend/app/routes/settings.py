"""Endpoints for viewing and updating site-wide settings."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.database import get_session
from app.models import User
from app.auth import require_role
from app.schemas import SettingsRead, SettingsUpdate, MultiplierUpdate, MultiplierHistoryRead, TreasuryYieldRead
from app.crud import (
    get_settings, save_settings, set_global_interest_rate, set_global_penalty_rate, post_transaction_update,
    set_multiplier, get_multiplier_for_date, fetch_treasury_yield, sync_treasury_yields, get_all_accounts
)
from app.models import MultiplierHistory, TreasuryYield
from sqlmodel import select
from datetime import date, timedelta
from typing import Optional

router = APIRouter(prefix="/settings", tags=["settings"])


class InterestRateUpdate(BaseModel):
    account_type: str  # "savings" or "college_savings"
    rate: float


class PenaltyRateUpdate(BaseModel):
    account_type: str  # "checking", "savings", or "college_savings"
    rate: float


@router.get("/", response_model=SettingsRead)
async def read_settings(db: AsyncSession = Depends(get_session)):
    """Retrieve the current configuration values."""
    settings = await get_settings(db)
    return SettingsRead(
        site_name=settings.site_name,
        site_url=settings.site_url,
        savings_account_interest_rate=settings.savings_account_interest_rate,
        college_savings_account_interest_rate=settings.college_savings_account_interest_rate,
        savings_multiplier=settings.savings_multiplier,
        college_savings_multiplier=settings.college_savings_multiplier,
        savings_account_lockup_period_days=settings.savings_account_lockup_period_days,
        checking_penalty_interest_rate=settings.checking_penalty_interest_rate,
        savings_penalty_interest_rate=settings.savings_penalty_interest_rate,
        college_savings_penalty_interest_rate=settings.college_savings_penalty_interest_rate,
        default_penalty_interest_rate=settings.default_penalty_interest_rate,
        default_cd_penalty_rate=settings.default_cd_penalty_rate,
        service_fee_amount=settings.service_fee_amount,
        service_fee_is_percentage=settings.service_fee_is_percentage,
        overdraft_fee_amount=settings.overdraft_fee_amount,
        overdraft_fee_is_percentage=settings.overdraft_fee_is_percentage,
        overdraft_fee_daily=settings.overdraft_fee_daily,
        currency_symbol=settings.currency_symbol,
        public_registration_disabled=settings.public_registration_disabled,
        chores_ui_enabled=settings.chores_ui_enabled,
        loans_ui_enabled=settings.loans_ui_enabled,
        coupons_ui_enabled=settings.coupons_ui_enabled,
        messages_ui_enabled=settings.messages_ui_enabled,
    )


@router.put("/", response_model=SettingsRead)
async def update_settings(
    data: SettingsUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    """Update settings; only admins may change configuration."""
    settings = await get_settings(db)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(settings, field, value)
    updated = await save_settings(db, settings)
    return SettingsRead(
        site_name=updated.site_name,
        site_url=updated.site_url,
        savings_account_interest_rate=updated.savings_account_interest_rate,
        college_savings_account_interest_rate=updated.college_savings_account_interest_rate,
        savings_multiplier=updated.savings_multiplier,
        college_savings_multiplier=updated.college_savings_multiplier,
        savings_account_lockup_period_days=updated.savings_account_lockup_period_days,
        checking_penalty_interest_rate=updated.checking_penalty_interest_rate,
        savings_penalty_interest_rate=updated.savings_penalty_interest_rate,
        college_savings_penalty_interest_rate=updated.college_savings_penalty_interest_rate,
        default_penalty_interest_rate=updated.default_penalty_interest_rate,
        default_cd_penalty_rate=updated.default_cd_penalty_rate,
        service_fee_amount=updated.service_fee_amount,
        service_fee_is_percentage=updated.service_fee_is_percentage,
        overdraft_fee_amount=updated.overdraft_fee_amount,
        overdraft_fee_is_percentage=updated.overdraft_fee_is_percentage,
        overdraft_fee_daily=updated.overdraft_fee_daily,
        currency_symbol=updated.currency_symbol,
        public_registration_disabled=updated.public_registration_disabled,
        chores_ui_enabled=updated.chores_ui_enabled,
        loans_ui_enabled=updated.loans_ui_enabled,
        coupons_ui_enabled=updated.coupons_ui_enabled,
        messages_ui_enabled=updated.messages_ui_enabled,
    )


@router.put("/rates/interest")
async def update_global_interest_rate(
    data: InterestRateUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    """Update the global interest rate for an account type (savings or college_savings)."""
    if data.account_type not in ("savings", "college_savings"):
        raise HTTPException(status_code=400, detail="Interest rates only apply to savings and college_savings accounts")
    
    await set_global_interest_rate(db, data.account_type, data.rate)
    
    # Trigger interest recalculation for all accounts of this type
    from app.crud import get_all_accounts
    accounts = await get_all_accounts(db)
    for account in accounts:
        if account.account_type == data.account_type:
            await post_transaction_update(db, account.child_id)
    
    return {"message": f"Interest rate updated for {data.account_type} accounts", "account_type": data.account_type, "rate": data.rate}


@router.put("/rates/penalty")
async def update_global_penalty_rate(
    data: PenaltyRateUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    """Update the global penalty interest rate for an account type."""
    if data.account_type not in ("checking", "savings", "college_savings"):
        raise HTTPException(status_code=400, detail="Invalid account type")
    
    await set_global_penalty_rate(db, data.account_type, data.rate)
    
    # Trigger interest recalculation for all accounts of this type
    from app.crud import get_all_accounts
    accounts = await get_all_accounts(db)
    for account in accounts:
        if account.account_type == data.account_type:
            await post_transaction_update(db, account.child_id)
    
    return {"message": f"Penalty rate updated for {data.account_type} accounts", "account_type": data.account_type, "rate": data.rate}


@router.put("/multipliers")
async def update_multiplier(
    data: MultiplierUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    """Update the multiplier for savings or college_savings account type.
    
    If effective_date is provided, the multiplier change will be backdated to that date.
    """
    if data.account_type not in ("savings", "college_savings"):
        raise HTTPException(status_code=400, detail="Multipliers only apply to savings and college_savings accounts")
    
    await set_multiplier(db, data.account_type, data.multiplier, data.effective_date)
    
    # Trigger interest recalculation for all accounts of this type
    accounts = await get_all_accounts(db)
    for account in accounts:
        if account.account_type == data.account_type:
            await post_transaction_update(db, account.child_id)
    
    return {"message": f"Multiplier updated for {data.account_type} accounts", "account_type": data.account_type, "multiplier": data.multiplier}


@router.get("/multipliers")
async def get_multipliers(
    db: AsyncSession = Depends(get_session),
):
    """Get current multiplier values from Settings."""
    settings = await get_settings(db)
    return {
        "savings_multiplier": settings.savings_multiplier,
        "college_savings_multiplier": settings.college_savings_multiplier,
    }


@router.get("/multipliers/history", response_model=list[MultiplierHistoryRead])
async def get_multiplier_history(
    account_type: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    """Get multiplier history entries.
    
    Query params:
    - account_type: Optional filter by account type ("savings" or "college_savings")
    - start_date: Optional start date filter
    - end_date: Optional end date filter
    """
    query = select(MultiplierHistory)
    
    if account_type:
        if account_type not in ("savings", "college_savings"):
            raise HTTPException(status_code=400, detail="Invalid account type")
        query = query.where(MultiplierHistory.account_type == account_type)
    
    if start_date:
        query = query.where(MultiplierHistory.date >= start_date)
    
    if end_date:
        query = query.where(MultiplierHistory.date <= end_date)
    
    query = query.order_by(MultiplierHistory.date.desc(), MultiplierHistory.created_at.desc())
    
    result = await db.execute(query)
    history = result.scalars().all()
    return [MultiplierHistoryRead(
        id=h.id,
        account_type=h.account_type,
        date=h.date,
        multiplier=h.multiplier,
        created_at=h.created_at,
    ) for h in history]


@router.delete("/multipliers/history/{history_id}")
async def delete_multiplier_history(
    history_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    """Delete a multiplier history entry by ID."""
    result = await db.execute(
        select(MultiplierHistory).where(MultiplierHistory.id == history_id)
    )
    entry = result.scalar_one_or_none()
    
    if not entry:
        raise HTTPException(status_code=404, detail="Multiplier history entry not found")
    
    account_type = entry.account_type
    
    await db.delete(entry)
    await db.commit()
    
    # Trigger interest recalculation for all accounts of this type
    accounts = await get_all_accounts(db)
    for account in accounts:
        if account.account_type == account_type:
            await post_transaction_update(db, account.child_id)
    
    return {"message": "Multiplier history entry deleted"}


@router.get("/treasury-yields", response_model=list[TreasuryYieldRead])
async def get_treasury_yields(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: AsyncSession = Depends(get_session),
):
    """Get Treasury yield data. Public read-only endpoint for displaying current rates.
    
    Query params:
    - start_date: Optional start date filter
    - end_date: Optional end date filter
    """
    query = select(TreasuryYield)
    
    if start_date:
        query = query.where(TreasuryYield.yield_date >= start_date)
    
    if end_date:
        query = query.where(TreasuryYield.yield_date <= end_date)
    
    query = query.order_by(TreasuryYield.yield_date.desc())
    
    result = await db.execute(query)
    yields = result.scalars().all()
    return [TreasuryYieldRead(
        id=y.id,
        yield_date=y.yield_date,
        yield_value=y.yield_value,
        created_at=y.created_at,
    ) for y in yields]


@router.post("/treasury-yields/sync")
async def sync_treasury_yields_endpoint(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    """Manually trigger Treasury yield sync from FRED API.
    
    Query params:
    - start_date: Optional start date (defaults to 30 days ago)
    - end_date: Optional end date (defaults to today)
    
    Useful for backfilling historical data or fixing missing data.
    """
    if start_date is None:
        start_date = date.today() - timedelta(days=30)
    if end_date is None:
        end_date = date.today()
    
    count = await sync_treasury_yields(db, start_date, end_date)
    return {
        "message": f"Synced {count} Treasury yield entries",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "count": count,
    }
