import socket
import time

TARGET_IP = "127.0.0.1"
TARGET_PORT = 5000
INTERVAL_SEC = 0.1  # 100 ms

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sequence_num = 1

    print(f"[Sender] Streaming UDP packets to {TARGET_IP}:{TARGET_PORT} every 100 ms...")
    print("[Sender] Press Ctrl+C to stop.\n")

    try:
        while True:
            timestamp = time.strftime("%H:%M:%S")
            # Format message with incremental sequence number
            message = f"Seq={sequence_num:05d} | Time={timestamp}\n"

            sock.sendto(message.encode('utf-8'), (TARGET_IP, TARGET_PORT))
            print(f"[Sent {timestamp}] {message.strip()}")

            sequence_num += 1
            time.sleep(INTERVAL_SEC)

    except KeyboardInterrupt:
        print("\n[Sender] Stopped.")
    finally:
        sock.close()

if __name__ == "__main__":
    main()
