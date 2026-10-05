from abc import ABC, abstractmethod

class Constellation(ABC):
    @property
    @abstractmethod
    def altitude(self):
        pass

    @property
    @abstractmethod
    def inclination(self):
        pass

    @property
    @abstractmethod
    def planes(self):
        pass

    @property
    @abstractmethod
    def satellites_per_plane(self):
        pass

    @property
    @abstractmethod
    def phasing(self):
        pass
