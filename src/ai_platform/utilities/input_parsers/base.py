from abc import ABC, abstractmethod
from typing import ClassVar, List, Optional

from pydantic import BaseModel


class ParsedDocument(BaseModel):
    source_name: str
    content_type: str
    text: str
    page_count: Optional[int] = None


class DocumentParser(ABC):
    supported_content_types: ClassVar[List[str]]

    @abstractmethod
    def parse(self, file_bytes: bytes, source_name: str) -> ParsedDocument: ...
