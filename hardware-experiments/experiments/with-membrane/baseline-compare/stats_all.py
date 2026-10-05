import os
import re
import csv
import glob
import statistics
from collections import defaultdict


def process_directory(runs_dir, output_prefix):
    print(f"\n--- Processing directory: {runs_dir} ---")

    if not os.path.exists(runs_dir):
        print(f"[Error] Directory {runs_dir} does not exist. Skipping.")
        return

    # Dictionary to group iterations by configuration, then pair sat1/sat2:
    # {(type, size, rate): { '1': {'sat1': file, 'sat2': file}, ... }}
    experiments = defaultdict(lambda: defaultdict(dict))

    # 1. Extracts Iteration, Node, Size, and Rate from the filename
    file_pattern = re.compile(r"it(\d+)_(sat[12])_mem(\d+)_rate(\d+)\.log")

    # 2. Looks inside the strategy subdirectories
    search_pattern = os.path.join(runs_dir, "*", "*.log")

    for filepath in glob.glob(search_pattern):
        filename = os.path.basename(filepath)

        parent_folder = os.path.basename(os.path.dirname(filepath))
        mig_type = parent_folder.replace("-", "")

        match = file_pattern.match(filename)
        if match:
            iteration, node, size, rate = match.groups()
            config_key = (mig_type, size, rate)
            experiments[config_key][iteration][node] = filepath

    membrane_results = []
    pre_results = []
    post_results = []
    stop_results = []

    # Parse paired logs across all iterations
    for (mig_type, size, rate), iterations in experiments.items():
        durations = []
        downtimes = []

        for iteration, nodes in iterations.items():
            if 'sat1' not in nodes or 'sat2' not in nodes:
                print(
                    f"[Warning] Missing a node log for {mig_type} (size: {size}, rate: {rate}) in iteration {iteration}. Skipping.")
                continue

            sat1_file = nodes['sat1']
            sat2_file = nodes['sat2']

            duration = None
            sat1_time = None
            sat2_time = None

            # Parse sat1 log
            with open(sat1_file, "r") as f1:
                for line in f1:
                    if mig_type in ["precopy"] and "Migration took" in line:
                        m = re.search(r"Migration took ([\d.]+)\s*ms", line)
                        if m: duration = float(m.group(1))
                    elif mig_type in ["membrane", "stopcopy"] and "Migration completed in" in line:
                        m = re.search(r"Migration completed in ([\d.]+)\s*ms", line)
                        if m: duration = float(m.group(1))
                    elif mig_type in ["postcopy"] and "Total session duration" in line:
                        m = re.search(r"Total session duration: ([\d.]+)\s*ms", line)
                        if m: duration = float(m.group(1))

                    if mig_type == "postcopy" and "Entering background page server mode" in line:
                        m = re.search(r"Entering background page server mode \(at ([\d.]+)\s*ms\)", line)
                        if m: sat1_time = float(m.group(1))
                    elif "Live migration completed at" in line:
                        m = re.search(r"Live migration completed at ([\d.]+)\s*ms", line)
                        if m: sat1_time = float(m.group(1))

            # Parse sat2 log
            with open(sat2_file, "r") as f2:
                for line in f2:
                    if "Live migration restored at" in line:
                        m = re.search(r"Live migration restored at ([\d.]+)\s*ms", line)
                        if m: sat2_time = float(m.group(1))
                    elif "Resuming bytecode function" in line:
                        m = re.search(r"Resuming bytecode function \(([\d.]+)\)", line)
                        if m: sat2_time = float(m.group(1))

            # Independently collect available metrics
            if duration is not None:
                durations.append(duration)

            if sat1_time is not None and sat2_time is not None:
                downtimes.append(abs(sat2_time - sat1_time))

            if duration is None or sat1_time is None or sat2_time is None:
                print(f"[Warning] Could not extract all metrics for {sat1_file} and {sat2_file} (Duration: {duration}, T1: {sat1_time}, T2: {sat2_time})")

        # Helpers to safely calculate statistics or return empty string
        calc_median = lambda lst: round(statistics.median(lst), 2) if lst else ""
        calc_min = lambda lst: round(min(lst), 2) if lst else ""
        calc_max = lambda lst: round(max(lst), 2) if lst else ""

        # Always construct the row for this configuration key
        row = {
            "type": mig_type,
            "size": int(size),
            "rate": int(rate),
            "duration": calc_median(durations),
            "duration_min": calc_min(durations),
            "duration_max": calc_max(durations),
            "downtime": calc_median(downtimes),
            "downtime_min": calc_min(downtimes),
            "downtime_max": calc_max(downtimes)
        }

        if mig_type == "membrane":
            membrane_results.append(row)
        elif mig_type == "precopy":
            pre_results.append(row)
        elif mig_type == "postcopy":
            post_results.append(row)
        elif mig_type == "stopcopy":
            stop_results.append(row)

    # Helper function to sort and write out a result set to a CSV file
    def write_csv(data, filename):
        if not data:
            print(f"No data to save for {filename}")
            return

        sorted_data = sorted(data, key=lambda x: (x["size"], x["rate"]))

        fieldnames = [
            "type", "size", "rate",
            "duration", "duration_min", "duration_max",
            "downtime", "downtime_min", "downtime_max"
        ]

        with open(filename, "w", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(sorted_data)
        print(f"Successfully saved {len(sorted_data)} rows to {filename}")

    # Output to separate CSV files for this directory
    write_csv(membrane_results, f"{output_prefix}_membrane.csv")
    write_csv(pre_results, f"{output_prefix}_pre.csv")
    write_csv(post_results, f"{output_prefix}_post.csv")
    write_csv(stop_results, f"{output_prefix}_stop.csv")


if __name__ == "__main__":
    process_directory("runs/rate", "baseline_compare_rate")
    process_directory("runs/size", "baseline_compare_size")