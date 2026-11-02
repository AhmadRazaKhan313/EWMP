"""Public (no login) endpoints for candidates and new hires, reached through a
secret link: the offer page and the pre-boarding portal (N-01).

Every route is rate limited per IP. Tokens are 256-bit random values that are
only stored as a hash, so a database leak does not expose working links."""
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.client_ip import get_client_ip
from app.core.database import get_db
from app.core.exceptions import RateLimitExceededError, ValidationError
from app.core.rate_limit import get_limiter
from app.schemas.onboarding import PreboardingSave, PublicAccept, PublicDecline
from app.services.documents import MAX_UPLOAD_BYTES
from app.services.onboarding import OnboardingService
from app.services.onboarding_offers import OfferService

router = APIRouter(prefix="/public", tags=["Public — offers & pre-boarding"])

_NO_TENANT = uuid4()  # replaced by the token's own tenant inside the service
PER_MINUTE = 30


async def _limit(request: Request) -> None:
    res = await get_limiter().hit(f"public-onboarding:{get_client_ip(request)}", PER_MINUTE, 60)
    if not res.allowed:
        raise RateLimitExceededError()


@router.get("/offers/{token}", summary="Candidate: view the offer")
async def view_offer(token: str, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    await _limit(request)
    return await OfferService(db, _NO_TENANT).public_view(token)


@router.post("/offers/{token}/accept", summary="Candidate: accept the offer (typed-name e-signature)")
async def accept_offer(token: str, data: PublicAccept, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    await _limit(request)
    if not data.agree:
        raise ValidationError("Tick the box to confirm you accept the offer.")
    return await OfferService(db, _NO_TENANT).public_accept(
        token, full_name=data.full_name, ip=get_client_ip(request), user_agent=request.headers.get("user-agent", ""))


@router.post("/offers/{token}/decline", summary="Candidate: decline the offer")
async def decline_offer(token: str, data: PublicDecline, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    await _limit(request)
    return await OfferService(db, _NO_TENANT).public_decline(token, reason=data.reason)


@router.get("/preboarding/{token}", summary="New hire: open the pre-boarding form")
async def preboarding_view(token: str, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    await _limit(request)
    return await OnboardingService(db, _NO_TENANT).preboarding_view(token)


@router.put("/preboarding/{token}", summary="New hire: save or submit the form")
async def preboarding_save(token: str, data: PreboardingSave, request: Request,
                           db: AsyncSession = Depends(get_db)) -> dict:
    await _limit(request)
    return await OnboardingService(db, _NO_TENANT).preboarding_save(
        token, data.form, submit=data.submit, acknowledge_policy=data.acknowledge_policy)


@router.post("/preboarding/{token}/documents/{doc_id}", summary="New hire: upload a requested document")
async def preboarding_upload(token: str, doc_id: UUID, request: Request, file: UploadFile = File(...),
                             db: AsyncSession = Depends(get_db)) -> dict:
    await _limit(request)
    content = await file.read(MAX_UPLOAD_BYTES + 1)  # never buffer more than the limit
    return await OnboardingService(db, _NO_TENANT).preboarding_upload(
        token, doc_id, file_name=file.filename or "document", content=content)
