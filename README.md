# American Default Research MCP

Read-only research tools for U.S. household financial distress: economic
indicators, county scorecards, and the American Distress Index, with dates,
original publishers, and citations. The public service requires no account or
API key for normal use. It does not access private homeowner records or expose
the warehouse, arbitrary SQL, or financial transactions.

## Connect to the hosted service

Endpoint: **https://mcp.americandefault.org/mcp**

Transport: Streamable HTTP. Public documentation:
https://americandefault.org/press/mcp/

In Claude, open Customize, Connectors, and add a custom connector using that
URL. In ChatGPT, use the custom MCP connection in developer mode where your
account supports it. Directory publication is a separate platform review;
this README does not claim that either platform has approved the listing.

Anonymous access allows 10 calls per minute and 60 per hour per IP block.
Higher-volume users can request an issued key through the public documentation.
The static JSON endpoints are the suitable route for permitted bulk downloads.

## Domain discovery

The main domain advertises the connector at
`https://americandefault.org/.well-known/ai-catalog.json`. Its entry points to
`https://mcp.americandefault.org/mcp/server-card`, using the experimental
[MCP Server Card format](https://github.com/modelcontextprotocol/ext-server-card).
This format describes identity and connection details; tools remain discoverable
through the MCP protocol.

For clients using Cloudflare's earlier discovery convention, both domains serve
`/.well-known/mcp/server-card.json`. That compatibility card includes the exact
tool descriptions and input schemas returned by the running SDK. The main-domain
route proxies only this public metadata from the MCP host, without forwarding
cookies or authorization. Cards support CORS, HEAD and conditional ETag requests.
The registry metadata supplies the same name and version used at initialization.
Discovery metadata does not grant access or guarantee agent recommendations.

## Research examples

- Find indicators about mortgage delinquency, then retrieve the latest reading
  with its period and source.
- Retrieve King County, Washington's county distress scorecard using FIPS 53033.
- Retrieve the latest American Distress Index, its domains, and its historical
  reading. The index describes conditions and does not forecast outcomes.

## Tools

| Tool | Input | Result |
|---|---|---|
| `search_indicators` | `query`, optional `limit` (maximum 50) | Matching indicators and public page links |
| `get_indicator_v2` | `slug`, `response_version: "v2"` | Latest reading, sources, citations, freshness and comparison warnings |
| `get_indicator` | `slug` | Legacy v1 reading and citations |
| `get_county_scorecard` | County `fips` | Score, domains, findings, dates and citations |
| `get_adi_composite` | None | Latest published quarter, domains and historical context |
| `get_cross_correlations` | Indicator `slug` | Validated research relationships; empty results are normal |

Prefer v2 when comparing indicators. A series break or a suppressed trend means
readings may not be comparable. Observation frequency and release cadence can
differ: freshness uses the source's declared `freshness_cadence` when present.
Monthly dates retain their original first-of-month convention, while warning
age starts at the reporting month's end. Historical indicators are not presented
as current. Full histories, where available, are at
`https://americandefault.org/api/indicators/{slug}.json`.

## Local development

Use Python 3.12 or later and install `scripts/machine_layer/requirements-server.txt`
in an isolated environment. That file carries the deployed MCP SDK constraint.

```bash
PYTHONPATH=. python -m scripts.machine_layer.mcp_server --probe
PYTHONPATH=. python -m scripts.machine_layer.mcp_server
PYTHONPATH=. python -m scripts.machine_layer.mcp_server --transport http
```

The default transport is stdio. HTTP listens on `PORT` (default 8080).
Health endpoint: `/up`. Logs go to stderr. Local stdio clients must set the
repository as their working directory and `PYTHONPATH=.`.

Focused regressions:

```bash
PYTHONPATH=. python -m pytest scripts/tests/test_mcp_submission_readiness.py scripts/tests/test_fp42_mcp_cache_invalidation.py
```

Existing tool names and v1/v2 response schemas remain compatible. Additions use
an explicitly versioned contract. Every tool validates its inputs and outputs;
invalid slugs or county codes return errors rather than fabricated results.

## Attribution and privacy

Our analysis is free to use with attribution to American Default Research.
Source data stays under each publisher's terms; cite the source named here.
These research tools do not need conversation history, account credentials,
private documents, or personal financial details. Request bodies and bearer
credentials must not be logged. The site's privacy policy is
https://americandefault.org/privacy/.
