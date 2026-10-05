#!/usr/bin/env python3
"""Analyze recurrent-migration soak experiment results.

Required sender input (the CSV written by sender.py):
    Sequence,TraceLoop,SentTimeS,PayloadBytes,WirePayloadBytes,Acked,...

Optional inputs unlock metrics that the sender cannot observe:

Host samples (--host-samples / --baseline-host-samples):
    TimeS,Host,CpuCores[,MemoryCurrentBytes,MemoryPeakBytes]

Migration events (--migrations), one row per attempted handover:
    Migration,StartTimeS,EndTimeS[,Completed,DowntimeMs,BaseBytes,
    EventBytes,TotalBytes,ReplayLag]

Migration traffic samples (--migration-traffic):
    TimeS,MigrationBytes

MigrationBytes is the byte delta represented by each observation, not a
cumulative counter. Times are seconds relative to the sender experiment start.
Network values use decimal MB (1 MB = 1,000,000 bytes).
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


MB = 1_000_000.0

METRIC_DEFINITIONS = [
    ("mean_cpu_cores", "Mean satellite-side CPU", "cores"),
    ("migration_cpu_cores", "CPU during active migration", "cores"),
    ("extra_cpu_per_handover", "Extra CPU per handover", "core-s"),
    ("base_mb_per_handover", "Base transfer", "MB/handover"),
    ("event_mb_per_handover", "Event transfer", "MB/handover"),
    ("migration_mb_per_handover", "Migration traffic", "MB/handover"),
    ("peak_1s_migration_mbps", "Peak 1-second migration rate", "Mbit/s"),
    ("logical_udp_mbps", "UDP application traffic", "Mbit/s"),
    ("fanout_udp_mbps", "UDP fan-out traffic", "Mbit/s"),
    ("acknowledged_udp_mbps", "Acknowledged UDP goodput", "Mbit/s"),
    ("duration_s", "Experiment duration", "s"),
    ("packets_sent", "Packets sent", "packets"),
    ("packets_acked", "Packets ACKed", "packets"),
    ("packets_lost", "Packets lost", "packets"),
    ("packet_loss_percent", "Packet loss", "%"),
    ("packet_availability_percent", "Packet availability", "%"),
    ("slo_availability_percent", "End-to-end SLO availability", "%"),
    ("rtt_mean_ms", "RTT mean", "ms"),
    ("rtt_p50_ms", "RTT p50", "ms"),
    ("rtt_p95_ms", "RTT p95", "ms"),
    ("rtt_p99_ms", "RTT p99", "ms"),
    ("rtt_max_ms", "RTT maximum", "ms"),
    ("send_lateness_p95_ms", "Send lateness p95", "ms"),
    ("send_lateness_p99_ms", "Send lateness p99", "ms"),
    ("duplicate_acks", "Duplicate ACKs", "ACKs"),
    ("authority_violation_packets", "Authority-violation packets", "packets"),
    ("authority_violation_percent", "Authority violations", "% of packets"),
    ("non_monotonic_app_counts", "Non-monotonic application counters", "packets"),
    ("send_error_packets", "Packets with send errors", "packets"),
    ("responding_hosts", "Distinct responding hosts", "hosts"),
    ("trace_loops_observed", "Trace loops observed", "loops"),
    ("trace_loops_completed", "Complete trace loops", "loops"),
    ("rtt_slope_per_100_loops", "RTT soak slope", "ms/100 loops"),
    ("loss_slope_per_100_loops", "Loss soak slope", "percentage points/100 loops"),
    ("migrations_attempted", "Migrations attempted", "handovers"),
    ("migrations_completed", "Migrations completed", "handovers"),
    ("migration_success_percent", "Migration success", "%"),
    ("migration_time_p50_s", "Migration time p50", "s"),
    ("migration_time_p95_s", "Migration time p95", "s"),
    ("migration_time_max_s", "Migration time maximum", "s"),
    ("downtime_p50_ms", "Downtime p50", "ms"),
    ("downtime_p95_ms", "Downtime p95", "ms"),
    ("downtime_max_ms", "Downtime maximum", "ms"),
    ("replay_lag_p95", "Replay lag p95", "events"),
    ("replay_lag_max", "Replay lag maximum", "events"),
    ("migration_occupancy_percent", "Migration occupancy", "%"),
    ("migration_time_slope_per_100", "Migration-time soak slope", "s/100 handovers"),
    ("downtime_slope_per_100", "Downtime soak slope", "ms/100 handovers"),
    ("rss_start_mb", "Satellite-side memory at start", "MB"),
    ("rss_end_mb", "Satellite-side memory at end", "MB"),
    ("rss_sum_host_peaks_mb", "Sum of per-host peak memory", "MB"),
]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", help="Recurrent sender results CSV")
    parser.add_argument("--baseline", help="No-migration sender results CSV")
    parser.add_argument("--slo-ms", type=float,
                        help="RTT SLO used for end-to-end availability")
    parser.add_argument("--host-samples", help="Recurrent cgroup CPU/memory CSV")
    parser.add_argument("--baseline-host-samples",
                        help="No-migration cgroup CPU/memory CSV")
    parser.add_argument("--sat1-log", help="sat1_iwasm.log path")
    parser.add_argument("--sat2-log", help="sat2_iwasm.log path")
    parser.add_argument("--migrations", help="Per-handover migration CSV (deprecated)")
    parser.add_argument("--migration-traffic",
                        help="Timestamped migration-byte CSV")
    parser.add_argument("--output", help="Metrics CSV output path")
    parser.add_argument("--json-output", help="Metrics JSON output path")
    args = parser.parse_args()

    if args.slo_ms is not None and args.slo_ms <= 0:
        parser.error("--slo-ms must be positive")

    source = Path(args.results)
    args.output = args.output or str(source.with_name(source.stem + "-metrics.csv"))
    args.json_output = args.json_output or str(
        source.with_name(source.stem + "-metrics.json")
    )
    return args


def read_csv(path, required):
    frame = pd.read_csv(path)
    missing = set(required) - set(frame.columns)
    if missing:
        raise ValueError(f"{path} is missing required columns: {sorted(missing)}")
    if frame.empty:
        raise ValueError(f"{path} contains no data rows")
    return frame


def numeric(frame, column, default=np.nan):
    if column not in frame:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def booleans(frame, column, default=False):
    if column not in frame:
        return pd.Series(default, index=frame.index, dtype=bool)
    text = frame[column].astype("string").str.strip().str.casefold()
    result = text.isin({"1", "true", "yes", "y", "completed"})
    return result | (text.isna() | text.eq("")) if default else result


def percentile(values, q):
    values = pd.Series(values).dropna().to_numpy(dtype=float)
    return float(np.percentile(values, q)) if values.size else None


def slope(values, x=None):
    values = pd.Series(values)
    valid = values.notna().to_numpy()
    if valid.sum() < 2:
        return None
    y = values.to_numpy(dtype=float)[valid]
    x_values = (
        values.index.to_numpy(dtype=float)[valid]
        if x is None
        else np.asarray(x, dtype=float)[valid]
    )
    if np.ptp(x_values) == 0:
        return None
    return float(np.polyfit(x_values, y, 1)[0])


def percent(numerator, denominator):
    return float(numerator * 100.0 / denominator) if denominator else None


class PacketAnalysis:
    REQUIRED = {"Sequence", "SentTimeS", "PayloadBytes", "Acked"}

    def __init__(self, path, slo_ms):
        self.path = str(path)
        self.slo_ms = slo_ms
        self.data = read_csv(path, self.REQUIRED)
        self.metrics, self.details = self._analyze()

    def _analyze(self):
        data = self.data
        sent_time = numeric(data, "SentTimeS")
        payload = numeric(data, "PayloadBytes")
        wire = numeric(data, "WirePayloadBytes") if "WirePayloadBytes" in data else payload
        acked = booleans(data, "Acked")
        latency = numeric(data, "LatencyMs")
        lateness = numeric(data, "SendLatenessMs")

        if sent_time.isna().any() or payload.isna().any():
            raise ValueError(f"{self.path} contains invalid times or payload lengths")
        if (payload < 0).any() or wire.isna().any() or (wire < 0).any():
            raise ValueError(f"{self.path} contains invalid byte counts")

        sent = len(data)
        ack_count = int(acked.sum())
        lost = sent - ack_count
        duration = max(float(sent_time.max()), 0.0)
        rtt = latency[acked & latency.notna()]
        responding = (
            data.loc[acked, "Address"].fillna("").astype(str).str.strip()
            if "Address" in data else pd.Series(dtype=str)
        )
        responding = responding[responding.ne("")]

        trace_loop = numeric(data, "TraceLoop", 0).fillna(0).astype(int)
        loops = pd.DataFrame({
            "TraceLoop": trace_loop,
            "Acked": acked.astype(int),
            "RTT": latency.where(acked),
        }).groupby("TraceLoop", sort=True).agg(
            sent=("Acked", "size"),
            acked=("Acked", "sum"),
            rtt_mean=("RTT", "mean"),
        )
        loops["loss_percent"] = (loops["sent"] - loops["acked"]) * 100 / loops["sent"]
        expected = int(loops.iloc[0]["sent"])
        complete_loops = int(loops["sent"].eq(expected).sum())

        duplicates = numeric(data, "DuplicateAcks", 0).fillna(0).sum()
        authority = int(booleans(data, "AuthorityViolation").sum())
        non_monotonic = int(booleans(data, "AppCountNonMonotonic").sum())
        send_errors = (
            int(data["SendError"].fillna("").astype(str).str.strip().ne("").sum())
            if "SendError" in data else 0
        )
        slo_compliant = (
            int((acked & latency.notna() & latency.le(self.slo_ms)).sum())
            if self.slo_ms is not None else None
        )

        rtt_slope = slope(loops["rtt_mean"], loops.index.to_numpy())
        loss_slope = slope(loops["loss_percent"], loops.index.to_numpy())
        metrics = {
            "duration_s": duration,
            "packets_sent": sent,
            "packets_acked": ack_count,
            "packets_lost": lost,
            "packet_loss_percent": percent(lost, sent),
            "packet_availability_percent": percent(ack_count, sent),
            "slo_availability_percent": percent(slo_compliant, sent)
            if slo_compliant is not None else None,
            "logical_udp_mbps": float(payload.sum() * 8 / duration / MB)
            if duration > 0 else None,
            "fanout_udp_mbps": float(wire.sum() * 8 / duration / MB)
            if duration > 0 else None,
            "acknowledged_udp_mbps": float(payload[acked].sum() * 8 / duration / MB)
            if duration > 0 else None,
            "rtt_mean_ms": float(rtt.mean()) if not rtt.empty else None,
            "rtt_p50_ms": percentile(rtt, 50),
            "rtt_p95_ms": percentile(rtt, 95),
            "rtt_p99_ms": percentile(rtt, 99),
            "rtt_max_ms": float(rtt.max()) if not rtt.empty else None,
            "send_lateness_p95_ms": percentile(lateness, 95),
            "send_lateness_p99_ms": percentile(lateness, 99),
            "duplicate_acks": int(duplicates),
            "authority_violation_packets": authority,
            "authority_violation_percent": percent(authority, sent),
            "non_monotonic_app_counts": non_monotonic,
            "send_error_packets": send_errors,
            "responding_hosts": int(responding.nunique()),
            "trace_loops_observed": len(loops),
            "trace_loops_completed": complete_loops,
            "rtt_slope_per_100_loops": multiply(rtt_slope, 100),
            "loss_slope_per_100_loops": multiply(loss_slope, 100),
        }
        details = {
            "input": self.path,
            "responding_host_ack_counts": {
                str(key): int(value) for key, value in responding.value_counts().items()
            },
            "rtt_observations": len(rtt),
            "quantiles_are_sampled": False,
        }
        return metrics, details

    @property
    def duration(self):
        return self.metrics["duration_s"]


def merge_intervals(intervals):
    merged = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def mean_mb(values):
    values = pd.Series(values).dropna()
    return float(values.mean() / MB) if len(values) else None


def finite_max(values):
    values = pd.Series(values).dropna()
    return float(values.max()) if len(values) else None


def multiply(value, factor):
    return value * factor if value is not None else None


class MigrationAnalysis:
    def __init__(self, sat1_log, sat2_log, experiment_duration, host_samples=None):
        self.experiment_duration = experiment_duration
        self.data = self._parse_logs(sat1_log, sat2_log, host_samples)
        self.metrics = self._metrics()

    def _parse_logs(self, sat1_log, sat2_log, host_samples):
        import re
        events = []
        start_re = re.compile(r"Migration is initiated \((\d+\.\d+) ms\)")
        comp_re = re.compile(r"Live migration completed at (\d+\.\d+) ms")
        rest_re = re.compile(r"Live migration restored at (\d+\.\d+) ms")

        for host, log_path in [("sat1", sat1_log), ("sat2", sat2_log)]:
            if not log_path or not Path(log_path).exists():
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
        
        migrations = []
        i = 0
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
                    migrations.append({
                        "StartTimeMs": start_event["ts"],
                        "EndTimeMs": rest_event["ts"],
                        "CompTimeMs": comp_event["ts"],
                        "Completed": True,
                        "DowntimeMs": rest_event["ts"] - comp_event["ts"],
                        "DurationS": (rest_event["ts"] - start_event["ts"]) / 1000.0
                    })
            i += 1
        
        df = pd.DataFrame(migrations)
        if df.empty:
            return pd.DataFrame(columns=["StartTimeS", "EndTimeS", "DurationS", "DowntimeMs", "Completed"])

        if host_samples is not None:
            # Try to align with experiment relative TimeS if host_samples are available
            # We find the offset between TimestampMs and TimeS in host_samples
            first_sample = host_samples.iloc[0]
            ts_offset = first_sample["TimestampMs"] - (first_sample["TimeS"] * 1000.0)
            df["StartTimeS"] = (df["StartTimeMs"] - ts_offset) / 1000.0
            df["EndTimeS"] = (df["EndTimeMs"] - ts_offset) / 1000.0
        else:
            # Fallback if no host samples: use absolute timestamps or relative to first migration
            df["StartTimeS"] = df["StartTimeMs"] / 1000.0
            df["EndTimeS"] = df["EndTimeMs"] / 1000.0
            
        return df

    @property
    def completed(self):
        return self.data[self.data.get("Completed", False)]

    @property
    def windows(self):
        if "StartTimeS" not in self.data or "EndTimeS" not in self.data:
            return []
        return list(self.completed[["StartTimeS", "EndTimeS"]].itertuples(
            index=False, name=None
        ))

    def _metrics(self):
        completed = self.completed
        if completed.empty:
            return {
                "migrations_attempted": 0,
                "migrations_completed": 0,
                "migration_success_percent": None,
                "migration_time_p50_s": None,
                "migration_time_p95_s": None,
                "migration_time_max_s": None,
                "downtime_p50_ms": None,
                "downtime_p95_ms": None,
                "downtime_max_ms": None,
                "migration_occupancy_percent": None,
            }

        durations = completed["DurationS"].reset_index(drop=True)
        downtime = completed["DowntimeMs"].dropna().reset_index(drop=True)
        merged_duration = sum(end - start for start, end in merge_intervals(self.windows))
        return {
            "migrations_attempted": len(self.data),
            "migrations_completed": len(completed),
            "migration_success_percent": percent(len(completed), len(self.data)),
            "migration_time_p50_s": percentile(durations, 50),
            "migration_time_p95_s": percentile(durations, 95),
            "migration_time_max_s": float(durations.max()) if len(durations) else None,
            "downtime_p50_ms": percentile(downtime, 50),
            "downtime_p95_ms": percentile(downtime, 95),
            "downtime_max_ms": float(downtime.max()) if len(downtime) else None,
            "base_mb_per_handover": mean_mb(completed.get("BaseBytes")),
            "event_mb_per_handover": mean_mb(completed.get("EventBytes")),
            "migration_mb_per_handover": mean_mb(completed.get("TotalBytes")),
            "replay_lag_p95": percentile(completed.get("ReplayLag"), 95),
            "replay_lag_max": finite_max(completed.get("ReplayLag")),
            "migration_occupancy_percent": percent(
                merged_duration, self.experiment_duration
            ),
            "migration_time_slope_per_100": multiply(slope(durations), 100),
            "downtime_slope_per_100": multiply(slope(downtime), 100),
        }


class HostAnalysis:
    REQUIRED = {"TimeS", "Host", "CpuCores"}

    def __init__(self, path, experiment_duration):
        self.data = read_csv(path, self.REQUIRED).copy()
        self.experiment_duration = experiment_duration
        self.data["TimeS"] = numeric(self.data, "TimeS")
        self.data["CpuCores"] = numeric(self.data, "CpuCores")
        self.data["Host"] = self.data["Host"].fillna("").astype(str).str.strip()
        memory_column = (
            "MemoryCurrentBytes"
            if "MemoryCurrentBytes" in self.data
            else "RssBytes"
        )
        self.data["MemoryCurrentBytes"] = numeric(self.data, memory_column)
        self.data["MemoryPeakBytes"] = numeric(self.data, "MemoryPeakBytes")
        invalid = (
            self.data[["TimeS", "CpuCores"]].isna().any(axis=1)
            | self.data["Host"].eq("")
        )
        if invalid.any():
            raise ValueError(f"{path} contains invalid host samples")
        self.data.sort_values(["Host", "TimeS"], inplace=True)
        self.metrics = self._metrics()

    def cpu_core_seconds(self, start=0.0, end=None):
        end = self.experiment_duration if end is None else end
        if end <= start:
            return 0.0
        total = 0.0
        for _, samples in self.data.groupby("Host", sort=False):
            times = samples["TimeS"].to_numpy(dtype=float)
            cpu = samples["CpuCores"].to_numpy(dtype=float)
            segment_ends = np.append(times[1:], end)
            overlap = np.maximum(
                np.minimum(segment_ends, end) - np.maximum(times, start), 0.0
            )
            total += float(np.sum(cpu * overlap))
        return total

    def cpu_during(self, intervals):
        intervals = merge_intervals(intervals)
        duration = sum(end - start for start, end in intervals)
        if duration <= 0:
            return None
        core_seconds = sum(self.cpu_core_seconds(start, end) for start, end in intervals)
        return core_seconds / duration

    def _metrics(self):
        metrics = {
            "mean_cpu_cores": self.cpu_core_seconds() / self.experiment_duration
            if self.experiment_duration > 0 else None
        }
        memory = self.data.dropna(subset=["MemoryCurrentBytes"])
        if not memory.empty:
            grouped = memory.groupby("Host")["MemoryCurrentBytes"].agg(
                ["first", "last", "max"]
            )
            reported_peaks = self.data.dropna(subset=["MemoryPeakBytes"])
            peak_sum = (
                reported_peaks.groupby("Host")["MemoryPeakBytes"].max().sum()
                if not reported_peaks.empty
                else grouped["max"].sum()
            )
            metrics.update({
                "rss_start_mb": float(grouped["first"].sum() / MB),
                "rss_end_mb": float(grouped["last"].sum() / MB),
                "rss_sum_host_peaks_mb": float(peak_sum / MB),
            })
        return metrics


def analyze_migration_traffic(path):
    data = read_csv(path, {"TimeS", "MigrationBytes"}).copy()
    data["TimeS"] = numeric(data, "TimeS")
    data["MigrationBytes"] = numeric(data, "MigrationBytes")
    if (data[["TimeS", "MigrationBytes"]].isna().any().any()
            or (data["MigrationBytes"] < 0).any()):
        raise ValueError(f"{path} contains invalid migration-traffic samples")
    data.sort_values("TimeS", inplace=True)
    index = pd.to_timedelta(data["TimeS"], unit="s")
    byte_deltas = pd.Series(data["MigrationBytes"].to_numpy(), index=index)
    peak_bytes = byte_deltas.rolling("1s").sum().max()
    return float(peak_bytes * 8 / MB)


def format_value(value):
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "N/A"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return f"{float(value):.6f}"


def native_metrics(metrics):
    return {
        key: (
            None if value is None or (isinstance(value, float) and not math.isfinite(value))
            else int(value) if isinstance(value, (int, np.integer))
            else float(value)
        )
        for key, value in metrics.items()
    }


def write_reports(args, baseline, recurrent, details):
    rows = [
        {
            "Metric": label,
            "No migration": format_value(baseline.get(key)),
            "Recurrent migration": format_value(recurrent.get(key)),
            "Unit": unit,
        }
        for key, label, unit in METRIC_DEFINITIONS
    ]
    report = pd.DataFrame(rows)
    report.to_csv(args.output, index=False)

    with open(args.json_output, "w", encoding="utf-8") as handle:
        json.dump({
            "slo_ms": args.slo_ms,
            "raw_metrics": {
                "no_migration": native_metrics(baseline),
                "recurrent_migration": native_metrics(recurrent),
            },
            "metrics": rows,
            "details": details,
        }, handle, indent=2, sort_keys=True)
        handle.write("\n")

    print(report.to_string(index=False))


def main():
    args = parse_args()
    try:
        recurrent_packets = PacketAnalysis(args.results, args.slo_ms)
        recurrent = dict(recurrent_packets.metrics)
        baseline = {}
        details = {"recurrent": recurrent_packets.details}

        baseline_packets = None
        if args.baseline:
            baseline_packets = PacketAnalysis(args.baseline, args.slo_ms)
            baseline.update(baseline_packets.metrics)
            details["baseline"] = baseline_packets.details

        recurrent_host = None
        if args.host_samples:
            recurrent_host = HostAnalysis(args.host_samples, recurrent_packets.duration)
            recurrent.update(recurrent_host.metrics)

        migrations = None
        if args.sat1_log and args.sat2_log:
            migrations = MigrationAnalysis(
                args.sat1_log, args.sat2_log, recurrent_packets.duration,
                recurrent_host.data if recurrent_host else None
            )
            recurrent.update(migrations.metrics)
        elif args.migrations:
            # Fallback to old behavior if migrations.csv is provided but not logs
            class LegacyMigrationAnalysis(MigrationAnalysis):
                REQUIRED = {"StartTimeS", "EndTimeS"}
                def __init__(self, path, experiment_duration):
                    self.data = read_csv(path, self.REQUIRED).copy()
                    self.experiment_duration = experiment_duration
                    self._prepare(path)
                    self.metrics = self._metrics()
                def _prepare(self, path):
                    for column in ["StartTimeS", "EndTimeS", "DowntimeMs", "BaseBytes",
                                   "EventBytes", "TotalBytes", "ReplayLag"]:
                        self.data[column] = numeric(self.data, column)
                    self.data["Completed"] = booleans(self.data, "Completed", True)
                    self.data["DurationS"] = self.data["EndTimeS"] - self.data["StartTimeS"]
                    derived_total = self.data["BaseBytes"] + self.data["EventBytes"]
                    self.data["TotalBytes"] = self.data["TotalBytes"].fillna(derived_total)
            
            migrations = LegacyMigrationAnalysis(args.migrations, recurrent_packets.duration)
            recurrent.update(migrations.metrics)

        baseline_host = None
        if args.baseline_host_samples:
            if baseline_packets is None:
                raise ValueError("--baseline-host-samples requires --baseline")
            baseline_host = HostAnalysis(
                args.baseline_host_samples, baseline_packets.duration
            )
            baseline.update(baseline_host.metrics)

        if migrations and recurrent_host:
            recurrent["migration_cpu_cores"] = recurrent_host.cpu_during(
                migrations.windows
            )

        if migrations and recurrent_host and baseline_host and len(migrations.completed):
            baseline_rate = baseline.get("mean_cpu_cores")
            recurrent["extra_cpu_per_handover"] = (
                recurrent_host.cpu_core_seconds()
                - baseline_rate * recurrent_packets.duration
            ) / len(migrations.completed)

        if args.migration_traffic:
            recurrent["peak_1s_migration_mbps"] = analyze_migration_traffic(
                args.migration_traffic
            )

        write_reports(args, baseline, recurrent, details)
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        print(f"[Error] {exc}")
        return 2

    print(f"\nMetrics CSV: {args.output}")
    print(f"Metrics JSON: {args.json_output}")
    if not recurrent_host:
        print("Note: CPU/RSS metrics require --host-samples.")
    if not migrations:
        print("Note: per-handover metrics require --sat1-log and --sat2-log.")
    if not args.migration_traffic:
        print("Note: peak migration rate requires --migration-traffic.")
    if not args.baseline:
        print("Note: the no-migration column requires --baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
