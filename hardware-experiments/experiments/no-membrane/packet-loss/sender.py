#!/usr/bin/env python3
import csv
import json
import socket
import sys
import time
import signal

# ==========================================
# EXPERIMENT CONFIGURATION
# ==========================================
SENSOR_PORT = 5005
SAT1_IP = "192.168.10.11"
SAT2_IP = "192.168.10.12"

TRACE_CSV_PATH = "50mbps_su_dcf_full.csv"
SIMULATION_DURATION_S = 60
LATENCY_CSV_PATH = "sender_loop_metrics.csv"
# ==========================================

active_sat_ip = SAT1_IP

def handle_handover(signum, frame):
    global active_sat_ip
    active_sat_ip = SAT2_IP
    print(f"\n[SIGNAL] SIGUSR1 received. Switching destination to {active_sat_ip}")

# Register the signal handler for live handover
signal.signal(signal.SIGUSR1, handle_handover)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setblocking(False)

print("=========================================================")
print(" Starting Multiplexed XR Telemetry Replay (UDP)")
print(f" Parsing trace data from: {TRACE_CSV_PATH}")
print(f" Initial Target Destination: sat1 ({active_sat_ip}:{SENSOR_PORT})")
print("=========================================================")

seq_id = 0
loop_latencies = []

try:
    with open(TRACE_CSV_PATH, mode="r") as infile:
        reader = csv.DictReader(infile)
        last_packet_time = None

        simulation_start_time = time.perf_counter()
        for row in reader:
            if row.get("Protocol") != "UDP":
                continue

            loop_start = time.perf_counter()
            tx_time_ns = time.time_ns()

            current_packet_time = float(row["Time"])
            packet_length = int(row["Length"])
            source_address = row["Source"]

            if current_packet_time > SIMULATION_DURATION_S:
                print(f"\n[INFO] Reached simulation duration limit of {SIMULATION_DURATION_S} seconds. Stopping.")
                break

            tenant_id = (
                "tenant_costas_downstream"
                if source_address == "192.168.50.185"
                else "tenant_costas_upstream"
            )

            payload = {
                "tenant_id": tenant_id,
                "seq_id": seq_id,
                "timestamp_ns": tx_time_ns,
                "packet_time": current_packet_time,
                "pose_6dof": [0.542, -1.219, 0.984, 12.4, -89.1, 0.5],
                "real_trace_len": packet_length,
            }

            base_packet = json.dumps(payload).encode("utf-8")
            padding_needed = max(0, packet_length - len(base_packet))
            final_packet = base_packet + (b"X" * padding_needed)

            sock.sendto(final_packet, (active_sat_ip, SENSOR_PORT))

            if seq_id % 1000 == 0:
                print(f"[PROGRESS] Replayed {seq_id} (packet time {current_packet_time:.5f}s) network packets to {active_sat_ip}...")

            if last_packet_time is not None:
                trace_delta = current_packet_time - last_packet_time
                sleep_interval = min(max(0, trace_delta), 0.050)

                elapsed = time.perf_counter() - loop_start
                remaining = sleep_interval - elapsed
                if remaining > 0:
                    time.sleep(remaining)

            last_packet_time = current_packet_time
            loop_latencies.append((time.perf_counter() - loop_start) * 1000)
            seq_id += 1
        simulation_end_time = time.perf_counter()
        print(f"\n[SUCCESS] Replay complete. Total time: {simulation_end_time - simulation_start_time:.2f} seconds")

except FileNotFoundError:
    print(f"\n[ERROR] Could not find the trace CSV file at '{TRACE_CSV_PATH}'.")
    sys.exit(1)
except KeyboardInterrupt:
    print("\n[INFO] Sender stopped manually.")
finally:
    sock.close()

if loop_latencies:
    with open(LATENCY_CSV_PATH, "w", newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["seq_id", "loop_duration_ms"])
        for i, lat in enumerate(loop_latencies):
            writer.writerow([i, lat])
    print(f"[SUCCESS] Sender trace ended. Metrics stored to {LATENCY_CSV_PATH}")