# Semrush Extension Setup

This extension adds a `seo-semrush` skill and `seo-semrush` agent that drive the
official **Semrush MCP server**. It is this project's premium keyword + backlink
+ competitive-intelligence source (replacing the Ahrefs extension).

## What you need

- A Semrush subscription with **API units** (the MCP bills per report row).
- The official Semrush MCP server connected to Claude Code.

## Connect the Semrush MCP

Semrush ships an official **remote** MCP endpoint:

```
https://mcp.semrush.com/v1/mcp
```

Connect it once and it is available to every Claude Code session. Either:

- **Claude Code CLI:**
  ```bash
  claude mcp add --transport http semrush https://mcp.semrush.com/v1/mcp
  ```
  Then authenticate when prompted (OAuth / API key per Semrush's MCP docs).

- **Or** add it under `mcpServers` in your Claude settings with the transport and
  auth Semrush specifies for your account.

> If your Semrush MCP is already connected (tools whose names end in
> `_research`, plus `get_report_schema` / `execute_report`, appear in the
> session), you do **not** need to do anything — the skill will detect and use it.

## Install the skill + agent

The base `claude-seo` plugin must already be installed. Then:

- **Windows:** `powershell -ExecutionPolicy Bypass -File extensions\semrush\install.ps1`
- **macOS/Linux:** `bash extensions/semrush/install.sh`

This copies `seo-semrush` into `~/.claude/skills/` and the agent into
`~/.claude/agents/`. Open a new Claude Code session afterward.

## Verify

```
/seo semrush overview example.com
```

You should see an authority score, traffic estimate, and keyword/backlink counts.

## Usage

| Command | What it does |
|---|---|
| `/seo semrush overview <domain>` | Authority score, traffic, keyword/backlink counts, trend |
| `/seo semrush organic <domain>` | Top organic keywords, positions, traffic share |
| `/seo semrush keywords <keyword>` | Volume, difficulty, CPC, intent, related, questions |
| `/seo semrush competitors <domain>` | Organic competitors and overlap |
| `/seo semrush gap <domain1> <domain2>` | Keyword gap between two domains |
| `/seo semrush backlinks <domain>` | Referring domains, anchors, authority, growth |
| `/seo semrush trends <domain>` | Traffic / visibility trend over time |

## Notes

- **Pick the right `database`** (regional market) — e.g. `sg` for Singapore,
  `us` for the US. The skill detects market from the client; override if needed.
- The skill follows the Semrush 3-step workflow: discovery `*_research` →
  `get_report_schema` → `execute_report`.
- Semrush pairs with `seo-backlinks` for multi-source confidence weighting and
  with `seo-cluster` / `seo-content-brief` for keyword-driven content planning.
