import socket
import sys

# --- CONFIGURATION ---
PORT = 8080
BIND_ADDR = "0.0.0.0"

def start_receiver():
    """
    Simple TCP receiver that listens for incoming connections.
    Used by simulation to measure RTT.
    """
    try:
        # Create a TCP/IP socket
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        # Allow immediate reuse of the port after the script stops
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # Bind the socket to the address and port
        server_sock.bind((BIND_ADDR, PORT))
        
        # Listen for incoming connections
        server_sock.listen(5)
        
        print(f"[*] Latency Receiver listening on {BIND_ADDR}:{PORT}")
        print("[*] Press Ctrl+C to stop.")

        while True:
            try:
                # Accept a new connection
                client_sock, addr = server_sock.accept()
                
                # In simulation, sample_rtt just opens and closes the connection.
                # We can print a debug message or just close it immediately.
                # To be more robust (like the guidelines' mock_receiver), we could handle 
                # payload reading if needed, but for RTT sampling, simple acceptance is enough.
                
                with client_sock:
                    # Connection established - this satisfies simulation's sample_rtt
                    pass
                
            except Exception as e:
                print(f"[!] Error handling connection: {e}")

    except KeyboardInterrupt:
        print("\n[*] Receiver stopping...")
    except Exception as e:
        print(f"[!] Fatal error: {e}")
    finally:
        server_sock.close()
        print("[*] Socket closed.")

if __name__ == "__main__":
    start_receiver()
