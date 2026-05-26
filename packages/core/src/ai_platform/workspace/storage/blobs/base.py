
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from pydantic import BaseModel

class PutFilePayload(BaseModel):
    logical_name: str
    bytes_data: bytes
    content_type: Optional[str] = None
    metadata: Dict[str, str] = {}

class FileReference(BaseModel):
    id: str
    logical_name: str
    file_name: str
    content_type: Optional[str] = None

class FileRepository(ABC):
    @abstractmethod
    def put_canonical_file(self, payload: PutFilePayload) -> FileReference:
        raise NotImplementedError

    @abstractmethod
    def get_canonical_file_bytes(self, logical_name: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def get_canonoical_file_metadata(self, logical_name: str) -> Dict[str, str]:
        raise NotImplementedError
    
    @abstractmethod
    def list_canonical_files(self, filters: Dict[str, Any]) -> Dict[str, FileReference]:
        raise NotImplementedError
