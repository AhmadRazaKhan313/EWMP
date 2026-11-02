"""Onboarding & offboarding cases (N-01): templates, cases, tasks, pre-boarding,
documents, probation confirmation, dashboard and the daily reminder sweep."""
import uuid
from datetime import date, datetime, timedelta

from dateutil.relativedelta import relativedelta
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.models.employee import Employee, EmploymentStatus, Gender, JobNature
from app.models.onboarding import (
    OWNER_ROLES, TASK_KINDS, TASK_PHASES, TASK_STATUSES, Offer, OnboardingCase, OnboardingCaseDocument,
    OnboardingCaseTask, OnboardingTemplate, OnboardingTemplateTask,
)
from app.models.user import User
from app.services.onboarding_common import (
    PREBOARDING_GRACE_DAYS, hash_token, new_token, notify, now, preboarding_url, queue, recipient_ids,
)
from app.services.onboarding_defaults import DEFAULT_DOCUMENTS, OFFBOARDING_TASKS, ONBOARDING_TASKS

CLOSED_TASK = ("done", "skipped")
OPEN_CASE = ("pre_boarding", "active")
REMIND_EVERY_DAYS = 2
ESCALATE_AFTER_DAYS = 3

# Pre-boarding form: field -> max length (None = not a plain string).
PERSONAL_FIELDS = {
    "personal_phone": 30, "personal_email": 255, "marital_status": 30, "nationality": 60,
    "address": 500, "permanent_address": 500, "national_id": 40, "national_id_type": 30,
    "blood_group": 5,
}
BANK_FIELDS = {"bank_name": 100, "bank_account_title": 100, "bank_account_number": 40, "bank_iban": 34}
REQUIRED_TO_SUBMIT = ("personal_phone", "address", "national_id")


def _full_name(first: str | None, last: str | None) -> str:
    return " ".join(x for x in (first, last) if x)


