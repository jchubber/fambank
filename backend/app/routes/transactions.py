import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone


"""Endpoints for recording and viewing ledger transactions."""

from app.database import get_session
from app.models import Transaction, User, Child
from app.schemas import (
    TransactionCreate,
    TransactionRead,
    TransactionUpdate,
    LedgerResponse,
)
from app.crud import (
    create_transaction,
    get_transactions_by_child,
    get_transactions_by_account,
    calculate_balance,
    calculate_total_balance,
    get_transaction,
    save_transaction,
    delete_transaction,
    post_transaction_update,
    get_child_user_link,
    get_checking_account_by_child,
    get_account,
    get_child,
)
from app.auth import require_permissions, get_current_user, get_current_identity
from app.acl import (
    PERM_ADD_TRANSACTION,
    PERM_VIEW_TRANSACTIONS,
    PERM_DELETE_TRANSACTION,
    PERM_EDIT_TRANSACTION,
    PERM_DEPOSIT,
    PERM_DEBIT,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.post("/", response_model=TransactionRead)
async def add_transaction(
    transaction: TransactionCreate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_permissions(PERM_ADD_TRANSACTION)),
):
    """Create a new credit or debit transaction."""
    user_perm_names = {p.name for p in current_user.permissions}
    if current_user.role != "admin":
        if transaction.type == "credit" and PERM_DEPOSIT not in user_perm_names:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
            )
        if transaction.type == "debit" and PERM_DEBIT not in user_perm_names:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
            )

    if current_user.role != "admin":
        link = await get_child_user_link(db, current_user.id, transaction.child_id)
        if not link:
            raise HTTPException(status_code=404, detail="Child not found")
        perm_needed = PERM_DEPOSIT if transaction.type == "credit" else PERM_DEBIT
        if perm_needed not in link.permissions and not link.is_owner:
            raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Validate and handle custom timestamp (only for parents and admins)
    timestamp = transaction.timestamp
    if timestamp is not None:
        # Only parents and admins can set custom timestamps
        if current_user.role not in ("admin", "parent"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only parents and admins can set custom timestamps"
            )
        
        # Normalize timestamp to timezone-aware UTC for all validations
        if timestamp.tzinfo is None:
            # Assume UTC if no timezone info
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        
        # Validate timestamp is not in the future
        now = datetime.now(timezone.utc)
        if timestamp > now:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Transaction timestamp cannot be in the future"
            )
        
        # Validate timestamp is after account creation
        child = await get_child(db, transaction.child_id)
        if not child:
            raise HTTPException(status_code=404, detail="Child not found")
        # Convert child.created_at to timezone-aware for comparison
        child_created = child.created_at
        if child_created.tzinfo is None:
            child_created = child_created.replace(tzinfo=timezone.utc)
        if timestamp < child_created:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Transaction timestamp cannot be before account creation"
            )

    # Default to checking account if account_id not provided
    account_id = transaction.account_id
    if not account_id:
        checking_account = await get_checking_account_by_child(db, transaction.child_id)
        if not checking_account:
            raise HTTPException(status_code=404, detail="Checking account not found")
        account_id = checking_account.id

    tx_model = Transaction(
        child_id=transaction.child_id,
        account_id=account_id,
        type=transaction.type,
        amount=transaction.amount,
        memo=transaction.memo,
        initiated_by=transaction.initiated_by,
        initiator_id=transaction.initiator_id,
    )
    # Set timestamp if provided, otherwise let default_factory handle it
    if timestamp is not None:
        # Remove timezone info for storage (database stores naive UTC)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.replace(tzinfo=None)
        tx_model.timestamp = timestamp
    new_tx = await create_transaction(db, tx_model)
    logger.info(
        "Transaction %s %s for child %s by user %s",
        transaction.type,
        transaction.amount,
        transaction.child_id,
        current_user.id,
    )
    await post_transaction_update(db, transaction.child_id)
    return new_tx


@router.put("/{transaction_id}", response_model=TransactionRead)
async def update_transaction_route(
    transaction_id: int,
    data: TransactionUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_permissions(PERM_EDIT_TRANSACTION)),
):
    tx = await get_transaction(db, transaction_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(tx, field, value)
    updated = await save_transaction(db, tx)
    logger.info("Transaction %s updated by user %s", transaction_id, current_user.id)
    await post_transaction_update(db, tx.child_id)
    return updated


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction_route(
    transaction_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_permissions(PERM_DELETE_TRANSACTION)),
):
    tx = await get_transaction(db, transaction_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    await delete_transaction(db, tx)
    logger.info("Transaction %s deleted by user %s", transaction_id, current_user.id)
    await post_transaction_update(db, tx.child_id)


@router.get("/child/{child_id}", response_model=LedgerResponse)
async def get_ledger(
    child_id: int,
    account_id: int | None = None,
    db: AsyncSession = Depends(get_session),
    identity: tuple[str, Child | User] = Depends(get_current_identity),
):
    """Return the full ledger and balance for a child, optionally filtered by account."""
    kind, obj = identity
    if kind == "child":
        child = obj
        if child.id != child_id:
            raise HTTPException(status_code=403, detail="Not authorized")
    else:
        user: User = obj
        if user.role != "admin":
            user_perms = {p.name for p in user.permissions}
            if PERM_VIEW_TRANSACTIONS not in user_perms:
                raise HTTPException(status_code=403, detail="Insufficient permissions")
            link = await get_child_user_link(db, user.id, child_id)
            if not link:
                raise HTTPException(status_code=404, detail="Child not found")
            if (
                PERM_VIEW_TRANSACTIONS not in link.permissions
                and not link.is_owner
            ):
                raise HTTPException(status_code=403, detail="Insufficient permissions")
    
    from app.crud import get_transactions_by_child, get_transactions_by_account, calculate_balance, calculate_total_balance, get_checking_account_by_child
    
    if account_id:
        # Filter by specific account
        from app.crud import get_account
        account = await get_account(db, account_id)
        if not account or account.child_id != child_id:
            raise HTTPException(status_code=404, detail="Account not found")
        transactions = await get_transactions_by_account(db, account_id)
        balance = await calculate_balance(db, account_id)
    else:
        # Return all transactions for child
        transactions = await get_transactions_by_child(db, child_id)
        # For backward compatibility, return total balance
        balance = await calculate_total_balance(db, child_id)
    
    return {"balance": balance, "transactions": transactions}
