import math
import subprocess
import threading

from .orchestrator import Orchestrator


class ExperimentOrchestrator(Orchestrator):
    def __init__(self, node_ips, sensor_ip, iface="eth0"):
        """
        :param node_ips: dict mapping Satellite ID to its IP address (e.g., {"sat1": "192.168.1.10"})
        :param sensor_ip: IP address of the ground sensor Raspberry Pi
        :param iface: The network interface on the Pis
        """
        self.node_ips = node_ips
        self.sensor_ip = sensor_ip
        self.iface = iface
        self.active_sat = None

        # Stateful tracking: Application starts on the first satellite in the list
        self.active_index = 0
        self.migration_count = 0

    # ------------------------------------------
    # Helper: SSH Command Runner (Synchronous)
    # ------------------------------------------
    def _run_ssh(self, ip, cmd, ignore_errors=False):
        """Blocking SSH call - used for setup."""
        target = f"root@{ip}"
        full_cmd = ["ssh", "-o", "StrictHostKeyChecking=no", target, cmd]
        try:
            result = subprocess.run(full_cmd, capture_output=True, text=True, check=not ignore_errors)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            if not ignore_errors:
                print(f"[ERROR] SSH command failed on {ip}: {cmd}\n{e.stderr}")
            return None

    # ------------------------------------------
    # Helper: SSH Command Runner (Asynchronous)
    # ------------------------------------------
    def _run_ssh_async(self, ip, cmd, ignore_errors=False):
        """Non-blocking SSH call - used during the active simulation loop."""
        thread = threading.Thread(
            target=self._run_ssh,
            args=(ip, cmd, ignore_errors),
            daemon=True
        )
        thread.start()

    # ------------------------------------------
    # Setup: Initialize TC Queues (Supports N Satellites)
    # ------------------------------------------
    def setup(self):
        print(f"[Orchestrator] Running Testbed Setup for {len(self.node_ips)} nodes...")
        all_ips = list(self.node_ips) + [self.sensor_ip]

        # Use the synchronous _run_ssh here so setup strictly finishes BEFORE simulation starts
        for ip in all_ips:
            self._run_ssh(ip, f"sudo tc qdisc del dev {self.iface} root", ignore_errors=True)
            self._run_ssh(ip, f"sudo tc qdisc add dev {self.iface} root handle 1: htb default 1")

            # Class 1:1 for ISL, Class 1:2 for Ground
            self._run_ssh(ip, f"sudo tc class add dev {self.iface} parent 1: classid 1:1 htb rate 10gbit")
            self._run_ssh(ip, f"sudo tc qdisc add dev {self.iface} parent 1:1 handle 10: netem delay 3.5ms 0.1ms distribution normal loss 0.01%")
            self._run_ssh(ip, f"sudo tc class add dev {self.iface} parent 1: classid 1:2 htb rate 10gbit")
            self._run_ssh(ip, f"sudo tc qdisc add dev {self.iface} parent 1:2 handle 20: netem delay 6ms 1ms distribution normal loss 1%")

        # Apply Filters: Any traffic to ANOTHER satellite goes to 1:1 (ISL), traffic to sensor goes to 1:2 (Ground)
        for sat_ip in self.node_ips:
            for other_ip in self.node_ips:
                if sat_ip != other_ip:
                    self._run_ssh(sat_ip, f"sudo tc filter add dev {self.iface} protocol ip parent 1:0 prio 1 u32 match ip dst {other_ip} flowid 1:1")

            # Route sensor traffic
            self._run_ssh(sat_ip, f"sudo tc filter add dev {self.iface} protocol ip parent 1:0 prio 1 u32 match ip dst {self.sensor_ip} flowid 1:2")

        # Sensor Filters: Route all satellite IPs to the Ground queue (1:2)
        for sat_ip in self.node_ips:
            self._run_ssh(self.sensor_ip, f"sudo tc filter add dev {self.iface} protocol ip parent 1:0 prio 1 u32 match ip dst {sat_ip} flowid 1:2")

        print("[Orchestrator] Setup Complete.")

    # ------------------------------------------
    # Migrate: Auto-advance to Next Node
    # ------------------------------------------
    def migrate(self, from_sat, to_sat):
        self.active_sat = to_sat

        # Calculate next index with wrap-around (Ping-Pong or Ring)
        from_ip = self.node_ips[self.active_index]
        next_index = (self.active_index + 1) % len(self.node_ips)
        to_ip = self.node_ips[next_index]

        # SCP back the log file from the target satellite before migration is triggered
        self.migration_count += 1
        remote_log_path = "/home/pi/iot-2026/experiments/with-membrane/macro/iwasm.log"
        local_log_path = f"logs/mig{self.migration_count}_iwasm.log"
        scp_cmd = ["scp", "-o", "StrictHostKeyChecking=no", f"root@{to_ip}:{remote_log_path}", local_log_path]
        
        print(f"[Orchestrator] Copying log from {to_ip} (if exists) to {local_log_path}...")
        # We use subprocess.run directly and ignore errors if the file doesn't exist
        subprocess.run(scp_cmd, capture_output=True, text=True, check=False)

        # Calculate ISL Delay
        to_sat_pos = to_sat.node.getPos(to_sat.earth.getTop())
        isl_metrics = from_sat.get_distance_metrics(to_sat_pos)
        one_way_delay = max(0.1, isl_metrics['rtt_ms'] / 2.0)

        # Calculate other link properties
        jitter = 0.1
        loss = 0.01

        print(f"\n[Orchestrator] TRIGGER MIGRATION: {from_sat.id} ({from_ip}) -> {to_sat.id} ({to_ip}) | ISL Delay: {one_way_delay:.2f}ms")

        # Update ISL TC queues ASYNCHRONOUSLY
        self._run_ssh_async(from_ip, f"sudo tc qdisc change dev {self.iface} parent 1:1 handle 10: netem delay {one_way_delay:.2f}ms {jitter:.2f}ms distribution normal loss {loss:.2f}%")
        self._run_ssh_async(to_ip, f"sudo tc qdisc change dev {self.iface} parent 1:1 handle 10: netem delay {one_way_delay:.2f}ms {jitter:.2f}ms distribution normal loss {loss:.2f}%")

        # Trigger Migration Script ASYNCHRONOUSLY (prevents Ansible startup from freezing the loop)
        migration_cmd = (
            "cd /home/pi/iot-2026/experiments/with-membrane/macro && "
            f"stdbuf -oL ./iwasm-arm64 --addr-pool=0.0.0.0/0 --migrate={from_ip}:8010 "
            "--migration-server=8010 benchmark.wasm > iwasm.log 2>&1"
        )
        self._run_ssh_async(to_ip, migration_cmd)

        # Somehow Ansible can only migrate from sat1 to sat2 but not the other way around
        # ansible_cmd = ["ansible-playbook", "-i", "experiment-orchestrator-hosts.ini", "experiment-orchestrator-migrate.yml", "-e", f"source={from_ip} target={to_ip}"]
        # threading.Thread(target=subprocess.run, args=(ansible_cmd,), kwargs={"check": False}, daemon=True).start()

        # Update active pointer to the new node
        self.active_index = next_index
        return to_sat

    # ------------------------------------------
    # Update: Track Active Sensor Delay
    # ------------------------------------------
    def update(self, active_sat, ground_pos):
        self.active_sat = active_sat
        active_ip = self.node_ips[self.active_index]

        # Calculate Ground Delay (The strict physical speed-of-light floor)
        ground_metrics = active_sat.get_distance_metrics(ground_pos)
        physical_min_delay = max(0.1, ground_metrics['rtt_ms'] / 2.0)
        elevation_deg = ground_metrics['elevation_deg']
        distance_km = ground_metrics['dist_km']

        # -------------------------------------------------------------
        # DYNAMIC LINK MODEL (Atmospheric & Elevation Scintillation)
        # -------------------------------------------------------------
        elev_clamped = max(25.0, min(90.0, elevation_deg))
        deg_factor = ((90.0 - elev_clamped) / 65.0) ** 2

        # Jitter scales from 0.2 ms (overhead) to 2.5 ms (low horizon)
        jitter = 0.2 + (2.3 * deg_factor)

        # Loss scales from 0.05% (overhead) to 3.0% (low horizon)
        loss = 0.05 + (2.95 * deg_factor)

        # THE FIX:
        # 1. Add a realistic, constant MAC/queuing overhead instead of a massive 2x jitter shift.
        mac_overhead_ms = 0.5
        tc_mean_delay = physical_min_delay + mac_overhead_ms
        # -------------------------------------------------------------

        print(
            f"[Orchestrator] Update ground ({self.sensor_ip}) to satellite ({active_ip}) "
            f"link | Elev: {elevation_deg:.1f}° | Min Floor: {physical_min_delay:.2f}ms | Mean: {tc_mean_delay:.2f}ms | Jitter: {jitter:.2f}ms | Loss: {loss:.2f}%"
        )

        # 2. Use 'paretonormal' distribution to naturally skew the delay tail to the right
        self._run_ssh_async(
            active_ip,
            f"sudo tc qdisc change dev {self.iface} parent 1:2 handle 20: netem delay {tc_mean_delay:.2f}ms {jitter:.2f}ms distribution paretonormal loss {loss:.2f}%"
        )
        self._run_ssh_async(
            self.sensor_ip,
            f"sudo tc qdisc change dev {self.iface} parent 1:2 handle 20: netem delay {tc_mean_delay:.2f}ms {jitter:.2f}ms distribution paretonormal loss {loss:.2f}%"
        )
