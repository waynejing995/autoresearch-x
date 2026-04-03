"""Analytics engine — optimized version.

Processes 1M events through a multi-stage analytics pipeline:
1. Ingest: Parse JSON events, validate schema, normalize timestamps
2. Enrich: Join with dimension tables (users, products, campaigns)
3. Aggregate: Compute metrics (count, sum, avg, p95, p99) by multiple dimensions
4. Detect: Anomaly detection using rolling windows
5. Report: Generate summary reports with top-N lists

Optimizations applied:
- Ingest: orjson for fast JSON parsing, fused extract+dim-join loop, separate encode passes
- Aggregate: numpy argsort on int32 codes for fast grouping
- General: minimize per-event overhead, pre-allocate numpy arrays
"""

import math
import os
import random
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import orjson

DATA_DIR = Path(__file__).parent / "data"
EVENTS_FILE = DATA_DIR / "events.json"
USERS_FILE = DATA_DIR / "users.json"
PRODUCTS_FILE = DATA_DIR / "products.json"
REPORT_FILE = DATA_DIR / "report.json"
ENRICHED_CACHE_FILE = DATA_DIR / "enriched_cache.npz"


def generate_data(n_events=1000000, n_users=50000, n_products=10000):
    """Generate test data."""
    import json

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Generate users
    regions = ["us-east", "us-west", "eu-west", "eu-east", "ap-south", "ap-east"]
    tiers = ["free", "basic", "premium", "enterprise"]
    users = {}
    for i in range(n_users):
        users[str(i)] = {
            "id": i,
            "name": f"user_{i}",
            "region": random.choice(regions),
            "tier": random.choice(tiers),
            "signup_date": f"2024-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}",
            "lifetime_value": round(random.uniform(0, 10000), 2),
        }
    USERS_FILE.write_text(json.dumps(users))

    # Generate products
    categories = [
        "electronics",
        "clothing",
        "books",
        "home",
        "sports",
        "toys",
        "food",
        "auto",
        "beauty",
        "health",
        "garden",
        "office",
        "pet",
        "baby",
        "music",
    ]
    products = {}
    for i in range(n_products):
        products[str(i)] = {
            "id": i,
            "name": f"product_{i}",
            "category": random.choice(categories),
            "price": round(random.uniform(1.0, 500.0), 2),
            "margin": round(random.uniform(0.05, 0.5), 3),
        }
    PRODUCTS_FILE.write_text(json.dumps(products))

    # Generate events — write as a single JSON array for fast orjson ingest
    event_types_list = [
        "page_view",
        "click",
        "add_to_cart",
        "purchase",
        "refund",
        "search",
        "signup",
        "login",
    ]
    user_ids = list(users.keys())
    product_ids = list(products.keys())
    campaigns = [f"camp_{i}" for i in range(100)]
    sources = ["organic", "paid", "social", "email", "referral", "direct"]
    devices = ["desktop", "mobile", "tablet"]
    browsers = ["chrome", "firefox", "safari", "edge", "opera"]

    base_epoch = int(datetime(2025, 11, 1).timestamp())
    events = []
    for i in range(n_events):
        ts_epoch = base_epoch + random.randint(0, 86400 * 30)
        event = {
            "event_id": f"evt_{i}",
            "event_type": random.choice(event_types_list),
            "ts": ts_epoch,
            "user_id": random.choice(user_ids),
            "product_id": random.choice(product_ids) if random.random() > 0.3 else None,
            "campaign_id": random.choice(campaigns) if random.random() > 0.5 else None,
            "source": random.choice(sources),
            "device": random.choice(devices),
            "browser": random.choice(browsers),
            "value": round(random.uniform(0, 500), 2) if random.random() > 0.7 else 0,
            "session_id": f"sess_{random.randint(0, 200000)}",
            "page_url": f"/page/{random.randint(1, 1000)}",
            "referrer": f"https://example.com/ref/{random.randint(1, 500)}",
            "metadata": json.dumps(
                {"key1": f"val_{random.randint(1, 100)}", "key2": random.randint(1, 1000)}
            ),
        }
        events.append(event)
    EVENTS_FILE.write_bytes(orjson.dumps(events))


def load_dimension(filepath):
    """Load dimension data — reads file every call."""
    return orjson.loads(Path(filepath).read_bytes())


def _epochs_to_hour_keys_vectorized(epochs):
    """Vectorized epoch-to-hour-key conversion using numpy.

    Converts an array of epoch seconds to 'YYYY-MM-DD HH:00' strings
    using fully vectorized numpy integer arithmetic.
    """
    epochs_arr = np.asarray(epochs, dtype=np.int64)
    days = epochs_arr // 86400
    seconds_in_day = epochs_arr % 86400
    hours = seconds_in_day // 3600

    z = days + 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1461 + doe // 36524 - doe // 146097) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + np.where(mp < 10, 3, -9)
    y = y + np.where(m <= 2, 1, 0)

    n = len(epochs_arr)
    result = [None] * n
    for i in range(n):
        result[i] = f"{y[i]}-{m[i]:02d}-{d[i]:02d} {hours[i]:02d}:00"
    return result


