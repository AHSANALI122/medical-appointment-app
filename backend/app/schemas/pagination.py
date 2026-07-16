from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int

    @classmethod
    def create(cls, items: list[T], *, page: int, page_size: int, total: int) -> "Page[T]":
        return cls(items=items, page=page, page_size=page_size, total=total)
