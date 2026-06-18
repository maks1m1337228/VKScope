"""SQLAlchemy-модели PostgreSQL для VKScope."""

from datetime import datetime
from enum import Enum

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class AnalysisStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vk_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    first_name: Mapped[str] = mapped_column(String(128), default="")
    last_name: Mapped[str] = mapped_column(String(128), default="")
    # User access_token (OAuth); для диплома — без шифрования
    access_token: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    token_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    sessions: Mapped[list["AnalysisSession"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class AnalysisSession(Base):
    __tablename__ = "analysis_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), default=AnalysisStatus.PENDING.value)

    user: Mapped["User"] = relationship(back_populates="sessions")
    recommendations: Mapped[list["RecommendedGroup"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="RecommendedGroup.weight.desc()",
    )


class RecommendedGroup(Base):
    __tablename__ = "recommended_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"),
        index=True,
    )
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    group_name: Mapped[str] = mapped_column(String(512), default="")
    members_count: Mapped[int] = mapped_column(Integer, default=0)
    photo_url: Mapped[str] = mapped_column(String(1024), default="")
    photo_vk_id: Mapped[str] = mapped_column(String(64), default="")
    weight: Mapped[float] = mapped_column(Float, default=0.0)
    # Порядок выдачи в карусели (0..N-1)
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    session: Mapped["AnalysisSession"] = relationship(back_populates="recommendations")
