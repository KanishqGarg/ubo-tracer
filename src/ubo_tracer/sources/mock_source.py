"""Mock data source for reproducible offline testing and synthetic scenarios."""

import os
import json
from pathlib import Path
from typing import List, Optional
from ubo_tracer.sources.base import BaseSource, Document


class MockSource(BaseSource):
    """Loads synthetic data from local JSON or text files in data/synthetic."""

    def __init__(self, synthetic_dir: str = "data/synthetic"):
        super().__init__(name="mock")
        self.synthetic_dir = Path(synthetic_dir)

    def is_available(self) -> bool:
        return self.synthetic_dir.exists()

    def fetch(self, entity_id: str, entity_name: Optional[str] = None) -> List[Document]:
        """Look for scenario files matching entity_id or normalized entity_name."""
        docs = []
        if not self.is_available():
            return docs

        def normalize_id(s: str) -> str:
            return s.lower().replace(" ", "").replace("_", "").replace("-", "").replace(".", "")

        norm_eid = normalize_id(entity_id)
        norm_name = normalize_id(entity_name) if entity_name else ""

        # Search synthetic scenarios directory for matching files
        for scenario_dir in sorted(self.synthetic_dir.glob("scenario_*")):
            if not scenario_dir.is_dir():
                continue

            # Look for docs.json
            docs_file = scenario_dir / "docs.json"
            if docs_file.exists():
                try:
                    with open(docs_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        for item in data.get("documents", []):
                            target_ent = normalize_id(item.get("entity_id", ""))
                            target_name = normalize_id(item.get("entity_name", ""))
                            
                            # Match against entity_id or entity_name
                            if target_ent in (norm_eid, norm_name) or (target_name and target_name in (norm_eid, norm_name)):
                                docs.append(
                                    Document(
                                        document_id=item.get("document_id", f"{scenario_dir.name}_{entity_id}"),
                                        source_name="mock",
                                        entity_id=entity_id,
                                        entity_name=entity_name or entity_id,
                                        content_text=item.get("content_text", ""),
                                        raw_data=item.get("raw_data"),
                                        metadata={"scenario": scenario_dir.name, **item.get("metadata", {})},
                                    )
                                )
                except Exception:
                    pass

            # Also check for text files like filings/entity_id.txt
            txt_file = scenario_dir / f"{entity_id}.txt"
            if txt_file.exists():
                with open(txt_file, "r", encoding="utf-8") as f:
                    docs.append(
                        Document(
                            document_id=f"{scenario_dir.name}_{entity_id}_txt",
                            source_name="mock",
                            entity_id=entity_id,
                            entity_name=entity_name or entity_id,
                            content_text=f.read(),
                            metadata={"scenario": scenario_dir.name},
                        )
                    )

        return docs
