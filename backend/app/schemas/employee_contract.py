from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field


class ContractCreate(BaseModel):
    contract_type: str = Field(..., max_length=30)
    start_date: date
    end_date: date | None = None
    renewal_alert_days: int = Field(30, ge=1, le=365)
    document_id: UUID | None = None
    notes: str | None = Field(None, max_length=2000)


class ContractUpdate(BaseModel):
    contract_type: str | None = Field(None, max_length=30)
    start_date: date | None = None
    end_date: date | None = None
    renewal_alert_days: int | None = Field(None, ge=1, le=365)
    document_id: UUID | None = None
    notes: str | None = Field(None, max_length=2000)


class ContractRenew(BaseModel):
    end_date: date | None = None
    start_date: date | None = None
    contract_type: str | None = Field(None, max_length=30)
    renewal_alert_days: int | None = Field(None, ge=1, le=365)
    document_id: UUID | None = None
    notes: str | None = Field(None, max_length=2000)


class ContractTerminate(BaseModel):
    reason: str | None = Field(None, max_length=500)
