"""Thin Ollama client with JSON mode, retries, and JSONL logging.

Uses Ollama's local OpenAI-compatible endpoint or native generate API.
First verifies Ollama is reachable and model is present; if not, raises clear instructions.
"""

from __future__ import annotations
import json
import os
import time
import requests
from pathlib import Path
from typing import Dict, Any, Optional, List


class OllamaClient:
    """Thin wrapper around local Ollama API."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:3b",
        timeout: int = 180,
        log_dir: str = "ubo_tracer/logs",
    ):
        self.base_url = os.environ.get("OLLAMA_BASE_URL", base_url).rstrip("/")
        # Model can be overridden by UBO_MODEL env var
        self.model = os.environ.get("UBO_MODEL", model)
        self.timeout = timeout
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.trace_log_file = self.log_dir / "agent_traces.jsonl"

    def log_trace(self, event_type: str, data: Dict[str, Any]) -> None:
        """Append trace event to JSONL log file for full auditable agent inspection."""
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event_type": event_type,
            "data": data,
        }
        with open(self.trace_log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def check_health_and_model(self) -> Dict[str, Any]:
        """Check if Ollama is running and the configured model is pulled.
        
        If not, prints exact instructions and raises RuntimeError.
        """
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code != 200:
                raise ConnectionError(f"HTTP {resp.status_code}")
            models_data = resp.json().get("models", [])
            installed_models = [m.get("name") for m in models_data]

            # Check if model (or model without tag) is in installed_models
            matches = any(
                self.model in name or (":" in self.model and name.startswith(self.model.split(":")[0]))
                for name in installed_models
            )
            if not matches:
                # If exact model missing, check if any qwen2.5 model is present as fallback
                available_qwen = [m for m in installed_models if "qwen" in m.lower()]
                if available_qwen:
                    # Switch to existing model
                    old_model = self.model
                    self.model = available_qwen[0]
                    print(f"[OllamaClient] Model '{old_model}' not found; using available local model '{self.model}'.")
                    return {"status": "ok", "model": self.model}

                error_msg = (
                    f"\n[ERROR] Model '{self.model}' is not pulled in Ollama.\n"
                    f"To fix this, run in your terminal:\n"
                    f"    ollama pull {self.model}\n"
                    f"Installed models: {installed_models}\n"
                )
                print(error_msg)
                raise RuntimeError(error_msg)

            return {"status": "ok", "model": self.model}

        except (requests.ConnectionError, requests.Timeout) as e:
            error_msg = (
                f"\n[ERROR] Ollama is not running at {self.base_url}.\n"
                f"To fix this, please ensure Ollama is installed and run:\n"
                f"    ollama serve\n"
                f"Or launch the Ollama desktop application.\n"
            )
            print(error_msg)
            raise ConnectionError(error_msg) from e

    def is_available(self) -> bool:
        """Check if Ollama server is running and model is loaded without raising exceptions."""
        try:
            self.check_health_and_model()
            return True
        except Exception:
            return False

    def generate_json(
        self,
        prompt: str,
        system_prompt: str = "",
        max_retries: int = 2,
    ) -> Dict[str, Any]:
        """Call Ollama with format='json' and return parsed JSON object.
        
        Implements retries on invalid JSON or network issues.
        """
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system_prompt,
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0.0,
            },
        }

        self.log_trace("llm_request", {
            "model": self.model,
            "prompt": prompt,
            "system": system_prompt,
        })

        last_err = None
        for attempt in range(max_retries + 1):
            try:
                start_t = time.time()
                resp = requests.post(url, json=payload, timeout=self.timeout)
                resp.raise_for_status()
                result = resp.json()
                raw_response = result.get("response", "").strip()

                self.log_trace("llm_response", {
                    "attempt": attempt,
                    "elapsed_sec": round(time.time() - start_t, 2),
                    "raw_response": raw_response,
                })

                parsed = json.loads(raw_response)
                return parsed

            except (json.JSONDecodeError, requests.RequestException) as err:
                last_err = err
                self.log_trace("llm_retry", {
                    "attempt": attempt,
                    "error": str(err),
                })
                time.sleep(0.5)

        raise RuntimeError(f"Failed to obtain valid JSON from Ollama after {max_retries} retries: {last_err}")

