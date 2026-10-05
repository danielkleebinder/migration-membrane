import numpy as np
import math
import csv
from astropy import units as u
from astropy.time import Time, TimeDelta
from astropy.coordinates import EarthLocation, AltAz, SkyCoord, GCRS
from poliastro.bodies import Earth
from poliastro.twobody import Orbit
from concurrent.futures import ThreadPoolExecutor
import subprocess
import time
import socket

# --- FIX FÜR DEN TIMEOUT (Offline-Modus für IERS-Daten aktivieren) ---
from astropy.utils.iers import conf

conf.auto_download = False
conf.auto_max_age = None

IFACE = "eth0"  # Change to "end0" if required by your OS build
TARGET_PORT = 8080
ALTITUDE = 550 * u.km
VIENNA_LOC = EarthLocation(lat=48.2082 * u.deg, lon=16.3738 * u.deg, height=0 * u.m)
epoch = Time("2026-06-29T15:30:00", scale="utc")
C_KM_S = 299792.458  # Speed of light
CSV_FILENAME = "results_routing_latency.csv"

CONNECTION_ELEVATION = 40.0
CONNECTION_ELEVATION_WORST = 15.0
MIN_JITTER = 1.0
MAX_JITTER = 12.0
MIN_LOSS = 0.5
MAX_LOSS = 4.0

SIMULATION_START = -100
SIMULATION_END = 350
SIMULATION_STEP_SIZE = 1
SAMPLES_PER_STEP = 3

satellites = [
    {
        "short": "sat1",
        "name": "Satellite 1",
        "ip": "192.168.10.11",
        "offset": 0
    },
    {
        "short":"sat2",
        "name": "Satellite 2",
        "ip": "192.168.10.12",
        "offset": -120
    },
    {
        "short":"sat3",
        "name": "Satellite 3",
        "ip": "192.168.10.13",
        "offset": -240
    },
]

vienna_gcrs = VIENNA_LOC.get_gcrs(epoch)
pos_vienna_vec = vienna_gcrs.cartesian.xyz
r_earth_mag = np.linalg.norm(pos_vienna_vec)
r_sat_mag = r_earth_mag + ALTITUDE
r_vec = (pos_vienna_vec / r_earth_mag) * r_sat_mag
v_mag = np.sqrt(Earth.k / r_sat_mag).to(u.km / u.s)

z_axis = np.array([0, 0, 1]) * u.km
east_vec = np.cross(z_axis.value, r_vec.value)
north_vec = np.cross(r_vec.value, east_vec)
north_dir = north_vec / np.linalg.norm(north_vec)
v_vec = north_dir * v_mag.value * (u.km / u.s)

orbit = Orbit.from_vectors(Earth, r_vec, v_vec, epoch)

def force_clean_interface():
    """Completely resets traffic control rules on the interface."""
    subprocess.run(["sudo", "tc", "qdisc", "del", "dev", IFACE, "root"], stderr=subprocess.DEVNULL)
    print(f"Interface {IFACE} cleared.")

def init_tc():
    """Initializes the classful queuing disciplines for path separation."""
    subprocess.run(["sudo", "tc", "qdisc", "add", "dev", IFACE, "root", "handle", "1:", "prio"])
    for index, curr in enumerate(satellites):
        subprocess.run(["sudo", "tc", "qdisc", "add", "dev", IFACE, "parent", f"1:{index + 1}", "handle", f"{(index + 1) * 10}:", "netem"])
        subprocess.run(["sudo", "tc", "filter", "add", "dev", IFACE, "parent", "1:0", "u32", "match", "ip", "dst", curr["ip"], "flowid", f"1:{index + 1}"])

    print("Classful traffic pipes initialized.")

