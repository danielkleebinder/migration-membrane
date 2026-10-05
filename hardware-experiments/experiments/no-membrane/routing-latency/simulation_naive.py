import time
import math
import subprocess
import csv
import socket
import os

# --- CONFIGURATION ---
IFACE = "eth0"  # Change to "end0" if required by your OS build
SAT1_IP = "192.168.10.11"
SAT2_IP = "192.168.10.12"
SAT3_IP = "192.168.10.13"
TARGET_PORT = 8080
CSV_FILENAME = "results_routing_latency.csv"

# Orbital simulation properties
EARTH_RADIUS_KM = 6378.135
ALTITUDE_KM = 550.0
C_KM_S = 299792.458  # Speed of light
ISL_HOP_DELAY_MS = 12.0  # Constant processing + propagation delay per ISL hop

# RTT Configuration (ms)
MIN_RTT = 15  # RTT at 90 degrees (zenith)
MAX_RTT = 20  # RTT at 25 degrees (horizon)

# Jitter Configuration (ms)
MIN_JITTER = 1   # Jitter at 90 degrees (zenith)
MAX_JITTER = 4   # Jitter at 25 degrees (horizon)

# Packet Loss Configuration (%)
MIN_LOSS = 0.2     # Loss at 90 degrees (zenith)
MAX_LOSS = 0.5     # Loss at 25 degrees (horizon)

TOTAL_DURATION = 300
# We now have two handovers, splitting the duration into three parts
HANDOVER_1_SECOND = math.floor(TOTAL_DURATION / 3)
HANDOVER_2_SECOND = math.floor(2 * TOTAL_DURATION / 3)

SPEEDUP_FACTOR = 8
SAMPLES_PER_SECOND = 5

def force_clean_interface():
    """Completely resets traffic control rules on the interface."""
    subprocess.run(["sudo", "tc", "qdisc", "del", "dev", IFACE, "root"], stderr=subprocess.DEVNULL)
    print(f"Interface {IFACE} cleared.")

def init_tc():
    """Initializes the classful queuing disciplines for path separation."""
    subprocess.run(["sudo", "tc", "qdisc", "add", "dev", IFACE, "root", "handle", "1:", "prio"])
    subprocess.run(["sudo", "tc", "qdisc", "add", "dev", IFACE, "parent", "1:1", "handle", "10:", "netem"])
    subprocess.run(["sudo", "tc", "qdisc", "add", "dev", IFACE, "parent", "1:2", "handle", "20:", "netem"])
    subprocess.run(["sudo", "tc", "qdisc", "add", "dev", IFACE, "parent", "1:3", "handle", "30:", "netem"])
    subprocess.run(["sudo", "tc", "filter", "add", "dev", IFACE, "parent", "1:0", "u32", "match", "ip", "dst", SAT1_IP, "flowid", "1:1"])
    subprocess.run(["sudo", "tc", "filter", "add", "dev", IFACE, "parent", "1:0", "u32", "match", "ip", "dst", SAT2_IP, "flowid", "1:2"])
    subprocess.run(["sudo", "tc", "filter", "add", "dev", IFACE, "parent", "1:0", "u32", "match", "ip", "dst", SAT3_IP, "flowid", "1:3"])
    print("Classful traffic pipes initialized.")

def get_link_dynamics(angle_deg):
    """Computes non-linear atmospheric RTT, jitter, and packet loss."""
    rad = math.radians(angle_deg)
    sin_theta = math.sin(rad)
    sin_25 = math.sin(math.radians(25.0))

    # 1. Calculate RTT (A + B / sin(theta))
    # RTT(90) = A + B = MIN_RTT
    # RTT(25) = A + B / sin(25) = MAX_RTT
    b_rtt = (MAX_RTT - MIN_RTT) / ((1.0 / sin_25) - 1.0)
    a_rtt = MIN_RTT - b_rtt
    rtt = a_rtt + (b_rtt / sin_theta)

    # 2. Calculate Jitter (Linear mapping from sin(theta))
    # Jitter(90) = MIN_JITTER
    # Jitter(25) = MAX_JITTER
    # Formula: Jitter = C + D * sin(theta)
    d_jit = (MAX_JITTER - MIN_JITTER) / (sin_25 - 1.0)
    c_jit = MIN_JITTER - d_jit
    jitter = c_jit + d_jit * sin_theta

    # 3. Calculate Loss (Linear mapping from sin(theta))
    # Loss(90) = MIN_LOSS
    # Loss(25) = MAX_LOSS
    # Formula: Loss = E + F * sin(theta)
    f_loss = (MAX_LOSS - MIN_LOSS) / (sin_25 - 1.0)
    e_loss = MIN_LOSS - f_loss
    loss = e_loss + f_loss * sin_theta

    return rtt, jitter, loss

