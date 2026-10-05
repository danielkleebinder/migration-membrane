import csv
import math
import os
from collections import defaultdict


def calculate_percentile(sorted_data, percentile):
    """Calculates a percentile using linear interpolation."""
    if not sorted_data:
        return 0.0
    n = len(sorted_data)
    if n == 1:
        return sorted_data[0]

    # Calculate index rank
    k = (n - 1) * (percentile / 100.0)
    f = math.floor(k)
    c = math.ceil(k)

    if f == c:
        return sorted_data[int(k)]

    # Interpolate between floor and ceiling values
    d0 = sorted_data[f] * (c - k)
    d1 = sorted_data[c] * (k - f)
    return d0 + d1


def calculate_stats(data):
    if not data:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

    n = len(data)
    mean = sum(data) / n
    variance = sum((x - mean) ** 2 for x in data) / n if n > 1 else 0.0
    std_dev = math.sqrt(variance)

    # Sort once to compute min, max, median (p50), p5, and p95
    sorted_data = sorted(data)
    min_val = sorted_data[0]
    max_val = sorted_data[-1]

    median_val = calculate_percentile(sorted_data, 50)
    p5 = calculate_percentile(sorted_data, 5)
    p95 = calculate_percentile(sorted_data, 95)

    return mean, std_dev, median_val, min_val, max_val, p5, p95


def main():
    file_path = 'results_routing_latency.csv'
    if not os.path.exists(file_path):
        print(f"Error: {file_path} not found.")
        return

    sat_latencies = defaultdict(list)
    # To track which satellite was active at each timestamp
    ts_active_sat = defaultdict(set)

    rows = []
    with open(file_path, mode='r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
            ts = row['timestamp']
            for sat in ['sat1', 'sat2', 'sat3']:
                val = row[sat]
                if val and val.lower() != 'nan':
                    sat_latencies[sat].append(float(val))
                    ts_active_sat[ts].add(sat)

    sat_losses = defaultdict(int)
    for row in rows:
        if row['lost'] == '1':
            ts = row['timestamp']
            # Attribute loss to the sat active at this timestamp
            active_sats = ts_active_sat.get(ts, set())
            for sat in active_sats:
                sat_losses[sat] += 1

    # Print Per-Satellite Latency & Loss Statistics
    for sat in ['sat1', 'sat2', 'sat3']:
        mean_lat, std_lat, median_lat, min_lat, max_lat, p5_lat, p95_lat = calculate_stats(sat_latencies[sat])
        loss = sat_losses[sat]
        print(f"--- {sat} ---")
        print(f"Mean Latency:       {mean_lat:.4f} ms")
        print(f"Median Latency:     {median_lat:.4f} ms")
        print(f"Standard Deviation: {std_lat:.4f} ms")
        print(f"Min Latency:        {min_lat:.4f} ms")
        print(f"Max Latency:        {max_lat:.4f} ms")
        print(f"p5 Latency:         {p5_lat:.4f} ms")
        print(f"p95 Latency:        {p95_lat:.4f} ms")
        print(f"Packet Loss:        {loss}")
        print()

    # Detect Handover Events
    handovers = []
    current_sat = None
    last_seen_ts = {}

    for row in rows:
        ts = row['timestamp']
        for sat in ['sat1', 'sat2', 'sat3']:
            val = row[sat]
            if val and val.lower() != 'nan':
                if current_sat is None:
                    current_sat = sat
                elif current_sat != sat:
                    # Handover detected!
                    handovers.append({
                        'from_sat': current_sat,
                        'to_sat': sat,
                        'last_pkt_ts': last_seen_ts[current_sat],
                        'first_pkt_ts': ts
                    })
                    current_sat = sat
                last_seen_ts[sat] = ts

    # Print Handover Timestamps
    print("--- Handover Events ---")
    if not handovers:
        print("No handover transitions detected.")
    else:
        for idx, ho in enumerate(handovers, 1):
            print(f"Handover #{idx}: {ho['from_sat']} -> {ho['to_sat']}")
            print(f"  Last packet from {ho['from_sat']}:  {ho['last_pkt_ts']}")
            print(f"  First packet from {ho['to_sat']}: {ho['first_pkt_ts']}")

            # Calculate gap if timestamps are numerical
            try:
                t1 = float(ho['last_pkt_ts'])
                t2 = float(ho['first_pkt_ts'])
                gap = t2 - t1
                print(f"  Handover Duration / Gap:     {gap:.4f} seconds/units")
            except ValueError:
                pass
            print()


if __name__ == "__main__":
    main()