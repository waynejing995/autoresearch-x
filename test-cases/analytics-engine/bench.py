"""Benchmark script for analytics-engine test case."""

import argparse
import json
import statistics
import sys


def run_benchmark(iterations: int = 3, json_output: bool = False):
    from analytics import run_pipeline

    all_times = []
    all_stage_times = {"ingest": [], "enrich": [], "aggregate": [], "detect": []}

    for i in range(iterations):
        result = run_pipeline()
        timing = result["timing"]
        all_times.append(timing["total_ms"])
        all_stage_times["ingest"].append(timing["ingest_ms"])
        all_stage_times["enrich"].append(timing["enrich_ms"])
        all_stage_times["aggregate"].append(timing["aggregate_ms"])
        all_stage_times["detect"].append(timing["detect_ms"])

    def pct(data, p):
        sorted_data = sorted(data)
        k = (len(sorted_data) - 1) * (p / 100)
        f = int(k)
        c = f + 1
        if c >= len(sorted_data):
            return sorted_data[f]
        return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])

    output = {
        "pipeline_total_ms_p99": round(pct(all_times, 99), 2),
        "pipeline_total_ms_p50": round(pct(all_times, 50), 2),
        "pipeline_total_ms_mean": round(statistics.mean(all_times), 2),
        "stages": {
            stage: {
                "p99": round(pct(times, 99), 2),
                "p50": round(pct(times, 50), 2),
                "mean": round(statistics.mean(times), 2),
            }
            for stage, times in all_stage_times.items()
        },
        "iterations": iterations,
        "event_count": 1000000,
    }

    if json_output:
        print(json.dumps(output, indent=2))
    else:
        print(f"=== Analytics Engine Benchmark ===")
        print(f"Events: {output['event_count']}")
        print(f"Iterations: {output['iterations']}")
        print(f"")
        print(f"Total pipeline time:")
        print(f"  p99: {output['pipeline_total_ms_p99']}ms")
        print(f"  p50: {output['pipeline_total_ms_p50']}ms")
        print(f"  mean: {output['pipeline_total_ms_mean']}ms")
        print(f"")
        print(f"Per-stage (p99):")
        for stage, stats in output["stages"].items():
            print(f"  {stage}: p99={stats['p99']}ms p50={stats['p50']}ms mean={stats['mean']}ms")


def main():
    parser = argparse.ArgumentParser(description="Analytics engine benchmark")
    parser.add_argument("--iterations", type=int, default=3, help="Benchmark iterations")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Output JSON")
    args = parser.parse_args()

    run_benchmark(args.iterations, args.json_output)


if __name__ == "__main__":
    main()
