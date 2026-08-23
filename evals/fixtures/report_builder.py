# Nightly meter-reading roll-up.
# Reads the raw meter CSV, throws away readings the loggers marked as suspect,
# and writes one average per site for the morning dashboard.

import csv
from collections import defaultdict

SUSPECT_FLAGS = {"E", "X", "?"}


def load_rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def is_usable(row):
    return row["flag"] not in SUSPECT_FLAGS and row["value"] != ""


def site_averages(rows):
    totals = defaultdict(float)
    seen = defaultdict(int)

    for row in rows:
        seen[row["site"]] += 1
        if not is_usable(row):
            continue
        totals[row["site"]] += float(row["value"])

    return {site: totals[site] / seen[site] for site in totals}


def write_dashboard(averages, path):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["site", "average"])
        for site in sorted(averages):
            writer.writerow([site, round(averages[site], 3)])


def main():
    rows = load_rows("raw_meters.csv")
    write_dashboard(site_averages(rows), "dashboard.csv")


if __name__ == "__main__":
    main()