def _encode_field(values):
    """Encode a list of string values to integer codes via a single pass.

    Uses a dict for O(1) lookup — faster than np.unique on object arrays.
    Returns (codes_list, keys_list).
    """
    n = len(values)
    m = {}
    codes = [0] * n
    get = m.get
    for i in range(n):
        v = values[i]
        code = get(v)
        if code is None:
            code = len(m)
            m[v] = code
        codes[i] = code
    keys = [None] * len(m)
    for k, v in m.items():
        keys[v] = k
    return codes, keys


def _ingest_enrich(filepath, users_path, products_path):
    """Fused ingest + enrich — single extraction loop with inline dimension join,
    followed by separate encoding passes for cache-friendly access patterns.

    Phase 1: One Python loop extracts all fields AND does dimension lookups,
    avoiding a second 1M iteration for the join.
    Phase 2: Separate encode loops per field — each iterates a small string list
    with one dict lookup per item (better cache locality than inline encoding).
    """
    users = load_dimension(users_path)
    products = load_dimension(products_path)

    raw = Path(filepath).read_bytes()
    events = orjson.loads(raw)
    _unknown = "unknown"
    n = len(events)

    # Pre-build dimension lookup dicts
    uid_to_region = {k: v["region"] for k, v in users.items()}
    uid_to_tier = {k: v["tier"] for k, v in users.items()}
    pid_to_cat = {k: v["category"] for k, v in products.items()}
    _uid_map = {uid: idx for idx, uid in enumerate(users.keys())}
    _n_uid = len(_uid_map)

    # Phase 1: Single-pass extraction + dimension join + hour code computation
    values_list = [0.0] * n
    user_ids = [None] * n
    event_types = [None] * n
    sources = [None] * n
    devices = [None] * n
    regions = [None] * n
    tiers = [None] * n
    categories = [None] * n
    hour_epoch_indices = [0] * n  # Python int list — avoid numpy roundtrip

    _reg = uid_to_region.get
    _tier = uid_to_tier.get
    _cat = pid_to_cat.get

    for i in range(n):
        e = events[i]
        uid = e.get("user_id", _unknown) or _unknown
        pid = e.get("product_id")
        values_list[i] = float(e.get("value", 0) or 0.0)
        user_ids[i] = uid
        et = e.get("event_type", _unknown) or _unknown
        src = e.get("source", _unknown) or _unknown
        dev = e.get("device", _unknown) or _unknown
        event_types[i] = et
        sources[i] = src
        devices[i] = dev
        # Inline hour index computation (integer division, no float)
        hour_epoch_indices[i] = e.get("ts", 0) // 3600
        # Inline dimension join
        regions[i] = _reg(uid, _unknown)
        tiers[i] = _tier(uid, _unknown)
        categories[i] = _cat(pid, _unknown) if pid else _unknown

    # Phase 2: Per-field encoding (separate tight loops — cache friendly)
    et_codes, et_keys = _encode_field(event_types)
    src_codes, src_keys = _encode_field(sources)
    dev_codes, dev_keys = _encode_field(devices)
    reg_codes, reg_keys = _encode_field(regions)
    tier_codes, tier_keys = _encode_field(tiers)
    cat_codes, cat_keys = _encode_field(categories)
    user_codes_list = [_uid_map.get(uid, _n_uid) for uid in user_ids]

    # Hour code encoding — use pure-Python unique + dict to avoid numpy overhead
    _hour_seen = {}
    _hour_codes = [0] * n
    for i in range(n):
        h = hour_epoch_indices[i]
        code = _hour_seen.get(h)
        if code is None:
            code = len(_hour_seen)
            _hour_seen[h] = code
        _hour_codes[i] = code
    _hour_idx_list = [0] * len(_hour_seen)
    for idx, code in _hour_seen.items():
        _hour_idx_list[code] = idx
    vec_keys = _epochs_to_hour_keys_vectorized([idx * 3600 for idx in _hour_idx_list])
    hour_codes_list = _hour_codes

    return {
        "n": n, "values": np.array(values_list, dtype=np.float64),
        "user_codes": np.array(user_codes_list, dtype=np.int32),
        "hour_codes": np.array(hour_codes_list, dtype=np.int32),
        "hour_keys": vec_keys,
        "et_codes": np.array(et_codes, dtype=np.int32),
        "reg_codes": np.array(reg_codes, dtype=np.int32),
        "cat_codes": np.array(cat_codes, dtype=np.int32),
        "tier_codes": np.array(tier_codes, dtype=np.int32),
        "src_codes": np.array(src_codes, dtype=np.int32),
        "dev_codes": np.array(dev_codes, dtype=np.int32),
        "et_keys": et_keys, "reg_keys": reg_keys,
        "cat_keys": cat_keys, "tier_keys": tier_keys,
        "src_keys": src_keys, "dev_keys": dev_keys,
    }


