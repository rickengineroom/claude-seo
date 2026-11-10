# GA4 Data API v1beta Reference

## Overview

The Google Analytics Data API v1beta provides programmatic access to GA4 report data. For SEO, the primary use case is organic traffic analysis.

**Base URL:** `https://analyticsdata.googleapis.com/v1beta`

## Key Methods

| Method | Description |
|--------|-------------|
| `properties.runReport` | Run a standard report |
| `properties.batchRunReports` | Up to 5 reports in one call |
| `properties.runRealtimeReport` | Last 30 minutes of data |
| `properties.getMetadata` | Available dimensions and metrics |
| `properties.checkCompatibility` | Verify dimension/metric combinations |

## runReport Request

```json
{
  "property": "properties/123456789",
  "dimensions": [
    { "name": "date" },
    { "name": "landingPage" }
  ],
  "metrics": [
    { "name": "sessions" },
    { "name": "totalUsers" }
  ],
  "dateRanges": [
    { "startDate": "28daysAgo", "endDate": "yesterday" }
  ],
  "dimensionFilter": {
    "filter": {
      "fieldName": "sessionDefaultChannelGroup",
      "stringFilter": {
        "matchType": "EXACT",
        "value": "Organic Search"
      }
    }
  },
  "orderBys": [
    { "metric": { "metricName": "sessions" }, "desc": true }
  ],
  "limit": 100,
  "returnPropertyQuota": true
}
```

## SEO-Relevant Dimensions

| Dimension | Description |
|-----------|-------------|
| `date` | Date in YYYYMMDD format |
| `pagePath` | Page path (e.g., `/blog/post`) |
| `landingPage` | Entry page path |
| `landingPagePlusQueryString` | Entry page with query params |
| `fullPageUrl` | Full page URL |
| `pageTitle` | Page title |
| `sessionSource` | Traffic source (e.g., `google`) |
| `sessionMedium` | Traffic medium (e.g., `organic`) |
| `sessionDefaultChannelGroup` | Channel grouping (e.g., `Organic Search`) |
| `country` | User country |
| `deviceCategory` | `desktop`, `mobile`, `tablet` |
| `hostName` | Domain name |
| `pageReferrer` | Referrer URL |
| `searchTerm` | Site search term (view_search_results events only) |

## SEO-Relevant Metrics

| Metric | Description |
|--------|-------------|
| `sessions` | Number of sessions |
| `totalUsers` | Total unique users |
| `newUsers` | First-time users |
| `activeUsers` | Users with engagement |
| `screenPageViews` | Page views |
| `bounceRate` | Bounce rate (0-1, multiply by 100 for %) |
| `averageSessionDuration` | Avg duration in seconds |
| `engagementRate` | Engaged session rate (0-1) |
| `keyEvents` | Key events (replaced deprecated `conversions`) |
| `eventCount` | Total event count |

## Filter Expressions

String filter: see `dimensionFilter` in the runReport request above. Match types: `EXACT`, `BEGINS_WITH`, `ENDS_WITH`, `CONTAINS`, `FULL_REGEXP`, `PARTIAL_REGEXP`

### Combining Filters

```json
{
  "andGroup": {
    "expressions": [
      { "filter": { "fieldName": "country", "stringFilter": { "matchType": "EXACT", "value": "US" }}},
      { "filter": { "fieldName": "deviceCategory", "stringFilter": { "matchType": "EXACT", "value": "mobile" }}}
    ]
  }
}
```

Also supports `orGroup` and `notExpression`.

## Date Range Shortcuts

| Value | Meaning |
|-------|---------|
| `today` | Current day |
| `yesterday` | Previous day |
| `NdaysAgo` | N days ago (e.g., `28daysAgo`) |
| `YYYY-MM-DD` | Specific date |

Up to 4 date ranges per request (for period-over-period comparison).

## Token-Based Quotas

Core reporting quotas (Google Analytics Data API quotas page, checked 2026-11-10):

| Quota | Standard property | Analytics 360 property |
|-------|-------------------|------------------------|
| Tokens per property per day | 200,000 | 2,000,000 |
| Tokens per property per hour | 40,000 | 400,000 |
| Tokens per project per property per hour | 14,000 | 140,000 |
| Concurrent requests per property | 10 | 50 |

Set `returnPropertyQuota: true` to monitor consumption (`ga4_report.py` prints it).
Simple reports cost ~1-10 tokens; complex ones up to ~100.

## Reports in `ga4_report.py`

| `--report` | Dimensions | Metrics | Default channel |
|------------|-----------|---------|-----------------|
| `organic`, `top-pages` | date / landingPage | sessions, users, views, bounce, engagement, keyEvents | Organic Search |
| `device`, `country` | deviceCategory / country | sessions, users | Organic Search |
| `ai-assistant` | landingPage, sessionSource | sessions, engagedSessions, keyEvents | AI Assistant |
| `key-events` | landingPage, sessionDefaultChannelGroup | sessions, keyEvents[:name], sessionKeyEventRate[:name] | all |
| `search-terms` | searchTerm (eventName = view_search_results) | eventCount, totalUsers | all |

`--channel "<Default Channel Group>"` overrides the default; `--channel all` removes it.
`keyEvents` replaced `conversions` in 2024; `keyEvents:purchase` reads one key event.

## Landing page join trap

`landingPage` is a path with no host and no query string (`landingPagePlusQueryString`
keeps the query). `/about` and `/about/` are separate rows, and sessions that start
without a page view are `(not set)`. Join to Search Console `page` on a key built the
same way on both sides: path only, no query string, no trailing slash. `ga4_report.py`
emits it as `page_key` and reports `(not set)` sessions in `landing_page_notes`;
never join `(not set)` and never call an unmatched page "zero traffic" without checking
its variants.

## Python Example

```python
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange, Dimension, Filter, FilterExpression,
    Metric, OrderBy, RunReportRequest,
)
from google.oauth2 import service_account

credentials = service_account.Credentials.from_service_account_file(
    "service_account.json",
    scopes=["https://www.googleapis.com/auth/analytics.readonly"],
)

client = BetaAnalyticsDataClient(credentials=credentials)

request = RunReportRequest(
    property="properties/123456789",
    dimensions=[Dimension(name="landingPage")],
    metrics=[Metric(name="sessions"), Metric(name="totalUsers")],
    date_ranges=[DateRange(start_date="28daysAgo", end_date="yesterday")],
    dimension_filter=FilterExpression(
        filter=Filter(
            field_name="sessionDefaultChannelGroup",
            string_filter=Filter.StringFilter(
                match_type=Filter.StringFilter.MatchType.EXACT,
                value="Organic Search",
            ),
        )
    ),
    order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="sessions"), desc=True)],
    limit=50,
    return_property_quota=True,
)

response = client.run_report(request)
for row in response.rows:
    print(f"{row.dimension_values[0].value}: {row.metric_values[0].value} sessions")
```

## Authentication
- **Scope:** `https://www.googleapis.com/auth/analytics.readonly`
- Service account must have **Viewer** role in GA4 property
- Add via GA4 Admin > Property Access Management
