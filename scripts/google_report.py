#!/usr/bin/env python3
"""
Google SEO Report Generator - Professional PDF/HTML reports from API data.

Consumes JSON output from seo-google scripts and generates formatted reports
with charts, analytics, and actionable recommendations.

Usage:
    python google_report.py --type cwv-audit --data cwv-data.json --domain example.com
    python google_report.py --type gsc-performance --data gsc-data.json --domain example.com
    python google_report.py --type indexation --data inspect-data.json --domain example.com
    python google_report.py --type full --data full-data.json --domain example.com
    cat data.json | python google_report.py --type cwv-audit --domain example.com
"""

import argparse
import json
import os
import sys
from datetime import datetime
from html import escape
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt
    import numpy as np
    _CHART_IMPORT_ERROR = None
except (ImportError, OSError, RuntimeError) as exc:
    matplotlib = plt = mpatches = np = None
    _CHART_IMPORT_ERROR = exc

try:
    from weasyprint import HTML
    _PDF_IMPORT_ERROR = None
except (ImportError, OSError) as exc:
    HTML = None
    _PDF_IMPORT_ERROR = exc


# ─── Brand Tokens (Engine Room) ──────────────────────────────────────────────
#
# Paper #F2F2F2, ink #0F0F0F, single accent #FF5722, white cards with hairline
# borders and 2-4px corners. Status colours (pass / warn / fail) stay
# functional and are kept visually distinct from the orange accent.

BRAND = {
    "primary": "#0F0F0F",      # Ink (headings, primary chart series)
    "secondary": "#4A4A4A",    # Grey 700
    "accent": "#FF5722",       # Engine Room orange (eyebrows, rules, highlights)
    "success": "#2E7D4F",      # Status: pass/good
    "warning": "#B7791F",      # Status: needs improvement (amber, not the accent)
    "danger": "#C62828",       # Status: fail/critical
    "dark": "#0F0F0F",         # Ink
    "light_bg": "#F2F2F2",     # Paper
    "card": "#FFFFFF",         # Card surface
    "grid": "#D6D6D6",         # Hairline
    "muted": "#686868",        # Grey 500
    "body": "#2D2D2D",         # Body text
    "track": "#E6E6E6",        # Gauge track
}

# Font stacks. Inter Tight and IBM Plex Mono are used when their files are
# installed (system or per-user font folder); otherwise the stack falls back to
# a common sans and mono so the PDF still builds.
SANS_STACK = "'Inter Tight', 'Inter', 'Segoe UI', 'Helvetica Neue', Arial, 'DejaVu Sans', sans-serif"
MONO_STACK = "'IBM Plex Mono', Consolas, 'DejaVu Sans Mono', monospace"

_FONT_PATTERNS = {
    "Inter Tight": ("InterTight*.ttf", "InterTight*.otf", "Inter Tight*.ttf"),
    "IBM Plex Mono": ("IBMPlexMono*.ttf", "IBMPlexMono*.otf", "IBM Plex Mono*.ttf"),
}
_FONT_CACHE = None


def _font_dirs():
    """Return candidate font folders without hard-coding any user path."""
    dirs = []
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    if windir:
        dirs.append(Path(windir) / "Fonts")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    home = Path.home()
    dirs += [
        home / "Library" / "Fonts", Path("/Library/Fonts"),
        home / ".fonts", home / ".local" / "share" / "fonts",
        Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
    ]
    return [d for d in dirs if d.is_dir()]


def _find_brand_fonts():
    """Locate installed brand font files. Returns {family: [Path, ...]}."""
    global _FONT_CACHE
    if _FONT_CACHE is not None:
        return _FONT_CACHE
    found = {}
    for family, patterns in _FONT_PATTERNS.items():
        files = []
        for folder in _font_dirs():
            for pattern in patterns:
                files.extend(folder.glob(pattern))
                files.extend(folder.glob(f"*/{pattern}"))
        if files:
            found[family] = sorted(set(files))
    _FONT_CACHE = found
    return found


def _font_weight_style(path):
    """Infer CSS font-weight and font-style from a font file name."""
    name = Path(path).stem.lower().replace(" ", "")
    style = "italic" if "italic" in name else "normal"
    if "[" in name or "variable" in name:
        return "100 900", style
    for token, weight in (
        ("extralight", "200"), ("ultralight", "200"), ("thin", "100"),
        ("semibold", "600"), ("demibold", "600"), ("extrabold", "800"),
        ("ultrabold", "800"), ("black", "900"), ("heavy", "900"),
        ("light", "300"), ("medium", "500"), ("bold", "700"),
    ):
        if token in name:
            return weight, style
    return "400", style


def _font_face_css():
    """Build @font-face rules for installed brand fonts (empty when none)."""
    rules = []
    for family, files in _find_brand_fonts().items():
        for path in files:
            weight, style = _font_weight_style(path)
            rules.append(
                f"  @font-face {{ font-family: '{family}'; "
                f"src: url('{_file_uri(path)}'); "
                f"font-weight: {weight}; font-style: {style}; }}"
            )
    return "\n".join(rules)


def _file_uri(path):
    """Return a file URI that works on Windows and POSIX (file:///C:/...)."""
    return Path(path).resolve().as_uri()


def _score_color(score):
    """Return brand color based on Lighthouse-style score thresholds."""
    if score >= 90:
        return BRAND["success"]
    elif score >= 50:
        return BRAND["warning"]
    return BRAND["danger"]


def _rating_color(rating):
    """Return brand color based on CrUX rating strings."""
    r = str(rating).lower().replace("-", "_").replace(" ", "_")
    if r in ("good", "pass", "fast"):
        return BRAND["success"]
    elif r in ("needs_improvement", "needs-improvement", "average", "warn"):
        return BRAND["warning"]
    return BRAND["danger"]


def _score_class(score):
    """Return CSS class for TOC score badges."""
    if score >= 80:
        return "score-good"
    elif score >= 50:
        return "score-warn"
    return "score-bad"


def _rating_css_class(rating):
    """Return CSS status class from a rating string."""
    r = str(rating).lower()
    if "good" in r or "pass" in r:
        return "status-pass"
    elif "poor" in r or "fail" in r:
        return "status-fail"
    return "status-warn"


GSC_ANOMALY_START = "2025-05-13"
GSC_ANOMALY_END = "2026-04-27"
GSC_ANOMALY_WARNING = (
    "GSC impressions logging error affected impressions, CTR, and average "
    "position from 2025-05-13 through 2026-04-27; clicks were not affected."
)


def _date_range_overlaps(start_date: str, end_date: str, overlap_start: str, overlap_end: str) -> bool:
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
        window_start = datetime.strptime(overlap_start, "%Y-%m-%d").date()
        window_end = datetime.strptime(overlap_end, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return False
    return start <= window_end and end >= window_start


def _gsc_anomaly_warning(gsc_data: dict) -> str:
    dr = gsc_data.get("date_range", {}) if isinstance(gsc_data, dict) else {}
    if _date_range_overlaps(
        dr.get("start"), dr.get("end"), GSC_ANOMALY_START, GSC_ANOMALY_END
    ):
        return GSC_ANOMALY_WARNING
    return ""


# ─── Chart Setup ─────────────────────────────────────────────────────────────

def _setup_matplotlib():
    """Configure matplotlib to match the Engine Room report style."""
    sans = ["Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans"]
    try:
        from matplotlib import font_manager
        for path in _find_brand_fonts().get("Inter Tight", []):
            font_manager.fontManager.addfont(str(path))
        if _find_brand_fonts().get("Inter Tight"):
            sans.insert(0, "Inter Tight")
    except (ImportError, OSError, RuntimeError, ValueError):
        pass
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": sans,
        "font.size": 10,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.titlecolor": BRAND["dark"],
        "axes.labelsize": 10,
        "axes.labelcolor": BRAND["secondary"],
        "axes.edgecolor": BRAND["grid"],
        "xtick.color": BRAND["secondary"],
        "ytick.color": BRAND["secondary"],
        "text.color": BRAND["dark"],
        "axes.facecolor": BRAND["card"],
        "figure.facecolor": BRAND["card"],
        "axes.grid": False,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "legend.frameon": False,
    })


if plt is not None:
    _setup_matplotlib()


def _require_chart_dependencies() -> None:
    """Raise a runtime error only when a requested report needs charts."""
    if plt is None or np is None:
        raise RuntimeError(
            "matplotlib and numpy are required for chart generation. "
            "Install the report dependencies from requirements.txt."
        ) from _CHART_IMPORT_ERROR


# ─── Chart Functions ─────────────────────────────────────────────────────────

def chart_lighthouse_gauges(data: dict, output_dir: Path) -> str:
    """Generate 2x2 Lighthouse score gauges."""
    scores = data.get("lighthouse_scores", {})
    if not scores:
        return ""
    _require_chart_dependencies()

    fig, axes = plt.subplots(2, 2, figsize=(8, 4), subplot_kw={"projection": "polar"})
    categories = [
        ("performance", "Performance"),
        ("accessibility", "Accessibility"),
        ("best-practices", "Best Practices"),
        ("seo", "SEO"),
    ]

    for ax, (key, label) in zip(axes.flat, categories):
        score = scores.get(key, 0)
        theta_bg = np.linspace(np.pi, 0, 100)
        theta_fill = np.linspace(np.pi, np.pi - (score / 100) * np.pi, 100)

        ax.plot(theta_bg, [1] * 100, linewidth=14, color=BRAND["track"], solid_capstyle="butt")
        ax.plot(theta_fill, [1] * 100, linewidth=14, color=_score_color(score), solid_capstyle="butt")

        ax.text(np.pi / 2, 0.35, f"{score}", ha="center", va="center",
                fontsize=24, fontweight="bold", color=BRAND["dark"])
        ax.text(np.pi / 2, -0.05, label, ha="center", va="center",
                fontsize=10, color=BRAND["muted"])

        ax.set_ylim(0, 1.3)
        ax.set_rticks([])
        ax.set_thetagrids([])
        ax.spines["polar"].set_visible(False)

    plt.tight_layout(pad=2)
    path = output_dir / "lighthouse_gauges.png"
    plt.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close()
    return str(path)


def chart_cwv_distributions(data: dict, output_dir: Path) -> str:
    """Generate stacked horizontal bars for CWV metric distributions."""
    crux = data.get("crux", {})
    metrics = crux.get("metrics", {})
    if not metrics:
        return ""

    cwv_order = [
        "largest_contentful_paint", "interaction_to_next_paint",
        "cumulative_layout_shift", "first_contentful_paint",
        "experimental_time_to_first_byte",
    ]

    labels, goods, nis, poors = [], [], [], []
    for name in cwv_order:
        m = metrics.get(name)
        if not m or "distribution" not in m:
            continue
        d = m["distribution"]
        labels.append(m.get("label", name))
        goods.append(d.get("good", 0))
        nis.append(d.get("needs_improvement", 0))
        poors.append(d.get("poor", 0))

    if not labels:
        return ""
    _require_chart_dependencies()

    fig, ax = plt.subplots(figsize=(8, max(2.5, len(labels) * 0.7)))
    y = range(len(labels))

    ax.barh(y, goods, color=BRAND["success"], label="Good", height=0.5)
    ax.barh(y, nis, left=goods, color=BRAND["warning"], label="Needs Improvement", height=0.5)
    left2 = [g + n for g, n in zip(goods, nis)]
    ax.barh(y, poors, left=left2, color=BRAND["danger"], label="Poor", height=0.5)

    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.set_xlim(0, 100)
    ax.set_xlabel("% of page loads")
    ax.legend(loc="lower right", fontsize=9)
    ax.invert_yaxis()

    for i, (g, n, p) in enumerate(zip(goods, nis, poors)):
        if g > 10:
            ax.text(g / 2, i, f"{g:.0f}%", ha="center", va="center",
                    fontsize=8, color="white", fontweight="bold")
        if n > 10:
            ax.text(g + n / 2, i, f"{n:.0f}%", ha="center", va="center",
                    fontsize=8, color="white", fontweight="bold")
        if p > 10:
            ax.text(g + n + p / 2, i, f"{p:.0f}%", ha="center", va="center",
                    fontsize=8, color="white", fontweight="bold")

    plt.tight_layout()
    path = output_dir / "cwv_distributions.png"
    plt.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close()
    return str(path)


