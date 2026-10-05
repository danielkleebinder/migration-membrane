"""
Render a set of satellites in orbit around the earth.
40 orbits of 40 satellites at a ~53 degree incline to the equator.

Derived from: https://github.com/panda3d/panda3d/tree/master/samples/solar-system
"""

from panda3d.core import loadPrcFileData, Vec3, LRotationf, LQuaternionf, LineSegs

from migration.constellations.constellation import Constellation
from migration.migrators.migrator import Migrator
from migration.orchestration.experiment_orchestrator import ExperimentOrchestrator
from migration.orchestration.noop_orchestrator import NoopOrchestrator
from migration.orchestration.orchestrator import Orchestrator
from migration.satellite import Satellite

loadPrcFileData("", "win-size 2200 1800")
from direct.showbase.ShowBase import ShowBase

base = ShowBase()

from direct.showbase.DirectObject import DirectObject
from direct.task import Task

import sys
import math
import csv
from migration.constellations.walker_delta_constellation import WalkerDeltaConstellation
from migration.constellations.walker_star_constellation import WalkerStarConstellation
from migration.migrators.migrator_simple import MigratorSimple

# Gravitational Constant (m^3 kg^-1 s^-2)
G = 6.67430e-11

# Mass of Earth (kg)
EARTH_MASS = 5.9722e24

# Equatorial Radius of Earth (km)
EARTH_RADIUS = 6378.137

# Standard Gravitational Parameter (μ = G * M)
MU_EARTH = G * EARTH_MASS # m^3 / s^2

EXPERIMENT_UPDATE_INTERVAL = 2
EXPERIMENT_SENSOR_IP = "192.168.10.14"
EXPERIMENT_SAT_IP_CONFIG = [
    "192.168.10.11",     # sat1
    "192.168.10.12"      # sat2
]


