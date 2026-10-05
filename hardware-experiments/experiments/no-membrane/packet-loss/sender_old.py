#!/usr/bin/env python3
import json
import socket
import time
import sys
import statistics

import struct

# ==========================================
# EXPERIMENT CONFIGURATION
# ==========================================
SENSOR_PORT = 5005
SAT1_IP = "192.168.10.11"  # Replace with your actual sat1 IP
SAT2_IP = "192.168.10.12"  # Replace with your actual sat2 IP

# Input path to the raw, space-separated NASA CMAPSS text file
TXT_FILE_PATH = "data/train_FD001.txt"

# Target sequence ID where the handover process should be initiated
HANDOVER_TRIGGER_SEQ = 500

# Maximum number of packets to send before stopping
MAX_PACKETS = 1000

# Path to save the per-packet latency results
LATENCY_CSV_PATH = "latency_results.csv"
# ==========================================

# Active satellite target pointer (starts with sat1)
active_sat_ip = SAT1_IP

def create_tcp_socket(ip, port, max_retries=1):
    for i in range(max_retries):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        try:
            s.connect((ip, port))
            return s  # Safe return: socket remains open and active
        except Exception as e:
            s.close() # Clean up the failed socket handle immediately before retrying
            if max_retries > 1:
                print(f"[RETRY] Failed to connect to {ip}:{port} (Attempt {i+1}/{max_retries}): {e}")
                time.sleep(1)
            else:
                print(f"[ERROR] Failed to connect to {ip}:{port}: {e}")
    return None

def send_msg(sock, msg):
    # Prefix each message with a 4-byte length (network byte order)
    msg = struct.pack('>I', len(msg)) + msg
    sock.sendall(msg)

def recv_msg(sock):
    # Read message length and unpack it into an integer
    raw_msglen = recv_all(sock, 4)
    if not raw_msglen:
        return None
    msglen = struct.unpack('>I', raw_msglen)[0]
    # Read the message data
    return recv_all(sock, msglen)

def recv_all(sock, n):
    # Helper function to recv n bytes or return None if EOF is hit
    data = bytearray()
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            return None
        data.extend(packet)
    return data

# Initialize TCP connection
sock = create_tcp_socket(active_sat_ip, SENSOR_PORT)

if not sock:
    sys.exit(1)

print(f"=========================================================")
print(f" Starting Stateful CMAPSS Telemetry Stream (TCP)")
print(f" Reading directly from: {TXT_FILE_PATH}")
print(f" Initial Target Destination: sat1 ({active_sat_ip}:{SENSOR_PORT})")
print(f"=========================================================")

seq_id = 0
latencies = []

try:
    with open(TXT_FILE_PATH, "r") as f:
        for line in f:
            row = line.strip().split()
            if not row or len(row) < 26:
                continue

            loop_start = time.perf_counter()

            payload = {
                "seq_id": seq_id,
                "timestamp_ns": time.time_ns(),
                "unit_number": int(row[0]),
                "cycle": int(row[1]),
                "settings": [float(row[2]), float(row[3]), float(row[4])],
                "sensors": [float(val) for val in row[5:26]]
            }

            packet = json.dumps(payload).encode('utf-8')
            
            # Send and wait for ACK to track full RTT latency
            send_msg(sock, packet)
            ack = recv_msg(sock)
            
            if seq_id == HANDOVER_TRIGGER_SEQ:
                print(f"\n[Handover Event] Reached packet #{HANDOVER_TRIGGER_SEQ}. Initiating reliable handshake...")
                send_msg(sock, b"HANDOVER")
                response = recv_msg(sock)
                if response == b"sat2":
                    print(f"\n[Handover Routing] Received redirection ACK from sat1!")
                    print(f"                   Updating stream path -> sat2 ({SAT2_IP}:{SENSOR_PORT})")
                    sock.close()
                    active_sat_ip = SAT2_IP
                    # Use a higher retry count for the handover connection to allow for sat2 startup
                    sock = create_tcp_socket(active_sat_ip, SENSOR_PORT, max_retries=30)
                    if not sock:
                        print("[ERROR] Failed to connect to sat2 during handover after multiple retries.")
                        break

            if seq_id % 100 == 0:
                print(f"[PROGRESS] Sent {seq_id} packets...")

            iteration_latency = (time.perf_counter() - loop_start) * 1000
            latencies.append(iteration_latency)

            seq_id += 1

            elapsed = time.perf_counter() - loop_start
            remaining = 0.010 - elapsed
            if remaining > 0:
                time.sleep(remaining)

            if seq_id >= MAX_PACKETS:
                print(f"\n[INFO] Reached maximum packet limit ({MAX_PACKETS}). Stopping.")
                break

except FileNotFoundError:
    print(f"\n[ERROR] Could not find the file '{TXT_FILE_PATH}'.")
    print("Please make sure the script is executed inside the same directory as the dataset.")
    sys.exit(1)
except KeyboardInterrupt:
    print("\n[INFO] Streaming stopped manually by user via KeyboardInterrupt.")
except Exception as e:
    print(f"\n[ERROR] {e}")
finally:
    if sock:
        sock.close()

print(f"=========================================================")
print(f" [SUCCESS] Stream finished executing.")
print(f" Sent a total of {seq_id} telemetry packets.")

if latencies:
    min_lat = min(latencies)
    max_lat = max(latencies)
    avg_lat = statistics.mean(latencies)
    std_dev_lat = statistics.stdev(latencies) if len(latencies) > 1 else 0.0

    print(f"\n--- Telemetry Latency Statistics (ms) ---")
    print(f" Min Latency: {min_lat:.4f} ms")
    print(f" Max Latency: {max_lat:.4f} ms")
    print(f" Avg Latency: {avg_lat:.4f} ms")
    print(f" Std Dev:     {std_dev_lat:.4f} ms")

    # Write per-packet latencies to CSV
    try:
        import csv
        with open(LATENCY_CSV_PATH, "w", newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["seq_id", "latency_ms"])
            for i, lat in enumerate(latencies):
                writer.writerow([i, lat])
        print(f"\n[SUCCESS] Per-packet latency data saved to {LATENCY_CSV_PATH}")
    except Exception as e:
        print(f"\n[ERROR] Failed to write latency CSV: {e}")
print(f"=========================================================")
