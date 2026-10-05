from abc import ABC, abstractmethod

class Orchestrator(ABC):
    @abstractmethod
    def setup(self):
        """Prepares the testbed, clears old tc configs, and sets up routing trees."""
        pass

    @abstractmethod
    def migrate(self, from_sat, to_sat):
        """Updates ISL traffic control and triggers the live migration."""
        pass

    @abstractmethod
    def update(self, active_sat, ground_pos):
        """Updates the dynamic traffic control between the active satellite and the ground sensor."""
        pass
