"""Summarize the web server's per-request timings (part 6 of the report).

Get the file from the server first:   ./manage.sh fetch-timings
Then:                                  python3 analyze_timings.py timings.csv

Only the standard library is used, so any python3 works.
"""
import csv
import statistics
import sys

STAGES = [
    ("parse_us", "Process request and extract headers"),
    ("read_us", "Read file from Cloud Storage"),
    ("send_us", "Send response to client"),
    ("db_us", "Insert into database"),
    ("total_us", "Whole request"),
]


def percentile(sorted_values, p):
    if not sorted_values:
        return float("nan")
    k = (len(sorted_values) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def main(path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit(f"{path} has no timing rows")

    statuses = {}
    for r in rows:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    print(f"{len(rows)} requests timed; by status: "
          + ", ".join(f"{k}: {v}" for k, v in sorted(statuses.items())))
    print("All times in milliseconds.\n")

    header = (f"{'Stage':<38}{'count':>8}{'mean':>9}{'median':>9}"
              f"{'p95':>9}{'p99':>9}{'max':>10}")
    print(header)
    print("-" * len(header))
    for key, label in STAGES:
        values = sorted(float(r[key]) / 1000 for r in rows if r[key] not in ("", None))
        if not values:
            print(f"{label:<38}{0:>8}")
            continue
        print(f"{label:<38}{len(values):>8}{statistics.fmean(values):>9.2f}"
              f"{statistics.median(values):>9.2f}{percentile(values, 95):>9.2f}"
              f"{percentile(values, 99):>9.2f}{values[-1]:>10.2f}")
    print("\nThe Cloud Storage stage only runs for requests that reach the bucket "
          "(not banned, valid file name), so its count is lower.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "timings.csv")