class World(DirectObject):

    def __init__(
            self,
            constellation: Constellation,
            migrator: Migrator= None,
            orchestrator: Orchestrator = None,
            speed: int = 1,
            render_earth: bool = True,
            render_satellites: bool = True,
            render_orbits: bool = True,
            render_slo_sphere: bool = True,
            render_red_point: bool = True,
    ):
        self.constellation = constellation
        self.migrator = migrator
        self.render_earth = render_earth
        self.render_satellites = render_satellites
        self.render_orbits = render_orbits
        self.render_slo_sphere = render_slo_sphere
        self.render_red_point = render_red_point
        base.setBackgroundColor(0, 0, 0)
        base.disableMouse()  # disable mouse control of the camera
        base.camera.setPos(0, -45, 0)  # Set the camera position (X, Y, Z)
        base.camera.setHpr(0, 0, 0)  # Set the camera orientation

        # Seconds in a day for the earth rotation.
        self.day_len = 24 * 60 * 60

        # Seconds for a satellite orbit.
        # Orbital Period T = 2 * pi * sqrt(r^3 / MU) in seconds
        r_meters = (EARTH_RADIUS + constellation.altitude) * 1000.0
        period_seconds = 2.0 * math.pi * math.sqrt((r_meters**3) / MU_EARTH)
        self.orbit_len = period_seconds
        print(f"Orbital period: {(period_seconds / 60):.2f} m")

        # Speed up factor for animation.
        self.speed = speed

        # Scale earth, satellites, and orbit
        self.sat_size_scale = 0.1 * 0.65
        self.earth_size_scale = 10

        # Red point configuration (geocentric lat/lon)
        self.point_lat = 21
        self.point_lon = 144

        # Orbit height above earch from constellation
        # Scale orbit above the earth
        self.orbitscale = self.earth_size_scale * (1 + self.constellation.altitude / EARTH_RADIUS)
        #  Nodes for rotating around the earth
        self.pivots = []
        # List of all satellite nodes
        self.satellites = []

        self.loadElements()
        self.rotateElements()
        base.taskMgr.add(self.gLoop, "gloop")
        self.accept("q", sys.exit)
        self.accept("arrow_up", self.moveUp)
        self.accept("arrow_down", self.moveDown)
        self.accept("arrow_right", self.moveRight)
        self.accept("arrow_left", self.moveLeft)
        self.heading = -(self.point_lon - 162) - 90
        self.pitch = 0
        self.setView()

        # Mouse control state
        self.dragging = False
        self.lastMousePos = None
        self.accept("mouse1", self.startDrag)
        self.accept("mouse1-up", self.stopDrag)
        self.accept("wheel_up", self.zoomIn)
        self.accept("wheel_down", self.zoomOut)
        base.taskMgr.add(self.mouseUpdate, "mouseUpdate")
        
        self.camDist = 45
        self.updateCamera()

        self.step_counter = 0

        self.orchestrator = orchestrator
        if self.orchestrator:
            self.orchestrator.setup()
            self.last_orchestrator_update = 0.0
            self.orchestrator_needs_update = False

        # CSV logging setup
        self.csv_file = open('traces.csv', 'w', newline='')
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow(['timestamp', 'satellite', 'distance', 'rtt', 'elevation'])

        self.accept("window-event", self.handleWindowEvent)

    def handleWindowEvent(self, window):
        if not base.win:
            self.csv_file.close()

    def startDrag(self):
        self.dragging = True
        if base.mouseWatcherNode.hasMouse():
            mpos = base.mouseWatcherNode.getMouse()
            self.lastMousePos = (mpos.getX(), mpos.getY())

    def stopDrag(self):
        self.dragging = False
        self.lastMousePos = None

    def mouseUpdate(self, task):
        if self.dragging and base.mouseWatcherNode.hasMouse():
            mpos = base.mouseWatcherNode.getMouse()
            currMousePos = (mpos.getX(), mpos.getY())
            if self.lastMousePos:
                dx = currMousePos[0] - self.lastMousePos[0]
                dy = currMousePos[1] - self.lastMousePos[1]
                
                # Sensitivity
                h_change = dx * 100
                p_change = dy * 100
                
                # Camera is looking along world Y.
                # Right is world X.
                # Up is world Z.
                
                # We apply horizontal rotation in world space (around Z)
                # and vertical rotation in camera space (around camera right, which is world X here)
                
                current_q = self.base.getQuat()
                
                # Rotation around world Z for horizontal movement
                h_q = LQuaternionf()
                h_q.setFromAxisAngle(h_change, Vec3(0, 0, 1))
                
                # Rotation around world X (camera right) for vertical movement
                p_q = LQuaternionf()
                p_q.setFromAxisAngle(-p_change, Vec3(1, 0, 0))
                
                # Applying P then current then H:
                new_q = current_q * p_q # Local pitch
                new_q = h_q * new_q     # Global yaw
                
                self.base.setQuat(new_q)
                
            self.lastMousePos = currMousePos
        return Task.cont

    def setView(self):
        # Initial view setting using HPR
        self.base.setHpr(self.heading, self.pitch, 0)

    def zoomIn(self):
        self.camDist -= 2
        if self.camDist < 11:  # Don't go inside the Earth (radius ~10)
            self.camDist = 11
        self.updateCamera()

    def zoomOut(self):
        self.camDist += 2
        self.updateCamera()

    def updateCamera(self):
        base.camera.setPos(0, -self.camDist, 0)

    def moveUp(self):
        current_q = self.base.getQuat()
        p_q = LQuaternionf()
        p_q.setFromAxisAngle(-5, Vec3(1, 0, 0))
        self.base.setQuat(current_q * p_q)

    def moveDown(self):
        current_q = self.base.getQuat()
        p_q = LQuaternionf()
        p_q.setFromAxisAngle(5, Vec3(1, 0, 0))
        self.base.setQuat(current_q * p_q)

    def moveLeft(self):
        current_q = self.base.getQuat()
        h_q = LQuaternionf()
        h_q.setFromAxisAngle(-5, Vec3(0, 0, 1))
        self.base.setQuat(h_q * current_q)

    def moveRight(self):
        current_q = self.base.getQuat()
        h_q = LQuaternionf()
        h_q.setFromAxisAngle(5, Vec3(0, 0, 1))
        self.base.setQuat(h_q * current_q)

    def loadElements(self):
        """
        Create all of the nodes for the animation.
        """

        # Create nodes used to incline the orbit and rotate.
        # Pivots are nodes that change heading for rotation.
        self.base = base.render.attachNewNode("base")
        orbits = self.constellation.planes

        satellites_total = self.constellation.planes * self.constellation.satellites_per_plane
        print(f"Total satellites: {satellites_total}")

        for i in range(0, orbits):
            # We use one node, an oribt path to orient the orbit, setting the
            # degree of tilt and the orientation.
            orbit_path = self.base.attachNewNode(f"orbit_path_{i}")
            heading = (360 / orbits) * i
            orbit_path.setHpr(heading, 0, self.constellation.inclination)

            # We create an additional node to simply rotate in the plane
            # set by the orbit path to which it is attached. We save this
            # node in order to run the rotation.
            orbit_pivot = orbit_path.attachNewNode(f"orbit_pivot_{i}")
            self.pivots.append(orbit_pivot)

            if self.render_orbits:
                ls = LineSegs()
                # ls.setColor(0.5, 0.5, 0.5, 1)
                ls.setColor(0.75, 0.5, 0.15, 1)     # postorange
                ls.setThickness(2.0)
                num_segments = 100
                for seg_num in range(num_segments + 1):
                    angle = (math.pi * 2 / num_segments) * seg_num
                    x = math.sin(angle) * self.orbitscale
                    y = math.cos(angle) * self.orbitscale
                    ls.drawTo(x, y, 0)
                orbit_line = orbit_path.attachNewNode(ls.create())
                orbit_line.setTransparency(1)
                orbit_line.setColorScale(1, 1, 1, 0.5)

            # Add orbital plane
            plane = base.loader.loadModel("models/planet_sphere")
            plane.reparentTo(orbit_path)
            plane.setPos(0, 0, 0)
            plane.setScale(self.orbitscale, self.orbitscale, 0.001)
            plane.setTransparency(1)
            plane.setColor(1, 1, 1, 0)

            # Add satellites to the orbit.
            num_sats = self.constellation.satellites_per_plane
            # Radians between the satellites in the same orbit
            separation = math.pi * 2 / num_sats

            # Phasing calculation:
            # phase_offset = p * phasing * (2 * np.pi / satellites_total)
            # where p is the plane index
            phase_offset_rad = i * self.constellation.phasing * (2 * math.pi / satellites_total)

            for sat_num in range(0, num_sats):
                rads = separation * sat_num + phase_offset_rad
                if self.render_satellites:
                    sat = base.loader.loadModel("models/planet_sphere")
                    sat.reparentTo(orbit_pivot)
                    sat.setScale(self.sat_size_scale)
                    x = math.sin(rads) * self.orbitscale
                    y = math.cos(rads) * self.orbitscale
                    sat.setPos(x, y, 0)
                    self.satellites.append(sat)
                else:
                    # We still need a placeholder or a way to track position if migrator is used,
                    # but if render_satellites is false, we might not have the nodes.
                    # The current migrator logic depends on self.satellites being a list of Panda3D nodes.
                    # If we don't render them, we should still probably create them but hide them,
                    # or update the migrator to handle missing nodes.
                    # Given the request is "render", hiding them is the safest approach to maintain logic.
                    sat = base.loader.loadModel("models/planet_sphere")
                    sat.reparentTo(orbit_pivot)
                    sat.setScale(self.sat_size_scale)
                    x = math.sin(rads) * self.orbitscale
                    y = math.cos(rads) * self.orbitscale
                    sat.setPos(x, y, 0)
                    sat.hide()
                    self.satellites.append(sat)

        # Load the Earth
        self.earth = base.loader.loadModel("models/planet_sphere")
        earth_tex = base.loader.loadTexture("models/earth_simple.jpg")
        self.earth.setTexture(earth_tex, 1)
        self.earth.reparentTo(self.base)
        self.earth.setScale(self.earth_size_scale)
        self.earth.setHpr(0, 0, 0)
        if not self.render_earth:
            self.earth.hide()

        # Draw red point on Earth's surface
        self.red_point = self.drawRedPoint(self.point_lat, self.point_lon)

        # SLO radius sphere
        self.slo_radius_km = 450 # Default if not from migrator
        if self.migrator and hasattr(self.migrator, 'slo_rtt_ms'):
            c_km_ms = 299.792458
            self.slo_radius_km = (self.migrator.slo_rtt_ms * c_km_ms) / 2.0
        
        self.drawSloSphere()

    def drawSloSphere(self):
        self.slo_sphere = base.loader.loadModel("models/planet_sphere")
        self.slo_sphere.setTextureOff(1)
        self.slo_sphere.reparentTo(self.red_point)
        # self.red_point is scaled by 0.02 and reparented to self.earth (scaled by 10)
        # In Panda3D, scale is multiplicative.
        # To get a world radius of 'r' where earth has world radius 10:
        # scale_on_red_point = (r_in_units) / (red_point_scale * earth_scale)
        # r_in_units = self.slo_radius_km / 637.1
        
        # 1 unit = 6371 km (Earth radius in Earth's local coordinate system)
        r_earth_relative = self.slo_radius_km / 6371.0
        
        # red_point scale is 0.02 relative to earth
        # To have slo_sphere have radius 'r_earth_relative' in earth's local space:
        # relative_scale = r_earth_relative / 0.02
        
        scale = r_earth_relative / 0.02
        self.slo_sphere.setScale(scale)
        self.slo_sphere.setTransparency(1)
        self.slo_sphere.setColor(0, 0, 1, 0.3) # Transparent blue
        if not self.render_slo_sphere:
            self.slo_sphere.hide()

    def drawRedPoint(self, lat, lon):
        phi = math.radians(lat)
        # Offset to align with the texture of models/planet_sphere
        # In this model, (1,0,0) corresponds to longitude 162E
        theta = math.radians(lon - 162)

        # Standard Spherical to Cartesian (Z-up)
        # We set radius to 1 because the point will be reparented to self.earth
        # which is already scaled by self.earth_size_scale.
        x = math.cos(phi) * math.cos(theta)
        y = math.cos(phi) * math.sin(theta)
        z = math.sin(phi)

        point = base.loader.loadModel("models/planet_sphere")
        point.setName("red_point")
        point.setTextureOff(1)
        point.reparentTo(self.earth)
        # Small scale relative to the earth
        point.setScale(0.02)
        point.setPos(x, y, z)
        point.setColor(1, 0, 0, 1)  # Red color
        if not self.render_red_point:
            point.hide()
        return point

    def rotateElements(self):
        """
        Create all loops to drive the animation.
        """
        # Create a loop to rotate the earth
        self.day_period = self.earth.hprInterval(self.day_len / self.speed, (360, 0, 0))
        self.day_period.loop()

        # Create loops to rotate the orbits
        self.orbit_periods = []
        for orbit_pivot in self.pivots:
            orbit_period = orbit_pivot.hprInterval(
                self.orbit_len / self.speed, (360, 0, 0)
            )
            orbit_period.loop()
            self.orbit_periods.append(orbit_period)

    def gLoop(self, task):
        self.step_counter += 1
        current_sim_time = task.time * self.speed

        if (task.time - self.last_orchestrator_update) >= EXPERIMENT_UPDATE_INTERVAL:
            self.orchestrator_needs_update = True

            # Record this exact time as the new baseline
            # (Or use self.last_orchestrator_update += EXPERIMENT_UPDATE_INTERVAL for strict pacing)
            self.last_orchestrator_update = task.time

        if self.migrator:
            active_idx = self.migrator.update(
                self.satellites, 
                self.earth, 
                self.point_lat, 
                self.point_lon, 
                current_sim_time
            )

            for i, sat in enumerate(self.satellites):
                if i == active_idx:
                    sat.setColor(0, 1, 0, 1) # Green
                    sat.setScale(self.sat_size_scale * 2) # Make it bigger
                    
                    # Calculate and print metrics for the active satellite
                    gs_pos = self.red_point.getPos(self.earth.getTop())
                    sat = Satellite(i, self.satellites[i], self.earth)
                    info = sat.get_distance_metrics(gs_pos)

                    if self.orchestrator and self.orchestrator_needs_update:
                        self.orchestrator.update(sat, gs_pos)
                        self.orchestrator_needs_update = False
                    
                    # Simulation time in HH:MM:ss.mmm
                    hours = int(current_sim_time // 3600)
                    minutes = int((current_sim_time % 3600) // 60)
                    seconds = int(current_sim_time % 60)
                    milliseconds = int((current_sim_time % 1) * 1000)
                    time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

                    if self.step_counter % 10 == 0:
                        print(f"[{time_str}] Active Satellite: {i}, Dist: {info['dist_km']:.2f}km, RTT: {info['rtt_ms']:.2f}ms, Elev: {info['elevation_deg']:.2f}°")
                    
                    # Write to CSV
                    self.csv_writer.writerow([
                        time_str, 
                        i, 
                        f"{info['dist_km']:.2f}", 
                        f"{info['rtt_ms']:.2f}", 
                        f"{info['elevation_deg']:.2f}"
                    ])
                    self.csv_file.flush()
                else:
                    sat.clearColor()
                    # sat.setColor(0.17, 0.63, 0.17, 1)                     # execgreen
                    # sat.setColor(0.12, 0.47, 0.71, 1)                     # compblue
                    # sat.setColor(214 / 255, 39 / 255, 40 / 255, 1)        # instred
                    sat.setColor(1, 0.5, 0.05, 1)                           # postorange
                    sat.setScale(self.sat_size_scale)

        return Task.cont


# Default Starlink-like configuration if run directly
# shell = WalkerDeltaConstellation(
#     altitude=550,
#     inclination=53,
#     planes=72,
#     satellites_per_plane=24,
#     phasing=1
# )

shell = WalkerDeltaConstellation(
    altitude=550,
    inclination=53,
    planes=40,
    satellites_per_plane=40,
    phasing=1
)

# Walker Star Baseline: OneWeb Gen 1
# shell = WalkerStarConstellation(
#     altitude=1200,
#     inclination=87.9,
#     planes=12,
#     satellites_per_plane=49,
#     phasing=1,
#     raan=180
# )

# Define an orchestrator for the experiments
orchestrator: Orchestrator = NoopOrchestrator(
    node_ips=EXPERIMENT_SAT_IP_CONFIG,
    sensor_ip=EXPERIMENT_SENSOR_IP
)

# 14 ms latency SLO experiment
migrator = MigratorSimple(
    orchestrator=orchestrator,
    slo_rtt_ms=14.0,
    safety_margin=0.8,
    min_elevation_deg=25,
)

# 10 ms latency SLO experiment
# migrator = MigratorSimple(
#     orchestrator=orchestrator,
#     slo_rtt_ms=10.0,
#     safety_margin=0.8,
#     min_elevation_deg=40,
# )

# 6 ms latency SLO experiment
# migrator = MigratorSimple(
#     orchestrator=orchestrator,
#     slo_rtt_ms=6.0,
#     safety_margin=0.8,
#     min_elevation_deg=40,
# )

w = World(
    constellation=shell,
    migrator=migrator,
    orchestrator=orchestrator,
    speed=10,
    render_earth=True,
    render_satellites=True,
    render_orbits=True,
    render_slo_sphere=True,
    render_red_point=True
)
base.run()
