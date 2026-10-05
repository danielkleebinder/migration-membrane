from .orchestrator import Orchestrator

class NoopOrchestrator(Orchestrator):
    def __init__(self, node_ips, sensor_ip, iface="eth0"):
        """
        :param node_ips: dict mapping Satellite ID to its IP address (e.g., {"sat1": "192.168.1.10"})
        :param sensor_ip: IP address of the ground sensor Raspberry Pi
        :param iface: The network interface on the Pis (usually eth0 or wlan0)
        """
        self.node_ips = node_ips
        self.sensor_ip = sensor_ip
        self.iface = iface
        self.active_sat = None

        # Stateful tracking: Application starts on the first satellite in the list
        self.active_index = 0
    # ------------------------------------------
    # Setup: Initialize TC Queues (Supports N Satellites)
    # ------------------------------------------
    def setup(self):
        print(f"[Orchestrator] Running Testbed Setup for {len(self.node_ips)} nodes...")
        all_ips = list(self.node_ips) + [self.sensor_ip]

        for ip in all_ips:
            print(f"  Setting up node {ip}...")

        # Apply Filters: Any traffic to ANOTHER satellite goes to 1:1 (ISL), traffic to sensor goes to 1:2 (Ground)
        for sat_ip in self.node_ips:
            for other_ip in self.node_ips:
                if sat_ip != other_ip:
                    print(f"  Add filters between satellites {sat_ip} and {other_ip}...")

        # Sensor Filters: Route all satellite IPs to the Ground queue (1:2)
        for sat_ip in self.node_ips:
            print(f"  Add filter for ground station {self.sensor_ip} to {sat_ip}...")

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

        # Calculate ISL Delay
        to_sat_pos = to_sat.node.getPos(to_sat.earth.getTop())
        isl_metrics = from_sat.get_distance_metrics(to_sat_pos)
        one_way_delay = max(0.1, isl_metrics['rtt_ms'] / 2.0)

        print(f"[Orchestrator] TRIGGER MIGRATION: {from_sat.id} ({from_ip}) -> {to_sat.id} ({to_ip}) | ISL Delay: {one_way_delay:.2f}ms")

        # Update active pointer to the new node
        self.active_index = next_index
        return to_sat

    # ------------------------------------------
    # Update: Track Active Sensor Delay
    # ------------------------------------------
    def update(self, active_sat, ground_pos):
        self.active_sat = active_sat
        active_ip = self.node_ips[self.active_index]

        # Calculate Ground Delay for the currently active satellite
        ground_metrics = active_sat.get_distance_metrics(ground_pos)
        one_way_delay = max(0.1, ground_metrics['rtt_ms'] / 2.0)
        elevation_deg = ground_metrics['elevation_deg']
        distance_km = ground_metrics['dist_km']

        # -------------------------------------------------------------
        # HARDCODED LINK MODEL
        # -------------------------------------------------------------
        # jitter = 1
        # loss = 1
        # -------------------------------------------------------------


        # -------------------------------------------------------------
        # DYNAMIC LINK MODEL (Atmospheric & Elevation Scintillation)
        # -------------------------------------------------------------
        # Clamp elevation between min cutoff (25°) and zenith (90°)
        elev_clamped = max(25.0, min(90.0, elevation_deg))

        # Normalized degradation factor: 0.0 at zenith (90°), 1.0 at horizon (25°)
        deg_factor = ((90.0 - elev_clamped) / 65.0) ** 2

        # Jitter scales from 0.2 ms (overhead) to 2.5 ms (low horizon)
        jitter = 0.2 + (2.3 * deg_factor)

        # Loss scales from 0.05% (overhead) to 3.0% (low horizon)
        loss = 0.05 + (2.95 * deg_factor)
        # -------------------------------------------------------------

        print(
            f"[Orchestrator] Update ground ({self.sensor_ip}) to satellite ({active_ip}) "
            f"link | Elev: {elevation_deg:.1f}° | Delay: {one_way_delay:.2f}ms | Jitter: {jitter:.2f}ms | Loss: {loss:.2f}%"
        )
