#!/usr/bin/env python3

import argparse
import csv
import re
import signal
import socket
import statistics
import threading
import time
from collections import OrderedDict


DEFAULT_TARGETS = ["192.168.10.11", "192.168.10.12"]
DEFAULT_PORT = 5000
DEFAULT_TRACE = "50mbps_su_dcf_full.csv"
DEFAULT_OUTPUT = "results.csv"
MAX_UDP_PAYLOAD = 65507
ACK_TOKEN_SIZE = 32

CSV_FIELDS = [
    "Sequence",
    "TraceLoop",
    "ScheduledTimeS",
    "SentTimeS",
    "SendLatenessMs",
    "PayloadBytes",
    "WirePayloadBytes",
    "Targets",
    "Acked",
    "LatencyMs",
    "Address",
    "DuplicateAcks",
    "DuplicateAddresses",
    "AuthorityViolation",
    "SendError",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Replay every UDP packet to all configured hosts."
    )
    parser.add_argument(
        "--targets",
        nargs="+",
        default=DEFAULT_TARGETS,
        help="IPv4 addresses or hostnames that receive every packet "
             "(default: %(default)s).",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--trace", default=DEFAULT_TRACE)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--duration", type=float, default=0.0,
                        help="Run duration in seconds; 0 runs until SIGINT/SIGTERM.")
    parser.add_argument("--ack-timeout", type=float, default=2.0,
                        help="Seconds to retain each packet for ACK/duplicate detection.")
    parser.add_argument("--status-interval", type=float, default=60.0,
                        help="Seconds between progress messages; 0 disables them.")
    args = parser.parse_args()

    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    normalized_targets = [target.casefold() for target in args.targets]
    if len(set(normalized_targets)) != len(normalized_targets):
        parser.error("--targets must not contain duplicate addresses")
    if args.duration < 0:
        parser.error("--duration cannot be negative")
    if args.ack_timeout <= 0:
        parser.error("--ack-timeout must be positive")
    if args.status_interval < 0:
        parser.error("--status-interval cannot be negative")

    return args


def load_vr_trace(filename):
    """Load and normalize trace timestamps and UDP payload lengths."""
    packets = []
    zero_payload_packets = 0
    with open(filename, mode="r", encoding="utf-8") as trace_file:
        reader = csv.DictReader(trace_file)
        for row_number, row in enumerate(reader, start=2):
            try:
                timestamp = float(row["Time"])
                info = row.get("Info", "")
                length_match = re.search(r"Len=(\d+)", info)
                packet_length = (
                    int(length_match.group(1))
                    if length_match
                    else int(row.get("Length", 100))
                )
            except (TypeError, ValueError, KeyError):
                continue

            if timestamp < 0 or not 0 <= packet_length <= MAX_UDP_PAYLOAD:
                raise ValueError(
                    f"Invalid trace entry on row {row_number}: "
                    f"Time={timestamp}, payload length={packet_length}"
                )
            if packet_length == 0:
                zero_payload_packets += 1
            packets.append((timestamp, packet_length))

    if not packets:
        raise ValueError("The trace contains no usable packets")

    packets.sort(key=lambda item: item[0])
    first_timestamp = packets[0][0]
    packets = [(timestamp - first_timestamp, length) for timestamp, length in packets]

    positive_gaps = [
        packets[index][0] - packets[index - 1][0]
        for index in range(1, len(packets))
        if packets[index][0] > packets[index - 1][0]
    ]
    final_gap = statistics.median(positive_gaps) if positive_gaps else 1.0
    trace_period = packets[-1][0] + final_gap
    return packets, trace_period, zero_payload_packets


def resolve_targets(targets, port):
    """Resolve every hostname once so addresses cannot change during a run."""
    resolved = []
    seen_addresses = {}

    for target in targets:
        try:
            candidates = socket.getaddrinfo(
                target,
                port,
                family=socket.AF_INET,
                type=socket.SOCK_DGRAM,
            )
        except socket.gaierror as exc:
            raise ValueError(f"cannot resolve target '{target}': {exc}") from exc

        addresses = []
        for candidate in candidates:
            address = candidate[4][0]
            if address not in addresses:
                addresses.append(address)
        if not addresses:
            raise ValueError(f"target '{target}' has no IPv4 address")

        address = addresses[0]
        if address in seen_addresses:
            raise ValueError(
                f"targets '{seen_addresses[address]}' and '{target}' both resolve to {address}"
            )
        seen_addresses[address] = target
        resolved.append((target, address))

    return resolved


