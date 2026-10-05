from abc import ABC, abstractmethod

class Migrator(ABC):
    @abstractmethod
    def update(self, satellites, earth_pos, point_lat, point_lon, current_time):
        """
        Updates the migration heuristic.
        :param satellites: List of satellite nodes/objects.
        :param earth_pos: Current position/rotation of Earth.
        :param point_lat: Geocentric latitude of the target point.
        :param point_lon: Geocentric longitude of the target point.
        :param current_time: Current simulation time.
        :return: The index or reference of the currently active satellite.
        """
        pass
