#!/usr/bin/env python3
import argparse
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_RESULTS_DIR = Path("experiments/with-membrane/state-continuity/results")
DEFAULT_STATS_DIR = Path("experiments/with-membrane/state-continuity/stats")
LOG_NAMES = ("sat1_iwasm.log", "sat2_iwasm.log")

INITIAL_CHECKSUM = 1469598103934665603
FNV_PRIME = 1099511628211
MASK_64 = 0xFFFFFFFFFFFFFFFF

SEQ_RE = re.compile(
    r"SEQ=(\d+)\s+RANDOM=([0-9a-fA-F]+)\s+"
    r"(?:HASH|CHECKSUM)=([0-9a-fA-F]+)"
)
REPLAY_RE = re.compile(r"\[LM/Checkpoint\] Transmitted (\d+) membrane events")
INITIATED_RE = re.compile(r"Migration is initiated")
COMPLETED_RE = re.compile(r"Live migration completed at")
RESTORED_RE = re.compile(r"Live migration restored at")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Calculate continuity statistics from continuous host logs."
    )
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--stats-dir", type=Path, default=DEFAULT_STATS_DIR)
    return parser.parse_args()


def calculate_expected_checksum(previous_checksum, sequence, random_value):
    checksum = (previous_checksum ^ sequence) & MASK_64
    checksum = (checksum * FNV_PRIME) & MASK_64
    checksum = (checksum ^ random_value) & MASK_64
    return (checksum * FNV_PRIME) & MASK_64


def main():
    args = parse_args()

    events = []
    replay_samples = []
    migration_initiations = 0
    migration_completions = 0
    migration_restorations = 0

    for log_name in LOG_NAMES:
        log_path = args.results_dir / log_name
        if not log_path.exists():
            print(f"Warning: {log_path} not found.")
            continue

        host = log_name.removesuffix("_iwasm.log")
        with log_path.open("r", encoding="utf-8", errors="replace") as log_file:
            for line_number, line in enumerate(log_file, start=1):
                match = SEQ_RE.search(line)
                if match:
                    events.append({
                        "seq": int(match.group(1)),
                        "rand": int(match.group(2), 16),
                        "checksum": int(match.group(3), 16),
                        "host": host,
                        "line": line_number,
                    })

                replay_match = REPLAY_RE.search(line)
                if replay_match:
                    replay_samples.append(int(replay_match.group(1)))

                migration_initiations += bool(INITIATED_RE.search(line))
                migration_completions += bool(COMPLETED_RE.search(line))
                migration_restorations += bool(RESTORED_RE.search(line))

    if not events:
        raise SystemExit("No sequence data found in the host logs.")

    # Each host log is continuous but contains alternating execution segments.
    # Sequence order reconstructs the single logical application stream.
    events_by_sequence = defaultdict(list)
    for event in events:
        events_by_sequence[event["seq"]].append(event)

    ordered_sequences = sorted(events_by_sequence)
    canonical_events = []
    duplicate_sequences = 0
    duplicate_conflicts = 0

    for sequence in ordered_sequences:
        same_sequence = events_by_sequence[sequence]
        duplicate_sequences += len(same_sequence) - 1

        values = {(event["rand"], event["checksum"]) for event in same_sequence}
        if len(values) > 1:
            duplicate_conflicts += 1

        canonical_events.append(same_sequence[0])

    sequence_gaps = sum(
        current - previous - 1
        for previous, current in zip(ordered_sequences, ordered_sequences[1:])
        if current > previous + 1
    )

    # A change in the host producing consecutive output records is an observed
    # handover. Replay-summary lines are counted separately below.
    handovers = sum(
        previous["host"] != current["host"]
        for previous, current in zip(canonical_events, canonical_events[1:])
    )

    # Verify the hash chain over the reconstructed logical stream. If the logs
    # start after sequence 1, use the first observed checksum as the anchor.
    hash_chain_mismatches = 0
    if canonical_events[0]["seq"] == 1:
        current_checksum = INITIAL_CHECKSUM
        events_to_verify = canonical_events
    else:
        current_checksum = canonical_events[0]["checksum"]
        events_to_verify = canonical_events[1:]
        print(
            "Warning: sequence log starts after 1; hash verification begins "
            "from the first observed checksum."
        )

    for event in events_to_verify:
        expected = calculate_expected_checksum(
            current_checksum, event["seq"], event["rand"]
        )
        if expected != event["checksum"]:
            hash_chain_mismatches += 1
            # Resynchronize so one corrupted record does not mark every later
            # record as another mismatch.
            current_checksum = event["checksum"]
        else:
            current_checksum = expected

    replay_count_total = sum(replay_samples)
    if replay_samples:
        replay_median = float(np.median(replay_samples))
        replay_p5 = float(np.percentile(replay_samples, 5))
        replay_p95 = float(np.percentile(replay_samples, 95))
        replay_max = int(np.max(replay_samples))
        replay_min = int(np.min(replay_samples))
    else:
        replay_median = replay_p5 = replay_p95 = float("nan")
        replay_max = replay_min = float("nan")

    print(f"Observed handovers: {handovers}")
    print(f"Migration initiations: {migration_initiations}")
    print(f"Source-side completions: {migration_completions}")
    print(f"Target-side restorations: {migration_restorations}")
    print(f"Replay-count samples: {len(replay_samples)}")
    print(f"Sequence gaps: {sequence_gaps}")
    print(f"Duplicate sequences: {duplicate_sequences}")
    print(f"Conflicting duplicate sequences: {duplicate_conflicts}")
    print(
        "Replay count: "
        f"total={replay_count_total}, median={replay_median:.2f}, "
        f"p5={replay_p5:.2f}, p95={replay_p95:.2f}, "
        f"max={replay_max}, min={replay_min}"
    )
    print(f"Hash-chain mismatches: {hash_chain_mismatches}")

    counters = {
        "observed handovers": handovers,
        "migration initiations": migration_initiations,
        "source-side completions": migration_completions,
        "target-side restorations": migration_restorations,
        "replay-count samples": len(replay_samples),
    }
    if len(set(counters.values())) != 1:
        details = ", ".join(f"{name}={value}" for name, value in counters.items())
        print(f"Warning: handover counters disagree: {details}")

    args.stats_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.stats_dir / "stats_state_continuity.csv"
    pd.DataFrame([{
        "Handovers": handovers,
        "MigrationInitiations": migration_initiations,
        "MigrationCompletions": migration_completions,
        "MigrationRestorations": migration_restorations,
        "ReplayCountSamples": len(replay_samples),
        "SequenceGaps": sequence_gaps,
        "DuplicateSequences": duplicate_sequences,
        "DuplicateSequenceConflicts": duplicate_conflicts,
        "ReplayCountTotal": replay_count_total,
        "ReplayCountMedian": replay_median,
        "ReplayCountP5": replay_p5,
        "ReplayCountP95": replay_p95,
        "ReplayCountMax": replay_max,
        "ReplayCountMin": replay_min,
        "HashChainMismatches": hash_chain_mismatches,
    }]).to_csv(csv_path, index=False)

    print(f"\nResults exported to {csv_path}")


if __name__ == "__main__":
    main()