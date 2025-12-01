"""Routes for managing child accounts and related settings."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone
from app.schemas import (
    ChildCreate,
    ChildRead,
    ChildLogin,
    InterestRateUpdate,
    PenaltyRateUpdate,
    CDPenaltyRateUpdate,
    AccessCodeUpdate,
    ShareCodeCreate,
    ShareCodeRead,
    ParentAccess,
    AccountRead,
    ChildAccountsResponse,
)
from app.models import Child, User
from app.database import get_session
from app.crud import (
    create_child_for_user,
    get_children_by_user,
    get_child_by_id,
    get_child_by_access_code,
    set_child_frozen,
    set_interest_rate,
    set_penalty_interest_rate,
    set_cd_penalty_rate,
    get_account_by_child,
    get_checking_account_by_child,
    post_transaction_update,
    save_child,
    get_child_user_link,
    create_share_code,
    get_share_code,
    mark_share_code_used,
    link_child_to_user,
    get_parents_for_child,
    remove_child_link,
    get_accounts_by_child,
    get_account_by_child_and_type,
    calculate_balance,
    calculate_total_balance,
    calculate_available_balance,
)
from app.auth import (
    get_current_user,
    require_role,
    create_access_token,
    require_permissions,
    get_current_identity,
)
from app.acl import (
    PERM_ADD_CHILD,
    PERM_REMOVE_CHILD,
    PERM_FREEZE_CHILD,
    PERM_VIEW_TRANSACTIONS,
    PERM_MANAGE_CHILD_SETTINGS,
)

router = APIRouter(prefix="/children", tags=["children"])


async def _ensure_link(
    db: AsyncSession,
    user_id: int,
    child_id: int,
    perm: str | None = None,
    require_owner: bool = False,
):
    link = await get_child_user_link(db, user_id, child_id)
    if not link:
        raise HTTPException(status_code=404, detail="Child not found")
    if require_owner and not link.is_owner:
        raise HTTPException(status_code=403, detail="Not authorized")
    if perm and perm not in link.permissions and link.is_owner is False:
        # owners implicitly have all permissions
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return link


@router.get("/me", response_model=ChildRead)
async def read_current_child(
    identity: tuple[str, Child | User] = Depends(get_current_identity),
    db: AsyncSession = Depends(get_session),
):
    kind, obj = identity
    if kind == "child":
        child = obj
    else:
        raise HTTPException(status_code=403, detail="Not a child token")
    account = await get_account_by_child(db, child.id)
    return ChildRead(
        id=child.id,
        first_name=child.first_name,
        account_frozen=child.account_frozen,
        interest_rate=account.interest_rate if account else None,
        penalty_interest_rate=account.penalty_interest_rate if account else None,
        cd_penalty_rate=account.cd_penalty_rate if account else None,
        total_interest_earned=account.total_interest_earned if account else None,
    )


@router.post("/{child_id}/sharecode", response_model=ShareCodeRead)
async def generate_share_code(
    child_id: int,
    data: ShareCodeCreate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("parent", "admin")),
):
    child = await get_child_by_id(db, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    if current_user.role != "admin":
        await _ensure_link(db, current_user.id, child_id, require_owner=True)
    share = await create_share_code(db, child_id, current_user.id, data.permissions)
    return ShareCodeRead(code=share.code)


@router.post("/sharecode/{code}", response_model=ChildRead)
async def redeem_share_code(
    code: str,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_role("parent", "admin")),
):
    share = await get_share_code(db, code)
    if not share or share.used_by is not None:
        raise HTTPException(status_code=404, detail="Invalid code")
    if current_user.role != "admin":
        existing = await get_child_user_link(db, current_user.id, share.child_id)
        if existing:
            raise HTTPException(status_code=400, detail="Already linked")
    await link_child_to_user(db, share.child_id, current_user.id, share.permissions)
    await mark_share_code_used(db, share, current_user.id)
    child = await get_child_by_id(db, share.child_id)
    account = await get_account_by_child(db, share.child_id)
    return ChildRead(
        id=child.id,
        first_name=child.first_name,
        account_frozen=child.account_frozen,
        interest_rate=account.interest_rate if account else None,
        penalty_interest_rate=account.penalty_interest_rate if account else None,
        cd_penalty_rate=account.cd_penalty_rate if account else None,
        total_interest_earned=account.total_interest_earned if account else None,
    )


@router.get("/me/parents", response_model=list[ParentAccess])
async def list_my_parents(
    identity: tuple[str, Child | User] = Depends(get_current_identity),
    db: AsyncSession = Depends(get_session),
):
    """List parents linked to the authenticated child."""
    kind, obj = identity
    if kind != "child":
        raise HTTPException(status_code=403, detail="Not a child token")
    links = await get_parents_for_child(db, obj.id)
    return [
        ParentAccess(
            user_id=l.user.id,
            name=l.user.name,
            email=l.user.email,
            permissions=l.permissions,
            is_owner=l.is_owner,
        )
        for l in links
    ]


@router.get("/{child_id}/parents", response_model=list[ParentAccess])
async def list_child_parents(
    child_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_permissions(PERM_MANAGE_CHILD_SETTINGS)),
):
    child = await get_child_by_id(db, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    if current_user.role != "admin":
        await _ensure_link(db, current_user.id, child_id, PERM_MANAGE_CHILD_SETTINGS)
    links = await get_parents_for_child(db, child_id)
    return [
        ParentAccess(
            user_id=l.user.id,
            name=l.user.name,
            email=l.user.email,
            permissions=l.permissions,
            is_owner=l.is_owner,
        )
        for l in links
    ]


@router.delete("/{child_id}/parents/{parent_id}", status_code=204)
async def remove_parent_access(
    child_id: int,
    parent_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_permissions(PERM_MANAGE_CHILD_SETTINGS)),
):
    child = await get_child_by_id(db, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    if current_user.role != "admin":
        await _ensure_link(db, current_user.id, child_id, PERM_MANAGE_CHILD_SETTINGS)
    link = await get_child_user_link(db, parent_id, child_id)
    if not link or link.is_owner:
        raise HTTPException(status_code=404, detail="Parent not found")
    await remove_child_link(db, child_id, parent_id)
    return


@router.put("/{child_id}/access-code", response_model=ChildRead)
async def update_access_code(
    child_id: int,
    data: AccessCodeUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_permissions(PERM_MANAGE_CHILD_SETTINGS)),
):
    """Update the login access code for a child."""

    child = await get_child_by_id(db, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    if current_user.role != "admin":
        await _ensure_link(db, current_user.id, child_id, PERM_MANAGE_CHILD_SETTINGS)
    existing = await get_child_by_access_code(db, data.access_code)
    if existing and existing.id != child_id:
        raise HTTPException(status_code=400, detail="Access code already in use")
    child.access_code = data.access_code
    updated = await save_child(db, child)
    account = await get_account_by_child(db, updated.id)
    return ChildRead(
        id=updated.id,
        first_name=updated.first_name,
        account_frozen=updated.account_frozen,
        interest_rate=account.interest_rate if account else None,
        penalty_interest_rate=account.penalty_interest_rate if account else None,
        cd_penalty_rate=account.cd_penalty_rate if account else None,
        total_interest_earned=account.total_interest_earned if account else None,
    )


@router.post("/", response_model=ChildRead)
async def create_child_route(
    child: ChildCreate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_permissions(PERM_ADD_CHILD)),
):
    """Create a new child and associated account for the current parent."""
    existing = await get_child_by_access_code(db, child.access_code)
    if existing:
        raise HTTPException(status_code=400, detail="Access code already in use")
    
    # Validate and handle custom created_at timestamp (only for parents and admins)
    created_at = child.created_at
    if created_at is not None:
        # Only parents and admins can set custom created_at
        if current_user.role not in ("admin", "parent"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only parents and admins can set custom account creation dates"
            )
        
        # Validate created_at is not in the future
        now = datetime.now(timezone.utc)
        if created_at.tzinfo is None:
            # Assume UTC if no timezone info
            created_at = created_at.replace(tzinfo=timezone.utc)
        if created_at > now:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Account creation date cannot be in the future"
            )
    
    child_model = Child(
        first_name=child.first_name,
        access_code=child.access_code,
        account_frozen=child.frozen,
    )
    # Set created_at if provided, otherwise let default_factory handle it
    if created_at is not None:
        # Remove timezone info for storage (database stores naive UTC)
        if created_at.tzinfo is not None:
            created_at = created_at.replace(tzinfo=None)
        child_model.created_at = created_at
    
    new_child = await create_child_for_user(db, child_model, current_user.id)
    account = await get_account_by_child(db, new_child.id)
    return ChildRead(
        id=new_child.id,
        first_name=new_child.first_name,
        account_frozen=new_child.account_frozen,
        interest_rate=account.interest_rate if account else None,
        penalty_interest_rate=account.penalty_interest_rate if account else None,
        cd_penalty_rate=account.cd_penalty_rate if account else None,
        total_interest_earned=account.total_interest_earned if account else None,
    )


@router.get("/", response_model=list[ChildRead])
async def list_children(
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_permissions(PERM_ADD_CHILD)),
):
    """List children belonging to the authenticated parent."""
    children = await get_children_by_user(db, current_user.id)
    result = []
    for c in children:
        account = await get_account_by_child(db, c.id)
        result.append(
            ChildRead(
                id=c.id,
                first_name=c.first_name,
                account_frozen=c.account_frozen,
                interest_rate=account.interest_rate if account else None,
                penalty_interest_rate=account.penalty_interest_rate if account else None,
                cd_penalty_rate=account.cd_penalty_rate if account else None,
                total_interest_earned=(
                    account.total_interest_earned if account else None
                ),
            )
        )
    return result


@router.get("/{child_id}/accounts", response_model=ChildAccountsResponse)
async def get_child_accounts(
    child_id: int,
    db: AsyncSession = Depends(get_session),
    identity: tuple[str, Child | User] = Depends(get_current_identity),
):
    """Return all accounts for a child with balances."""
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
    
    checking = await get_account_by_child_and_type(db, child_id, "checking")
    savings = await get_account_by_child_and_type(db, child_id, "savings")
    college_savings = await get_account_by_child_and_type(db, child_id, "college_savings")
    
    if not checking or not savings or not college_savings:
        raise HTTPException(status_code=404, detail="Accounts not found")
    
    checking_balance = await calculate_balance(db, checking.id)
    savings_balance = await calculate_balance(db, savings.id)
    savings_available = await calculate_available_balance(db, savings.id)
    college_balance = await calculate_balance(db, college_savings.id)
    total = await calculate_total_balance(db, child_id)
    
    return ChildAccountsResponse(
        checking=AccountRead(
            id=checking.id,
            account_type=checking.account_type,
            balance=checking_balance,
            available_balance=None,
            interest_rate=checking.interest_rate,
            lockup_period_days=None,
        ),
        savings=AccountRead(
            id=savings.id,
            account_type=savings.account_type,
            balance=savings_balance,
            available_balance=savings_available,
            interest_rate=savings.interest_rate,
            lockup_period_days=savings.lockup_period_days,
        ),
        college_savings=AccountRead(
            id=college_savings.id,
            account_type=college_savings.account_type,
            balance=college_balance,
            available_balance=None,
            interest_rate=college_savings.interest_rate,
            lockup_period_days=None,
        ),
        total_balance=total,
    )


@router.get("/{child_id}", response_model=ChildRead)
async def get_child_route(
    child_id: int,
    db: AsyncSession = Depends(get_session),
    identity: tuple[str, Child | User] = Depends(get_current_identity),
):
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
            children = await get_children_by_user(db, user.id)
            if child_id not in [c.id for c in children]:
                raise HTTPException(status_code=404, detail="Child not found")
        child = await get_child_by_id(db, child_id)
        if not child:
            raise HTTPException(status_code=404, detail="Child not found")
    account = await get_account_by_child(db, child_id)
    return ChildRead(
        id=child.id,
        first_name=child.first_name,
        account_frozen=child.account_frozen,
        interest_rate=account.interest_rate if account else None,
        penalty_interest_rate=account.penalty_interest_rate if account else None,
        cd_penalty_rate=account.cd_penalty_rate if account else None,
        total_interest_earned=account.total_interest_earned if account else None,
    )


@router.post("/{child_id}/freeze", response_model=ChildRead)
async def freeze_child(
    child_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_permissions(PERM_FREEZE_CHILD)),
):
    child = await get_child_by_id(db, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    if current_user.role != "admin":
        await _ensure_link(db, current_user.id, child_id, PERM_FREEZE_CHILD)
    updated = await set_child_frozen(db, child_id, True)
    account = await get_account_by_child(db, child_id)
    return ChildRead(
        id=updated.id,
        first_name=updated.first_name,
        account_frozen=updated.account_frozen,
        interest_rate=account.interest_rate if account else None,
        penalty_interest_rate=account.penalty_interest_rate if account else None,
        cd_penalty_rate=account.cd_penalty_rate if account else None,
        total_interest_earned=account.total_interest_earned if account else None,
    )


@router.post("/{child_id}/unfreeze", response_model=ChildRead)
async def unfreeze_child(
    child_id: int,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_permissions(PERM_FREEZE_CHILD)),
):
    child = await get_child_by_id(db, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    if current_user.role != "admin":
        children = await get_children_by_user(db, current_user.id)
        if child_id not in [c.id for c in children]:
            raise HTTPException(status_code=404, detail="Child not found")
    updated = await set_child_frozen(db, child_id, False)
    account = await get_account_by_child(db, child_id)
    return ChildRead(
        id=updated.id,
        first_name=updated.first_name,
        account_frozen=updated.account_frozen,
        interest_rate=account.interest_rate if account else None,
        penalty_interest_rate=account.penalty_interest_rate if account else None,
        cd_penalty_rate=account.cd_penalty_rate if account else None,
        total_interest_earned=account.total_interest_earned if account else None,
    )


@router.put("/{child_id}/interest-rate", response_model=ChildRead)
async def update_interest_rate(
    child_id: int,
    data: InterestRateUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_permissions(PERM_MANAGE_CHILD_SETTINGS)),
):
    child = await get_child_by_id(db, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    if current_user.role != "admin":
        await _ensure_link(db, current_user.id, child_id, PERM_MANAGE_CHILD_SETTINGS)
    await post_transaction_update(db, child_id)
    try:
        account = await set_interest_rate(db, child_id, data.interest_rate, data.account_type)
    except ValueError:
        raise HTTPException(status_code=404, detail="Account not found")
    # Return checking account for backward compatibility
    checking_account = await get_checking_account_by_child(db, child_id)
    return ChildRead(
        id=child.id,
        first_name=child.first_name,
        account_frozen=child.account_frozen,
        interest_rate=checking_account.interest_rate if checking_account else None,
        penalty_interest_rate=checking_account.penalty_interest_rate if checking_account else None,
        cd_penalty_rate=checking_account.cd_penalty_rate if checking_account else None,
        total_interest_earned=checking_account.total_interest_earned if checking_account else None,
    )


@router.put("/{child_id}/penalty-interest-rate", response_model=ChildRead)
async def update_penalty_interest_rate(
    child_id: int,
    data: PenaltyRateUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_permissions(PERM_MANAGE_CHILD_SETTINGS)),
):
    child = await get_child_by_id(db, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    if current_user.role != "admin":
        await _ensure_link(db, current_user.id, child_id, PERM_MANAGE_CHILD_SETTINGS)
    await post_transaction_update(db, child_id)
    try:
        account = await set_penalty_interest_rate(
            db, child_id, data.penalty_interest_rate, data.account_type
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Account not found")
    # Return checking account for backward compatibility
    checking_account = await get_checking_account_by_child(db, child_id)
    return ChildRead(
        id=child.id,
        first_name=child.first_name,
        account_frozen=child.account_frozen,
        interest_rate=checking_account.interest_rate if checking_account else None,
        penalty_interest_rate=checking_account.penalty_interest_rate if checking_account else None,
        cd_penalty_rate=checking_account.cd_penalty_rate if checking_account else None,
        total_interest_earned=checking_account.total_interest_earned if checking_account else None,
    )


@router.put("/{child_id}/cd-penalty-rate", response_model=ChildRead)
async def update_cd_penalty_rate(
    child_id: int,
    data: CDPenaltyRateUpdate,
    db: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_permissions(PERM_MANAGE_CHILD_SETTINGS)),
):
    child = await get_child_by_id(db, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="Child not found")
    if current_user.role != "admin":
        await _ensure_link(db, current_user.id, child_id, PERM_MANAGE_CHILD_SETTINGS)
    try:
        account = await set_cd_penalty_rate(db, child_id, data.cd_penalty_rate)
    except ValueError:
        raise HTTPException(status_code=404, detail="Account not found")
    return ChildRead(
        id=child.id,
        first_name=child.first_name,
        account_frozen=child.account_frozen,
        interest_rate=account.interest_rate if account else None,
        penalty_interest_rate=account.penalty_interest_rate if account else None,
        cd_penalty_rate=account.cd_penalty_rate if account else None,
        total_interest_earned=account.total_interest_earned if account else None,
    )


@router.post("/login")
async def child_login(
    credentials: ChildLogin,
    db: AsyncSession = Depends(get_session),
):
    """Issue a token for a child using their access code."""
    child = await get_child_by_access_code(db, credentials.access_code)
    if not child:
        raise HTTPException(status_code=401, detail="Invalid access code")
    if child.account_frozen:
        raise HTTPException(status_code=403, detail="Account is frozen")
    token = create_access_token(data={"sub": f"child:{child.id}"})
    return {"access_token": token, "token_type": "bearer"}
