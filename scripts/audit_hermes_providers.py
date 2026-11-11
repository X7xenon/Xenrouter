"""
Audit all Hermes providers from .env and auth.json.
Pings each provider, retrieves all models, tests balance/quota endpoints,
and collects comprehensive metadata.
"""

import asyncio
import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
import httpx


def get_all_hermes_credentials() -> List[Dict[str, Any]]:
    env_file = Path("C:/Users/kumar/AppData/Local/hermes/.env")
    auth_file = Path("C:/Users/kumar/AppData/Local/hermes/auth.json")

    providers: Dict[str, Dict[str, Any]] = {}

    if env_file.exists():
        content = env_file.read_text(encoding="utf-8", errors="ignore")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if not v:
                continue

            if k.startswith("HERMES_CUSTOM_") and k.endswith("_API_KEY"):
                raw = k[len("HERMES_CUSTOM_"):-len("_API_KEY")].lower()
                # Special cases
                if "top_tools_ai_com" in raw:
                    base_url = "https://top-tools-ai.com/api/v1"
                elif "groq_com" in raw:
                    base_url = "https://api.groq.com/openai/v1"
                elif "hcnsec_cn" in raw:
                    base_url = "https://api.hcnsec.cn/v1"
                elif "dahl_global" in raw:
                    base_url = "https://inference.dahl.global/v1"
                else:
                    host = raw.replace("_", ".")
                    base_url = f"https://{host}/v1"

                # Check if value itself is a URL (e.g. HCNSEC)
                key_val = v
                if v.startswith("http"):
                    base_url = v
                    key_val = "none"

                providers[raw] = {
                    "name": raw,
                    "base_url": base_url,
                    "keys": [key_val] if key_val != "none" else [],
                    "source": ".env"
                }

            elif k in ["NAVY_API_KEY", "NAVYAI_API_KEY"]:
                if "api_navy" in providers:
                    if v not in providers["api_navy"]["keys"]:
                        providers["api_navy"]["keys"].append(v)
                else:
                    providers["api_navy"] = {
                        "name": "api_navy",
                        "base_url": "https://api.navy/v1",
                        "keys": [v],
                        "source": ".env"
                    }

            elif k == "OPENCODE_ZEN_API_KEY":
                providers["opencode_zen"] = {
                    "name": "opencode_zen",
                    "base_url": "https://opencode.ai/inference/openai/v1",
                    "keys": [v],
                    "source": ".env"
                }

            elif k == "OLLAMA_API_KEY":
                providers["ollama_cloud"] = {
                    "name": "ollama_cloud",
                    "base_url": "https://ollama.com/v1",
                    "keys": [v],
                    "source": ".env"
                }

    # Also check auth.json
    if auth_file.exists():
        try:
            auth_data = json.loads(auth_file.read_text(encoding="utf-8"))
            pool = auth_data.get("credential_pool", {})

            for provider_key, creds in pool.items():
                if not creds:
                    continue
                clean_name = provider_key.replace("custom:", "").replace(".", "_")
                for c in creds:
                    token = c.get("access_token")
                    base = c.get("base_url") or c.get("inference_base_url")
                    if token and base:
                        if clean_name not in providers:
                            providers[clean_name] = {
                                "name": clean_name,
                                "base_url": base.rstrip("/"),
                                "keys": [token],
                                "source": "auth.json"
                            }
                        else:
                            if token not in providers[clean_name]["keys"]:
                                providers[clean_name]["keys"].append(token)
        except Exception:
            pass

    return list(providers.values())


async def audit_provider(client: httpx.AsyncClient, p: Dict[str, Any]) -> Dict[str, Any]:
    name = p["name"]
    base_url = p["base_url"].rstrip("/")
    keys = p.get("keys", [])
    test_key = keys[0] if keys else None

    result = {
        "name": name,
        "base_url": base_url,
        "keys_count": len(keys),
        "status": "UNKNOWN",
        "status_code": 0,
        "latency_ms": 0.0,
        "models_count": 0,
        "models": [],
        "quota_info": "Unknown",
        "error": None
    }

    headers = {"Content-Type": "application/json", "User-Agent": "Xenrouter/0.1.0"}
    if test_key:
        headers["Authorization"] = f"Bearer {test_key}"

    start_time = time.perf_counter()
    try:
        # 1. Fetch models
        models_url = f"{base_url}/models"
        resp = await client.get(models_url, headers=headers, timeout=12.0)
        dur = (time.perf_counter() - start_time) * 1000.0
        result["latency_ms"] = round(dur, 1)
        result["status_code"] = resp.status_code

        if resp.status_code == 200:
            result["status"] = "ONLINE"
            try:
                data = resp.json()
                models_data = data.get("data", [])
                result["models"] = [m.get("id") for m in models_data if m.get("id")]
                result["models_count"] = len(result["models"])
            except Exception:
                result["status"] = "INVALID_JSON"
        elif resp.status_code in [401, 403]:
            result["status"] = "AUTH_FAILED"
            result["error"] = f"HTTP {resp.status_code}: {resp.text[:80]}"
        elif resp.status_code == 429:
            result["status"] = "RATE_LIMITED"
            result["error"] = "HTTP 429: Quota exhausted or rate limited"
        else:
            result["status"] = f"HTTP_{resp.status_code}"
            result["error"] = resp.text[:100]

        # 2. Check quota / balance endpoints
        quota_endpoints = [
            f"{base_url}/dashboard/billing/credit_grants",
            f"{base_url}/user/balance",
            f"{base_url}/user/quota",
            f"{base_url}/billing/usage"
        ]
        for q_url in quota_endpoints:
            try:
                q_resp = await client.get(q_url, headers=headers, timeout=3.0)
                if q_resp.status_code == 200:
                    q_data = q_resp.json()
                    result["quota_info"] = json.dumps(q_data)[:120]
                    break
            except Exception:
                pass

        # Inspect headers for remaining quota
        for h, v in resp.headers.items():
            h_low = h.lower()
            if "ratelimit-remaining" in h_low or "credit-remaining" in h_low or "balance" in h_low:
                result["quota_info"] = f"{h}: {v}"

    except httpx.ConnectTimeout:
        result["status"] = "TIMEOUT"
        result["error"] = "Connection timed out (12s)"
    except httpx.ConnectError as ce:
        result["status"] = "UNREACHABLE"
        result["error"] = f"ConnectError: {ce}"
    except Exception as exc:
        result["status"] = "ERROR"
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


async def main():
    providers = get_all_hermes_credentials()
    print(f"Auditing {len(providers)} Hermes providers...")

    async with httpx.AsyncClient(verify=False) as client:
        tasks = [audit_provider(client, p) for p in providers]
        results = await asyncio.gather(*tasks)

    # Save detailed audit JSON
    out_path = Path("hermes_providers_audit.json")
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Audit results written to {out_path}")

    # Summary
    online = [r for r in results if r["status"] == "ONLINE"]
    print(f"\nAudit complete: {len(online)}/{len(results)} providers ONLINE")
    for r in sorted(results, key=lambda x: (x["status"] != "ONLINE", x["name"])):
        status_tag = f"[{r['status']}]"
        print(f"{r['name']:<28} | {status_tag:<14} | {r['latency_ms']:>6.1f}ms | Models: {r['models_count']:<4} | Base: {r['base_url']}")


if __name__ == "__main__":
    asyncio.run(main())
