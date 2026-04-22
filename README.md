# FFR API

Financial Fitness Report API — generates pillar summaries and spending insight cards powered by Google Gemini.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/ffr_summary` | Generate a pillar summary from structured financial data |
| `POST` | `/v1/ffr_insight` | Generate spending insight cards from derived features & ledger |

## Prerequisites

- Python 3.11+
- A Google Gemini API key (or Vertex AI project credentials)

## Setup

```bash
# 1. Clone and enter the repo
git clone <repo-url> && cd ffr-insights

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

## Configuration

The app reads `config.yaml` at the project root on startup for non-secret tunables (model name, temperatures, token budgets, prompt filenames, etc.). Secrets and overrides are supplied via environment variables.

### Required environment variables

| Variable | Purpose |
|----------|---------|
| `GEMINI_API_KEY` | Google Gemini API key |

### Optional environment variables

| Variable | Default (from `config.yaml`) | Purpose |
|----------|------------------------------|---------|
| `GEMINI_BASE_URL` | — | Custom Gemini endpoint URL |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Model to use for generation |
| `MAX_OUTPUT_TOKENS` | `16384` | Max output tokens for all Gemini calls |
| `GEMINI_VERTEX_PROJECT` | `aigateway` | Vertex AI project ID |
| `GEMINI_VERTEX_LOCATION` | `global` | Vertex AI location |
| `INSIGHT_SYSTEM_PROMPT_FILE` | `system/insight_system.txt` | Override the insight system prompt file (relative to prompts/) |
| `INSIGHT_MAX_WORKERS` | `8` | Thread pool size for parallel insight generation |
| `LLM_DEBUG` | `false` | Set to `1`/`true` to enable verbose LLM logging |
| `LOG_MAX_BODY_CHARS` | `500000` | Max characters logged per request/response body |

Create a `.env` file at the project root (it is loaded automatically via `python-dotenv`):

```bash
GEMINI_API_KEY=your-api-key-here
```

## Running the API

```bash
# Option A — via the entry-point script
python run.py

# Option B — via uvicorn directly
uvicorn app.main:app --reload --port 8000
```

The server starts on `http://localhost:8000`.

## API Contracts

The API contracts are auto-generated from the Pydantic models using the **OpenAPI 3.1** standard. You can view them in several ways:

### Interactive docs (server must be running)

| UI | URL |
|----|-----|
| Swagger UI | `http://localhost:8000/docs` |
| ReDoc | `http://localhost:8000/redoc` |
| Raw JSON spec | `http://localhost:8000/openapi.json` |

### Static spec files

Pre-generated OpenAPI spec files live in `API_Contract/`:

```
API_Contract/
├── openapi.json   # Machine-readable JSON spec
└── openapi.yaml   # Human-readable YAML spec
```

These files can be imported into any OpenAPI-compatible tool (Postman, Stoplight, Redocly, etc.) or used for client code generation.

### Regenerating the spec

After changing any Pydantic model or router, regenerate the static files:

```bash
python -m scripts.export_openapi
```

This writes both `openapi.json` and `openapi.yaml` into `API_Contract/`. Pass `--out-dir <path>` to write to a different location.

To rebuild the static HTML documentation from the spec:

```bash
npm install -g @redocly/cli
redocly build-docs API_Contract/openapi.json -o API_Contract/ffr-api-docs.html
```

## Project structure

```
app/
├── main.py              # FastAPI app factory, startup hook, exception handlers
├── config.py            # Config loading, defaults, env-var overrides
├── core/
│   ├── exceptions.py    # Custom exceptions (LLMValidationError)
│   ├── llm.py           # Gemini client, prompt loading, JSON parsing
│   ├── logging.py       # Structured logging wrappers
│   └── tracing.py       # OpenTelemetry setup, @traced decorator
├── models/
│   ├── common.py        # Shared constants & metadata models
│   ├── summary.py       # Summary data models (FfrScreenData, MonthValue, …)
│   └── api.py           # Request / response envelope models
├── routers/
│   ├── summary.py       # POST /v1/ffr_summary
│   └── insight.py       # POST /v1/ffr_insight
├── services/
│   ├── summary/
│   │   ├── pipeline.py  # Pillar summary generation loop
│   │   ├── response.py  # Response & error builders
│   │   └── audit.py     # Post-generation validation audit
│   └── insight/
│       ├── pipeline.py  # Insight card generation
│       └── response.py  # Response & error builders
├── validation/
│   └── post_llm.py      # Post-LLM output validation checks
└── persona/
    └── mece.py          # Persona narrative generation

config.yaml                # Non-secret tunables
spending_theme_config.yaml # Theme keys, prompts & data fields for insights
prompts/                   # Prompt template files (.txt)
run.py                     # Uvicorn entry point
scripts/
└── export_openapi.py      # Generate static OpenAPI spec files
API_Contract/
├── openapi.json           # Auto-generated OpenAPI 3.1 spec (JSON)
└── openapi.yaml           # Auto-generated OpenAPI 3.1 spec (YAML)
```

