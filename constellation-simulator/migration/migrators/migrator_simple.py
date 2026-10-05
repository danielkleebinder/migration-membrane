import math

from migration.orchestration import orchestrator
from migration.orchestration.orchestrator import Orchestrator
from migration.satellite import Satellite


class MigratorSimple:
    def __init__(
            self,
            orchestrator: Orchestrator = None,
            slo_rtt_ms = 10,
            safety_margin = 0.9,
            min_elevation_deg = 40.0
    ):
        self.orchestrator = orchestrator
        self.slo_rtt_ms = slo_rtt_ms
        self.safety_margin = safety_margin
        self.min_elevation_deg = min_elevation_deg
        self.active_idx = None
        self.prev_distances = {} # satellite_id -> distance

    def update(self, satellites, earth_node, point_lat, point_lon, current_time):
        # 1. Calculate ground station position in World coordinates
        # The point is reparented to Earth, so its world position changes as Earth rotates.
        # However, for simplicity and to match the old logic, we can get the point's world position.
        
        # In Panda3D, we can get the world position of the point if we had a reference to it.
        # But here 'satellites' are expected to be a list of NodePaths.
        # We also need the point's position.
        
        # Let's assume the caller provides the ground station world position or we calculate it.
        # The issue says "The heuristic from live_migration_old/main.py should be used".
        
        # In live_migration_old/main.py:
        # distances_km = np.sqrt((sat_x - gs_x) ** 2 + (sat_y - gs_y) ** 2 + (sat_z - gs_z) ** 2)
        # is_satellite_in_slo_range = distances_km <= slo_radius_km
        # approach_deltas = prev_distances_km - distances_km
        # is_satellite_approaching = approach_deltas > 0
        # candidates_mask = (is_satellite_visible_mask & is_satellite_in_slo_range & is_satellite_approaching)
        # active_idx = np.argmax(candidate_approach_speeds)
        
        # We need:
        # - Ground station world position
        # - Satellites world positions
        # - Speed of light to calculate SLO radius in km

        c_km_ms = 299.792458
        slo_radius_km = (self.slo_rtt_ms * c_km_ms) / 2.0
        slo_radius_km_handover = slo_radius_km * self.safety_margin
        slo_rtt_ms_handover = self.slo_rtt_ms * self.safety_margin

        # Find the point node (it was reparented to earth)
        # We might need to pass the point_node explicitly or find it.
        # For now, let's assume we can get it from earth_node.
        point_node = earth_node.find("**/red_point") 
        if not point_node:
            return None
            
        gs_pos = point_node.getPos(earth_node.getTop()) # Get world position
        
        candidates = []
        current_distances = {}
        
        for i, sat in enumerate(satellites):
            sat_pos = sat.getPos(earth_node.getTop())
            dist_vec = sat_pos - gs_pos
            dist_km = dist_vec.length() * (6371.0 / 10.0) # Scaling back to km. Earth radius is 10 in sim, 6371 in reality.
            
            current_distances[i] = dist_km
            
            # Check SLO
            if dist_km > slo_radius_km_handover:
                continue
            
            # Check elevation (approximate)
            # Normal at ground station (pointing away from Earth center)
            # Since Earth is at (0,0,0) in world if base is at (0,0,0)
            # Actually Earth is at self.base.
            earth_world_pos = earth_node.getPos(earth_node.getTop())
            up_vec = gs_pos - earth_world_pos
            up_vec.normalize()
            
            sat_vec = sat_pos - gs_pos
            sat_vec.normalize()
            
            cos_theta = up_vec.dot(sat_vec)
            elevation_rad = math.asin(max(-1.0, min(1.0, cos_theta))) # This is actually angle from horizon if up_vec was normal and we used dot product? 
            # Wait, dot product of normalized up_vec and sat_vec is cos(angle between them).
            # Elevation = 90 - angle_between_them
            angle_between_deg = math.degrees(math.acos(max(-1.0, min(1.0, cos_theta))))
            elevation_deg = 90 - angle_between_deg
            
            if elevation_deg < self.min_elevation_deg:
                continue
                
            # Check if approaching
            approaching = False
            if i in self.prev_distances:
                approach_speed = self.prev_distances[i] - dist_km
                if approach_speed > 0:
                    approaching = True
                    candidates.append((i, approach_speed))
        
        # Handover logic
        needs_handover = False
        if self.active_idx is not None:
            active_dist = current_distances.get(self.active_idx, float('inf'))
            active_rtt = (2 * active_dist) / c_km_ms
            
            # Check if current active satellite still meets SLO and elevation
            if active_rtt > slo_rtt_ms_handover:
                needs_handover = True
            else:
                # Still need to check elevation for the active one
                sat = satellites[self.active_idx]
                sat_pos = sat.getPos(earth_node.getTop())
                earth_world_pos = earth_node.getPos(earth_node.getTop())
                up_vec = gs_pos - earth_world_pos
                up_vec.normalize()
                sat_vec = sat_pos - gs_pos
                sat_vec.normalize()
                cos_theta = up_vec.dot(sat_vec)
                angle_between_deg = math.degrees(math.acos(max(-1.0, min(1.0, cos_theta))))
                elevation_deg = 90 - angle_between_deg
                
                if elevation_deg < self.min_elevation_deg:
                    needs_handover = True
        
        if needs_handover or self.active_idx is None:
            # Try to find a new candidate from the approaching satellites in range
            if candidates:
                # Select candidate with max approach speed
                best_cand = max(candidates, key=lambda x: x[1])
                new_idx = best_cand[0]
                
                if new_idx != self.active_idx:
                    hours = int(current_time // 3600)
                    minutes = int((current_time % 3600) // 60)
                    seconds = int(current_time % 60)
                    milliseconds = int((current_time % 1) * 1000)
                    time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

                    old_sat: Satellite = None
                    
                    print(f"\n--- Handover at simulation time: {time_str} ---")
                    if self.active_idx is not None:
                        old_sat = Satellite(self.active_idx, satellites[self.active_idx], earth_node)
                        old_info = old_sat.get_distance_metrics(gs_pos)
                        print(f"Old Satellite {old_info['id']}: dist={old_info['dist_km']:.2f}km, rtt={old_info['rtt_ms']:.2f}ms, elev={old_info['elevation_deg']:.2f}°")
                    else:
                        print("Old Satellite: None")

                    new_sat = Satellite(new_idx, satellites[new_idx], earth_node)
                    new_info = new_sat.get_distance_metrics(gs_pos)
                    print(f"New Satellite {new_info['id']}: dist={new_info['dist_km']:.2f}km, rtt={new_info['rtt_ms']:.2f}ms, elev={new_info['elevation_deg']:.2f}°")

                    if self.orchestrator and old_sat and new_sat:
                        self.orchestrator.migrate(old_sat, new_sat)
                        self.orchestrator.update(new_sat, gs_pos)

                    self.active_idx = new_idx
            elif needs_handover:
                # If current one is invalid and no approaching candidates, set to None
                if self.active_idx is not None:
                    hours = int(current_time // 3600)
                    minutes = int((current_time % 3600) // 60)
                    seconds = int(current_time % 60)
                    milliseconds = int((current_time % 1) * 1000)
                    time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
                    
                    print(f"\n--- Handover at simulation time: {time_str} ---")
                    old_sat = Satellite(self.active_idx, satellites[self.active_idx], earth_node)
                    old_info = old_sat.get_distance_metrics(gs_pos)
                    print(f"Old Satellite {old_info['id']}: dist={old_info['dist_km']:.2f}km, rtt={old_info['rtt_ms']:.2f}ms, elev={old_info['elevation_deg']:.2f}°")
                    print("New Satellite: None")
                self.active_idx = None

        self.prev_distances = current_distances
        return self.active_idx
