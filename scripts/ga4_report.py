#!/usr/bin/env python3
"""
GA4 Data API v1beta - traffic, AI Assistant, key event and site search reports.

Queries the Google Analytics Data API for channel traffic (Organic Search by
default), top landing pages, key events by landing page and channel, the
AI Assistant channel by landing page, and site search terms.

Usage:
    python ga4_report.py --property 123456789
    python ga4_report.py --property 123456789 --days 90 --report top-pages
    python ga4_report.py --property 123456789 --report top-pages --channel "Paid Search"
    python ga4_report.py --property 123456789 --report ai-assistant --json
    python ga4_report.py --property 123456789 --report key-events --key-event purchase
    python ga4_report.py --property 123456789 --report search-terms --json

Joining to Search Console: GA4 ``landingPage`` is a path without host or query
string, "/about" and "/about/" are separate rows, and sessions without a page
view land in "(not set)". Every landing-page row carries ``page_key`` (path,
no query string, no trailing slash) for joining; "(not set)" is counted
separately and never joined.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from typing import Optional

try:
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        DateRange,
        Dimension,
        Filter,
        FilterExpression,
        FilterExpressionList,
        Metric,
        OrderBy,
        RunReportRequest,
    )
except ImportError:
    print(
        "Error: google-analytics-data required. "
        "Install with: pip install google-analytics-data",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    from google_auth import describe_google_error, get_oauth_credentials, load_config
except ImportError:
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from google_auth import describe_google_error, get_oauth_credentials, load_config

GA4_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
DEFAULT_CHANNEL = "Organic Search"
# GA4 Default Channel Group for sessions from recognised AI assistants
# (medium exactly "ai-assistant"). It excludes AI Overviews and AI Mode.
AI_ASSISTANT_CHANNEL = "AI Assistant"
NOT_SET = "(not set)"
ALL_CHANNELS = {"", "all", "any", "none"}


def _build_ga4_client():
    """Build the GA4 BetaAnalyticsDataClient."""
    credentials = get_oauth_credentials(GA4_SCOPES)
    if not credentials:
        return None
    try:
        return BetaAnalyticsDataClient(credentials=credentials)
    except Exception as e:
        print(f"Error building GA4 client: {e}", file=sys.stderr)
        return None


def _resolve_property(property_id: str) -> str:
    """Ensure property ID is in the correct format."""
    if not property_id:
        return ""
    if property_id.startswith("properties/"):
        return property_id
    return f"properties/{property_id}"


def _date_range(days: int) -> tuple[str, str]:
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    end_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    return start_date, end_date


def _exact_filter(field_name: str, value: str) -> FilterExpression:
    return FilterExpression(
        filter=Filter(
            field_name=field_name,
            string_filter=Filter.StringFilter(
                match_type=Filter.StringFilter.MatchType.EXACT,
                value=value,
            ),
        )
    )


def _channel_filter(channel: Optional[str]) -> Optional[FilterExpression]:
    """Return a sessionDefaultChannelGroup filter, or None for all channels."""
    if channel is None or channel.strip().lower() in ALL_CHANNELS:
        return None
    return _exact_filter("sessionDefaultChannelGroup", channel)


def _request(prop: str, dimensions: list, metrics: list, start: str, end: str,
             dimension_filter=None, order_bys=None, limit: int = 0,
             quota: bool = False) -> RunReportRequest:
    kwargs = {
        "property": prop,
        "dimensions": [Dimension(name=d) for d in dimensions],
        "metrics": [Metric(name=m) for m in metrics],
        "date_ranges": [DateRange(start_date=start, end_date=end)],
    }
    if dimension_filter is not None:
        kwargs["dimension_filter"] = dimension_filter
    if order_bys:
        kwargs["order_bys"] = order_bys
    if limit:
        kwargs["limit"] = limit
    if quota:
        kwargs["return_property_quota"] = True
    return RunReportRequest(**kwargs)


def _order_by_metric(name: str) -> list:
    return [OrderBy(metric=OrderBy.MetricOrderBy(metric_name=name), desc=True)]


def _quota(response) -> Optional[dict]:
    pq = getattr(response, "property_quota", None)
    if not pq:
        return None
    return {
        "daily_consumed": pq.tokens_per_day.consumed if pq.tokens_per_day else None,
        "daily_remaining": pq.tokens_per_day.remaining if pq.tokens_per_day else None,
        "hourly_consumed": pq.tokens_per_hour.consumed if pq.tokens_per_hour else None,
        "hourly_remaining": pq.tokens_per_hour.remaining if pq.tokens_per_hour else None,
    }


def _error_message(exc: Exception, property_id: str) -> tuple[str, dict]:
    """Turn a GA4 API exception into a diagnosis by reason and consumer."""
    info = describe_google_error(exc, resource=f"GA4 property '{property_id}'")
    if info["status"] == 404 or "NOT_FOUND" in str(exc):
        return (
            f"Property '{property_id}' not found. "
            "Verify the numeric property ID in GA4 Admin > Property Details.",
            info,
        )
    if info["status"] == 403 or "PERMISSION_DENIED" in str(exc):
        return (
            f"GA4 403 for property '{property_id}' (reason {info['reason'] or 'unknown'}, "
            f"consumer {info['consumer'] or 'unknown'}): {info['diagnosis']}",
            info,
        )
    return f"GA4 API error: {info['message']}", info


def normalize_landing_page(value: str) -> Optional[str]:
    """Join key for a GA4 landingPage value: path only, no query, no trailing slash.

    Returns None for "(not set)" and empty values, which must not be joined.
    """
    if not value or value.strip() == NOT_SET:
        return None
    path = value.strip().split("#", 1)[0].split("?", 1)[0]
    if "://" in path:
        # A full URL (e.g. a GSC page) reduces to its path for the same key.
        rest = path.split("://", 1)[1]
        path = "/" + rest.split("/", 1)[1] if "/" in rest else "/"
    if not path.startswith("/"):
        path = "/" + path
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    return path


def _landing_page_notes(rows: list, sessions_key: str = "sessions") -> dict:
    """Summarise (not set) sessions and trailing-slash / query-string variants."""
    not_set = sum(r.get(sessions_key, 0) for r in rows if r.get("page_key") is None)
    total = sum(r.get(sessions_key, 0) for r in rows)
    variants: dict = {}
    for r in rows:
        if r.get("page_key"):
            variants.setdefault(r["page_key"], set()).add(r.get("landing_page"))
    multi = sorted(k for k, v in variants.items() if len(v) > 1)
    return {
        "not_set_sessions": not_set,
        "not_set_share": round(not_set / total * 100, 1) if total else 0.0,
        "page_keys_with_variants": multi[:20],
        "join_rule": (
            "Join to Search Console on page_key (GSC page URL reduced to its path, "
            "no query string, no trailing slash). Never join '(not set)'."
        ),
    }


def organic_traffic_report(
    property_id: str,
    days: int = 28,
    limit: int = 100,
    channel: Optional[str] = DEFAULT_CHANNEL,
) -> dict:
    """
    Generate a channel traffic report from GA4 (Organic Search by default).

    Filters by sessionDefaultChannelGroup == channel and returns daily
    sessions, top landing pages (with key events), and key metrics.

    Args:
        property_id: GA4 property ID (numeric or 'properties/123456789').
        days: Number of days to query (default: 28).
        limit: Max rows (default: 100).
        channel: Default Channel Group name, or "all" for no filter.

    Returns:
        Dictionary with daily_data, top_pages, totals, and quota usage.
    """
    result = {
        "property": property_id,
        "report": "organic_traffic",
        "channel": channel or "all",
        "date_range": None,
        "totals": {},
        "daily_data": [],
        "top_pages": [],
        "quota_tokens_used": None,
        "error": None,
    }

    client = _build_ga4_client()
    if not client:
        result["error"] = (
            "Could not build GA4 client. Ensure the service account has "
            "Viewer access in GA4 Admin > Property Access Management."
        )
        return result

    prop = _resolve_property(property_id)
    start_date, end_date = _date_range(days)
    result["date_range"] = {"start": start_date, "end": end_date}
    channel_filter = _channel_filter(channel)

    # Daily sessions
    try:
        daily_request = _request(
            prop, ["date"],
            ["sessions", "totalUsers", "screenPageViews", "bounceRate",
             "averageSessionDuration", "engagementRate"],
            start_date, end_date, dimension_filter=channel_filter,
            order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name="date"))],
            limit=days + 5, quota=True,
        )
        daily_response = client.run_report(daily_request)

        for row in daily_response.rows:
            result["daily_data"].append({
                "date": row.dimension_values[0].value,
                "sessions": int(row.metric_values[0].value),
                "users": int(row.metric_values[1].value),
                "pageviews": int(row.metric_values[2].value),
                "bounce_rate": round(float(row.metric_values[3].value) * 100, 1),
                "avg_session_duration": round(float(row.metric_values[4].value), 1),
                "engagement_rate": round(float(row.metric_values[5].value) * 100, 1),
            })
        result["quota_tokens_used"] = _quota(daily_response)

    except Exception as e:
        result["error"], result["error_detail"] = _error_message(e, property_id)
        return result

    # Top landing pages by sessions
    try:
        pages_request = _request(
            prop, ["landingPage"],
            ["sessions", "totalUsers", "screenPageViews", "bounceRate",
             "engagementRate", "keyEvents"],
            start_date, end_date, dimension_filter=channel_filter,
            order_bys=_order_by_metric("sessions"), limit=limit,
        )
        pages_response = client.run_report(pages_request)

        for row in pages_response.rows:
            page = row.dimension_values[0].value
            result["top_pages"].append({
                "landing_page": page,
                "page_key": normalize_landing_page(page),
                "sessions": int(row.metric_values[0].value),
                "users": int(row.metric_values[1].value),
                "pageviews": int(row.metric_values[2].value),
                "bounce_rate": round(float(row.metric_values[3].value) * 100, 1),
                "engagement_rate": round(float(row.metric_values[4].value) * 100, 1),
                "key_events": round(float(row.metric_values[5].value), 2),
            })
        result["landing_page_notes"] = _landing_page_notes(result["top_pages"])

    except Exception as e:
        # Non-fatal: daily data succeeded, pages failed
        result["pages_error"] = f"Error fetching top pages: {e}"

    # Calculate totals
    if result["daily_data"]:
        total_sessions = sum(d["sessions"] for d in result["daily_data"])
        total_users = sum(d["users"] for d in result["daily_data"])
        total_pageviews = sum(d["pageviews"] for d in result["daily_data"])
        result["totals"] = {
            "sessions": total_sessions,
            "users": total_users,
            "pageviews": total_pageviews,
            "avg_daily_sessions": round(total_sessions / len(result["daily_data"]), 1),
        }

    return result


def top_pages_report(
    property_id: str,
    days: int = 28,
    limit: int = 50,
    channel: Optional[str] = DEFAULT_CHANNEL,
) -> dict:
    """
    Get top landing pages for a channel (Organic Search by default) from GA4.

    Args:
        property_id: GA4 property ID.
        days: Number of days.
        limit: Max pages to return.
        channel: Default Channel Group name, or "all".

    Returns:
        Dictionary with top pages ranked by sessions.
    """
    report = organic_traffic_report(property_id, days, limit, channel=channel)
    channel_sessions = report.get("totals", {}).get("sessions", 0)
    return {
        "property": property_id,
        "report": "top_organic_pages",
        "channel": report.get("channel"),
        "date_range": report.get("date_range"),
        "pages": report.get("top_pages", []),
        "landing_page_notes": report.get("landing_page_notes"),
        "total_organic_sessions": channel_sessions,
        "total_channel_sessions": channel_sessions,
        "quota_tokens_used": report.get("quota_tokens_used"),
        "error": report.get("error"),
    }


def device_breakdown(
    property_id: str,
    days: int = 28,
    channel: Optional[str] = DEFAULT_CHANNEL,
) -> dict:
    """
    Sessions for a channel (Organic Search by default) by device category.

    Args:
        property_id: GA4 property ID.
        days: Number of days.
        channel: Default Channel Group name, or "all".

    Returns:
        Dictionary with device breakdown data.
    """
    result = {"property": property_id, "report": "device_breakdown",
              "channel": channel or "all", "devices": [], "error": None}

    client = _build_ga4_client()
    if not client:
        result["error"] = "Could not build GA4 client."
        return result

    prop = _resolve_property(property_id)
    start_date, end_date = _date_range(days)
    result["date_range"] = {"start": start_date, "end": end_date}

    try:
        request = _request(
            prop, ["deviceCategory"],
            ["sessions", "totalUsers", "bounceRate", "engagementRate"],
            start_date, end_date, dimension_filter=_channel_filter(channel),
            order_bys=_order_by_metric("sessions"),
        )
        response = client.run_report(request)
        for row in response.rows:
            result["devices"].append({
                "category": row.dimension_values[0].value,
                "sessions": int(row.metric_values[0].value),
                "users": int(row.metric_values[1].value),
                "bounce_rate": round(float(row.metric_values[2].value) * 100, 1),
                "engagement_rate": round(float(row.metric_values[3].value) * 100, 1),
            })
    except Exception as e:
        result["error"], result["error_detail"] = _error_message(e, property_id)

    return result


def country_breakdown(
    property_id: str,
    days: int = 28,
    limit: int = 20,
    channel: Optional[str] = DEFAULT_CHANNEL,
) -> dict:
    """
    Sessions for a channel (Organic Search by default) by country.

    Args:
        property_id: GA4 property ID.
        days: Number of days.
        limit: Max countries to return.
        channel: Default Channel Group name, or "all".

    Returns:
        Dictionary with country breakdown data.
    """
    result = {"property": property_id, "report": "country_breakdown",
              "channel": channel or "all", "countries": [], "error": None}

    client = _build_ga4_client()
    if not client:
        result["error"] = "Could not build GA4 client."
        return result

    prop = _resolve_property(property_id)
    start_date, end_date = _date_range(days)
    result["date_range"] = {"start": start_date, "end": end_date}

    try:
        request = _request(
            prop, ["country"], ["sessions", "totalUsers"],
            start_date, end_date, dimension_filter=_channel_filter(channel),
            order_bys=_order_by_metric("sessions"), limit=limit,
        )
        response = client.run_report(request)
        for row in response.rows:
            result["countries"].append({
                "country": row.dimension_values[0].value,
                "sessions": int(row.metric_values[0].value),
                "users": int(row.metric_values[1].value),
            })
    except Exception as e:
        result["error"], result["error_detail"] = _error_message(e, property_id)

    return result


def ai_assistant_report(
    property_id: str,
    days: int = 28,
    limit: int = 50,
    channel: Optional[str] = AI_ASSISTANT_CHANNEL,
) -> dict:
    """
    AI Assistant channel sessions by landing page and source.

    The channel counts sessions GA4 attributes to recognised assistants
    (medium "ai-assistant"). It excludes AI Overviews / AI Mode, has no
    backfill, and undercounts: referrer-less assistant visits land in Direct.

    Returns:
        Dictionary with rows (landing page x source), per-page totals and notes.
    """
    result = {
        "property": property_id,
        "report": "ai_assistant_landing_pages",
        "channel": channel,
        "rows": [],
        "pages": [],
        "totals": {},
        "caveats": [
            "Counts only sessions GA4 attributes to recognised assistants; "
            "referrer-less assistant visits are in Direct.",
            "Excludes Google AI Overviews and AI Mode (those sit in Organic Search).",
            "Forward-only channel: zero before it went live is not zero AI traffic.",
        ],
        "error": None,
    }
    client = _build_ga4_client()
    if not client:
        result["error"] = "Could not build GA4 client."
        return result

    prop = _resolve_property(property_id)
    start_date, end_date = _date_range(days)
    result["date_range"] = {"start": start_date, "end": end_date}

    try:
        request = _request(
            prop, ["landingPage", "sessionSource"],
            ["sessions", "engagedSessions", "keyEvents"],
            start_date, end_date, dimension_filter=_channel_filter(channel),
            order_bys=_order_by_metric("sessions"), limit=limit, quota=True,
        )
        response = client.run_report(request)
        result["total_rows"] = getattr(response, "row_count", None)
        result["truncated"] = bool(result["total_rows"] and result["total_rows"] > limit)
        result["quota_tokens_used"] = _quota(response)
        pages: dict = {}
        for row in response.rows:
            page = row.dimension_values[0].value
            entry = {
                "landing_page": page,
                "page_key": normalize_landing_page(page),
                "source": row.dimension_values[1].value,
                "sessions": int(row.metric_values[0].value),
                "engaged_sessions": int(row.metric_values[1].value),
                "key_events": round(float(row.metric_values[2].value), 2),
            }
            result["rows"].append(entry)
            agg = pages.setdefault(entry["page_key"] or NOT_SET, {
                "page_key": entry["page_key"], "sessions": 0,
                "engaged_sessions": 0, "key_events": 0.0, "sources": set(),
            })
            agg["sessions"] += entry["sessions"]
            agg["engaged_sessions"] += entry["engaged_sessions"]
            agg["key_events"] += entry["key_events"]
            agg["sources"].add(entry["source"])
        result["pages"] = sorted(
            ({**v, "sources": sorted(v["sources"])} for v in pages.values()),
            key=lambda p: p["sessions"], reverse=True,
        )
        result["totals"] = {
            "sessions": sum(r["sessions"] for r in result["rows"]),
            "engaged_sessions": sum(r["engaged_sessions"] for r in result["rows"]),
            "key_events": round(sum(r["key_events"] for r in result["rows"]), 2),
        }
        result["landing_page_notes"] = _landing_page_notes(result["rows"])
    except Exception as e:
        result["error"], result["error_detail"] = _error_message(e, property_id)

    return result


def key_events_report(
    property_id: str,
    days: int = 28,
    limit: int = 100,
    key_event: Optional[str] = None,
    channel: Optional[str] = None,
) -> dict:
    """
    Key events by landing page and session default channel group.

    Args:
        key_event: One key event name (e.g. "purchase"); None = all key events.
        channel: Restrict to one channel; None = every channel as a dimension.

    Returns:
        Dictionary with rows (landing page x channel) and per-channel totals.
    """
    metric = f"keyEvents:{key_event}" if key_event else "keyEvents"
    rate = f"sessionKeyEventRate:{key_event}" if key_event else "sessionKeyEventRate"
    result = {
        "property": property_id,
        "report": "key_events_by_landing_page_and_channel",
        "key_event": key_event or "all key events",
        "channel": channel or "all",
        "rows": [],
        "channels": [],
        "error": None,
    }
    client = _build_ga4_client()
    if not client:
        result["error"] = "Could not build GA4 client."
        return result

    prop = _resolve_property(property_id)
    start_date, end_date = _date_range(days)
    result["date_range"] = {"start": start_date, "end": end_date}

    try:
        request = _request(
            prop, ["landingPage", "sessionDefaultChannelGroup"],
            ["sessions", metric, rate],
            start_date, end_date, dimension_filter=_channel_filter(channel),
            order_bys=_order_by_metric(metric), limit=limit, quota=True,
        )
        response = client.run_report(request)
        result["total_rows"] = getattr(response, "row_count", None)
        result["truncated"] = bool(result["total_rows"] and result["total_rows"] > limit)
        result["quota_tokens_used"] = _quota(response)
        by_channel: dict = {}
        for row in response.rows:
            page = row.dimension_values[0].value
            entry = {
                "landing_page": page,
                "page_key": normalize_landing_page(page),
                "channel": row.dimension_values[1].value,
                "sessions": int(row.metric_values[0].value),
                "key_events": round(float(row.metric_values[1].value), 2),
                "session_key_event_rate": round(float(row.metric_values[2].value) * 100, 2),
            }
            result["rows"].append(entry)
            agg = by_channel.setdefault(entry["channel"], {"channel": entry["channel"],
                                                           "sessions": 0, "key_events": 0.0})
            agg["sessions"] += entry["sessions"]
            agg["key_events"] += entry["key_events"]
        result["channels"] = sorted(by_channel.values(), key=lambda c: c["key_events"], reverse=True)
        result["landing_page_notes"] = _landing_page_notes(result["rows"])
        if not any(r["key_events"] for r in result["rows"]):
            result["warnings"] = [
                "Zero key events in the period. Check GA4 Admin > Key events: no event "
                "may be marked as a key event, or the named event does not exist."
            ]
    except Exception as e:
        result["error"], result["error_detail"] = _error_message(e, property_id)

    return result


def search_terms_report(
    property_id: str,
    days: int = 28,
    limit: int = 100,
    channel: Optional[str] = None,
) -> dict:
    """
    Site search terms from the GA4 ``searchTerm`` dimension.

    ``searchTerm`` is filled by view_search_results events (Enhanced
    measurement > Site search). Empty output usually means site search
    tracking is off or the site uses a query parameter GA4 does not watch.
    """
    result = {
        "property": property_id,
        "report": "site_search_terms",
        "channel": channel or "all",
        "terms": [],
        "error": None,
    }
    client = _build_ga4_client()
    if not client:
        result["error"] = "Could not build GA4 client."
        return result

    prop = _resolve_property(property_id)
    start_date, end_date = _date_range(days)
    result["date_range"] = {"start": start_date, "end": end_date}

    event_filter = _exact_filter("eventName", "view_search_results")
    channel_filter = _channel_filter(channel)
    if channel_filter is not None:
        dimension_filter = FilterExpression(
            and_group=FilterExpressionList(expressions=[event_filter, channel_filter])
        )
    else:
        dimension_filter = event_filter

    try:
        request = _request(
            prop, ["searchTerm"], ["eventCount", "totalUsers"],
            start_date, end_date, dimension_filter=dimension_filter,
            order_bys=_order_by_metric("eventCount"), limit=limit, quota=True,
        )
        response = client.run_report(request)
        result["total_rows"] = getattr(response, "row_count", None)
        result["quota_tokens_used"] = _quota(response)
        not_set = 0
        for row in response.rows:
            term = row.dimension_values[0].value
            count = int(row.metric_values[0].value)
            if term in ("", NOT_SET):
                not_set += count
                continue
            result["terms"].append({
                "term": term,
                "searches": count,
                "users": int(row.metric_values[1].value),
            })
        result["not_set_searches"] = not_set
        if not result["terms"]:
            result["warnings"] = [
                "No site search terms. Check GA4 Admin > Data streams > Enhanced "
                "measurement > Site search, and the search query parameter the site uses."
            ]
    except Exception as e:
        result["error"], result["error_detail"] = _error_message(e, property_id)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="GA4 Data API - channel traffic, AI Assistant, key events, site search"
    )
    parser.add_argument(
        "--property", "-p",
        help=(
            "GA4 property ID (numeric, e.g., 123456789). Pass it on every run: "
            "the config default is a fallback and is flagged in the output."
        ),
    )
    parser.add_argument("--days", "-d", type=int, default=28, help="Number of days (default: 28)")
    parser.add_argument(
        "--report", "-r",
        choices=["organic", "top-pages", "device", "country",
                 "ai-assistant", "key-events", "search-terms"],
        default="organic",
        help="Report type (default: organic)",
    )
    parser.add_argument(
        "--channel",
        help=(
            "Session default channel group to filter on, or 'all'. Defaults: "
            "'Organic Search' for organic/top-pages/device/country, "
            "'AI Assistant' for ai-assistant, all channels for key-events/search-terms."
        ),
    )
    parser.add_argument(
        "--key-event",
        help="key-events: one key event name (e.g. purchase); default all key events",
    )
    parser.add_argument("--limit", type=int, default=50, help="Max rows (default: 50)")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    # Resolve property
    prop = args.property
    property_source = "argument"
    if not prop:
        config = load_config()
        prop = config.get("ga4_property_id") or ""
        property_source = "config_default"
        # Strip 'properties/' prefix if present for consistency
        if prop and prop.startswith("properties/"):
            prop = prop[len("properties/"):]
    if not prop:
        print(
            "Error: No GA4 property specified. Use --property or set ga4_property_id in config.",
            file=sys.stderr,
        )
        sys.exit(1)

    channel = args.channel
    if args.report == "top-pages":
        result = top_pages_report(prop, args.days, args.limit,
                                  channel=channel or DEFAULT_CHANNEL)
    elif args.report == "device":
        result = device_breakdown(prop, args.days, channel=channel or DEFAULT_CHANNEL)
    elif args.report == "country":
        result = country_breakdown(prop, args.days, args.limit,
                                   channel=channel or DEFAULT_CHANNEL)
    elif args.report == "ai-assistant":
        result = ai_assistant_report(prop, args.days, args.limit,
                                     channel=channel or AI_ASSISTANT_CHANNEL)
    elif args.report == "key-events":
        result = key_events_report(prop, args.days, args.limit,
                                   key_event=args.key_event, channel=channel)
    elif args.report == "search-terms":
        result = search_terms_report(prop, args.days, args.limit, channel=channel)
    else:
        result = organic_traffic_report(prop, args.days, args.limit,
                                        channel=channel or DEFAULT_CHANNEL)

    result["property_source"] = property_source
    if property_source == "config_default":
        result.setdefault("warnings", []).append(
            f"GA4 property {prop} came from ga4_property_id in the config, not from "
            "--property. Pass --property (and the matching GSC --property) on every "
            "run so one client's data is never reported as another's."
        )

    if result.get("error"):
        print(f"Error: {result['error']}", file=sys.stderr)
        if not args.json:
            sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return

    for warning in result.get("warnings", []):
        print(f"Warning: {warning}")
    dr = result.get("date_range") or {}
    period = f"Period: {dr.get('start')} to {dr.get('end')}"
    if args.report == "top-pages":
        print(f"=== Top Landing Pages ({result.get('channel')}) ===")
        print(f"Property: {prop} | {period}")
        print(f"Total sessions: {result.get('total_channel_sessions', 0):,}")
        print()
        for i, page in enumerate(result.get("pages", [])[:20], 1):
            print(f"  {i:2d}. {page['landing_page']}")
            print(f"      Sessions: {page['sessions']:,} | Users: {page['users']:,} | "
                  f"Bounce: {page['bounce_rate']}% | Key events: {page['key_events']}")
    elif args.report == "ai-assistant":
        print(f"=== AI Assistant channel by landing page | {prop} | {period} ===")
        totals = result.get("totals", {})
        print(f"Sessions: {totals.get('sessions', 0):,} | Key events: {totals.get('key_events', 0)}")
        for p in result.get("pages", [])[:20]:
            print(f"  {p['page_key'] or NOT_SET}: {p['sessions']:,} sessions "
                  f"({', '.join(p['sources'])})")
    elif args.report == "key-events":
        print(f"=== Key events ({result.get('key_event')}) by landing page and channel | {period} ===")
        for c in result.get("channels", []):
            print(f"  {c['channel']}: {c['key_events']} key events / {c['sessions']:,} sessions")
        for r in result.get("rows", [])[:20]:
            print(f"  {r['landing_page']} [{r['channel']}] {r['key_events']} "
                  f"({r['session_key_event_rate']}% of sessions)")
    elif args.report == "search-terms":
        print(f"=== Site search terms | {prop} | {period} ===")
        for t in result.get("terms", [])[:30]:
            print(f"  {t['searches']:>6,}  {t['term']}")
    elif args.report in ("device", "country"):
        key = "devices" if args.report == "device" else "countries"
        name = "category" if args.report == "device" else "country"
        print(f"=== {args.report.title()} breakdown ({result.get('channel')}) | {period} ===")
        for r in result.get(key, []):
            print(f"  {r[name]}: {r['sessions']:,} sessions")
    else:
        totals = result.get("totals", {})
        print(f"=== GA4 Traffic Report ({result.get('channel')}) ===")
        print(f"Property: {prop}")
        print(period)
        print(f"\nSessions: {totals.get('sessions', 0):,} | Users: {totals.get('users', 0):,} | Pageviews: {totals.get('pageviews', 0):,}")
        print(f"Avg Daily Sessions: {totals.get('avg_daily_sessions', 0):,.0f}")

        quota = result.get("quota_tokens_used")
        if quota and quota.get("daily_remaining") is not None:
            print(f"\nQuota: {quota['daily_consumed']} tokens used / {quota['daily_remaining']} remaining (daily)")

        pages = result.get("top_pages", [])
        if pages:
            print(f"\nTop {min(10, len(pages))} Landing Pages:")
            for i, page in enumerate(pages[:10], 1):
                print(f"  {i:2d}. {page['landing_page']} ({page['sessions']:,} sessions)")


if __name__ == "__main__":
    main()
