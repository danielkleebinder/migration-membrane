#!/usr/bin/env python3
import csv
import sys
from pathlib import Path


def load_csv(filepath):
    """Reads a benchmark CSV file and returns a dict mapping size -> duration."""
    data = {}
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Strip whitespace to handle messy CSV headers/values safely
            size = int(row["size"].strip())
            duration = float(row["duration"].strip())
            data[size] = duration
    return data


def normalize_benchmarks(
    membrane_path, stopcopy_path, precopy_path, output_path="normalized_data.csv"
):
    print(f"Loading data from:")
    print(f"  - Membrane:  {membrane_path}")
    print(f"  - StopCopy:  {stopcopy_path}")
    print(f"  - PreCopy:   {precopy_path}")

    # Load data
    membrane_data = load_csv(membrane_path)
    stopcopy_data = load_csv(stopcopy_path)
    precopy_data = load_csv(precopy_path)

    # Find common memory sizes present in all three files
    common_sizes = sorted(
        set(stopcopy_data.keys())
        & set(membrane_data.keys())
        & set(precopy_data.keys())
    )

    if not common_sizes:
        print("Error: No matching memory sizes found across the three files!")
        sys.exit(1)

    normalized_rows = []
    for size in common_sizes:
        base_dur = stopcopy_data[size]
        memb_dur = membrane_data[size]
        prec_dur = precopy_data[size]

        # Calculate normalized factors (Ratio relative to Stop-and-Copy = 1.0)
        memb_factor = memb_dur / base_dur
        prec_factor = prec_dur / base_dur

        normalized_rows.append(
            {
                "size": size,
                "membrane_factor": round(memb_factor, 4),
                "precopy_factor": round(prec_factor, 4),
                "stopcopy_duration": round(base_dur, 2),
                "membrane_duration": round(memb_dur, 2),
                "precopy_duration": round(prec_dur, 2),
            }
        )

    # Write output CSV
    fieldnames = [
        "size",
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
        f"\nSuccessfully normalized {len(normalized_rows)} data points."
    )
    print(f"Saved result to: {output_path}\n")


if __name__ == "__main__":
    # Accept command line arguments or fall back to default filenames
    memb_file = sys.argv[1] if len(sys.argv) > 1 else "membrane.csv"
    stop_file = sys.argv[2] if len(sys.argv) > 2 else "stopcopy.csv"
    prec_file = sys.argv[3] if len(sys.argv) > 3 else "precopy.csv"
    out_file = sys.argv[4] if len(sys.argv) > 4 else "normalized_data_size.csv"

    normalize_benchmarks(memb_file, stop_file, prec_file, out_file)