# -*- coding: utf-8 -*-
"""
Azayaka utility functions.
"""

import os
from typing import Callable, Tuple

import numpy as np
import cv2
import rasterio
from rasterio.transform import from_bounds


def save_scene_kml(
    geocoder,
    output_kml_path: str,
    max_iter: int = 1000,
    look_direction: str = None,
    include_overlay: bool = True,
    overlay_size: int = 1024,
    xyz2geo_func: Callable[[np.ndarray], Tuple[np.ndarray, np.ndarray, np.ndarray]] = None,
):
    """
    Export the SAR scene footprint to a KML file.

    Parameters
    ----------
    geocoder : Geocode
        Geocode instance containing SAR geometry and orbit information.
    output_kml_path : str
        Output path for the KML file.
    max_iter : int, optional
        Maximum iterations for the range-Doppler back-geocoding solver.
    look_direction : str, optional
        Look direction override ("R" or "L"). If None, uses the geocoder setting.
    include_overlay : bool, optional
        Whether to embed a downsampled intensity overlay.
    overlay_size : int, optional
        Output overlay size in pixels for both width and height.
    xyz2geo_func : callable, optional
        Function to convert ECEF XYZ to (lat, lon, height) in radians/meters.

    Returns
    -------
    list[tuple[float, float]]
        Scene corners as (lat, lon) in degrees, ordered around the footprint.

    Raises
    ------
    ValueError
        If `xyz2geo_func` is not provided or computed corners are out of bounds.
    """
    if xyz2geo_func is None:
        raise ValueError("xyz2geo_func is required.")
    if look_direction is None:
        look_direction = geocoder.look_direction

    corners = geocoder._compute_scene_corners(max_iter=max_iter, look_direction=look_direction)
    for lat, lon in corners:
        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
            raise ValueError(f"Corner out of bounds: lat={lat}, lon={lon}")

    scene_id = getattr(geocoder.sar, "PATH_CEOS_FOLDER", "unknown")
    scene_id = os.path.basename(scene_id)

    sat_start = np.array([geocoder.sar.P_X_SAT[0], geocoder.sar.P_Y_SAT[0], geocoder.sar.P_Z_SAT[0]])
    sat_end = np.array([geocoder.sar.P_X_SAT[-1], geocoder.sar.P_Y_SAT[-1], geocoder.sar.P_Z_SAT[-1]])
    sat_start_lat, sat_start_lon, sat_start_h = xyz2geo_func(sat_start)
    sat_end_lat, sat_end_lon, sat_end_h = xyz2geo_func(sat_end)
    sat_start_lat = float(np.degrees(sat_start_lat))
    sat_start_lon = float(np.degrees(sat_start_lon))
    sat_start_h = float(sat_start_h)
    sat_end_lat = float(np.degrees(sat_end_lat))
    sat_end_lon = float(np.degrees(sat_end_lon))
    sat_end_h = float(sat_end_h)

    near_idx = int(np.argmin(geocoder.sar.SLANT_RANGE_SAMPLE))
    far_idx = int(np.argmax(geocoder.sar.SLANT_RANGE_SAMPLE))
    near_range = float(geocoder.sar.SLANT_RANGE_SAMPLE[near_idx])
    far_range = float(geocoder.sar.SLANT_RANGE_SAMPLE[far_idx])
    sat_vel_start = np.array(
        [geocoder.sar.V_X_SAT[0], geocoder.sar.V_Y_SAT[0], geocoder.sar.V_Z_SAT[0]]
    )
    sat_vel_end = np.array(
        [geocoder.sar.V_X_SAT[-1], geocoder.sar.V_Y_SAT[-1], geocoder.sar.V_Z_SAT[-1]]
    )

    near_start = geocoder._range_doppler_back_geocode(
        sat_start, sat_vel_start, near_range, max_iter=max_iter, look_direction=look_direction
    )
    far_start = geocoder._range_doppler_back_geocode(
        sat_start, sat_vel_start, far_range, max_iter=max_iter, look_direction=look_direction
    )
    near_end = geocoder._range_doppler_back_geocode(
        sat_end, sat_vel_end, near_range, max_iter=max_iter, look_direction=look_direction
    )
    far_end = geocoder._range_doppler_back_geocode(
        sat_end, sat_vel_end, far_range, max_iter=max_iter, look_direction=look_direction
    )

    overlay_href = None
    if include_overlay and getattr(geocoder.sar, "signal", None) is not None:
        intensity = np.abs(geocoder.sar.signal).astype(np.float32)
        if intensity.size > 0:
            vmin = np.nanpercentile(intensity, 2)
            vmax = np.nanpercentile(intensity, 98)
            if np.isclose(vmax, vmin):
                vmax = vmin + 1.0
            norm = (intensity - vmin) / (vmax - vmin)
            norm = np.clip(norm, 0.0, 1.0)
            norm = (norm * 255.0).astype(np.uint8)
            resized = cv2.resize(norm, (overlay_size, overlay_size), interpolation=cv2.INTER_AREA)
            if str(getattr(geocoder.sar, "ORBIT_NAME", "")).upper() == "A":
                resized = cv2.flip(resized, 0)
            if str(look_direction).upper().startswith("L"):
                resized = cv2.flip(resized, 1)
            overlay_path = os.path.splitext(output_kml_path)[0] + "_intensity.png"
            cv2.imwrite(overlay_path, resized)
            overlay_href = os.path.basename(overlay_path)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2">',
        "  <Document>",
        f"    <name>{scene_id}</name>",
        "    <Style id=\"scene_footprint_style\">",
        "      <LineStyle>",
        "        <color>ff0000ff</color>",
        "        <width>2</width>",
        "      </LineStyle>",
        "      <PolyStyle>",
        "        <color>7f0000ff</color>",
        "        <fill>1</fill>",
        "        <outline>1</outline>",
        "      </PolyStyle>",
        "    </Style>",
        "    <Placemark>",
        "      <name>satellite_start</name>",
        "      <Point>",
        "        <coordinates>",
        f"          {sat_start_lon:.8f},{sat_start_lat:.8f},{sat_start_h:.2f}",
        "        </coordinates>",
        "      </Point>",
        "    </Placemark>",
        "    <Placemark>",
        "      <name>satellite_end</name>",
        "      <Point>",
        "        <coordinates>",
        f"          {sat_end_lon:.8f},{sat_end_lat:.8f},{sat_end_h:.2f}",
        "        </coordinates>",
        "      </Point>",
        "    </Placemark>",
        "    <Placemark>",
        "      <name>orbit_start_end</name>",
        "      <LineString>",
        "        <coordinates>",
        f"          {sat_start_lon:.8f},{sat_start_lat:.8f},{sat_start_h:.2f}",
        f"          {sat_end_lon:.8f},{sat_end_lat:.8f},{sat_end_h:.2f}",
        "        </coordinates>",
        "      </LineString>",
        "    </Placemark>",
        "    <Placemark>",
        "      <name>orbit_direction</name>",
        "      <LineString>",
        "        <coordinates>",
        f"          {sat_start_lon:.8f},{sat_start_lat:.8f},{sat_start_h:.2f}",
        f"          {sat_start_lon + (sat_end_lon - sat_start_lon) * 0.1:.8f},"
        f"{sat_start_lat + (sat_end_lat - sat_start_lat) * 0.1:.8f},{sat_start_h:.2f}",
        "        </coordinates>",
        "      </LineString>",
        "    </Placemark>",
        "    <Placemark>",
        "      <name>range_lines_start</name>",
        "      <LineString>",
        "        <coordinates>",
        f"          {sat_start_lon:.8f},{sat_start_lat:.8f},{sat_start_h:.2f}",
        f"          {near_start[1]:.8f},{near_start[0]:.8f},0",
        f"          {far_start[1]:.8f},{far_start[0]:.8f},0",
        "        </coordinates>",
        "      </LineString>",
        "    </Placemark>",
        "    <Placemark>",
        "      <name>range_lines_end</name>",
        "      <LineString>",
        "        <coordinates>",
        f"          {sat_end_lon:.8f},{sat_end_lat:.8f},{sat_end_h:.2f}",
        f"          {near_end[1]:.8f},{near_end[0]:.8f},0",
        f"          {far_end[1]:.8f},{far_end[0]:.8f},0",
        "        </coordinates>",
        "      </LineString>",
        "    </Placemark>",
        "    <Placemark>",
        "      <name>scene_footprint</name>",
        "      <styleUrl>#scene_footprint_style</styleUrl>",
        "      <Polygon>",
        "        <outerBoundaryIs>",
        "          <LinearRing>",
        "            <coordinates>",
    ]
    for lat, lon in corners + [corners[0]]:
        lines.append(f"              {lon:.8f},{lat:.8f},0")
    lines += [
        "            </coordinates>",
        "          </LinearRing>",
        "        </outerBoundaryIs>",
        "      </Polygon>",
        "    </Placemark>",
    ]
    if overlay_href is not None:
        quad = [
            (corners[0][1], corners[0][0]),
            (corners[1][1], corners[1][0]),
            (corners[2][1], corners[2][0]),
            (corners[3][1], corners[3][0]),
        ]
        lines += [
            "    <GroundOverlay>",
            "      <name>intensity_overlay</name>",
            "      <Icon>",
            f"        <href>{overlay_href}</href>",
            "      </Icon>",
            "      <gx:LatLonQuad>",
            "        <coordinates>",
            f"          {quad[0][0]:.8f},{quad[0][1]:.8f},0",
            f"          {quad[1][0]:.8f},{quad[1][1]:.8f},0",
            f"          {quad[2][0]:.8f},{quad[2][1]:.8f},0",
            f"          {quad[3][0]:.8f},{quad[3][1]:.8f},0",
            "        </coordinates>",
            "      </gx:LatLonQuad>",
            "    </GroundOverlay>",
        ]
    lines += [
        "  </Document>",
        "</kml>",
    ]
    with open(output_kml_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return corners
