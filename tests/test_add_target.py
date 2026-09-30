import shutil
from pathlib import Path

from src import add_target
from src.config import load_config
from src.models import FetchResult
from tests.conftest import fixture_text

REPO_CONFIG = Path(__file__).parent.parent / "config" / "targets.yml"
URL_IN = "https://www.hmtwatches.in/product_all_details?id=NEW"
NEW_SKU = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
URL_STORE = f"https://www.hmtwatches.store/product/{NEW_SKU}?srsltid=tracking123"


class FakeFetcher:
    def __init__(self, cfg):
        self.calls = []

    def get(self, url, referer=None, extra_headers=None):
        self.calls.append(url)
        if "product_view" in url:
            return FetchResult(200, fixture_text("product_view_out_of_stock.json").replace("534", "777"))
        if "hmtwatches.store" in url:
            body = fixture_text("store_product_kohinoor.html").replace(
                "77733243-645c-4eac-8e69-63425e1cc09b", NEW_SKU)
            return FetchResult(200, body)
        return FetchResult(200, fixture_text("product_page_534.html").replace("534", "777"))


def test_add_target_appends_valid_entry(tmp_path, monkeypatch):
    cfg_path = tmp_path / "targets.yml"
    shutil.copy(REPO_CONFIG, cfg_path)
    monkeypatch.setattr(add_target, "Fetcher", FakeFetcher)
    monkeypatch.setattr(add_target.time, "sleep", lambda s: None)
    assert add_target.main([URL_IN, "--config", str(cfg_path)]) == 0
    cfg = load_config(cfg_path)
    new = [t for t in cfg.targets if t.site == "in" and t.product_id == 777]
    assert len(new) == 1 and new[0].url == URL_IN and new[0].id == "stellar_dasl_10_r_black"
    assert "# HMT sells through TWO official sites" in cfg_path.read_text()  # comments preserved
    # adding again is a no-op
    assert add_target.main([URL_IN, "--config", str(cfg_path)]) == 0
    assert len([t for t in load_config(cfg_path).targets if t.site == "in" and t.product_id == 777]) == 1


def test_add_target_store_site_strips_tracking_params(tmp_path, monkeypatch):
    cfg_path = tmp_path / "targets.yml"
    shutil.copy(REPO_CONFIG, cfg_path)
    monkeypatch.setattr(add_target, "Fetcher", FakeFetcher)
    assert add_target.main([URL_STORE, "--config", str(cfg_path)]) == 0
    cfg = load_config(cfg_path)
    new = [t for t in cfg.targets if t.site == "store" and t.product_id == NEW_SKU]
    assert len(new) == 1
    assert new[0].url == f"https://www.hmtwatches.store/product/{NEW_SKU}"  # tracking param stripped
    assert "srsltid" not in cfg_path.read_text()
    # adding again is a no-op, even with a different tracking param
    assert add_target.main([URL_STORE.replace("tracking123", "other456"), "--config", str(cfg_path)]) == 0
    assert len([t for t in load_config(cfg_path).targets if t.site == "store" and t.product_id == NEW_SKU]) == 1


def test_rejects_non_hmt_url(tmp_path):
    assert add_target.main(["https://example.com/x", "--config", str(REPO_CONFIG)]) == 2


def test_rejects_store_url_missing_sku(tmp_path, monkeypatch):
    monkeypatch.setattr(add_target, "Fetcher", FakeFetcher)
    assert add_target.main(["https://www.hmtwatches.store/", "--config", str(REPO_CONFIG)]) == 2


def test_slugify():
    assert add_target.slugify("HMT Janata - Blue Dial!") == "janata_blue_dial"


def test_detect_site():
    assert add_target.detect_site(URL_IN) == "in"
    assert add_target.detect_site(URL_STORE) == "store"