def apply_ground_channel(class_id, latency, jitter, loss, correlation = "25%"):
    """Updates the network pipe parameters in the kernel using replace."""
    delay = latency + 3 * jitter
    subprocess.run([
        "sudo", "tc", "qdisc", "replace", "dev", IFACE, "parent", f"1:{class_id}",
        "netem", "delay", f"{delay:.2f}ms", f"{jitter:.2f}ms", correlation, "distribution", "paretonormal", "loss", f"{loss:.2f}%"
    ])

def sample_rtt(target_ip):
    """Executes a single TCP connection attempt to sample network latency."""
    t0 = time.time()
    try:
        sock = socket.create_connection((target_ip, TARGET_PORT), timeout=0.4)
        sock.close()
        return (time.time() - t0) * 1000
    except Exception as e:
        print(f"Connection failed to {target_ip}:{TARGET_PORT} - {e}")
        return None


def latency(gsl_slant_range_km, extra_isl_distance_km = 0.0):
    """Calculates latency (one-way propagation delay * 2) for a given distance."""
    gsl_delay_ms = (gsl_slant_range_km / C_KM_S) * 1000
    isl_delay_ms = (extra_isl_distance_km / C_KM_S) * 1000
    return gsl_delay_ms + isl_delay_ms

def link_properties(deg):
    if deg <= CONNECTION_ELEVATION_WORST:
        return 100.0, MAX_JITTER

    # An empirical mapping inspired by the elevation dependence described in ITU-R P.618
    # 20° elevation maps to worst case (5% loss, 15ms stochastical jitter)
    # 90° elevation maps to best case (near 0% loss, 1ms jitter)
    # loss_scale = (math.sin(math.radians(CONNECTION_ELEVATION)) / math.sin(math.radians(deg))) ** 1.2
    raw_min = (math.sin(math.radians(CONNECTION_ELEVATION_WORST)) / math.sin(math.radians(90.0))) ** 1.2
    raw_scale = (math.sin(math.radians(CONNECTION_ELEVATION_WORST)) / math.sin(math.radians(deg))) ** 1.2

    # Normalize scale to range strictly between 0.0 (at 90 deg) and 1.0 (at 20 deg)
    loss_scale = (raw_scale - raw_min) / (1.0 - raw_min)

    packet_loss = MIN_LOSS + ((MAX_LOSS - MIN_LOSS) * loss_scale)
    jitter = MIN_JITTER + ((MAX_JITTER - MIN_JITTER) * loss_scale)
    return packet_loss, jitter

print(f"=== POLIASTRO SIMULATION (Flughöhe: {ALTITUDE.value} km) ===")
print(" Timestep | Time (UTC) | Sat 1 Elev | Sat 2 Elev | Sat 3 Elev | Sat 1 Lat  | Sat 2 Lat  | Sat 3 Lat  ")
print("-" * 110)

force_clean_interface()
init_tc()

results_log = []
timestep = 0

current_sat_index = 0
handover_time = SIMULATION_START - 1000

