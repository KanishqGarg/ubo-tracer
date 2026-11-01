"""Report Generator: Markdown and JSON reports with full audit trail and human sign-off."""

from __future__ import annotations
import json
from typing import Dict, Any, List
from ubo_tracer.models import EffectiveOwnershipResult, UBOStatus


DISCLAIMER_TEXT = (
    "> [!WARNING]\n"
    "> **COMPLIANCE DISCLAIMER**: This report is produced by an automated prototype agent as decision support\n"
    "> and does NOT constitute legal advice or formal regulatory certification. A qualified compliance\n"
    "> officer must review source evidence, verify corporate registries, and sign off on all UBO determinations.\n"
)


class ReportGenerator:
    """Generates audit-ready Markdown and JSON compliance reports."""

    @staticmethod
    def generate_json_report(trace_result: Dict[str, Any]) -> str:
        results: List[EffectiveOwnershipResult] = trace_result.get("results", [])
        graph = trace_result.get("graph")
        edges_data = []
        if graph:
            for edg_list in graph.incoming_edges.values():
                for e in edg_list:
                    edges_data.append(e.to_dict())

        report_dict = {
            "disclaimer": "This output is automated decision support, not legal advice. A qualified compliance officer is accountable for the final determination.",
            "target_id": trace_result.get("target_id"),
            "target_name": trace_result.get("target_name"),
            "steps_taken": trace_result.get("steps_taken"),
            "limit_reached": trace_result.get("limit_reached"),
            "summary": {
                "total_candidates": len(results),
                "ubos_above_threshold": len([r for r in results if r.status == UBOStatus.ABOVE]),
                "uncertain_count": len([r for r in results if r.status == UBOStatus.UNCERTAIN]),
                "unresolved_count": len([r for r in results if r.status == UBOStatus.UNRESOLVED]),
                "below_count": len([r for r in results if r.status == UBOStatus.BELOW]),
                "requires_human_review": any(r.requires_human_review for r in results),
            },
            "beneficial_owners": [r.to_dict() for r in results],
            "verified_ownership_edges": edges_data,
            "rejected_edges": trace_result.get("rejected_edges", []),
        }
        return json.dumps(report_dict, indent=2)

    @staticmethod
    def generate_markdown_report(trace_result: Dict[str, Any]) -> str:
        results: List[EffectiveOwnershipResult] = trace_result.get("results", [])
        target_name = trace_result.get("target_name", trace_result.get("target_id"))
        rejected = trace_result.get("rejected_edges", [])
        graph = trace_result.get("graph")

        md = []
        md.append(f"# UBO Tracer Audit Report: {target_name}\n")
        md.append(DISCLAIMER_TEXT)
        md.append(f"**Target Entity ID**: `{trace_result.get('target_id')}`  ")
        md.append(f"**Steps Taken**: {trace_result.get('steps_taken')}  ")
        md.append(f"**Limit Reached**: {'Yes' if trace_result.get('limit_reached') else 'No'}\n")

        # Summary Table
        md.append("## Executive Summary\n")
        md.append("| Candidate Owner | Type | Effective Ownership | Classification | Human Review Needed |")
        md.append("| :--- | :--- | :--- | :--- | :--- |")

        for r in results:
            if r.effective_percentage_min == r.effective_percentage_max:
                pct_str = f"{r.effective_percentage_min:.2f}%"
            else:
                pct_str = f"[{r.effective_percentage_min:.2f}%, {r.effective_percentage_max:.2f}%]"

            review_badge = "⚠️ **FLAGGED**" if r.requires_human_review else "✅ No"
            md.append(f"| **{r.owner_name}** | `{r.owner_type.value}` | {pct_str} | **{r.status.value}** | {review_badge} |")

        # Detailed breakdown per candidate
        md.append("\n## Audit Trail & Calculation Breakdown\n")
        for r in results:
            md.append(f"### {r.owner_name} ({r.owner_id})\n")
            md.append(f"- **Entity Type**: {r.owner_type.value}")
            md.append(f"- **Final Classification**: `{r.status.value}`")
            md.append(f"- **Effective Percentage Range**: [{r.effective_percentage_min:.2f}%, {r.effective_percentage_max:.2f}%]")

            if r.requires_human_review:
                md.append("\n> [!CAUTION]\n> **Human Review Required**:")
                for reason in r.review_reasons:
                    md.append(f"> - {reason}")
                md.append("")

            if r.control_flags:
                md.append("**Control Mechanisms (Separated from Ownership %):**")
                for cf in r.control_flags:
                    md.append(f"- 🔑 {cf}")
                md.append("")

            if r.paths:
                md.append("**Traversed Ownership Paths & Mathematical Formulas:**")
                for p in r.paths:
                    md.append(f"- `{p.formula_str()}`")
                    for e in p.edges:
                        md.append(f"  - Link: `{e.owner_name}` ➔ `{e.owned_id}` ({e.percentage_min}% - {e.percentage_max}%)")
                        md.append(f"    - *Document*: `{e.evidence.document_id}` ({e.evidence.source_name})")
                        md.append(f"    - *Verbatim Quote*: \"{e.evidence.quote}\"")
            else:
                md.append("- *No verified path leading to target entity found.*")

            md.append("")

        # Rejected Edges Section (Rule #3)
        if rejected:
            md.append("## Rejected Edges (Verifier Audit Log)\n")
            md.append("| Claimed Owner | Target | Claimed % | Document | Rejection Reason |")
            md.append("| :--- | :--- | :--- | :--- | :--- |")
            for rej in rejected:
                e = rej.get("edge", {})
                reason = rej.get("reason", "Failed verification")
                md.append(f"| {e.get('owner_name')} | {e.get('owned_id')} | {e.get('percentage_min')}% | {rej.get('doc_id')} | ❌ {reason} |")
            md.append("")

        # Human Reviewer Sign-Off Block
        md.append("## Compliance Officer Sign-Off\n")
        md.append("```text")
        md.append("Reviewer Name: ___________________________")
        md.append("Role / Title:  ___________________________")
        md.append("Decision:      [ ] Approved   [ ] Rejected   [ ] Escalated to Legal")
        md.append("Comments:      ___________________________")
        md.append("Date:          ____ / ____ / ________")
        md.append("Signature:     ___________________________")
        md.append("```\n")

        return "\n".join(md)

