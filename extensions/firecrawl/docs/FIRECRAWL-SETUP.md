# Firecrawl Setup Guide

## 1. Install and sign in to the CLI (recommended)

```bash
npm install -g firecrawl-cli     # tested with 1.26.3
firecrawl login --browser        # browser sign-in; the key is stored by the CLI, not in this repo
firecrawl --status               # signed in, team, credits left
firecrawl credits --json         # remaining credits, plan credits, billing period
```

Then try:

```
/seo firecrawl map https://example.com
```

## 2. MCP server (alternative)

The installer in this folder configures the Firecrawl MCP server instead:

```bash
./extensions/firecrawl/install.sh
```

It prompts for an API key (starts with `fc-`, from the Firecrawl dashboard under
API Keys). If the installer fails, add this to `~/.claude.json` manually:

```json
{
  "mcpServers": {
    "firecrawl-mcp": {
      "command": "npx",
      "args": ["-y", "firecrawl-mcp"],
      "env": {
        "FIRECRAWL_API_KEY": "fc-your-api-key-here"
      }
    }
  }
}
```

Restart Claude Code to load the MCP tools.

## 3. Understanding Credits

Measured with firecrawl-cli 1.26.3 on 2026-11-10 (credits read before and after):

| Operation | Credits Used |
|-----------|-------------|
| `map` | 1 per call |
| `scrape` | 1 per page; PDFs 1 per parsed page (cap with `--max-pages`) |
| `crawl` | At least 1 per page crawled; always set `--limit` |
| `search` | 2 for a 2-result web search; `--scrape` adds the scrape cost per result |

Plan allowances and reset dates differ by account: read them from
`firecrawl credits --json` rather than assuming a figure.

**Tip**: single pages are free through WebFetch or `render_page.py`. Use `map` first
(one credit) to see how many pages a site has, then decide how many to `crawl`.
