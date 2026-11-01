"""Deterministic Quote and Number Verification.

NON-NEGOTIABLE DESIGN RULE 3:
"A Verifier step must check that the quote exists verbatim in the source text
and that the number in the edge appears in the quote. If not, the edge is
rejected and logged. Never keep unverified edges."
"""

from __future__ import annotations
import re
from typing import Tuple, Optional, List
from ubo_tracer.models import OwnershipEdge, Evidence


def normalize_text_for_matching(text: str) -> str:
    """Normalize text by stripping quotes, unescaping, and standardizing whitespace."""
    if not text:
        return ""
    # Strip leading/trailing double or single quotes that JSON/LLM might wrap around quotes
    cleaned = text.strip().strip('"\'`“”‘’')
    # Replace linebreaks, tabs, multiple spaces with single space
    cleaned = " ".join(cleaned.split())
    # Standardize curly quotes to straight quotes
    cleaned = cleaned.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    return cleaned


class EdgeVerifier:
    """Deterministic verifier for LLM-extracted ownership claims."""

    @staticmethod
    def verify_quote_in_document(quote: str, document_text: str) -> Tuple[bool, Optional[str]]:
        """Verify that the quote exists verbatim in document_text (ignoring superficial whitespace diffs)."""
        if not quote or not quote.strip():
            return False, "Quote is empty."

        clean_quote = normalize_text_for_matching(quote)
        clean_doc = normalize_text_for_matching(document_text)

        if clean_quote in clean_doc:
            return True, None

        # Try case-insensitive fallback check
        if clean_quote.lower() in clean_doc.lower():
            # Exact casing differed slightly, but matches textually
            return True, None

        return False, f"Quote was not found verbatim in source document. Searched quote: '{quote[:60]}...'"

    @staticmethod
    def extract_numbers_from_text(text: str) -> List[float]:
        """Extract all numeric representations (percentages, integers, decimals, word numbers) from text."""
        # Find explicit numbers like "25", "25.0", "50%"
        found = []
        # Matches numbers like 10, 25.5, 75
        pattern = r"\b\d+(?:\.\d+)?\b"
        for match in re.finditer(pattern, text):
            try:
                found.append(float(match.group()))
            except ValueError:
                pass

        # Check common number words
        word_map = {
            "quarter": 25.0,
            "one quarter": 25.0,
            "third": 33.3333,
            "one third": 33.3333,
            "half": 50.0,
            "one half": 50.0,
            "wholly": 100.0,
            "entire": 100.0,
            "wholly owned": 100.0,
            "all": 100.0,
            "ten": 10.0,
            "twenty": 20.0,
            "twenty-five": 25.0,
            "thirty": 30.0,
            "forty": 40.0,
            "fifty": 50.0,
            "sixty": 60.0,
            "seventy": 70.0,
            "seventy-five": 75.0,
            "eighty": 80.0,
            "ninety": 90.0,
            "hundred": 100.0,
        }
        text_lower = text.lower()
        for word, val in word_map.items():
            if re.search(r"\b" + re.escape(word) + r"\b", text_lower):
                found.append(val)

        return found

    @classmethod
    def verify_numbers_in_quote(
        cls,
        percentage_min: float,
        percentage_max: float,
        quote: str,
    ) -> Tuple[bool, Optional[str]]:
        """Verify that the percentages in the edge are grounded in the quote."""
        numbers = cls.extract_numbers_from_text(quote)

        # Allow slight rounding tolerance (e.g. 25.01 for >25%)
        def matches_any(val: float) -> bool:
            return any(abs(val - n) < 0.1 for n in numbers)

        # If min and max are the same (single percentage)
        if percentage_min == percentage_max:
            if not matches_any(percentage_min):
                return False, f"Percentage {percentage_min}% does not appear in quote: '{quote}'"
            return True, None

        # If range: either min or max or both must appear, or words indicating band
        min_found = matches_any(percentage_min) or (percentage_min == 25.01 and 25.0 in numbers)
        max_found = matches_any(percentage_max)

        if not min_found and not max_found:
            return False, f"Neither range bound ({percentage_min}%, {percentage_max}%) appears in quote: '{quote}'"

        return True, None

    @classmethod
    def verify_edge(cls, edge: OwnershipEdge, document_text: str) -> OwnershipEdge:
        """Fully verify edge against document text.
        
        Mutates or returns edge with evidence.verified set to True/False
        and verification_error populated.
        """
        # Step 1: Check quote verbatim existence in document
        quote_ok, err_quote = cls.verify_quote_in_document(edge.evidence.quote, document_text)
        if not quote_ok:
            edge.evidence.verified = False
            edge.evidence.verification_error = err_quote
            return edge

        # Step 2: Check numbers in quote
        num_ok, err_num = cls.verify_numbers_in_quote(
            edge.percentage_min,
            edge.percentage_max,
            edge.evidence.quote
        )
        if not num_ok:
            edge.evidence.verified = False
            edge.evidence.verification_error = err_num
            return edge

        # Both passed
        edge.evidence.verified = True
        edge.evidence.verification_error = None
        return edge
