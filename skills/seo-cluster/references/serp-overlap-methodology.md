# SERP Overlap Methodology

## Core Principle

Two keywords that return the same Google results should be targeted by the same page.
Two keywords that return completely different results need separate pages. This is the
foundation of SERP-based clustering -- using Google's own ranking decisions to determine
content architecture rather than relying on keyword text similarity or stemming.

## Scoring Algorithm

### Step 1: Collect SERP Data

For each keyword in the candidate set, retrieve the top 10 organic results **for the
target market**:
- Semrush `phrase_organic` (`database` = market, `display_limit: 10`,
  `export_columns: [position, url, domain, triggered_serp_features]`), or DataForSEO
  `serp_organic_live_advanced` with the market's `location_code` and `language_code`
  when that MCP is configured. WebSearch is not a source: it returns titles and URLs
  for US results only, without ranked positions.
- Extract only organic result URLs (ignore ads, featured snippets, PAA, knowledge panels)
- Keep `triggered_serp_features` per keyword (needed for anti-pattern 4 and the
  AI Overview attribute)
- Normalize URLs: strip protocol, trailing slash, and query parameters (except meaningful ones)
- Store as a set of 10 URLs per keyword with the source, database and data date

**Stop rule:** if no source returns real top-10 URLs for the market, do not
produce overlap scores. Report "SERP-overlap evidence for <market> could not be
obtained" and stop; do not fall back to intent-only clustering or assumed scores.

### Step 2: Pairwise Comparison

For each pair of keywords (A, B):
1. Retrieve the URL sets: `urls_A` and `urls_B`
2. Compute overlap: `shared = urls_A intersection urls_B`
3. Score: `overlap_score = len(shared)`

### Step 3: Apply Thresholds

| Overlap Score | Relationship | Action |
|--------------|-------------|--------|
| 7-10 | **Same post** | Merge keywords into one target page. Use higher-volume keyword as primary. |
| 4-6 | **Same cluster** | Place in same spoke cluster. May be separate posts or same post depending on volume difference. |
| 2-3 | **Interlink** | Place in adjacent clusters. Create cross-cluster internal links. |
| 0-1 | **Separate** | Different clusters entirely or exclude from current pillar topic. |

### Step 4: Handle Ambiguous Scores (3-4 Range)

Scores in the 3-4 range require tiebreaking:
1. Check domain overlap (same domains but different pages = closer relationship)
2. Check intent alignment (same result-page intent = lean toward same cluster)
3. Check volume ratio from Semrush for the same database (if one keyword has 10x+
   more volume, it may deserve its own post); no volume data = no volume tiebreak
4. When in doubt, keep in same cluster with separate posts (err toward cohesion)

These thresholds (3 shared URLs, 4 of 10, 7 of 10) are working conventions, not
validated cut-offs. State them as such in the plan.

## Optimization Strategy

Full pairwise comparison of N keywords requires N*(N-1)/2 SERP fetches. For 40
keywords, that is 780 comparisons. Optimize by reducing unnecessary checks:

### Pre-Grouping

1. Group keywords by the Semrush intent label (a grouping aid only, not a verdict)
2. Group keywords that share the same head term (e.g., "CRM software" variants)
3. Only run pairwise SERP comparison within pre-groups
4. Cross-check boundary keywords (highest volume in each group) across groups

Pairwise comparison costs no extra API calls once each keyword's top 10 is cached:
it is set arithmetic. The cost is one `phrase_organic` call per keyword, so the
pre-grouping mainly limits review effort, not data pulls.

### Unchecked Pairs

- A pair that was not compared is recorded as `null` (unchecked) in the matrix,
  never as an assumed score.
- Do not merge, group or separate on an unchecked pair. Compare it or leave it out.

## Scoring Matrix Format

Store the overlap data as a symmetric matrix in `cluster-plan.json`:

```json
{
  "serp_matrix": {
    "keywords": ["keyword-a", "keyword-b", "keyword-c"],
    "scores": [
      [10, 5, 1],
      [5, 10, 3],
      [1, 3, 10]
    ]
  }
}
```

Diagonal is always 10 (a keyword overlaps perfectly with itself).

## Anti-Patterns

1. **Never cluster by text similarity alone.** "Dog training tips" and "dog training
   classes" may have completely different SERPs despite similar text.
2. **Never use stemming-only grouping.** "Run" and "running" may target different
   intents entirely.
3. **Never assume related searches belong in the same cluster.** Verify with SERP data.
4. **Never ignore SERP feature differences.** If keyword A triggers a local pack and
   keyword B triggers a featured snippet, they likely need different content types
   even with moderate URL overlap.
5. **Never treat all domains equally.** Wikipedia and Reddit appear in many SERPs.
   Consider filtering out ubiquitous domains (top 5 most common) before overlap
   scoring, or weighting domain-specific results higher. Keep them when judging
   intent: a Reddit-heavy or marketplace-heavy top 10 is itself an intent signal.

## Data Source Priority

The market is a parameter, never a constant. Use the same market for every keyword
in one plan.

1. **Semrush** (connected): `phrase_organic` with `database` set to the market
   (`us`, `uk`, `au`, `sg`, `id`, `mobile-au`, ...). Record the data date.
2. **DataForSEO** (if configured): `serp_organic_live_advanced` with the market's
   `location_code` and `language_code` (for example Australia + `en`, Singapore +
   `en`, Indonesia + `id`). Run the cost check first.
3. **No source:** stop (see the stop rule in Step 1). WebSearch is not a fallback.

## Caching

Within a single clustering session, cache all SERP results. If keyword A's results
are fetched for the A-B comparison, reuse them for the A-C comparison. This halves
the number of actual SERP fetches needed.
