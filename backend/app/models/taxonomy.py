import uuid

from sqlmodel import Field, SQLModel


class SpecializationTaxonomy(SQLModel, table=True):
    """Fixed list of specializations. Free text is banned — F17 triage routing
    depends on doctors being classified into this closed set."""

    __tablename__ = "specialization_taxonomy"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    slug: str = Field(index=True, unique=True, nullable=False)
    name_en: str
    name_ur: str | None = None
    is_active: bool = Field(default=True)
