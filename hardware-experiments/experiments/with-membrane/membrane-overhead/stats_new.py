#!/usr/bin/env python3
import sys
import re
import csv
import numpy as np
from collections import defaultdict


def parse_logs(record_log_path, replay_log_path, output_csv="results/membrane_overhead.csv"):
    # Timing data storage updated for new calculation
    record_data = defaultdict(lambda: {
        'record': [],
        'transfer': [],
        'record_total': [],
        'native_total': [],
        'pure_native': []  # NEW: Native Total - Transfer
    })

    replay_data = defaultdict(lambda: {
        'fetch': [],
        'replay': [],
        'total': []
    })

    record_iterations = []
    replay_iterations = []

    # REGEX: Matches the new record log structure
    rec_pattern = re.compile(
        r"\[MICROBENCH/RECORD\]\s+(?:wasi_snapshot_preview1\.)?([a-zA-Z0-9_]+)[^\s]*\s+"
        r"record:\s*(\d+)\s*ns,\s*transfer:\s*(\d+)\s*ns,\s*record total:\s*(\d+)\s*ns,\s*native total:\s*(\d+)\s*ns"
    )

    # REGEX: Matches the new replay log structure
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

                    record_time = int(m_rec.group(2))
                    transfer_time = int(m_rec.group(3))
                    raw_record_total = int(m_rec.group(4))
                    native_total = int(m_rec.group(5))

                    # --- Pure Calculations ---
                    pure_native = native_total - transfer_time
                    pure_record_total = raw_record_total - transfer_time

                    record_data[syscall]['record'].append(record_time)
                    record_data[syscall]['transfer'].append(transfer_time)
                    record_data[syscall]['record_total'].append(pure_record_total)
                    record_data[syscall]['native_total'].append(native_total)
                    record_data[syscall]['pure_native'].append(pure_native)
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

                    fetch_time = int(m_rep.group(2))
                    replay_time = int(m_rep.group(3))
                    raw_total_time = int(m_rep.group(4))

                    # --- Total - Fetch ---
                    pure_replay_total = raw_total_time - fetch_time

                    replay_data[syscall]['fetch'].append(fetch_time)
                    replay_data[syscall]['replay'].append(replay_time)
                    replay_data[syscall]['total'].append(pure_replay_total)
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
    print("=" * 145)

    all_syscalls = sorted(list(set(record_data.keys()) | set(replay_data.keys())))
    summary_rows = []

    # SAFETY CHECK
    if not all_syscalls:
        print("ERROR: No syscall data was matched. Please verify the logs.")
        return

    # Console Header
    print(
        f"{'SYSCALL':<18} | {'RECORD p50 [p95]':<18} | {'PURE NATIVE p50':<18} | {'PURE REP p50':<18} | {'SPEEDUP (Nat/Rep)':<18}")
    print("=" * 145)

    # Helper to calculate percentiles and convert to microseconds safely
    def get_pct(data, q):
        return np.percentile(data, q) / 1000.0 if data else 0.0

    for sc in all_syscalls:
        rec = record_data[sc]
        rep = replay_data[sc]

        # Raw Record stats (us)
        record_p50 = get_pct(rec['record'], 50)
        record_p95 = get_pct(rec['record'], 95)

        # PURE Native stats (us) (Native Total - Transfer)
        pure_native_p5 = get_pct(rec['pure_native'], 5)
        pure_native_p50 = get_pct(rec['pure_native'], 50)
        pure_native_p95 = get_pct(rec['pure_native'], 95)

        # PURE Replay Time stats (us) (Total - Fetch)
        rep_total_p5 = get_pct(rep['total'], 5)
        rep_total_p50 = get_pct(rep['total'], 50)
        rep_total_p95 = get_pct(rep['total'], 95)

        # Raw Data (for CSV completeness)
        transfer_p50 = get_pct(rec['transfer'], 50)
        native_raw_p50 = get_pct(rec['native_total'], 50)
        rep_fetch_p50 = get_pct(rep['fetch'], 50)

        # Speedup calculation = (Native Execution without Transfer) / (Replay Execution without Fetch)
        speedup = (pure_native_p50 / rep_total_p50) if rep_total_p50 > 0 else 0.0

        # Print formatted console row
        print(
            f"{sc:<18} | "
            f"{record_p50:6.3f} [{record_p95:6.3f}]  | "
            f"{pure_native_p50:6.3f} [{pure_native_p95:6.3f}] | "
            f"{rep_total_p50:6.3f} [{rep_total_p95:6.3f}] | "
            f"{speedup:6.2f}x"
        )

        summary_rows.append({
            'syscall': sc,

            'record_us_p50': round(record_p50, 4),
            'record_us_p95': round(record_p95, 4),

            'raw_transfer_us_p50': round(transfer_p50, 4),
            'raw_native_us_p50': round(native_raw_p50, 4),
            'raw_rep_fetch_us_p50': round(rep_fetch_p50, 4),

            'pure_native_us_p5': round(pure_native_p5, 4),
            'pure_native_us_p50': round(pure_native_p50, 4),
            'pure_native_us_p95': round(pure_native_p95, 4),

            'pure_rep_total_us_p5': round(rep_total_p5, 4),
            'pure_rep_total_us_p50': round(rep_total_p50, 4),
            'pure_rep_total_us_p95': round(rep_total_p95, 4),

            'native_vs_replay_speedup_x': round(speedup, 2)
        })

    print("=" * 145)

    # Save to CSV
    if summary_rows:
        fieldnames = list(summary_rows[0].keys())
        with open(output_csv, "w", newline="") as out:
            writer = csv.DictWriter(out, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(summary_rows)
        print(f"Saved summary CSV to: {output_csv}")


if __name__ == "__main__":
    rec_file = sys.argv[1] if len(sys.argv) > 1 else "results/sat1_iwasm.log"
    rep_file = sys.argv[2] if len(sys.argv) > 2 else "results/sat2_iwasm.log"
    parse_logs(rec_file, rep_file)