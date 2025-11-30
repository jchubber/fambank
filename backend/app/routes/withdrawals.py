from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

"""Endpoints for handling child withdrawal requests."""

from app.database import get_session
from app.auth import get_current_child, require_permissions
from app.models import WithdrawalRequest, Transaction, Child, User
from app.acl import PERM_MANAGE_WITHDRAWALS
from app.crud import (
    create_withdrawal_request,
    get_pending_withdrawals_for_parent,
    get_withdrawal_requests_by_child,
    get_withdrawal_request,
    save_withdrawal_request,
    create_transaction,
    get_children_by_user,
    post_transaction_update,
    get_child_user_link,
    get_checking_account_by_child,
    get_account_by_child_and_type,
    calculate_available_balance,
)
from app.schemas import WithdrawalRequestCreate, WithdrawalRequestRead, DenyRequest

router = APIRouter(prefix="/withdrawals", tags=["withdrawals"])


@router.post("/", response_model=WithdrawalRequestRead)
async def request_withdrawal(
    data: WithdrawalRequestCreate,
    db: AsyncSession = Depends(get_session),
    child: Child = Depends(get_current_child),
):
    """Children create a withdrawal request for parent approval."""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        account_type = data.account_type or 'checking'
        logger.info(f"Withdrawal request: child_id={child.id}, amount={data.amount}, account_type={account_type}, memo={data.memo}")
        
        # College savings withdrawals are admin-only
        if account_type == "college_savings":
            raise HTTPException(status_code=403, detail="College savings withdrawals are admin-only")
        
        # Get the account and validate available balance
        account = await get_account_by_child_and_type(db, child.id, account_type)
        if not account:
            logger.error(f"Account not found: child_id={child.id}, account_type={account_type}")
            raise HTTPException(status_code=404, detail=f"{account_type} account not found")
        
        if account_type == "savings":
            available = await calculate_available_balance(db, account.id)
            logger.info(f"Savings account available balance: {available}")
            if data.amount > available:
                raise HTTPException(status_code=400, detail=f"Insufficient available balance. Available: ${available:.2f}")
        else:
            from app.crud import calculate_balance
            balance = await calculate_balance(db, account.id)
            logger.info(f"Checking account balance: {balance}")
            if data.amount > balance:
                raise HTTPException(status_code=400, detail="Insufficient balance")
        
        req = WithdrawalRequest(child_id=child.id, account_type=account_type, amount=data.amount, memo=data.memo)
        result = await create_withdrawal_request(db, req)
        logger.info(f"Withdrawal request created: id={result.id}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating withdrawal request: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/mine", response_model=list[WithdrawalRequestRead])
async def my_requests(
    db: AsyncSession = Depends(get_session),
    child: Child = Depends(get_current_child),
):
    return await get_withdrawal_requests_by_child(db, child.id)


@router.get("/", response_model=list[WithdrawalRequestRead])
async def pending_requests(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(
        require_permissions(PERM_MANAGE_WITHDRAWALS)
    ),
):
    return await get_pending_withdrawals_for_parent(db, current_user.id)


async def _ensure_parent_owns_request(db: AsyncSession, req: WithdrawalRequest, parent_id: int) -> None:
    children = await get_children_by_user(db, parent_id)
    if req.child_id not in [c.id for c in children]:
        raise HTTPException(status_code=404, detail="Request not found")


@router.post("/{request_id}/approve", response_model=WithdrawalRequestRead)
async def approve_request(
    request_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(
        require_permissions(PERM_MANAGE_WITHDRAWALS)
    ),
):
    req = await get_withdrawal_request(db, request_id)
    if not req or req.status != "pending":
        raise HTTPException(status_code=404, detail="Request not found")
    await _ensure_parent_owns_request(db, req, current_user.id)
    if current_user.role != "admin":
        link = await get_child_user_link(db, current_user.id, req.child_id)
        if not link or (
            PERM_MANAGE_WITHDRAWALS not in link.permissions and not link.is_owner
        ):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

    account = await get_account_by_child_and_type(db, req.child_id, req.account_type)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    # Validate available balance for savings accounts
    if req.account_type == "savings":
        available = await calculate_available_balance(db, account.id)
        if req.amount > available:
            raise HTTPException(status_code=400, detail=f"Insufficient available balance. Available: ${available:.2f}")
    
    tx = Transaction(
        child_id=req.child_id,
        account_id=account.id,
        type="debit",
        amount=req.amount,
        memo=req.memo,
        initiated_by="child",
        initiator_id=req.child_id,
    )
    await create_transaction(db, tx)
    await post_transaction_update(db, req.child_id)

    req.status = "approved"
    req.responded_at = datetime.utcnow()
    req.approver_id = current_user.id
    await save_withdrawal_request(db, req)
    return req


@router.post("/{request_id}/deny", response_model=WithdrawalRequestRead)
async def deny_request(
    request_id: int,
    reason: DenyRequest,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(
        require_permissions(PERM_MANAGE_WITHDRAWALS)
    ),
):
    req = await get_withdrawal_request(db, request_id)
    if not req or req.status != "pending":
        raise HTTPException(status_code=404, detail="Request not found")
    await _ensure_parent_owns_request(db, req, current_user.id)
    if current_user.role != "admin":
        link = await get_child_user_link(db, current_user.id, req.child_id)
        if not link or (
            PERM_MANAGE_WITHDRAWALS not in link.permissions and not link.is_owner
        ):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
    req.status = "denied"
    req.denial_reason = reason.reason
    req.responded_at = datetime.utcnow()
    req.approver_id = current_user.id
    await save_withdrawal_request(db, req)
    return req


@router.post("/{request_id}/cancel", response_model=WithdrawalRequestRead)
async def cancel_request(
    request_id: int,
    db: AsyncSession = Depends(get_session),
    child: Child = Depends(get_current_child),
):
    req = await get_withdrawal_request(db, request_id)
    if not req or req.status != "pending" or req.child_id != child.id:
        raise HTTPException(status_code=404, detail="Request not found")
    req.status = "cancelled"
    req.responded_at = datetime.utcnow()
    await save_withdrawal_request(db, req)
    return req
