"""Add a watch to config/targets.yml from its HMT product page link.

    python -m src.add_target "https://www.hmtwatches.in/product_all_details?id=..."

Makes ONE request to the product page, finds HMT's numeric product id, verifies it
with one product_view request, and appends a target entry (comments are preserved).
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from .config import ConfigError, load_config
from .fetcher import Fetcher
from .logging_utils import setup_logging
from .parser import classify, extract_product_id_and_title, product_view_url

log = logging.getLogger("add_target")
ROOT = Path(__file__).resolve().parent.parent


def slugify(text: str) -> str:
    text = re.sub(r"^hmt\s+", "", text.strip(), flags=re.I)
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "watch"


def yaml_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_target(tid: str, name: str, product_id: int, url: str) -> str:
    return (
        f"  - id: {tid}\n"
        f"    name: {yaml_quote(name)}\n"
        f"    product_id: {product_id}\n"
        f"    url: {yaml_quote(url)}\n"
        f"    enabled: true\n"
        f"    rule: auto\n"
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", help="HMT product page link")
    ap.add_argument("--name", help="display name (default: title from the page)")
    ap.add_argument("--config", default=str(ROOT / "config" / "targets.yml"))
    args = ap.parse_args(argv)
    setup_logging()

    url = args.url.strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc.endswith("hmtwatches.in"):
        log.error("Please give an https://www.hmtwatches.in/... product link")
        return 2

    config_path = Path(args.config)
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        log.error("current config is invalid, fix it first: %s", exc)
        return 2

    fetcher = Fetcher(cfg.request)
    log.info("fetching product page once (HMT can take ~40s)...")
    page = fetcher.get(url)
    if page.blocked or page.http_status != 200:
        log.error("could not load the product page: %s (HTTP %s). If it says 404, open the watch on "
                  "hmtwatches.in again and copy a fresh link.", page.error, page.http_status)
        return 1
    product_id, title = extract_product_id_and_title(page.body)
    if product_id is None:
        log.error("could not find a unique product id on that page (site layout may have changed)")
        return 1

    for t in cfg.targets:
        if t.product_id == product_id:
            log.info("already watching product %s as '%s'; nothing to do", product_id, t.id)
            return 0

    time.sleep(2)
    check = classify("new", product_id, fetcher.get(product_view_url(cfg.base_url, product_id), referer=url))
    name = args.name or check.title or title or f"HMT product {product_id}"
    log.info("verified: product_id=%s title=%r current_status=%s", product_id, name, check.status.value)

    existing = {t.id for t in cfg.targets}
    tid, n = slugify(name), 2
    base_tid = tid
    while tid in existing:
        tid, n = f"{base_tid}_{n}", n + 1

    text = config_path.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    config_path.write_text(text + render_target(tid, name, product_id, url), encoding="utf-8")
    try:
        load_config(config_path)
    except ConfigError as exc:
        config_path.write_text(text, encoding="utf-8")
        log.error("result would be invalid, reverted: %s", exc)
        return 1
    log.info("added target '%s' (product %s) to %s", tid, product_id, config_path)
    print(f"ADDED id={tid} product_id={product_id} name={name!r} status={check.status.value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
