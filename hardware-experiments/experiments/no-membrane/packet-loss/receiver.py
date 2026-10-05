#!/usr/bin/env python3
import socket
import json
import time
import os
import csv
import numpy as np

# ==========================================
# RECEIVER CONFIGURATION
# ==========================================
UDP_IP = "0.0.0.0"
UDP_PORT = 5005
SOCKET_PATH = "/data/xr_ingress.sock"
LOG_PATH = "/data/results_packet_loss.csv"

received_packets = 0

# Multi-tenant state tracking dictionary stored directly on the heap
tenant_sessions = {}

# Pre-allocate a projection reference matrix to simulate spatial re-rendering calculations
PROJECTION_MATRIX = np.random.rand(4, 4)

# Ensure any stale socket file from a previous crash is cleaned up
if os.path.exists(SOCKET_PATH):
    os.remove(SOCKET_PATH)

# Instantiate and bind socket
sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
sock.bind(SOCKET_PATH)

os.chmod(SOCKET_PATH, 0o777)

print(f"=========================================================")
print(f" Stateful XR Heavy Receiver Active on UDP Port {UDP_PORT}")
print(f" Writing evaluation logs directly to: {LOG_PATH}")
print(f"=========================================================")

with open(LOG_PATH, "a", buffering=1, newline='') as log_file:
    writer = csv.writer(log_file)
    # Write header if file is empty
    if os.stat(LOG_PATH).st_size == 0:
        writer.writerow(["Sequence", "Time", "Latency"])

    while True:
        # Accept packets up to maximum theoretical UDP size (65535 bytes)
        data, addr = sock.recvfrom(65535)
        recv_timestamp_ns = time.time_ns()

        try:
            # Isolate our structured json metadata block from trailing padding bytes
            end_json_idx = data.rfind(b'}') + 1
            clean_json = data[:end_json_idx].decode('utf-8')

            payload = json.loads(clean_json)
            tenant_id = payload.get("tenant_id", "unknown_tenant")
            seq_id = payload["seq_id"]
            tx_timestamp_ns = payload["timestamp_ns"]
            packet_time = payload["packet_time"]
            pose_data = payload.get("pose_6dof", [0.0] * 6)

            # --- WORKLOAD 1: Continuous Heap Accumulation ---
            # Storing stateful history context across migration events
            if tenant_id not in tenant_sessions:
                tenant_sessions[tenant_id] = {
                    "total_packets": 0,
                    "seen_sequences": []
                }

            session = tenant_sessions[tenant_id]
            session["total_packets"] += 1
            session["seen_sequences"].append(seq_id)
            received_packets += 1

            # --- WORKLOAD 2: Heavy CPU Coordinate Transform Simulation ---
            # Use NumPy matrix operations to consume CPU and mutate working registries
            # pose_vector = np.array(pose_data)
            # outer_product = np.outer(pose_vector, pose_vector)[:4, :4]
            # transformed_matrix = np.dot(outer_product, PROJECTION_MATRIX)
            # math_checksum = float(np.sum(transformed_matrix))

            # --- WORKLOAD 3: Pipeline Telemetry Assessment ---
            one_way_latency_ms = (recv_timestamp_ns - tx_timestamp_ns) / 1_000_000.0

            writer.writerow([seq_id, packet_time, one_way_latency_ms])

            if received_packets % 1000 == 0:
                print(f"Processed {received_packets} packets...")

        except Exception as e:
            # Crucial for capturing malformed or truncated payloads caught mid-migration frame cuts
            error_log = {
                "error": str(e),
                "timestamp_ns": recv_timestamp_ns,
                "raw_data_len": len(data)
            }
            print(f"[PACKET EXCEPTION] Processing error: {e}")
            log_file.write(json.dumps(error_log) + "\n")
