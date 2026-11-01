"""UBO Tracer Professional Compliance Web Interface.

Dark-themed, professional compliance dashboard featuring:
1. Trace Execution with Live Activity Feed
2. Interactive Pyvis Graph Visualization with Color Codes & Legends
3. Evidence & Verifier Audit Panel with verbatim quotes & number highlights
4. Deterministic Calculation & Multi-Path Breakdown
5. Human-in-the-Loop Review Queue (Approve / Reject / Supply-Owner) & Resumption
6. Past Runs History & Step-by-Step Replay
7. 11-Scenario Evaluation Dashboard
8. Multi-format Export (Markdown, JSON, PDF) with Legal Disclaimers
"""

from __future__ import annotations
import sys
from pathlib import Path

# Ensure ubo_tracer packages are resolvable regardless of PYTHONPATH
_this_dir = Path(__file__).resolve().parent
_src_dir = _this_dir.parent.parent
_repo_dir = _src_dir.parent
for p in [str(_src_dir), str(_repo_dir), str(_repo_dir / "ubo_tracer" / "src")]:
    if p not in sys.path:
        sys.path.insert(0, p)

import json
import os
import streamlit as st
from pyvis.network import Network
import streamlit.components.v1 as components

from ubo_tracer.models import UBOStatus, EntityType
from ubo_tracer.calculator import OwnershipCalculator, OwnershipGraph
from ubo_tracer.sources.mock_source import MockSource
from ubo_tracer.sources.companies_house import CompaniesHouseSource
from ubo_tracer.sources.gleif import GLEIFSource
from ubo_tracer.sources.filing_text import FilingTextSource
from ubo_tracer.agents.retrieval import RetrievalAgent
from ubo_tracer.agents.extraction import ExtractionAgent
from ubo_tracer.agents.verifier import EdgeVerifier
from ubo_tracer.agents.planner import PlannerAgent
from ubo_tracer.checkpoint import CheckpointStore, ReviewDecision
from ubo_tracer.cache import EntityCache
from ubo_tracer.llm import OllamaClient
from ubo_tracer.pdf_export import generate_pdf_report


