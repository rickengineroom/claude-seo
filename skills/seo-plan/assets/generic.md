<!-- Updated: 2026-02-07 -->
# Generic Business SEO Strategy Template

## Overview

This template applies to businesses that don't fit neatly into SaaS, local service, e-commerce, publisher, or agency categories. Customize based on your specific business model.

## Recommended Site Architecture

```
/
├── Home
├── /products (or /services)
│   ├── /product-1
│   ├── /product-2
│   └── ...
├── /solutions (if applicable)
│   ├── /solution-1
│   └── ...
├── /about
│   ├── /team
│   ├── /history
│   └── /values
├── /resources
│   ├── /blog
│   ├── /guides
│   ├── /faq
│   └── /glossary
├── /contact
├── /support
└── /legal
    ├── /privacy
    └── /terms
```

## Universal SEO Principles

### Every Page Should Have
- Unique title tag (30-60 chars)
- Unique meta description (120-160 chars)
- Single H1 matching page intent
- Logical heading hierarchy (H1→H2→H3)
- Internal links to related content
- Clear call-to-action

### Schema for All Sites
| Page Type | Schema Types |
|-----------|-------------|
| Homepage | Organization, WebSite |
| About | Organization, AboutPage |
| Contact | ContactPage |
| Blog | Article, BlogPosting |
| FAQ | QAPage for genuine Q&A; FAQPage no longer yields rich results (retired May 2026); keep FAQPage only when useful for on-page content structure |
| Product/Service | Product or Service |

## Content Quality Standards

### Minimum Word Counts
| Page Type | Min Words |
|-----------|-----------|
| Homepage | 500 |
| Product/Service | 800 |
| Blog Post | 1,500 |
| About Page | 400 |
| Landing Page | 600 |

### E-E-A-T Essentials
1. **Experience**: Share real examples and case studies
2. **Expertise**: Display credentials and qualifications
3. **Authoritativeness**: Earn mentions and citations
4. **Trustworthiness**: Full contact info, policies visible

## Technical Foundations

### Must-Haves
- [ ] HTTPS enabled
- [ ] Mobile-responsive design
- [ ] robots.txt configured
- [ ] XML sitemap submitted
- [ ] Google Search Console verified
- [ ] Core Web Vitals passing (LCP <2.5s, INP <200ms, CLS <0.1)

### Should-Haves
- [ ] Structured data on key pages
- [ ] Internal linking strategy
- [ ] 404 error page optimized
- [ ] Redirect chains eliminated
- [ ] Image optimization (WebP, lazy loading)

## Build Dependencies

Order by dependency, not by date. Ordering, effort and timing are set after
scope approval.

### Needed first (other pages depend on them)
1. Homepage
2. Core product/service pages (the hubs)
3. About and contact pages (entity and trust information)
4. Schema for those page types

### Built on the hubs
1. Supporting articles or resources that answer questions the hubs cannot,
   only where the foundation keyword map shows demand
2. Additional product/service pages
3. Internal links from supporting pages back to their hub

### Ongoing work (scoped separately)
1. Link acquisition
2. AI search readiness
3. Performance
4. Original research and PR

## Key Metrics to Track

- Organic traffic (overall and by section)
- Keyword rankings (branded and non-branded)
- Conversion rate from organic
- Pages indexed
- Core Web Vitals scores
- Backlinks acquired

## Customization Points

Adjust this template based on:

1. **Business Model**: B2B vs B2C vs D2C
2. **Geographic Scope**: Local, national, or international
3. **Content Type**: Product-focused vs content-heavy
4. **Competition Level**: Niche vs competitive market
5. **Content capacity**: how many pages the business can populate with unique content

## Generative Engine Optimization (GEO) Checklist

- [ ] Include clear, quotable facts and statistics that AI systems can extract and cite
- [ ] Use structured data (Schema.org) to help AI systems understand content
- [ ] Build topical authority through comprehensive content clusters
- [ ] Provide original data, research, or unique perspectives AI cannot find elsewhere
- [ ] Maintain consistent entity information (brand, people, products) across the web
- [ ] Structure content with clear headings, definitions, and step-by-step formats
- [ ] Consider adding an `llms.txt` file at site root (emerging convention for AI crawlers: Google treats it as a regular text file)
- [ ] Monitor AI citation across Google AI Overviews, ChatGPT, Perplexity, and Bing Copilot