def chart_cwv_timeline(data: dict, output_dir: Path) -> str:
    """Generate CWV timeline chart from CrUX History data."""
    metrics = data.get("metrics", {})
    periods = data.get("collection_periods", [])
    if not metrics or not periods:
        return ""

    cwv_metrics = [
        "largest_contentful_paint",
        "interaction_to_next_paint",
        "cumulative_layout_shift",
    ]
    available = [m for m in cwv_metrics if m in metrics]
    if not available:
        return ""
    _require_chart_dependencies()

    fig, axes = plt.subplots(len(available), 1, figsize=(10, 3 * len(available)), sharex=True)
    if len(available) == 1:
        axes = [axes]

    x_labels = [p.get("last", "")[-5:] for p in periods]  # MM-DD format
    for ax, metric_name in zip(axes, available):
        m = metrics[metric_name]
        p75s = m.get("p75_values", [])
        label = m.get("label", metric_name)
        good_t = m.get("good_threshold", 0)
        poor_t = m.get("poor_threshold", 0)

        valid_x = [i for i, v in enumerate(p75s) if v is not None]
        valid_y = [v for v in p75s if v is not None]

        if not valid_y:
            continue

        # Threshold bands
        if good_t and poor_t:
            ax.axhspan(0, good_t, alpha=0.1, color=BRAND["success"])
            ax.axhspan(good_t, poor_t, alpha=0.1, color=BRAND["warning"])
            ax.axhline(y=good_t, color=BRAND["success"], linestyle="--", alpha=0.5, linewidth=1)
            ax.axhline(y=poor_t, color=BRAND["danger"], linestyle="--", alpha=0.5, linewidth=1)

        ax.plot(valid_x, valid_y, color=BRAND["primary"], linewidth=2, marker="o", markersize=3)
        ax.fill_between(valid_x, valid_y, alpha=0.1, color=BRAND["primary"])

        unit = m.get("unit", "")
        ax.set_ylabel(f"{label} (p75{unit})")
        ax.set_title(label, fontsize=12, fontweight="bold")

    if x_labels:
        step = max(1, len(x_labels) // 8)
        axes[-1].set_xticks(range(0, len(x_labels), step))
        axes[-1].set_xticklabels(
            [x_labels[i] for i in range(0, len(x_labels), step)],
            rotation=45, fontsize=8,
        )

    plt.tight_layout()
    path = output_dir / "cwv_timeline.png"
    plt.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close()
    return str(path)


def chart_top_queries(data: dict, output_dir: Path) -> str:
    """Generate horizontal bar chart of top queries by impressions."""
    rows = data.get("rows", [])
    if not rows:
        return ""

    # Sort by impressions (more meaningful than clicks for new sites)
    top = sorted(rows, key=lambda r: r.get("impressions", 0), reverse=True)[:12]
    top = [r for r in top if r.get("impressions", 0) > 0]
    if not top:
        return ""

    labels = [r.get("query", r.get("keys", ["?"])[0])[:35] for r in top]
    impressions = [r.get("impressions", 0) for r in top]
    clicks = [r.get("clicks", 0) for r in top]

    if not impressions or max(impressions) < 3:
        return ""
    _require_chart_dependencies()

    fig, ax = plt.subplots(figsize=(7, max(2, len(labels) * 0.3)))
    y = range(len(labels))
    bars = ax.barh(y, impressions, color=BRAND["primary"], height=0.55, label="Impressions")
    if any(c > 0 for c in clicks):
        ax.barh(y, clicks, color=BRAND["accent"], height=0.55, label="Clicks")
        ax.legend(fontsize=8, loc="lower right")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("Count")
    ax.invert_yaxis()

    for bar, val in zip(bars, clicks):
        if val > 0:
            ax.text(
                bar.get_width() + max(clicks) * 0.02,
                bar.get_y() + bar.get_height() / 2,
                str(val), va="center", fontsize=8, color=BRAND["dark"],
            )

    plt.tight_layout()
    path = output_dir / "top_queries.png"
    plt.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close()
    return str(path)


def chart_index_status(data: dict, output_dir: Path) -> str:
    """Generate donut chart for URL inspection results."""
    summary = data.get("summary", {})
    if not summary:
        return ""

    labels, sizes, colors = [], [], []
    for key, label, color in [
        ("pass", "Indexed", BRAND["success"]),
        ("fail", "Not Indexed", BRAND["danger"]),
        ("neutral", "Neutral", BRAND["grid"]),
        ("error", "Error", BRAND["muted"]),
    ]:
        val = summary.get(key, 0)
        if val > 0:
            labels.append(f"{label} ({val})")
            sizes.append(val)
            colors.append(color)

    if not sizes:
        return ""
    _require_chart_dependencies()

    fig, ax = plt.subplots(figsize=(4.5, 3.5))
    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, colors=colors, autopct="%1.0f%%",
        startangle=90, pctdistance=0.75, textprops={"fontsize": 9},
    )
    centre = plt.Circle((0, 0), 0.50, fc="white")
    ax.add_artist(centre)
    total = sum(sizes)
    ax.text(0, 0, f"{total}\nURLs", ha="center", va="center",
            fontsize=16, fontweight="bold", color=BRAND["dark"])

    plt.tight_layout()
    path = output_dir / "index_status.png"
    plt.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close()
    return str(path)


# ─── CSS Template ────────────────────────────────────────────────────────────

