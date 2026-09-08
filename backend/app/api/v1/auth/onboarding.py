"""
Employee onboarding endpoint.
Creates a User account and returns the user_id for the employee profile.
"""

import uuid
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import EmailAlreadyExistsError
from app.core.security import hash_password, generate_password_reset_token
from app.models.user import User
from app.models.organization import Organization
from app.permissions.dependencies import get_tenant_id, require_permission

router = APIRouter(prefix="/auth", tags=["Auth — Onboarding"])


class RegisterEmployeeRequest(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr


class RegisterEmployeeResponse(BaseModel):
    user_id: str
    email: str
    temporary_password: str


@router.post(
    "/register-employee",
    response_model=RegisterEmployeeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user account for a new employee",
)
async def register_employee_user(
    data: RegisterEmployeeRequest,
    current_user: User = Depends(require_permission("employees.create")),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> RegisterEmployeeResponse:
    """
    Create a User account during employee onboarding.
    Returns a temporary password that must be changed on first login.
    """
    # Check email uniqueness
    existing = await db.execute(
        select(User).where(User.email_normalized == data.email.lower())
    )
    if existing.scalar_one_or_none():
        raise EmailAlreadyExistsError(
            f"An account with email {data.email} already exists"
        )

    # Generate temporary password
    temp_password = generate_password_reset_token()[:12] + "Aa1!"

    user = User(
        organization_id=tenant_id,
        email=data.email,
        email_normalized=data.email.lower().strip(),
        password_hash=hash_password(temp_password),
        first_name=data.first_name,
        last_name=data.last_name,
        is_active=True,
        is_email_verified=False,
    )
    db.add(user)
    await db.flush()

    return RegisterEmployeeResponse(
        user_id=str(user.id),
        email=user.email,
        temporary_password=temp_password,
    )
