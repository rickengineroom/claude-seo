# Page Type Taxonomy: Extended Types

Types 9-14 extend `page-type-taxonomy.md` (types 1-8). Use the same priority list at
the end of that file. Types 13 and 14 are result-only: they classify what ranks so
community, marketplace and video intent stay visible; they are rarely the target
page type a client builds.

---

## 9. Category / Collection

**Primary signals:** one merchant's product grid under a taxonomy node (for example
`/collections/`, `/category/`, `/c/`), filters and sort controls, product cards with
price, short intro copy above or below the grid, breadcrumb, pagination.

**SERP indicators (top 10):** several retailer category pages, shopping or product
results, popular products blocks, query is a plural product noun ("linen sheets",
"baby gift boxes") with few question modifiers.

**Content structure:** H1 (category name) > short intro > filters > product grid >
pagination > supporting copy (buying guidance, sizing, delivery facts) > related
categories.

**Required elements:** crawlable product links, self-referencing canonical on each
paginated page, BreadcrumbList, unique intro copy, product cards with price and
availability.

**Common mismatches:**
- Blog Post targeting a category query (severity: CRITICAL)
- Single Product Page targeting a plural category query (severity: HIGH)

---

## 10. Product Listing

**Primary signals:** a product grid from many sellers or an aggregator: marketplace
search results (Amazon, eBay, Etsy, Shopee, Tokopedia), price-comparison grids,
retailer on-site search result pages.

**SERP indicators (top 10):** marketplace domains in the top 10, shopping results,
price-led titles. When marketplaces dominate, the query has marketplace intent: the
user wants to compare offers across sellers.

**Content structure:** search or filter header > offer grid with seller, price,
rating > facets.

**Required elements (when the client is a marketplace):** crawlable listing URLs
for the facets that have demand, canonical rules for the rest.

**Common mismatches:**
- Brand category page against a marketplace-dominated result page (severity:
  MEDIUM; report it as a market fact, the fix may be marketplace presence rather
  than a page change)

---

## 11. Homepage

**Primary signals:** site root URL, brand navigation, broad value proposition,
links into every main section.

**SERP indicators (top 10):** brand or navigational query, sitelinks, knowledge
panel, one domain holding several positions. Rater-guideline intent: Website.

**Content structure:** brand statement > primary categories or services > proof >
contact or conversion route.

**Required elements:** Organization (and WebSite) markup, clear links to the
pages that own each commercial query.

**Common mismatches:**
- Inner page or blog post ranking for the brand query (severity: HIGH)
- Homepage ranking for a specific category or service query that has its own page
  (severity: MEDIUM; check Search Console for split signals before calling it
  cannibalisation)

---

## 12. Case Study

**Primary signals:** one client or project story: problem, approach, outcome with
figures, client name or sector, quote, often under `/work/`, `/case-studies/`,
`/projects/`.

**SERP indicators (top 10):** queries with "case study", "example", "results",
"portfolio", or B2B evaluation queries where agency and vendor proof pages rank.

**Content structure:** headline outcome > client context > problem > what was done
> results with figures and dates > quote > related service link.

**Required elements:** named or described client, measurable outcome with a date,
link to the service page that sells the work.

**Common mismatches:**
- Service Page targeting a "case study" or "examples" query (severity: MEDIUM)
- Case Study targeting a head service query (severity: HIGH)

---

## 13. Forum / Community (result-only)

**Primary signals:** user-generated thread or Q&A (Reddit, Quora, Whirlpool,
Stack Exchange, brand community forums), multiple authors, votes or replies.

**SERP indicators:** discussion or forum results, Reddit or Quora URLs in the top 10.
This signals that searchers want first-hand opinions and lived experience.

**How to use:** never filter these out before classifying intent. A community-heavy
result page means the target page needs first-hand experience, real examples and
honest trade-offs, or that the client should take part in the community itself.

---

## 14. Video (result-only)

**Primary signals:** video player page (YouTube, Vimeo, TikTok), video carousel or
video results in the top 10.

**How to use:** a video-heavy result page means the query expects demonstration.
Recommend a video asset embedded in the target page, not a separate text page.

---

## Location Page notes (type 7)

- One page per real place the business serves from (store, office, clinic). A
  service-area page without a physical presence is a Service Page with local
  signals, not a Location Page.
- Location pages need unique content per place (staff, hours, directions, local
  proof). Swapping only the city name across many pages is a doorway pattern.
- When the result page shows a local pack, record Visit-in-Person intent and hand
  off to `seo-local`.