def _build_css(domain: str) -> str:
    """
    A4 report CSS in the Engine Room house style.

    Paper #F2F2F2, ink #0F0F0F, one accent #FF5722, white cards with hairline
    borders and 2-4px corners, bracketed mono eyebrows. Inter Tight / IBM Plex
    Mono are embedded via @font-face when installed, otherwise the sans and
    mono fallback stacks apply. WeasyPrint-safe patterns are kept (div.section
    for page breaks, float:right for badges, display:table for columns, no
    page-break-inside: avoid).
    """
    # Raw text inside <style>: strip characters that could end the CSS string.
    domain = "".join(ch for ch in str(domain) if ch not in '"\\<>')
    font_faces = _font_face_css()
    return f"""\
{font_faces}

  @page {{
    size: A4;
    margin: 20mm 18mm 22mm 18mm;
    background: {BRAND["light_bg"]};
    @bottom-left {{
      content: "[ {domain} ]";
      font-family: {MONO_STACK};
      font-size: 7pt;
      letter-spacing: 0.6pt;
      color: {BRAND["muted"]};
    }}
    @bottom-right {{
      content: counter(page) " / " counter(pages);
      font-family: {MONO_STACK};
      font-size: 7pt;
      letter-spacing: 0.6pt;
      color: {BRAND["muted"]};
    }}
  }}

  @page :first {{
    margin: 0;
    background: {BRAND["dark"]};
    @bottom-left {{ content: none; }}
    @bottom-center {{ content: none; }}
    @bottom-right {{ content: none; }}
  }}

  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }}

  body {{
    font-family: {SANS_STACK};
    font-size: 9.5pt;
    line-height: 1.5;
    color: {BRAND["body"]};
    background: {BRAND["light_bg"]};
    counter-reset: er-section;
  }}

  /* ─── Title Page (ink) ─── */
  .title-page {{
    width: 210mm;
    height: 297mm;
    background: {BRAND["dark"]};
    color: {BRAND["light_bg"]};
    padding: 70mm 22mm 30mm 22mm;
    text-align: left;
  }}

  .title-page::before {{
    content: "";
    display: block;
    width: 18mm;
    height: 1.2mm;
    background: {BRAND["accent"]};
    margin-bottom: 10mm;
  }}

  .title-page .badge {{
    font-family: {MONO_STACK};
    font-size: 8.5pt;
    letter-spacing: 1.5pt;
    text-transform: uppercase;
    color: {BRAND["accent"]};
    margin-bottom: 8mm;
  }}

  .title-page .badge::before {{ content: "[ "; }}
  .title-page .badge::after {{ content: " ]"; }}

  .title-page h1 {{
    font-size: 34pt;
    font-weight: 700;
    letter-spacing: -0.6pt;
    line-height: 1.1;
    color: {BRAND["light_bg"]};
    margin-bottom: 4mm;
  }}

  .title-page .subtitle {{
    font-size: 13pt;
    color: #969696;
    margin-bottom: 16mm;
  }}

  .title-page .score-box {{
    display: inline-block;
    border: 1px solid {BRAND["secondary"]};
    border-left: 3px solid {BRAND["accent"]};
    border-radius: 3px;
    padding: 5mm 9mm 5mm 7mm;
    margin-bottom: 16mm;
  }}

  .title-page .score-number {{
    white-space: nowrap;
    font-size: 46pt;
    font-weight: 700;
    letter-spacing: -1pt;
    color: {BRAND["light_bg"]};
    line-height: 1;
  }}

  .title-page .score-max {{
    font-size: 18pt;
    font-weight: 400;
    color: {BRAND["muted"]};
  }}

  .title-page .score-label {{
    font-family: {MONO_STACK};
    font-size: 7.5pt;
    letter-spacing: 1pt;
    text-transform: uppercase;
    color: #969696;
    margin-top: 2mm;
  }}

  .title-page .meta {{
    font-family: {MONO_STACK};
    font-size: 7.5pt;
    letter-spacing: 0.8pt;
    text-transform: uppercase;
    color: #969696;
    padding-top: 4mm;
    border-top: 1px solid {BRAND["secondary"]};
  }}

  .title-page .meta span {{
    margin-right: 8mm;
  }}

  .title-page .powered {{
    margin-top: 8mm;
  }}

  .title-page .powered img {{
    height: 18px;
  }}

  .title-page .powered div {{
    font-family: {MONO_STACK};
    font-size: 7pt;
    color: {BRAND["muted"]};
    margin-top: 2mm;
  }}

  /* ─── Table of Contents ─── */
  .toc-page {{
    page-break-before: always;
  }}

  .toc-page::before {{
    content: "[ Contents ]";
    display: block;
    font-family: {MONO_STACK};
    font-size: 7.5pt;
    letter-spacing: 1.2pt;
    text-transform: uppercase;
    color: {BRAND["accent"]};
    margin-bottom: 2mm;
  }}

  .toc-page h2 {{
    font-size: 22pt;
    font-weight: 700;
    letter-spacing: -0.4pt;
    color: {BRAND["dark"]};
    margin-bottom: 6mm;
    padding-bottom: 3mm;
    border-bottom: 2px solid {BRAND["dark"]};
  }}

  .toc-list {{
    list-style: none;
    padding: 0;
    margin-left: 0;
  }}

  .toc-list li {{
    padding: 2mm 0;
    border-bottom: 1px solid {BRAND["grid"]};
    overflow: hidden;
  }}

  .toc-list li.toc-section {{
    font-weight: 600;
    font-size: 10.5pt;
    padding-top: 3.5mm;
    color: {BRAND["dark"]};
  }}

  .toc-list li.toc-sub {{
    padding-left: 8mm;
    font-size: 9pt;
    color: {BRAND["secondary"]};
  }}

  .toc-score {{
    display: inline-block;
    float: right;
    padding: 0.4mm 2.5mm;
    border-radius: 2px;
    font-family: {MONO_STACK};
    font-size: 8pt;
    font-weight: 600;
    color: #FFFFFF;
  }}

  .score-good {{ background: {BRAND["success"]}; }}
  .score-warn {{ background: {BRAND["warning"]}; }}
  .score-bad {{ background: {BRAND["danger"]}; }}

  /* ─── Section Styles ─── */
  div.section {{
    page-break-before: always;
  }}

  .section-header {{
    counter-increment: er-section;
    border-top: 2px solid {BRAND["dark"]};
    padding: 3mm 0 0 0;
    margin-bottom: 6mm;
    page-break-after: avoid;
  }}

  .section-header::before {{
    content: "[ " counter(er-section, decimal-leading-zero) " ]";
    display: block;
    font-family: {MONO_STACK};
    font-size: 7.5pt;
    letter-spacing: 1.2pt;
    color: {BRAND["accent"]};
    margin-bottom: 1.5mm;
  }}

  .section-header h2 {{
    font-size: 20pt;
    font-weight: 700;
    letter-spacing: -0.4pt;
    line-height: 1.15;
    color: {BRAND["dark"]};
  }}

  .section-header .section-score {{
    font-family: {MONO_STACK};
    font-size: 11pt;
    font-weight: 600;
    float: right;
    margin-top: -7mm;
  }}

  h3 {{
    font-size: 12pt;
    font-weight: 700;
    color: {BRAND["dark"]};
    margin-top: 6mm;
    margin-bottom: 3mm;
    padding-bottom: 1.5mm;
    border-bottom: 1px solid {BRAND["grid"]};
    page-break-after: avoid;
  }}

  h4 {{
    font-size: 10pt;
    font-weight: 600;
    color: {BRAND["dark"]};
    margin-top: 4mm;
    margin-bottom: 2mm;
    page-break-after: avoid;
  }}

  p {{
    margin-bottom: 3mm;
    color: {BRAND["body"]};
  }}

  .highlight, .critical-box, .success-box {{
    background: {BRAND["card"]};
    border: 1px solid {BRAND["grid"]};
    border-left: 3px solid {BRAND["warning"]};
    border-radius: 2px;
    padding: 3mm 4mm;
    margin: 4mm 0;
    font-size: 9pt;
    /* allow page breaks to prevent white gaps */
  }}

  .critical-box {{ border-left-color: {BRAND["danger"]}; }}
  .success-box {{ border-left-color: {BRAND["success"]}; }}

  /* ─── Tables ─── */
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 4mm 0 6mm 0;
    font-size: 8.5pt;
    background: {BRAND["card"]};
  }}

  thead th {{
    background: {BRAND["dark"]};
    color: {BRAND["light_bg"]};
    font-family: {MONO_STACK};
    font-weight: 500;
    font-size: 7pt;
    letter-spacing: 0.8pt;
    text-transform: uppercase;
    padding: 2.5mm 3mm;
    text-align: left;
  }}

  tbody td {{
    padding: 2.2mm 3mm;
    border-bottom: 1px solid {BRAND["grid"]};
    vertical-align: top;
  }}

  .status-pass {{
    color: {BRAND["success"]};
    font-weight: 600;
  }}

  .status-fail {{
    color: {BRAND["danger"]};
    font-weight: 600;
  }}

  .status-warn {{
    color: {BRAND["warning"]};
    font-weight: 600;
  }}

  .status-partial {{
    color: {BRAND["secondary"]};
    font-weight: 600;
  }}

  /* ─── Charts ─── */
  .chart-container {{
    text-align: center;
    background: {BRAND["card"]};
    border: 1px solid {BRAND["grid"]};
    border-radius: 3px;
    padding: 4mm;
    margin: 4mm 0;
  }}

  .chart-container img {{
    max-width: 100%;
    max-height: 120mm;
    height: auto;
  }}

  .chart-caption {{
    font-family: {MONO_STACK};
    font-size: 7pt;
    letter-spacing: 0.4pt;
    color: {BRAND["muted"]};
    margin-top: 2mm;
    text-align: center;
  }}

  .chart-half {{
    display: inline-block;
    width: 48%;
    vertical-align: top;
    text-align: center;
    margin: 2mm 0;
  }}

  .chart-half img {{
    max-width: 100%;
    height: auto;
  }}

  /* ─── Two column layout ─── */
  .two-col {{
    display: table;
    width: 100%;
    table-layout: fixed;
    margin: 3mm 0;
  }}

  .two-col .col {{
    display: table-cell;
    vertical-align: top;
    padding: 0 2mm;
  }}

  .four-col {{
    display: table;
    width: 100%;
    table-layout: fixed;
    margin: 3mm 0;
  }}

  .four-col .col {{
    display: table-cell;
    vertical-align: top;
    padding: 0 1.5mm;
  }}

  /* ─── Metric Cards ─── */
  .metric-card {{
    background: {BRAND["card"]};
    border: 1px solid {BRAND["grid"]};
    border-radius: 3px;
    padding: 3mm 3mm 2.5mm 3mm;
    text-align: left;
    margin: 2mm 0;
  }}

  .metric-card .value {{
    font-size: 15pt;
    font-weight: 700;
    letter-spacing: -0.3pt;
    line-height: 1.2;
    color: {BRAND["dark"]};
  }}

  .metric-card .label {{
    font-family: {MONO_STACK};
    font-size: 6.5pt;
    color: {BRAND["muted"]};
    text-transform: uppercase;
    letter-spacing: 0.8pt;
    margin-top: 1mm;
  }}

  /* ─── Action Items ─── */
  .action-item {{
    background: {BRAND["card"]};
    border: 1px solid {BRAND["grid"]};
    border-left: 3px solid {BRAND["muted"]};
    border-radius: 2px;
    padding: 3mm 4mm;
    margin: 3mm 0;
    /* allow page breaks to prevent white gaps */
  }}

  .action-item.critical {{ border-left-color: {BRAND["danger"]}; }}
  .action-item.high {{ border-left-color: {BRAND["warning"]}; }}
  .action-item.medium {{ border-left-color: {BRAND["dark"]}; }}
  .action-item.low {{ border-left-color: #969696; }}

  .action-item h4 {{
    margin-top: 0;
    margin-bottom: 1.5mm;
    border-bottom: none;
    padding-bottom: 0;
  }}

  .priority-tag {{
    display: inline-block;
    padding: 0.4mm 2.5mm;
    border-radius: 2px;
    font-family: {MONO_STACK};
    font-size: 7pt;
    font-weight: 600;
    letter-spacing: 0.8pt;
    color: #FFFFFF;
    margin-right: 2mm;
    vertical-align: middle;
  }}

  .priority-critical {{ background: {BRAND["danger"]}; }}
  .priority-high {{ background: {BRAND["warning"]}; }}
  .priority-medium {{ background: {BRAND["dark"]}; }}
  .priority-low {{ background: #969696; }}

  /* ─── Code blocks ─── */
  .code-block {{
    background: {BRAND["dark"]};
    color: {BRAND["light_bg"]};
    padding: 3mm 4mm;
    border-radius: 3px;
    font-family: {MONO_STACK};
    font-size: 7.5pt;
    line-height: 1.6;
    margin: 3mm 0;
    white-space: pre-wrap;
    word-break: break-all;
    /* allow page breaks to prevent white gaps */
  }}

  /* ─── Divider ─── */
  .divider {{
    border: none;
    border-top: 1px solid {BRAND["grid"]};
    margin: 5mm 0;
  }}

  /* ─── Action groups ─── */
  .roadmap-phase {{
    background: {BRAND["card"]};
    border: 1px solid {BRAND["grid"]};
    border-top: 2px solid {BRAND["accent"]};
    border-radius: 3px;
    padding: 4mm 5mm;
    margin: 4mm 0;
    /* allow page breaks to prevent white gaps */
  }}

  .roadmap-phase h4 {{
    margin-top: 0;
    border-bottom: none;
    color: {BRAND["dark"]};
  }}

  .roadmap-phase ul {{
    margin: 2mm 0 0 5mm;
    padding: 0;
  }}

  .roadmap-phase li {{
    margin-bottom: 1.5mm;
    font-size: 9pt;
    color: {BRAND["body"]};
  }}

  /* ─── Lists ─── */
  ul {{
    margin-left: 5mm;
    margin-bottom: 3mm;
  }}

  li {{
    margin-bottom: 1.5mm;
  }}

  /* ─── Data freshness and footer notes ─── */
  .data-freshness {{
    font-family: {MONO_STACK};
    font-size: 7pt;
    letter-spacing: 0.3pt;
    color: {BRAND["muted"]};
    margin-top: 4mm;
    padding-top: 2mm;
    border-top: 1px solid {BRAND["grid"]};
  }}

  .report-footnote {{
    font-family: {MONO_STACK};
    font-size: 7.5pt;
    color: {BRAND["muted"]};
    margin-top: 5mm;
    text-align: left;
  }}
"""


# ─── HTML Helpers ────────────────────────────────────────────────────────────

def _img_tag(path, alt="Chart"):
    """Convert file path to a file URI img tag for WeasyPrint."""
    if not path:
        return ""
    return f'<img src="{_file_uri(path)}" style="max-width: 100%;" alt="{alt}">'


def _chart_html(path, caption, fig_num, alt="Chart"):
    """Build a complete chart container with figure caption."""
    if not path:
        return ""
    return (
        f'    <div class="chart-container">\n'
        f'      <img src="{_file_uri(path)}" style="width: 85%;" alt="{alt}">\n'
        f'      <div class="chart-caption">Figure {fig_num}: {caption}</div>\n'
        f'    </div>\n'
    )


def _metric_card(value, label, color=None):
    """Build a metric card HTML block."""
    style = f' style="color: {color};"' if color else ""
    return (
        f'      <div class="metric-card">\n'
        f'        <div class="value"{style}>{value}</div>\n'
        f'        <div class="label">{label}</div>\n'
        f'      </div>\n'
    )


# ─── Section Builders ────────────────────────────────────────────────────────

def _build_title_page(domain, report_title, subtitle, score=None, score_label=None, meta_items=None):
    """Build the ink title page (eyebrow, domain, subtitle, score, meta)."""
    score_html = ""
    if score is not None:
        # Counts (clicks, URLs inspected) are not out of 100; only scores get "/100".
        is_score = "score" in str(score_label or "Score").lower()
        max_html = '<span class="score-max">/100</span>' if is_score else ""
        score_html = (
            f'  <div class="score-box">\n'
            f'    <div class="score-number">{score}{max_html}</div>\n'
            f'    <div class="score-label">{score_label or "Lighthouse Performance Score"}</div>\n'
            f'  </div>\n'
        )

    meta_html = ""
    if meta_items:
        spans = "\n    ".join(f"<span>{item}</span>" for item in meta_items)
        meta_html = (
            f'  <div class="meta">\n'
            f'    {spans}\n'
            f'  </div>\n'
        )

    # Google logo (if available in charts dir)
    google_logo_path = Path(__file__).parent.parent / "charts" / "google_logo.png"
    google_logo_html = ""
    if google_logo_path.exists():
        google_logo_html = (
            f'  <div class="powered">\n'
            f'    <img src="{_file_uri(google_logo_path)}" alt="Google">\n'
            f'    <div>Powered by Google APIs</div>\n'
            f'  </div>\n'
        )

    subtitle_html = f'  <div class="subtitle">{subtitle}</div>\n' if subtitle else ""
    return (
        f'\n<!-- {"=" * 55} TITLE PAGE {"=" * 3} -->\n'
        f'<div class="title-page">\n'
        f'  <div class="badge">{report_title}</div>\n'
        f'  <h1>{domain}</h1>\n'
        f'{subtitle_html}'
        f'{score_html}'
        f'{meta_html}'
        f'{google_logo_html}'
        f'</div>\n'
    )


def _build_toc(sections_info):
    """
    Build a Table of Contents page.

    sections_info: list of dicts with keys 'num', 'title', 'score' (optional),
                   and 'subs' (list of subtitle strings).
    """
    items = []
    for sec in sections_info:
        score_html = ""
        if sec.get("score") is not None:
            cls = _score_class(sec["score"])
            score_html = f' <span class="toc-score {cls}">{sec["score"]}</span>'
        items.append(
            f'    <li class="toc-section">'
            f'<span>{sec["num"]}. {sec["title"]}</span>{score_html}'
            f'</li>'
        )
        for sub in sec.get("subs", []):
            items.append(f'    <li class="toc-sub"><span>{sub}</span></li>')

    items_html = "\n".join(items)
    return (
        f'\n<!-- {"=" * 55} TABLE OF CONTENTS {"=" * 3} -->\n'
        f'<div class="toc-page">\n'
        f'  <h2>Table of Contents</h2>\n'
        f'  <ul class="toc-list">\n'
        f'{items_html}\n'
        f'  </ul>\n'
        f'</div>\n'
    )


