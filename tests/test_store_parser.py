import json
import re

from src.models import FetchResult, Status
from src.store_parser import (SKU_RE, classify_store, extract_sku_from_url, parse_store_product,
                              store_product_url)
from tests.conftest import fixture_text

REAL_FIXTURE = fixture_text("store_product_kohinoor.html")
SKU = "77733243-645c-4eac-8e69-63425e1cc09b"


def _next_data(fixture=REAL_FIXTURE):
    return json.loads(re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', fixture, re.S).group(1))


def _fixture_with(**availability_overrides):
    data = _next_data()
    avail = data["props"]["pageProps"]["catalog"]["variantsInfo"][0]["attributes"]["buyingOptions"]["singlePurchase"]["availability"]
    avail.update(availability_overrides)
    return f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></body></html>'


def test_url_helpers():
    assert store_product_url("https://www.hmtwatches.store", SKU) == f"https://www.hmtwatches.store/product/{SKU}"
    assert extract_sku_from_url(f"https://www.hmtwatches.store/product/{SKU}?srsltid=abc") == SKU
    assert extract_sku_from_url("https://www.hmtwatches.store/") is None
    assert SKU_RE.match(SKU) and not SKU_RE.match("not-a-uuid")


def test_real_out_of_stock_fixture():
    r = parse_store_product("t", SKU, REAL_FIXTURE)
    assert r.status == Status.OUT_OF_STOCK
    assert r.title == "HMT Kohinoor Quartz B Maroon Sunray"
    assert r.price == 2899


def test_in_stock_variant():
    r = parse_store_product("t", SKU, _fixture_with(inStock=True, isBuyable=True))
    assert r.status == Status.IN_STOCK


def test_conflicting_signals_are_unknown_never_in_stock():
    r = parse_store_product("t", SKU, _fixture_with(inStock=True, isBuyable=False))
    assert r.status == Status.UNKNOWN and r.possible_stock


def test_stale_oos_field_is_ignored():
    # the top-level attributes.oos field is known-unreliable; only buyingOptions counts
    data = _next_data()
    attrs = data["props"]["pageProps"]["catalog"]["variantsInfo"][0]["attributes"]
    attrs["oos"] = False  # contradicts the real (correct) availability block below it
    body = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'
    assert parse_store_product("t", SKU, body).status == Status.OUT_OF_STOCK


def test_missing_availability_fields_are_unknown():
    r = parse_store_product("t", SKU, _fixture_with(inStock=None))
    assert r.status == Status.UNKNOWN


def test_malformed_pages_are_unknown():
    assert parse_store_product("t", SKU, "<html>no next data here</html>").status == Status.UNKNOWN
    assert parse_store_product("t", SKU, '<script id="__NEXT_DATA__">not json</script>').status == Status.UNKNOWN


def test_wrong_sku_is_unknown():
    assert parse_store_product("t", "00000000-0000-0000-0000-000000000000", REAL_FIXTURE).status == Status.UNKNOWN


def test_classify_store_http_outcomes():
    assert classify_store("t", SKU, FetchResult(200, REAL_FIXTURE)).status == Status.OUT_OF_STOCK
    assert classify_store("t", SKU, FetchResult(403, "", blocked=True)).status == Status.BLOCKED
    assert classify_store("t", SKU, FetchResult(502, "", error="server error 502")).status == Status.ERROR