def apply_ground_channel(class_id, rtt, jitter, loss):
    """Updates the network pipe parameters in the kernel using replace."""
    subprocess.run([
        "sudo", "tc", "qdisc", "replace", "dev", IFACE, "parent", f"1:{class_id}",
        "netem", "delay", f"{rtt:.2f}ms", f"{jitter:.2f}ms", "distribution", "paretonormal", "loss", f"{loss:.2f}%"
    ])

def sample_rtt(target_ip):
    """Executes a single TCP connection attempt to sample network latency."""
    t0 = time.time()
    try:
        sock = socket.create_connection((target_ip, TARGET_PORT), timeout=0.4)
        sock.close()
        return (time.time() - t0) * 1000
    except Exception as e:
        # print(f"Connection failed to {target_ip}:{TARGET_PORT} - {e}")
        return None

# --- ASYNCHRONOUS EXECUTION LOOP ---
from concurrent.futures import ThreadPoolExecutor

force_clean_interface()
init_tc()
results_log = []

REAL_SAMPLE_INTERVAL = 1.0 / (SAMPLES_PER_SECOND * SPEEDUP_FACTOR)
real_duration_target = TOTAL_DURATION / SPEEDUP_FACTOR

print(f"Start simulation (Speedup {SPEEDUP_FACTOR}x).")

# Initialize a ThreadPool to handle measurements without blocking the main clock
executor = ThreadPoolExecutor(max_workers=20)
futures = []

start_time = time.time()
last_tc_update_logical_t = -1
active_target = SAT1_IP
current_sat_index = 1

while True:
    real_elapsed = time.time() - start_time
    if real_elapsed >= real_duration_target:
        break

    t_logical = real_elapsed * SPEEDUP_FACTOR
    t_logical_int = int(t_logical)

    if t_logical_int > TOTAL_DURATION:
        break

    # Dynamic Network Parameter Updates (Remains synchronous)
    if t_logical_int != last_tc_update_logical_t:
        if t_logical_int <= HANDOVER_1_SECOND:
            angle_sat1 = 25.0 + 130 * (t_logical / HANDOVER_1_SECOND)
            rtt1, jit1, loss1 = get_link_dynamics(angle_sat1)
            apply_ground_channel(1, rtt1, jit1, loss1)
            active_target = SAT1_IP
            current_sat_index = 1
        elif t_logical_int <= HANDOVER_2_SECOND:
            segment_duration = HANDOVER_2_SECOND - HANDOVER_1_SECOND
            angle_sat2 = 25.0 + 130 * ((t_logical - HANDOVER_1_SECOND) / segment_duration)
            rtt2, jit2, loss2 = get_link_dynamics(angle_sat2)
            apply_ground_channel(2, rtt2, jit2, loss2)
            active_target = SAT2_IP
            current_sat_index = 2
        else:
            segment_duration = TOTAL_DURATION - HANDOVER_2_SECOND
            angle_sat3 = 25.0 + 130 * ((t_logical - HANDOVER_2_SECOND) / segment_duration)
            rtt3, jit3, loss3 = get_link_dynamics(angle_sat3)
            apply_ground_channel(3, rtt3, jit3, loss3)
            active_target = SAT3_IP
            current_sat_index = 3

        last_tc_update_logical_t = t_logical_int

    # Calculate exact execution boundaries
    next_sample_trigger_real = start_time + (len(futures) * REAL_SAMPLE_INTERVAL)

    # Offload the latency check to the background thread pool
    future = executor.submit(sample_rtt, active_target)
    futures.append((t_logical_int, current_sat_index, future))

    # Strict clock synchronization
    sleep_time = next_sample_trigger_real - time.time()
    if sleep_time > 0:
        time.sleep(sleep_time)

print("\nFlight simulation complete. Collecting data...")
executor.shutdown(wait=True)

# Process background results
for t_log, sat_idx, fut in futures:
    measured_rtt = fut.result() # Safe to read now since executor has joined

    results_log.append({
        "timestamp_s": t_log,
        "measured_rtt_sat1_ms": f"{measured_rtt:.4f}" if (sat_idx == 1 and measured_rtt is not None) else "NaN",
        "measured_rtt_sat2_ms": f"{measured_rtt:.4f}" if (sat_idx == 2 and measured_rtt is not None) else "NaN",
        "measured_rtt_sat3_ms": f"{measured_rtt:.4f}" if (sat_idx == 3 and measured_rtt is not None) else "NaN"
    })

# Reset interface to standard settings
force_clean_interface()

# Write clean dataset to disk
with open(CSV_FILENAME, 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=["timestamp_s", "measured_rtt_sat1_ms", "measured_rtt_sat2_ms", "measured_rtt_sat3_ms"])
    writer.writeheader()
    writer.writerows(results_log)

print(f"Simulation complete. Save results to: {CSV_FILENAME}")
