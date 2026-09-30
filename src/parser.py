"""HMT-specific parsing.

Verified 2026-09-30: the site's own quick-view request
    GET https://www.hmtwatches.in/product_view?id=<numeric id>
returns JSON like
    {"product_details": {"id": 534, "product_title": "...", "product_price": 11299,
                         "in_stock": "no", "quantity": 0, ...}, ...}
Only the out-of-stock shape ("no", 0) has been observed so far. The in-stock value is
assumed to be "yes"/quantity > 0; anything unexpected becomes UNKNOWN (never IN_STOCK),
with `possible_stock` set when quantity > 0 so the user can still be told to look.
"""
from __future__ import annotations

import html
import json
import re
from typing import Optional, Tuple

from .models import CheckResult, FetchResult, Status

YES_VALUES = {"yes", "y", "1", "true", "in stock", "instock", "available"}
NO_VALUES = {"no", "n", "0", "false", "out of stock", "outofstock", "unavailable", "sold out"}


def product_view_url(base_url: str, product_id: int) -> str:
    return f"{base_url.rstrip('/')}/product_view?id={int(product_id)}"


def _to_int(value) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"\s*-?\d+\s*", value):
        return int(value)
    return None


def _to_float(value) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").strip())
        except ValueError:
            return None
    return None


def parse_product_view(target_id: str, product_id: int, body: str) -> CheckResult:
    """Turn a product_view JSON body into a CheckResult (pure function, no network)."""
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return CheckResult(target_id, Status.UNKNOWN, note="response is not JSON (site layout changed?)")

    details = data.get("product_details") if isinstance(data, dict) else None
    if not isinstance(details, dict):
        return CheckResult(target_id, Status.UNKNOWN, note="no product_details in JSON")

    got_id = _to_int(details.get("id"))
    if got_id is not None and got_id != int(product_id):
        return CheckResult(target_id, Status.UNKNOWN, note=f"JSON is for product {got_id}, expected {product_id}")

    title = details.get("product_title")
    title = html.unescape(str(title)).strip() if title else None
    price = _to_float(details.get("product_price"))
    qty = _to_int(details.get("quantity"))
    raw_flag = details.get("in_stock")
    flag = str(raw_flag).strip().lower() if raw_flag is not None else None

    fields = {"in_stock": raw_flag, "quantity": details.get("quantity")}
    base = dict(target_id=target_id, title=title, price=price, quantity=qty, raw=fields)

    if flag in YES_VALUES:
        if qty is None or qty > 0:
            return CheckResult(status=Status.IN_STOCK, note="in_stock=yes", **base)
        return CheckResult(status=Status.UNKNOWN, note=f"conflict: in_stock={raw_flag!r} but quantity={qty}", **base)
    if flag in NO_VALUES:
        if qty is None or qty <= 0:
            return CheckResult(status=Status.OUT_OF_STOCK, note="in_stock=no", **base)
        return CheckResult(status=Status.UNKNOWN, possible_stock=True,
                           note=f"conflict: in_stock={raw_flag!r} but quantity={qty}", **base)
    # Unrecognised or missing flag
    return CheckResult(status=Status.UNKNOWN, possible_stock=bool(qty and qty > 0),
                       note=f"unrecognised in_stock={raw_flag!r}, quantity={qty}", **base)


def classify(target_id: str, product_id: int, fetch: FetchResult) -> CheckResult:
    """Combine a FetchResult with parsing into the final detector status."""
    common = dict(http_status=fetch.http_status, latency_ms=fetch.latency_ms)
    if fetch.blocked:
        return CheckResult(target_id, Status.BLOCKED, note=fetch.error or "blocked", **common)
    if fetch.http_status == 304:
        return CheckResult(target_id, Status.UNKNOWN, note="304 not modified (unexpected)", **common)
    if fetch.http_status != 200:
        return CheckResult(target_id, Status.ERROR, note=fetch.error or f"HTTP {fetch.http_status}", **common)
    result = parse_product_view(target_id, product_id, fetch.body)
    result.http_status, result.latency_ms = fetch.http_status, fetch.latency_ms
    return result


# ---- product page helpers (used by add_target) -------------------------------------

_ID_PATTERNS = (
    re.compile(r"getCompareProduct\((\d+)\)"),
    re.compile(r"favourite\((\d+)\)"),
    re.compile(r"notifyMe\((\d+)\)"),
)
_TITLE_RE = re.compile(r'<h3 class="product-title">\s*([^<]+?)\s*</h3>')


def extract_product_id_and_title(page_html: str) -> Tuple[Optional[int], Optional[str]]:
    """Find the numeric product id on an HMT product page. Returns (None, ...) if ambiguous."""
    ids = set()
    for pattern in _ID_PATTERNS:
        ids.update(int(m) for m in pattern.findall(page_html))
    title_match = _TITLE_RE.search(page_html)
    title = html.unescape(title_match.group(1)) if title_match else None
    if len(ids) == 1:
        return ids.pop(), title
    return None, title