class OnboardingService:
    def __init__(self, db: AsyncSession, tenant_id: uuid.UUID) -> None:
        self.db = db
        self.tenant_id = tenant_id

    # ── small lookups ──────────────────────────────────────────────────────
    async def _employee(self, employee_id: uuid.UUID) -> Employee:
        emp = (await self.db.execute(
            select(Employee).where(Employee.id == employee_id, Employee.tenant_id == self.tenant_id,
                                   Employee.is_deleted == False)  # noqa: E712
        )).scalar_one_or_none()
        if emp is None:
            raise NotFoundError("Employee not found")
        return emp

    async def _user_id_of(self, employee_id: uuid.UUID | None) -> uuid.UUID | None:
        if employee_id is None:
            return None
        return (await self.db.execute(
            select(Employee.user_id).where(Employee.id == employee_id, Employee.tenant_id == self.tenant_id)
        )).scalar_one_or_none()

    async def _case(self, case_id: uuid.UUID, *, lock: bool = False) -> OnboardingCase:
        q = select(OnboardingCase).where(
            OnboardingCase.id == case_id, OnboardingCase.tenant_id == self.tenant_id,
            OnboardingCase.is_deleted == False,  # noqa: E712
        )
        if lock:
            q = q.with_for_update()
        case = (await self.db.execute(q)).scalar_one_or_none()
        if case is None:
            raise NotFoundError("Onboarding case not found")
        return case

    async def _tasks(self, case_id: uuid.UUID) -> list[OnboardingCaseTask]:
        return list((await self.db.execute(
            select(OnboardingCaseTask).where(OnboardingCaseTask.case_id == case_id,
                                             OnboardingCaseTask.is_deleted == False)  # noqa: E712
            .order_by(OnboardingCaseTask.order)
        )).scalars().all())

    async def _docs(self, case_id: uuid.UUID) -> list[OnboardingCaseDocument]:
        return list((await self.db.execute(
            select(OnboardingCaseDocument).where(OnboardingCaseDocument.case_id == case_id,
                                                 OnboardingCaseDocument.is_deleted == False)  # noqa: E712
            .order_by(OnboardingCaseDocument.created_at)
        )).scalars().all())

    # ═══ templates ═════════════════════════════════════════════════════════
    @staticmethod
    def _t_out(t: OnboardingTemplate, tasks: list[OnboardingTemplateTask] | None = None) -> dict:
        out = {
            "id": str(t.id), "name": t.name, "description": t.description, "kind": t.kind,
            "department_id": str(t.department_id) if t.department_id else None,
            "designation_id": str(t.designation_id) if t.designation_id else None,
            "branch_id": str(t.branch_id) if t.branch_id else None,
            "is_active": t.is_active, "is_default": t.is_default,
        }
        if tasks is not None:
            out["tasks"] = [{
                "id": str(x.id), "order": x.order, "title": x.title, "description": x.description,
                "owner_role": x.owner_role, "phase": x.phase, "due_offset_days": x.due_offset_days,
                "depends_on_order": x.depends_on_order, "is_required": x.is_required, "kind": x.kind,
                "provision_key": x.provision_key, "link_url": x.link_url,
            } for x in tasks]
        return out

    async def _t_tasks(self, template_id: uuid.UUID) -> list[OnboardingTemplateTask]:
        return list((await self.db.execute(
            select(OnboardingTemplateTask).where(OnboardingTemplateTask.template_id == template_id,
                                                 OnboardingTemplateTask.is_deleted == False)  # noqa: E712
            .order_by(OnboardingTemplateTask.order)
        )).scalars().all())

    @staticmethod
    def _check_task_defs(tasks: list[dict]) -> list[dict]:
        if len(tasks) > 100:
            raise ValidationError("A template can have at most 100 tasks.")
        orders = [t["order"] for t in tasks]
        if len(set(orders)) != len(orders):
            raise ValidationError("Each task needs a unique order number.")
        for t in tasks:
            if t["owner_role"] not in OWNER_ROLES:
                raise ValidationError(f"owner_role must be one of {', '.join(OWNER_ROLES)}.")
            if t["phase"] not in TASK_PHASES:
                raise ValidationError(f"phase must be one of {', '.join(TASK_PHASES)}.")
            if t["kind"] not in TASK_KINDS:
                raise ValidationError(f"kind must be one of {', '.join(TASK_KINDS)}.")
            dep = t.get("depends_on_order")
            if dep is not None and dep not in orders:
                raise ValidationError(f"Task '{t['title']}' depends on a task that does not exist.")
            if dep is not None and dep == t["order"]:
                raise ValidationError(f"Task '{t['title']}' cannot depend on itself.")
        # No dependency cycles.
        dep_of = {t["order"]: t.get("depends_on_order") for t in tasks}
        for start in dep_of:
            seen, cur = set(), start
            while dep_of.get(cur) is not None:
                if cur in seen:
                    raise ValidationError("Task dependencies form a loop.")
                seen.add(cur)
                cur = dep_of[cur]
        return tasks

    async def list_templates(self, kind: str | None = None) -> dict:
        q = select(OnboardingTemplate).where(OnboardingTemplate.tenant_id == self.tenant_id,
                                             OnboardingTemplate.is_deleted == False)  # noqa: E712
        if kind:
            q = q.where(OnboardingTemplate.kind == kind)
        rows = (await self.db.execute(q.order_by(OnboardingTemplate.name))).scalars().all()
        counts = dict((await self.db.execute(
            select(OnboardingTemplateTask.template_id, func.count())
            .where(OnboardingTemplateTask.tenant_id == self.tenant_id, OnboardingTemplateTask.is_deleted == False)  # noqa: E712
            .group_by(OnboardingTemplateTask.template_id)
        )).all())
        items = []
        for t in rows:
            d = self._t_out(t)
            d["task_count"] = counts.get(t.id, 0)
            items.append(d)
        return {"items": items}

    async def get_template(self, template_id: uuid.UUID) -> dict:
        t = await self._template(template_id)
        return self._t_out(t, await self._t_tasks(t.id))

    async def _template(self, template_id: uuid.UUID) -> OnboardingTemplate:
        t = (await self.db.execute(
            select(OnboardingTemplate).where(OnboardingTemplate.id == template_id,
                                             OnboardingTemplate.tenant_id == self.tenant_id,
                                             OnboardingTemplate.is_deleted == False)  # noqa: E712
        )).scalar_one_or_none()
        if t is None:
            raise NotFoundError("Template not found")
        return t

    async def _check_scope(self, data: dict) -> None:
        from app.models.organization_structure import Branch, Department, Designation

        for key, model in (("department_id", Department), ("designation_id", Designation), ("branch_id", Branch)):
            if data.get(key) is None:
                continue
            ok = (await self.db.execute(
                select(model.id).where(model.id == data[key], model.tenant_id == self.tenant_id)
            )).scalar_one_or_none()
            if ok is None:
                raise ValidationError(f"Unknown {key.replace('_id', '')}.")

    async def _unset_other_defaults(self, kind: str, keep: uuid.UUID) -> None:
        for other in (await self.db.execute(
            select(OnboardingTemplate).where(OnboardingTemplate.tenant_id == self.tenant_id,
                                             OnboardingTemplate.kind == kind, OnboardingTemplate.is_default == True,  # noqa: E712
                                             OnboardingTemplate.id != keep, OnboardingTemplate.is_deleted == False)  # noqa: E712
        )).scalars().all():
            other.is_default = False

    async def _write_tasks(self, template_id: uuid.UUID, tasks: list[dict]) -> None:
        for t in await self._t_tasks(template_id):
            t.soft_delete()
        await self.db.flush()
        for t in tasks:
            self.db.add(OnboardingTemplateTask(tenant_id=self.tenant_id, template_id=template_id, **t))

    async def create_template(self, data: dict) -> dict:
        data = dict(data)
        tasks = self._check_task_defs(data.pop("tasks", []))
        await self._check_scope(data)
        if data.get("kind") not in ("onboarding", "offboarding"):
            raise ValidationError("kind must be 'onboarding' or 'offboarding'.")
        t = OnboardingTemplate(tenant_id=self.tenant_id, **data)
        self.db.add(t)
        await self.db.flush()
        if t.is_default:
            await self._unset_other_defaults(t.kind, t.id)
        await self._write_tasks(t.id, tasks)
        await self.db.flush()
        return await self.get_template(t.id)

    async def update_template(self, template_id: uuid.UUID, data: dict) -> dict:
        t = await self._template(template_id)
        data = dict(data)
        tasks = data.pop("tasks", None)
        await self._check_scope(data)
        data.pop("kind", None)  # a template never changes kind
        for k, v in data.items():
            setattr(t, k, v)
        if t.is_default:
            await self._unset_other_defaults(t.kind, t.id)
        if tasks is not None:
            await self._write_tasks(t.id, self._check_task_defs(tasks))
        await self.db.flush()
        return await self.get_template(t.id)

    async def delete_template(self, template_id: uuid.UUID) -> None:
        # Cases already created keep their own copy of the tasks, so this is safe.
        (await self._template(template_id)).soft_delete()
        await self.db.flush()

    async def seed_default_templates(self) -> dict:
        existing = {t.kind for t in (await self.db.execute(
            select(OnboardingTemplate).where(OnboardingTemplate.tenant_id == self.tenant_id,
                                             OnboardingTemplate.is_deleted == False)  # noqa: E712
        )).scalars().all() if t.is_default}
        created = []
        for kind, name, rows in (("onboarding", "Standard onboarding", ONBOARDING_TASKS),
                                 ("offboarding", "Standard offboarding", OFFBOARDING_TASKS)):
            if kind in existing:
                continue
            tasks = [{
                "order": o, "title": title, "description": desc, "owner_role": owner, "phase": phase,
                "due_offset_days": off, "depends_on_order": dep, "is_required": True, "kind": k,
                "provision_key": prov, "link_url": link,
            } for (o, title, owner, phase, off, dep, k, prov, link, desc) in rows]
            created.append(await self.create_template(
                {"name": name, "kind": kind, "is_default": True, "is_active": True,
                 "description": "Ready-made checklist. Edit freely.", "tasks": tasks}))
        return {"created": created}

    async def _pick_template(self, kind: str, employee: Employee, explicit: uuid.UUID | None) -> OnboardingTemplate:
        if explicit:
            t = await self._template(explicit)
            if t.kind != kind:
                raise ValidationError(f"That is an {t.kind} template, not {kind}.")
            return t
        rows = (await self.db.execute(
            select(OnboardingTemplate).where(OnboardingTemplate.tenant_id == self.tenant_id,
                                             OnboardingTemplate.kind == kind, OnboardingTemplate.is_active == True,  # noqa: E712
                                             OnboardingTemplate.is_deleted == False)  # noqa: E712
        )).scalars().all()

        def score(t: OnboardingTemplate) -> int | None:
            s = 0
            for mine, theirs, weight in ((employee.designation_id, t.designation_id, 4),
                                         (employee.department_id, t.department_id, 2),
                                         (employee.branch_id, t.branch_id, 1)):
                if theirs is None:
                    continue
                if theirs != mine:
                    return None  # scoped to something else
                s += weight
            return s

        scored = [(score(t), t) for t in rows]
        scored = [(s, t) for s, t in scored if s is not None]
        specific = [(s, t) for s, t in scored if s > 0]
        if specific:
            return max(specific, key=lambda x: x[0])[1]
        defaults = [t for _, t in scored if t.is_default] or [t for _, t in scored]
        if defaults:
            return defaults[0]
        raise ValidationError(
            f"No {kind} template exists yet. Open Templates and use 'Add default templates' first."
        )

    # ═══ cases ═════════════════════════════════════════════════════════════
    async def _progress(self, tasks: list[OnboardingCaseTask], today: date | None = None) -> dict:
        today = today or date.today()
        counted = [t for t in tasks if t.status != "skipped"]
        done = sum(1 for t in counted if t.status == "done")
        overdue = sum(1 for t in counted if t.status != "done" and t.due_date and t.due_date < today)
        total = len(counted)
        return {"done": done, "total": total, "percent": round(100 * done / total) if total else 0, "overdue": overdue}

    async def _case_out(self, case: OnboardingCase, *, detail: bool = False) -> dict:
        emp = (await self.db.execute(
            select(Employee, User.first_name, User.last_name, User.email)
            .join(User, User.id == Employee.user_id, isouter=True).where(Employee.id == case.employee_id)
        )).first()
        e, first, last, email = emp if emp else (None, None, None, None)
        tasks = await self._tasks(case.id)
        today = date.today()
        out = {
            "id": str(case.id), "kind": case.kind, "status": case.status,
            "employee": {"id": str(case.employee_id), "employee_code": e.employee_code if e else None,
                         "name": _full_name(first, last), "email": email,
                         "department_id": str(e.department_id) if e and e.department_id else None},
            "offer_id": str(case.offer_id) if case.offer_id else None,
            "template_id": str(case.template_id) if case.template_id else None,
            "anchor_date": case.anchor_date.isoformat(), "days_until": (case.anchor_date - today).days,
            "manager_id": str(case.manager_id) if case.manager_id else None,
            "buddy_id": str(case.buddy_id) if case.buddy_id else None,
            "progress": await self._progress(tasks, today),
            "preboarding_submitted_at": case.preboarding_submitted_at.isoformat() if case.preboarding_submitted_at else None,
            "policy_ack_at": case.policy_ack_at.isoformat() if case.policy_ack_at else None,
            "welcome_sent_at": case.welcome_sent_at.isoformat() if case.welcome_sent_at else None,
            "completed_at": case.completed_at.isoformat() if case.completed_at else None,
        }
        if detail:
            by_id = {t.id: t for t in tasks}
            names = {}
            ids = {t.assignee_user_id for t in tasks if t.assignee_user_id}
            if ids:
                for uid, f, l in (await self.db.execute(
                    select(User.id, User.first_name, User.last_name).where(User.id.in_(ids))
                )).all():
                    names[uid] = _full_name(f, l)
            out["tasks"] = [self._task_out(t, by_id, names, today) for t in tasks]
            out["documents"] = [self._doc_out(d) for d in await self._docs(case.id)]
            out["welcome_message"] = case.welcome_message
        return out

    @staticmethod
    def _task_out(t: OnboardingCaseTask, by_id: dict, names: dict, today: date) -> dict:
        dep = by_id.get(t.depends_on_id) if t.depends_on_id else None
        return {
            "id": str(t.id), "case_id": str(t.case_id), "order": t.order, "title": t.title,
            "description": t.description, "owner_role": t.owner_role, "phase": t.phase,
            "assignee_user_id": str(t.assignee_user_id) if t.assignee_user_id else None,
            "assignee_name": names.get(t.assignee_user_id), "due_date": t.due_date.isoformat() if t.due_date else None,
            "status": t.status, "is_required": t.is_required, "kind": t.kind, "provision_key": t.provision_key,
            "link_url": t.link_url, "notes": t.notes,
            "depends_on_id": str(t.depends_on_id) if t.depends_on_id else None,
            "blocked": bool(dep and dep.status not in CLOSED_TASK) and t.status not in CLOSED_TASK,
            "overdue": bool(t.due_date and t.due_date < today and t.status not in CLOSED_TASK),
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        }

    @staticmethod
    def _doc_out(d: OnboardingCaseDocument) -> dict:
        return {
            "id": str(d.id), "document_type": d.document_type, "title": d.title, "is_required": d.is_required,
            "status": d.status, "rejection_reason": d.rejection_reason,
            "employee_document_id": str(d.employee_document_id) if d.employee_document_id else None,
            "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
        }

    async def create_case(self, *, employee_id: uuid.UUID, kind: str = "onboarding",
                          template_id: uuid.UUID | None = None, anchor_date: date | None = None,
                          manager_id: uuid.UUID | None = None, buddy_id: uuid.UUID | None = None,
                          offer_id: uuid.UUID | None = None, actor_id: uuid.UUID | None = None,
                          welcome_message: str | None = None) -> dict:
        if kind not in ("onboarding", "offboarding"):
            raise ValidationError("kind must be 'onboarding' or 'offboarding'.")
        emp = await self._employee(employee_id)
        for label, ref in (("manager", manager_id), ("buddy", buddy_id)):
            if ref is not None:
                await self._employee(ref)
                if ref == employee_id:
                    raise ValidationError(f"The {label} cannot be the employee themself.")
        existing = (await self.db.execute(
            select(OnboardingCase.id).where(OnboardingCase.employee_id == employee_id, OnboardingCase.kind == kind,
                                            OnboardingCase.status.in_(OPEN_CASE), OnboardingCase.is_deleted == False)  # noqa: E712
        )).scalar_one_or_none()
        if existing:
            raise ConflictError(f"This employee already has an open {kind} case.")
        template = await self._pick_template(kind, emp, template_id)
        tdefs = await self._t_tasks(template.id)
        if not tdefs:
            raise ValidationError("That template has no tasks.")
        if anchor_date is None:
            anchor_date = emp.date_of_joining if kind == "onboarding" else (emp.date_of_leaving or date.today())
        manager_id = manager_id or emp.manager_id
        today = date.today()
        token = new_token() if kind == "onboarding" else None
        case = OnboardingCase(
            tenant_id=self.tenant_id, kind=kind, employee_id=employee_id, offer_id=offer_id, template_id=template.id,
            anchor_date=anchor_date, manager_id=manager_id, buddy_id=buddy_id, created_by_id=actor_id,
            status="pre_boarding" if (kind == "onboarding" and anchor_date > today) else "active",
            welcome_message=welcome_message,
            preboarding_token_hash=hash_token(token) if token else None,
            preboarding_expires_at=(datetime.combine(anchor_date, datetime.min.time(), tzinfo=now().tzinfo)
                                    + timedelta(days=PREBOARDING_GRACE_DAYS)) if token else None,
        )
        self.db.add(case)
        try:
            await self.db.flush()
        except IntegrityError:
            raise ConflictError(f"This employee already has an open {kind} case.")
        employee_user = emp.user_id
        manager_user = await self._user_id_of(manager_id)
        by_order: dict[int, OnboardingCaseTask] = {}
        for d in tdefs:
            link = (d.link_url or "").replace("{employee_id}", str(employee_id)) or None
            assignee = employee_user if d.owner_role == "employee" else manager_user if d.owner_role == "manager" else None
            t = OnboardingCaseTask(
                tenant_id=self.tenant_id, case_id=case.id, template_task_id=d.id, order=d.order, title=d.title,
                description=d.description, owner_role=d.owner_role, assignee_user_id=assignee, phase=d.phase,
                due_offset_days=d.due_offset_days, due_date=anchor_date + timedelta(days=d.due_offset_days),
                is_required=d.is_required, kind=d.kind, provision_key=d.provision_key, link_url=link,
            )
            self.db.add(t)
            by_order[d.order] = t
        await self.db.flush()
        for d in tdefs:
            if d.depends_on_order is not None:
                by_order[d.order].depends_on_id = by_order[d.depends_on_order].id
        if kind == "onboarding":
            for dtype, title, required in DEFAULT_DOCUMENTS:
                self.db.add(OnboardingCaseDocument(tenant_id=self.tenant_id, case_id=case.id, document_type=dtype,
                                                   title=title, is_required=required))
            await self.db.flush()
        # The employee already has a login by the time a case exists.
        if employee_user:
            for t in by_order.values():
                if t.provision_key == "account":
                    self._finish(t, None, "Login account was created with the employee record.")
        await self.db.flush()
        await self._after_change(case)
        name = (await self._case_out(case))["employee"]["name"] or "the new hire"
        for uid, role in ((manager_user, "manager"), (await self._user_id_of(buddy_id), "buddy")):
            if uid:
                notify(self.db, self.tenant_id, uid,
                       title=f"You are the {role} for {name}",
                       body=f"{'Joining' if kind == 'onboarding' else 'Last working day'}: {anchor_date.isoformat()}",
                       type_="onboarding_assigned", action_url=f"/onboarding/{case.id}")
        out = await self._case_out(case, detail=True)
        if token:
            out["preboarding_link"] = preboarding_url(token)
            from app.workers.tasks import onboarding as tasks_mod

            user = await self.db.get(User, employee_user) if employee_user else None
            if user is not None:
                queue(tasks_mod.send_preboarding_email, user.email, name, preboarding_url(token),
                      anchor_date.isoformat())
        return out

    @staticmethod
    def _finish(t: OnboardingCaseTask, by: uuid.UUID | None, note: str | None = None) -> None:
        t.status = "done"
        t.completed_at = now()
        t.completed_by_id = by
        if note and not t.notes:
            t.notes = note

    async def list_cases(self, *, kind: str | None = None, status: str | None = None, search: str | None = None,
                         employee_id: uuid.UUID | None = None, overdue: bool = False,
                         page: int = 1, page_size: int = 25) -> dict:
        q = (select(OnboardingCase).join(Employee, Employee.id == OnboardingCase.employee_id)
             .join(User, User.id == Employee.user_id, isouter=True)
             .where(OnboardingCase.tenant_id == self.tenant_id, OnboardingCase.is_deleted == False))  # noqa: E712
        if kind:
            q = q.where(OnboardingCase.kind == kind)
        if status:
            q = q.where(OnboardingCase.status == status)
        if employee_id:
            q = q.where(OnboardingCase.employee_id == employee_id)
        if search:
            like = f"%{search.strip()}%"
            q = q.where(or_(User.first_name.ilike(like), User.last_name.ilike(like), User.email.ilike(like),
                            Employee.employee_code.ilike(like)))
        if overdue:
            q = q.where(OnboardingCase.id.in_(
                select(OnboardingCaseTask.case_id).where(
                    OnboardingCaseTask.tenant_id == self.tenant_id, OnboardingCaseTask.status.notin_(CLOSED_TASK),
                    OnboardingCaseTask.due_date < date.today(), OnboardingCaseTask.is_deleted == False)))  # noqa: E712
        total = (await self.db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
        rows = (await self.db.execute(q.order_by(OnboardingCase.anchor_date.desc())
                                      .offset((page - 1) * page_size).limit(page_size))).scalars().all()
        return {"items": [await self._case_out(c) for c in rows], "total": total, "page": page, "page_size": page_size}

    async def get_case(self, case_id: uuid.UUID) -> dict:
        return await self._case_out(await self._case(case_id), detail=True)

    async def update_case(self, case_id: uuid.UUID, data: dict) -> dict:
        case = await self._case(case_id, lock=True)
        if case.status in ("completed", "cancelled"):
            raise ConflictError(f"A {case.status} case cannot be changed.")
        for label, key in (("manager", "manager_id"), ("buddy", "buddy_id")):
            if key in data and data[key] is not None:
                if data[key] == case.employee_id:
                    raise ValidationError(f"The {label} cannot be the employee themself.")
                await self._employee(data[key])
        if "manager_id" in data:
            case.manager_id = data["manager_id"]
            new_user = await self._user_id_of(case.manager_id)
            for t in await self._tasks(case.id):
                if t.owner_role == "manager" and t.status not in CLOSED_TASK:
                    t.assignee_user_id = new_user
        if "buddy_id" in data:
            case.buddy_id = data["buddy_id"]
        if "welcome_message" in data:
            case.welcome_message = data["welcome_message"]
        if data.get("anchor_date") and data["anchor_date"] != case.anchor_date:
            case.anchor_date = data["anchor_date"]
            for t in await self._tasks(case.id):
                if t.status not in CLOSED_TASK:
                    t.due_date = case.anchor_date + timedelta(days=t.due_offset_days)
            if case.kind == "onboarding":
                emp = await self._employee(case.employee_id)
                if emp.date_of_joining and emp.date_of_joining > date.today():
                    emp.date_of_joining = case.anchor_date
                case.preboarding_expires_at = (
                    datetime.combine(case.anchor_date, datetime.min.time(), tzinfo=now().tzinfo)
                    + timedelta(days=PREBOARDING_GRACE_DAYS))
        await self.db.flush()
        return await self._case_out(case, detail=True)

    async def cancel_case(self, case_id: uuid.UUID) -> dict:
        case = await self._case(case_id, lock=True)
        if case.status == "completed":
            raise ConflictError("A completed case cannot be cancelled.")
        case.status = "cancelled"
        case.preboarding_token_hash = None
        await self.db.flush()
        return await self._case_out(case)

    async def _after_change(self, case: OnboardingCase) -> None:
        """Auto-complete form/document/acknowledge tasks and close the case when done."""
        tasks = await self._tasks(case.id)
        docs = await self._docs(case.id)
        required_docs = [d for d in docs if d.is_required]
        rules = {
            "form": case.preboarding_submitted_at is not None,
            "acknowledge": case.policy_ack_at is not None,
            "document": bool(required_docs) and all(d.status in ("uploaded", "verified") for d in required_docs),
        }
        for t in tasks:
            if t.status not in CLOSED_TASK and rules.get(t.kind):
                self._finish(t, None, "Completed automatically.")
        required = [t for t in tasks if t.is_required and t.status != "skipped"]
        if (case.status in OPEN_CASE and required and all(t.status == "done" for t in required)
                and not (case.kind == "onboarding" and case.status == "pre_boarding")):
            case.status = "completed"
            case.completed_at = now()
        await self.db.flush()

    # ═══ tasks ═════════════════════════════════════════════════════════════
    async def _task(self, task_id: uuid.UUID) -> OnboardingCaseTask:
        t = (await self.db.execute(
            select(OnboardingCaseTask).where(OnboardingCaseTask.id == task_id,
                                             OnboardingCaseTask.tenant_id == self.tenant_id,
                                             OnboardingCaseTask.is_deleted == False)  # noqa: E712
            .with_for_update()
        )).scalar_one_or_none()
        if t is None:
            raise NotFoundError("Task not found")
        return t

    async def update_task(self, task_id: uuid.UUID, actor: User, data: dict) -> dict:
        t = await self._task(task_id)
        can_manage = actor.has_permission("onboarding.manage")
        if not can_manage and t.assignee_user_id != actor.id:
            raise PermissionDeniedError("This task is not assigned to you.")
        case = await self._case(t.case_id, lock=True)
        if case.status in ("completed", "cancelled"):
            raise ConflictError(f"This case is {case.status}.")
        manage_only = ("assignee_user_id", "due_date")
        if any(k in data for k in manage_only) and not can_manage:
            raise PermissionDeniedError("Only HR can reassign or reschedule tasks.")
        if "assignee_user_id" in data:
            uid = data["assignee_user_id"]
            if uid is not None:
                ok = (await self.db.execute(select(User.id).where(User.id == uid, User.organization_id == self.tenant_id,
                                                                    User.is_deleted == False))).scalar_one_or_none()  # noqa: E712
                if ok is None:
                    raise ValidationError("That user is not in this organization.")
            t.assignee_user_id = uid
            if uid and uid != actor.id:
                notify(self.db, self.tenant_id, uid, title="Onboarding task assigned to you", body=t.title,
                       type_="onboarding_task", action_url=f"/onboarding/{case.id}")
        if "due_date" in data:
            t.due_date = data["due_date"]
        if "notes" in data:
            t.notes = (data["notes"] or "")[:2000] or None
        if "status" in data and data["status"] != t.status:
            new = data["status"]
            if new not in TASK_STATUSES:
                raise ValidationError(f"status must be one of {', '.join(TASK_STATUSES)}.")
            if new in ("skipped", "pending") and not can_manage:
                raise PermissionDeniedError("Only HR can skip or reopen a task.")
            if new in ("done", "in_progress") and t.depends_on_id:
                dep = await self.db.get(OnboardingCaseTask, t.depends_on_id)
                if dep is not None and dep.status not in CLOSED_TASK:
                    raise ConflictError(f"Finish '{dep.title}' first.")
            if new == "done":
                self._finish(t, actor.id)
            else:
                t.status = new
                t.completed_at = None
                t.completed_by_id = None
        await self.db.flush()
        await self._after_change(case)
        by_id = {x.id: x for x in await self._tasks(case.id)}
        return self._task_out(t, by_id, {}, date.today())

    async def my_tasks(self, actor: User, *, include_done: bool = False) -> dict:
        q = (select(OnboardingCaseTask, OnboardingCase)
             .join(OnboardingCase, OnboardingCase.id == OnboardingCaseTask.case_id)
             .where(OnboardingCaseTask.tenant_id == self.tenant_id, OnboardingCaseTask.assignee_user_id == actor.id,
                    OnboardingCaseTask.is_deleted == False, OnboardingCase.status.in_(OPEN_CASE)))  # noqa: E712
        if not include_done:
            q = q.where(OnboardingCaseTask.status.notin_(CLOSED_TASK))
        rows = (await self.db.execute(q.order_by(OnboardingCaseTask.due_date))).all()
        today = date.today()
        out = []
        for t, c in rows:
            row = self._task_out(t, {}, {}, today)
            row["case"] = {"id": str(c.id), "kind": c.kind, "anchor_date": c.anchor_date.isoformat(),
                           "employee_id": str(c.employee_id)}
            out.append(row)
        return {"items": out}

    # ═══ welcome / buddy / confirmation ════════════════════════════════════
    async def send_welcome(self, case_id: uuid.UUID, message: str | None, actor_id: uuid.UUID) -> dict:
        case = await self._case(case_id, lock=True)
        if case.kind != "onboarding" or case.status in ("completed", "cancelled"):
            raise ConflictError("A welcome message can only be sent on an open onboarding case.")
        if message is not None:
            case.welcome_message = message.strip()[:2000] or None
        emp = await self._employee(case.employee_id)
        user = await self.db.get(User, emp.user_id) if emp.user_id else None
        body = case.welcome_message or f"Welcome aboard! We are happy you are joining us on {case.anchor_date:%d %B %Y}."
        if user is not None:
            notify(self.db, self.tenant_id, user.id, title="Welcome!", body=body, type_="onboarding_welcome",
                   action_url="/dashboard", icon="party-popper")
            from app.workers.tasks import onboarding as tasks_mod

            queue(tasks_mod.send_welcome_email, user.email, user.first_name or "", body)
        case.welcome_sent_at = now()
        for t in await self._tasks(case.id):
            if t.provision_key == "welcome" and t.status not in CLOSED_TASK:
                self._finish(t, actor_id, "Welcome message sent.")
        await self.db.flush()
        await self._after_change(case)
        return await self._case_out(case, detail=True)

    async def confirm(self, case_id: uuid.UUID, actor_id: uuid.UUID, confirmed_on: date | None,
                      note: str | None) -> dict:
        """Probation confirmation: the employee becomes permanent and active."""
        from app.services.employee_history import record_status_change

        case = await self._case(case_id, lock=True)
        if case.kind != "onboarding":
            raise ConflictError("Only an onboarding case can confirm an employee.")
        emp = await self._employee(case.employee_id)
        if emp.date_of_confirmation is not None or emp.job_nature == JobNature.PERMANENT:
            raise ConflictError("This employee is already confirmed.")
        if emp.employment_status in (EmploymentStatus.TERMINATED, EmploymentStatus.RESIGNED):
            raise ConflictError("A former employee cannot be confirmed.")
        on = confirmed_on or date.today()
        if on < emp.date_of_joining:
            raise ValidationError("The confirmation date cannot be before the joining date.")
        before = emp.employment_status
        emp.job_nature = JobNature.PERMANENT
        emp.employment_status = EmploymentStatus.ACTIVE
        emp.date_of_confirmation = on
        await record_status_change(self.db, self.tenant_id, emp.id, from_status=before,
                                   to_status=EmploymentStatus.ACTIVE, changed_by_id=actor_id,
                                   reason=(note or "Probation confirmed")[:500], effective_date=on, source="confirmed")
        for t in await self._tasks(case.id):
            if t.phase == "probation" and "confirmation" in t.title.lower() and t.status not in CLOSED_TASK:
                self._finish(t, actor_id, note)
        await self.db.flush()
        await self._after_change(case)
        return await self._case_out(case, detail=True)

    # ═══ pre-boarding (HR side) ════════════════════════════════════════════
    async def issue_preboarding_link(self, case_id: uuid.UUID) -> dict:
        case = await self._case(case_id, lock=True)
        if case.kind != "onboarding" or case.status not in OPEN_CASE:
            raise ConflictError("A pre-boarding link needs an open onboarding case.")
        token = new_token()
        case.preboarding_token_hash = hash_token(token)
        case.preboarding_expires_at = (datetime.combine(case.anchor_date, datetime.min.time(), tzinfo=now().tzinfo)
                                       + timedelta(days=PREBOARDING_GRACE_DAYS))
        await self.db.flush()
        emp = await self._employee(case.employee_id)
        user = await self.db.get(User, emp.user_id) if emp.user_id else None
        if user is not None:
            from app.workers.tasks import onboarding as tasks_mod

            queue(tasks_mod.send_preboarding_email, user.email, user.first_name or "", preboarding_url(token),
                  case.anchor_date.isoformat())
        return {"link": preboarding_url(token)}

    async def add_document_request(self, case_id: uuid.UUID, document_type: str, title: str, required: bool) -> dict:
        from app.models.documents import DocumentType

        case = await self._case(case_id)
        if case.status in ("completed", "cancelled"):
            raise ConflictError(f"This case is {case.status}.")
        try:
            DocumentType(document_type)
        except ValueError:
            raise ValidationError("Unknown document type.")
        d = OnboardingCaseDocument(tenant_id=self.tenant_id, case_id=case.id, document_type=document_type,
                                   title=title.strip()[:200], is_required=required)
        self.db.add(d)
        await self.db.flush()
        return self._doc_out(d)

    async def review_document(self, doc_id: uuid.UUID, actor_id: uuid.UUID, approve: bool, reason: str | None) -> dict:
        d = (await self.db.execute(
            select(OnboardingCaseDocument).where(OnboardingCaseDocument.id == doc_id,
                                                 OnboardingCaseDocument.tenant_id == self.tenant_id,
                                                 OnboardingCaseDocument.is_deleted == False)  # noqa: E712
            .with_for_update()
        )).scalar_one_or_none()
        if d is None:
            raise NotFoundError("Document request not found")
        if d.status not in ("uploaded", "verified", "rejected"):
            raise ConflictError("Nothing has been uploaded for this document yet.")
        if not approve and not (reason or "").strip():
            raise ValidationError("Say why the document is rejected so the new hire can fix it.")
        d.status = "verified" if approve else "rejected"
        d.rejection_reason = None if approve else reason.strip()[:300]
        d.verified_by_id = actor_id
        d.verified_at = now()
        await self.db.flush()
        case = await self._case(d.case_id)
        await self._after_change(case)
        return self._doc_out(d)

    # ═══ pre-boarding (candidate side, by secure link) ═════════════════════
    async def _by_preboarding_token(self, token: str) -> OnboardingCase:
        case = (await self.db.execute(
            select(OnboardingCase).where(OnboardingCase.preboarding_token_hash == hash_token(token),
                                         OnboardingCase.is_deleted == False)  # noqa: E712
            .with_for_update()
        )).scalar_one_or_none()
        if case is None or case.status not in OPEN_CASE or case.kind != "onboarding":
            raise NotFoundError("This pre-boarding link is not valid.")
        if case.preboarding_expires_at and case.preboarding_expires_at < now():
            raise NotFoundError("This pre-boarding link has expired. Ask HR for a new one.")
        self.tenant_id = case.tenant_id
        return case

    async def preboarding_view(self, token: str) -> dict:
        from app.models.organization import Organization

        case = await self._by_preboarding_token(token)
        emp = await self._employee(case.employee_id)
        user = await self.db.get(User, emp.user_id) if emp.user_id else None
        org = await self.db.get(Organization, case.tenant_id)
        data = dict(case.preboarding_data or {})
        # Show only what the hire typed in; never echo stored identifiers beyond that.
        return {
            "company_name": org.name if org else "", "first_name": user.first_name if user else "",
            "joining_date": case.anchor_date.isoformat(), "submitted": case.preboarding_submitted_at is not None,
            "policy_acknowledged": case.policy_ack_at is not None,
            "form": data, "documents": [self._doc_out(d) for d in await self._docs(case.id)],
            "required_fields": list(REQUIRED_TO_SUBMIT),
        }

    @staticmethod
    def _clean_form(raw: dict) -> dict:
        out: dict = {}
        for key, limit in {**PERSONAL_FIELDS, **BANK_FIELDS}.items():
            if key in raw and raw[key] is not None:
                val = str(raw[key]).strip()
                if len(val) > limit:
                    raise ValidationError(f"{key.replace('_', ' ')} is too long (max {limit}).")
                out[key] = val
        if raw.get("date_of_birth"):
            try:
                dob = date.fromisoformat(str(raw["date_of_birth"]))
            except ValueError:
                raise ValidationError("Date of birth must be a valid date.")
            if dob >= date.today() - timedelta(days=16 * 365):
                raise ValidationError("Date of birth looks wrong.")
            out["date_of_birth"] = dob.isoformat()
        if raw.get("gender"):
            try:
                out["gender"] = Gender(str(raw["gender"])).value
            except ValueError:
                raise ValidationError("Unknown gender value.")
        if "emergency_contacts" in raw and raw["emergency_contacts"] is not None:
            people = raw["emergency_contacts"]
            if not isinstance(people, list) or len(people) > 5:
                raise ValidationError("Give up to 5 emergency contacts.")
            clean = []
            for p in people:
                name, phone = str(p.get("name", "")).strip(), str(p.get("phone", "")).strip()
                if not name or not phone:
                    raise ValidationError("Each emergency contact needs a name and a phone number.")
                clean.append({"name": name[:100], "phone": phone[:30],
                              "relationship": str(p.get("relationship", "")).strip()[:50]})
            out["emergency_contacts"] = clean
        return out

    async def preboarding_save(self, token: str, form: dict, *, submit: bool, acknowledge_policy: bool) -> dict:
        case = await self._by_preboarding_token(token)
        if case.preboarding_submitted_at is not None:
            raise ConflictError("You have already submitted this form. Contact HR to change it.")
        merged = {**(case.preboarding_data or {}), **self._clean_form(form or {})}
        case.preboarding_data = merged
        if acknowledge_policy and case.policy_ack_at is None:
            case.policy_ack_at = now()
        if submit:
            missing = [f for f in REQUIRED_TO_SUBMIT if not merged.get(f)]
            if not merged.get("emergency_contacts"):
                missing.append("emergency_contacts")
            if case.policy_ack_at is None:
                missing.append("policy_acknowledgement")
            if missing:
                raise ValidationError("Please complete: " + ", ".join(m.replace("_", " ") for m in missing) + ".")
            await self._apply_to_employee(case, merged)
            case.preboarding_submitted_at = now()
            for uid in await recipient_ids(self.db, case.tenant_id, "onboarding.manage"):
                notify(self.db, case.tenant_id, uid, title="Pre-boarding form submitted",
                       body="A new hire completed their details.", type_="onboarding_form",
                       action_url=f"/onboarding/{case.id}")
        await self.db.flush()
        await self._after_change(case)
        return await self.preboarding_view(token)

    async def _apply_to_employee(self, case: OnboardingCase, data: dict) -> None:
        emp = await self._employee(case.employee_id)
        for key in (*PERSONAL_FIELDS, *BANK_FIELDS):
            if data.get(key):
                setattr(emp, key, data[key])
        if data.get("date_of_birth"):
            emp.date_of_birth = date.fromisoformat(data["date_of_birth"])
        if data.get("gender"):
            emp.gender = Gender(data["gender"])
        if data.get("emergency_contacts"):
            emp.emergency_contacts = data["emergency_contacts"]
            emp.emergency_contact = data["emergency_contacts"][0]

    async def preboarding_upload(self, token: str, doc_id: uuid.UUID, *, file_name: str, content: bytes) -> dict:
        from app.models.documents import DocumentType
        from app.services.documents import EmployeeDocumentService

        case = await self._by_preboarding_token(token)
        d = (await self.db.execute(
            select(OnboardingCaseDocument).where(OnboardingCaseDocument.id == doc_id,
                                                 OnboardingCaseDocument.case_id == case.id,
                                                 OnboardingCaseDocument.is_deleted == False)  # noqa: E712
            .with_for_update()
        )).scalar_one_or_none()
        if d is None:
            raise NotFoundError("Document request not found")
        if d.status == "verified":
            raise ConflictError("This document was already verified.")
        emp = await self._employee(case.employee_id)
        if emp.user_id is None:
            raise ConflictError("This employee has no login account yet.")
        doc = await EmployeeDocumentService(self.db, self.tenant_id).upload_document(
            employee_id=emp.id, document_type=DocumentType(d.document_type), title=d.title, file_name=file_name[:200],
            mime_type="", content=content, expiry_date=None, notes="Uploaded during pre-boarding",
            uploaded_by_id=emp.user_id,
        )
        d.employee_document_id = doc.id
        d.status = "uploaded"
        d.rejection_reason = None
        d.uploaded_at = now()
        await self.db.flush()
        await self._after_change(case)
        return self._doc_out(d)

    # ═══ offer -> employee ═════════════════════════════════════════════════
    async def convert_offer(self, offer_id: uuid.UUID, actor: User, *, role_id: uuid.UUID,
                            first_name: str | None = None, last_name: str | None = None,
                            template_id: uuid.UUID | None = None, manager_id: uuid.UUID | None = None,
                            buddy_id: uuid.UUID | None = None) -> dict:
        from app.schemas.employee import EmployeeCreateSchema
        from app.services.employee import EmployeeService

        offer = (await self.db.execute(
            select(Offer).where(Offer.id == offer_id, Offer.tenant_id == self.tenant_id, Offer.is_deleted == False)  # noqa: E712
            .with_for_update()
        )).scalar_one_or_none()
        if offer is None:
            raise NotFoundError("Offer not found")
        if offer.employee_id is not None:
            raise ConflictError("This offer was already converted to an employee.")
        if offer.status != "accepted":
            raise ConflictError("Only an accepted offer can be converted to an employee.")
        parts = offer.candidate_name.split()
        first = (first_name or (parts[0] if parts else "")).strip()
        last = (last_name or " ".join(parts[1:])).strip()
        if not first or not last:
            raise ValidationError("Enter the employee's first and last name to convert this offer.")
        payload = {
            "first_name": first, "last_name": last, "email": offer.candidate_email, "role_id": role_id,
            "date_of_joining": offer.joining_date, "job_nature": offer.job_nature,
            "employment_type": offer.employment_type, "phone": offer.candidate_phone,
            "department_id": offer.department_id, "designation_id": offer.designation_id,
            "branch_id": offer.branch_id, "manager_id": manager_id or offer.manager_id,
            "current_salary": offer.salary, "currency": offer.currency,
        }
        if offer.pay_items:
            payload["compensation_items"] = offer.pay_items
        try:
            data = EmployeeCreateSchema(**payload)
        except Exception as exc:  # pydantic ValidationError
            errs = getattr(exc, "errors", lambda: [])()
            first_err = errs[0] if errs else {"loc": ("offer",), "msg": str(exc)}
            raise ValidationError(f"{'.'.join(str(x) for x in first_err['loc'])}: {first_err['msg']}")
        emp, temp_password = await EmployeeService(self.db, self.tenant_id).create_employee(
            data, actor.id, actor=actor)
        if offer.probation_months and offer.job_nature == "probationary":
            emp.probation_end_date = offer.joining_date + relativedelta(months=offer.probation_months)
        offer.employee_id = emp.id
        if offer.applicant_id:
            from app.models.recruitment import Applicant, ApplicantStatus

            ap = await self.db.get(Applicant, offer.applicant_id)
            if ap is not None and ap.tenant_id == self.tenant_id:
                ap.status = ApplicantStatus.HIRED
        await self.db.flush()
        case = await self.create_case(
            employee_id=emp.id, kind="onboarding", template_id=template_id or offer.template_id,
            anchor_date=offer.joining_date, manager_id=manager_id or offer.manager_id, buddy_id=buddy_id,
            offer_id=offer.id, actor_id=actor.id)
        return {"employee_id": str(emp.id), "employee_code": emp.employee_code,
                "temporary_password": temp_password, "case": case}

    # ═══ dashboard ═════════════════════════════════════════════════════════
    async def dashboard(self) -> dict:
        today = date.today()
        T, C = OnboardingCaseTask, OnboardingCase
        base_open = [T.tenant_id == self.tenant_id, T.is_deleted == False, T.status.notin_(CLOSED_TASK),  # noqa: E712
                     C.status.in_(OPEN_CASE)]
        open_cases = (await self.db.execute(
            select(C).where(C.tenant_id == self.tenant_id, C.is_deleted == False, C.status.in_(OPEN_CASE))  # noqa: E712
            .order_by(C.anchor_date))).scalars().all()
        overdue_rows = (await self.db.execute(
            select(T.owner_role, T.title, Employee.department_id)
            .join(C, C.id == T.case_id).join(Employee, Employee.id == C.employee_id)
            .where(*base_open, T.due_date < today))).all()
        by_role: dict[str, int] = {}
        by_title: dict[str, int] = {}
        by_dept: dict[uuid.UUID | None, int] = {}
        for role, title, dept in overdue_rows:
            by_role[role] = by_role.get(role, 0) + 1
            by_title[title] = by_title.get(title, 0) + 1
            by_dept[dept] = by_dept.get(dept, 0) + 1
        dept_names: dict = {}
        real = [d for d in by_dept if d]
        if real:
            from app.models.organization_structure import Department

            dept_names = dict((await self.db.execute(
                select(Department.id, Department.name).where(Department.id.in_(real)))).all())
        due_week = (await self.db.execute(
            select(func.count()).select_from(T).join(C, C.id == T.case_id)
            .where(*base_open, T.due_date >= today, T.due_date <= today + timedelta(days=7)))).scalar_one()
        month_start = today.replace(day=1)
        completed_month = (await self.db.execute(
            select(func.count()).select_from(C).where(
                C.tenant_id == self.tenant_id, C.status == "completed", C.completed_at >= datetime.combine(
                    month_start, datetime.min.time(), tzinfo=now().tzinfo)))).scalar_one()
        joiners = []
        for c in open_cases:
            if c.kind != "onboarding" or c.anchor_date < today - timedelta(days=14):
                continue
            joiners.append(await self._case_out(c))
        joiners = joiners[:20]
        return {
            "totals": {
                "open_onboarding": sum(1 for c in open_cases if c.kind == "onboarding"),
                "open_offboarding": sum(1 for c in open_cases if c.kind == "offboarding"),
                "overdue_tasks": len(overdue_rows), "due_this_week": due_week,
                "completed_this_month": completed_month,
            },
            "upcoming_joiners": joiners,
            "bottlenecks": {
                "by_owner_role": [{"owner_role": k, "overdue": v} for k, v in sorted(by_role.items(), key=lambda x: -x[1])],
                "by_task": [{"title": k, "overdue": v} for k, v in sorted(by_title.items(), key=lambda x: -x[1])[:8]],
                "by_department": [{"department_id": str(k) if k else None, "department": dept_names.get(k, "No department"),
                                   "overdue": v} for k, v in sorted(by_dept.items(), key=lambda x: -x[1])],
            },
        }


# ═══ daily sweep (Celery) ══════════════════════════════════════════════════
async def run_daily_sweep(db: AsyncSession, today: date | None = None) -> dict:
    """Activate cases whose first day has come, remind assignees about overdue
    tasks (at most every REMIND_EVERY_DAYS), escalate to the manager + HR once a
    task is ESCALATE_AFTER_DAYS late, and expire unanswered offers."""
    from app.services.onboarding_offers import expire_due_offers

    today = today or date.today()
    activated = reminded = escalated = 0
    for c in (await db.execute(
        select(OnboardingCase).where(OnboardingCase.status == "pre_boarding", OnboardingCase.anchor_date <= today,
                                     OnboardingCase.is_deleted == False)  # noqa: E712
    )).scalars().all():
        c.status = "active"
        activated += 1
    await db.flush()

    rows = (await db.execute(
        select(OnboardingCaseTask, OnboardingCase)
        .join(OnboardingCase, OnboardingCase.id == OnboardingCaseTask.case_id)
        .where(OnboardingCaseTask.status.notin_(CLOSED_TASK), OnboardingCaseTask.due_date < today,
               OnboardingCaseTask.is_deleted == False, OnboardingCase.status.in_(OPEN_CASE),  # noqa: E712
               OnboardingCase.is_deleted == False)  # noqa: E712
    )).all()
    hr_cache: dict[uuid.UUID, list[uuid.UUID]] = {}
    for t, c in rows:
        # A task still waiting on an unfinished dependency is not the owner's fault yet.
        if t.depends_on_id:
            dep = await db.get(OnboardingCaseTask, t.depends_on_id)
            if dep is not None and dep.status not in CLOSED_TASK:
                continue
        if c.tenant_id not in hr_cache:
            hr_cache[c.tenant_id] = await recipient_ids(db, c.tenant_id, "onboarding.manage")
        late = (today - t.due_date).days
        url = f"/onboarding/{c.id}"
        if t.last_reminded_at is None or (today - t.last_reminded_at).days >= REMIND_EVERY_DAYS:
            for uid in ([t.assignee_user_id] if t.assignee_user_id else hr_cache[c.tenant_id]):
                notify(db, c.tenant_id, uid, title="Onboarding task overdue", body=f"{t.title} ({late} day(s) late)",
                       type_="onboarding_overdue", action_url=url, icon="alarm-clock")
            t.last_reminded_at = today
            reminded += 1
        if late >= ESCALATE_AFTER_DAYS and t.escalated_at is None:
            targets = set(hr_cache[c.tenant_id])
            if c.manager_id:
                mu = (await db.execute(select(Employee.user_id).where(Employee.id == c.manager_id))).scalar_one_or_none()
                if mu:
                    targets.add(mu)
            for uid in targets:
                notify(db, c.tenant_id, uid, title="Onboarding task escalated",
                       body=f"{t.title} is {late} days late.", type_="onboarding_escalation",
                       action_url=url, icon="siren")
            t.escalated_at = today
            escalated += 1
    expired = await expire_due_offers(db)
    await db.flush()
    return {"activated": activated, "reminded": reminded, "escalated": escalated, "offers_expired": expired}
