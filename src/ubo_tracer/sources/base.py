"""Base interface for all data sources in UBO Tracer."""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class Document(BaseModel):
    """Normalized document fetched from any source (API, file, mock)."""
    document_id: str
    source_name: str
    entity_id: str
    entity_name: str
    content_text: str
    raw_data: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BaseSource(ABC):
    """Abstract interface that all data sources must implement."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def fetch(self, entity_id: str, entity_name: Optional[str] = None) -> List[Document]:
        """Fetch documents relevant to the given entity.
        
        Returns a list of Document objects, or empty list if no records found.
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this data source is configured and accessible."""
        pass

