import pandas as pd
import numpy as np
import re
import os
import sys
from pathlib import Path

def parse_logs(results_dir):
    sat1_log = results_dir / "sat1_iwasm.log"
    sat2_log = results_dir / "sat2_iwasm.log"
    
    events = []
    start_re = re.compile(r"\[LM\] Client connected\. Migration is initiated \((\d+\.\d+) ms\)\.\.\.")
    comp_re = re.compile(r"\[LM/Checkpoint\] Live migration completed at (\d+\.\d+) ms\.")
    rest_re = re.compile(r"\[LM/Restore\] Live migration restored at (\d+\.\d+) ms")

    for host, log_path in [("sat1", sat1_log), ("sat2", sat2_log)]:
        if not log_path.exists():
            continue
        with open(log_path, "r") as f:
            for line in f:
                m = start_re.search(line)
                if m:
                    events.append({"type": "start", "host": host, "ts": float(m.group(1))})
                m = comp_re.search(line)
                if m:
                    events.append({"type": "comp", "host": host, "ts": float(m.group(1))})
                m = rest_re.search(line)
                if m:
                    events.append({"type": "rest", "host": host, "ts": float(m.group(1))})
    
    events.sort(key=lambda x: x["ts"])
    
    handovers = []
    i = 0
    handover_id = 1
    while i < len(events):
        if events[i]["type"] == "start":
            start_event = events[i]
            comp_event = None
            rest_event = None
            
            j = i + 1
            while j < len(events):
                if events[j]["type"] == "comp" and events[j]["host"] == start_event["host"]:
                    if comp_event is None:
                        comp_event = events[j]
                elif events[j]["type"] == "rest" and events[j]["host"] != start_event["host"]:
                    if rest_event is None:
                        rest_event = events[j]
                
                if comp_event and rest_event:
                    break
                j += 1
            
            if comp_event and rest_event:
                handovers.append({
                    "HandoverId": handover_id,
                    "StartTime": start_event["ts"],
                    "EndTime": rest_event["ts"],
                    "CheckpointTime": comp_event["ts"],
                    "Source": start_event["host"],
                    "Target": rest_event["host"]
                })
                handover_id += 1
                i = j # Move to the end of this handover
            else:
                i += 1
        else:
            i += 1
    return pd.DataFrame(handovers)

