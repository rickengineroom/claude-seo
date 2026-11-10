# Firecrawl Extension for Claude SEO

Full-site crawling, scraping, site mapping and web search powered by [Firecrawl](https://www.firecrawl.dev/), driven through the Firecrawl CLI. Enables site-wide SEO analysis with JavaScript rendering support.

## Prerequisites

- [Claude SEO](https://github.com/AgriciDaniel/claude-seo) installed
- Node.js 20+
- A Firecrawl account (plans and credit allowances: https://www.firecrawl.dev/pricing)

## Installation

```bash
npm install -g firecrawl-cli     # tested with 1.26.3
firecrawl login --browser        # browser sign-in; no key in repo config files
firecrawl --status               # confirms sign-in and credits left
```

The `install.sh` / `install.ps1` scripts in this folder configure the older Firecrawl
MCP server instead. The skill works with either; the CLI is the tested path.

## Commands

| Command | Purpose | Credits (measured 2026-11-10, CLI 1.26.3) |
|---------|---------|---------|
| `/seo firecrawl map <url>` | Discover site structure (URLs only) | 1 per call |
| `/seo firecrawl scrape <url>` | One page with JS rendering | 1 per page (PDF: 1 per parsed page) |
| `/seo firecrawl crawl <url>` | Multi-page crawl with content extraction | At least 1 per page crawled |
| `/seo firecrawl search <query>` | Web search (`site:example.com` in the query to scope it) | 2 for a 2-result web search |

Single pages are free through WebFetch or `render_page.py`; use Firecrawl when those fail.
Check spend with `firecrawl credits --json` before and after a batch.

## Integration with Claude SEO

When the CLI is signed in, other Claude SEO skills can use it from the main session:

- **`/seo audit`**: `map` to discover pages, then a capped `crawl` on key sections
- **`/seo technical`**: broken link detection across the crawled pages
- **`/seo sitemap`**: compare the XML sitemap with mapped URLs
- **`/seo content`**: thin content detection at scale

## Troubleshooting

**CLI not signed in?**
- Run `firecrawl login`, then `firecrawl --status`
- MCP setup instead: see [FIRECRAWL-SETUP.md](docs/FIRECRAWL-SETUP.md)

**Credits exhausted?**
- `firecrawl credits --json` shows remaining credits and the billing period
- Fall back to WebFetch, `render_page.py` and `sitemap_discovery.py`

**Site blocking crawls?**
- Some sites block automated crawling via robots.txt or Cloudflare
- Try `scrape` (single page) instead of `crawl` (full site)
- Fall back to `fetch_page.py` for basic HTML retrieval

## Uninstall

```bash
npm uninstall -g firecrawl-cli          # CLI
./extensions/firecrawl/uninstall.sh      # MCP config, macOS/Linux
.\extensions\firecrawl\uninstall.ps1     # MCP config, Windows
```

## Links

- [Firecrawl Documentation](https://docs.firecrawl.dev/)
- [Firecrawl CLI](https://www.npmjs.com/package/firecrawl-cli)
- [Claude SEO](https://github.com/AgriciDaniel/claude-seo)
