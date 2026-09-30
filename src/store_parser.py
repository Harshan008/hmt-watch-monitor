"""Parsing for hmtwatches.store — a *different* official HMT site from hmtwatches.in.

Verified 2026-09-30. Confirmed same owner via WHOIS (both registered to "HMT Limited,
Auxiliary Business Division", Bengaluru). Technically unrelated to the .in site: this one
is an Amazon-powered storefront (Next.js). Product pages embed a
`<script id="__NEXT_DATA__">` JSON blob. The authoritative stock signal is:

    props.pageProps.catalog.variantsInfo[].attributes.buyingOptions
        .singlePurchase.availability = {"inStock": bool, "isBuyable": bool, "isLimitedStock": bool}

NOTE: attributes.oos was observed STALE/WRONG on a real out-of-stock product (said
`false` while the page showed "Out of Stock" and inStock was `false`) — it is
intentionally ignored in favour of buyingOptions.singlePurchase.availability.

Known WAF behaviour: /search/*, /sitemap.xml, /robots.txt and /_next/data/* all returned
a CloudFront "Request blocked" 403 during inspection. Only /product/<sku> (a normal page
load) was tested and worked, so that is the only path this adapter uses.
"""
from __future__ import annotations

import html
import json
import re
from typing import Optional

from .models import CheckResult, FetchResult, Status

SKU_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_PRODUCT_URL_SKU_RE = re.compile(r"/product/([0-9a-f-]{36})", re.I)
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def store_product_url(base_url: str, sku: str) -> str:
    return f"{base_url.rstrip('/')}/product/{sku}"


def extract_sku_from_url(url: str) -> Optional[str]:
    m = _PRODUCT_URL_SKU_RE.search(url)
    return m.group(1).lower() if m else None


def _find_variant(catalog, sku: str) -> Optional[dict]:
    if not isinstance(catalog, dict):
        return None
    variants = catalog.get("variantsInfo")
    if not isinstance(variants, list):
        return None
    for v in variants:
        if isinstance(v, dict) and v.get("sku") == sku:
            return v
    return None


def _to_float(value) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def parse_store_product(target_id: str, sku: str, body: str) -> CheckResult:
    m = _NEXT_DATA_RE.search(body)
    if not m:
        return CheckResult(target_id, Status.UNKNOWN, note="no __NEXT_DATA__ found (site layout changed?)")
    try:
        data = json.loads(m.group(1))
    except (ValueError, TypeError):
        return CheckResult(target_id, Status.UNKNOWN, note="__NEXT_DATA__ is not valid JSON")

    pp = data.get("props", {}).get("pageProps", {}) if isinstance(data, dict) else {}
    variant = _find_variant(pp.get("catalog"), sku)
    if variant is None:
        return CheckResult(target_id, Status.UNKNOWN, note=f"no matching product variant for sku {sku}")

    attrs = variant.get("attributes") if isinstance(variant.get("attributes"), dict) else {}
    title = attrs.get("name")
    title = html.unescape(str(title)).strip() if title else None
    price_info = attrs.get("price") if isinstance(attrs.get("price"), dict) else {}
    price = _to_float(price_info.get("discountedPrice"))
    if price is None:
        price = _to_float(price_info.get("mrp"))

    buying = attrs.get("buyingOptions") if isinstance(attrs.get("buyingOptions"), dict) else {}
    single = buying.get("singlePurchase") if isinstance(buying.get("singlePurchase"), dict) else {}
    avail = single.get("availability") if isinstance(single.get("availability"), dict) else {}
    in_stock, is_buyable = avail.get("inStock"), avail.get("isBuyable")

    base = dict(target_id=target_id, title=title, price=price,
               raw={"inStock": in_stock, "isBuyable": is_buyable, "isLimitedStock": avail.get("isLimitedStock")})

    if not isinstance(in_stock, bool) or not isinstance(is_buyable, bool):
        return CheckResult(status=Status.UNKNOWN,
                           note=f"missing/invalid availability: inStock={in_stock!r} isBuyable={is_buyable!r}", **base)
    if not in_stock:
        return CheckResult(status=Status.OUT_OF_STOCK, note="inStock=false", **base)
    if is_buyable:
        return CheckResult(status=Status.IN_STOCK, note="inStock=true, isBuyable=true", **base)
    # inStock true but not buyable: unusual, worth a manual look rather than silence
    return CheckResult(status=Status.UNKNOWN, possible_stock=True,
                       note=f"conflict: inStock=true isBuyable={is_buyable}", **base)


def classify_store(target_id: str, sku: str, fetch: FetchResult) -> CheckResult:
    common = dict(http_status=fetch.http_status, latency_ms=fetch.latency_ms)
    if fetch.blocked:
        return CheckResult(target_id, Status.BLOCKED, note=fetch.error or "blocked", **common)
    if fetch.http_status != 200:
        return CheckResult(target_id, Status.ERROR, note=fetch.error or f"HTTP {fetch.http_status}", **common)
    result = parse_store_product(target_id, sku, fetch.body)
    result.http_status, result.latency_ms = fetch.http_status, fetch.latency_ms
    return result
