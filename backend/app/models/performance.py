"""Performance Management models."""
import uuid, enum
from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, JSON, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import TenantModel

class GoalStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    AT_RISK = "at_risk"

class ReviewStatus(str, enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    COMPLETED = "completed"

class Goal(TenantModel):
    __tablename__ = "goals"
    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[GoalStatus] = mapped_column(SAEnum(GoalStatus, name="goal_status_enum"), default=GoalStatus.NOT_STARTED, index=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    completed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    key_results: Mapped[list] = mapped_column(JSON, default=list)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

class PerformanceReview(TenantModel):
    __tablename__ = "performance_reviews"
    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True)
    reviewer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False)
    review_period: Mapped[str] = mapped_column(String(50), nullable=False)
    review_year: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ReviewStatus] = mapped_column(SAEnum(ReviewStatus, name="review_status_enum"), default=ReviewStatus.DRAFT)
    overall_rating: Mapped[float | None] = mapped_column(Numeric(3, 1), nullable=True)
    strengths: Mapped[str | None] = mapped_column(Text, nullable=True)
    improvements: Mapped[str | None] = mapped_column(Text, nullable=True)
    goals_for_next_period: Mapped[str | None] = mapped_column(Text, nullable=True)
    employee_comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    ratings: Mapped[dict] = mapped_column(JSON, default=dict)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)