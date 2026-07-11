---
name: seo-semrush
description: Semrush API analyst (extension). Live keyword research, domain organic/paid analysis, backlink profiles, competitor and keyword-gap analysis, and traffic estimates via the official Semrush MCP server. Use when user says "semrush", "keyword volume", "keyword difficulty", "organic keywords", "competitor keywords", "keyword gap", "referring domains", "backlink data", "domain authority", "traffic estimate", or "competitive analysis".
user-invocable: true
argument-hint: "[command] [domain|keyword]"
license: MIT
compatibility: "Requires the official Semrush MCP server connected to this session (remote: https://mcp.semrush.com/v1/mcp). Pairs with seo-backlinks for multi-source confidence weighting."
metadata:
  author: AgriciDaniel
  version: "2.2.0"
  category: seo
---

# seo-semrush

Live Semrush data via the official Semrush MCP server. Replaces the Ahrefs
extension as this project's premium keyword + backlink + competitive
intelligence source.

## Prerequisites

- The Semrush MCP server must be connected to this Claude Code session
  (remote endpoint `https://mcp.semrush.com/v1/mcp`, authenticated with a
  Semrush API unit balance). See `extensions/semrush/docs/SEMRUSH-SETUP.md`.

**Before calling any Semrush tool, verify the MCP is connected** by checking
that the Semrush discovery tools are available in this session. Semrush MCP
tool names are suffixed `*_research` (e.g. `keyword_research`,
`backlink_research`, `organic_research`, `overview_research`) plus
`get_report_schema` and `execute_report`. If those tools are not available,
tell the user the Semrush MCP is not connected and point them to the setup doc.

## How the Semrush MCP works (3-step workflow)

The Semrush MCP is report-based. Every data pull follows the same loop:

1. **Discovery** — call the relevant `*_research` tool (no args) to list the
   reports it exposes (e.g. `keyword_research` → `phrase_this`, `phrase_related`,
   `phrase_questions`, `phrase_fullsearch`...).
2. **Schema** — call `get_report_schema(report=<name>)` to learn that report's
   required/optional parameters.
3. **Execute** — call `execute_report(report=<name>, params={...})` with the
   parameters from the schema.

Never guess report parameters — always `get_report_schema` first when unsure.

## Database (market) selection — IMPORTANT

Semrush reports are scoped to a regional **database**. Pick the database that
matches the client's target market, not the US default:

- Detect market from the client's GSC `default_property` country, TLD, or stated
  audience. For example, a Singapore-market client uses `database: "sg"`.
- Common codes: `us`, `uk`, `ca`, `au`, `sg`, `in`, `de`, `fr`, `es`, `it`,
  `nl`, `jp`. If unsure, ask or default to `us` and label the report with the
  database used.
- State the database in every report ("Semrush, sg database, live").

## Routing

| Command | Action | Primary Semrush tool(s) |
|---|---|---|
| `/seo semrush overview <domain>` | Authority score, traffic estimate, keyword/backlink counts, trend | `overview_research` |
| `/seo semrush organic <domain>` | Top organic keywords, positions, traffic share, SERP features | `organic_research` |
| `/seo semrush keywords <keyword>` | Volume, difficulty, CPC, intent, related keywords, questions | `keyword_research` |
| `/seo semrush competitors <domain>` | Organic competitors and overlap | `organic_research` (competitors report) |
| `/seo semrush gap <domain1> <domain2>` | Keyword gap between two domains | `organic_research` (keyword-gap report) |
| `/seo semrush backlinks <domain>` | Referring domains, anchors, authority, link growth, link types | `backlink_research` |
| `/seo semrush trends <domain>` | Traffic / visibility trend over time | `trends_research`, `overview_research` |

For each command: run discovery → pick the matching report → get_report_schema
→ execute_report with the right `database`.

## Output conventions

- Cite the data source on every metric: "Semrush (live, <database>, confidence 1.00)".
- When Semrush and Moz disagree on the same metric, trust Semrush (larger index,
  live data) and note the discrepancy in the report.
- Toxic / risky link assessment: combine Semrush Authority Score + anchor
  distribution with the existing seo-backlinks Common Crawl + verify-crawler
  signals.
- Report Semrush "Authority Score" (0-100) as the domain-authority metric;
  do not relabel it "DA" (that is a Moz metric).

## Cross-skill delegation

- For multi-source confidence weighting across Semrush + Moz + Bing + Common
  Crawl, hand back to `seo-backlinks` (Semrush is the highest-confidence source).
- For keyword clustering, hand the keyword + volume + intent data to `seo-cluster`.
- For content briefs, feed `keyword_research` volume/difficulty/questions into
  `seo-content-brief`.
- For live SERP scraping where DataForSEO is also installed, prefer DataForSEO
  for raw SERP HTML; prefer Semrush for keyword metrics and competitive data.

## Cost guardrails

Semrush API usage is metered in **API units** per report row. Before running a
batch (>= 50 rows or >= 10 domains):

1. Estimate the row count and surface it to the orchestrator before executing.
2. Use report `display_limit` / `display_offset` to cap rows (default 30-50 for
   exploratory queries; raise only when the user needs the full set).
3. Log the report name + row count after each call so unit spend is traceable.

Do not run unbounded `*_fullsearch` or full backlink pulls without confirming
with the user first.

## Error handling

| Error | Cause | Resolution |
|-------|-------|-----------|
| Semrush tools not available | MCP not connected | See `extensions/semrush/docs/SEMRUSH-SETUP.md` |
| `NOTHING FOUND` / empty report | Domain/keyword has no data in that database | Try a different `database` or the www/non-www host |
| Unit/limit error | API unit balance exhausted | Check Semrush plan; reduce `display_limit` |
| Unknown report param | Guessed params | Call `get_report_schema` and retry with exact params |

## Post-analysis

After completing any Semrush analysis command, offer:
"Generate a professional PDF report? Use `/seo google report`"
