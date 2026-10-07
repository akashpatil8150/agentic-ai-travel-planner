from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum

from sqlalchemy import (
    Date,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TripStatus(str, Enum):
    DRAFT = "DRAFT"
    PLANNING = "PLANNING"
    READY = "READY"


class Trip(Base):
    __tablename__ = "trips"

    # Primary Key
    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    # User Foreign Key
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    # Route
    source_city: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    destination_city: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    # Dates
    start_date: Mapped[date] = mapped_column(
        Date,
        nullable=False
    )

    end_date: Mapped[date] = mapped_column(
        Date,
        nullable=False
    )

    # Traveller Details
    adults: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    children: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0
    )

    travellers: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    # Trip Information
    trip_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )

    # Budget
    budget: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True
    )

    # Transport Preference
    transport_pref: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True
    )

    # User Preferences
    preferences: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list
    )

    # Workflow Status
    status: Mapped[TripStatus] = mapped_column(
        SQLEnum(TripStatus),
        default=TripStatus.DRAFT,
        nullable=False
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationship
    user = relationship(
        "User",
        back_populates="trips"
    )