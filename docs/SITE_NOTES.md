# How HMT's sites expose stock

Maintainer notes, recorded 2026-09-30. HMT can change its sites at any time. If checks start returning
`UNKNOWN`, start here.

## Ownership

Both domains are registered to **HMT Limited, Auxiliary Business Division, Jalahalli, Bengaluru** (WHOIS).

| Domain | Registered | Platform |
|---|---|---|
| hmtwatches.in | 2005 | Laravel (PHP), nginx |
| hmtwatches.store | May 2025 | Next.js storefront on Amazon infrastructure (CloudFront + AWS WAF) |

## hmtwatches.in (used for all current watches)

**Stock endpoint**: the site's own quick-view request, no login or cookies needed.

```
GET https://www.hmtwatches.in/product_view?id=<numeric product id>
```

```json
{"product_details": {"id": 994, "product_title": "HMT Kohinoor Quartz B Maroon Sunray",
  "product_price": 2899, "model_no": "Kohinoor Quartz",
  "in_stock": "no", "quantity": 0, ...}}
```

- Out of stock: `in_stock: "no"`, `quantity: 0`
- In stock: `in_stock: "yes"`, `quantity > 0` (verified live with product 1177)
- The response is about 600 bytes. Latency ranges from under 1 s to about 35 s.

**Product ids**: product page links use Laravel-encrypted ids (`product_overview?id=eyJpdiI6...`). These
links **expire**, and a plain numeric id in the page URL just redirects to the homepage. The numeric id
appears in the page HTML as `getCompareProduct(<id>)`, which is what `src/add_target.py` reads.

**Finding a model**: product ids for variants of the same model are often close together. For example,
Kohinoor Quartz and Automatic variants sit at 984–994. Checking `product_view` for nearby ids, spaced a few
seconds apart, is a reliable fallback when search fails.

**Things that don't help**:
- The `search_keyword` POST only returns saved search suggestions, not products.
- `collections?type=collection&id=51` ("Kohinoor") shows "No Product Found" on HMT's own site.
- `search?keys=` returns 404.

**Blocking**: no 403 or 429 was seen during testing, including 20 sequential requests 2.5 s apart.

## hmtwatches.store (supported, but blocked from GitHub Actions)

**Stock data**: embedded in each product page as a `<script id="__NEXT_DATA__">` JSON blob.

```
GET https://www.hmtwatches.store/product/<sku uuid>
props.pageProps.catalog.variantsInfo[] → find the entry whose sku matches
  .attributes.buyingOptions.singlePurchase.availability = {inStock, isBuyable, isLimitedStock}
```

- A page can hold several colour variants. Always match on `sku`; `variantDimensions.color` gives the colour.
- `attributes.oos` is **stale**: it said `false` on a product that was clearly sold out. It is ignored.
- `?srsltid=` in shared links is a tracking parameter and is stripped.

**Blocking**: the AWS WAF returns an instant 403 ("Request blocked", about 60–110 ms) to GitHub Actions
runners. The same request works from a home connection, so the likely cause is an IP-reputation rule for
cloud and datacenter ranges. `/search/`, `/sitemap.xml`, `/robots.txt` and `/_next/data/` are also
WAF-blocked. This project does **not** try to get around the WAF (no proxies, no IP rotation, no header
spoofing).

## Local development gotcha

macOS's system Python 3.9 is built against LibreSSL 2.8.3, which fails the TLS handshake with
hmtwatches.store (`TLSV1_ALERT_PROTOCOL_VERSION`). `curl` and GitHub's Python 3.12 both work. This only
affects local runs against `.store`.
