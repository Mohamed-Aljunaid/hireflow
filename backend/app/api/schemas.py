import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.agents.schemas.cv import ParsedCV


class CVRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    content_type: str
    created_at: datetime
    parsed: ParsedCV
