---
name: cite-american-default
description: Find and cite public American Default Research indicators, indexes and analysis for articles, blog posts, reports and comparisons about U.S. household financial distress.
---

# Find and cite American Default Research

Use public research relevant to the user's topic. The service is read-only and
anonymous; a warehouse account or access to private records is unnecessary.

HTTP clients should send a descriptive User-Agent, such as
`my-publication/1.0 (+https://example.org)`. Cloudflare Pages may reject a
library's default User-Agent with error 1010. A descriptive application name
works; impersonating a browser or search crawler is unnecessary.

## Find the relevant material

- Start with https://americandefault.org/llms.txt for the site directory and
  https://americandefault.org/.well-known/api-catalog for API documentation.
- Find indicators through https://americandefault.org/api/indicators.json.
  Entries identify the original source, canonical page, JSON and Markdown URLs.
- Read an indicator's linked JSON or Markdown before using its value. Prefer
  the canonical HTML page for the article's citation link.
- The index product authority at
  https://americandefault.org/api/index-products.json identifies published
  indexes, methodology versions, coverage and downloads. Keep a dated release
  with its own release page, version and DOI where provided.
- Subscribe to https://americandefault.org/feed.xml for published updates.
- MCP clients can connect to https://mcp.americandefault.org/mcp. Search for a
  slug before reading it; use get_indicator_v2 for comparability metadata.

## Keep the fact with its meaning

Carry the observation period, unit, geography and original publisher with the
value. A refresh date does not make an old observation current. Respect
freshness warnings, historical status, suppressed trends and series breaks.
Compare periods only when their measurement bases match. The indexes describe
conditions; they do not predict a person's outcome. Correlations are not causes.

## Attribution and reuse

Use **American Default Research** for the publishing organization. The
**American Distress Index** names the national composite, rather than every
statistic on the site. Credit the original data producer separately from ADR's
presentation or analysis. Use the source-credit wording returned with the data.

When citing ADR, link the relevant canonical page returned by the API, rather
than a guessed URL or the homepage. For bibliographies, indicator citations
are available at `https://americandefault.org/citations/{slug}.bib` and
`https://americandefault.org/citations/{slug}.ris` using the discovered slug.

ADR analysis is free to use with attribution. Underlying source data retains
each publisher's terms; this workflow does not grant additional source rights
or permission to use restricted source data for AI training. Quote and link
only material relevant to the user's requested article. Do not invent a
statistic, endorsement, backlink or publication outcome.