class BenchmarkState:
    def __init__(self):
        self.lock = threading.Lock()
        self.pending = OrderedDict()
        self.stats = {
            "sent": 0,
            "payload_bytes": 0,
            "wire_payload_bytes": 0,
            "first_acks": 0,
            "duplicate_acks": 0,
            "late_or_unknown_acks": 0,
            "finalized": 0,
            "lost": 0,
            "acked_payload_bytes": 0,
            "send_errors": 0,
            "authority_violations": 0,
        }

    def add_packet(self, token, record):
        with self.lock:
            self.pending[token] = record
            self.stats["sent"] += 1
            self.stats["payload_bytes"] += record["PayloadBytes"]

    def mark_send_success(self, token, payload_bytes):
        with self.lock:
            record = self.pending.get(token)
            if record is not None:
                record["WirePayloadBytes"] += payload_bytes
            self.stats["wire_payload_bytes"] += payload_bytes

    def mark_send_error(self, token, target, error):
        with self.lock:
            record = self.pending.get(token)
            if record is not None:
                entry = f"{target}: {error}"
                record["SendError"] = "; ".join(
                    part for part in (record["SendError"], entry) if part
                )
            self.stats["send_errors"] += 1

    def record_ack(self, data, address, received_at):
        with self.lock:
            record = self.pending.get(data)
            if record is None:
                self.stats["late_or_unknown_acks"] += 1
                return

            if not record["Acked"]:
                record["Acked"] = 1
                record["LatencyMs"] = round(
                    (received_at - record["_sent_perf"]) * 1000.0, 4
                )
                record["Address"] = address
                self.stats["first_acks"] += 1
            else:
                record["DuplicateAcks"] += 1
                record["_duplicate_addresses"].add(address)
                self.stats["duplicate_acks"] += 1
                if address != record["Address"] and not record["AuthorityViolation"]:
                    record["AuthorityViolation"] = 1
                    self.stats["authority_violations"] += 1

    def collect_expired(self, now, timeout, collect_all=False):
        rows = []
        with self.lock:
            while self.pending:
                token, record = next(iter(self.pending.items()))
                if not collect_all and now - record["_sent_perf"] < timeout:
                    break

                self.pending.pop(token)
                row = {field: record[field] for field in CSV_FIELDS}
                row["DuplicateAddresses"] = ";".join(
                    sorted(record["_duplicate_addresses"])
                )
                rows.append(row)

                self.stats["finalized"] += 1
                if record["Acked"]:
                    self.stats["acked_payload_bytes"] += record["PayloadBytes"]
                else:
                    self.stats["lost"] += 1

        return rows

    def snapshot_stats(self):
        with self.lock:
            return dict(self.stats), len(self.pending)


def receiver_worker(sock, state, stop_event):
    while not stop_event.is_set():
        try:
            data, address = sock.recvfrom(2048)
            state.record_ack(data, address[0], time.perf_counter())
        except socket.timeout:
            continue
        except (BlockingIOError, ConnectionRefusedError):
            continue
        except OSError:
            if stop_event.is_set():
                return
            raise


def make_payload(sequence, scheduled_time, requested_length):
    header = f"Seq={sequence}|Time={scheduled_time:.6f}|".encode("ascii")
    payload_length = max(requested_length, len(header))
    return header + b"#" * (payload_length - len(header))


def write_rows(writer, rows):
    if rows:
        writer.writerows(rows)


