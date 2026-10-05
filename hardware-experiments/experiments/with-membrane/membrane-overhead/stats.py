#!/usr/bin/env python3
import sys
import re
import csv
import numpy as np
from collections import defaultdict


def parse_logs(record_log_path, replay_log_path, output_csv="results/membrane_overhead.csv"):
    # Timing data storage updated for new log structure
    record_data = defaultdict(lambda: {
        'record': [],
        'transfer': [],
        'record_total': [],
        'native_total': []
    })

    replay_data = defaultdict(lambda: {
        'fetch': [],
        'replay': [],
        'total': []
    })

    record_iterations = []
    replay_iterations = []

    # UPDATED REGEX: Matches the new record log structure including 'native total'
    rec_pattern = re.compile(
        r"\[MICROBENCH/RECORD\]\s+(?:wasi_snapshot_preview1\.)?([a-zA-Z0-9_]+)[^\s]*\s+"
        r"record:\s*(\d+)\s*ns,\s*transfer:\s*(\d+)\s*ns,\s*record total:\s*(\d+)\s*ns,\s*native total:\s*(\d+)\s*ns"
    )

    # UPDATED REGEX: Matches the new replay log structure
    rep_pattern = re.compile(
        r"\[MICROBENCH/REPLAY\]\s+(?:wasi_snapshot_preview1\.)?([a-zA-Z0-9_]+)[^\s]*\s+"
        r"fetch:\s*(\d+)\s*ns,\s*replay:\s*(\d+)\s*ns,\s*total:\s*(\d+)\s*ns"
    )

    iter_pattern = re.compile(r"\[BENCH/IO\]\s+Iteration:\s*(\d+)")

    # 1. Parse Record Log
    try:
        with open(record_log_path, "r") as f:
            for line in f:
                m_rec = rec_pattern.search(line)
                if m_rec:
                    syscall = m_rec.group(1)
                    record_data[syscall]['record'].append(int(m_rec.group(2)))
                    record_data[syscall]['transfer'].append(int(m_rec.group(3)))
                    record_data[syscall]['record_total'].append(int(m_rec.group(4)))
                    record_data[syscall]['native_total'].append(int(m_rec.group(5)))
                    continue

                m_iter = iter_pattern.search(line)
                if m_iter:
                    record_iterations.append(int(m_iter.group(1)))
    except FileNotFoundError:
        print(f"WARNING: Record log file '{record_log_path}' not found.")

    # 2. Parse Replay Log
    try:
        with open(replay_log_path, "r") as f:
            for line in f:
                m_rep = rep_pattern.search(line)
                if m_rep:
                    syscall = m_rep.group(1)
                    replay_data[syscall]['fetch'].append(int(m_rep.group(2)))
                    replay_data[syscall]['replay'].append(int(m_rep.group(3)))
                    replay_data[syscall]['total'].append(int(m_rep.group(4)))
                    continue

                m_iter = iter_pattern.search(line)
                if m_iter:
                    replay_iterations.append(int(m_iter.group(1)))
    except FileNotFoundError:
        print(f"WARNING: Replay log file '{replay_log_path}' not found.")

    # Summary of Iteration Progress
    rec_count = len(record_iterations)
    rep_count = len(replay_iterations)
    rec_range = f"{min(record_iterations)} -> {max(record_iterations)}" if record_iterations else "N/A"
    rep_range = f"{min(replay_iterations)} -> {max(replay_iterations)}" if replay_iterations else "N/A"

    print(f"\nLog Summary:")
    print(f"  Source Node (Sat1): {rec_count} iteration events logged (Iter range: {rec_range})")
    print(f"  Destination Node (Sat2): {rep_count} iteration events logged (Iter range: {rep_range})")
    print("=" * 135)

    all_syscalls = sorted(list(set(record_data.keys()) | set(replay_data.keys())))
    summary_rows = []

    # SAFETY CHECK
    if not all_syscalls:
        print("ERROR: No syscall data was matched. Please verify the log files contain the correct MICROBENCH output.")
        return

    # Updated console header to include Native Execution Time
    print(
        f"{'SYSCALL':<18} | {'RECORD p50 [p95]':<18} | {'TRANSFER p50 [p95]':<18} | {'TOT REC p50 [p95]':<18} | {'NATIVE p50 [p95]':<18} | {'REPLAY p50 [p95]':<18}")
    print("=" * 135)

    # Helper to calculate percentiles and convert to microseconds safely
    def get_pct(data, q):
        return np.percentile(data, q) / 1000.0 if data else 0.0

    for sc in all_syscalls:
        rec = record_data[sc]
        rep = replay_data[sc]

        # In-Memory Record stats (us)
        rec_p5 = get_pct(rec['record'], 5)
        rec_p50 = get_pct(rec['record'], 50)
        rec_p95 = get_pct(rec['record'], 95)

        # TCP Socket Transfer stats (us)
        transfer_p5 = get_pct(rec['transfer'], 5)
        transfer_p50 = get_pct(rec['transfer'], 50)
        transfer_p95 = get_pct(rec['transfer'], 95)

        # Total Record Time stats (us)
        rec_total_p5 = get_pct(rec['record_total'], 5)
        rec_total_p50 = get_pct(rec['record_total'], 50)
        rec_total_p95 = get_pct(rec['record_total'], 95)

        # Native Total Time stats (us)
        native_p5 = get_pct(rec['native_total'], 5)
        native_p50 = get_pct(rec['native_total'], 50)
        native_p95 = get_pct(rec['native_total'], 95)

        # Total Replay Time stats (us)
        rep_total_p5 = get_pct(rep['total'], 5)
        rep_total_p50 = get_pct(rep['total'], 50)
        rep_total_p95 = get_pct(rep['total'], 95)

        # Component metrics for replay
        rep_fetch_p50 = get_pct(rep['fetch'], 50)
        rep_execution_p50 = get_pct(rep['replay'], 50)

        # Taxes and Speedups based on median
        tax_in_memory_pct = (rec_p50 / rec_total_p50 * 100.0) if rec_total_p50 > 0 else 0.0
        tax_tcp_streaming_pct = (transfer_p50 / rec_total_p50 * 100.0) if rec_total_p50 > 0 else 0.0
        record_overhead_x = (rec_total_p50 / native_p50) if native_p50 > 0 else 0.0
        replay_overhead_x = (rep_total_p50 / native_p50) if native_p50 > 0 else 0.0
        speedup = (rec_total_p50 / rep_total_p50) if rep_total_p50 > 0 else 0.0

        # Print formatted console row
        print(
            f"{sc:<18} | "
            f"{rec_p50:6.3f} [{rec_p95:6.3f}] | "
            f"{transfer_p50:6.3f} [{transfer_p95:6.3f}] | "
            f"{rec_total_p50:6.3f} [{rec_total_p95:6.3f}] | "
            f"{native_p50:6.3f} [{native_p95:6.3f}] | "
            f"{rep_total_p50:6.3f} [{rep_total_p95:6.3f}]"
        )

        summary_rows.append({
            'syscall': sc,

            'rec_in_memory_us_p5': round(rec_p5, 4),
            'rec_in_memory_us_p50': round(rec_p50, 4),
            'rec_in_memory_us_p95': round(rec_p95, 4),

            'rec_transfer_us_p5': round(transfer_p5, 4),
            'rec_transfer_us_p50': round(transfer_p50, 4),
            'rec_transfer_us_p95': round(transfer_p95, 4),

            'rec_total_us_p5': round(rec_total_p5, 4),
            'rec_total_us_p50': round(rec_total_p50, 4),
            'rec_total_us_p95': round(rec_total_p95, 4),

            'native_total_us_p5': round(native_p5, 4),
            'native_total_us_p50': round(native_p50, 4),
            'native_total_us_p95': round(native_p95, 4),

            'rep_fetch_us_p50': round(rep_fetch_p50, 4),
            'rep_execution_us_p50': round(rep_execution_p50, 4),

            'rep_total_us_p5': round(rep_total_p5, 4),
            'rep_total_us_p50': round(rep_total_p50, 4),
            'rep_total_us_p95': round(rep_total_p95, 4),

            'tax_in_memory_pct': round(tax_in_memory_pct, 2),
            'tax_tcp_streaming_pct': round(tax_tcp_streaming_pct, 2),
            'record_vs_native_overhead_x': round(record_overhead_x, 2),
            'replay_vs_native_overhead_x': round(replay_overhead_x, 2),
            'record_vs_replay_speedup_x': round(speedup, 2)
        })

    print("=" * 135)

    # Save to CSV
    if summary_rows:
        fieldnames = list(summary_rows[0].keys())
        with open(output_csv, "w", newline="") as out:
            writer = csv.DictWriter(out, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(summary_rows)
        print(f"Saved summary CSV to: {output_csv}")


if __name__ == "__main__":
    # Specify your log files here, or pass them as args (e.g. python3 stats.py sat1_iwasm.log sat2_iwasm.log)
    rec_file = sys.argv[1] if len(sys.argv) > 1 else "results/sat1_iwasm.log"
    rep_file = sys.argv[2] if len(sys.argv) > 2 else "results/sat2_iwasm.log"
    parse_logs(rec_file, rep_file)