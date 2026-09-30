import json

from src.models import FetchResult, Status
from src.parser import classify, extract_product_id_and_title, parse_product_view, product_view_url
from tests.conftest import fixture_text

REAL_OOS = fixture_text("product_view_out_of_stock.json")


def _variant(**changes):
    data = json.loads(REAL_OOS)
    data["product_details"].update(changes)
    return json.dumps(data)


def test_url():
    assert product_view_url("https://www.hmtwatches.in/", 534) == "https://www.hmtwatches.in/product_view?id=534"


def test_real_out_of_stock_fixture():
    r = parse_product_view("t", 534, REAL_OOS)
    assert r.status == Status.OUT_OF_STOCK
    assert r.title == "HMT Stellar DASL 10 R Black"
    assert r.price == 11299
    assert r.quantity == 0


def test_in_stock_variant():
    r = parse_product_view("t", 534, _variant(in_stock="yes", quantity=12))
    assert r.status == Status.IN_STOCK
    assert r.quantity == 12


def test_in_stock_quantity_as_string():
    assert parse_product_view("t", 534, _variant(in_stock="Yes", quantity="3")).status == Status.IN_STOCK


def test_conflicting_signals_are_unknown_never_in_stock():
    r = parse_product_view("t", 534, _variant(in_stock="yes", quantity=0))
    assert r.status == Status.UNKNOWN
    r = parse_product_view("t", 534, _variant(in_stock="no", quantity=4))
    assert r.status == Status.UNKNOWN and r.possible_stock


def test_unrecognised_flag_with_quantity_is_possible_stock():
    r = parse_product_view("t", 534, _variant(in_stock="maybe", quantity=2))
    assert r.status == Status.UNKNOWN and r.possible_stock
    r = parse_product_view("t", 534, _variant(in_stock=None, quantity=0))
    assert r.status == Status.UNKNOWN and not r.possible_stock


def test_malformed_pages_are_unknown():
    assert parse_product_view("t", 534, "<html>Not JSON</html>").status == Status.UNKNOWN
    assert parse_product_view("t", 534, "{}").status == Status.UNKNOWN
    assert parse_product_view("t", 534, "[]").status == Status.UNKNOWN
    assert parse_product_view("t", 534, "").status == Status.UNKNOWN


def test_wrong_product_id_is_unknown():
    assert parse_product_view("t", 999, REAL_OOS).status == Status.UNKNOWN


def test_classify_http_outcomes():
    assert classify("t", 534, FetchResult(200, REAL_OOS)).status == Status.OUT_OF_STOCK
    assert classify("t", 534, FetchResult(403, "", blocked=True)).status == Status.BLOCKED
    assert classify("t", 534, FetchResult(429, "", blocked=True)).status == Status.BLOCKED
    assert classify("t", 534, FetchResult(502, "", error="server error 502")).status == Status.ERROR
    assert classify("t", 534, FetchResult(None, "", error="timeout")).status == Status.ERROR
    assert classify("t", 534, FetchResult(404, "not found")).status == Status.ERROR


def test_extract_id_from_real_product_page():
    pid, title = extract_product_id_and_title(fixture_text("product_page_534.html"))
    assert pid == 534
    assert title == "HMT Stellar DASL 10 R Black"


def test_extract_id_ambiguous_returns_none():
    pid, _ = extract_product_id_and_title("getCompareProduct(1) favourite(2)")
    assert pid is None
