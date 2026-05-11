# American Default Research — MCP Server

A Model Context Protocol server that exposes American Default Research data — 96 economic distress indicators, the American Distress Index (ADI) composite score, and county-level distress scores across all 3,144 U.S. counties — to MCP-compatible AI agents.

**Official MCP Registry namespace:** `org.americandefault/research`
**Hosted endpoint:** `https://mcp.americandefault.org/mcp` (streamable HTTP)
**Website:** [https://americandefault.org/press/mcp/](https://americandefault.org/press/mcp/)

---

## Use the hosted MCP (recommended)

Point any MCP-compatible client at the hosted streamable-HTTP endpoint. No install, no data files, no maintenance — every response is generated against the same data that powers [americandefault.org](https://americandefault.org).

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "american-default-research": {
      "url": "https://mcp.americandefault.org/mcp",
      "transport": "streamable-http"
    }
  }
}
```

Restart Claude Desktop. The 5 tools appear under the hammer icon.

### Smithery

The MCP is also available via the Smithery gateway at [smithery.ai/servers/americandefault/research](https://smithery.ai/servers/americandefault/research).

### Cursor / other MCP clients

Any client that speaks streamable HTTP can connect by adding the endpoint URL to its MCP server config. The exact config format varies by client — see your client's docs.

---

## Tool surface

| Tool | Input | Returns |
|---|---|---|
| `get_indicator(slug)` | bundle slug (e.g. `the-buffer`) | compact snapshot + pre-computed aggregates + canonical citation |
| `get_county_scorecard(fips)` | 5-digit FIPS (4-digit accepted with implicit leading zero) | CDI scorecard + 5-domain breakdown + pre-baked citations |
| `get_adi_composite()` | (none) | latest quarter ADI + 5 components + zone + citation |
| `search_indicators(query, limit=10)` | keyword + optional limit (max 50) | ranked matches (slug, branded_name, name, category, URL) |
| `get_cross_correlations(slug)` | indicator slug | fully-validated leading/lagging pairs split into `as_leader` + `as_follower` |

### Schema versioning

Every response carries `schema_version: "v1"`. Breaking changes ship as a new tool with a `_v2` suffix — v1 tools stay live for backward compatibility. Callers should assert the schema version they expect.

### Response size budgets

| Endpoint | Budget | Typical |
|---|---|---|
| `get_indicator` | ≤ 16 KB | ~13.8 KB |
| `get_county_scorecard` | ≤ 25 KB | ~2.5 KB |
| `get_adi_composite` | ≤ 4 KB | ~2.0 KB |

Raw 300+ point indicator series is intentionally omitted from `get_indicator` to keep LLM context budgets manageable. The full series lives at `https://americandefault.org/api/indicators/{slug}.json`.

---

## Canonical attribution

Every response includes a `citation` object with APA, MLA, Chicago, and news-copy forms. Three-tier naming is enforced:

- **American Default Research** — institutional name, used in citations, source lists, bibliographies
- **American Default** — brand name, used for URLs and casual references
- **American Distress Index (ADI)** — product name, used only when the composite score is the subject

See [`https://americandefault.org/llms.txt`](https://americandefault.org/llms.txt) § "Canonical Attribution" for the authoritative spec.

---

## Run locally (optional)

The recommended way to use this MCP is the hosted endpoint above. The local install path is provided for transparency, audit, and self-hosting — but the local server reads data files from sibling directories (`data/` and `site/src/data/`) that aren't included in this repo. To run locally end-to-end you need either:

1. **Mirror the data files from the public API.** All indicator data is published at `https://americandefault.org/api/indicators/{slug}.json` and county scorecards at `https://americandefault.org/api/counties/{fips}.json`. A small companion script (not bundled) can fetch these into a local `data/` mirror.
2. **Use this repo as a code reference only.** Read the source, audit the implementation, then point your client at the hosted endpoint.

Install:

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

Probe (confirms the server boots and discovers tools):

```bash
PYTHONPATH=. python3 -m scripts.machine_layer.mcp_server --probe
```

This emits a JSON handshake to stdout and exits 0 without entering the stdio loop. Use it in CI or as a smoke test.

Run the stdio loop:

```bash
PYTHONPATH=. python3 -m scripts.machine_layer.mcp_server
```

Stdout is reserved for JSON-RPC framing. Logs go to stderr.

---

## Architecture

The server is built on `mcp >= 1.27.0` and supports two transports:

- **stdio** (`mcp_server.py`) — for local Claude Desktop / Cursor / IDE plugins
- **streamable-HTTP** (`http_app.py`) — for the hosted endpoint at `mcp.americandefault.org`

The HTTP transport adds a bearer-auth middleware (anonymous + issued tiers), two-level token-bucket rate limiting (per-minute burst + per-hour sustained), and per-tier rate limits. See `http_app.py` for the full middleware stack.

### Slug ↔ indicator_id mapping

Source JSONs carry both `indicator_id` (snake_case) and `slug` (kebab-case). 91 of 96 indicators have slugs that DO NOT mechanically transform from their id — branded indicators use marketing names like `the-buffer` (id: `savings_rate`), `the-horizon` (id: `ai_capability`), `the-pinch` (id: `census_htops_difficulty`).

The server builds a boot-time bidirectional map by scanning every source JSON once (~100ms). Lookups are O(1) thereafter.

### Empty-data bundles

10 of 96 bundles ship without populated data — indicators tracked but not yet backfilled (AI job postings, ABA consumer discretionary, NMHC rent tracker, utility disconnections, etc.). These return `status: "awaiting_population"` with full metadata and a null `latest_value`. Agents can discover the slug exists without receiving phantom data.

### Rate limiting (HTTP transport)

Two-level token bucket keyed by IP and bearer-token contact:

- **Per-minute burst** — `MCP_RATE_LIMIT_RPM`, default `60`
- **Per-hour sustained** — `MCP_RATE_LIMIT_RPH`, default `600`

Anonymous tier (no bearer) gets the default. Issued tier (valid bearer) gets a higher allowance configured server-side.

---

## Data sources

This MCP serves data sourced from FRED (Federal Reserve Economic Data), BLS (Bureau of Labor Statistics), NY Fed Household Debt and Credit Report, ATTOM Data Solutions, Mortgage Bankers Association, American Bankruptcy Institute / Epiq Systems, and additional primary government and industry sources. Data is updated daily via automated pipelines.

Per-indicator source attribution is included in every `citation` field returned by the server. The full source-attribution methodology is at [https://americandefault.org/methodology/](https://americandefault.org/methodology/).

---

## About American Default Research

American Default Research is a nonpartisan data project tracking U.S. household financial distress. It publishes the American Distress Index (ADI) — a composite 0-100 score built from five statistically derived components — and the County Distress Index (CDI) for all 3,144 U.S. counties.

Website: [https://americandefault.org](https://americandefault.org)
Press: [https://americandefault.org/press/mcp/](https://americandefault.org/press/mcp/)
Methodology: [https://americandefault.org/methodology/](https://americandefault.org/methodology/)

---

## License

MIT — see `LICENSE`.

Data is free to use with attribution per the canonical attribution block at `https://americandefault.org/llms.txt`.

---

## Issues and contributions

Bug reports and feature requests welcome via GitHub Issues on this repo. Pull requests are reviewed against the data pipeline's correctness gates — see [`https://americandefault.org/llms.txt`](https://americandefault.org/llms.txt) for the data-accuracy standard.