def _coerce_items(value):
    """Return a list for scalar-or-list audit fields."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _finding_title(item):
    if isinstance(item, dict):
        return item.get("title") or item.get("issue") or item.get("name") or "Finding"
    return str(item)


def _finding_severity(item):
    if isinstance(item, dict):
        return str(item.get("severity", "Info"))
    return "Info"


def _finding_description(item):
    if isinstance(item, dict):
        return item.get("description") or item.get("details") or item.get("evidence") or ""
    return ""


def _build_full_audit_categories(data, section_num=2):
    """Build category sections for audit-data.json style reports."""
    categories = _coerce_items(data.get("categories"))
    if not categories:
        return ""

    lines = []
    lines.append(f'\n<!-- {"=" * 55} {section_num}. AUDIT CATEGORIES {"=" * 3} -->')
    lines.append('<div class="section">')
    lines.append('  <div class="section-header">')
    lines.append(f'    <h2>{section_num}. Audit Categories</h2>')
    lines.append('  </div>')
    lines.append('')

    for idx, category in enumerate(categories, 1):
        if not isinstance(category, dict):
            continue
        name = escape(str(category.get("name", f"Category {idx}")))
        score = category.get("score")
        lines.append(f'  <h3>{section_num}.{idx} {name}</h3>')
        if score is not None:
            try:
                score_val = float(score)
                cls = "status-pass" if score_val >= 80 else ("status-warn" if score_val >= 50 else "status-fail")
                lines.append(f'  <p><strong>Score:</strong> <span class="{cls}">{score_val:g}/100</span></p>')
            except (TypeError, ValueError):
                lines.append(f'  <p><strong>Score:</strong> {escape(str(score))}</p>')

        what_works = _coerce_items(category.get("what_works"))
        if what_works:
            lines.append('  <h4>What Works</h4>')
            lines.append('  <ul>')
            for item in what_works:
                lines.append(f'    <li>{escape(str(item))}</li>')
            lines.append('  </ul>')

        findings = _coerce_items(category.get("findings"))
        if findings:
            lines.append('  <h4>Findings</h4>')
            for finding in findings:
                title = escape(_finding_title(finding))
                desc = escape(_finding_description(finding))
                recommendation = ""
                if isinstance(finding, dict) and finding.get("recommendation"):
                    recommendation = escape(str(finding["recommendation"]))
                lines.append('  <div class="action-item medium">')
                # Only label a severity when the finding actually carries one. Plain-string
                # findings have no severity, and _finding_severity() falls back to "Info" --
                # which would badge every entry as "Info" (see the executive-summary fix for
                # the same shape). Dict-shaped findings with an explicit severity keep it.
                if isinstance(finding, dict) and finding.get("severity"):
                    severity = escape(str(finding["severity"]))
                    severity_class = _rating_css_class(severity)
                    lines.append(f'    <h4>{title} <span class="{severity_class}">{severity}</span></h4>')
                else:
                    lines.append(f'    <h4>{title}</h4>')
                if desc:
                    lines.append(f'    <p>{desc}</p>')
                if recommendation:
                    lines.append(f'    <p><strong>Recommendation:</strong> {recommendation}</p>')
                lines.append('  </div>')
        lines.append('  <hr class="divider">')

    lines.append('</div>')
    return "\n".join(lines)


def _build_audit_action_plan(data, section_num=5):
    """Build the action-plan section as priority groups.

    Groups keep their names but any ``timeframe`` / ``timeline`` value in the
    input is deliberately not rendered: reports carry no schedules, effort or
    week labels (ordering and timing are agreed after scope approval).
    """
    action_plan = data.get("action_plan", {})
    phases = []
    if isinstance(action_plan, dict):
        phases = _coerce_items(action_plan.get("phases") or action_plan.get("roadmap"))
    elif isinstance(action_plan, list):
        phases = action_plan
    if not phases:
        return ""

    lines = []
    lines.append(f'\n<!-- {"=" * 55} {section_num}. ACTION PLAN {"=" * 3} -->')
    lines.append('<div class="section">')
    lines.append('  <div class="section-header">')
    lines.append(f'    <h2>{section_num}. Action Plan</h2>')
    lines.append('  </div>')
    lines.append('')

    for idx, phase in enumerate(phases, 1):
        if isinstance(phase, dict):
            name = phase.get("name") or phase.get("phase") or phase.get("priority") or f"Group {idx}"
            items = _coerce_items(phase.get("items") or phase.get("actions"))
        else:
            name = f"Group {idx}"
            items = [phase]
        lines.append('  <div class="roadmap-phase">')
        lines.append(f'    <h4>{escape(str(name))}</h4>')
        lines.append('    <ul>')
        for item in items:
            lines.append(f'      <li>{escape(str(item))}</li>')
        lines.append('    </ul>')
        lines.append('  </div>')

    lines.append('</div>')
    return "\n".join(lines)


def _build_executive_summary(domain, timestamp, data, report_type):
    """Build the Executive Summary section with metric cards, issues, and wins."""
    lines = []
    lines.append(f'\n<!-- {"=" * 55} 1. EXECUTIVE SUMMARY {"=" * 3} -->')
    lines.append('<div class="section">')
    lines.append('  <div class="section-header">')
    lines.append('    <h2>1. Executive Summary</h2>')
    lines.append('  </div>')
    lines.append('')

    summary = data.get("summary", {}) if isinstance(data.get("summary"), dict) else {}

    # Context paragraph
    if summary:
        business_type = summary.get("business_type")
        type_text = f' for a <strong>{escape(str(business_type))}</strong> site' if business_type else ""
        lines.append(f'  <p>This report presents a comprehensive SEO audit of '
                     f'<strong>{domain}</strong>{type_text}, generated on {timestamp}. '
                     f'Findings combine technical, content, schema, performance, visual, '
                     f'and search-readiness evidence as available.</p>')
    else:
        lines.append(f'  <p>This report presents a comprehensive Google SEO analysis of '
                     f'<strong>{domain}</strong>, generated on {timestamp}. '
                     f'Data was collected from Google PageSpeed Insights, Chrome User Experience '
                     f'Report (CrUX), Google Search Console, and the URL Inspection API as available.</p>')
    lines.append('')

    # Metric cards row
    cards = []

    health_score = summary.get("health_score")
    if health_score is not None:
        cards.append(("health", f"{health_score}/100", "SEO Health Score", _score_color(float(health_score))))

    # PSI performance score
    psi = data.get("psi", {})
    mobile = psi.get("psi", {}).get("mobile", psi) if isinstance(psi, dict) else {}
    perf_score = mobile.get("lighthouse_scores", {}).get("performance")
    if perf_score is not None:
        color = _score_color(perf_score)
        cards.append(("perf", f"{perf_score}/100", "Lighthouse Performance", color))

    seo_score = mobile.get("lighthouse_scores", {}).get("seo")
    if seo_score is not None:
        color = _score_color(seo_score)
        cards.append(("seo", f"{seo_score}/100", "Lighthouse SEO", color))

    # GSC totals
    gsc = data.get("gsc", {})
    if gsc.get("totals"):
        clicks = gsc["totals"].get("clicks", 0)
        cards.append(("clicks", f"{clicks:,}", "Total Clicks", BRAND["primary"]))
        impr = gsc["totals"].get("impressions", 0)
        cards.append(("impr", f"{impr:,}", "Impressions", BRAND["secondary"]))

    # Indexation
    inspection = data.get("inspection", {})
    if inspection.get("summary"):
        indexed = inspection["summary"].get("pass", 0)
        total = inspection.get("total", 0)
        cards.append(("idx", f"{indexed}/{total}", "Indexed URLs", BRAND["success"]))

    # Render metric cards in a compact row
    if cards:
        col_class = "four-col" if len(cards) >= 4 else "two-col"
        display_cards = cards[:5]
        lines.append(f'  <div class="{col_class}">')
        for _, val, lbl, clr in display_cards:
            lines.append('    <div class="col">')
            lines.append(_metric_card(val, lbl, clr))
            lines.append('    </div>')
        lines.append('  </div>')
        lines.append('')

    # Critical issues box
    issues = []
    for item in _coerce_items(summary.get("top_findings")):
        title = _finding_title(item)
        # Only label a severity when the finding actually carries one. Plain-string
        # top_findings (the shape documented in seo-audit/SKILL.md) have no severity, and
        # _finding_severity() falls back to "Info" -- which rendered every entry in the
        # "Critical Issues Found" box as "Info:", understating the whole section.
        if isinstance(item, dict) and item.get("severity"):
            issues.append(f'<strong>{escape(str(item["severity"]))}:</strong> {escape(title)}')
        else:
            issues.append(escape(title))

    failed_audits = mobile.get("failed_audits", [])
    if failed_audits:
        top_fail = sorted(failed_audits, key=lambda a: a.get("score", 1))[:3]
        for a in top_fail:
            issues.append(f'<strong>{a.get("title", "Unknown")}</strong> '
                          f'(score: {a.get("score", 0):.0%})')

    seo_audits = mobile.get("seo_audits", [])
    seo_failed = [a for a in seo_audits if not a.get("pass")]
    for a in seo_failed[:2]:
        issues.append(f'<strong>SEO:</strong> {a.get("title", "Unknown")}')

    inspect_fails = inspection.get("summary", {}).get("fail", 0)
    if inspect_fails:
        issues.append(f'<strong>{inspect_fails} URL(s)</strong> not indexed')

    if issues:
        issue_items = "\n".join(f"      <li>{i}</li>" for i in issues[:5])
        lines.append('  <div class="critical-box">')
        lines.append('    <strong>Critical Issues Found:</strong>')
        lines.append('    <ol>')
        lines.append(issue_items)
        lines.append('    </ol>')
        lines.append('  </div>')
        lines.append('')

    # Quick wins box
    wins = []
    for item in _coerce_items(summary.get("quick_wins")):
        wins.append(escape(str(item)))

    qw = gsc.get("quick_wins", [])
    if qw:
        wins.append(f'{len(qw)} search queries at positions 4-10 with high impressions '
                    f'(check intent fit before optimising)')

    opps = mobile.get("opportunities", [])
    for o in opps[:3]:
        savings = o.get("savings_ms", 0)
        if savings:
            wins.append(f'{o.get("title", "Optimization")}: save ~{savings}ms')

    if wins:
        win_items = "\n".join(f"      <li>{w}</li>" for w in wins[:5])
        lines.append('  <div class="success-box">')
        lines.append('    <strong>Quick Wins:</strong>')
        lines.append('    <ol>')
        lines.append(win_items)
        lines.append('    </ol>')
        lines.append('  </div>')
        lines.append('')

    lines.append('</div>')
    return "\n".join(lines)


def _build_cwv_section(psi_data, crux_data, chart_paths, history_data=None, section_num=2):
    """Build the Core Web Vitals audit section."""
    fig_counter = [1]  # mutable counter for figure numbering

    def next_fig():
        n = fig_counter[0]
        fig_counter[0] += 1
        return n

    lines = []
    lines.append(f'\n<!-- {"=" * 55} {section_num}. CORE WEB VITALS {"=" * 3} -->')
    lines.append('<div class="section">')
    lines.append('  <div class="section-header">')
    lines.append(f'    <h2>{section_num}. Core Web Vitals &amp; Performance</h2>')

    # Section score from Lighthouse performance
    psi = psi_data if isinstance(psi_data, dict) else {}
    mobile = psi.get("psi", {}).get("mobile", psi)
    scores = mobile.get("lighthouse_scores", {})
    perf = scores.get("performance")
    if perf is not None:
        color = _score_color(perf)
        lines.append(f'    <div class="section-score" style="color: {color};">{perf}/100</div>')

    lines.append('  </div>')
    lines.append('')

    # 2.1 Lighthouse Scores gauges
    if scores:
        lines.append(f'  <h3>{section_num}.1 Lighthouse Scores</h3>')
        lines.append('')
        gauges_path = chart_paths.get("gauges_path", "")
        lines.append(_chart_html(
            gauges_path,
            "Lighthouse audit scores across Performance, Accessibility, Best Practices, and SEO.",
            next_fig(),
            "Lighthouse gauge scores",
        ))

        # Scores summary table
        lines.append('  <table>')
        lines.append('    <thead>')
        lines.append('      <tr><th>Category</th><th>Score</th><th>Rating</th></tr>')
        lines.append('    </thead>')
        lines.append('    <tbody>')
        for key, label in [("performance", "Performance"), ("accessibility", "Accessibility"),
                           ("best-practices", "Best Practices"), ("seo", "SEO")]:
            s = scores.get(key)
            if s is not None:
                cls = "status-pass" if s >= 90 else ("status-warn" if s >= 50 else "status-fail")
                rating = "Good" if s >= 90 else ("Needs Work" if s >= 50 else "Poor")
                lines.append(f'      <tr><td>{label}</td><td class="{cls}">{s}</td><td>{rating}</td></tr>')
        lines.append('    </tbody>')
        lines.append('  </table>')
        lines.append('')

    # Divider between Lighthouse Scores and Lab Metrics
    lines.append('  <hr class="divider">')

    # 2.2 Lab Metrics
    lab = mobile.get("lab_metrics", {})
    if lab:
        lines.append(f'  <h3>{section_num}.2 Lab Metrics (Simulated)</h3>')
        lines.append('  <table>')
        lines.append('    <thead>')
        lines.append('      <tr><th>Metric</th><th>Value</th><th>Score</th><th>Threshold</th></tr>')
        lines.append('    </thead>')
        lines.append('    <tbody>')
        metric_labels = {
            "first-contentful-paint": "First Contentful Paint (FCP)",
            "largest-contentful-paint": "Largest Contentful Paint (LCP)",
            "total-blocking-time": "Total Blocking Time (TBT)",
            "cumulative-layout-shift": "Cumulative Layout Shift (CLS)",
            "speed-index": "Speed Index",
            "interactive": "Time to Interactive (TTI)",
        }
        thresholds = {
            "first-contentful-paint": "\u2264 1.8s",
            "largest-contentful-paint": "\u2264 2.5s",
            "total-blocking-time": "\u2264 200ms",
            "cumulative-layout-shift": "\u2264 0.1",
            "speed-index": "\u2264 3.4s",
            "interactive": "\u2264 3.8s",
        }
        for k, v in lab.items():
            score_val = v.get("score")
            score_pct = f"{score_val:.0%}" if score_val is not None else "N/A"
            cls = ("status-pass" if score_val and score_val >= 0.9
                   else ("status-warn" if score_val and score_val >= 0.5 else "status-fail"))
            label = metric_labels.get(k, k.replace("-", " ").title())
            threshold = thresholds.get(k, "n/a")
            lines.append(f'      <tr><td>{label}</td><td>{v.get("display", "")}</td>'
                         f'<td class="{cls}">{score_pct}</td><td>{threshold}</td></tr>')
        lines.append('    </tbody>')
        lines.append('  </table>')
        lines.append('')

    # 2.3 CrUX Field Data
    crux = crux_data if isinstance(crux_data, dict) else {}
    crux_metrics = crux.get("metrics", {})
    if crux_metrics:
        lines.append(f'  <h3>{section_num}.3 CrUX Field Data (28-day Rolling Average)</h3>')
        lines.append('')

        # Distribution chart
        dist_path = chart_paths.get("distributions_path", "")
        lines.append(_chart_html(
            dist_path,
            "Core Web Vitals field data distribution across Good, Needs Improvement, and Poor buckets.",
            next_fig(),
            "CWV distribution chart",
        ))

        lines.append('  <table>')
        lines.append('    <thead>')
        lines.append('      <tr><th>Metric</th><th>p75</th><th>Rating</th>'
                     '<th>Good %</th><th>NI %</th><th>Poor %</th></tr>')
        lines.append('    </thead>')
        lines.append('    <tbody>')
        for name, m in crux_metrics.items():
            rating = m.get("rating", "?")
            dist = m.get("distribution", {})
            unit = m.get("unit", "")
            p75 = m.get("p75", "?")
            display_val = f"{p75:.3f}" if name == "cumulative_layout_shift" else f"{p75}{unit}"
            cls = _rating_css_class(rating)
            lines.append(f'      <tr><td>{m.get("label", name)}</td><td>{display_val}</td>')
            lines.append(f'      <td class="{cls}">{rating.upper()}</td>')
            lines.append(f'      <td>{dist.get("good", "N/A")}%</td>'
                         f'<td>{dist.get("needs_improvement", "N/A")}%</td>'
                         f'<td>{dist.get("poor", "N/A")}%</td></tr>')
        lines.append('    </tbody>')
        lines.append('  </table>')

        cp = crux.get("collection_period", {})
        if cp:
            lines.append(f'  <p class="data-freshness">Collection period: {cp.get("first", "?")} '
                         f'to {cp.get("last", "?")}. CrUX data is a 28-day rolling average '
                         f'updated daily ~04:00 UTC.</p>')
        lines.append('')
    elif crux.get("error"):
        lines.append(f'  <h3>{section_num}.3 CrUX Field Data</h3>')
        lines.append(f'  <div class="highlight"><strong>CrUX Field Data:</strong> '
                     f'{crux["error"]}</div>')
        lines.append('')

    # CrUX History timeline
    if history_data and not history_data.get("error"):
        lines.append(f'  <h3>{section_num}.4 Core Web Vitals Trends (25-week)</h3>')
        timeline_path = chart_paths.get("timeline_path", "")
        lines.append(_chart_html(
            timeline_path,
            "CrUX p75 values over 25 weeks with Good/Poor threshold bands.",
            next_fig(),
            "CWV timeline trends",
        ))

        trends = history_data.get("trends", {})
        if trends:
            lines.append('  <table>')
            lines.append('    <thead>')
            lines.append('      <tr><th>Metric</th><th>Direction</th><th>Change</th>'
                         '<th>Earliest Avg</th><th>Latest Avg</th></tr>')
            lines.append('    </thead>')
            lines.append('    <tbody>')
            for name, t in trends.items():
                direction = t.get("direction", "?")
                cls = ("status-pass" if direction == "improving"
                       else ("status-fail" if direction == "degrading" else ""))
                lines.append(f'      <tr><td>{t.get("label", name)}</td>'
                             f'<td class="{cls}">{direction.upper()}</td>')
                lines.append(f'      <td>{t.get("change_pct", 0):+.1f}%</td>'
                             f'<td>{t.get("earliest_avg", "?")}</td>'
                             f'<td>{t.get("latest_avg", "?")}</td></tr>')
            lines.append('    </tbody>')
            lines.append('  </table>')
        lines.append('')

    # Failed audits
    failed = mobile.get("failed_audits", [])
    if failed:
        sub = f"{section_num}.5" if history_data and not history_data.get("error") else f"{section_num}.4"
        lines.append(f'  <h3>{sub} Failed / Warning Audits ({len(failed)})</h3>')
        lines.append('  <table>')
        lines.append('    <thead>')
        lines.append('      <tr><th>Audit</th><th>Score</th><th>Details</th></tr>')
        lines.append('    </thead>')
        lines.append('    <tbody>')
        for a in failed[:20]:
            score_pct = f"{a['score']:.0%}" if a.get("score") is not None else "?"
            lines.append(f'      <tr><td>{a.get("title", "")}</td>'
                         f'<td class="status-fail">{score_pct}</td>'
                         f'<td>{a.get("display", "")}</td></tr>')
        lines.append('    </tbody>')
        lines.append('  </table>')
        lines.append('')

    # SEO audit checks
    seo_audits = mobile.get("seo_audits", [])
    if seo_audits:
        seo_failed = [a for a in seo_audits if not a.get("pass")]
        if seo_failed:
            lines.append(f'  <h3>SEO Audit Issues ({len(seo_failed)})</h3>')
            for a in seo_failed:
                lines.append('  <div class="action-item critical">')
                lines.append(f'    <h4>{a.get("title", "")}</h4>')
                lines.append('  </div>')
        else:
            lines.append(f'  <div class="success-box"><strong>SEO:</strong> '
                         f'All {len(seo_audits)} Lighthouse SEO checks passed.</div>')
        lines.append('')

    # Accessibility issues
    a11y = mobile.get("accessibility_audits", [])
    if a11y:
        lines.append(f'  <h3>Accessibility Issues ({len(a11y)})</h3>')
        lines.append('  <table>')
        lines.append('    <thead>')
        lines.append('      <tr><th>Issue</th><th>Score</th></tr>')
        lines.append('    </thead>')
        lines.append('    <tbody>')
        for a in a11y:
            lines.append(f'      <tr><td>{a.get("title", "")}</td>'
                         f'<td class="status-fail">{a.get("score", 0):.0%}</td></tr>')
        lines.append('    </tbody>')
        lines.append('  </table>')
        lines.append('')

    # Opportunities
    opps = mobile.get("opportunities", [])
    if opps:
        lines.append(f'  <h3>Optimization Opportunities ({len(opps)})</h3>')
        lines.append('  <table>')
        lines.append('    <thead>')
        lines.append('      <tr><th>Opportunity</th><th>Estimated Savings</th></tr>')
        lines.append('    </thead>')
        lines.append('    <tbody>')
        for o in opps:
            lines.append(f'      <tr><td>{o.get("title", "")}</td>'
                         f'<td>{o.get("savings_ms", 0)}ms</td></tr>')
        lines.append('    </tbody>')
        lines.append('  </table>')
        lines.append('')

    lines.append('</div>')
    return "\n".join(lines), fig_counter[0]


def _build_gsc_section(gsc_data, chart_paths, section_num=3, fig_start=1):
    """Build the GSC Search Performance section."""
    fig_counter = [fig_start]
    gsc_warning = _gsc_anomaly_warning(gsc_data)

    def next_fig():
        n = fig_counter[0]
        fig_counter[0] += 1
        return n

    lines = []
    lines.append(f'\n<!-- {"=" * 55} {section_num}. SEARCH PERFORMANCE {"=" * 3} -->')
    lines.append('<div class="section">')
    lines.append('  <div class="section-header">')
    lines.append(f'    <h2>{section_num}. Search Console Performance</h2>')
    lines.append('  </div>')
    lines.append('')

    totals = gsc_data.get("totals", {})
    dr = gsc_data.get("date_range", {})

    if totals:
        domain = gsc_data.get("property", "?")
        lines.append(f'  <p>Period: {dr.get("start", "?")} to {dr.get("end", "?")} '
                     f'| Property: {domain}</p>')
        if gsc_warning:
            lines.append(f'  <div class="highlight"><strong>GSC data warning:</strong> '
                         f'{escape(gsc_warning)}</div>')
        queries_count = gsc_data.get("row_count", 0)
        impr_total = totals.get("impressions", 0)
        lines.append(f'  <p><strong>{domain}</strong> appeared in <strong>{queries_count}</strong> unique search queries '
                     f'with <strong>{impr_total:,}</strong> total impressions during this period.</p>')
        lines.append('')

        clicks_val = f'{totals.get("clicks", 0):,}'
        impr_val = f'{totals.get("impressions", 0):,}'
        ctr_val = f'{totals.get("ctr", 0)}%'
        rows_val = str(gsc_data.get("row_count", 0))

        # Metric cards in single row
        lines.append(f'  <h3>{section_num}.1 Key Metrics</h3>')
        lines.append('  <div class="four-col">')
        lines.append(f'    <div class="col">{_metric_card(clicks_val, "Total Clicks", BRAND["primary"])}</div>')
        lines.append(f'    <div class="col">{_metric_card(impr_val, "Total Impressions", BRAND["secondary"])}</div>')
        lines.append(f'    <div class="col">{_metric_card(ctr_val, "Average CTR", BRAND["accent"])}</div>')
        lines.append(f'    <div class="col">{_metric_card(rows_val, "Queries Found", BRAND["dark"])}</div>')
        lines.append('  </div>')
        lines.append('  <hr class="divider">')
        lines.append('')

    # Top queries chart
    queries_path = chart_paths.get("top_queries_path", "")
    if queries_path:
        lines.append(f'  <h3>{section_num}.2 Top Queries by Impressions</h3>')
        lines.append(_chart_html(
            queries_path,
            "Top search queries ranked by impression volume from Google Search Console (28-day period).",
            next_fig(),
            "Top queries bar chart",
        ))

    # Top queries table
    rows = gsc_data.get("rows", [])
    if rows:
        lines.append(f'  <h3>{section_num}.3 Query Detail Table</h3>')
        lines.append('  <table>')
        lines.append('    <thead>')
        lines.append('      <tr><th>#</th><th>Query</th><th>Clicks</th>'
                     '<th>Impressions</th><th>CTR</th><th>Position</th></tr>')
        lines.append('    </thead>')
        lines.append('    <tbody>')
        sorted_rows = sorted(rows, key=lambda r: r.get("impressions", 0), reverse=True)
        for i, r in enumerate(sorted_rows[:15], 1):
            query = r.get("query", r.get("keys", ["?"])[0])
            pos = r.get("position", 0)
            pos_cls = ("status-pass" if pos <= 3
                       else ("status-warn" if pos <= 10 else "status-fail"))
            lines.append(f'      <tr><td>{i}</td><td>{query}</td>'
                         f'<td>{r.get("clicks", 0)}</td>'
                         f'<td>{r.get("impressions", 0):,}</td>')
            lines.append(f'      <td>{r.get("ctr", 0)}%</td>'
                         f'<td class="{pos_cls}">{pos:.1f}</td></tr>')
        lines.append('    </tbody>')
        lines.append('  </table>')
        lines.append('')

    # Position analysis
    if rows:
        top3 = len([r for r in rows if r.get("position", 99) <= 3])
        top10 = len([r for r in rows if r.get("position", 99) <= 10])
        beyond = len([r for r in rows if r.get("position", 99) > 10])
        lines.append(f'  <h3>{section_num}.4 Query Position Analysis</h3>')
        lines.append('  <div class="two-col">')
        lines.append('    <div class="col">')
        lines.append(_metric_card(str(top3), "Queries in Top 3", BRAND["success"]))
        lines.append('    </div>')
        lines.append('    <div class="col">')
        lines.append(_metric_card(str(top10), "Queries in Top 10", BRAND["warning"]))
        lines.append('    </div>')
        lines.append('  </div>')
        if beyond:
            lines.append(f'  <p>{beyond} queries rank beyond position 10 '
                         f'and may benefit from content optimization.</p>')
        lines.append('')

    # Quick wins
    qw = gsc_data.get("quick_wins", [])
    if qw:
        lines.append(f'  <h3>{section_num}.5 Quick Wins ({len(qw)} opportunities)</h3>')
        lines.append('  <div class="highlight">These queries rank at position 4-10 with '
                     'high impressions. Check that the ranking page matches the intent of '
                     'each query before optimising it.</div>')
        lines.append('  <table>')
        lines.append('    <thead>')
        lines.append('      <tr><th>Query</th><th>Position</th>'
                     '<th>Impressions</th><th>Clicks</th></tr>')
        lines.append('    </thead>')
        lines.append('    <tbody>')
        for w in qw:
            query = w.get("keys", ["?"])[0] if w.get("keys") else w.get("query", "?")
            lines.append(f'      <tr><td>{query}</td>'
                         f'<td>{w.get("position", 0):.1f}</td>'
                         f'<td>{w.get("impressions", 0):,}</td>'
                         f'<td>{w.get("clicks", 0)}</td></tr>')
        lines.append('    </tbody>')
        lines.append('  </table>')
        lines.append('')

    lines.append('  <p class="data-freshness">Search Analytics data has a 2-3 day lag. '
                 'Data available for ~16 months.</p>')
    lines.append('</div>')
    return "\n".join(lines), fig_counter[0]


def _build_indexation_section(inspect_data, chart_paths, section_num=4, fig_start=1):
    """Build the Indexation Status section."""
    fig_counter = [fig_start]

    def next_fig():
        n = fig_counter[0]
        fig_counter[0] += 1
        return n

    lines = []
    lines.append(f'\n<!-- {"=" * 55} {section_num}. INDEXATION STATUS {"=" * 3} -->')
    lines.append('<div class="section">')
    lines.append('  <div class="section-header">')
    lines.append(f'    <h2>{section_num}. Indexation Status</h2>')
    lines.append('  </div>')
    lines.append('')

    summary = inspect_data.get("summary", {})
    total = inspect_data.get("total", 0)

    if summary:
        # Donut chart
        idx_path = chart_paths.get("index_status_path", "")
        if idx_path:
            fig_n = next_fig()
            lines.append(f'  <h3>{section_num}.1 Index Coverage Overview</h3>')
            lines.append('    <div class="chart-container">')
            lines.append(f'      <img src="{_file_uri(idx_path)}" style="width: 70%;" alt="Index status donut chart">')
            lines.append(f'      <div class="chart-caption">Figure {fig_n}: URL indexation status distribution from Google URL Inspection API.</div>')
            lines.append('    </div>')

        # Summary cards
        lines.append(f'  <p>Total URLs inspected: <strong>{total}</strong></p>')
        lines.append('  <div class="two-col">')
        lines.append('    <div class="col">')
        lines.append(_metric_card(summary.get("pass", 0), "Indexed", BRAND["success"]))
        lines.append('    </div>')
        lines.append('    <div class="col">')
        lines.append(_metric_card(summary.get("fail", 0), "Not Indexed", BRAND["danger"]))
        lines.append('    </div>')
        lines.append('  </div>')
        lines.append('')

        indexed = summary.get("pass", 0)
        if total > 0:
            rate = round((indexed / total) * 100, 1)
            lines.append(f'  <p><strong>Index Rate:</strong> {rate}% of inspected URLs are indexed by Google.</p>')
        if total > 0 and indexed > 0:
            pct = (indexed / total) * 100
            cls = "success-box" if pct >= 90 else ("highlight" if pct >= 70 else "critical-box")
            lines.append(f'  <div class="{cls}"><strong>Index Rate:</strong> '
                         f'{pct:.0f}% of inspected URLs are indexed.</div>')
            lines.append('')

    # Per-URL results table
    results = inspect_data.get("results", [])
    if results:
        lines.append(f'  <h3>{section_num}.2 Per-URL Results</h3>')
        lines.append('  <table>')
        lines.append('    <thead>')
        lines.append('      <tr><th>URL</th><th>Verdict</th>'
                     '<th>Coverage State</th><th>Last Crawl</th></tr>')
        lines.append('    </thead>')
        lines.append('    <tbody>')
        for r in results:
            verdict = r.get("verdict", "?")
            cls = ("status-pass" if verdict == "PASS"
                   else ("status-fail" if verdict == "FAIL" else ""))
            idx = r.get("index_status", {})
            cov = idx.get("coverage_state", r.get("error", "N/A"))
            crawl = idx.get("last_crawl_time", "N/A")
            if crawl and crawl != "N/A":
                crawl = crawl[:10]
            url_display = r.get("url", "?")
            lines.append(f'      <tr><td style="word-break:break-all;font-size:8pt;">'
                         f'{url_display}</td>')
            lines.append(f'      <td class="{cls}">{verdict}</td>'
                         f'<td>{cov}</td><td>{crawl}</td></tr>')
        lines.append('    </tbody>')
        lines.append('  </table>')
        lines.append('')

    # Rich results
    rich = inspect_data.get("rich_results", [])
    if rich:
        lines.append(f'  <h3>{section_num}.3 Rich Results Detected</h3>')
        lines.append('  <table>')
        lines.append('    <thead>')
        lines.append('      <tr><th>URL</th><th>Rich Result Type</th></tr>')
        lines.append('    </thead>')
        lines.append('    <tbody>')
        for rr in rich:
            lines.append(f'      <tr><td style="word-break:break-all;font-size:8pt;">'
                         f'{rr.get("url", "?")}</td>'
                         f'<td>{rr.get("type", "?")}</td></tr>')
        lines.append('    </tbody>')
        lines.append('  </table>')
        lines.append('')

    lines.append('  <p class="data-freshness">URL Inspection API: '
                 '2,000 inspections/day per property.</p>')
    lines.append('</div>')
    return "\n".join(lines), fig_counter[0]


def _build_recommendations(data, section_num=5):
    """Build prioritized recommendations section based on discovered issues."""
    lines = []
    lines.append(f'\n<!-- {"=" * 55} {section_num}. RECOMMENDATIONS {"=" * 3} -->')
    lines.append('<div class="section">')
    lines.append('  <div class="section-header">')
    lines.append(f'    <h2>{section_num}. Recommendations</h2>')
    lines.append('  </div>')
    lines.append('')
    lines.append('  <p>Prioritized action items based on the data collected. '
                 'Items are ranked by expected impact on search visibility and user experience.</p>')
    lines.append('')

    item_num = 0

    # Collect critical items
    critical_items = []
    psi = data.get("psi", {})
    mobile = psi.get("psi", {}).get("mobile", psi) if isinstance(psi, dict) else {}

    perf = mobile.get("lighthouse_scores", {}).get("performance")
    if perf is not None and perf < 50:
        critical_items.append(
            ("Improve Lighthouse Performance Score",
             f"Current score is {perf}/100. Focus on reducing Largest Contentful Paint "
             f"and Total Blocking Time. Defer non-critical JavaScript and optimize images.")
        )

    seo_failed = [a for a in mobile.get("seo_audits", []) if not a.get("pass")]
    for a in seo_failed[:2]:
        critical_items.append(
            (f"Fix SEO Issue: {a.get('title', 'Unknown')}",
             "This Lighthouse SEO check is failing. Address it to ensure proper crawling "
             "and indexing by search engines.")
        )

    inspect = data.get("inspection", {})
    not_indexed = inspect.get("summary", {}).get("fail", 0)
    if not_indexed:
        critical_items.append(
            (f"Resolve {not_indexed} Non-Indexed URL(s)",
             "These pages are not appearing in Google's index. Review coverage state, "
             "fix crawl errors, and request re-indexing via Search Console.")
        )

    if critical_items:
        lines.append('  <h3><span class="priority-tag priority-critical">CRITICAL</span> '
                     'Critical priority</h3>')
        for title, desc in critical_items:
            item_num += 1
            lines.append('  <div class="action-item critical">')
            lines.append(f'    <h4>{item_num}. {title}</h4>')
            lines.append(f'    <p>{desc}</p>')
            lines.append('  </div>')
        lines.append('')

    # High priority items
    high_items = []
    failed_audits = mobile.get("failed_audits", [])
    top_fails = sorted(failed_audits, key=lambda a: a.get("score", 1))[:5]
    for a in top_fails:
        if a.get("score", 1) < 0.5:
            high_items.append(
                (f"Address: {a.get('title', 'Unknown')}",
                 f"Score: {a['score']:.0%}. {a.get('display', 'Review and optimize this audit.')}")
            )

    opps = mobile.get("opportunities", [])
    for o in opps[:3]:
        savings = o.get("savings_ms", 0)
        if savings:
            high_items.append(
                (f"{o.get('title', 'Optimization')}",
                 f"Potential savings of ~{savings}ms. Implement this to improve page load speed.")
            )

    gsc = data.get("gsc", {})
    qw = gsc.get("quick_wins", [])
    if qw:
        high_items.append(
            (f"Optimize {len(qw)} Quick-Win Queries",
             "These queries rank at positions 4-10 with high impressions. Check that "
             "the ranking page matches the intent of each query, then improve on-page "
             "relevance and depth.")
        )

    if high_items:
        lines.append('  <h3><span class="priority-tag priority-high">HIGH</span> '
                     'High priority</h3>')
        for title, desc in high_items:
            item_num += 1
            lines.append('  <div class="action-item high">')
            lines.append(f'    <h4>{item_num}. {title}</h4>')
            lines.append(f'    <p>{desc}</p>')
            lines.append('  </div>')
        lines.append('')

    # Medium priority items
    medium_items = []
    a11y = mobile.get("accessibility_audits", [])
    if a11y:
        medium_items.append(
            (f"Fix {len(a11y)} Accessibility Issue(s)",
             "Accessibility improvements benefit SEO (Lighthouse score) and user experience. "
             "Address failing accessibility audits.")
        )

    acc_score = mobile.get("lighthouse_scores", {}).get("accessibility")
    if acc_score is not None and acc_score < 90 and not a11y:
        medium_items.append(
            ("Improve Accessibility Score",
             f"Current score: {acc_score}/100. Run a detailed accessibility audit "
             f"and address any violations.")
        )

    bp_score = mobile.get("lighthouse_scores", {}).get("best-practices")
    if bp_score is not None and bp_score < 90:
        medium_items.append(
            ("Address Best Practices Issues",
             f"Current score: {bp_score}/100. Review browser console for errors, "
             f"update deprecated APIs, and ensure HTTPS for all resources.")
        )

    if medium_items:
        lines.append('  <h3><span class="priority-tag priority-medium">MEDIUM</span> '
                     'Medium priority</h3>')
        for title, desc in medium_items:
            item_num += 1
            lines.append('  <div class="action-item medium">')
            lines.append(f'    <h4>{item_num}. {title}</h4>')
            lines.append(f'    <p>{desc}</p>')
            lines.append('  </div>')
        lines.append('')

    # If no recommendations were generated at all
    if item_num == 0:
        lines.append('  <div class="success-box"><strong>No critical issues detected.</strong> '
                     'Continue monitoring Core Web Vitals and search performance regularly.</div>')
        lines.append('')

    # Action groups: grouped by type of work, no dates, weeks or effort.
    groups = []
    quick = []
    if seo_failed:
        quick.append('Fix failing Lighthouse SEO checks')
    if a11y:
        quick.append(f'Address {len(a11y)} accessibility issue(s)')
    bp_score_val = mobile.get("lighthouse_scores", {}).get("best-practices")
    if bp_score_val is not None and bp_score_val < 90:
        quick.append('Review and fix Best Practices issues')
    if quick:
        groups.append(('Checks and fixes', quick))
    perf_items = []
    if perf is not None and perf < 50:
        perf_items.append('Optimize Largest Contentful Paint and Total Blocking Time')
    if not_indexed:
        perf_items.append(f'Resolve {not_indexed} non-indexed URL(s)')
    if opps:
        perf_items.append(f'Implement {len(opps)} performance optimization(s)')
    if perf_items:
        groups.append(('Performance &amp; indexation', perf_items))
    search_items = []
    if qw:
        search_items.append(
            f'Check intent fit, then on-page relevance, for {len(qw)} queries at positions 4-10'
        )
    if search_items:
        groups.append(('Content &amp; search', search_items))
    if groups:
        lines.append('  <hr class="divider">')
        lines.append('  <h3>Action Groups</h3>')
        lines.append('  <p>Grouped by type of work. Order of work and timing are agreed '
                     'separately.</p>')
        for heading, items in groups:
            lines.append('  <div class="roadmap-phase">')
            lines.append(f'    <h4>{heading}</h4>')
            lines.append('    <ul>')
            for item in items:
                lines.append(f'      <li>{item}</li>')
            lines.append('    </ul>')
            lines.append('  </div>')
        lines.append('')

    lines.append('</div>')
    return "\n".join(lines)


def _build_methodology_footer(domain, timestamp, gsc_warning=""):
    """Build the Data Sources & Methodology footer section."""
    warning_html = ""
    if gsc_warning:
        warning_html = (
            f'  <p class="data-freshness"><strong>GSC data warning:</strong> '
            f'{escape(gsc_warning)}</p>\n'
        )
    return (
        f'\n<!-- {"=" * 55} DATA SOURCES & METHODOLOGY {"=" * 3} -->\n'
        f'<div class="section">\n'
        f'  <div class="section-header">\n'
        f'    <h2>Data Sources &amp; Methodology</h2>\n'
        f'  </div>\n'
        f'  <table>\n'
        f'    <thead>\n'
        f'      <tr><th>Source</th><th>Description</th><th>Update Frequency</th></tr>\n'
        f'    </thead>\n'
        f'    <tbody>\n'
        f'      <tr><td>PageSpeed Insights API</td>\n'
        f'          <td>Lighthouse lab audit (mobile emulation, Moto G Power, slow 4G)</td>\n'
        f'          <td>Real-time</td></tr>\n'
        f'      <tr><td>Chrome UX Report (CrUX)</td>\n'
        f'          <td>28-day rolling field data from real Chrome users</td>\n'
        f'          <td>Daily ~04:00 UTC</td></tr>\n'
        f'      <tr><td>CrUX History API</td>\n'
        f'          <td>25-week p75 trend data per metric</td>\n'
        f'          <td>Weekly</td></tr>\n'
        f'      <tr><td>Google Search Console</td>\n'
        f'          <td>Search Analytics (clicks, impressions, CTR, position)</td>\n'
        f'          <td>2-3 day lag</td></tr>\n'
        f'      <tr><td>URL Inspection API</td>\n'
        f'          <td>Per-URL index status, coverage state, crawl info</td>\n'
        f'          <td>Real-time (2,000/day)</td></tr>\n'
        f'    </tbody>\n'
        f'  </table>\n'
        f'{warning_html}'
        f'  <p class="report-footnote">\n'
        f'    Report generated {timestamp}<br>\n'
        f'    Methodology based on Google Web Vitals thresholds, Search Console documentation, '
        f'and Lighthouse scoring algorithms.\n'
        f'  </p>\n'
        f'</div>\n'
    )


# ─── Report Assemblers ───────────────────────────────────────────────────────

def generate_report(report_type, data, domain, output_dir, output_format="pdf"):
    """
    Generate a complete professional PDF/HTML report.

    Args:
        report_type: 'cwv-audit', 'gsc-performance', 'indexation', or 'full'.
        data: Dictionary with all input data.
        domain: Domain name for the report header.
        output_dir: Directory for output files.
        output_format: 'pdf', 'html', or 'both'.

    Returns:
        Dictionary with output paths.
    """
    output_dir = Path(output_dir)
    charts_dir = output_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%B %d, %Y")
    result = {"report_type": report_type, "domain": domain, "files": [], "error": None}

    # ── Generate Charts ──────────────────────────────────────────────────────

    chart_paths = {}

    try:
        if report_type in ("cwv-audit", "full"):
            psi = data.get("psi", data)
            mobile = psi.get("psi", {}).get("mobile", psi) if isinstance(psi, dict) else {}
            path = chart_lighthouse_gauges(mobile, charts_dir)
            if path:
                chart_paths["gauges_path"] = path

            crux = data.get("crux", {})
            path = chart_cwv_distributions({"crux": crux} if crux else data, charts_dir)
            if path:
                chart_paths["distributions_path"] = path

            history = data.get("crux_history", {})
            if history and not history.get("error"):
                path = chart_cwv_timeline(history, charts_dir)
                if path:
                    chart_paths["timeline_path"] = path

        if report_type in ("gsc-performance", "full"):
            gsc = data.get("gsc", data)
            path = chart_top_queries(gsc, charts_dir)
            if path:
                chart_paths["top_queries_path"] = path

        if report_type in ("indexation", "full"):
            inspect = data.get("inspection", data)
            path = chart_index_status(inspect, charts_dir)
            if path:
                chart_paths["index_status_path"] = path
    except RuntimeError as exc:
        result["error"] = str(exc)
        return result

    # ── Build HTML Sections ──────────────────────────────────────────────────

    sections = []
    fig_num = 1

    # ── CWV-AUDIT report ─────────────────────────────────────────────────────
    if report_type == "cwv-audit":
        mobile = data.get("psi", data)
        if isinstance(mobile, dict):
            mobile = mobile.get("psi", {}).get("mobile", mobile)
        perf_score = mobile.get("lighthouse_scores", {}).get("performance") if isinstance(mobile, dict) else None

        sections.append(_build_title_page(
            domain, "Core Web Vitals Audit",
            "Performance &amp; User Experience Analysis",
            score=perf_score,
            score_label="Lighthouse Performance Score",
            meta_items=[timestamp, "PageSpeed Insights + CrUX"],
        ))

        # TOC
        toc_sections = [
            {"num": 1, "title": "Executive Summary", "subs": [
                "Key Metrics &amp; Critical Issues",
            ]},
            {"num": 2, "title": "Core Web Vitals &amp; Performance", "score": perf_score, "subs": [
                "Lighthouse Scores",
                "Lab Metrics",
                "CrUX Field Data",
                "Failed Audits &amp; SEO Checks",
            ]},
            {"num": 3, "title": "Recommendations", "subs": [
                "Prioritized Action Items",
            ]},
            {"num": 4, "title": "Data Sources &amp; Methodology", "subs": []},
        ]
        sections.append(_build_toc(toc_sections))

        sections.append(_build_executive_summary(domain, timestamp, data, report_type))

        cwv_html, fig_num = _build_cwv_section(
            data, data.get("crux", {}), chart_paths,
            data.get("crux_history"), section_num=2,
        )
        sections.append(cwv_html)

        sections.append(_build_recommendations(data, section_num=3))
        sections.append(_build_methodology_footer(domain, timestamp))

    # ── GSC-PERFORMANCE report ───────────────────────────────────────────────
    elif report_type == "gsc-performance":
        gsc = data.get("gsc", data)
        clicks = gsc.get("totals", {}).get("clicks", 0)

        sections.append(_build_title_page(
            domain, "Search Console Performance",
            "Google Search Analytics Report",
            score=f"{clicks:,}",
            score_label="Total Clicks",
            meta_items=[timestamp, "Google Search Console API"],
        ))

        toc_sections = [
            {"num": 1, "title": "Executive Summary", "subs": [
                "Key Metrics &amp; Quick Wins",
            ]},
            {"num": 2, "title": "Search Console Performance", "subs": [
                "Key Metrics",
                "Top Queries by Clicks",
                "Query Detail Table",
                "Position Analysis &amp; Quick Wins",
            ]},
            {"num": 3, "title": "Recommendations", "subs": [
                "Prioritized Action Items",
            ]},
            {"num": 4, "title": "Data Sources &amp; Methodology", "subs": []},
        ]
        sections.append(_build_toc(toc_sections))

        sections.append(_build_executive_summary(domain, timestamp, data, report_type))

        gsc_html, fig_num = _build_gsc_section(gsc, chart_paths, section_num=2)
        sections.append(gsc_html)

        sections.append(_build_recommendations(data, section_num=3))
        sections.append(_build_methodology_footer(domain, timestamp, _gsc_anomaly_warning(gsc)))

    # ── INDEXATION report ────────────────────────────────────────────────────
    elif report_type == "indexation":
        inspect = data.get("inspection", data)
        total = inspect.get("total", 0)

        sections.append(_build_title_page(
            domain, "Indexation Status Report",
            "URL Index Coverage Analysis",
            score=total,
            score_label="URLs Inspected",
            meta_items=[timestamp, "URL Inspection API"],
        ))

        toc_sections = [
            {"num": 1, "title": "Executive Summary", "subs": [
                "Index Coverage Overview",
            ]},
            {"num": 2, "title": "Indexation Status", "subs": [
                "Index Coverage Overview",
                "Per-URL Results",
            ]},
            {"num": 3, "title": "Recommendations", "subs": [
                "Prioritized Action Items",
            ]},
            {"num": 4, "title": "Data Sources &amp; Methodology", "subs": []},
        ]
        sections.append(_build_toc(toc_sections))

        sections.append(_build_executive_summary(domain, timestamp, data, report_type))

        idx_html, fig_num = _build_indexation_section(inspect, chart_paths, section_num=2)
        sections.append(idx_html)

        sections.append(_build_recommendations(data, section_num=3))
        sections.append(_build_methodology_footer(domain, timestamp))

    # ── FULL report ──────────────────────────────────────────────────────────
    elif report_type == "full":
        psi = data.get("psi", {})
        mobile = psi.get("psi", {}).get("mobile", psi) if isinstance(psi, dict) else {}
        perf_score = mobile.get("lighthouse_scores", {}).get("performance") if isinstance(mobile, dict) else None
        summary = data.get("summary", {}) if isinstance(data.get("summary"), dict) else {}
        health_score = summary.get("health_score")
        display_score = health_score if health_score is not None else perf_score
        has_audit_schema = bool(summary or data.get("categories") or data.get("action_plan"))

        sections.append(_build_title_page(
            domain, "Full SEO Audit Report" if has_audit_schema else "Google SEO Intelligence Report",
            "Comprehensive Analysis",
            score=display_score,
            score_label="SEO Health Score" if health_score is not None else ("Lighthouse Performance Score" if perf_score else None),
            meta_items=[timestamp, "Full Audit"],
        ))

        # Build TOC dynamically based on available data
        toc_sections = [
            {"num": 1, "title": "Executive Summary", "subs": [
                "Key Metrics, Critical Issues &amp; Quick Wins",
            ]},
        ]
        sec_num = 2
        if data.get("categories"):
            toc_sections.append({
                "num": sec_num, "title": "Audit Categories", "subs": [
                    "What Works",
                    "Findings by Severity",
                ],
            })
            sec_num += 1
        if data.get("psi") or data.get("crux"):
            toc_sections.append({
                "num": sec_num, "title": "Core Web Vitals &amp; Performance",
                "score": perf_score, "subs": [
                    "Lighthouse Scores &amp; Lab Metrics",
                    "CrUX Field Data &amp; Trends",
                    "Failed Audits &amp; Opportunities",
                ],
            })
            sec_num += 1
        if data.get("gsc"):
            toc_sections.append({
                "num": sec_num, "title": "Search Console Performance", "subs": [
                    "Key Metrics &amp; Top Queries",
                    "Position Analysis &amp; Quick Wins",
                ],
            })
            sec_num += 1
        if data.get("inspection"):
            toc_sections.append({
                "num": sec_num, "title": "Indexation Status", "subs": [
                    "Index Coverage &amp; Per-URL Results",
                ],
            })
            sec_num += 1
        if data.get("action_plan"):
            toc_sections.append({
                "num": sec_num, "title": "Action Plan", "subs": [
                    "Actions Grouped by Priority",
                ],
            })
        else:
            toc_sections.append({
                "num": sec_num, "title": "Recommendations", "subs": [
                    "Prioritized Action Items",
                ],
            })
        rec_num = sec_num
        sec_num += 1
        toc_sections.append({
            "num": sec_num, "title": "Data Sources &amp; Methodology", "subs": [],
        })

        sections.append(_build_toc(toc_sections))
        sections.append(_build_executive_summary(domain, timestamp, data, report_type))

        current_sec = 2
        if data.get("categories"):
            sections.append(_build_full_audit_categories(data, section_num=current_sec))
            current_sec += 1

        if data.get("psi") or data.get("crux"):
            cwv_html, fig_num = _build_cwv_section(
                data.get("psi", {}), data.get("crux", {}), chart_paths,
                data.get("crux_history"), section_num=current_sec,
            )
            sections.append(cwv_html)
            current_sec += 1

        if data.get("gsc"):
            gsc_html, fig_num = _build_gsc_section(
                data["gsc"], chart_paths,
                section_num=current_sec, fig_start=fig_num,
            )
            sections.append(gsc_html)
            current_sec += 1

        if data.get("inspection"):
            idx_html, fig_num = _build_indexation_section(
                data["inspection"], chart_paths,
                section_num=current_sec, fig_start=fig_num,
            )
            sections.append(idx_html)
            current_sec += 1

        action_html = _build_audit_action_plan(data, section_num=rec_num)
        if action_html:
            sections.append(action_html)
        else:
            sections.append(_build_recommendations(data, section_num=rec_num))
        sections.append(_build_methodology_footer(domain, timestamp, _gsc_anomaly_warning(data.get("gsc", {}))))

    # ── Assemble Final HTML ──────────────────────────────────────────────────

    css = _build_css(domain)
    body = "\n".join(sections)
    html_content = (
        f'<!DOCTYPE html>\n'
        f'<html lang="en">\n'
        f'<head>\n'
        f'<meta charset="UTF-8">\n'
        f'<style>\n'
        f'{css}\n'
        f'</style>\n'
        f'</head>\n'
        f'<body>\n'
        f'{body}\n'
        f'</body>\n'
        f'</html>\n'
    )

    # ── Write Output Files ───────────────────────────────────────────────────

    safe_domain = domain.replace(":", "_").replace("/", "_")
    base_name = f"Google-SEO-Report-{safe_domain}-{report_type}"

    if output_format in ("html", "both", "all"):
        html_path = output_dir / f"{base_name}.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        result["files"].append(str(html_path))

    if output_format in ("pdf", "both", "all"):
        if HTML is None:
            result["error"] = (
                "weasyprint is required for PDF generation. "
                "Install the report dependencies from requirements.txt."
            )
            return result
        pdf_path = output_dir / f"{base_name}.pdf"
        try:
            HTML(string=html_content).write_pdf(str(pdf_path))
            result["files"].append(str(pdf_path))
            # Post-generation review
            review = _review_pdf(str(pdf_path), html_content)
            if review:
                result["review"] = review
        except Exception as e:
            result["error"] = f"PDF generation failed: {e}"

    if output_format in ("xlsx", "all"):
        xlsx_path = generate_xlsx(data, domain, report_type, output_dir)
        if xlsx_path:
            result["files"].append(xlsx_path)

    return result


def _review_pdf(pdf_path: str, html_content: str) -> dict:
    """
    RULE: Always review the PDF before presenting to the user.
    Check for common rendering issues.
    """
    review = {"issues": [], "page_count": None, "file_size_kb": None}

    # File size
    try:
        size = os.path.getsize(pdf_path)
        review["file_size_kb"] = round(size / 1024, 1)
    except OSError:
        pass

    # Page count (if pypdf available)
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        review["page_count"] = len(reader.pages)
    except ImportError:
        review["issues"].append("pypdf missing, page-count check skipped")

    # HTML-level checks
    import re
    # Check for empty chart containers (img with no src)
    empty_imgs = re.findall(r'<img[^>]*src=""[^>]*>', html_content)
    if empty_imgs:
        review["issues"].append(f"{len(empty_imgs)} empty image tag(s) found")

    # Check for very short sections (might appear as mostly whitespace)
    sections = html_content.split('div class="section"')
    for i, sec in enumerate(sections[1:], 1):
        # Strip HTML tags to get text content
        text_only = re.sub(r'<[^>]+>', '', sec[:2000])
        text_only = re.sub(r'\s+', ' ', text_only).strip()
        if len(text_only) < 50:
            review["issues"].append(f"Section {i} has very little text content ({len(text_only)} chars)")

    # Check for duplicate content
    tables = re.findall(r'<table>.*?</table>', html_content, re.DOTALL)
    if len(tables) != len(set(tables)):
        review["issues"].append("Duplicate tables detected")

    if not review["issues"]:
        review["status"] = "PASS"
    else:
        review["status"] = f"WARN ({len(review['issues'])} issues)"

    return review


# ─── XLSX Export ──────────────────────────────────────────────────────────────

def generate_xlsx(data, domain, report_type, output_dir):
    """Generate Excel workbook from audit data.

    Returns path to generated .xlsx file, or None if openpyxl unavailable.
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("Warning: openpyxl not installed. Skipping xlsx. Install: pip install openpyxl", file=sys.stderr)
        return None

    wb = Workbook()
    output_dir = Path(output_dir)

    # Plain functional grid: header in row 1, bold Calibri, frozen header,
    # autofilter, no fills, colours or title blocks inside the grid.
    header_font = Font(name="Calibri", bold=True, size=11)
    body_font = Font(name="Calibri", size=11)

    def _style_header(ws, row=1):
        """Bold the header row (no fill or colour)."""
        for cell in ws[row]:
            cell.font = header_font

    def _finish_sheet(ws, last_col):
        """Freeze the header, add an autofilter and fit column widths."""
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:{last_col}{max(ws.max_row, 1)}"
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.font = body_font
        _auto_width(ws)

    def _auto_width(ws):
        """Auto-fit column widths based on content."""
        for col_cells in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col_cells[0].column)
            for cell in col_cells:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
            ws.column_dimensions[col_letter].width = min(max_len + 4, 60)

    def _rating(value):
        if value >= 90:
            return "pass"
        if value >= 50:
            return "warning"
        return "fail"

    # ── Summary Sheet (one filterable register) ──────────────────────────────
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Section", "Item", "Value", "Rating"])
    _style_header(ws)
    ws.append(["Report", "Domain", domain, ""])
    ws.append(["Report", "Report Type", report_type, ""])
    ws.append(["Report", "Generated", datetime.now().strftime("%Y-%m-%d %H:%M"), ""])

    if report_type in ("cwv-audit", "full"):
        psi = data.get("psi", data)
        mobile = psi.get("psi", {}).get("mobile", psi) if isinstance(psi, dict) else {}
        scores = mobile.get("lighthouse_scores", {}) if isinstance(mobile, dict) else {}
        for cat in ["performance", "accessibility", "best-practices", "best_practices", "seo"]:
            val = scores.get(cat)
            if isinstance(val, (int, float)):
                pct = int(val * 100) if val <= 1 else val
                label = cat.replace("_", " ").replace("-", " ").title()
                ws.append(["Lighthouse", label, pct, _rating(pct)])

        crux = data.get("crux", {})
        metrics = crux.get("metrics", {}) if isinstance(crux, dict) else {}
        for metric_name, metric_data in metrics.items():
            if isinstance(metric_data, dict):
                p75 = metric_data.get("percentile_p75", metric_data.get("p75", ""))
                rating = metric_data.get("category", "")
                ws.append(["Core Web Vitals (field)", metric_name, p75, rating])

    _finish_sheet(ws, "D")

    # ── GSC Queries Sheet ─────────────────────────────────────────────────────
    gsc = data.get("gsc", {})
    queries = gsc.get("queries", gsc.get("rows", []))
    if queries and isinstance(queries, list):
        ws2 = wb.create_sheet("Queries")
        ws2.append(["Query", "Clicks", "Impressions", "CTR", "Position"])
        _style_header(ws2)
        for row_data in queries[:500]:
            if isinstance(row_data, dict):
                keys = row_data.get("keys", [])
                query = keys[0] if keys else row_data.get("query", "")
                ws2.append([
                    query,
                    row_data.get("clicks", 0),
                    row_data.get("impressions", 0),
                    f"{row_data.get('ctr', 0):.2%}" if isinstance(row_data.get("ctr"), (int, float)) else str(row_data.get("ctr", "")),
                    round(row_data.get("position", 0), 1) if isinstance(row_data.get("position"), (int, float)) else row_data.get("position", ""),
                ])
        _finish_sheet(ws2, "E")

    # ── GSC Pages Sheet ───────────────────────────────────────────────────────
    pages = gsc.get("pages", [])
    if pages and isinstance(pages, list):
        ws3 = wb.create_sheet("Pages")
        ws3.append(["Page", "Clicks", "Impressions", "CTR", "Position"])
        _style_header(ws3)
        for row_data in pages[:500]:
            if isinstance(row_data, dict):
                keys = row_data.get("keys", [])
                page = keys[0] if keys else row_data.get("page", "")
                ws3.append([
                    page,
                    row_data.get("clicks", 0),
                    row_data.get("impressions", 0),
                    f"{row_data.get('ctr', 0):.2%}" if isinstance(row_data.get("ctr"), (int, float)) else str(row_data.get("ctr", "")),
                    round(row_data.get("position", 0), 1) if isinstance(row_data.get("position"), (int, float)) else row_data.get("position", ""),
                ])
        _finish_sheet(ws3, "E")

    # ── Indexation Sheet ──────────────────────────────────────────────────────
    inspection = data.get("inspection", {})
    results = inspection.get("results", [])
    if results and isinstance(results, list):
        ws4 = wb.create_sheet("Indexation")
        ws4.append(["URL", "Verdict", "Coverage State", "Indexing State", "Crawled As", "Last Crawl"])
        _style_header(ws4)
        for item in results[:500]:
            if isinstance(item, dict):
                result_data = item.get("inspectionResult", item)
                idx = result_data.get("indexStatusResult", {})
                ws4.append([
                    item.get("url", result_data.get("inspectedUrl", "")),
                    idx.get("verdict", ""),
                    idx.get("coverageState", ""),
                    idx.get("indexingState", ""),
                    idx.get("crawledAs", ""),
                    idx.get("lastCrawlTime", ""),
                ])
        _finish_sheet(ws4, "F")

    # ── Save ──────────────────────────────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d-%H%M")
    filename = f"Google-SEO-Report-{domain}-{timestamp}.xlsx"
    filepath = output_dir / filename
    wb.save(filepath)
    return str(filepath)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Google SEO Report Generator - Professional PDF/HTML reports"
    )
    parser.add_argument(
        "--type", "-t",
        choices=["cwv-audit", "gsc-performance", "indexation", "full"],
        required=True,
        help="Report type",
    )
    parser.add_argument("--data", "-d", help="Path to JSON data file (or pipe via stdin)")
    parser.add_argument("--domain", required=True, help="Domain name for the report header")
    parser.add_argument("--output-dir", "-o", default=".", help="Output directory (default: current)")
    parser.add_argument(
        "--format", "-f",
        choices=["pdf", "html", "xlsx", "both", "all"],
        default="pdf",
        help="Output format: pdf, html, xlsx, both (pdf+html), all (pdf+html+xlsx)",
    )
    parser.add_argument("--json", "-j", action="store_true", help="Output metadata as JSON")

    args = parser.parse_args()

    # Load data
    if args.data:
        try:
            with open(args.data, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error reading data file: {e}", file=sys.stderr)
            sys.exit(1)
    elif not sys.stdin.isatty():
        try:
            data = json.load(sys.stdin)
        except json.JSONDecodeError as e:
            print(f"Error parsing stdin JSON: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print("Error: Provide --data file or pipe JSON via stdin.", file=sys.stderr)
        sys.exit(1)

    result = generate_report(
        report_type=args.type,
        data=data,
        domain=args.domain,
        output_dir=args.output_dir,
        output_format=args.format,
    )

    if result.get("error"):
        print(f"Error: {result['error']}", file=sys.stderr)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for f in result.get("files", []):
            print(f"Generated: {f}")


if __name__ == "__main__":
    main()
