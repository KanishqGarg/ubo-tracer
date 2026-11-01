"""Command-line interface for UBO Tracer."""

import argparse
import sys
import yaml
from pathlib import Path
from rich.console import Console
from rich.table import Table

from ubo_tracer.models import UBOStatus
from ubo_tracer.llm import OllamaClient
from ubo_tracer.calculator import OwnershipCalculator
from ubo_tracer.sources.mock_source import MockSource
from ubo_tracer.sources.companies_house import CompaniesHouseSource
from ubo_tracer.sources.gleif import GLEIFSource
from ubo_tracer.sources.filing_text import FilingTextSource
from ubo_tracer.agents.retrieval import RetrievalAgent
from ubo_tracer.agents.extraction import ExtractionAgent
from ubo_tracer.agents.planner import PlannerAgent
from ubo_tracer.report import ReportGenerator

console = Console()


def load_config(config_path: str = "config.yaml"):
    path = Path(config_path)
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def trace_cli(args):
    config = load_config(args.config)

    # Initialize LLM Client
    model_name = args.model or config.get("llm", {}).get("model", "qwen2.5:3b")
    llm_client = OllamaClient(
        base_url=config.get("llm", {}).get("base_url", "http://localhost:11434"),
        model=model_name,
        log_dir=args.log_dir or "ubo_tracer/logs",
    )

    console.print(f"[bold blue]Checking Ollama status & model ({model_name})...[/bold blue]")
    try:
        status_info = llm_client.check_health_and_model()
        console.print(f"[green]Ollama connected! Model ready: {status_info.get('model')}[/green]")
    except Exception as e:
        console.print(f"[bold red]{e}[/bold red]")
        sys.exit(1)

    # Setup calculator
    calc_cfg = config.get("calculation", {})
    calc = OwnershipCalculator(
        threshold_percentage=args.threshold or calc_cfg.get("threshold_percentage", 25.0),
        comparison_operator=args.operator or calc_cfg.get("comparison_operator", "gt"),
        max_depth=config.get("limits", {}).get("max_graph_depth", 8),
        listed_company_identifiers=config.get("listed_companies"),
    )

    # Setup sources
    mock_source = MockSource(synthetic_dir=args.mock_dir or config.get("sources", {}).get("mock_data_dir", "ubo_tracer/data/synthetic"))
    ch_source = CompaniesHouseSource()
    gleif_source = GLEIFSource()
    filing_source = FilingTextSource(filing_dir=config.get("sources", {}).get("filing_text_dir", "data/filings"))

    sources_map = {
        "mock": mock_source,
        "companies_house": ch_source,
        "gleif": gleif_source,
        "filing_text": filing_source,
    }

    retrieval_agent = RetrievalAgent(
        sources=sources_map,
        llm_client=llm_client,
        default_order=config.get("sources", {}).get("order"),
    )
    extraction_agent = ExtractionAgent(llm_client=llm_client)

    planner = PlannerAgent(
        retrieval_agent=retrieval_agent,
        extraction_agent=extraction_agent,
        calculator=calc,
        llm_client=llm_client,
        max_depth=config.get("limits", {}).get("max_graph_depth", 8),
        max_steps=config.get("limits", {}).get("max_agent_steps", 40),
        max_retries=config.get("limits", {}).get("max_retries_per_entity", 2),
    )

    console.print(f"\n[bold green]Starting UBO Trace for Target Entity: '{args.entity_id}'...[/bold green]")
    trace_result = planner.trace_entity(args.entity_id, target_name=args.name)

    results = trace_result["results"]

    # Display Rich Table in Terminal
    table = Table(title=f"UBO Tracer Results for {args.entity_id}")
    table.add_column("Owner", style="cyan", no_wrap=True)
    table.add_column("Type", style="magenta")
    table.add_column("Effective Ownership", justify="right")
    table.add_column("Status", justify="center")
    table.add_column("Human Review", justify="center")

    for r in results:
        pct_str = (
            f"{r.effective_percentage_min:.2f}%"
            if r.effective_percentage_min == r.effective_percentage_max
            else f"[{r.effective_percentage_min:.2f}%, {r.effective_percentage_max:.2f}%]"
        )
        status_color = "bold green" if r.status == UBOStatus.ABOVE else ("yellow" if r.status == UBOStatus.UNCERTAIN else "white")
        review_str = "[bold red]FLAGGED[/bold red]" if r.requires_human_review else "[green]OK[/green]"
        table.add_row(r.owner_name, r.owner_type.value, pct_str, f"[{status_color}]{r.status.value}[/{status_color}]", review_str)

    console.print(table)

    # Output Reports
    md_content = ReportGenerator.generate_markdown_report(trace_result)
    json_content = ReportGenerator.generate_json_report(trace_result)

    out_dir = Path(args.output_dir or "ubo_tracer/evals/results")
    out_dir.mkdir(parents=True, exist_ok=True)

    md_path = out_dir / f"ubo_report_{args.entity_id}.md"
    json_path = out_dir / f"ubo_report_{args.entity_id}.json"

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(json_content)

    console.print(f"\n[bold green]Report saved to:[/bold green] {md_path} and {json_path}\n")


def main():
    parser = argparse.ArgumentParser(prog="ubo_tracer", description="Deterministic & Agentic UBO Tracer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    trace_parser = subparsers.add_parser("trace", help="Trace UBO for a specific entity ID")
    trace_parser.add_argument("entity_id", help="Company ID, Number, or LEI to trace")
    trace_parser.add_argument("--name", help="Human-readable legal name of entity")
    trace_parser.add_argument("--config", default="ubo_tracer/config.yaml", help="Path to config.yaml")
    trace_parser.add_argument("--model", help="Ollama model name (overrides config)")
    trace_parser.add_argument("--threshold", type=float, help="Ownership threshold %")
    trace_parser.add_argument("--operator", choices=["gt", "gte"], help="Comparison operator")
    trace_parser.add_argument("--mock-dir", help="Path to synthetic benchmark data directory")
    trace_parser.add_argument("--output-dir", help="Directory to save generated reports")
    trace_parser.add_argument("--log-dir", help="Directory to save agent trace logs")

    args = parser.parse_args()
    if args.command == "trace":
        trace_cli(args)


if __name__ == "__main__":
    main()

