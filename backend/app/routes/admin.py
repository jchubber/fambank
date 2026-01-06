"""Administrative endpoints for managing users, children and transactions."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import get_session
from app.auth import require_role, get_password_hash
from app.models import User, Child, Transaction, Permission, UserPermissionLink
from app.schemas import (
    UserCreate,
    UserResponse,
    UserUpdate,
    ChildRead,
    ChildUpdate,
    TransactionRead,
    TransactionUpdate,
    PermissionRead,
    PermissionsUpdate,
    Promotion,
)
from app.crud import (
    get_all_users,
    get_user,
    save_user,
    delete_user,
    create_user,
    get_user_by_email,
    get_all_children,
    get_child,
    save_child,
    delete_child,
    get_all_transactions,
    get_transaction,
    save_transaction,
    delete_transaction,
    get_account_by_child,
    get_all_permissions,
    assign_permissions_by_names,
    remove_permissions_by_names,
    apply_promotion,
    get_all_accounts,
    recalc_interest,
    get_checking_account_by_child,
    get_current_rate_for_account_type,
)

router = APIRouter(prefix="/admin", tags=["admin"])


async def _build_child_read_with_rates(
    db: AsyncSession, child: Child, account
) -> ChildRead:
    """Build a ChildRead response with rates computed from global source."""
    if not account:
        # Get checking account as default
        account = await get_checking_account_by_child(db, child.id)
    
    if account:
        # Get current rates from global history (for checking account)
        interest_rate, penalty_interest_rate = await get_current_rate_for_account_type(
            db, account.account_type
        )
        return ChildRead(
            id=child.id,
            first_name=child.first_name,
            account_frozen=child.account_frozen,
            interest_rate=interest_rate,
            penalty_interest_rate=penalty_interest_rate,
            cd_penalty_rate=account.cd_penalty_rate,
            total_interest_earned=account.total_interest_earned,
        )
    else:
        return ChildRead(
            id=child.id,
            first_name=child.first_name,
            account_frozen=child.account_frozen,
            interest_rate=None,
            penalty_interest_rate=None,
            cd_penalty_rate=None,
            total_interest_earned=None,
        )


@router.get("/users", response_model=list[UserResponse])
async def admin_list_users(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    return await get_all_users(db)


@router.post("/users", response_model=UserResponse)
async def admin_create_parent(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    existing = await get_user_by_email(db, user_in.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    new_user = User(
        name=user_in.name,
        email=user_in.email,
        password_hash=user_in.password,
        role="parent",
        status="active",
    )
    created = await create_user(db, new_user)
    return created


@router.get("/permissions", response_model=list[PermissionRead])
async def list_permissions(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    return await get_all_permissions(db)


@router.post("/users/{user_id}/permissions", response_model=list[PermissionRead])
async def add_permissions_to_user(
    user_id: int,
    perms: PermissionsUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    user = await get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await assign_permissions_by_names(db, user, perms.permissions)
    result = await db.execute(
        select(Permission)
        .join(UserPermissionLink)
        .where(UserPermissionLink.user_id == user.id)
    )
    return result.scalars().all()


@router.delete("/users/{user_id}/permissions", response_model=list[PermissionRead])
async def remove_permissions_from_user(
    user_id: int,
    perms: PermissionsUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    user = await get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await remove_permissions_by_names(db, user, perms.permissions)
    result = await db.execute(
        select(Permission)
        .join(UserPermissionLink)
        .where(UserPermissionLink.user_id == user.id)
    )
    return result.scalars().all()


@router.get("/users/{user_id}", response_model=UserResponse)
async def admin_get_user(
    user_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    user = await get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put("/users/{user_id}", response_model=UserResponse)
async def admin_update_user(
    user_id: int,
    data: UserUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    user = await get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if data.password is not None:
        user.password_hash = get_password_hash(data.password)
    for field, value in data.model_dump(
        exclude_unset=True, exclude={"password"}
    ).items():
        setattr(user, field, value)
    updated = await save_user(db, user)
    if data.role is not None:
        from app.acl import get_default_permissions_for_role

        await remove_permissions_by_names(
            db, updated, [p.name for p in updated.permissions]
        )
        defaults = get_default_permissions_for_role(updated.role)
        await assign_permissions_by_names(db, updated, defaults)
    return updated


@router.post("/users/{user_id}/approve", response_model=UserResponse)
async def admin_approve_user(
    user_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    user = await get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.status = "active"
    updated = await save_user(db, user)
    return updated


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    user = await get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await delete_user(db, user)


@router.get("/children", response_model=list[ChildRead])
async def admin_list_children(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    children = await get_all_children(db)
    result = []
    for c in children:
        account = await get_account_by_child(db, c.id)
        result.append(await _build_child_read_with_rates(db, c, account))
    return result


@router.get("/children/{child_id}", response_model=ChildRead)
async def admin_get_child(
    child_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    child = await get_child(db, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    account = await get_account_by_child(db, child_id)
    return await _build_child_read_with_rates(db, child, account)


@router.put("/children/{child_id}", response_model=ChildRead)
async def admin_update_child(
    child_id: int,
    data: ChildUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    child = await get_child(db, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "frozen":
            setattr(child, "account_frozen", value)
        else:
            setattr(child, field, value)
    updated = await save_child(db, child)
    account = await get_account_by_child(db, child_id)
    return await _build_child_read_with_rates(db, updated, account)


@router.delete("/children/{child_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_child(
    child_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    child = await get_child(db, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    await delete_child(db, child)


@router.get("/transactions", response_model=list[TransactionRead])
async def admin_list_transactions(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    return await get_all_transactions(db)


@router.get("/transactions/{transaction_id}", response_model=TransactionRead)
async def admin_get_transaction(
    transaction_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    tx = await get_transaction(db, transaction_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return tx


@router.put("/transactions/{transaction_id}", response_model=TransactionRead)
async def admin_update_transaction(
    transaction_id: int,
    data: TransactionUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    tx = await get_transaction(db, transaction_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(tx, field, value)
    updated = await save_transaction(db, tx)
    return updated


@router.delete("/transactions/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_transaction(
    transaction_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    tx = await get_transaction(db, transaction_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    await delete_transaction(db, tx)


@router.post("/promotions")
async def run_promotion(
    promo: Promotion,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    count = await apply_promotion(
        db, promo.amount, promo.is_percentage, promo.credit, promo.memo
    )
    return {"accounts_updated": count}


@router.post("/recalc-all-interest")
async def recalc_all_interest(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("admin")),
):
    """Recalculate interest for all savings and college_savings accounts."""
    accounts = await get_all_accounts(db)
    interest_accounts = [
        acc for acc in accounts 
        if acc.account_type in ("savings", "college_savings")
    ]
    
    count = 0
    for account in interest_accounts:
        try:
            await recalc_interest(db, account.id)
            count += 1
        except Exception as e:
            # Log error but continue with other accounts
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error recalculating interest for account {account.id}: {e}")
    
    return {"accounts_processed": count, "total_accounts": len(interest_accounts)}
