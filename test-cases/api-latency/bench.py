"""Benchmark script for api-latency test case.

Measures p99, p95, p50 latency across multiple endpoints.
Outputs JSON for easy metric extraction.

Usage:
    uv run python bench.py --json
    uv run python bench.py --endpoint /api/items --iterations 50
"""

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request

ENDPOINTS = ["/api/items", "/api/items/42", "/api/stats", "/health"]
BASE_URL = "http://127.0.0.1:8000"


def measure_latency(url: str, iterations: int = 20) -> list[float]:
    latencies = []
    for _ in range(iterations):
        start = time.monotonic()
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp.read()
        except urllib.error.URLError:
            print(f"ERROR: Cannot connect to {url}", file=sys.stderr)
            sys.exit(1)
        elapsed = (time.monotonic() - start) * 1000  # ms
        latencies.append(elapsed)
    return latencies


def percentile(data: list[float], pct: float) -> float:
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (pct / 100)
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[f]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def run_benchmark(endpoints: list[str], iterations: int, json_output: bool):
    all_results = {}
    all_latencies = []

    for ep in endpoints:
        url = f"{BASE_URL}{ep}"
        lats = measure_latency(url, iterations)
        all_latencies.extend(lats)
        all_results[ep] = {
            "p50": round(percentile(lats, 50), 2),
            "p95": round(percentile(lats, 95), 2),
            "p99": round(percentile(lats, 99), 2),
            "mean": round(statistics.mean(lats), 2),
            "min": round(min(lats), 2),
            "max": round(max(lats), 2),
            "samples": len(lats),
        }

    overall_p99 = round(percentile(all_latencies, 99), 2)
    overall_p95 = round(percentile(all_latencies, 95), 2)
    overall_p50 = round(percentile(all_latencies, 50), 2)

    if json_output:
        output = {
            "p99_latency_ms": overall_p99,
            "p95_latency_ms": overall_p95,
            "p50_latency_ms": overall_p50,
            "endpoints": all_results,
        }
        print(json.dumps(output, indent=2))
    else:
        print("=== API Latency Benchmark ===")
        print(f"Overall p99: {overall_p99}ms")
        print(f"Overall p95: {overall_p95}ms")
        print(f"Overall p50: {overall_p50}ms")
        print("")
        for ep, stats in all_results.items():
            print(f"  {ep}: p50={stats['p50']}ms p95={stats['p95']}ms p99={stats['p99']}ms")


def main():
    global BASE_URL
    parser = argparse.ArgumentParser(description="API latency benchmark")
    parser.add_argument("--endpoint", action="append", help="Specific endpoint(s) to test")
    parser.add_argument("--iterations", type=int, default=20, help="Requests per endpoint")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Output JSON")
    parser.add_argument("--base-url", default=BASE_URL, help="Base URL")
    args = parser.parse_args()

    BASE_URL = args.base_url

    endpoints = args.endpoint or ENDPOINTS
    run_benchmark(endpoints, args.iterations, args.json_output)


if __name__ == "__main__":
    main()
