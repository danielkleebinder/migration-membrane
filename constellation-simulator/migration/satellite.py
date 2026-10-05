import math

class Satellite:
    def __init__(self, id, node, earth):
        self.id = id
        self.node = node
        self.earth = earth

    def get_distance_metrics(self, other_pos):
        c_km_ms = 299.792458
        sat_pos = self.node.getPos(self.earth.getTop())
        dist_vec = sat_pos - other_pos
        dist_km = dist_vec.length() * (6371.0 / 10.0)
        rtt_ms = (2 * dist_km) / c_km_ms

        earth_world_pos = self.earth.getPos(self.earth.getTop())
        up_vec = other_pos - earth_world_pos
        up_vec.normalize()

        sat_vec = sat_pos - other_pos
        sat_vec.normalize()
        cos_theta = up_vec.dot(sat_vec)
        angle_between_deg = math.degrees(math.acos(max(-1.0, min(1.0, cos_theta))))
        elevation_deg = 90 - angle_between_deg

        return {
            "id": self.id,
            "dist_km": dist_km,
            "rtt_ms": rtt_ms,
            "elevation_deg": elevation_deg
        }
