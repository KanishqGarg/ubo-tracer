"""Loads plain text/PDF corporate filings from a directory."""

from pathlib import Path
from typing import List, Optional
from ubo_tracer.sources.base import BaseSource, Document


class FilingTextSource(BaseSource):
    """Loads plain text filings from a directory."""

    def __init__(self, filing_dir: str = "data/filings"):
        super().__init__(name="filing_text")
        self.filing_dir = Path(filing_dir)

    def is_available(self) -> bool:
        return self.filing_dir.exists()

    def fetch(self, entity_id: str, entity_name: Optional[str] = None) -> List[Document]:
        if not self.is_available():
            return []

        docs = []
        # Look for entity_id.txt or files starting with entity_id
        for p in self.filing_dir.glob(f"*{entity_id}*.txt"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    docs.append(
                        Document(
                            document_id=p.stem,
                            source_name=self.name,
                            entity_id=entity_id,
                            entity_name=entity_name or entity_id,
                            content_text=f.read(),
                            metadata={"filepath": str(p)},
                        )
                    )
            except Exception:
                pass
        return docs

