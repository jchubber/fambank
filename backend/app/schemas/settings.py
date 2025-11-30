from pydantic import BaseModel

"""Pydantic models for application configuration settings."""

from pydantic import BaseModel


class SettingsRead(BaseModel):
    site_name: str
    site_url: str
    savings_account_interest_rate: float
    college_savings_account_interest_rate: float
    savings_account_lockup_period_days: int
    default_penalty_interest_rate: float
    default_cd_penalty_rate: float
    service_fee_amount: float
    service_fee_is_percentage: bool
    overdraft_fee_amount: float
    overdraft_fee_is_percentage: bool
    overdraft_fee_daily: bool
    currency_symbol: str
    public_registration_disabled: bool
    chores_ui_enabled: bool
    loans_ui_enabled: bool
    coupons_ui_enabled: bool
    messages_ui_enabled: bool


class SettingsUpdate(BaseModel):
    site_name: str | None = None
    site_url: str | None = None
    savings_account_interest_rate: float | None = None
    college_savings_account_interest_rate: float | None = None
    savings_account_lockup_period_days: int | None = None
    default_penalty_interest_rate: float | None = None
    default_cd_penalty_rate: float | None = None
    service_fee_amount: float | None = None
    service_fee_is_percentage: bool | None = None
    overdraft_fee_amount: float | None = None
    overdraft_fee_is_percentage: bool | None = None
    overdraft_fee_daily: bool | None = None
    currency_symbol: str | None = None
    public_registration_disabled: bool | None = None
    chores_ui_enabled: bool | None = None
    loans_ui_enabled: bool | None = None
    coupons_ui_enabled: bool | None = None
    messages_ui_enabled: bool | None = None