def main():
    args = parse_args()

    try:
        trace_packets, trace_period, zero_payload_packets = load_vr_trace(args.trace)
    except (OSError, ValueError) as exc:
        print(f"[Error] Could not load trace: {exc}")
        return 2

    print(
        f"[Sender] Loaded {len(trace_packets)} packets from '{args.trace}' "
        f"(period={trace_period:.6f}s)"
    )
    if zero_payload_packets:
        print(
            f"[Sender] Trace contains {zero_payload_packets} zero-payload UDP "
            "entries; they will carry only the benchmark header."
        )

    try:
        resolved_targets = resolve_targets(args.targets, args.port)
    except ValueError as exc:
        print(f"[Error] {exc}")
        return 2

    targets_csv = ";".join(
        label if label == address else f"{label}={address}"
        for label, address in resolved_targets
    )
    print(f"[Sender] Fan-out targets: {targets_csv}")

    state = BenchmarkState()
    run_event = threading.Event()
    run_event.set()
    receiver_stop = threading.Event()

    def request_stop(signum, _frame):
        print(f"\n[Sender] Received signal {signum}; stopping replay.")
        run_event.clear()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.1)

    receiver = threading.Thread(
        target=receiver_worker,
        args=(sock, state, receiver_stop),
        daemon=True,
    )
    receiver.start()

    sequence = 0
    packet_index = 0
    loop_count = 0
    start_perf = time.perf_counter()
    final_send_elapsed = 0.0
    next_flush = start_perf + 0.25
    next_status = (
        start_perf + args.status_interval
        if args.status_interval > 0
        else float("inf")
    )

    try:
        with open(args.output, mode="w", newline="", encoding="utf-8") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=CSV_FIELDS)
            writer.writeheader()

            while run_event.is_set():
                now = time.perf_counter()
                elapsed = now - start_perf
                if args.duration > 0 and elapsed >= args.duration:
                    break

                trace_time, packet_length = trace_packets[packet_index]
                scheduled_time = loop_count * trace_period + trace_time
                deadline = start_perf + scheduled_time

                if now >= deadline:
                    sequence += 1
                    payload = make_payload(sequence, scheduled_time, packet_length)
                    ack_token = payload[:ACK_TOKEN_SIZE]
                    sent_at = time.perf_counter()
                    sent_elapsed = sent_at - start_perf
                    record = {
                        "Sequence": sequence,
                        "TraceLoop": loop_count,
                        "ScheduledTimeS": round(scheduled_time, 6),
                        "SentTimeS": round(sent_elapsed, 6),
                        "SendLatenessMs": round((sent_at - deadline) * 1000.0, 4),
                        "PayloadBytes": len(payload),
                        "WirePayloadBytes": 0,
                        "Targets": targets_csv,
                        "Acked": 0,
                        "LatencyMs": "",
                        "Address": "",
                        "DuplicateAcks": 0,
                        "DuplicateAddresses": "",
                        "AuthorityViolation": 0,
                        "SendError": "",
                        "_sent_perf": sent_at,
                        "_duplicate_addresses": set(),
                    }
                    state.add_packet(ack_token, record)

                    for target_label, target_address in resolved_targets:
                        try:
                            sock.sendto(payload, (target_address, args.port))
                            state.mark_send_success(ack_token, len(payload))
                        except OSError as exc:
                            state.mark_send_error(
                                ack_token,
                                f"{target_label}={target_address}",
                                exc,
                            )

                    final_send_elapsed = sent_elapsed
                    packet_index += 1
                    if packet_index == len(trace_packets):
                        packet_index = 0
                        loop_count += 1
                else:
                    time.sleep(min(0.0005, max(0.0, deadline - now)))

                now = time.perf_counter()
                if now >= next_flush:
                    write_rows(
                        writer,
                        state.collect_expired(now, args.ack_timeout),
                    )
                    output_file.flush()
                    next_flush = now + 0.25

                if now >= next_status:
                    stats, pending_count = state.snapshot_stats()
                    print(
                        f"[Sender] elapsed={now - start_perf:.1f}s "
                        f"sent={stats['sent']} acked={stats['first_acks']} "
                        f"lost={stats['lost']} duplicates={stats['duplicate_acks']} "
                        f"authority_violations={stats['authority_violations']} "
                        f"trace_loops={loop_count} "
                        f"pending={pending_count}"
                    )
                    next_status = now + args.status_interval

            print(f"[Sender] Replay stopped after {time.perf_counter() - start_perf:.3f}s")
            print(f"[Sender] Waiting {args.ack_timeout:.3f}s for final ACKs...")
            drain_deadline = time.perf_counter() + args.ack_timeout
            while time.perf_counter() < drain_deadline:
                time.sleep(0.05)

            receiver_stop.set()
            receiver.join(timeout=1.0)
            write_rows(
                writer,
                state.collect_expired(time.perf_counter(), 0.0, collect_all=True),
            )
            output_file.flush()

    finally:
        receiver_stop.set()
        receiver.join(timeout=1.0)
        sock.close()

    stats, pending_count = state.snapshot_stats()
    measured_duration = max(final_send_elapsed, 1e-9)
    offered_mbps = stats["payload_bytes"] * 8.0 / measured_duration / 1_000_000.0
    fanout_mbps = (
            stats["wire_payload_bytes"] * 8.0 / measured_duration / 1_000_000.0
    )
    goodput_mbps = (
            stats["acked_payload_bytes"] * 8.0 / measured_duration / 1_000_000.0
    )
    loss_percent = (
        stats["lost"] * 100.0 / stats["finalized"]
        if stats["finalized"]
        else 0.0
    )

    print(f"[Sender] Results written incrementally to '{args.output}'")
    print(
        f"[Sender] sent={stats['sent']} acked={stats['first_acks']} "
        f"lost={stats['lost']} ({loss_percent:.6f}%) "
        f"duplicates={stats['duplicate_acks']} "
        f"authority_violations={stats['authority_violations']} "
        f"late_or_unknown_acks={stats['late_or_unknown_acks']} "
        f"send_errors={stats['send_errors']} pending={pending_count}"
    )
    print(
        f"[Sender] logical_udp_payload={offered_mbps:.6f} Mbit/s | "
        f"fanout_udp_payload={fanout_mbps:.6f} Mbit/s | "
        f"acknowledged_udp_payload={goodput_mbps:.6f} Mbit/s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())