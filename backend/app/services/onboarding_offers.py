"""Offer management (N-01): draft -> approval -> send -> accept/decline ->
convert to employee, with revise / revoke / expiry.

Statuses: draft, pending_approval, approved, sent, viewed, accepted, declined,
expired, revoked, revised (superseded by a newer version).
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.models.onboarding import Offer
from app.services.onboarding_common import (
    OFFER_VALID_DAYS, hash_token, new_token, notify, now, offer_url, queue, recipient_ids,
)

EDITABLE = {"draft"}
OPEN_FOR_RESPONSE = {"sent", "viewed"}

DEFAULT_BODY = (
    "Dear {{candidate_name}},\n\n"
    "We are pleased to offer you the position of {{job_title}} at {{company_name}}, "
    "starting on {{joining_date}}.\n\n"
    "Your gross monthly salary will be {{currency}} {{salary}}. "
    "{{probation_line}}\n\n"
    "This offer is valid until {{expiry_date}}. To accept, please use the secure "
    "link we sent you and confirm with your full name.\n\n"
    "We look forward to welcoming you to the team.\n\n"
    "Regards,\n{{company_name}} HR"
)

_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render_body(template: str, values: dict[str, str]) -> str:
    """Replace {{var}} placeholders. Unknown placeholders are left as-is so HR
    notices a typo instead of it silently disappearing."""
    return _VAR.sub(lambda m: values.get(m.group(1), m.group(0)), template)


def _money(value) -> str:
    if value is None:
        return "—"
    return f"{Decimal(value):,.0f}"


def serialize(o: Offer, *, include_body: bool = True) -> dict:
    out = {
        "id": str(o.id), "status": o.status, "version": o.version,
        "parent_offer_id": str(o.parent_offer_id) if o.parent_offer_id else None,
        "applicant_id": str(o.applicant_id) if o.applicant_id else None,
        "candidate_name": o.candidate_name, "candidate_email": o.candidate_email,
        "candidate_phone": o.candidate_phone, "job_title": o.job_title,
        "department_id": str(o.department_id) if o.department_id else None,
        "designation_id": str(o.designation_id) if o.designation_id else None,
        "branch_id": str(o.branch_id) if o.branch_id else None,
        "manager_id": str(o.manager_id) if o.manager_id else None,
        "template_id": str(o.template_id) if o.template_id else None,
        "employment_type": o.employment_type, "job_nature": o.job_nature,
        "salary": float(o.salary) if o.salary is not None else None, "currency": o.currency,
        "pay_items": o.pay_items or [], "joining_date": o.joining_date.isoformat(),
        "probation_months": o.probation_months,
        "expires_at": o.expires_at.isoformat() if o.expires_at else None,
        "approver_ids": o.approver_ids or [], "approvals": o.approvals or [],
        "sent_at": o.sent_at.isoformat() if o.sent_at else None,
        "viewed_at": o.viewed_at.isoformat() if o.viewed_at else None,
        "responded_at": o.responded_at.isoformat() if o.responded_at else None,
        "decline_reason": o.decline_reason, "accepted_name": o.accepted_name,
        "employee_id": str(o.employee_id) if o.employee_id else None,
        "created_at": o.created_at.isoformat() if o.created_at else None,
    }
    if include_body:
        out["body"] = o.body
    return out


class OfferService:
    def __init__(self, db: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id

    # ── helpers ────────────────────────────────────────────────────────────
    async def _get(self, offer_id: uuid.UUID, *, lock: bool = False) -> Offer:
        q = select(Offer).where(
            Offer.id == offer_id, Offer.tenant_id == self.tenant_id, Offer.is_deleted == False  # noqa: E712
        )
        if lock:
            q = q.with_for_update()
        offer = (await self.db.execute(q)).scalar_one_or_none()
        if offer is None:
            raise NotFoundError("Offer not found")
        await self._expire_if_due(offer)
        return offer

    async def _company_name(self) -> str:
        from app.models.organization import Organization

        org = (await self.db.execute(select(Organization).where(Organization.id == self.tenant_id))).scalar_one_or_none()
        return org.name if org else "the company"

    async def _expire_if_due(self, offer: Offer) -> None:
        if offer.status in OPEN_FOR_RESPONSE and offer.expires_at and offer.expires_at <= now():
            offer.status = "expired"  # the link keeps working so the candidate sees "expired", not an error
            await self.db.flush()

    async def _render(self, offer: Offer) -> str:
        probation = (
            f"The first {offer.probation_months} month(s) are a probation period."
            if offer.probation_months else ""
        )
        expiry = (offer.expires_at or (now() + timedelta(days=OFFER_VALID_DAYS))).date()
        return render_body(
            DEFAULT_BODY,
            {
                "candidate_name": offer.candidate_name, "job_title": offer.job_title,
                "company_name": await self._company_name(),
                "joining_date": offer.joining_date.strftime("%d %B %Y"),
                "currency": offer.currency, "salary": _money(offer.salary),
                "probation_line": probation, "expiry_date": expiry.strftime("%d %B %Y"),
            },
        )

    async def _check_approvers(self, ids: list) -> list[str]:
        from app.models.user import User

        clean: list[str] = []
        for raw in ids or []:
            try:
                uid = uuid.UUID(str(raw))
            except ValueError:
                raise ValidationError("Invalid approver id.")
            if str(uid) in clean:
                continue
            found = (await self.db.execute(
                select(User.id).where(User.id == uid, User.organization_id == self.tenant_id, User.is_deleted == False)  # noqa: E712
            )).scalar_one_or_none()
            if found is None:
                raise ValidationError("An approver does not belong to this organization.")
            clean.append(str(uid))
        return clean

    async def _check_refs(self, data: dict) -> None:
        """department/designation/branch/manager/template must be in this tenant."""
        from app.models.employee import Employee
        from app.models.onboarding import OnboardingTemplate
        from app.models.organization_structure import Branch, Department, Designation

        for key, model in (("department_id", Department), ("designation_id", Designation),
                           ("branch_id", Branch), ("manager_id", Employee),
                           ("template_id", OnboardingTemplate)):
            val = data.get(key)
            if val is None:
                continue
            ok = (await self.db.execute(
                select(model.id).where(model.id == val, model.tenant_id == self.tenant_id)
            )).scalar_one_or_none()
            if ok is None:
                raise ValidationError(f"Unknown {key.replace('_id', '').replace('_', ' ')}.")

    # ── queries ────────────────────────────────────────────────────────────
    async def list(self, *, status: str | None = None, search: str | None = None,
                   page: int = 1, page_size: int = 25) -> dict:
        base = select(Offer).where(Offer.tenant_id == self.tenant_id, Offer.is_deleted == False)  # noqa: E712
        if status:
            base = base.where(Offer.status == status)
        else:
            base = base.where(Offer.status != "revised")
        if search:
            like = f"%{search.strip()}%"
            base = base.where(or_(Offer.candidate_name.ilike(like), Offer.candidate_email.ilike(like),
                                  Offer.job_title.ilike(like)))
        total = (await self.db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        rows = (await self.db.execute(
            base.order_by(Offer.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )).scalars().all()
        for o in rows:
            await self._expire_if_due(o)
        return {"items": [serialize(o, include_body=False) for o in rows], "total": total,
                "page": page, "page_size": page_size}

    async def get(self, offer_id: uuid.UUID) -> dict:
        offer = await self._get(offer_id)
        out = serialize(offer)
        out["history"] = await self._history(offer)
        return out

    async def _history(self, offer: Offer) -> list[dict]:
        """All versions of this offer, oldest first."""
        root = offer
        seen = {root.id}
        while root.parent_offer_id and root.parent_offer_id not in seen:
            parent = (await self.db.execute(select(Offer).where(Offer.id == root.parent_offer_id))).scalar_one_or_none()
            if parent is None:
                break
            seen.add(parent.id)
            root = parent
        chain = [root]
        while True:
            child = (await self.db.execute(
                select(Offer).where(Offer.parent_offer_id == chain[-1].id, Offer.tenant_id == self.tenant_id)
            )).scalar_one_or_none()
            if child is None or child.id in {c.id for c in chain}:
                break
            chain.append(child)
        return [{"id": str(c.id), "version": c.version, "status": c.status} for c in chain]

    # ── create / edit ──────────────────────────────────────────────────────
    async def create(self, data: dict, actor_id: uuid.UUID) -> dict:
        await self._check_refs(data)
        data = dict(data)
        approvers = await self._check_approvers(data.pop("approver_ids", []))
        if data["joining_date"] < date.today():
            raise ValidationError("Joining date cannot be in the past.")
        applicant_id = data.get("applicant_id")
        if applicant_id is not None:
            from app.models.recruitment import Applicant

            ok = (await self.db.execute(
                select(Applicant.id).where(Applicant.id == applicant_id, Applicant.tenant_id == self.tenant_id)
            )).scalar_one_or_none()
            if ok is None:
                raise ValidationError("Unknown applicant.")
        body = data.pop("body", None)
        offer = Offer(tenant_id=self.tenant_id, created_by_id=actor_id, approver_ids=approvers, approvals=[], **data)
        offer.body = body or await self._render(offer)
        self.db.add(offer)
        await self.db.flush()
        return serialize(offer)

    async def update(self, offer_id: uuid.UUID, data: dict) -> dict:
        offer = await self._get(offer_id, lock=True)
        if offer.status not in EDITABLE:
            raise ConflictError("Only draft offers can be edited. Use 'revise' to change a sent offer.")
        await self._check_refs(data)
        data = dict(data)
        if "approver_ids" in data:
            offer.approver_ids = await self._check_approvers(data.pop("approver_ids") or [])
        if "joining_date" in data and data["joining_date"] < date.today():
            raise ValidationError("Joining date cannot be in the past.")
        rerender = "body" not in data and any(
            k in data for k in ("candidate_name", "job_title", "joining_date", "salary", "currency", "probation_months")
        )
        for k, v in data.items():
            setattr(offer, k, v)
        if rerender:
            offer.body = await self._render(offer)
        await self.db.flush()
        return serialize(offer)

    async def delete(self, offer_id: uuid.UUID) -> None:
        offer = await self._get(offer_id, lock=True)
        if offer.status != "draft":
            raise ConflictError("Only draft offers can be deleted. Revoke a sent offer instead.")
        offer.soft_delete()
        await self.db.flush()

    # ── approval chain ─────────────────────────────────────────────────────
    async def submit(self, offer_id: uuid.UUID) -> dict:
        offer = await self._get(offer_id, lock=True)
        if offer.status != "draft":
            raise ConflictError("Only a draft offer can be submitted.")
        if offer.salary is None:
            raise ValidationError("Enter the offered salary before submitting.")
        offer.approvals = []
        if not offer.approver_ids:
            offer.status = "approved"
        else:
            offer.status = "pending_approval"
            first = uuid.UUID(offer.approver_ids[0])
            notify(self.db, self.tenant_id, first, title="Offer awaiting your approval",
                   body=f"{offer.candidate_name} — {offer.job_title}", type_="offer_approval",
                   action_url=f"/onboarding/offers/{offer.id}", icon="file-check",
                   meta={"offer_id": str(offer.id)})
        await self.db.flush()
        return serialize(offer)

    async def decide(self, offer_id: uuid.UUID, actor_id: uuid.UUID, decision: str, note: str | None) -> dict:
        if decision not in ("approved", "rejected"):
            raise ValidationError("decision must be 'approved' or 'rejected'.")
        offer = await self._get(offer_id, lock=True)
        if offer.status != "pending_approval":
            raise ConflictError("This offer is not waiting for approval.")
        done = len(offer.approvals or [])
        expected = offer.approver_ids[done] if done < len(offer.approver_ids) else None
        if expected is None or str(actor_id) != expected:
            raise PermissionDeniedError("It is not your turn to approve this offer.")
        entry = {"user_id": str(actor_id), "decision": decision, "at": now().isoformat(), "note": (note or "")[:500]}
        offer.approvals = [*(offer.approvals or []), entry]
        if decision == "rejected":
            offer.status = "draft"
            if offer.created_by_id:
                notify(self.db, self.tenant_id, offer.created_by_id, title="Offer rejected",
                       body=f"{offer.candidate_name}: {entry['note'] or 'no note'}", type_="offer_rejected",
                       action_url=f"/onboarding/offers/{offer.id}", icon="file-x")
        elif len(offer.approvals) == len(offer.approver_ids):
            offer.status = "approved"
            if offer.created_by_id:
                notify(self.db, self.tenant_id, offer.created_by_id, title="Offer approved",
                       body=f"{offer.candidate_name} — ready to send", type_="offer_approved",
                       action_url=f"/onboarding/offers/{offer.id}", icon="file-check")
        else:
            nxt = uuid.UUID(offer.approver_ids[len(offer.approvals)])
            notify(self.db, self.tenant_id, nxt, title="Offer awaiting your approval",
                   body=f"{offer.candidate_name} — {offer.job_title}", type_="offer_approval",
                   action_url=f"/onboarding/offers/{offer.id}", icon="file-check")
        await self.db.flush()
        return serialize(offer)

    # ── send / resend / revoke / revise ────────────────────────────────────
    async def send(self, offer_id: uuid.UUID, *, valid_days: int | None = None) -> dict:
        offer = await self._get(offer_id, lock=True)
        if offer.status == "approved":
            pass
        elif offer.status in OPEN_FOR_RESPONSE:
            pass  # resend: issues a fresh link, old one stops working
        else:
            raise ConflictError("Only an approved offer can be sent.")
        if offer.joining_date < date.today():
            raise ValidationError("The joining date has passed. Revise the offer with a new date.")
        token = new_token()
        offer.token_hash = hash_token(token)
        offer.status = "sent"
        offer.sent_at = now()
        offer.viewed_at = None
        offer.expires_at = now() + timedelta(days=valid_days or OFFER_VALID_DAYS)
        if offer.applicant_id:
            from app.models.recruitment import Applicant, ApplicantStatus

            ap = await self.db.get(Applicant, offer.applicant_id)
            if ap is not None and ap.tenant_id == self.tenant_id and ap.status not in (ApplicantStatus.HIRED,):
                ap.status = ApplicantStatus.OFFER
        await self.db.flush()
        from app.workers.tasks import onboarding as tasks

        queue(tasks.send_offer_email, offer.candidate_email, offer.candidate_name, offer.job_title,
              await self._company_name(), offer_url(token), offer.expires_at.isoformat())
        out = serialize(offer)
        out["link"] = offer_url(token)  # shown once so HR can also copy it
        return out

    async def revoke(self, offer_id: uuid.UUID) -> dict:
        offer = await self._get(offer_id, lock=True)
        if offer.status in ("accepted", "declined", "expired", "revoked", "revised"):
            raise ConflictError(f"A {offer.status} offer cannot be revoked.")
        if offer.employee_id:
            raise ConflictError("This offer was already converted to an employee.")
        offer.status = "revoked"
        offer.token_hash = None
        await self.db.flush()
        return serialize(offer)

    async def revise(self, offer_id: uuid.UUID, actor_id: uuid.UUID, changes: dict) -> dict:
        """Negotiation: closes the current version and opens a new draft copy."""
        old = await self._get(offer_id, lock=True)
        if old.status in ("accepted", "revised") or old.employee_id:
            raise ConflictError("An accepted or superseded offer cannot be revised.")
        await self._check_refs(changes)
        changes = dict(changes)
        approvers = await self._check_approvers(changes.pop("approver_ids", old.approver_ids or []))
        fields = (
            "applicant_id", "candidate_name", "candidate_email", "candidate_phone", "job_title",
            "department_id", "designation_id", "branch_id", "manager_id", "template_id",
            "employment_type", "job_nature", "salary", "currency", "pay_items", "joining_date",
            "probation_months",
        )
        values = {f: getattr(old, f) for f in fields}
        values.update({k: v for k, v in changes.items() if k in fields})
        if values["joining_date"] < date.today():
            raise ValidationError("Joining date cannot be in the past.")
        old.status = "revised"
        old.token_hash = None
        new = Offer(tenant_id=self.tenant_id, created_by_id=actor_id, version=old.version + 1,
                    parent_offer_id=old.id, approver_ids=approvers, approvals=[], **values)
        new.body = changes.get("body") or await self._render(new)
        self.db.add(new)
        await self.db.flush()
        return serialize(new)

    # ── public (candidate) side ────────────────────────────────────────────
    async def _by_token(self, token: str) -> Offer:
        offer = (await self.db.execute(
            select(Offer).where(Offer.token_hash == hash_token(token), Offer.is_deleted == False)  # noqa: E712
            .with_for_update()
        )).scalar_one_or_none()
        if offer is None:
            raise NotFoundError("This offer link is not valid.")
        self.tenant_id = offer.tenant_id
        await self._expire_if_due(offer)
        return offer

    def _public(self, offer: Offer, company: str) -> dict:
        return {
            "company_name": company, "candidate_name": offer.candidate_name, "job_title": offer.job_title,
            "joining_date": offer.joining_date.isoformat(), "salary": float(offer.salary) if offer.salary is not None else None,
            "currency": offer.currency, "pay_items": offer.pay_items or [], "body": offer.body,
            "status": offer.status, "expires_at": offer.expires_at.isoformat() if offer.expires_at else None,
            "can_respond": offer.status in OPEN_FOR_RESPONSE,
        }

    async def public_view(self, token: str) -> dict:
        offer = await self._by_token(token)
        if offer.status == "sent":
            offer.status = "viewed"
            offer.viewed_at = now()
            await self.db.flush()
        return self._public(offer, await self._company_name())

    async def public_accept(self, token: str, *, full_name: str, ip: str, user_agent: str) -> dict:
        offer = await self._by_token(token)
        if offer.status not in OPEN_FOR_RESPONSE:
            raise ConflictError(f"This offer is {offer.status} and can no longer be accepted.")
        typed = " ".join((full_name or "").split())
        if len(typed) < 2:
            raise ValidationError("Type your full name to accept.")
        if typed.casefold() != " ".join(offer.candidate_name.split()).casefold():
            raise ValidationError("The name you typed must match the name on the offer.")
        offer.status = "accepted"
        offer.responded_at = now()
        offer.accepted_name = typed
        offer.accepted_ip = (ip or "")[:64]
        offer.accepted_user_agent = (user_agent or "")[:300]
        await self.db.flush()
        for uid in await recipient_ids(self.db, offer.tenant_id, "offers.manage"):
            notify(self.db, offer.tenant_id, uid, title="Offer accepted",
                   body=f"{offer.candidate_name} accepted the {offer.job_title} offer.",
                   type_="offer_accepted", action_url=f"/onboarding/offers/{offer.id}", icon="party-popper")
        await self.db.flush()
        return self._public(offer, await self._company_name())

    async def public_decline(self, token: str, *, reason: str | None) -> dict:
        offer = await self._by_token(token)
        if offer.status not in OPEN_FOR_RESPONSE:
            raise ConflictError(f"This offer is {offer.status} and can no longer be declined.")
        offer.status = "declined"
        offer.responded_at = now()
        offer.decline_reason = (reason or "").strip()[:1000] or None
        await self.db.flush()
        for uid in await recipient_ids(self.db, offer.tenant_id, "offers.manage"):
            notify(self.db, offer.tenant_id, uid, title="Offer declined",
                   body=f"{offer.candidate_name} declined the {offer.job_title} offer.",
                   type_="offer_declined", action_url=f"/onboarding/offers/{offer.id}", icon="user-x")
        await self.db.flush()
        return self._public(offer, await self._company_name())


async def expire_due_offers(db: AsyncSession, at: datetime | None = None) -> int:
    """Daily sweep: sent/viewed offers past their expiry become 'expired'."""
    at = at or now()
    rows = (await db.execute(
        select(Offer).where(Offer.status.in_(tuple(OPEN_FOR_RESPONSE)), Offer.expires_at.is_not(None),
                            Offer.expires_at <= at, Offer.is_deleted == False)  # noqa: E712
    )).scalars().all()
    for o in rows:
        o.status = "expired"
        if o.created_by_id:
            notify(db, o.tenant_id, o.created_by_id, title="Offer expired",
                   body=f"{o.candidate_name} did not respond to the {o.job_title} offer in time.",
                   type_="offer_expired", action_url=f"/onboarding/offers/{o.id}", icon="clock")
    await db.flush()
    return len(rows)
