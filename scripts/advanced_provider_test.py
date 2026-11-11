"""
Advanced Multi-Provider Inference Diagnostics for Xenrouter.
Dispatches a live chat completion request saying 'Hi' to all configured inference providers,
measuring latency, token counts, response validity, and failure modes.
"""

import asyncio
import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
import httpx
from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from xenrouter.backends.hermes_importer import discover_hermes_backends
from xenrouter.config import load_config
from xenrouter.types import BackendConfig

console = Console()


async def test_single_provider(
    client: httpx.AsyncClient,
    backend: BackendConfig,
    prompt: str = "Hi"
) -> Dict[str, Any]:
    """Dispatch a test chat completion saying 'Hi' to a single inference provider."""
    name = backend.name
    base_url = backend.base_url.rstrip("/")
    keys = backend.api_keys
    test_key = keys[0] if keys else None

    # Determine endpoint
    if base_url.endswith("/v1"):
        chat_url = f"{base_url}/chat/completions"
    else:
        chat_url = f"{base_url}/v1/chat/completions"

    # Determine candidate model
    model = None
    if backend.models_filter:
        model = backend.models_filter[0]

    # Specific default model fallbacks
    known_models = {
        "groq": "openai/gpt-oss-120b",
        "nvidia": "meta/llama-3.1-8b-instruct",
        "xkiro": "qwen/qwen3.8-max:free",
        "tokenharbor": "deepseek-v4.1-flash:free",
        "inceptionlabs": "mercury-2.5",
        "apinex": "free/deepseek-v4.1-flash",
        "dahl": "zai-org/GLM-5.3-Flash",
        "vyceai": "glm-5.3-flash",
        "router9": "deepseek/deepseek-v4-flash",
        "river": "deepseek-ai/DeepSeek-V4.1-Flash",
        "moonmath": "zro/deepseek-v4.1-flash",
        "top-tools": "Top-Tools-Ai",
        "orcarouter": "orcarouter/free",
        "iteracompute": "qwen/qwen3.8-27b",
        "navy": "hermes-3-llama-3.1-8b",
        "ollama-cloud": "llama3.2",
        "nous": "hermes-3-llama-3.1-8b",
        "free-ai": "qwen7b",
    }
    if not model or model == "auto":
        model = known_models.get(name) or (backend.models_filter[1] if backend.models_filter and len(backend.models_filter) > 1 else "default")

    headers = {"Content-Type": "application/json"}
    if test_key:
        headers["Authorization"] = f"Bearer {test_key}"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 20,
        "temperature": 0.3
    }

    result = {
        "provider": name,
        "base_url": base_url,
        "model": model,
        "has_key": bool(test_key),
        "status": "UNKNOWN",
        "status_code": 0,
        "latency_ms": 0.0,
        "reply": "",
        "tokens": 0,
        "error": None
    }

    start = time.perf_counter()
    try:
        resp = await client.post(chat_url, headers=headers, json=payload, timeout=20.0)
        dur = (time.perf_counter() - start) * 1000.0
        result["latency_ms"] = round(dur, 1)
        result["status_code"] = resp.status_code

        if resp.status_code == 200:
            data = resp.json()
            choices = data.get("choices", [])
            if choices and "message" in choices[0]:
                content = choices[0]["message"].get("content")
                if not content:
                    content = choices[0]["message"].get("reasoning_content") or choices[0]["message"].get("text") or ""
                reply_text = str(content).strip()
                result["reply"] = reply_text.replace("\n", " ")[:60]
                result["status"] = "SUCCESS"
                usage = data.get("usage", {})
                result["tokens"] = usage.get("completion_tokens", 0)
            else:
                result["status"] = "INVALID_RESPONSE"
                result["reply"] = str(data)[:60]
        elif resp.status_code == 429:
            result["status"] = "RATE_LIMITED"
            result["error"] = "HTTP 429 Rate Limit Exceeded"
        elif resp.status_code in (401, 403):
            result["status"] = "AUTH_FAILED"
            result["error"] = f"HTTP {resp.status_code} Unauthorized"
        elif resp.status_code == 404:
            result["status"] = "NOT_FOUND"
            result["error"] = f"Model '{model}' not found on endpoint"
        else:
            result["status"] = f"HTTP_{resp.status_code}"
            result["error"] = resp.text[:70].replace("\n", " ")
    except httpx.ConnectTimeout:
        dur = (time.perf_counter() - start) * 1000.0
        result["latency_ms"] = round(dur, 1)
        result["status"] = "TIMEOUT"
        result["error"] = "Connection Timeout (>20s)"
    except httpx.ReadTimeout:
        dur = (time.perf_counter() - start) * 1000.0
        result["latency_ms"] = round(dur, 1)
        result["status"] = "READ_TIMEOUT"
        result["error"] = "Read Timeout (>20s)"
    except Exception as exc:
        dur = (time.perf_counter() - start) * 1000.0
        result["latency_ms"] = round(dur, 1)
        result["status"] = "ERROR"
        result["error"] = f"{type(exc).__name__}: {str(exc)[:50]}"

    return result


