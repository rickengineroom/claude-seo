#!/usr/bin/env python3
"""
Google Search Console Search Analytics query helper.

Queries the GSC Search Analytics API for clicks, impressions, CTR, and position
data. Supports filtering by dimensions, auto-pagination, and quick-win detection.

Usage:
    python gsc_query.py --property sc-domain:example.com
    python gsc_query.py --property sc-domain:example.com --days 90 --dimensions query
    python gsc_query.py --property sc-domain:example.com --dimensions query \
        --filter "query:includingRegex:(?i)^how " --limit 25000
    python gsc_query.py buckets --property sc-domain:example.com --brand-regex "(?i)acme"
    python gsc_query.py sitemaps --property sc-domain:example.com
    python gsc_query.py sites

Row cap: the API returns at most 25,000 rows per request and this script pages
with startRow up to 100,000. A page or query missing from a capped result is
NOT proof of zero impressions; check ``truncated`` before reporting absence.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from typing import Optional

try:
    from googleapiclient.discovery import build
except ImportError:
    print(
        "Error: google-api-python-client required. "
        "Install with: pip install google-api-python-client",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    from google_auth import describe_google_error, get_oauth_credentials, load_config
except ImportError:
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from google_auth import describe_google_error, get_oauth_credentials, load_config

GSC_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
INDEXATION_NOTE = (
    "Sitemaps API contents[].submitted reflects submitted URL counts only. "
    "Use the URL Inspection API as the indexation truth for whether specific "
    "URLs are indexed."
)
GSC_ANOMALY_START = "2025-05-13"
GSC_ANOMALY_END = "2026-04-27"
GSC_ANOMALY_WARNING = (
    "GSC impressions logging error affected impressions, CTR, and average "
    "position from 2025-05-13 through 2026-04-27; clicks were not affected."
)
MAX_TOTAL_ROWS = 100000
VALID_DIMENSIONS = {
    "query", "page", "country", "device", "date", "hour", "searchAppearance",
}
VALID_OPERATORS = {
    "equals", "notEquals", "contains", "notContains", "includingRegex", "excludingRegex",
}
# Search Console regex filters use RE2 syntax and are case-sensitive unless
# the pattern starts with (?i). Wh-words match anywhere; auxiliaries only at
# the start, so "things to do in bali" is not counted as a question.
QUESTION_REGEX = (
    r"(?i)(^(can|could|does|do|did|is|are|was|should|will|would)\s)"
    r"|\b(who|what|when|where|why|how|which)\b"
)
LENGTH_BUCKETS = [
    ("1 word", r"^\S+$"),
    ("2-3 words", r"^\S+(\s+\S+){1,2}$"),
    ("4-6 words", r"^\S+(\s+\S+){3,5}$"),
    ("7+ words", r"^\S+(\s+\S+){6,}$"),
]
UNVERIFIED_PERMISSION = "siteUnverifiedUser"


def _parse_filter(raw: str) -> dict:
    """Parse a CLI filter 'dimension:operator:expression' into an API filter."""
    parts = raw.split(":", 2)
    if len(parts) != 3 or not all(parts):
        raise ValueError(
            f"Filter '{raw}' must be dimension:operator:expression, "
            "e.g. query:includingRegex:(?i)^how"
        )
    dimension, operator, expression = parts
    if dimension not in {"query", "page", "country", "device", "searchAppearance"}:
        raise ValueError(f"Unsupported filter dimension: {dimension}")
    if operator not in VALID_OPERATORS:
        raise ValueError(
            f"Unsupported filter operator: {operator} "
            f"(use one of {', '.join(sorted(VALID_OPERATORS))})"
        )
    return {"dimension": dimension, "operator": operator, "expression": expression}


def _validate_dimensions(dimensions: Optional[list]) -> list[str]:
    """Validate API dimensions before credentials or a service are loaded."""
    if dimensions is None:
        return ["query", "page"]
    if not isinstance(dimensions, list):
        raise ValueError("GSC dimensions must be a list or None")
    if any(not isinstance(item, str) for item in dimensions):
        raise ValueError("GSC dimensions must contain only strings")
    invalid = sorted(set(dimensions) - VALID_DIMENSIONS)
    if invalid:
        raise ValueError(f"Unsupported GSC dimensions: {', '.join(invalid)}")
    if len(dimensions) != len(set(dimensions)):
        raise ValueError("GSC dimensions cannot contain duplicates")
    return list(dimensions)


def _parse_dimensions(raw: str) -> list[str]:
    """Parse a comma-separated CLI dimension list, preserving an empty list."""
    return _validate_dimensions([item.strip() for item in raw.split(",") if item.strip()])


def _totals_from_row(row: dict) -> dict:
    """Normalize a Search Analytics aggregate row for public output."""
    return {
        "clicks": row.get("clicks", 0),
        "impressions": row.get("impressions", 0),
        "ctr": round(row.get("ctr", 0) * 100, 2),
        "position": round(row.get("position", 0), 1),
    }


def _date_range_overlaps(start_date: str, end_date: str, overlap_start: str, overlap_end: str) -> bool:
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
        window_start = datetime.strptime(overlap_start, "%Y-%m-%d").date()
        window_end = datetime.strptime(overlap_end, "%Y-%m-%d").date()
    except ValueError:
        return False
    return start <= window_end and end >= window_start


def _build_gsc_service():
    """Build the Search Console API service."""
    credentials = get_oauth_credentials(GSC_SCOPES)
    if not credentials:
        return None
    try:
        return build("searchconsole", "v1", credentials=credentials)
    except Exception as e:
        print(f"Error building GSC service: {e}", file=sys.stderr)
        return None


def _query_site_totals(
    service,
    site_url: str,
    start_date: str,
    end_date: str,
    search_type: str,
    data_state: str,
    filters: Optional[list],
) -> Optional[dict]:
    """Fetch true site-wide totals via a dimensionless query.

    GSC anonymizes click data for low-volume ("rare") queries, so summing
    the per-query rows undercounts clicks (often to exactly 0) and
    impressions. A query with an empty ``dimensions`` array returns a
    single aggregate row carrying the real site totals (issue #130).
    Returns ``None`` if the aggregate query fails (caller falls back).
    """
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": [],
        "type": search_type,
        "rowLimit": 1,
        "dataState": data_state,
    }
    if filters:
        body["dimensionFilterGroups"] = [{"filters": filters}]
    try:
        response = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
    except Exception:
        return None
    rows = response.get("rows", [])
    if not rows:
        return {"clicks": 0, "impressions": 0, "ctr": 0, "position": 0}
    return _totals_from_row(rows[0])


def query_search_analytics(
    site_url: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    dimensions: Optional[list] = None,
    search_type: str = "web",
    row_limit: int = 1000,
    filters: Optional[list] = None,
    data_state: str = "final",
) -> dict:
    """
    Query GSC Search Analytics API.

    Args:
        site_url: GSC property (e.g., 'sc-domain:example.com' or 'https://example.com/').
        start_date: Start date (YYYY-MM-DD). Default: 28 days ago.
        end_date: End date (YYYY-MM-DD). Default: 3 days ago (data lag).
        dimensions: List of dimensions: query, page, country, device, date, searchAppearance.
        search_type: web, image, video, news, discover, googleNews.
        row_limit: Maximum total rows to return. Requests are internally paged
            at up to 25,000 rows and the public result is capped at 100,000.
        filters: List of filter dicts with dimension, operator, expression.
        data_state: 'final' or 'all' (includes fresh/unfinalized data).

    Returns:
        Dictionary with rows, totals, and quick_wins.
    """
    result = {
        "property": site_url,
        "rows": [],
        "totals": {"clicks": 0, "impressions": 0, "ctr": 0, "position": 0},
        "totals_source": None,
        "totals_complete": False,
        "quick_wins": [],
        "warnings": [],
        "row_count": 0,
        "error": None,
    }

    if not isinstance(row_limit, int) or isinstance(row_limit, bool) or row_limit < 1:
        result["error"] = "row_limit must be a positive integer"
        return result

    try:
        dimensions = _validate_dimensions(dimensions)
    except ValueError as exc:
        result["error"] = str(exc)
        return result

    service = _build_gsc_service()
    if not service:
        result["error"] = "Could not build GSC service. Check service account credentials."
        return result

    if not start_date:
        start_date = (datetime.now() - timedelta(days=28)).strftime("%Y-%m-%d")
    if not end_date:
        end_date = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    result["date_range"] = {"start": start_date, "end": end_date}
    if _date_range_overlaps(start_date, end_date, GSC_ANOMALY_START, GSC_ANOMALY_END):
        result["warnings"].append(GSC_ANOMALY_WARNING)

    total_cap = min(row_limit, MAX_TOTAL_ROWS)
    if row_limit > MAX_TOTAL_ROWS:
        result["warnings"].append(
            f"Requested row limit {row_limit:,} was capped at {MAX_TOTAL_ROWS:,}."
        )

    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": dimensions,
        "type": search_type,
        "rowLimit": min(total_cap, 25000),
        "dataState": data_state,
    }

    if filters:
        body["dimensionFilterGroups"] = [{"filters": filters}]

    # Auto-paginate
    all_rows = []
    start_row = 0

    try:
        while len(all_rows) < total_cap:
            remaining = total_cap - len(all_rows)
            page_size = min(remaining, 25000)
            body["startRow"] = start_row
            body["rowLimit"] = page_size

            response = service.searchanalytics().query(
                siteUrl=site_url, body=body
            ).execute()

            rows = response.get("rows", [])
            all_rows.extend(rows[:remaining])

            if len(rows) < page_size or len(all_rows) >= total_cap:
                break

            start_row += len(rows)

            # Safety: cap at 100,000 rows
            if start_row >= MAX_TOTAL_ROWS:
                break

    except Exception as e:
        error_str = str(e)
        info = describe_google_error(e, resource=f"property '{site_url}'")
        if info["status"] in (401, 403) or "403" in error_str:
            result["error_detail"] = info
        access_reasons = {None, "forbidden", "PERMISSION_DENIED"}
        if ("403" in error_str or info["status"] == 403) and info["reason"] not in access_reasons:
            # Not a property-access problem: API disabled, quota project,
            # scope, or verification lost. Say which, by reason and consumer.
            result["error"] = (
                f"Google API 403 for property '{site_url}' "
                f"(reason {info['reason']}, consumer {info['consumer'] or 'unknown'}): "
                f"{info['diagnosis']}"
            )
        elif "403" in error_str:
            hint = (
                " A domain property is written sc-domain:example.com."
                if not site_url.startswith(("sc-domain:", "http://", "https://"))
                else ""
            )
            result["error"] = (
                f"Permission denied for property '{site_url}'.{hint} "
                "The signed-in Google account has no access to it: add that account "
                "(a service account email, or your own) in Google Search Console > "
                "Settings > Users and permissions, or use your own account with "
                "CLAUDE_SEO_GOOGLE_AUTH=adc after gcloud auth application-default login. "
                "Run `gsc_query.py sites`: a permission of siteUnverifiedUser means "
                "access was lost, not that the property has no data."
            )
        elif "404" in error_str:
            result["error"] = (
                f"Property '{site_url}' not found. "
                "Use 'sc-domain:example.com' for domain properties or "
                "'https://example.com/' for URL-prefix properties."
            )
        else:
            result["error"] = f"GSC API error: {e}"
        return result

    # Process rows
    total_clicks = 0
    total_impressions = 0

    for row in all_rows:
        keys = row.get("keys", [])
        clicks = row.get("clicks", 0)
        impressions = row.get("impressions", 0)
        ctr = row.get("ctr", 0)
        position = row.get("position", 0)

        processed = {
            "keys": keys,
            "clicks": clicks,
            "impressions": impressions,
            "ctr": round(ctr * 100, 2),
            "position": round(position, 1),
        }

        # Label keys by dimension name
        for i, dim in enumerate(dimensions):
            if i < len(keys):
                processed[dim] = keys[i]

        result["rows"].append(processed)
        total_clicks += clicks
        total_impressions += impressions

    result["row_count"] = len(all_rows)
    result["truncated"] = len(all_rows) >= total_cap and bool(dimensions)
    if result["truncated"]:
        result["warnings"].append(
            f"Row cap reached at {total_cap:,} rows; more rows may exist. A page or query "
            "missing from these rows is not proof of zero impressions. Re-run with a "
            f"higher --limit (paged by startRow, max {MAX_TOTAL_ROWS:,}) or filter to "
            "the page or query before reporting it as absent."
        )

    # Site totals come from a dimensionless aggregate query, NOT from summing
    # the per-dimension rows. Summing query-dimension rows undercounts clicks
    # because GSC anonymizes low-volume queries, producing a false "0 clicks"
    # site total (issue #130). Fall back to the row sum only if the aggregate
    # query fails.
    if dimensions == []:
        result["totals"] = (
            _totals_from_row(all_rows[0]) if all_rows
            else {"clicks": 0, "impressions": 0, "ctr": 0, "position": 0}
        )
        result["totals_source"] = "dimensionless_query"
        result["totals_complete"] = True
    else:
        site_totals = _query_site_totals(
            service, site_url, start_date, end_date, search_type, data_state, filters
        )
        if site_totals is not None:
            result["totals"] = site_totals
            result["totals_source"] = "dimensionless_aggregate"
            result["totals_complete"] = True
        else:
            result["totals"]["clicks"] = total_clicks
            result["totals"]["impressions"] = total_impressions
            if total_impressions > 0:
                result["totals"]["ctr"] = round((total_clicks / total_impressions) * 100, 2)
            result["totals_source"] = "partial_row_sum"
            result["warnings"].append(
                "The dimensionless totals query failed. Reported totals are an "
                "incomplete sum of returned rows and must not be presented as site-wide totals."
            )

    # Quick wins: position 4-10 with high impressions
    if "query" in dimensions:
        sorted_by_impressions = sorted(all_rows, key=lambda r: r.get("impressions", 0), reverse=True)
        for row in sorted_by_impressions[:200]:
            pos = row.get("position", 0)
            if 4 <= pos <= 10 and row.get("impressions", 0) > 50:
                result["quick_wins"].append({
                    "keys": row.get("keys", []),
                    "position": round(pos, 1),
                    "impressions": row.get("impressions", 0),
                    "clicks": row.get("clicks", 0),
                    "ctr": round(row.get("ctr", 0) * 100, 2),
                    "opportunity": "Position 4-10 with high impressions -- small ranking improvement yields significant traffic gain",
                })

        result["quick_wins"] = result["quick_wins"][:20]

    return result


def list_sitemaps(site_url: str) -> dict:
    """
    List sitemaps for a GSC property.

    Args:
        site_url: GSC property URL.

    Returns:
        Dictionary with sitemaps list.
    """
    result = {"property": site_url, "sitemaps": [], "error": None}

    service = _build_gsc_service()
    if not service:
        result["error"] = "Could not build GSC service."
        return result

    try:
        response = service.sitemaps().list(siteUrl=site_url).execute()
        for sm in response.get("sitemap", []):
            contents = [
                {k: v for k, v in item.items() if k != "indexed"}
                for item in sm.get("contents", [])
            ]
            result["sitemaps"].append({
                "path": sm.get("path"),
                "last_submitted": sm.get("lastSubmitted"),
                "is_pending": sm.get("isPending"),
                "is_index": sm.get("isSitemapsIndex"),
                "type": sm.get("type"),
                "warnings": sm.get("warnings", 0),
                "errors": sm.get("errors", 0),
                "contents": contents,
                "indexation_note": INDEXATION_NOTE,
            })
    except Exception as e:
        result["error"] = f"Error listing sitemaps: {e}"

    return result


def list_sites() -> dict:
    """
    List all verified GSC properties.

    Returns:
        Dictionary with sites list.
    """
    result = {"sites": [], "error": None}

    service = _build_gsc_service()
    if not service:
        result["error"] = "Could not build GSC service."
        return result

    try:
        response = service.sites().list().execute()
        for site in response.get("siteEntry", []):
            permission = site.get("permissionLevel")
            entry = {
                "url": site.get("siteUrl"),
                "permission": permission,
                "has_data_access": permission != UNVERIFIED_PERMISSION,
            }
            if permission == UNVERIFIED_PERMISSION:
                entry["note"] = (
                    "siteUnverifiedUser: access lost (owner removed the account or "
                    "verification lapsed). Queries will be denied; this is not a "
                    "zero-traffic property."
                )
            result["sites"].append(entry)
    except Exception as e:
        result["error"] = f"Error listing sites: {e}"
        result["error_detail"] = describe_google_error(e, resource="Search Console sites")

    return result


def query_buckets(
    site_url: str,
    brand_regex: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search_type: str = "web",
    data_state: str = "final",
    sample: int = 5,
) -> dict:
    """Split Search Console clicks and impressions into query buckets by regex.

    Buckets: brand / non-brand (needs ``brand_regex``), question, and query
    length (1, 2-3, 4-6, 7+ words). Each bucket is one dimensionless query
    with a query regex filter, so totals are exact for the filter. Anonymized
    queries never match a query filter, so bucket totals do not add up to the
    site total; the gap is reported as ``anonymized_or_unmatched``.
    """
    result = {
        "property": site_url,
        "report": "query_buckets",
        "site_totals": None,
        "buckets": [],
        "regex": {"question": QUESTION_REGEX, "length": dict(LENGTH_BUCKETS)},
        "warnings": [],
        "error": None,
    }
    if brand_regex:
        result["regex"]["brand"] = brand_regex
    else:
        result["warnings"].append(
            "No --brand-regex given: brand / non-brand split skipped. Pass the brand "
            "name, misspellings and product names, e.g. (?i)acme|acmee|acme ?widgets."
        )

    service = _build_gsc_service()
    if not service:
        result["error"] = "Could not build GSC service. Check service account credentials."
        return result

    if not start_date:
        start_date = (datetime.now() - timedelta(days=28)).strftime("%Y-%m-%d")
    if not end_date:
        end_date = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    result["date_range"] = {"start": start_date, "end": end_date}
    if _date_range_overlaps(start_date, end_date, GSC_ANOMALY_START, GSC_ANOMALY_END):
        result["warnings"].append(GSC_ANOMALY_WARNING)

    site_totals = _query_site_totals(
        service, site_url, start_date, end_date, search_type, data_state, None
    )
    if site_totals is None:
        result["error"] = (
            f"Site totals query failed for '{site_url}'. Check access with "
            "`gsc_query.py sites` (siteUnverifiedUser = access lost)."
        )
        return result
    result["site_totals"] = site_totals

    specs = []
    if brand_regex:
        specs.append(("brand", "brand", "includingRegex", brand_regex))
        specs.append(("brand", "non-brand", "excludingRegex", brand_regex))
    specs.append(("question", "question", "includingRegex", QUESTION_REGEX))
    for label, pattern in LENGTH_BUCKETS:
        specs.append(("length", label, "includingRegex", pattern))

    for group, label, operator, pattern in specs:
        filters = [{"dimension": "query", "operator": operator, "expression": pattern}]
        totals = _query_site_totals(
            service, site_url, start_date, end_date, search_type, data_state, filters
        )
        bucket = {"group": group, "bucket": label, "operator": operator, "totals": totals}
        if totals is None:
            bucket["error"] = "Bucket query failed (check the regex is valid RE2)."
        else:
            site_clicks = site_totals.get("clicks") or 0
            site_impr = site_totals.get("impressions") or 0
            bucket["click_share"] = (
                round(totals["clicks"] / site_clicks * 100, 1) if site_clicks else None
            )
            bucket["impression_share"] = (
                round(totals["impressions"] / site_impr * 100, 1) if site_impr else None
            )
        if sample > 0 and totals is not None:
            body = {
                "startDate": start_date,
                "endDate": end_date,
                "dimensions": ["query"],
                "type": search_type,
                "rowLimit": sample,
                "dataState": data_state,
                "dimensionFilterGroups": [{"filters": filters}],
            }
            try:
                response = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
                bucket["sample_queries"] = [
                    {"query": (row.get("keys") or [""])[0], "clicks": row.get("clicks", 0),
                     "impressions": row.get("impressions", 0)}
                    for row in response.get("rows", [])
                ]
            except Exception:
                bucket["sample_queries"] = []
        result["buckets"].append(bucket)

    length_rows = [b for b in result["buckets"] if b["group"] == "length" and b["totals"]]
    if length_rows:
        matched_clicks = sum(b["totals"]["clicks"] for b in length_rows)
        matched_impr = sum(b["totals"]["impressions"] for b in length_rows)
        result["anonymized_or_unmatched"] = {
            "clicks": max(0, site_totals["clicks"] - matched_clicks),
            "impressions": max(0, site_totals["impressions"] - matched_impr),
            "note": (
                "Site total minus the sum of the length buckets (which together "
                "cover every named query). The remainder is anonymized queries."
            ),
        }
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Google Search Console Search Analytics query helper"
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="query",
        choices=["query", "buckets", "sitemaps", "sites"],
        help="Command: query (default), buckets, sitemaps, sites",
    )
    parser.add_argument(
        "--property", "-p",
        help="GSC property (e.g., sc-domain:example.com). Uses default from config if not specified.",
    )
    parser.add_argument("--days", "-d", type=int, default=28, help="Number of days (default: 28)")
    parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--dimensions",
        default="query,page",
        help="Comma-separated dimensions (default: query,page)",
    )
    parser.add_argument("--type", default="web", help="Search type (default: web)")
    parser.add_argument("--limit", type=int, default=1000, help="Row limit (default: 1000)")
    parser.add_argument(
        "--device",
        choices=["desktop", "mobile", "tablet"],
        help="Filter by device type",
    )
    parser.add_argument("--country", help="Filter by country (ISO 3166-1 alpha-3, e.g., USA)")
    parser.add_argument(
        "--filter",
        action="append",
        default=[],
        metavar="DIM:OPERATOR:EXPRESSION",
        help=(
            "Extra filter, repeatable. Operators: equals, notEquals, contains, "
            "notContains, includingRegex, excludingRegex (RE2; add (?i) for "
            "case-insensitive). Example: query:includingRegex:(?i)^how"
        ),
    )
    parser.add_argument(
        "--brand-regex",
        help="buckets: RE2 regex for brand queries, e.g. (?i)acme|acmee",
    )
    parser.add_argument(
        "--sample", type=int, default=5,
        help="buckets: top queries to show per bucket (default: 5, 0 = none)",
    )
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    # Resolve property
    prop = args.property
    property_source = "argument"
    if not prop:
        config = load_config()
        prop = config.get("default_property")
        property_source = "config_default"
    if not prop and args.command != "sites":
        print("Error: No property specified. Use --property or set default_property in config.", file=sys.stderr)
        sys.exit(1)

    if args.command == "sites":
        result = list_sites()
    elif args.command == "sitemaps":
        result = list_sitemaps(prop)
    elif args.command == "buckets":
        start = args.start_date or (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
        end = args.end_date or (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        result = query_buckets(
            prop, brand_regex=args.brand_regex, start_date=start, end_date=end,
            search_type=args.type, sample=max(0, args.sample),
        )
    else:
        start = args.start_date or (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
        end = args.end_date or (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        try:
            dims = _parse_dimensions(args.dimensions)
        except ValueError as exc:
            parser.error(str(exc))
        filters = []
        if args.device:
            filters.append({
                "dimension": "device",
                "operator": "equals",
                "expression": args.device.upper(),
            })
        if args.country:
            filters.append({
                "dimension": "country",
                "operator": "equals",
                "expression": args.country.upper(),
            })
        for raw in args.filter:
            try:
                filters.append(_parse_filter(raw))
            except ValueError as exc:
                parser.error(str(exc))
        result = query_search_analytics(
            prop, start_date=start, end_date=end,
            dimensions=dims, search_type=args.type, row_limit=args.limit,
            filters=filters if filters else None,
        )

    if args.command != "sites":
        result["property_source"] = property_source
        if property_source == "config_default":
            result.setdefault("warnings", []).append(
                f"Property '{prop}' came from default_property in the config, not from "
                "--property. Pass --property on every run so one client's data is "
                "never reported as another's."
            )

    if result.get("error"):
        print(f"Error: {result['error']}", file=sys.stderr)
        if not args.json:
            sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if args.command == "sites":
            print("=== Verified GSC Properties ===")
            for site in result.get("sites", []):
                flag = "  <- ACCESS LOST" if not site.get("has_data_access", True) else ""
                print(f"  {site['url']} ({site['permission']}){flag}")
        elif args.command == "buckets":
            print(f"=== Query buckets: {prop} ===")
            dr = result.get("date_range", {})
            print(f"Period: {dr.get('start')} to {dr.get('end')}")
            for warning in result.get("warnings", []):
                print(f"Warning: {warning}")
            site = result.get("site_totals") or {}
            print(f"Site: {site.get('clicks', 0):,} clicks | {site.get('impressions', 0):,} impressions")
            for b in result.get("buckets", []):
                t = b.get("totals") or {}
                print(
                    f"  {b['group']:<8} {b['bucket']:<10} {t.get('clicks', 0):>8,} clicks "
                    f"({b.get('click_share')}%) | {t.get('impressions', 0):>10,} imp "
                    f"({b.get('impression_share')}%)"
                )
            gap = result.get("anonymized_or_unmatched")
            if gap:
                print(f"  Anonymized: {gap['clicks']:,} clicks | {gap['impressions']:,} imp")
        elif args.command == "sitemaps":
            print(f"=== Sitemaps for {prop} ===")
            for sm in result.get("sitemaps", []):
                status = "pending" if sm.get("is_pending") else "processed"
                print(f"  {sm['path']} [{status}] errors={sm.get('errors', 0)} warnings={sm.get('warnings', 0)}")
            if result.get("sitemaps"):
                print(f"\nNote: {INDEXATION_NOTE}")
        else:
            totals = result.get("totals", {})
            print(f"=== Search Analytics: {prop} ===")
            print(f"Period: {result.get('date_range', {}).get('start')} to {result.get('date_range', {}).get('end')}")
            for warning in result.get("warnings", []):
                print(f"Warning: {warning}")
            print(f"Clicks: {totals.get('clicks', 0):,} | Impressions: {totals.get('impressions', 0):,} | CTR: {totals.get('ctr', 0)}% | Rows: {result.get('row_count', 0)}")

            qw = result.get("quick_wins", [])
            if qw:
                print(f"\nQuick Wins ({len(qw)} found):")
                for w in qw[:10]:
                    keys = " | ".join(w.get("keys", []))
                    print(f"  Pos {w['position']} | {w['impressions']:,} imp | {w['clicks']} clicks | {keys}")


if __name__ == "__main__":
    main()
