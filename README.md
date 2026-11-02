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
readings may not be comparable. Historical indicators are not presented
as current. Full histories, where available, are at
`https://americandefault.org/api/indicators/{slug}.json`.

## Source and installation

This public repository is a source reference for the hosted connector. The
production service also uses shared formatting, index metadata and public data
files maintained separately. Cloning this repository alone does not provide a
complete local data installation. Connect to the hosted endpoint above for
normal use; no local process, API key or data download is needed.

For Cline and Cursor, add this to the client's MCP server configuration:

```json
{
  "mcpServers": {
    "american-default-research": {
      "url": "https://mcp.americandefault.org/mcp"
    }
  }
}
```

All six tools are read-only. Invalid slugs or county codes return errors rather
than fabricated results. The hosted HTTP health endpoint is `/up`.

## Attribution and privacy

Our analysis is free to use with attribution to American Default Research.
Source data stays under each publisher's terms; cite the source named here.
These research tools do not need conversation history, account credentials,
private documents, or personal financial details. Request bodies and bearer
credentials must not be logged. The site's privacy policy is
https://americandefault.org/privacy/.