async def run_advanced_testing(prompt: str = "Hi"):
    """Execute live chat completion test across all providers."""
    cfg = load_config()
    backends = discover_hermes_backends() if cfg.import_hermes_providers else []

    # Filter to providers that have an API key or base URL
    candidates = [b for b in backends if b.api_keys]

    console.print(f"[bold cyan]Starting Advanced Multi-Provider Test ({len(candidates)} providers with active keys)...[/bold cyan]")
    console.print(f"Test Prompt: [bold white]'{prompt}'[/bold white]\n")

    limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
    async with httpx.AsyncClient(timeout=25.0, verify=False, limits=limits) as client:
        # Run tests with bounded concurrency of 6
        semaphore = asyncio.Semaphore(6)

        async def bounded_test(b):
            async with semaphore:
                return await test_single_provider(client, b, prompt=prompt)

        tasks = [bounded_test(b) for b in candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    valid_results = [r for r in results if isinstance(r, dict)]

    table = Table(
        title="ADVANCED INFERENCE PROVIDER AUDIT (PROMPT: 'Hi')",
        box=box.ROUNDED,
        expand=True,
        header_style="bold cyan",
        border_style="dim cyan"
    )
    table.add_column("Provider", style="bold white", width=14)
    table.add_column("Status", justify="left", width=14)
    table.add_column("Latency", justify="right", width=9)
    table.add_column("Model Tested", style="yellow", width=26)
    table.add_column("Response / Error Output", style="white")

    success_count = 0
    for r in sorted(valid_results, key=lambda x: (0 if x["status"] == "SUCCESS" else 1, x["latency_ms"])):
        st = r["status"]
        if st == "SUCCESS":
            status_text = Text("* SUCCESS", style="bold green")
            output_text = Text(f"\"{r['reply']}\"", style="bright_white")
            success_count += 1
        elif st == "RATE_LIMITED":
            status_text = Text("! RATE_LIMIT", style="bold yellow")
            output_text = Text(r["error"] or "429", style="yellow")
        elif st in ("AUTH_FAILED", "NOT_FOUND"):
            status_text = Text(f"x {st}", style="dim red")
            output_text = Text(r["error"] or str(r["status_code"]), style="dim")
        else:
            status_text = Text(f"x {st}", style="dim red")
            output_text = Text(r["error"] or "-", style="dim red")

        ping_str = f"{r['latency_ms']:.0f}ms" if r["latency_ms"] > 0 else "-"
        table.add_row(
            r["provider"],
            status_text,
            ping_str,
            (r["model"] or "-")[:25],
            output_text
        )

    console.print(table)
    console.print(f"\n[bold green]Summary: {success_count}/{len(valid_results)} providers responded successfully (HTTP 200).[/bold green]")

    # Save detailed audit json
    audit_file = Path("advanced_inference_audit.json")
    audit_file.write_text(json.dumps(valid_results, indent=2), encoding="utf-8")
    console.print(f"Full audit report saved to: [cyan]{audit_file}[/cyan]")


if __name__ == "__main__":
    asyncio.run(run_advanced_testing("Hi"))
