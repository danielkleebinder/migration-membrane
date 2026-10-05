import re
from datetime import datetime


def analyze_migration_latency(log_file_path):
    migrations = []

    # Matches: [Orchestrator] TRIGGER MIGRATION: 423 (192.168.10.11) -> 424 (192.168.10.12)
    # (Doesn't require a timestamp on the trigger line itself)
    migration_pattern = re.compile(
        r'\[Orchestrator\]\s+TRIGGER MIGRATION:\s+(\w+)\s+\((.*?)\)\s+->\s+(\w+)\s+\((.*?)\)')

    # Matches: [00:01:56.277] Active Satellite: 424, ...
    active_sat_pattern = re.compile(r'\[(.*?)\]\s+Active Satellite:\s+(\w+)')

    try:
        with open(log_file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"[Error] Log file '{log_file_path}' not found.")
        return

    print(f"Total lines read from log: {len(lines)}")

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Skip empty lines
        if not line:
            i += 1
            continue

        mig_match = migration_pattern.search(line)

        if mig_match:
            from_sat = mig_match.group(1)
            from_ip = mig_match.group(2)
            to_sat = mig_match.group(3)
            to_ip = mig_match.group(4)

            migration_event = {
                "trigger_line": line,
                "from_satellite": from_sat,
                "to_satellite": to_sat,
                "first_active_time": None,
                "time_to_first_active_sec": None
            }

            # Look ahead for the next 'Active Satellite' log entry
            j = i + 1
            while j < len(lines):
                next_line = lines[j].strip()
                if not next_line:
                    j += 1
                    continue

                # If we hit another migration event, stop searching this lookahead block
                if migration_pattern.search(next_line):
                    break

                active_match = active_sat_pattern.search(next_line)
                if active_match:
                    active_time_str = active_match.group(1)
                    migration_event["first_active_time"] = active_time_str
                    break
                j += 1

            migrations.append(migration_event)
        i += 1

    print(f"Found {len(migrations)} migration events.\n")
    print(f"{'Migration Route':<15} | {'First Active Satellite Timestamp'}")
    print("-" * 50)

    valid_timestamps = []
    for m in migrations:
        route = f"{m['from_satellite']} -> {m['to_satellite']}"
        active_t = m['first_active_time'] if m['first_active_time'] else "NOT FOUND"
        print(f"{route:<15} | {active_t}")

        if m['first_active_time']:
            try:
                dt = datetime.strptime(m['first_active_time'], "%H:%M:%S.%f")
                valid_timestamps.append(dt)
            except ValueError:
                pass

    # Calculate and print mean time between consecutive first active timestamps
    if len(valid_timestamps) > 1:
        deltas = []
        for idx in range(1, len(valid_timestamps)):
            diff = (valid_timestamps[idx] - valid_timestamps[idx - 1]).total_seconds()
            deltas.append(diff)

        mean_interval = sum(deltas) / len(deltas)
        print("\n" + "=" * 50)
        print(f"Mean time between First Active timestamps: {mean_interval:.3f} seconds")
        print("=" * 50)
    else:
        print("\n[Notice] Not enough valid timestamps found to compute a mean interval.")


if __name__ == "__main__":
    # Replace with your actual log file path
    log_file = "experiment/experiment-orchestrator.log"
    analyze_migration_latency(log_file)