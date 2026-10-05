import re
from pathlib import Path
import numpy as np

# Path to the multi-run directory
BASE_DIR = Path("runs/multi")

# List of target experiment directories
APPROACHES = ["membrane", "post-copy", "pre-copy", "stop-copy"]


def parse_timestamp(file_path: Path, pattern: str) -> float | None:
    """Reads a file line-by-line and returns the first float matching the regex pattern."""
    if not file_path.exists():
        return None
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            match = re.search(pattern, line)
            if match:
                return float(match.group(1))
    return None


def process_approach(approach_name: str) -> None:
    approach_dir = BASE_DIR / approach_name
    if not approach_dir.exists():
        print(f"Directory not found: {approach_dir}")
        return

    durations = []

    # Find all sat1 log files to discover available iterations
    sat1_files = sorted(approach_dir.glob("results_it*_sat1.log"))

    for sat1_path in sat1_files:
        # Extract iteration identifier (e.g., '1', '9', '20')
        match_it = re.search(r"results_it(\d+)_sat1\.log", sat1_path.name)
        if not match_it:
            continue

        it_num = match_it.group(1)
        sat2_path = approach_dir / f"results_it{it_num}_sat2.log"
        duration = None

        # --- Paradigm 1: Membrane & Stop-Copy ---
        if approach_name in ["membrane", "stop-copy"]:
            p_sat1 = r"\[LM\] Client connected\. Migration is initiated \(([\d\.]+) ms\)"
            p_sat2 = r"\[LM/Restore\] Live migration restored at ([\d\.]+) ms"

            t1 = parse_timestamp(sat1_path, p_sat1)
            t2 = parse_timestamp(sat2_path, p_sat2)

            if t1 is not None and t2 is not None:
                duration = t2 - t1

        # --- Paradigm 2: Pre-Copy ---
        elif approach_name == "pre-copy":
            p_sat1 = r"\[LM\] Client connected\. Migration is initiated \(([\d\.]+)(?:\s*ms)?\)"
            p_sat2 = r"\[LM/Resume\] Resuming bytecode function \(([\d\.]+)(?:\s*ms)?\)"

            t1 = parse_timestamp(sat1_path, p_sat1)
            t2 = parse_timestamp(sat2_path, p_sat2)

            if t1 is not None and t2 is not None:
                duration = t2 - t1

        # --- Paradigm 3: Post-Copy ---
        elif approach_name == "post-copy":
            p_sat1 = r"\[LM/Checkpoint\] Total session duration: ([\d\.]+) ms"
            duration = parse_timestamp(sat1_path, p_sat1)

        if duration is not None:
            durations.append(duration)
        else:
            print(f"Warning: Could not parse valid duration for '{approach_name}' (iteration {it_num})")

    # Output Statistics
    print(f"=== Paradigm: {approach_name} ===")
    if durations:
        p5 = np.percentile(durations, 5)
        p50 = np.percentile(durations, 50)
        p95 = np.percentile(durations, 95)

        print(f"  Valid Runs Parsed : {len(durations)}")
        print(f"  P50 (Median)      : {p50:.2f} ms")
        print(f"  P5                : {p5:.2f} ms")
        print(f"  P95               : {p95:.2f} ms\n")
    else:
        print("  No valid measurements found.\n")


def main():
    for approach in APPROACHES:
        process_approach(approach)


if __name__ == "__main__":
    main()