# Adjusting range to allow trailing satellites to fully pass over the horizon
for delta_sec in range(SIMULATION_START, SIMULATION_END, SIMULATION_STEP_SIZE):
    t_current = epoch + TimeDelta(delta_sec * u.s)
    time_str = t_current.strftime('%H:%M:%S')

    sat_data = {}

    satellite_metrics = []

    for index, curr in enumerate(satellites):
        # Trailing position is computed by looking at the orbit at an earlier time offset

        offset = curr["offset"]
        name = curr["short"]

        tof = (delta_sec + curr["offset"]) * u.s
        current_state = orbit.propagate(tof)

        sat_coord = SkyCoord(
            x=current_state.r[0],
            y=current_state.r[1],
            z=current_state.r[2],
            representation_type='cartesian',
            frame=GCRS(obstime=t_current)
        )

        altaz_frame = AltAz(obstime=t_current, location=VIENNA_LOC)
        sat_altaz = sat_coord.transform_to(altaz_frame)

        elevation = sat_altaz.alt.degree
        distance = sat_altaz.distance.to(u.km).value

        is_connected = elevation >= CONNECTION_ELEVATION
        curr_latency = latency(distance)
        curr_loss, curr_jitter = link_properties(elevation)

        satellite_metrics.append({
            "elevation": elevation,
            "distance": distance,
            "latency": curr_latency,
            "jitter": curr_jitter,
            "loss": curr_loss,
            "connected": is_connected
        })

        sat_data[f"{name}_elevation"] = elevation
        sat_data[f"{name}_distance"] = distance if is_connected else np.nan
        sat_data[f"{name}_latency"] = curr_latency if is_connected else np.nan
        sat_data[f"{name}_jitter"] = curr_jitter if is_connected else np.nan
        sat_data[f"{name}_loss"] = curr_loss if is_connected else np.nan

    satellite = satellites[current_sat_index]
    metrics = satellite_metrics[current_sat_index]

    if not metrics["connected"]:
        print(f"Not connected to any satellite....")
        continue

    if (current_sat_index < (len(satellites) - 1)
            and satellite_metrics[current_sat_index]["distance"] > satellite_metrics[current_sat_index + 1]["distance"]
            and (satellite_metrics[current_sat_index]["elevation"] * 1.1) < satellite_metrics[current_sat_index + 1]["elevation"]):
        handover_time = timestep

    apply_ground_channel(
        current_sat_index + 1,
        metrics["latency"],
        metrics["jitter"] if not timestep <= handover_time + 5 else metrics["jitter"] * 2,
        metrics["loss"] if not timestep <= handover_time + 5 else metrics["loss"] * 3
    )

    samples = SAMPLES_PER_STEP if not timestep <= handover_time + 5 else SAMPLES_PER_STEP * 2

    if handover_time == timestep:
        print(f"Handover from satellite {current_sat_index} to satellite {current_sat_index + 1} at {timestep}")
        current_sat_index += 1

    with ThreadPoolExecutor(max_workers=samples) as executor:
        futures = []
        for x in range(0, samples, 1):
            future = executor.submit(sample_rtt, satellite["ip"])
            futures.append(future)
            time.sleep(0.025)

        for future in futures:
            rtt = future.result()
            log = {
                "timestamp": timestep,
                "lost": 1 if rtt is None else 0
            }
            for curr in satellites:
                log[curr["short"]] = f"{rtt:.4f}" if (curr["short"] == satellite["short"] and rtt is not None) else "NaN"

            results_log.append(log)

    # Format output row for printing
    elev_str_1 = f"{sat_data['sat1_elevation']:8.2f}°" if not np.isnan(sat_data['sat1_distance']) else f"{'Out':>9}"
    elev_str_2 = f"{sat_data['sat2_elevation']:8.2f}°" if not np.isnan(sat_data['sat2_distance']) else f"{'Out':>9}"
    elev_str_3 = f"{sat_data['sat3_elevation']:8.2f}°" if not np.isnan(sat_data['sat3_distance']) else f"{'Out':>9}"

    lat_str_1 = f"{sat_data['sat1_latency']:10.2f}" if not np.isnan(sat_data['sat1_distance']) else f"{'-':>10}"
    lat_str_2 = f"{sat_data['sat2_latency']:10.2f}" if not np.isnan(sat_data['sat2_distance']) else f"{'-':>10}"
    lat_str_3 = f"{sat_data['sat3_latency']:10.2f}" if not np.isnan(sat_data['sat3_distance']) else f"{'-':>10}"

    print(f" {timestep:8} | {time_str}  | {elev_str_1} | {elev_str_2} | {elev_str_3} | {lat_str_1} | {lat_str_2} | {lat_str_3}")

    timestep += SIMULATION_STEP_SIZE

# Reset interface to standard settings
force_clean_interface()

# Write clean dataset to disk
with open(CSV_FILENAME, 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=["timestamp"] + [s["short"] for s in satellites] + ["lost"])
    writer.writeheader()
    writer.writerows(results_log)

print(f"Simulation complete. Save results to: {CSV_FILENAME}")