## Distributed Tracing (OpenTelemetry)

The API ships with built-in OpenTelemetry tracing. Every request generates a trace with spans covering the HTTP handler, LLM calls, pipeline steps, validation, and thread-pool fan-out — letting you visualise latency hops end-to-end.

### Configuration

Tracing is controlled via `config.yaml`:

| Key | Default | Description |
|-----|---------|-------------|
| `tracing_enabled` | `true` | Enable/disable tracing globally |
| `tracing_exporter` | `"otlp"` | `"otlp"` to send to a collector, `"console"` to print spans to stdout |
| `tracing_service_name` | `"ffr-api"` | Service name that appears in the tracing UI |
| `otlp_endpoint` | `http://localhost:4317` | gRPC endpoint of the OTLP collector |

You can also override the endpoint via the `OTEL_EXPORTER_OTLP_ENDPOINT` environment variable.

### Setting up Jaeger (local collector + UI)

[Jaeger](https://www.jaegertracing.io/) is the recommended local backend. It receives traces over OTLP gRPC and provides a web UI for exploring them.

**1. Start Jaeger via Docker (one command):**

```bash
docker run -d --name jaeger \
  -p 4317:4317 \
  -p 16686:16686 \
  jaegertracing/all-in-one:latest
```

This exposes:
- **Port 4317** — OTLP gRPC receiver (where the app sends traces)
- **Port 16686** — Jaeger web UI

**2. Verify the container is running:**

```bash
docker ps --filter name=jaeger
```

**3. Start (or restart) the API** so it connects to the collector:

```bash
uvicorn app.main:app --reload --port 8000
```

No code changes needed — the default `config.yaml` already points at `localhost:4317`.

### Viewing spans in Jaeger

1. Open **http://localhost:16686** in your browser.
2. Select **`ffr-api`** from the *Service* dropdown.
3. Click **Find Traces**.

Each trace represents a single API request. Clicking a trace opens a timeline (Gantt chart) showing every span and its duration. Key spans you will see:

| Span | Location | What it measures |
|------|----------|------------------|
| `generate_summary` | `summary` router | Full `/v1/ffr_summary` handler |
| `run_pillar_summary` | summary pipeline | Single pillar generation (incl. retries) |
| `call_llm` / `_call_gemini` | `core/llm.py` | Individual Gemini API call with model, token, and retry attributes |
| `generate_insights` | `insight` router | Full `/v1/ffr_insight` handler |
| `_generate_pillar_insights` | insight pipeline | Per-pillar parallel fan-out |
| `_generate_single_insight` | insight pipeline | Single theme insight generation |
| `_validate_insight_output` | insight pipeline | Post-LLM validation |
| `deduplicate_pillar_insights` | insight pipeline | Cross-insight deduplication |
| `screen_insight_compliance` | insight pipeline | Final compliance screening |

Spans include custom attributes such as `request_id`, `customer_id`, `llm.model`, `llm.temperature`, `retry.attempt`, and validation counts — visible in the span detail panel.

### Tips

- **Console mode** — Set `tracing_exporter: "console"` in `config.yaml` to print span JSON to stdout (useful when Docker isn't available).
- **Stopping Jaeger** — `docker stop jaeger && docker rm jaeger`
- **Persistent storage** — The default `all-in-one` image stores traces in memory. For persistence across restarts, mount a Badger volume:
  ```bash
  docker run -d --name jaeger \
    -p 4317:4317 -p 16686:16686 \
    -v jaeger-data:/badger \
    -e SPAN_STORAGE_TYPE=badger \
    -e BADGER_EPHEMERAL=false \
    -e BADGER_DIRECTORY_VALUE=/badger/data \
    -e BADGER_DIRECTORY_KEY=/badger/key \
    jaegertracing/all-in-one:latest
  ```

## Running tests

```bash
pytest
```