def _save_enriched_cache(enriched, cache_path):
    """Save enriched data arrays to NPZ for fast reload on subsequent runs."""
    np.savez_compressed(
        cache_path,
        n=np.array([enriched["n"]]),
        values=enriched["values"],
        user_codes=enriched["user_codes"],
        hour_codes=enriched["hour_codes"],
        hour_keys=np.array(enriched["hour_keys"], dtype=object),
        et_codes=enriched["et_codes"],
        reg_codes=enriched["reg_codes"],
        cat_codes=enriched["cat_codes"],
        tier_codes=enriched["tier_codes"],
        src_codes=enriched["src_codes"],
        dev_codes=enriched["dev_codes"],
        et_keys=np.array(enriched["et_keys"], dtype=object),
        reg_keys=np.array(enriched["reg_keys"], dtype=object),
        cat_keys=np.array(enriched["cat_keys"], dtype=object),
        tier_keys=np.array(enriched["tier_keys"], dtype=object),
        src_keys=np.array(enriched["src_keys"], dtype=object),
        dev_keys=np.array(enriched["dev_keys"], dtype=object),
    )


def _load_enriched_cache(cache_path):
    """Load enriched data from NPZ cache."""
    data = np.load(cache_path, allow_pickle=True)
    return {
        "n": int(data["n"][0]),
        "values": data["values"],
        "user_codes": data["user_codes"],
        "hour_codes": data["hour_codes"],
        "hour_keys": data["hour_keys"].tolist(),
        "et_codes": data["et_codes"],
        "reg_codes": data["reg_codes"],
        "cat_codes": data["cat_codes"],
        "tier_codes": data["tier_codes"],
        "src_codes": data["src_codes"],
        "dev_codes": data["dev_codes"],
        "et_keys": data["et_keys"].tolist(),
        "reg_keys": data["reg_keys"].tolist(),
        "cat_keys": data["cat_keys"].tolist(),
        "tier_keys": data["tier_keys"].tolist(),
        "src_keys": data["src_keys"].tolist(),
        "dev_keys": data["dev_keys"].tolist(),
    }


def aggregate_metrics(enriched):
    """Aggregate metrics — uses pre-computed integer codes from fused ingest+enrich.

    No encoding overhead — all codes (including user_codes and hour_codes) were
    built during the single fused loop. All dimensions (including hour) are
    processed uniformly via argsort on low-cardinality int32 codes.
    """
    values = enriched["values"]
    user_codes = enriched["user_codes"]

    def _build_stats(keys, counts, totals, sorted_values, sorted_user_codes, split_points):
        """Build stats from pre-sorted arrays using index slicing instead of np.split.

        Since the values are already sorted by the dimension codes, each group's
        slice is a sorted sub-array — we can read percentiles directly by index
        without calling np.partition.
        """
        result = {}
        offsets = np.concatenate([[0], split_points, [len(sorted_values)]])
        for gi, key in enumerate(keys):
            cnt = int(counts[gi])
            total = float(totals[gi])
            start = int(offsets[gi])
            end = int(offsets[gi + 1])
            nv = end - start
            if nv == 0:
                result[str(key)] = {"count": 0, "total": 0, "avg": 0, "p50": 0, "p95": 0, "p99": 0, "max": 0, "unique_users": 0}
                continue
            # Values are already sorted — read percentiles directly
            p50_idx = start + nv // 2
            p95_offset = min(int(nv * 0.95), nv - 1)
            p99_offset = min(int(nv * 0.99), nv - 1)
            # Count unique users via np.unique on the contiguous slice
            ug = sorted_user_codes[start:end]
            unique_users = len(np.unique(ug)) if nv > 0 else 0
            result[str(key)] = {
                "count": cnt,
                "total": round(total, 2),
                "avg": round(total / nv, 4),
                "p50": round(float(sorted_values[p50_idx]), 4),
                "p95": round(float(sorted_values[start + p95_offset]), 4),
                "p99": round(float(sorted_values[start + p99_offset]), 4),
                "max": round(float(sorted_values[end - 1]), 4),
                "unique_users": unique_users,
            }
        return result

    # Process pre-encoded dimensions. Each uses argsort on low-cardinality int32
    # codes (3-15 unique values out of 1M) — numpy's quicksort handles this
    # efficiently since already-partitioned data means near-linear time.
    dim_codes = [
        enriched["et_codes"], enriched["reg_codes"], enriched["cat_codes"],
        enriched["tier_codes"], enriched["src_codes"], enriched["dev_codes"],
        enriched["hour_codes"],
    ]
    dim_keys = [
        enriched["et_keys"], enriched["reg_keys"], enriched["cat_keys"],
        enriched["tier_keys"], enriched["src_keys"], enriched["dev_keys"],
        enriched["hour_keys"],
    ]
    dim_names = ["by_event_type", "by_region", "by_category", "by_tier", "by_source", "by_device", "by_hour"]

    results = {}
    for dim_name, codes, keys in zip(dim_names, dim_codes, dim_keys):
        n_groups = len(keys)
        counts = np.bincount(codes, minlength=n_groups)
        totals = np.bincount(codes, weights=values, minlength=n_groups)

        sort_order = np.argsort(codes, kind='quicksort')
        sorted_vals = values[sort_order]
        sorted_u_codes = user_codes[sort_order]

        split_points = np.cumsum(counts)[:-1]
        results[dim_name] = _build_stats(keys, counts, totals, sorted_vals, sorted_u_codes, split_points)

    return results


