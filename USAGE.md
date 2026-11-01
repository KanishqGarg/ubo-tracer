# UBO Tracer: User Guide & Running Instructions

This guide provides step-by-step instructions for installing, configuring, testing, and running the UBO Tracer prototype.

---

## 1. Prerequisites

1. **Python**: Python 3.10+ (tested on Python 3.11).
2. **Ollama**: Local Ollama server installed and running.
   - Install Ollama from [https://ollama.com](https://ollama.com).
   - In your terminal, pull the model:
     ```bash
     ollama pull qwen2.5:3b
     # Or for the larger model:
     ollama pull qwen2.5:7b-instruct
     ```
   - Start the server:
     ```bash
     ollama serve
     ```
   - Verify server is healthy:
     ```bash
     curl http://localhost:11434/api/tags
     ```

---

## 2. Environment Setup

Create and activate a virtual environment in `./venv`:

### Windows (PowerShell)
```powershell
# Create venv
python -m venv venv

# Activate venv
.\venv\Scripts\Activate.ps1

# Install pinned requirements
pip install -r ubo_tracer\requirements.txt
```

### Linux / macOS (Bash)
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r ubo_tracer/requirements.txt
```

---

## 3. Configuration & Optional API Keys

Configuration settings are stored in `ubo_tracer/config.yaml`:
- `threshold_percentage`: Default `25.0`.
- `comparison_operator`: `"gt"` (strictly $> 25\%$, UK PSC rule) or `"gte"` ($\ge 25\%$).
- `max_graph_depth`: Default `8`.
- `max_agent_steps`: Default `40`.

### Companies House API Key (Optional)
To query live UK corporate registers:
```powershell
$env:COMPANIES_HOUSE_API_KEY="your_api_key_here"
```
*Note: If no API key is set, the system gracefully skips the live Companies House API and operates offline using local mock data and text filings.*

---

## 4. Running a UBO Trace via CLI

Trace any corporate entity using the command line:

```powershell
# Trace synthetic Scenario 1 (Direct ownership)
$env:PYTHONPATH="ubo_tracer/src;ubo_tracer"
.\venv\Scripts\python -m ubo_tracer.cli trace target_corp_1

# Trace with custom threshold (e.g. 10%)
.\venv\Scripts\python -m ubo_tracer.cli trace target_corp_5 --threshold 10.0

# Trace with greater-than-or-equal operator
.\venv\Scripts\python -m ubo_tracer.cli trace target_corp_4 --operator gte
```

### Generated Reports
Every trace run outputs:
1. An interactive summary table directly in your terminal.
2. A human-readable Markdown audit report: `ubo_tracer/evals/results/ubo_report_<id>.md`.
3. A structured JSON compliance payload: `ubo_tracer/evals/results/ubo_report_<id>.json`.
4. A full JSONL audit trace: `ubo_tracer/logs/agent_traces.jsonl`.

---

### Running the Compliance Web Interface (Streamlit)

Launch the polished dark-mode compliance web application:

```powershell
$env:PYTHONPATH="ubo_tracer/src;ubo_tracer"
.\venv\Scripts\streamlit run ubo_tracer\src\ubo_tracer\ui\app.py
```

The portal provides:
- **Trace Investigation**: Live agent activity log, custom legal entity lookup, and scenario selection.
- **Ownership Graph**: Pyvis interactive network with color-coded classification nodes (ABOVE, BELOW, UNCERTAIN, DISPUTED, UNRESOLVED) and distinct dashed lines for control relationships.
- **Evidence & Audit**: Verbatim source quotes with highlighted key figures and verifier confirmation.
- **Deterministic Math**: Multi-path audit breakdowns showing every multiplication and summation formula.
- **Human Review Queue**: Persistent approval/rejection and owner-supply controls with resumption from SQLite checkpoints.
- **History & Step Replay**: Step-by-step trajectory replay of historical investigation sessions.
- **Benchmark Dashboard**: Automated evaluation of all 11 compliance scenarios.
- **Export Center**: Instant download of investigation findings as Markdown, JSON, and signed PDF packages.

---

## 5. Running the Test Suite

Run unit tests and verification checks:

```powershell
$env:PYTHONPATH="ubo_tracer/src;ubo_tracer"

# Run pure calculator tests (no LLM, exact arithmetic)
.\venv\Scripts\pytest ubo_tracer\tests\test_calculator.py -v

# Run deterministic quote and number verifier tests
.\venv\Scripts\pytest ubo_tracer\tests\test_verifier.py -v

# Run full synthetic scenario suite
.\venv\Scripts\pytest ubo_tracer\tests\test_scenarios.py -v
```

---

## 6. Running the Evaluation Benchmark

To run all 10 synthetic scenarios across multiple repetitions and generate the benchmark report:

```powershell
$env:PYTHONPATH="ubo_tracer/src;ubo_tracer"
.\venv\Scripts\python ubo_tracer\evals\run_eval.py
```
This produces the comprehensive evaluation matrix in `ubo_tracer/evals/EVAL_REPORT.md`.

---

## 7. Troubleshooting

| Issue | Cause | Resolution |
| :--- | :--- | :--- |
| `ConnectionError: Ollama is not running` | Ollama daemon is offline | Run `ollama serve` in a background terminal. |
| `RuntimeError: Model '...' not found` | Model has not been downloaded | Run `ollama pull qwen2.5:3b`. |
| `ModuleNotFoundError: No module named 'ubo_tracer'` | Python path not set | Set `$env:PYTHONPATH="ubo_tracer/src;ubo_tracer"` before running. |
| `Edge rejected: Quote not found verbatim` | LLM altered quote formatting | The Verifier automatically strips quotes and normalizes whitespace; check `ubo_tracer/logs/agent_traces.jsonl` for the verbatim diff. |