def main():
    results_dir = Path("experiments/with-membrane/recurrent-migration/results")
    if not results_dir.exists():
        print(f"Results directory {results_dir} not found.")
        sys.exit(1)
        
    handovers = parse_logs(results_dir)
    if handovers.empty:
        print("No handovers found in logs.")
        sys.exit(0)
        
    # Basic timing metrics
    handovers["MigrationTimeS"] = (handovers["EndTime"] - handovers["StartTime"]) / 1000.0
    handovers["DowntimeMs"] = handovers["EndTime"] - handovers["CheckpointTime"]
    
    # Load host metrics for memory
    host_samples_path = results_dir / "host-samples.csv"
    if host_samples_path.exists():
        host_samples = pd.read_csv(host_samples_path)
        
        # Calculate PostCleanupMemoryMB
        post_mem = []
        for idx, row in handovers.iterrows():
            start_time = row["EndTime"]
            # End of window is next handover start or end of data
            if idx + 1 < len(handovers):
                end_time = handovers.iloc[idx + 1]["StartTime"]
            else:
                end_time = float('inf')
            
            # Application runs on Target host after EndTime
            target_host = row["Target"]
            mask = (host_samples["Host"] == target_host) & \
                   (host_samples["TimestampMs"] >= start_time) & \
                   (host_samples["TimestampMs"] < end_time)
            
            samples = host_samples.loc[mask, "MemoryCurrentBytes"]
            if not samples.empty:
                median_bytes = samples.median()
                post_mem.append(median_bytes / (1024 * 1024))
            else:
                post_mem.append(np.nan)
        handovers["PostCleanupMemoryMB"] = post_mem
    else:
        handovers["PostCleanupMemoryMB"] = np.nan

    # Load network packets
    net_packets_path = results_dir / "network-packets.csv"
    if net_packets_path.exists():
        # Handle the comma issue in TimeS if it exists. 
        # The user said: "TimeS,TimestampMs,Bytes,Channel \n 4,291221,1787219542667.314000,74,base"
        # This implies 5 columns where TimeS was split.
        try:
            net_df = pd.read_csv(net_packets_path)
            if "TimestampMs" not in net_df.columns:
                 # Try reading with different logic if it's malformed
                 net_df = pd.read_csv(net_packets_path, header=None, skiprows=1)
                 # Expecting: TimeS_whole, TimeS_frac, TimestampMs, Bytes, Channel
                 if len(net_df.columns) == 5:
                     net_df.columns = ["TimeS_w", "TimeS_f", "TimestampMs", "Bytes", "Channel"]
                 else:
                     raise ValueError("Unexpected network-packets.csv format")
        except Exception:
            # Fallback for the specific malformed format
            net_df = pd.read_csv(net_packets_path, sep=',', engine='python', on_bad_lines='warn')
            if len(net_df.columns) == 5:
                net_df.columns = ["TimeS_w", "TimeS_f", "TimestampMs", "Bytes", "Channel"]
            elif len(net_df.columns) == 4:
                net_df.columns = ["TimeS", "TimestampMs", "Bytes", "Channel"]

        # Ensure TimestampMs is numeric
        net_df["TimestampMs"] = pd.to_numeric(net_df["TimestampMs"], errors='coerce')
        net_df["Bytes"] = pd.to_numeric(net_df["Bytes"], errors='coerce')
        
        base_transfers = []
        event_transfers = []
        for idx, row in handovers.iterrows():
            mask = (net_df["TimestampMs"] >= row["StartTime"]) & \
                   (net_df["TimestampMs"] <= row["EndTime"])
            
            handover_packets = net_df.loc[mask]
            base_bytes = handover_packets.loc[handover_packets["Channel"] == "base", "Bytes"].sum()
            event_bytes = handover_packets.loc[handover_packets["Channel"] == "event", "Bytes"].sum()
            
            base_transfers.append(base_bytes / (1000 * 1000)) # Decimal MB as per analyze_recurrent_results.py
            event_transfers.append(event_bytes / (1000 * 1000))
            
        handovers["BaseTransferMB"] = base_transfers
        handovers["EventTransferMB"] = event_transfers
    else:
        handovers["BaseTransferMB"] = np.nan
        handovers["EventTransferMB"] = np.nan

    # Load experiment start time for alignment
    exp_start_ms = None
    if host_samples_path.exists():
        hs_temp = pd.read_csv(host_samples_path)
        if not hs_temp.empty:
            exp_start_ms = (hs_temp["TimestampMs"] - hs_temp["TimeS"] * 1000).median()

    # Authority Violations from results.csv
    results_path = results_dir / "results.csv"
    if results_path.exists() and exp_start_ms is not None:
        # Load only necessary columns from results.csv to save memory and time
        # New requirement: "only count duplicates if the ACK came from different addresses"
        res_df = pd.read_csv(results_path, usecols=["SentTimeS", "DuplicateAcks", "Address", "DuplicateAddresses"], low_memory=False)
        # Convert SentTimeS to absolute TimestampMs for alignment with migration windows
        res_df["AbsTimestampMs"] = exp_start_ms + res_df["SentTimeS"] * 1000.0
        
        # New definition: Violation if more than 1 ACK AND they came from different addresses.
        # DuplicateAddresses contains the addresses of the duplicate ACKs.
        # We check if DuplicateAcks > 0 and if DuplicateAddresses is not empty/null.
        # According to the experiment setup, DuplicateAddresses only contains addresses different from Address.
        res_df["NewViolation"] = ((res_df["DuplicateAcks"] > 0) & (res_df["DuplicateAddresses"].notna()) & (res_df["DuplicateAddresses"] != "")).astype(int)
        
        violation_percents = []
        violation_counts = []
        
        # Sort by timestamp to speed up windowing
        res_df = res_df.sort_values("AbsTimestampMs")
        
        for idx, row in handovers.iterrows():
            # Use searchsorted to find indices for the time window
            idx_start = res_df["AbsTimestampMs"].searchsorted(row["StartTime"], side='left')
            idx_end = res_df["AbsTimestampMs"].searchsorted(row["EndTime"], side='right')
            
            handover_res = res_df.iloc[idx_start:idx_end]
            
            total_packets = len(handover_res)
            violation_packets = handover_res["NewViolation"].sum()
            violation_percent = (violation_packets / total_packets * 100) if total_packets > 0 else 0
            
            violation_percents.append(violation_percent)
            violation_counts.append(violation_packets)
            
        handovers["AuthorityViolationsPercent"] = violation_percents
        handovers["AuthorityViolationsCount"] = violation_counts
        
        # Cleanup large dataframe
        del res_df
    else:
        handovers["AuthorityViolationsPercent"] = np.nan
        handovers["AuthorityViolationsCount"] = np.nan

    # Prepare final output
    output_df = handovers[[
        "HandoverId", "StartTime", "EndTime", "MigrationTimeS", "DowntimeMs",
        "PostCleanupMemoryMB", "BaseTransferMB", "EventTransferMB",
        "AuthorityViolationsPercent", "AuthorityViolationsCount"
    ]].copy()

    # CPU Core Seconds calculation
    cpu_core_seconds = []
    host_metrics = {}
    for host in ["sat1", "sat2"]:
        p = results_dir / f"{host}_host-metrics.csv"
        if p.exists():
            df = pd.read_csv(p)
            df["TimestampMs"] = pd.to_numeric(df["TimestampMs"], errors='coerce')
            df["CpuCores"] = pd.to_numeric(df["CpuCores"], errors='coerce')
            host_metrics[host] = df.sort_values("TimestampMs")

    # Find experiment start time in absolute ms
    # We use the fact that TimeS = (TimestampMs - StartTimeMs) / 1000
    # So StartTimeMs = TimestampMs - TimeS * 1000
    exp_start_ms = None
    if host_samples_path.exists():
        # Re-read to be safe
        hs_temp = pd.read_csv(host_samples_path)
        if not hs_temp.empty:
            exp_start_ms = (hs_temp["TimestampMs"] - hs_temp["TimeS"] * 1000).median()

    handover_intervals = []
    for idx, row in handovers.iterrows():
        t_start = row["StartTime"]
        t_end = row["EndTime"]
        
        # Interval since last migration or experiment start
        if idx == 0:
            interval_ms = t_start - exp_start_ms if exp_start_ms is not None else np.nan
        else:
            interval_ms = t_start - handovers.iloc[idx-1]["StartTime"]
        handover_intervals.append(interval_ms)

        total_cpu_work = 0.0
        
        for host, df in host_metrics.items():
            # The calculation: sum(CpuCores * overlap_duration)
            # We assume each sample represents the CPU usage until the next sample or some end.
            # But the user example shows:
            # Sample interval: 5.049102–6.055771 | Overlap with 6–12 s | CpuCores | Core-seconds
            # This means the CpuCores value at 6.055771 applies to the interval leading up to it.
            
            ts = df["TimestampMs"].to_numpy()
            cpu = df["CpuCores"].to_numpy()
            
            if len(ts) < 2:
                continue
                
            # Interval i is (ts[i-1], ts[i]) with CpuCores[i]
            for i in range(1, len(ts)):
                low = ts[i-1]
                high = ts[i]
                val = cpu[i]
                
                # Overlap between [low, high] and [t_start, t_end]
                overlap_start = max(low, t_start)
                overlap_end = min(high, t_end)
                
                if overlap_end > overlap_start:
                    duration_s = (overlap_end - overlap_start) / 1000.0
                    total_cpu_work += val * duration_s
                    
        cpu_core_seconds.append(total_cpu_work)
    
    output_df["CpuCoreSeconds"] = cpu_core_seconds
    
    # Migration Occupancy and Availability
    # MigrationTimeS is in seconds, interval_ms is in milliseconds
    handovers["IntervalMs"] = handover_intervals
    output_df["MigrationOccupancy"] = (output_df["MigrationTimeS"] * 1000.0) / handovers["IntervalMs"]
    output_df["Availability"] = 1.0 - (output_df["DowntimeMs"] / handovers["IntervalMs"])
    
    # Add Authority Violations to output_df
    output_df["AuthorityViolationsPercent"] = handovers["AuthorityViolationsPercent"]
    output_df["AuthorityViolationsCount"] = handovers["AuthorityViolationsCount"]
    
    stats_dir = results_dir.parent / "stats"
    stats_dir.mkdir(exist_ok=True)
    
    output_file = stats_dir / "stats_continuous_handover.csv"
    with open(output_file, 'w') as f:
        # Write custom header with duplicate names
        f.write("HandoverId,StartTime,EndTime,MigrationTimeS,DowntimeMs,PostCleanupMemoryMB,BaseTransferMB,EventTransferMB,CpuCoreSeconds,MigrationOccupancy,Availability,AuthorityViolations,AuthorityViolations\n")
        output_df[[
            "HandoverId", "StartTime", "EndTime", "MigrationTimeS", "DowntimeMs",
            "PostCleanupMemoryMB", "BaseTransferMB", "EventTransferMB",
            "CpuCoreSeconds", "MigrationOccupancy", "Availability", 
            "AuthorityViolationsPercent", "AuthorityViolationsCount"
        ]].to_csv(f, header=False, index=False)

    # Generate summary table
    summary_metrics = {
        "Migration time (s)": "MigrationTimeS",
        "Downtime (ms)": "DowntimeMs",
        "CPU consumption (core-s)": "CpuCoreSeconds",
        "Post-cleanup memory (MB)": "PostCleanupMemoryMB",
        "Base transfer (MB)": "BaseTransferMB",
        "Event transfer (MB)": "EventTransferMB",
        "Migration occupancy": "MigrationOccupancy",
        "Availability": "Availability"
    }
    
    summary_rows = []
    for label, col in summary_metrics.items():
        data = output_df[col].dropna()
        if not data.empty:
            median = data.median()
            p95 = data.quantile(0.95)
            first_20 = data.head(50).median()
            last_20 = data.tail(50).median()
            change = last_20 - first_20
            summary_rows.append({
                "Metric": label,
                "Median": median,
                "p95": p95,
                "Median of the first 20 values": first_20,
                "Median of the last 20 values": last_20,
                "Change": change
            })
        else:
            summary_rows.append({
                "Metric": label,
                "Median": np.nan,
                "p95": np.nan,
                "Median of the first 20 values": np.nan,
                "Median of the last 20 values": np.nan,
                "Change": np.nan
            })
            
    # Latency SLO compliance row
    if results_path.exists():
        res_df = pd.read_csv(results_path, low_memory=False)
        latency = pd.to_numeric(res_df["LatencyMs"], errors='coerce')
        total_packets = len(res_df)
        if total_packets > 0:
            violations = (latency.isna() | (latency > 20)).sum()
            violation_percent = (violations / total_packets)
        else:
            violation_percent = np.nan
            
        summary_rows.append({
            "Metric": "Latency SLO compliance (20 ms)",
            "Median": violation_percent,
            "p95": np.nan,
            "Median of the first 20 values": np.nan,
            "Median of the last 20 values": np.nan,
            "Change": np.nan
        })

    summary_df = pd.DataFrame(summary_rows)
    summary_file = stats_dir / "stats_summary_table.csv"
    summary_df.to_csv(summary_file, index=False)
    
    # Display version for printing
    print_df = output_df[[
        "HandoverId", "StartTime", "EndTime", "MigrationTimeS", "DowntimeMs",
        "PostCleanupMemoryMB", "BaseTransferMB", "EventTransferMB",
        "CpuCoreSeconds", "MigrationOccupancy", "Availability",
        "AuthorityViolationsPercent", "AuthorityViolationsCount"
    ]].copy()
    print_df.columns = [
        "HandoverId", "StartTime", "EndTime", "MigrationTimeS", "DowntimeMs",
        "PostCleanupMemoryMB", "BaseTransferMB", "EventTransferMB",
        "CpuCoreSeconds", "MigrationOccupancy", "Availability", 
        "AuthorityViolations(%)", "AuthorityViolations(count)"
    ]
    print("--- Continuous Handover Stats ---")
    print(print_df.to_string(index=False))
    print("\n--- Summary Table ---")
    print(summary_df.to_string(index=False))
    print(f"\nSaved results to {stats_dir}")

if __name__ == "__main__":
    main()
