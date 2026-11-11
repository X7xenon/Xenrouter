# Xenrouter

Ultra-lightweight Unified Local Inference Router and Interactive Terminal User Interface (TUI).

Inspired by OmniRoute, Xenrouter aggregates multiple local and private inference backends (Ollama, LM Studio, llama.cpp / llama-server, vLLM, KoboldCPP, and Hermes Agent providers) into a unified, high-performance, OpenAI-compatible local API gateway.

---

## Key Features

- **Unified OpenAI-Compatible Wire**: Exposes standard `/v1/chat/completions`, `/v1/models`, `/v1/embeddings`, `/v1/health`, `/v1/metrics`, and `/v1/backends` endpoints. Any client, script, or coding agent (Cursor, Claude Code, Cline, Aider, Hermes) connects to one local endpoint.
- **Intelligent API Key Rotation & Cooldown**:
  - Distributes requests across key pools per backend using `round_robin`, `random`, or `failover` strategies.
  - Automatically isolates degraded keys upon receiving rate limits (HTTP 429) or authorization errors (HTTP 401/403), applying exponential backoff cooldown without dropping requests.
- **Native Hermes Provider Integration**:
  - Automatically detects and imports configured inference providers from local Hermes Agent installations (`~/.hermes` and `AppData/Local/hermes`).
  - Supports custom private inference nodes like `iteracompute`, `navy`, `inceptionlabs`, and `seekai`.
- **Zero-Config Port Probing**:
  - Scans standard local ports on startup (Ollama at `11434`, LM Studio at `1234`, llama.cpp at `8080`, vLLM at `8000`, KoboldCPP at `5001`).
- **Smart Cascades and Virtual Model Aliases**:
  - `coding`: Cascades to highest-tier local coding models (e.g. `qwen2.5-coder:32b`, `deepseek-coder`).
  - `fast`: Routes to low-latency completion models (`llama3.2:3b`, `qwen2.5:3b`).
  - `reasoning`: Routes to deep reasoning chain-of-thought models (`deepseek-r1:14b`).
  - `gpt-4o` / `claude-3-5-sonnet`: Compatibility aliases allowing existing coding agents to run without reconfiguring prompts.
- **Prefix Namespaced Routing**:
  - Target specific backends directly using `backend_name/model_name` (e.g. `ollama/qwen2.5:7b`, `hermes-navy/gpt-6-astra`).
- **Interactive Terminal User Interface (TUI)**:
  - Built with Rich Live. Displays real-time health tables, live request streams, TTFT (Time To First Token), token throughput (tok/sec), and active key rotations.
- **Zero-Latency SSE Streaming**:
  - Asynchronous event streaming with true pass-through chunk delivery and accurate token counting.

---

## Installation

Xenrouter is installed directly into your Python environment and added to PATH:

```powershell
pip install -e .
```

Verify installation:

```powershell
xenrouter --help
```

---

## CLI Reference

### 1. Start the Router
Launch with live interactive TUI dashboard:
```powershell
xenrouter start
```

Launch in headless daemon mode (ideal for background services or background tasks):
```powershell
xenrouter start --headless --port 8989
```

### 2. Inspect Hermes Providers
Inspect and probe all providers imported from Hermes Agent:
```powershell
xenrouter hermes
```

### 3. Scan Local Engines
Scan localhost for running inference engines:
```powershell
xenrouter probe
```

### 4. Query Status and Health
Inspect active backends, latency, models count, and key rotation states of a running instance:
```powershell
xenrouter status
```

### 5. Unified Model Catalog
List all unified models and virtual aliases across all active backends:
```powershell
xenrouter models
```

### 6. Test Model Inference
Benchmark inference and measure latency and tokens per second:
```powershell
xenrouter test --model "coding" --prompt "Explain binary search in one sentence."
```

### 7. Generate Default Configuration
Generate a starter `xenrouter.yaml` configuration file:
```powershell
xenrouter init
```

---

## Configuration (`xenrouter.yaml`)

```yaml
host: "127.0.0.1"
port: 8989
auto_probe_local: true
import_hermes_providers: true
health_check_interval: 15.0
default_model: "general"
max_history_logs: 200

backends:
  - name: "ollama"
    type: "ollama"
    base_url: "http://127.0.0.1:11434"
    enabled: true
    priority: 1
    max_concurrency: 4

  - name: "lmstudio"
    type: "lmstudio"
    base_url: "http://127.0.0.1:1234"
    enabled: true
    priority: 2
    max_concurrency: 2

  - name: "vllm-node"
    type: "vllm"
    base_url: "http://127.0.0.1:8000"
    enabled: true
    priority: 1
    max_concurrency: 8
    key_rotation_strategy: "round_robin"
    key_cooldown_seconds: 60.0
    api_keys:
      - "sk-local-vllm-alpha"
      - "sk-local-vllm-beta"
      - "sk-local-vllm-gamma"

aliases:
  coding:
    targets:
      - "qwen2.5-coder:32b"
      - "qwen2.5-coder:14b"
      - "codellama"
    description: "Primary coding cascade"

  fast:
    targets:
      - "llama3.2:3b"
      - "qwen2.5:3b"
    description: "Low-latency autocomplete"

  gpt-4o:
    targets:
      - "coding"
      - "general"
```

---

## Connecting External Coding Agents

Point any OpenAI-compatible tool to Xenrouter:

- **Base URL**: `http://127.0.0.1:8989/v1`
- **API Key**: Any dummy string (e.g. `sk-xenrouter`) unless server authentication is enforced.
- **Model**: `coding`, `fast`, `reasoning`, `gpt-4o`, or any model ID listed under `xenrouter models`.

### Hermes Agent Integration
In Hermes configuration (`~/.hermes/config.yaml`):
```yaml
model:
  provider: "custom"
  base_url: "http://127.0.0.1:8989/v1"
  default: "coding"
```

---

## Architecture

```
Clients (Cursor / Hermes / Cline / Aider / Scripts)
                     |
                     v
             [ Xenrouter API ] (http://127.0.0.1:8989/v1)
                     |
        +------------+------------+
        |                         |
  [ Router Engine ]       [ Key Rotator ]
  (Aliases/Prefix/LB)     (Cooldown / RoundRobin)
        |                         |
        +------------+------------+
                     |
  +------------------+------------------+
  |                  |                  |
  v                  v                  v
[ Ollama ]     [ LM Studio ]      [ Hermes Providers ]
:11434         :1234              (Iteracompute / Navy)
```

---

## License

MIT License. Designed and maintained by Abeer Kumar.
