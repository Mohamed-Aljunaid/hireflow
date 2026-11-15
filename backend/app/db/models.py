import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CV(Base):
    __tablename__ = "cvs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(127))
    raw_text: Mapped[str] = mapped_column(Text)
    parsed: Mapped[dict[str, Any]] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
