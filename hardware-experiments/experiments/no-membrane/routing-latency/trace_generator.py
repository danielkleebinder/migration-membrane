import numpy as np
import math
from astropy import units as u
from astropy.time import Time, TimeDelta
from astropy.coordinates import EarthLocation, AltAz, SkyCoord, GCRS
from poliastro.bodies import Earth
from poliastro.twobody import Orbit

# --- FIX FÜR DEN TIMEOUT (Offline-Modus für IERS-Daten aktivieren) ---
from astropy.utils.iers import conf

conf.auto_download = False

ALTITUDE = 550 * u.km
VIENNA_LOC = EarthLocation(lat=48.2082 * u.deg, lon=16.3738 * u.deg, height=0 * u.m)
epoch = Time("2026-06-29T15:30:00", scale="utc")
C_KM_S = 299792.458  # Speed of light

CONNECTION_ELEVATION = 40.0
MIN_JITTER = 2.0
MAX_JITTER = 15.0
MIN_LOSS = 1.0
MAX_LOSS = 5.0

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

def latency(gsl_slant_range_km, extra_isl_distance_km = 0.0):
    """Calculates RTT latency (one-way propagation delay * 2) for a given distance."""
    gsl_delay_ms = (gsl_slant_range_km / C_KM_S) * 1000
    isl_delay_ms = (extra_isl_distance_km / C_KM_S) * 1000
    return gsl_delay_ms + isl_delay_ms

def link_properties(deg):
    if deg <= CONNECTION_ELEVATION:
        return 100.0, MAX_JITTER

    # 6. ITU-R P.618 Scintillation/Loss Mapping Curve (Higher loss at low elevation)
    # 20° elevation maps to worst case (5% loss, 15ms stochastical jitter)
    # 90° elevation maps to best case (near 0% loss, 1ms jitter)
    raw_min = (math.sin(math.radians(CONNECTION_ELEVATION)) / math.sin(math.radians(90.0))) ** 1.2
    raw_scale = (math.sin(math.radians(CONNECTION_ELEVATION)) / math.sin(math.radians(deg))) ** 1.2

    # Normalize scale to range strictly between 0.0 (at 90 deg) and 1.0 (at 20 deg)
    loss_scale = (raw_scale - raw_min) / (1.0 - raw_min)

    packet_loss = MIN_LOSS + ((MAX_LOSS - MIN_LOSS) * loss_scale)
    jitter = MIN_JITTER + ((MAX_JITTER - MIN_JITTER) * loss_scale)
    return packet_loss, jitter

print(f"=== POLIASTRO SIMULATION (Flughöhe: {ALTITUDE.value} km) ===")
print(" Timestep | Time (UTC) | Sat 1 Elev | Sat 2 Elev | Sat 3 Elev | Sat 1 Lat  | Sat 2 Lat  | Sat 3 Lat  ")
print("-" * 110)

results_log = []
timestep = 0

# Adjusting range to allow trailing satellites to fully pass over the horizon
for delta_sec in range(-100, 350, 5):
    t_current = epoch + TimeDelta(delta_sec * u.s)
    time_str = t_current.strftime('%H:%M:%S')

    sat_data = {}

    # Define trailing offsets in seconds (Sat 1 is lead, Sat 2 and 3 trail behind)
    sat_offsets = {
        "sat1": 0,
        "sat2": -120,
        "sat3": -240
    }

    for sat_name, offset_sec in sat_offsets.items():
        # Trailing position is computed by looking at the orbit at an earlier time offset
        tof = (delta_sec + offset_sec) * u.s
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
        l, j = link_properties(elevation)

        sat_data[f"{sat_name}_elevation"] = elevation
        sat_data[f"{sat_name}_distance"] = distance if is_connected else np.nan
        sat_data[f"{sat_name}_latency"] = curr_latency if is_connected else np.nan
        sat_data[f"{sat_name}_jitter"] = j if is_connected else np.nan
        sat_data[f"{sat_name}_loss"] = l if is_connected else np.nan

    # Format output row for printing
    elev_str_1 = f"{sat_data['sat1_elevation']:8.2f}°" if not np.isnan(sat_data['sat1_distance']) else f"{'Out':>9}"
    elev_str_2 = f"{sat_data['sat2_elevation']:8.2f}°" if not np.isnan(sat_data['sat2_distance']) else f"{'Out':>9}"
    elev_str_3 = f"{sat_data['sat3_elevation']:8.2f}°" if not np.isnan(sat_data['sat3_distance']) else f"{'Out':>9}"

    lat_str_1 = f"{sat_data['sat1_latency']:10.2f}" if not np.isnan(sat_data['sat1_distance']) else f"{'-':>10}"
    lat_str_2 = f"{sat_data['sat2_latency']:10.2f}" if not np.isnan(sat_data['sat2_distance']) else f"{'-':>10}"
    lat_str_3 = f"{sat_data['sat3_latency']:10.2f}" if not np.isnan(sat_data['sat3_distance']) else f"{'-':>10}"

    dist_str_1 = f"{sat_data['sat1_distance']:10.2f}" if not np.isnan(sat_data['sat1_distance']) else f"{'-':>10}"
    dist_str_2 = f"{sat_data['sat2_distance']:10.2f}" if not np.isnan(sat_data['sat2_distance']) else f"{'-':>10}"
    dist_str_3 = f"{sat_data['sat3_distance']:10.2f}" if not np.isnan(sat_data['sat3_distance']) else f"{'-':>10}"

    print(f" {timestep:8} | {time_str}  | {elev_str_1} | {elev_str_2} | {elev_str_3} | {lat_str_1} | {lat_str_2} | {lat_str_3} | {dist_str_1} | {dist_str_2} | {dist_str_3}")

    results_log.append({
        "timestep": timestep,
        **sat_data
    })

    timestep += 1

print(f"Simulation complete.")