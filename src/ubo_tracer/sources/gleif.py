"""Global Legal Entity Identifier Foundation (GLEIF) public relationship API.

Free public API (no key required) for ultimate and direct corporate parents.
"""

import requests
from typing import List, Optional
from ubo_tracer.sources.base import BaseSource, Document


class GLEIFSource(BaseSource):
    """Client for GLEIF search & relationship API."""

    BASE_URL = "https://api.gleif.org/api/v1"

    def __init__(self):
        super().__init__(name="gleif")

    def is_available(self) -> bool:
        return True

    def fetch(self, entity_id: str, entity_name: Optional[str] = None) -> List[Document]:
        """Fetch direct and ultimate parent relationships for LEI or company name."""
        clean_id = entity_id.strip()

        # Check if entity_id looks like a 20-character LEI
        try:
            if len(clean_id) == 20 and clean_id.isalnum():
                url = f"{self.BASE_URL}/lei-records/{clean_id}/direct-parent-relationship"
            else:
                # Search by name
                search_term = entity_name or clean_id
                url = f"{self.BASE_URL}/fuzzycompletions?field=fulltext&q={requests.utils.quote(search_term)}"
                resp = requests.get(url, headers={"Accept": "application/json"}, timeout=10)
                if resp.status_code != 200:
                    return []
                data = resp.json()
                if not data.get("data"):
                    return []
                lei = data["data"][0].get("relationships", {}).get("lei-record", {}).get("data", {}).get("id")
                if not lei:
                    return []
                url = f"{self.BASE_URL}/lei-records/{lei}/direct-parent-relationship"

            resp = requests.get(url, headers={"Accept": "application/json"}, timeout=10)
            if resp.status_code != 200:
                return []

            rel_data = resp.json()
            # Format parent relationship info into content_text
            content = f"GLEIF Record for {clean_id}: Parent relationship: {rel_data}"
            return [
                Document(
                    document_id=f"gleif_{clean_id}",
                    source_name=self.name,
                    entity_id=clean_id,
                    entity_name=entity_name or clean_id,
                    content_text=content,
                    raw_data=rel_data,
                )
            ]
        except Exception:
            return []

