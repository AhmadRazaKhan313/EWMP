"""
Aggregate counts for the Dashboard page's stat cards.

Before this existed, the Dashboard's six stat cards (Total Employees,
Present Today, On Leave, Open Tickets, Devices Online, Assets Assigned)
were a hardcoded `stats = {...}` object in the frontend with a comment
saying "In production, these come from TanStack Query hooks" — they never
did. This is the one query per number that comment was describing.

Kept as a single aggregate endpoint (one round trip) rather than having the
dashboard fire six separate list-endpoint requests just to read `.total`
off each — cheaper for both the client and the DB.
"""

from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance import AttendanceRecord, AttendanceStatus, LeaveRequest, LeaveRequestStatus
from app.models.devices import Asset, AssetStatus, Device, DeviceStatus
from app.models.employee import Employee
from app.models.helpdesk import SupportTicket, TicketStatus


async def get_dashboard_stats(db: AsyncSession, tenant_id: UUID) -> dict:
    today = date.today()

    total_employees = (
        await db.execute(
            select(func.count()).where(
                Employee.tenant_id == tenant_id, Employee.is_deleted == False  # noqa: E712
            )
        )
    ).scalar_one()

    present_today = (
        await db.execute(
            select(func.count()).where(
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.date == today,
                AttendanceRecord.status.in_([
                    AttendanceStatus.PRESENT,
                    AttendanceStatus.LATE,
                    AttendanceStatus.HALF_DAY,
                    AttendanceStatus.WORK_FROM_HOME,
                ]),
            )
        )
    ).scalar_one()

    on_leave_today = (
        await db.execute(
            select(func.count()).where(
                LeaveRequest.tenant_id == tenant_id,
                LeaveRequest.status == LeaveRequestStatus.APPROVED,
                LeaveRequest.start_date <= today,
                LeaveRequest.end_date >= today,
            )
        )
    ).scalar_one()

    open_tickets = (
        await db.execute(
            select(func.count()).where(
                SupportTicket.tenant_id == tenant_id,
                SupportTicket.status.in_([
                    TicketStatus.OPEN,
                    TicketStatus.IN_PROGRESS,
                    TicketStatus.PENDING,
                ]),
            )
        )
    ).scalar_one()

    devices_online = (
        await db.execute(
            select(func.count()).where(
                Device.tenant_id == tenant_id,
                Device.status == DeviceStatus.ONLINE,
            )
        )
    ).scalar_one()

    devices_total = (
        await db.execute(
            select(func.count()).where(
                Device.tenant_id == tenant_id,
                Device.status != DeviceStatus.DECOMMISSIONED,
            )
        )
    ).scalar_one()

    assets_assigned = (
        await db.execute(
            select(func.count()).where(
                Asset.tenant_id == tenant_id,
                Asset.status == AssetStatus.ASSIGNED,
            )
        )
    ).scalar_one()

    return {
        "total_employees": total_employees,
        "present_today": present_today,
        "on_leave_today": on_leave_today,
        "open_tickets": open_tickets,
        "devices_online": devices_online,
        "devices_total": devices_total,
        "assets_assigned": assets_assigned,
    }