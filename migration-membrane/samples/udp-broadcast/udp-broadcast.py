import socket
import time
import select
import re

TARGET_IPS = [
    "192.168.10.11",
    "192.168.10.12",
    "192.168.10.13"
]
TARGET_PORT = 5000
INTERVAL_SEC = 0.002  # 2 ms (matches your last log)

def extract_seq(ack_payload: str) -> int:
    """Extracts integer sequence number from payload like 'ACK:Seq=00714|...'"""
    match = re.search(r'Seq=(\d+)', ack_payload)
    return int(match.group(1)) if match else None

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Set to non-blocking so select() handles all the waiting precisely
    sock.setblocking(False)

    sequence_num = 1
    sent_timestamps = {}

    print(f"[Sender] High-Precision Benchmark active (Interval: {INTERVAL_SEC * 1000} ms)...\n")
    print(f"[Sender] Duplicate ACKs will be silently dropped.\n")

    try:
        # perf_counter is immune to system clock updates and has nanosecond precision
        next_send_time = time.perf_counter()

        while True:
            now = time.perf_counter()

            # 1. SEND PHASE: If it's time to send, fire the packet.
            if now >= next_send_time:
                timestamp_str = time.strftime("%H:%M:%S")
                message = f"Seq={sequence_num:05d}|Time={timestamp_str}\n".encode('utf-8')

                sent_timestamps[sequence_num] = now

                for ip in TARGET_IPS:
                    sock.sendto(message, (ip, TARGET_PORT))

                sequence_num += 1
                next_send_time += INTERVAL_SEC

            # 2. RECEIVE PHASE: Wait for ACKs precisely until the NEXT send deadline
            time_until_next = next_send_time - time.perf_counter()

            if time_until_next > 0:
                # select() blocks efficiently at the OS level until data arrives OR the deadline hits
                ready = select.select([sock], [], [], time_until_next)

                if ready[0]:
                    try:
                        # Process all readable packets in a quick loop
                        while True:
                            data, addr = sock.recvfrom(1024)
                            ack_time = time.perf_counter()
                            ack_str = data.decode('utf-8', errors='ignore').strip()

                            seq = extract_seq(ack_str)
                            if seq:
                                # Use pop() to retrieve AND remove the timestamp in one O(1) operation
                                if seq in sent_timestamps:
                                    send_time = sent_timestamps.pop(seq)
                                    true_rtt_ms = (ack_time - send_time) * 1000
                                    print(f"└─ [ACK] From {addr[0]:<15} | True RTT for Seq #{seq:05d}: {true_rtt_ms:.2f} ms")
                                else:
                                    # This sequence was already answered (e.g., Sat2 buffer drain). Silently drop it.
                                    pass
                            else:
                                print(f"└─ [ACK] From {addr[0]:<15} | Unrecognized Payload: {ack_str}")

                    except BlockingIOError:
                        # No more packets to read in the OS buffer right now
                        pass
                    except ConnectionRefusedError:
                        # Ignores ICMP Port Unreachable errors during the downtime window
                        pass

            # 3. FAST CLEANUP: Prevent memory leaks from lost packets
            if len(sent_timestamps) > 1000:
                oldest_keys = sorted(sent_timestamps.keys())[:-500]
                for k in oldest_keys:
                    del sent_timestamps[k]

    except KeyboardInterrupt:
        print("\n[Sender] Benchmark stopped.")
    finally:
        sock.close()

if __name__ == "__main__":
    main()
