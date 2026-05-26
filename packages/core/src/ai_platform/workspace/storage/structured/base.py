from abc import ABC, abstractmethod
from typing import Generic, List, Optional, Type, TypeVar, ClassVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class RecordReference(BaseModel):
    id: str
    logical_name: str          # stable key, e.g. "company_context"
    file_name: str             # full path in bucket (incl prefix)


class StoredRecord(BaseModel, Generic[T]):
    data: T
    reference: RecordReference


class RecordRepository(Generic[T]):
    model_cls: ClassVar[type[T]]

    def __init__(self, prefix: Optional[str] = None):
        self.prefix = prefix

    def _file_name(self, logical_name: str) -> str:
        return f"{self.prefix}/{logical_name}.json" if self.prefix else f"{logical_name}.json"

    def parse(self, json_str: str) -> T:
        return self.model_cls.model_validate_json(json_str)

    @abstractmethod
    def put_canonical(self, logical_name: str, data: T) -> StoredRecord[T]:
        raise NotImplementedError

    @abstractmethod
    def get_canonical(self, logical_name: str) -> StoredRecord[T]:
        raise NotImplementedError

    @abstractmethod
    def list_canonicals(self) -> List[str]:
        """Return logical names (not full file paths)."""
        raise NotImplementedError
