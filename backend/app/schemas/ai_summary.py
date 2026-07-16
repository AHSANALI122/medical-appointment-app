from pydantic import BaseModel, Field


class AIDraftRequest(BaseModel):
    rough_notes: str = Field(min_length=1, max_length=4000)
