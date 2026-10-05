from .constellation import Constellation

class WalkerDeltaConstellation(Constellation):
    def __init__(self, altitude, inclination, planes, satellites_per_plane, phasing):
        self._altitude = altitude
        self._inclination = inclination
        self._planes = planes
        self._satellites_per_plane = satellites_per_plane
        self._phasing = phasing

    @property
    def altitude(self):
        return self._altitude

    @property
    def inclination(self):
        return self._inclination

    @property
    def planes(self):
        return self._planes

    @property
    def satellites_per_plane(self):
        return self._satellites_per_plane

    @property
    def phasing(self):
        return self._phasing
