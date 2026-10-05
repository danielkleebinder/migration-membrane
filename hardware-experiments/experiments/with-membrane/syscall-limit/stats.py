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
    # {(type, size, rate): { 'iteration_1': {'sat1': file, 'sat2': file}, ... }}
    experiments = defaultdict(lambda: defaultdict(dict))

    # Extract file configurations from filenames
    # Example filename: sat1_membrane_mem256_rate20.log
    file_pattern = re.compile(r"(sat[12])_(membrane|precopy|postcopy|stopcopy)_syscalls(\d+)_bytes(\d+)\.log")

    # Use glob to find all .log files in any iteration subdirectory
    search_pattern = os.path.join(runs_dir, "iteration_*", "*.log")

    for filepath in glob.glob(search_pattern):
        filename = os.path.basename(filepath)
        # Extract the iteration folder name (e.g., "iteration_1")
        iteration = os.path.basename(os.path.dirname(filepath))

        match = file_pattern.match(filename)
        if match:
            node, mig_type, syscalls_rate, syscall_bytes = match.groups()
            config_key = (mig_type, syscalls_rate, syscall_bytes)
            experiments[config_key][iteration][node] = filepath

    membrane_results = []
    pre_results = []
    stop_results = []

    # Parse paired logs across all iterations
    for (mig_type, syscall_rate, syscall_bytes), iterations in experiments.items():
        durations = []
        downtimes = []

        for iteration, nodes in iterations.items():
            if 'sat1' not in nodes or 'sat2' not in nodes:
                print(
                    f"[Warning] Missing a node log for {mig_type} (syscall rate: {syscall_rate}, syscall bytes: {syscall_bytes}) in {iteration}. Skipping.")
                continue

            sat1_file = nodes['sat1']
            sat2_file = nodes['sat2']

            duration = None
            sat1_time = None
            sat2_time = None

            # Parse sat1 log
            with open(sat1_file, "r") as f1:
                for line in f1:
                    if mig_type == "precopy" and "Migration took" in line:
                        m = re.search(r"Migration took ([\d.]+)\s*ms", line)
                        if m: duration = float(m.group(1))
                    elif (mig_type == "membrane" or mig_type == "stopcopy") and "Migration completed in" in line:
                        m = re.search(r"Migration completed in ([\d.]+)\s*ms", line)
                        if m: duration = float(m.group(1))

                    if "Live migration completed at" in line:
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

            # Calculate downtime for this specific iteration
            if duration is not None and sat1_time is not None and sat2_time is not None:
                downtime = abs(sat2_time - sat1_time)
                durations.append(duration)
                downtimes.append(downtime)
            else:
                print(f"[Warning] Could not extract all metrics for {sat1_file} and {sat2_file}")

        # If we successfully extracted metrics from the iterations, compute stats
        if durations and downtimes:
            row = {
                "type": mig_type,
                "rate": int(syscall_rate),
                "bytes": int(syscall_bytes),
                "duration": round(statistics.median(durations), 2),
                "duration_min": round(min(durations), 2),
                "duration_max": round(max(durations), 2),
                "downtime": round(statistics.median(downtimes), 2),
                "downtime_min": round(min(downtimes), 2),
                "downtime_max": round(max(downtimes), 2)
            }

            if mig_type == "membrane":
                membrane_results.append(row)
            elif mig_type == "precopy":
                pre_results.append(row)
            elif mig_type == "stopcopy":
                stop_results.append(row)

    # Helper function to sort and write out a result set to a CSV file
    def write_csv(data, filename):
        if not data:
            print(f"No data to save for {filename}")
            return

        # Sort rows numerically by size, then rate
        sorted_data = sorted(data, key=lambda x: (x["rate"], x["bytes"]))

        fieldnames = [
            "type", "rate", "bytes",
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
    write_csv(stop_results, f"{output_prefix}_stop.csv")


if __name__ == "__main__":
    # Process the 'rate' sweep directory
    process_directory("runs/syscall_rate", "syscall_limit_rate")

    # Process the 'size' sweep directory
    process_directory("runs/syscall_payload", "syscall_limit_size")