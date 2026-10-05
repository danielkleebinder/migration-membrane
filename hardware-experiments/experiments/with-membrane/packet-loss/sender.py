import socket
import time
import re
import csv
import threading
from datetime import datetime

TARGET_IPS = [
    "192.168.10.11",
    "192.168.10.12"
]
TARGET_PORT = 5000
CSV_TRACE_FILE = "50mbps_su_dcf_full.csv"
OUTPUT_CSV_FILE = "results.csv"


def extract_seq(ack_payload: str) -> int:
    """Extracts integer sequence number from payload like 'ACK:Seq=00714|...'"""
    match = re.search(r'Seq=(\d+)', ack_payload)
    return int(match.group(1)) if match else None


def load_vr_trace(filename):
    """Reads the CSV trace and extracts sequence number, relative time, and packet length."""
    packets = []
    try:
        with open(filename, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    seq = int(row['No.'])
                    t = float(row['Time'])
                    info = row.get('Info', '')
                    len_match = re.search(r'Len=(\d+)', info)
                    packet_len = int(len_match.group(1)) if len_match else int(row.get('Length', 100))
                    packets.append((t, seq, packet_len))
                except (ValueError, KeyError):
                    continue
    except FileNotFoundError:
        print(f"[Error] Could not find trace file: {filename}")
    return packets


def receiver_worker(sock, packet_records, stop_event):
    """Background thread strictly dedicated to catching and timestamping ACKs."""
    while not stop_event.is_set():
        try:
            data, addr = sock.recvfrom(2048)
            ack_perf_time = time.perf_counter()
            ack_str = data.decode('utf-8', errors='ignore').strip()

            seq = extract_seq(ack_str)
            if seq is not None and seq in packet_records:
                # CRITICAL FIX: Only record the FIRST arriving ACK to prevent overwrites
                if packet_records[seq]['Latency'] == '':
                    send_perf_time = packet_records[seq]['_perf_time']
                    true_rtt_ms = (ack_perf_time - send_perf_time) * 1000

                    packet_records[seq]['Address'] = addr[0]
                    packet_records[seq]['Latency'] = round(true_rtt_ms, 4)
        except socket.timeout:
            # Expected behavior periodically so the loop can check stop_event
            continue
        except (BlockingIOError, ConnectionRefusedError):
            pass


def main():
    print(f"[Sender] Loading VR traffic trace from '{CSV_TRACE_FILE}'...")
    trace_packets = load_vr_trace(CSV_TRACE_FILE)

    if not trace_packets:
        print("[Error] No packets loaded.")
        return

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Using a standard timeout simplifies the receiver thread (no select needed)
    sock.settimeout(0.1)

    packet_records = {}
    total_packets = len(trace_packets)

    # 1. Start Receiver Thread
    stop_event = threading.Event()
    rx_thread = threading.Thread(target=receiver_worker, args=(sock, packet_records, stop_event), daemon=True)
    rx_thread.start()

    print(f"[Sender] Successfully loaded {total_packets} packets. Starting high-precision replay...\n")

    # 2. Main Thread: Sending Loop
    start_perf_time = time.perf_counter()
    packet_index = 0

    try:
        while packet_index < total_packets:
            now = time.perf_counter()
            target_time, seq_num, packet_len = trace_packets[packet_index]

            if (now - start_perf_time) >= target_time:
                # Format string outside the absolute critical timestamping path
                base_msg = f"Seq={seq_num:05d}|Time={target_time}|"
                padding_len = max(0, packet_len - len(base_msg))
                message = (base_msg + "#" * padding_len).encode('utf-8')

                # Lock in the performance counter right before hardware dispatch
                dispatch_time = time.perf_counter()

                packet_records[seq_num] = {
                    'Sequence': seq_num,
                    'Time': target_time,
                    'Latency': '',
                    'Address': '',
                    '_perf_time': dispatch_time
                }

                for ip in TARGET_IPS:
                    sock.sendto(message, (ip, TARGET_PORT))

                packet_index += 1
            else:
                # Yield to prevent 100% CPU lockup while waiting for the next packet time
                time.sleep(0.0001)

        print("\n[Sender] Replay finished. Waiting 1 second for final ACKs to arrive...")
        time.sleep(1.0)  # Passive wait replaces the complex manual drain loop

    except KeyboardInterrupt:
        print("\n[Sender] Benchmark stopped by user.")

    finally:
        # 3. Clean up threads and export
        stop_event.set()
        rx_thread.join(timeout=1.0)
        sock.close()

        if packet_records:
            print(f"[Sender] Writing metrics for {len(packet_records)} packets to '{OUTPUT_CSV_FILE}'...")
            try:
                with open(OUTPUT_CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
                    fieldnames = ['Sequence', 'Time', 'Latency', 'Address']
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    for seq_num in sorted(packet_records.keys()):
                        row_data = {k: v for k, v in packet_records[seq_num].items() if k in fieldnames}
                        writer.writerow(row_data)
                print(f"[Sender] Successfully exported results to {OUTPUT_CSV_FILE}")
            except Exception as e:
                print(f"[Error] Failed to write CSV output: {e}")


if __name__ == "__main__":
    main()
