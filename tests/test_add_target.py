import shutil
from pathlib import Path

from src import add_target
from src.config import load_config
from src.models import FetchResult
from tests.conftest import fixture_text

REPO_CONFIG = Path(__file__).parent.parent / "config" / "targets.yml"
URL = "https://www.hmtwatches.in/product_all_details?id=NEW"


class FakeFetcher:
    def __init__(self, cfg):
        self.calls = []

    def get(self, url, referer=None):
        self.calls.append(url)
        if "product_view" in url:
            return FetchResult(200, fixture_text("product_view_out_of_stock.json").replace("534", "777"))
        return FetchResult(200, fixture_text("product_page_534.html").replace("534", "777"))


def test_add_target_appends_valid_entry(tmp_path, monkeypatch):
    cfg_path = tmp_path / "targets.yml"
    shutil.copy(REPO_CONFIG, cfg_path)
    monkeypatch.setattr(add_target, "Fetcher", FakeFetcher)
    monkeypatch.setattr(add_target.time, "sleep", lambda s: None)
    assert add_target.main([URL, "--config", str(cfg_path)]) == 0
    cfg = load_config(cfg_path)
    new = [t for t in cfg.targets if t.product_id == 777]
    assert len(new) == 1 and new[0].url == URL and new[0].id == "stellar_dasl_10_r_black"
    assert "# HMT Watch Stock Monitor" in cfg_path.read_text()  # comments preserved
    # adding again is a no-op
    assert add_target.main([URL, "--config", str(cfg_path)]) == 0
    assert len([t for t in load_config(cfg_path).targets if t.product_id == 777]) == 1


def test_rejects_non_hmt_url(tmp_path):
    assert add_target.main(["https://example.com/x", "--config", str(REPO_CONFIG)]) == 2


def test_slugify():
    assert add_target.slugify("HMT Janata - Blue Dial!") == "janata_blue_dial"