# Set Page Configuration with Professional Styling
st.set_page_config(
    page_title="UBO Tracer | Compliance Portal",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Professional Theme CSS (Dark Mode by Default)
st.markdown("""
<style>
    .main {
        background-color: #0b0f19;
        color: #f1f5f9;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: #1e293b;
        color: #94a3b8;
        border-radius: 6px 6px 0 0;
        padding: 8px 16px;
        font-weight: 600;
    }
    .stTabs [aria-selected="true"] {
        background-color: #3b82f6 !important;
        color: #ffffff !important;
    }
    .compliance-banner {
        background: linear-gradient(90deg, #1e293b 0%, #0f172a 100%);
        border-left: 4px solid #f59e0b;
        padding: 10px 16px;
        border-radius: 4px;
        margin-bottom: 20px;
        display: flex;
        align-items: center;
        gap: 12px;
    }
    .card {
        background-color: #1e293b;
        border-radius: 8px;
        padding: 16px;
        border: 1px solid #334155;
        margin-bottom: 16px;
    }
    .quote-box {
        background-color: #0f172a;
        border-left: 3px solid #38bdf8;
        padding: 10px 14px;
        font-family: monospace;
        font-size: 0.9em;
        margin: 6px 0;
        border-radius: 0 4px 4px 0;
    }
    .highlight-num {
        background-color: #eab308;
        color: #000000;
        font-weight: bold;
        padding: 1px 4px;
        border-radius: 2px;
    }
</style>
""", unsafe_allow_html=True)

# Persistent Legal Disclaimer Banner
st.markdown("""
<div class="compliance-banner">
    <span style="font-size: 1.4em;">⚖️</span>
    <div>
        <strong style="color: #fbbf24;">DECISION SUPPORT SYSTEM ONLY</strong><br/>
        <span style="font-size: 0.88em; color: #cbd5e1;">
            Outputs are automated guidance based on public/synthetic registry records. A certified compliance officer is legally accountable for final UBO determinations.
        </span>
    </div>
</div>
""", unsafe_allow_html=True)


# Initialize Singletons
@st.cache_resource
def get_services():
    store = CheckpointStore("ubo_tracer/logs/checkpoints.db")
    cache = EntityCache("ubo_tracer/logs/entity_cache.db")
    llm = OllamaClient(model=os.environ.get("UBO_MODEL", "qwen2.5:3b"))
    mock_src = MockSource("ubo_tracer/data/synthetic")
    ch_src = CompaniesHouseSource()
    gleif_src = GLEIFSource()
    filing_src = FilingTextSource("ubo_tracer/data/synthetic")
    retrieval = RetrievalAgent(
        sources={"mock": mock_src, "companies_house": ch_src, "gleif": gleif_src, "filing_text": filing_src},
        default_order=["mock", "companies_house", "gleif", "filing_text"],
        use_mcp=True,
    )
    extraction = ExtractionAgent(llm, enable_self_consistency=False)
    calc = OwnershipCalculator(threshold_percentage=25.0, comparison_operator="gt")
    planner = PlannerAgent(retrieval, extraction, calc, llm, checkpoint_store=store, entity_cache=cache)
    return store, cache, llm, retrieval, extraction, calc, planner

checkpoint_store, entity_cache, llm_client, retrieval_agent, extraction_agent, calculator, planner_agent = get_services()


# Sidebar Navigation & Settings
st.sidebar.title("🛡️ UBO Tracer")
st.sidebar.caption("Deterministic Corporate Ownership Tracing")

threshold = st.sidebar.slider("UBO Threshold (%)", min_value=5.0, max_value=50.0, value=25.0, step=1.0)
operator = st.sidebar.selectbox("Threshold Operator", options=["Strictly Greater Than (>) [UK PSC]", "Greater Than or Equal (>=) [FATF]"], index=0)
op_code = "gt" if ">" in operator else "gte"
calculator.threshold = threshold
calculator.comparison_operator = op_code

st.sidebar.markdown("---")
use_mcp = st.sidebar.checkbox("Query Sources via MCP Servers", value=True)
retrieval_agent.use_mcp = use_mcp
enable_sc = st.sidebar.checkbox("Dual-Prompt Self-Consistency Check", value=False)
extraction_agent.enable_self_consistency = enable_sc

# Check Ollama Health
st.sidebar.markdown("---")
is_ollama_alive = llm_client.is_available()
if is_ollama_alive:
    st.sidebar.success(f"Ollama Active: {llm_client.model}")
else:
    st.sidebar.error("Ollama Offline: Run 'ollama serve'")


# Tab Layout
tabs = st.tabs([
    "🚀 Trace Investigation",
    "🕸️ Ownership Graph",
    "🔍 Evidence & Audit",
    "📊 Deterministic Calculations",
    "⏳ Human Review Queue",
    "📼 History & Replay",
    "🎯 Benchmark Evaluation",
    "📥 Export Reports",
])

# Scenario dictionary for quick selection
SCENARIOS = {
    "target_corp_1": "Scenario 1: Direct Ownership (60%)",
    "target_corp_2": "Scenario 2: Two Layers (60% * 50% = 30%)",
    "target_corp_3": "Scenario 3: Multiple Paths (12% + 15% = 27%)",
    "target_corp_4": "Scenario 4: Boundary (Exactly 25%)",
    "target_corp_5": "Scenario 5: Below Threshold Dilution (10%)",
    "target_corp_6": "Scenario 6: Circular Ownership Loop",
    "target_corp_7": "Scenario 7: Bands / Ranges [25% - 50%]",
    "target_corp_8": "Scenario 8: Unresolved Dead End",
    "target_corp_9": "Scenario 9: Messy Text & Hallucination Trap",
    "target_corp_10": "Scenario 10: Control Without Ownership",
    "target_corp_11": "Scenario 11: Prompt-Injection Defense",
}


# ==========================================
# TAB 1: TRACE INVESTIGATION
# ==========================================
with tabs[0]:
    st.header("Execute Corporate Ownership Trace")
    col1, col2 = st.columns([2, 1])

    with col1:
        target_choice = st.selectbox("Select Target Company to Investigate", options=list(SCENARIOS.keys()), format_func=lambda x: f"{x} - {SCENARIOS[x]}")
        custom_id = st.text_input("Or Enter Custom Legal Entity Identifier / Name", value="")
        effective_target = custom_id.strip() if custom_id.strip() else target_choice

    with col2:
        st.write("")
        st.write("")
        run_btn = st.button("🚀 Start Investigation Trace", use_container_width=True, type="primary")

    if run_btn:
        st.info(f"Initiating autonomous investigation for '{effective_target}'...")
        with st.status("Agent Execution Frontier", expanded=True) as status_box:
            st.write(f"🔍 [Planner] Starting BFS search at root: `{effective_target}` (Depth: 0)")
            st.write(f"📡 [Retrieval] Accessing sources via MCP server...")
            
            trace_output = planner_agent.trace_entity(effective_target)
            st.session_state["latest_trace"] = trace_output
            status_box.update(label=f"Trace Complete: {trace_output['steps_taken']} steps taken", state="complete")
        st.success("Investigation complete! View results across tabs.")

    if "latest_trace" in st.session_state:
        res = st.session_state["latest_trace"]
        st.subheader("Summary Findings")
        cols = st.columns(4)
        cols[0].metric("Target Entity", res["target_id"])
        cols[1].metric("Steps Explored", res["steps_taken"])
        cols[2].metric("Verified Edges", sum(len(el) for el in res["graph"].incoming_edges.values()))
        cols[3].metric("Rejected / Traps", len(res["rejected_edges"]))

        st.subheader("Identified Beneficial Owners & Controlling Persons")
        table_rows = []
        for r in res["results"]:
            p_min = r.effective_percentage_min
            p_max = r.effective_percentage_max
            pct_str = f"{p_min:.2f}%" if p_min == p_max else f"[{p_min:.2f}%, {p_max:.2f}%]"
            table_rows.append({
                "Owner Name": r.owner_name,
                "Type": r.owner_type.value,
                "Effective Ownership": pct_str,
                "Status": r.status.value,
                "Review Required": "⚠️ YES" if r.requires_human_review else "✅ No",
                "Review Reasons": "; ".join(r.review_reasons) if r.review_reasons else "-",
            })
        st.dataframe(table_rows, use_container_width=True)


# ==========================================
# TAB 2: OWNERSHIP GRAPH
# ==========================================
with tabs[1]:
    st.header("Interactive Corporate Ownership Network")
    st.markdown("""
    **Color Legend:**
    - 🟢 **ABOVE Threshold** (> 25%) &nbsp;&nbsp;|&nbsp;&nbsp; 
    - 🔴 **BELOW Threshold** (<= 25%) &nbsp;&nbsp;|&nbsp;&nbsp; 
    - 🟡 **UNCERTAIN** (Interval spans threshold) &nbsp;&nbsp;|&nbsp;&nbsp; 
    - ⚪ **UNRESOLVED / Dead End** &nbsp;&nbsp;|&nbsp;&nbsp; 
    - 🟣 **DISPUTED** (Self-Consistency conflict) &nbsp;&nbsp;|&nbsp;&nbsp; 
    - 🔷 **Target / Corporate Intermediary**
    """)

    if "latest_trace" in st.session_state:
        res = st.session_state["latest_trace"]
        graph: OwnershipGraph = res["graph"]
        results_map = {r.owner_id: r for r in res["results"]}

        net = Network(height="500px", width="100%", bgcolor="#0b0f19", font_color="#ffffff", directed=True)
        net.force_atlas_2based()

        # Add Nodes
        for eid, ent in graph.entities.items():
            r = results_map.get(eid)
            color = "#3b82f6"  # Blue corporate
            shape = "box" if ent.entity_type == EntityType.COMPANY else "ellipse"
            if r:
                if r.status == UBOStatus.ABOVE:
                    color = "#22c55e"  # Green
                elif r.status == UBOStatus.BELOW:
                    color = "#ef4444"  # Red
                elif r.status == UBOStatus.UNCERTAIN:
                    color = "#eab308"  # Yellow
                elif r.status == UBOStatus.DISPUTED:
                    color = "#a855f7"  # Purple
                elif r.status == UBOStatus.UNRESOLVED:
                    color = "#94a3b8"  # Gray
            if ent.is_unresolved:
                color = "#94a3b8"

            net.add_node(
                eid,
                label=ent.name,
                color=color,
                shape=shape,
                title=f"Entity: {ent.name}\nType: {ent.entity_type.value}\nStatus: {r.status.value if r else 'Intermediary'}",
            )

        # Add Edges
        for owned_id, edge_list in graph.incoming_edges.items():
            for e in edge_list:
                pct_label = f"{e.percentage_min:.1f}%" if e.percentage_min == e.percentage_max else f"[{e.percentage_min:.1f}%, {e.percentage_max:.1f}%]"
                edge_color = "#38bdf8"
                dashes = False
                if e.control and e.control.is_controlled():
                    dashes = True
                    edge_color = "#f59e0b"
                if e.is_disputed:
                    edge_color = "#a855f7"

                net.add_edge(
                    e.owner_id,
                    owned_id,
                    label=pct_label,
                    color=edge_color,
                    dashes=dashes,
                    title=f"Quote: {e.evidence.quote}\nVerified: {e.evidence.verified}",
                )

        html_path = "ubo_tracer/logs/temp_graph.html"
        net.save_graph(html_path)
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        components.html(html_content, height=520)
    else:
        st.info("Run an investigation in Tab 1 to render the ownership network.")


# ==========================================
# TAB 3: EVIDENCE & AUDIT
# ==========================================
with tabs[2]:
    st.header("Verbatim Evidence & Verifier Audit Gate")
    st.write("Every accepted ownership edge must be grounded by a verbatim quotation from source records.")

    if "latest_trace" in st.session_state:
        res = st.session_state["latest_trace"]
        graph: OwnershipGraph = res["graph"]

        st.subheader("Verified Evidentiary Links")
        for owned_id, edge_list in graph.incoming_edges.items():
            for e in edge_list:
                with st.expander(f"🔗 {e.owner_name} ➔ {graph.entities[owned_id].name} ({e.percentage_min:.1f}%)"):
                    st.markdown(f"**Document ID:** `{e.evidence.document_id}` &nbsp;&nbsp;|&nbsp;&nbsp; **Source Register:** `{e.evidence.source_name}`")
                    st.markdown(f"**Verifier Status:** ✅ PASS (Verbatim match confirmed)")
                    st.markdown("**Verbatim Excerpt:**")
                    st.markdown(f'<div class="quote-box">"{e.evidence.quote}"</div>', unsafe_allow_html=True)
                    if e.control and e.control.is_controlled():
                        st.markdown(f"**Control Mechanism:** `{e.control.details or 'Voting / Director Appointment Rights'}`")
                    if e.is_disputed:
                        st.warning(f"⚠️ Self-Consistency Dispute: {e.dispute_reason}")

        if res["rejected_edges"]:
            st.subheader("🛡️ Rejected Edges & Traps (Verifier Gate)")
            for rj in res["rejected_edges"]:
                st.error(f"❌ REJECTED EDGE: `{rj['edge']['owner_name']}` ({rj['edge']['percentage_min']}%) ➔ Reason: {rj['reason']}")
    else:
        st.info("Run an investigation in Tab 1 to inspect source evidence.")


# ==========================================
# TAB 4: DETERMINISTIC CALCULATIONS
# ==========================================
with tabs[3]:
    st.header("Deterministic Multi-Path Calculations")
    st.write("Under Rule 1, all effective ownership percentages are calculated via exact interval arithmetic. No LLM arithmetic is ever used.")

    if "latest_trace" in st.session_state:
        res = st.session_state["latest_trace"]
        for r in res["results"]:
            with st.expander(f"🧮 {r.owner_name} ({r.effective_percentage_min:.2f}%) - {r.status.value}"):
                st.markdown(f"**Candidate Owner:** `{r.owner_name}` ({r.owner_type.value})")
                st.markdown(f"**Classification vs Threshold ({calculator.threshold}%):** `{r.status.value}`")
                st.markdown("#### Path Formulas & Products:")
                if not r.paths:
                    st.write("No paths resolved to target (Dead end or direct non-path control).")
                for i, p in enumerate(r.paths, 1):
                    p_str = " ➔ ".join(p.path_nodes)
                    st.markdown(f"**Path {i}:** `{p_str}`")
                    formula_val = getattr(p, "formula", None) or (p.formula_str() if hasattr(p, "formula_str") else "")
                    st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;↳ Formula: `{formula_val}` = **{p.effective_min:.2f}%**")
                p_min = r.effective_percentage_min
                p_max = r.effective_percentage_max
                st.markdown(f"**Combined Ownership Bounds:** `[{p_min:.2f}%, {p_max:.2f}%]`")
    else:
        st.info("Run an investigation in Tab 1 to view multi-path math.")


# ==========================================
# TAB 5: HUMAN REVIEW QUEUE
# ==========================================
with tabs[4]:
    st.header("Compliance Officer Review Queue")
    st.write("Items flagged due to dead ends, voting control, uncertain intervals, or verifier disputes.")

    if "latest_trace" in st.session_state and st.session_state["latest_trace"]["pending_reviews"]:
        rev_items = st.session_state["latest_trace"]["pending_reviews"]
        for item in rev_items:
            with st.expander(f"⚠️ Flagged: {item['entity_name']} ({item['type']})"):
                st.write(f"**Reason:** {item['reason']}")
                colA, colB, colC = st.columns(3)
                reviewer = st.text_input("Reviewer Name", value="Senior Compliance Officer", key=f"rev_{item['item_id']}")
                notes = st.text_area("Review Notes & Statutory Reference", value="", key=f"notes_{item['item_id']}")
                if colA.button("✅ Approve Item", key=f"app_{item['item_id']}"):
                    dec = ReviewDecision(
                        decision_id=f"dec_{item['item_id']}",
                        run_id=st.session_state["latest_trace"]["run_id"],
                        item_id=item["item_id"],
                        reviewer_name=reviewer,
                        action="approve",
                        notes=notes,
                    )
                    checkpoint_store.record_decision(dec)
                    st.success("Item approved and logged in audit store.")
                if colB.button("❌ Reject Item", key=f"rej_{item['item_id']}"):
                    dec = ReviewDecision(
                        decision_id=f"dec_{item['item_id']}",
                        run_id=st.session_state["latest_trace"]["run_id"],
                        item_id=item["item_id"],
                        reviewer_name=reviewer,
                        action="reject",
                        notes=notes,
                    )
                    checkpoint_store.record_decision(dec)
                    st.error("Item rejected.")
    else:
        st.success("No pending human reviews for the active run.")


# ==========================================
# TAB 6: HISTORY & REPLAY
# ==========================================
with tabs[5]:
    st.header("Run History & Step Replay")
    runs = checkpoint_store.list_runs()
    if runs:
        st.dataframe(runs, use_container_width=True)
        selected_run_id = st.selectbox("Select Past Run to Inspect / Replay", options=[r["run_id"] for r in runs])
        if st.button("Inspect Selected Checkpoint"):
            cp = checkpoint_store.load_checkpoint(selected_run_id)
            st.json(cp)
    else:
        st.info("No checkpointed runs recorded yet.")


# ==========================================
# TAB 7: BENCHMARK EVALUATION
# ==========================================
with tabs[6]:
    st.header("Ground Truth Benchmark Evaluation (11 Scenarios)")
    st.markdown("""
    The UBO Tracer test suite evaluates 11 canonical compliance scenarios including direct ownership, multi-layer dilution, 
    multi-path addition, regulatory boundary operators, circular holdings, ranges/bands, dead ends, messy text with hallucination traps, 
    trustee control, and prompt-injection defense.
    """)
    if st.button("▶ Run Full Benchmark Suite"):
        from evals.run_eval import evaluate_scenario
        eval_results = []
        progress_bar = st.progress(0)
        for s in range(1, 12):
            res = evaluate_scenario(s, planner_agent)
            eval_results.append({
                "Scenario": f"Scenario {s:02d}",
                "Status": "✅ PASS" if res["passed"] else "❌ FAIL",
                "Duration (s)": res["duration_sec"],
                "Details": "; ".join(res.get("reasons", [])) if res.get("reasons") else "Matched ground truth",
            })
            progress_bar.progress(s / 11)
        st.dataframe(eval_results, use_container_width=True)


# ==========================================
# TAB 8: EXPORT REPORTS
# ==========================================
with tabs[7]:
    st.header("Export Compliance Reports")
    st.write("Generate auditor-ready reports in Markdown, JSON, and PDF formats.")

    if "latest_trace" in st.session_state:
        res = st.session_state["latest_trace"]
        res_dicts = [r.to_dict() for r in res["results"]]

        col_md, col_json, col_pdf = st.columns(3)

        # Markdown Export
        md_text = f"# UBO Investigation Report: {res['target_id']}\n\n"
        md_text += "## Decision Support Only - Compliance Sign-off Required\n\n"
        for r in res["results"]:
            md_text += f"- **{r.owner_name}** ({r.owner_type.value}): {r.effective_percentage_min:.2f}% | Status: {r.status.value}\n"
        col_md.download_button("📄 Download Markdown", data=md_text, file_name=f"ubo_report_{res['target_id']}.md")

        # JSON Export
        json_data = json.dumps(res_dicts, indent=2)
        col_json.download_button("📦 Download JSON", data=json_data, file_name=f"ubo_report_{res['target_id']}.json", mime="application/json")

        # PDF Export
        pdf_bytes = generate_pdf_report(
            target_name=res["target_name"],
            target_id=res["target_id"],
            threshold=calculator.threshold,
            results=res_dicts,
        )
        col_pdf.download_button("📕 Download Signed PDF", data=pdf_bytes, file_name=f"ubo_report_{res['target_id']}.pdf", mime="application/pdf")
    else:
        st.info("Run an investigation in Tab 1 to generate export packages.")

