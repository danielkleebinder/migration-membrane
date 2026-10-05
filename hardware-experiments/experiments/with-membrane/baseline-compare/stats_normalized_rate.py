#!/usr/bin/env python3
import csv
import sys
from pathlib import Path


def load_csv(filepath):
    """Reads a benchmark CSV file and returns a dict mapping rate -> duration."""
    data = {}
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Strip whitespace to handle messy CSV headers/values safely
            rate = int(row["rate"].strip())
            duration = float(row["duration"].strip())
            data[rate] = duration
    return data


def normalize_benchmarks(
    membrane_path, stopcopy_path, precopy_path, output_path="normalized_data_rate.csv"
):
    print(f"Loading data from:")
    print(f"  - Membrane:  {membrane_path}")
    print(f"  - StopCopy:  {stopcopy_path}")
    print(f"  - PreCopy:   {precopy_path}")

    # Load data
    membrane_data = load_csv(membrane_path)
    stopcopy_data = load_csv(stopcopy_path)
    precopy_data = load_csv(precopy_path)

    # Union of all rates across all files (up to 140) instead of intersection (&)
    all_rates = sorted(
        set(stopcopy_data.keys())
        | set(membrane_data.keys())
        | set(precopy_data.keys())
    )

    if not all_rates:
        print("Error: No memory rates found across the files!")
        sys.exit(1)

    normalized_rows = []
    for rate in all_rates:
        # Stop-and-Copy and Membrane should always exist, but use safe get just in case
        base_dur = stopcopy_data.get(rate)
        memb_dur = membrane_data.get(rate)
        prec_dur = precopy_data.get(rate) # Might be missing for 120, 130, 140

        # Calculate factors safely
        memb_factor = (memb_dur / base_dur) if (memb_dur is not None and base_dur) else ""
        prec_factor = (prec_dur / base_dur) if (prec_dur is not None and base_dur) else ""

        normalized_rows.append(
            {
                "rate": rate,
                "membrane_factor": round(memb_factor, 4) if isinstance(memb_factor, float) else "",
                "precopy_factor": round(prec_factor, 4) if isinstance(prec_factor, float) else "",
                "stopcopy_duration": round(base_dur, 2) if base_dur is not None else "",
                "membrane_duration": round(memb_dur, 2) if memb_dur is not None else "",
                "precopy_duration": round(prec_dur, 2) if prec_dur is not None else "",
            }
        )

    # Write output CSV
    fieldnames = [
        "rate",
        "membrane_factor",
        "precopy_factor",
        "stopcopy_duration",
        "membrane_duration",
        "precopy_duration",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(normalized_rows)

    print(
        f"\nSuccessfully processed {len(normalized_rows)} data points up to rate {max(all_rates)}."
    )
    print(f"Saved result to: {output_path}\n")


if __name__ == "__main__":
    # Accept command line arguments or fall back to default filenames
    memb_file = sys.argv[1] if len(sys.argv) > 1 else "membrane.csv"
    stop_file = sys.argv[2] if len(sys.argv) > 2 else "stopcopy.csv"
    prec_file = sys.argv[3] if len(sys.argv) > 3 else "precopy.csv"
    out_file = sys.argv[4] if len(sys.argv) > 4 else "normalized_data_rate.csv"

    normalize_benchmarks(memb_file, stop_file, prec_file, out_file)