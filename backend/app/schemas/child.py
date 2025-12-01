"""Pydantic models for child accounts and updates."""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class ChildCreate(BaseModel):
    first_name: str
    access_code: str
    frozen: Optional[bool] = False
    created_at: Optional[datetime] = None  # Optional: allows back-dating account creation


class ChildRead(BaseModel):
    id: int
    first_name: str
    frozen: bool = Field(alias="account_frozen")
    interest_rate: float | None = None
    penalty_interest_rate: float | None = None
    cd_penalty_rate: float | None = None
    total_interest_earned: float | None = None

    class Config:
        model_config = {"from_attributes": True}


class ChildLogin(BaseModel):
    access_code: str


class InterestRateUpdate(BaseModel):
    interest_rate: float
    account_type: str = "checking"  # "checking", "savings", "college_savings"


class PenaltyRateUpdate(BaseModel):
    penalty_interest_rate: float
    account_type: str = "checking"  # "checking", "savings", "college_savings"


class CDPenaltyRateUpdate(BaseModel):
    cd_penalty_rate: float


class ChildUpdate(BaseModel):
    first_name: str | None = None
    access_code: str | None = None
    frozen: bool | None = None


class AccessCodeUpdate(BaseModel):
    access_code: str


class AccountRead(BaseModel):
    id: int
    account_type: str
    balance: float
    available_balance: float | None = None  # For savings accounts with lockup
    interest_rate: float
    lockup_period_days: int | None = None


class ChildAccountsResponse(BaseModel):
    checking: AccountRead
    savings: AccountRead
    college_savings: AccountRead
    total_balance: float
