from datetime import datetime

from pydantic import BaseModel


class AccountDeletionRead(BaseModel):
    deleted_at: datetime | None
    purge_after: datetime | None
    message: str