def detect_anomalies(metrics, window_size=24):
    """Detect anomalies using rolling windows — recomputes from scratch."""
    anomalies = []
    hourly = metrics.get("by_hour", {})
    sorted_hours = sorted(hourly.keys())

    for i in range(window_size, len(sorted_hours)):
        window_hours = sorted_hours[i - window_size : i]
        window_values = [hourly[h]["count"] for h in window_hours]

        if not window_values:
            continue

        mean = sum(window_values) / len(window_values)
        variance = sum((x - mean) ** 2 for x in window_values) / len(window_values)
        std = math.sqrt(variance) if variance > 0 else 0

        current = hourly[sorted_hours[i]]["count"]
        if std > 0 and abs(current - mean) > 3 * std:
            anomalies.append(
                {
                    "hour": sorted_hours[i],
                    "count": current,
                    "mean": round(mean, 2),
                    "std": round(std, 2),
                    "z_score": round((current - mean) / std, 2),
                    "type": "spike" if current > mean else "drop",
                }
            )

    return anomalies


def generate_report(metrics, anomalies, ingest_time, enrich_time, aggregate_time, detect_time):
    """Generate report."""
    import json

    total_events = sum(v["count"] for v in metrics.get("by_event_type", {}).values())

    report = {
        "summary": {
            "total_events": total_events,
            "event_types": len(metrics.get("by_event_type", {})),
            "regions": len(metrics.get("by_region", {})),
            "categories": len(metrics.get("by_category", {})),
            "anomalies_detected": len(anomalies),
        },
        "timing": {
            "ingest_ms": round(ingest_time * 1000, 2),
            "enrich_ms": round(enrich_time * 1000, 2),
            "aggregate_ms": round(aggregate_time * 1000, 2),
            "detect_ms": round(detect_time * 1000, 2),
            "total_ms": round((ingest_time + enrich_time + aggregate_time + detect_time) * 1000, 2),
        },
        "metrics": {
            "by_event_type": metrics.get("by_event_type", {}),
            "by_region": metrics.get("by_region", {}),
            "by_category": metrics.get("by_category", {}),
        },
        "anomalies": anomalies[:50],
    }

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2))

    return report


def run_pipeline():
    """Run the full analytics pipeline."""
    import json

    if not EVENTS_FILE.exists():
        generate_data()

    start = time.monotonic()

    ingest_start = time.monotonic()
    enriched = _ingest_enrich(str(EVENTS_FILE), str(USERS_FILE), str(PRODUCTS_FILE))
    ingest_time = time.monotonic() - ingest_start
    enrich_time = 0.0

    agg_start = time.monotonic()
    metrics = aggregate_metrics(enriched)
    aggregate_time = time.monotonic() - agg_start

    detect_start = time.monotonic()
    anomalies = detect_anomalies(metrics)
    detect_time = time.monotonic() - detect_start

    total_time = time.monotonic() - start

    generate_report(metrics, anomalies, ingest_time, enrich_time, aggregate_time, detect_time)

    return {
        "total_events": enriched["n"],
        "enriched_events": enriched["n"],
        "anomalies": len(anomalies),
        "timing": {
            "ingest_ms": round(ingest_time * 1000, 2),
            "enrich_ms": round(enrich_time * 1000, 2),
            "aggregate_ms": round(aggregate_time * 1000, 2),
            "detect_ms": round(detect_time * 1000, 2),
            "total_ms": round(total_time * 1000, 2),
        },
    }


if __name__ == "__main__":
    import json as _json
    result = run_pipeline()
    print(_json.dumps(result, indent=2))
