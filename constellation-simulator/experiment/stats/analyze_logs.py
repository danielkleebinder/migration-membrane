import re
import csv
import argparse
from pathlib import Path


def analyze_migration_logs(log_dir="logs", csv_file="migration_tax.csv"):
    # Define regex patterns for parsing
    init_pattern = re.compile(r"\[LM\] Client connected\. Migration is initiated \(([\d\.]+)\s*ms\)\.\.\.")
    comp_pattern = re.compile(r"\[LM/Checkpoint\] Live migration completed at ([\d\.]+)\s*ms\.")
    rest_pattern = re.compile(r"\[LM/Restore\] Live migration restored at ([\d\.]+)\s*ms")
    events_pattern = re.compile(r"\[LM/Restore\] Read (\d+) membrane events")

    # Patterns for determining the start of the hosting window
    start_restore_pattern = re.compile(r"\[LM/Restore\] Initial state has been reconstructed \(([\d\.]+)\s*ms\)\.")
    start_server_pattern = re.compile(r"\[LM\] Migration server started \(([\d\.]+)\s*ms\)\.")

    log_path = Path(log_dir)
    if not log_path.exists():
        print(f"[Error] Directory '{log_dir}' does not exist.")
        return

    # Find all mig{id}_iwasm.log files and extract their IDs
    id_list = []
    for file in log_path.glob("mig*_iwasm.log"):
        match = re.search(r"mig(\d+)_iwasm\.log", file.name)
        if match:
            id_list.append(int(match.group(1)))

    if not id_list:
        print(f"[Notice] No matching log files found in '{log_dir}'.")
        return

    # Sort to process migrations sequentially
    id_list.sort()

    # Setup Console Table Header
    header = (
        f"{'Route':<15} | {'Mig. Time (ms)':<15} | {'Source Dur. (ms)':<17} | "
        f"{'Downtime (ms)':<15} | {'Host Window (s)':<16} | {'Mig. Tax (%)':<12} | {'Events'}"
    )

    # Open CSV and begin processing
    with open(csv_file, mode='w', newline='', encoding='utf-8') as f_csv:
        writer = csv.writer(f_csv)

        # Write CSV Header
        writer.writerow(
            ["route", "migration_time", "source_duration", "downtime", "host_window", "migration_tax", "events"])

        print(f"Exporting data to: {csv_file}\n")
        print(header)
        print("-" * len(header))

        # Process pairs of id and id+1
        for current_id in id_list:
            next_id = current_id + 1

            file1 = log_path / f"mig{current_id}_iwasm.log"
            file2 = log_path / f"mig{next_id}_iwasm.log"

            if not file2.exists():
                continue

            t_init = None
            t_comp = None
            t_rest = None
            events = None
            t_start_restore = None
            t_start_server = None

            # Parse Source Host (mig{id})
            with open(file1, 'r', encoding='utf-8') as f1:
                for line in f1:
                    m_start_rest = start_restore_pattern.search(line)
                    if m_start_rest:
                        t_start_restore = float(m_start_rest.group(1))

                    m_start_srv = start_server_pattern.search(line)
                    if m_start_srv:
                        t_start_server = float(m_start_srv.group(1))

                    m_init = init_pattern.search(line)
                    if m_init:
                        t_init = float(m_init.group(1))

                    m_comp = comp_pattern.search(line)
                    if m_comp:
                        t_comp = float(m_comp.group(1))

            # Parse Target Host (mig{id+1})
            with open(file2, 'r', encoding='utf-8') as f2:
                for line in f2:
                    m_rest = rest_pattern.search(line)
                    if m_rest:
                        t_rest = float(m_rest.group(1))

                    m_events = events_pattern.search(line)
                    if m_events:
                        events = int(m_events.group(1))

            # -------------------------------------------------------------
            # Calculations & Formatting
            # -------------------------------------------------------------
            if t_init and t_rest:
                migration_time = t_rest - t_init
                route_str = f"{current_id} -> {next_id}"

                # 1. Determine Source Duration and Downtime
                if t_comp:
                    src_duration = t_comp - t_init
                    downtime = migration_time - src_duration

                    # Console strings
                    src_duration_str = f"{src_duration:.3f}"
                    downtime_str = f"{downtime:.3f}"
                    # Raw numbers for CSV
                    csv_src_duration = round(src_duration, 3)
                    csv_downtime = round(downtime, 3)
                else:
                    src_duration_str = "N/A"
                    downtime_str = "N/A"
                    csv_src_duration = "N/A"
                    csv_downtime = "N/A"

                # 2. Determine Hosting Window Start (earliest of the two if both exist)
                valid_starts = [t for t in (t_start_restore, t_start_server) if t is not None]
                runtime_start = min(valid_starts) if valid_starts else None

                # 3. Calculate Hosting Window and Migration Tax
                if t_comp and runtime_start:
                    hosting_window_ms = t_comp - runtime_start
                    hosting_window_s = hosting_window_ms / 1000.0
                    migration_tax_pct = (migration_time / hosting_window_ms) * 100

                    # Console strings
                    hw_str = f"{hosting_window_s:.3f}"
                    tax_str = f"{migration_tax_pct:.4f}%"
                    # Raw numbers for CSV (leaving % off for easier data processing)
                    csv_hw = round(hosting_window_s, 3)
                    csv_tax = round(migration_tax_pct, 4)
                else:
                    hw_str = "N/A"
                    tax_str = "N/A"
                    csv_hw = "N/A"
                    csv_tax = "N/A"

                event_count = events if events is not None else "N/A"

                # Write to Console
                print(
                    f"{route_str:<15} | {migration_time:<15.3f} | {src_duration_str:<17} | {downtime_str:<15} | {hw_str:<16} | {tax_str:<12} | {event_count}")

                # Write to CSV
                writer.writerow([
                    route_str,
                    round(migration_time, 3),
                    csv_src_duration,
                    csv_downtime,
                    csv_hw,
                    csv_tax,
                    event_count
                ])
            else:
                print(f"[Warning] Incomplete target timestamps for migration {current_id} -> {next_id}")

    print(f"\n[Success] Processing complete. Results saved to {csv_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze migration logs and calculate migration tax.")
    parser.add_argument("log_dir", nargs="?", default="experiment-results/6ms900s/logs", help="Path to the logs directory")
    parser.add_argument("--csv", default="migration_tax.csv", help="Name of the output CSV file")
    
    args = parser.parse_args()
    
    analyze_migration_logs(args.log_dir, args.csv)