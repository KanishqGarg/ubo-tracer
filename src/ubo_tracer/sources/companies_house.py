"""Companies House API client for UK Persons with Significant Control (PSC).

Gracefully skips if COMPANIES_HOUSE_API_KEY environment variable is missing.
"""

import os
import requests
from typing import List, Optional
from ubo_tracer.sources.base import BaseSource, Document


class CompaniesHouseSource(BaseSource):
    """Client for UK Companies House REST API."""

    BASE_URL = "https://api.company-information.service.gov.uk"

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(name="companies_house")
        self.api_key = api_key or os.environ.get("COMPANIES_HOUSE_API_KEY")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def fetch(self, entity_id: str, entity_name: Optional[str] = None) -> List[Document]:
        """Fetch PSC (Persons with Significant Control) records for a UK company number."""
        if not self.is_available():
            return []

        # Assuming entity_id is a UK company number (8 chars e.g. 01234567 or SC123456)
        clean_id = entity_id.strip()
        url = f"{self.BASE_URL}/company/{clean_id}/persons-with-significant-control"

        try:
            response = requests.get(
                url,
                auth=(self.api_key, ""),
                headers={"Accept": "application/json"},
                timeout=10,
            )
            if response.status_code == 404:
                return []
            response.raise_for_status()

            data = response.json()
            items = data.get("items", [])

            # Convert PSC items into a textual Document that can be inspected and verified
            lines = [f"Companies House PSC Register for Company {clean_id}:"]
            for item in items:
                name = item.get("name", "Unknown")
                kind = item.get("kind", "")
                natures_of_control = item.get("natures_of_control", [])
                lines.append(f"- Name: {name}")
                lines.append(f"  Kind: {kind}")
                lines.append(f"  Natures of control: {', '.join(natures_of_control)}")

            doc_text = "\n".join(lines)
            return [
                Document(
                    document_id=f"ch_psc_{clean_id}",
                    source_name=self.name,
                    entity_id=clean_id,
                    entity_name=entity_name or clean_id,
                    content_text=doc_text,
                    raw_data=data,
                )
            ]
        except Exception:
            # Gracefully handle network or auth issues
            return []

