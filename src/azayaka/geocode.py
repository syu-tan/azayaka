# -*- coding: utf-8 -*-
"""
Azayaka: 
    SAR/InSAR Geocoding Module.
    This module provides functionalities for geocoding SAR/InSAR outputs data.

    Copyright (c) 2026 Syusuke Yasui, Yutaka Yamamoto, and contributors.
    Licensed under the APGL-3.0 License.
    
    Equation - Condition: No 3.xxx File.

"""

import os, gc, json, time
from typing import Union, Tuple

import numpy as np
import matplotlib.pyplot as plt
from tqdm import tqdm
import rasterio
from rasterio.transform import from_bounds
import cv2
from . import utils
from scipy.interpolate import (
    interp1d, RectBivariateSpline, griddata, NearestNDInterpolator, LinearNDInterpolator)
from scipy.ndimage import uniform_filter, shift, gaussian_filter, binary_dilation


class GRS80:
    """GRS80 (Geodetic Reference System 1980) 測地基準系のパラメータ"""
    AE = 6378137.0  # 赤道半径 (m)
    FLAT = 1.0 / 298.257222101  # 扁平率
    GM = 398600.436  # 地心重力定数 (km³/s²)
    OMFSQ = (1.0 - FLAT) ** 2  # (1 - f)²
    AP = AE * (1.0 - FLAT)  # 極半径 (m)
    FFACT = OMFSQ - 1.0  # 形状係数
    AM = AE * (1.0 - FLAT / 3.0 - FLAT * FLAT / 5.0)  # 平均半径
    AMSQ = AM ** 2  # 平均半径の二乗


def geocen(lat: Union[float, np.ndarray],
           height: Union[float, np.ndarray]) -> Tuple[np.ndarray, np.ndarray]:
    """
    測地緯度から地心緯度と地心距離を計算する。
    
    測地緯度（地表面の法線が赤道面となす角）を地心緯度（地心から見た角度）に変換し、
    地心からの距離を計算します。
    
    Parameters
    ----------
    lat : float or array_like
        測地緯度 (ラジアン)。スカラー値またはn次元配列。
    height : float or array_like
        GRS80楕円体からの高度 (m)。latと同じ形状である必要があります。
    
    Returns
    -------
    latc : ndarray
        地心緯度 (ラジアン)
    r : ndarray
        地心からの距離 (m)
    
    Notes
    -----
    この関数は、楕円体上の点から地心座標系への変換において、
    緯度の補正と実際の地心距離を計算します。
    """
    lat = np.asarray(lat)
    height = np.asarray(height)
    
    # 測地緯度から地心緯度への第一近似
    # Equation - Condition: No 3.1
    # # Geocentric Latitude (approx.) := ArcTan((1 - f)² * tan(φ))
    lats = np.arctan(GRS80.OMFSQ * np.tan(lat))
    
    # 楕円体上の点の地心距離
    # Equation - Condition: No 3.2
    # # Ellipsoid Radius := a_p / sqrt(1 + F * cos²(φc))
    rs = GRS80.AP / np.sqrt(1.0 + GRS80.FFACT * np.cos(lats) ** 2)
    
    # 高度を含めた実際の地心距離
    # Equation - Condition: No 3.3
    # # Geocentric Distance := sqrt(h² + rs² + 2h * rs *  cos(φ - φc))
    r = np.sqrt(height ** 2 + rs ** 2 + 2 * height * rs * np.cos(lat - lats))
    
    # 地心緯度の計算（高度による補正を含む）
    # Equation - Condition: No 3.4
    # # Geocentric Latitude := φc + ArcSin(h * sin(φ - φc) / r)
    latc = lats + np.arcsin(height * np.sin(lat - lats) / r)
    
    return latc, r


def polcar(lat: Union[float, np.ndarray],
           lon: Union[float, np.ndarray],
           r: Union[float, np.ndarray]) -> np.ndarray:
    """
    極座標（球座標）から直交座標への変換。
    
    地心距離と地心緯度・経度から、地心直交座標系（ECEF: Earth Centered Earth Fixed）
    のXYZ座標を計算します。
    
    Parameters
    ----------
    lat : float or array_like
        地心緯度 (ラジアン)
    lon : float or array_like
        経度 (ラジアン)
    r : float or array_like
        地心からの距離 (m)
    
    Returns
    -------
    xyz : ndarray
        地心直交座標 [X, Y, Z] (m)。
        入力が配列の場合、最後の次元が3要素の座標になります。
        例：入力が(M, N)の場合、出力は(M, N, 3)
    """
    lat = np.asarray(lat)
    lon = np.asarray(lon)
    r = np.asarray(r)
    
    # 各座標成分を計算
    # Equation - Condition: No 3.5
    # # ECEF XYZ := r * [cos(φ)cos(λ), cos(φ)sin(λ), sin(φ)]
    x = r * np.cos(lat) * np.cos(lon)
    y = r * np.cos(lat) * np.sin(lon)
    z = r * np.sin(lat)
    
    # 結果を結合して返す
    return np.stack([x, y, z], axis=-1)


def geoxyz(lat: Union[float, np.ndarray],
           lon: Union[float, np.ndarray],
           height: Union[float, np.ndarray]) -> Tuple[np.ndarray, np.ndarray]:
    """
    測地座標から地心直交座標（ECEF）への変換。
    
    GRS80測地基準系における測地緯度、経度、楕円体高から、
    地球中心を原点とする地心直交座標系（Earth Centered Earth Fixed: ECEF）の
    XYZ座標を計算します。
    
    Parameters
    ----------
    lat : float or array_like
        測地緯度 (ラジアン)。-π/2 ≤ lat ≤ π/2
    lon : float or array_like
        測地経度 (ラジアン)。-π ≤ lon ≤ π
    height : float or array_like
        GRS80楕円体からの高度 (m)
    
    Returns
    -------
    xyz : ndarray
        地心直交座標 [X, Y, Z] (m)。
        - X軸: グリニッジ子午線と赤道の交点方向
        - Y軸: 東経90度と赤道の交点方向  
        - Z軸: 地球の自転軸（北極方向が正）
    r : ndarray
        地心からの距離 (m)

    
    See Also
    --------
    xyz2geo : 逆変換（地心直交座標から測地座標への変換）
    """
    # 入力を配列に変換
    lat = np.asarray(lat)
    lon = np.asarray(lon)
    height = np.asarray(height)
    
    # 入力の形状が一致していることを確認
    if not (lat.shape == lon.shape == height.shape):
        raise ValueError("lat, lon, heightは同じ形状である必要があります")
    
    # 地心緯度と地心距離を計算
    latc, r = geocen(lat, height)
    
    # 極座標から直交座標へ変換
    xyz = polcar(latc, lon, r)
    
    return xyz, r


def xyz2geo(xyz: Union[np.ndarray, Tuple[float, float, float]]
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    地心直交座標（ECEF）から測地座標への逆変換。
    
    Parameters
    ----------
    xyz : array_like
        地心直交座標 [X, Y, Z] (m)。
        形状は(..., 3)である必要があります。
    
    Returns
    -------
    lat : ndarray
        測地緯度 (ラジアン)
    lon : ndarray
        測地経度 (ラジアン)
    height : ndarray
        楕円体高 (m)
    
    Notes
    -----
    Bowringの反復法を使用した逆変換アルゴリズムを実装しています。
    """
    xyz = np.asarray(xyz)
    if xyz.shape[-1] != 3:
        raise ValueError("xyzの最後の次元は3（X, Y, Z）である必要があります")
    
    x = xyz[..., 0]
    y = xyz[..., 1]
    z = xyz[..., 2]
    
    # 経度の計算
    # Equation - Condition: No 3.6 from 3.1
    # # Longitude := ArcTan(Y / X)
    lon = np.arctan2(y, x)
    
    # XY平面での距離
    # Equation - Condition: No 3.7
    # # Planar Distance := sqrt(X² + Y²)
    p = np.sqrt(x ** 2 + y ** 2)
    
    # Bowringの方法による緯度と高度の反復計算
    # Equation - Condition: No 3.8
    # # Auxiliary Angle θ := ArcTan(Z * a / (p * b))
    theta = np.arctan2(z * GRS80.AE, p * GRS80.AP)
    
    # 測地緯度の計算
    # Equation - Condition: No 3.9
    # # Geodetic Latitude := ArcTan(
    # #   (Z + f' b sin³θ) / (p - f' a cos³θ)
    # # )
    lat = np.arctan2(
        z + GRS80.FFACT * GRS80.AP * np.sin(theta) ** 3,
        p - GRS80.FFACT * GRS80.AE * np.cos(theta) ** 3
    )
    
    # 曲率半径
    # Equation - Condition: No 3.10
    # # Radius of Curvature := a / sqrt(1 - (2 - f) f sin²φ)
    N = GRS80.AE / np.sqrt(1.0 - (2.0 - GRS80.FLAT) * GRS80.FLAT * np.sin(lat) ** 2)
    
    # 高度の計算
    # 緯度が極に近い場合と赤道に近い場合で計算方法を分ける
    # Equation - Condition: No 3.11
    # # Height := (p / cosφ - N) or (z / sinφ - N(1 - (2 - f)f))
    height = np.where(
        np.abs(lat) < np.pi / 4,
        p / np.cos(lat) - N,
        z / np.sin(lat) - N * (1.0 - (2.0 - GRS80.FLAT) * GRS80.FLAT)
    )
    
    return lat, lon, height


class Geocode(object):
    """
    SAR/InSAR geocoding workflow.

    This class manages DEM loading/creation and provides utilities to map
    radar-domain data onto geographic coordinates using range-Doppler geometry.
    """

    def __init__(
        self,
        sar,
        dem_path: str=None,
        dem_bounds: Tuple[float, float, float, float]=None,
        dem_shape: Tuple[int, int]=None,
        dem_transform: rasterio.Affine=None,
        dem_crs: Union[str, rasterio.crs.CRS]="EPSG:4326",
        buffer_sample: int=0,
        look_direction: str="R",
    ):
        """
        Initialize the geocoding helper with SAR metadata and DEM settings.

        Parameters
        ----------
        sar : object
            SAR reader instance with geometry attributes (orbit, slant range, etc.).
        dem_path : str, optional
            Path to an existing DEM GeoTIFF. If not provided, an empty DEM is created.
        dem_bounds : tuple of float, optional
            DEM bounds as (min_lon, min_lat, max_lon, max_lat) in degrees.
        dem_shape : tuple of int, optional
            DEM shape as (height, width) in pixels.
        dem_transform : rasterio.Affine, optional
            Raster transform for DEM creation.
        dem_crs : str or rasterio.crs.CRS, optional
            Coordinate reference system for the DEM.
        buffer_sample : int, optional
            Margin in radar samples to include when cropping for registration.
        look_direction : str, optional
            Look direction ("R" or "L") used for range-Doppler back-geocoding.
        """
        self.sar = sar
        self.dem_path = dem_path
        self.dem_bounds = dem_bounds
        self.dem_shape = dem_shape
        self.dem_transform = dem_transform
        self.dem_crs = dem_crs
        self.buffer_sample = buffer_sample
        self.look_direction = look_direction

        self.dem, self.transform, self.crs, self.bounds = self._load_or_create_dem()
        self.dem_height, self.dem_width = self.dem.shape

        (
            self.xyz_dem,
            self.idx_azimuth,
            self.idx_range,
            self.idx_invalid,
        ) = self._compute_dem_geometry()
        self.scene_corners = self._compute_scene_corners(look_direction=self.look_direction)

    def _load_or_create_dem(self):
        """
        Load a DEM from disk or create an empty DEM grid.

        Returns
        -------
        dem : np.ndarray
            DEM height array in meters.
        transform : rasterio.Affine
            Affine transform for the DEM grid.
        crs : rasterio.crs.CRS or str
            Coordinate reference system for the DEM.
        bounds : rasterio.coords.BoundingBox
            Bounding box of the DEM.

        Raises
        ------
        ValueError
            If required DEM metadata is missing when `dem_path` is not provided.
        """
        if self.dem_path:
            with rasterio.open(self.dem_path) as src:
                dem = src.read(1)
                transform = src.transform
                crs = src.crs
                bounds = src.bounds
            return dem, transform, crs, bounds

        if self.dem_transform is None:
            if self.dem_bounds is None or self.dem_shape is None:
                raise ValueError("dem_bounds and dem_shape are required when dem_path is not provided")
            transform = from_bounds(
                self.dem_bounds[0],
                self.dem_bounds[1],
                self.dem_bounds[2],
                self.dem_bounds[3],
                self.dem_shape[1],
                self.dem_shape[0],
            )
        else:
            transform = self.dem_transform

        if self.dem_shape is None:
            raise ValueError("dem_shape is required when dem_path is not provided")

        dem = np.zeros(self.dem_shape, dtype=np.float32)
        bounds = rasterio.transform.array_bounds(self.dem_shape[0], self.dem_shape[1], transform)
        return dem, transform, self.dem_crs, rasterio.coords.BoundingBox(*bounds)

    def _compute_dem_geometry(self):
        """
        Compute DEM geometry and radar index mappings.

        Returns
        -------
        xyz_dem : np.ndarray
            DEM points in ECEF coordinates with shape (H, W, 3).
        idx_azimuth : np.ndarray
            Azimuth indices for each DEM pixel.
        idx_range : np.ndarray
            Range indices for each DEM pixel.
        idx_invalid : np.ndarray
            Boolean mask of invalid indices.
        """
        # Equation - Condition: No 3.12
        # # DEM Grid  := (i * a + c, j * e + f)
        # where (i, j) are pixel indices (GeoTIFF Raster Matrix convention)
        # i.e. center of pixel: (i + 0.5, j + 0.5)
        dem_x = np.arange(self.dem_width) * self.transform.a + self.transform.c + self.transform.a / 2
        dem_y = np.arange(self.dem_height) * self.transform.e + self.transform.f + self.transform.e / 2
        dem_lon, dem_lat = np.meshgrid(dem_x, dem_y)

        # Equation - Condition: No 3.13
        # # Radian Conversion := deg * π / 180
        dem_lat_rad = np.radians(dem_lat)
        dem_lon_rad = np.radians(dem_lon)
        xyz_dem, _ = geoxyz(dem_lat_rad, dem_lon_rad, self.dem)

        idx_azimuth = np.zeros((self.dem_height, self.dem_width), dtype=np.int32)
        idx_range = np.zeros((self.dem_height, self.dem_width), dtype=np.int32)
        sat_pos = np.stack((self.sar.P_X_SAT, self.sar.P_Y_SAT, self.sar.P_Z_SAT), axis=1)
        sat_vel = np.stack((self.sar.V_X_SAT, self.sar.V_Y_SAT, self.sar.V_Z_SAT), axis=1)
        sat_vel_t = sat_vel.T
        sat_pos_dot_vel = np.sum(sat_pos * sat_vel, axis=1)
        slant_range = self.sar.SLANT_RANGE_SAMPLE
        slant_sorted = np.all(np.diff(slant_range) > 0)

        for idx_lat in tqdm(
            range(self.dem_height),
            desc="DEM Processing Zero Doppler Search Step...",
            total=self.dem_height,
        ):
            dem_xyz_lat = xyz_dem[idx_lat]
            # Equation - Condition: No 3.14
            # # Zero-Doppler Residual := (Position Observation · Velocity Satellite) - (Position Satellite · Velocity Satellite)
            dot_product = dem_xyz_lat @ sat_vel_t - sat_pos_dot_vel[None,:]
            idx_closest = np.argmin(np.abs(dot_product), axis=1)
            idx_azimuth[idx_lat,:] = idx_closest

            sat_pos_closest = sat_pos[idx_closest]
            diff = dem_xyz_lat - sat_pos_closest
            # Equation - Condition: No 3.15
            # # Slant Range := sqrt((Position Observation - Position Satellite)²)
            dis_earth_satellite = np.sqrt(np.sum(diff * diff, axis=1))

            if slant_sorted:
                idx_slant_range = np.searchsorted(slant_range, dis_earth_satellite, side="left")
                idx_slant_range = np.clip(idx_slant_range, 1, slant_range.size - 1)
                left = slant_range[idx_slant_range - 1]
                right = slant_range[idx_slant_range]
                use_left = dis_earth_satellite - left <= right - dis_earth_satellite
                idx_slant_range = np.where(use_left, idx_slant_range - 1, idx_slant_range)
            else:
                idx_slant_range = np.argmin(
                    np.abs(slant_range[None,:] - dis_earth_satellite[:, None]),
                    axis=1,
                )
            idx_range[idx_lat,:] = idx_slant_range

        idx_invalid_azimuth = (idx_azimuth == 0) | (idx_azimuth == self.sar.NUM_APERTURE_SAMPLE - 1)
        idx_invalid_range = (idx_range == 0) | (idx_range == self.sar.NUM_PIXEL - 1)
        idx_invalid = idx_invalid_azimuth | idx_invalid_range

        return xyz_dem, idx_azimuth, idx_range, idx_invalid

    def _range_doppler_back_geocode(
        self,
        sat_pos: np.ndarray,
        sat_vel: np.ndarray,
        slant_range: float,
        max_iter: int=50,
        tol: float=1e-6,
        look_direction: str="R",
    ) -> Tuple[float, float]:
        """
        Solve range-Doppler equations to obtain ground coordinates.

        Parameters
        ----------
        sat_pos : np.ndarray
            Satellite position (ECEF) as a length-3 vector.
        sat_vel : np.ndarray
            Satellite velocity (ECEF) as a length-3 vector.
        slant_range : float
            Slant range distance in meters.
        max_iter : int, optional
            Maximum number of Newton iterations.
        tol : float, optional
            Convergence tolerance for the Newton solver.
        look_direction : str, optional
            Look direction ("R" or "L") used to select the cross-track direction.

        Returns
        -------
        lat : float
            Geodetic latitude in degrees.
        lon : float
            Geodetic longitude in degrees.
        """
        # Range-Doppler Newton solve on ECEF (zero Doppler).
        p = sat_pos.astype(np.float64).reshape(3)
        v = sat_vel.astype(np.float64).reshape(3)
        r = float(slant_range)

        def initial_guess():
            """
            Compute an initial ECEF position for the Newton solver.

            Returns
            -------
            np.ndarray
                Initial ECEF coordinates on the reference ellipsoid.
            """
            p_norm = np.linalg.norm(p)
            v_norm = np.linalg.norm(v)
            if p_norm == 0.0 or v_norm == 0.0:
                raise ValueError("Satellite position/velocity norm is zero.")
            # Equation - Condition: No 3.
            # # Unit Vectors := e_r = -p/|p|, e_v = v/|v|, e_c = e_v × e_r
            e_r = -p / p_norm
            e_v = v / v_norm
            e_c = np.cross(e_v, e_r)
            c_norm = np.linalg.norm(e_c)
            if c_norm == 0.0:
                e_c = np.array([0.0, 0.0, 1.0], dtype=np.float64)
            else:
                e_c = e_c / c_norm
            if look_direction.lower().startswith("l"):
                e_c = -e_c
            # Equation - Condition: No 3.
            # # Slant Direction := e_s = e_c × e_v
            e_s = np.cross(e_c, e_v)
            e_s = e_s / np.linalg.norm(e_s)
            # Equation - Condition: No 3.
            # # Initial Position := x_g = p + r * e_s
            xg = p + r * e_s
            a = GRS80.AE
            b = GRS80.AP
            denom = (xg[0] ** 2 + xg[1] ** 2) / (a * a) + (xg[2] ** 2) / (b * b)
            # Equation - Condition: No 3.
            # # Ellipsoid Scale := k = 1 / sqrt((x²+y²)/a² + z²/b²)
            k = 1.0 / np.sqrt(denom)
            return k * xg

        x = initial_guess()
        a = GRS80.AE
        b = GRS80.AP

        for _ in range(max_iter):
            d = x - p
            rho = np.linalg.norm(d)
            if rho == 0.0:
                break

            # Equation - Condition: No 3.
            # # Range-Doppler System := [v·d, |d|² - r², x²/a² + y²/a² + z²/b² - 1]
            e1 = np.dot(v, d)
            e2 = np.dot(d, d) - r * r
            e3 = (x[0] ** 2 + x[1] ** 2) / (a * a) + (x[2] ** 2) / (b * b) - 1.0
            f = np.array([e1, e2, e3], dtype=np.float64)

            if np.linalg.norm(f) < tol:
                break

            j = np.array(
                [
                    [v[0], v[1], v[2]],
                    [2.0 * d[0], 2.0 * d[1], 2.0 * d[2]],
                    [2.0 * x[0] / (a * a), 2.0 * x[1] / (a * a), 2.0 * x[2] / (b * b)],
                ],
                dtype=np.float64,
            )
            try:
                dx = np.linalg.solve(j, f)
            except np.linalg.LinAlgError:
                break

            if np.linalg.norm(dx) > 1e6:
                x = x - 0.3 * dx
            else:
                x = x - dx

            if np.linalg.norm(dx) < tol:
                break

        lat, lon, _ = xyz2geo(x)
        return float(np.degrees(lat)), float(np.degrees(lon))

    def _compute_scene_corners(self, max_iter: int=1000, look_direction: str="R"):
        """
        Compute scene footprint corners via range-Doppler back-geocoding.

        Parameters
        ----------
        max_iter : int, optional
            Maximum iterations for the solver.
        look_direction : str, optional
            Look direction ("R" or "L").

        Returns
        -------
        list[tuple[float, float]]
            Corner coordinates as (lat, lon) in degrees.
        """
        az_indices = [0, 0, self.sar.NUM_APERTURE_SAMPLE - 1, self.sar.NUM_APERTURE_SAMPLE - 1]
        near_idx = int(np.argmin(self.sar.SLANT_RANGE_SAMPLE))
        far_idx = int(np.argmax(self.sar.SLANT_RANGE_SAMPLE))
        rg_indices = [near_idx, far_idx, far_idx, near_idx]

        corners = []
        for az_idx, rg_idx in zip(az_indices, rg_indices):
            sat_pos = np.array(
                [self.sar.P_X_SAT[az_idx], self.sar.P_Y_SAT[az_idx], self.sar.P_Z_SAT[az_idx]],
                dtype=np.float64,
            )
            sat_vel = np.array(
                [self.sar.V_X_SAT[az_idx], self.sar.V_Y_SAT[az_idx], self.sar.V_Z_SAT[az_idx]],
                dtype=np.float64,
            )
            slant_range = float(self.sar.SLANT_RANGE_SAMPLE[rg_idx])
            lat, lon = self._range_doppler_back_geocode(
                sat_pos,
                sat_vel,
                slant_range,
                max_iter=max_iter,
                look_direction=look_direction,
            )
            corners.append((lat, lon))

        return corners

    def save_scene_kml(
        self,
        output_kml_path: str,
        max_iter: int=1000,
        look_direction: str=None,
        include_overlay: bool=True,
        overlay_size: int=1024,
    ):
        """
        Save a scene footprint KML for the current SAR acquisition.

        Parameters
        ----------
        output_kml_path : str
            Output path for the KML file.
        max_iter : int, optional
            Maximum iterations for range-Doppler solver.
        look_direction : str, optional
            Look direction ("R" or "L"). If None, uses the class default.
        include_overlay : bool, optional
            Whether to include an intensity overlay.
        overlay_size : int, optional
            Size of the overlay image (pixels).

        Returns
        -------
        list[tuple[float, float]]
            Scene corners as (lat, lon) in degrees.
        """
        return utils.save_scene_kml(
            self,
            output_kml_path,
            max_iter=max_iter,
            look_direction=look_direction,
            include_overlay=include_overlay,
            overlay_size=overlay_size,
            xyz2geo_func=xyz2geo,
        )

    # def save_intensity_geotiff_from_bounds(self, output_path: str, size: int = 2048):
    #     return utils.save_intensity_geotiff_from_bounds(self, output_path, size=size)

    @staticmethod
    def _fill_nan_values_simple(data, fill_value=0.0):
        """
        Replace NaN values with a constant fill value.

        Parameters
        ----------
        data : np.ndarray
            Input array possibly containing NaNs.
        fill_value : float, optional
            Value to replace NaNs with.

        Returns
        -------
        np.ndarray
            Array with NaNs replaced.
        """
        mask = np.isnan(data)
        if not np.any(mask):
            return data
        data[mask] = fill_value
        return data

    @staticmethod
    def _simple_interpolation(dem_sparse, valid_mask, height, width):
        """
        Fill sparse DEM data using nearest-neighbor interpolation.

        Parameters
        ----------
        dem_sparse : np.ndarray
            Sparse DEM in radar coordinates.
        valid_mask : np.ndarray
            Boolean mask of valid samples.
        height : int
            Output height.
        width : int
            Output width.

        Returns
        -------
        np.ndarray
            Interpolated DEM array.
        """
        valid_points = np.column_stack(np.where(valid_mask))
        valid_values = dem_sparse[valid_mask]
        if len(valid_values) == 0:
            return dem_sparse
        interp = NearestNDInterpolator(valid_points, valid_values)
        grid_y, grid_x = np.meshgrid(np.arange(height), np.arange(width), indexing="ij")
        return interp(grid_y, grid_x)

    @classmethod
    def _interpolate_with_spline_fixed(cls, dem_sparse, valid_mask, height, width):
        """
        Interpolate DEM data using a coarse spline, with fallback interpolation.

        Parameters
        ----------
        dem_sparse : np.ndarray
            Sparse DEM in radar coordinates.
        valid_mask : np.ndarray
            Boolean mask of valid samples.
        height : int
            Output height.
        width : int
            Output width.

        Returns
        -------
        np.ndarray
            Interpolated DEM array.
        """
        valid_points = np.where(valid_mask)
        valid_values = dem_sparse[valid_mask].astype(np.float32)
        if len(valid_values) == 0:
            return dem_sparse

        coarse_factor = 8
        coarse_height = max(4, height // coarse_factor)
        coarse_width = max(4, width // coarse_factor)

        azimuth_coarse = np.linspace(0, height - 1, coarse_height)
        range_coarse = np.linspace(0, width - 1, coarse_width)
        azimuth_grid, range_grid = np.meshgrid(azimuth_coarse, range_coarse, indexing="ij")

        points = np.column_stack((valid_points[0], valid_points[1]))
        grid_points = np.column_stack((azimuth_grid.ravel(), range_grid.ravel()))

        coarse_dem_flat = griddata(
            points,
            valid_values,
            grid_points,
            method="cubic",
            fill_value=np.nanmean(valid_values),
        )
        
        del valid_points, points, grid_points, azimuth_grid, range_grid
        gc.collect()
        
        coarse_dem = coarse_dem_flat.reshape(coarse_height, coarse_width)
        coarse_dem = cls._fill_nan_values_simple(coarse_dem, np.nanmean(valid_values))
        coarse_dem_smooth = gaussian_filter(coarse_dem, sigma=1.0)
        
        del coarse_dem_flat, coarse_dem, valid_values
        gc.collect()

        try:
            kx = min(3, coarse_height - 1)
            ky = min(3, coarse_width - 1)
            interp_func = RectBivariateSpline(
                azimuth_coarse, range_coarse, coarse_dem_smooth, kx=kx, ky=ky, s=0
            )
            azimuth_full = np.arange(height)
            range_full = np.arange(width)
            dem_interpolated = interp_func(azimuth_full, range_full)
            
            del interp_func, azimuth_full, range_full, coarse_dem_smooth, azimuth_coarse, range_coarse
            gc.collect()
            
        except Exception:
            dem_interpolated = cls._simple_interpolation(dem_sparse, valid_mask, height, width)

        return dem_interpolated

    @classmethod
    def _geocode_dem_to_radar_smooth(
        cls,
        dem,
        idx_azimuth,
        idx_range,
        num_aperture_sample,
        num_pixel,
    ):
        """
        Map DEM into radar coordinates and fill gaps smoothly.

        Parameters
        ----------
        dem : np.ndarray
            DEM in geographic grid.
        idx_azimuth : np.ndarray
            Azimuth index map.
        idx_range : np.ndarray
            Range index map.
        num_aperture_sample : int
            Number of azimuth samples.
        num_pixel : int
            Number of range pixels.

        Returns
        -------
        dem_radar_smooth : np.ndarray
            DEM resampled to radar coordinates.
        valid_mask : np.ndarray
            Boolean mask of valid samples.
        """
        dem_height, dem_width = dem.shape
        dem_radar_coordinate = np.zeros((num_aperture_sample, num_pixel), dtype=np.float32)
        valid_mask = np.zeros((num_aperture_sample, num_pixel), dtype=bool)

        for idx_lat in tqdm(range(dem_height), total=dem_height, desc="Mapping DEM to Radar"):
            idx_azimuth_lat = idx_azimuth[idx_lat,:]
            idx_range_lat = idx_range[idx_lat,:]

            valid_idx = (
                (idx_azimuth_lat >= 0)
                & (idx_azimuth_lat < num_aperture_sample)
                & (idx_range_lat >= 0)
                & (idx_range_lat < num_pixel)
            )

            if np.any(valid_idx):
                valid_azimuth = idx_azimuth_lat[valid_idx]
                valid_range = idx_range_lat[valid_idx]
                valid_dem = dem[idx_lat, valid_idx]
                dem_radar_coordinate[valid_azimuth, valid_range] = valid_dem
                valid_mask[valid_azimuth, valid_range] = True

        if not np.any(valid_mask):
            raise ValueError("No overlap between radar coordinates and DEM")

        gc.collect()
        
        dem_radar_smooth = cls._interpolate_with_spline_fixed(
            dem_radar_coordinate, valid_mask, num_aperture_sample, num_pixel
        )
        
        del dem_radar_coordinate
        gc.collect()

        return dem_radar_smooth, valid_mask

    @staticmethod
    def _correlation_vectorized(clx_m, clx_s, window_size, mean_m_squared=None):
        """
        Compute normalized correlation between two complex arrays.

        Parameters
        ----------
        clx_m : np.ndarray
            Main complex image.
        clx_s : np.ndarray
            Secondary complex image.
        window_size : int
            Window size for local averaging.
        mean_m_squared : np.ndarray, optional
            Precomputed local mean of |clx_m|^2 for reuse.

        Returns
        -------
        np.ndarray
            Correlation (coherence-like) map.
        """
        ifg = clx_m * clx_s
        mean_ifg = uniform_filter(ifg, size=window_size, mode="constant")
        if mean_m_squared is None:
            mean_m_squared = uniform_filter(np.abs(clx_m) ** 2, size=window_size, mode="constant")
        mean_s_squared = uniform_filter(np.abs(clx_s) ** 2, size=window_size, mode="constant")
        denominator = np.sqrt(mean_m_squared * mean_s_squared)

        coherence = np.zeros_like(denominator, dtype=np.float32)
        valid_mask = denominator > 1e-10
        # Equation - Condition: No 3.16
        # # Correlation := |<M * S>| / sqrt(<|M|²> * <|S|²>)
        coherence[valid_mask] = np.abs(mean_ifg[valid_mask]) / denominator[valid_mask]
        return coherence

    @classmethod
    def _coregistration_fine_correlation_vectorized(
        cls,
        clx_m,
        clx_s,
        window_size=32,
        shift_range_min=-5,
        shift_range_max=5,
        stride=8,
    ):
        """
        Estimate fine coregistration shifts by maximizing correlation.

        Parameters
        ----------
        clx_m : np.ndarray
            Main complex image.
        clx_s : np.ndarray
            Secondary complex image to be shifted.
        window_size : int, optional
            Window size for correlation computation.
        shift_range_min : int, optional
            Minimum shift to test (pixels).
        shift_range_max : int, optional
            Maximum shift to test (pixels).
        stride : int, optional
            Sampling stride for sparse shift estimation.

        Returns
        -------
        clx_s_reg : np.ndarray
            Coregistered secondary image.
        coh_best : np.ndarray
            Best correlation map.
        shift_map : tuple[np.ndarray, np.ndarray]
            (azimuth_shift_map, range_shift_map).
        """
        height, width = clx_m.shape
        clx_s = clx_s[:height,:width]

        shifts = np.arange(shift_range_min, shift_range_max + 1)
        h_points = np.arange(0, height, stride)
        w_points = np.arange(0, width, stride)

        h_shift_sparse = np.zeros((len(h_points), len(w_points)), dtype=np.float32)
        w_shift_sparse = np.zeros((len(h_points), len(w_points)), dtype=np.float32)
        coh_best_sparse = np.zeros((len(h_points), len(w_points)), dtype=np.float32)
        clx_s_shifted = np.zeros_like(clx_s)
        mean_m_squared = uniform_filter(np.abs(clx_m) ** 2, size=window_size, mode="constant")

        with tqdm(total=len(shifts) ** 2, desc="Computing for shifts") as pbar:
            for h_shift in shifts:
                for w_shift in shifts:
                    clx_s_shifted.fill(0)
                    src_h_start = max(0, -h_shift)
                    src_h_end = min(height, height - h_shift)
                    src_w_start = max(0, -w_shift)
                    src_w_end = min(width, width - w_shift)

                    dst_h_start = max(0, h_shift)
                    dst_h_end = min(height, height + h_shift)
                    dst_w_start = max(0, w_shift)
                    dst_w_end = min(width, width + w_shift)

                    clx_s_shifted[dst_h_start:dst_h_end, dst_w_start:dst_w_end] = clx_s[
                        src_h_start:src_h_end, src_w_start:src_w_end
                    ]

                    correlation_map = cls._correlation_vectorized(
                        clx_m, clx_s_shifted, window_size, mean_m_squared=mean_m_squared
                    )
                    correlation_points = correlation_map[np.ix_(h_points, w_points)]
                    update_mask = correlation_points > coh_best_sparse
                    if np.any(update_mask):
                        coh_best_sparse[update_mask] = correlation_points[update_mask]
                        h_shift_sparse[update_mask] = h_shift
                        w_shift_sparse[update_mask] = w_shift

                    pbar.update(1)

        h_interp = RectBivariateSpline(h_points, w_points, h_shift_sparse, kx=1, ky=1)
        w_interp = RectBivariateSpline(h_points, w_points, w_shift_sparse, kx=1, ky=1)
        coh_interp = RectBivariateSpline(h_points, w_points, coh_best_sparse, kx=1, ky=1)

        h_full = np.arange(height)
        w_full = np.arange(width)
        h_shift_map = np.round(h_interp(h_full, w_full)).astype(np.int32)
        w_shift_map = np.round(w_interp(h_full, w_full)).astype(np.int32)
        coh_best = coh_interp(h_full, w_full)

        clx_s_reg = cls._apply_shift_map(clx_s, h_shift_map, w_shift_map)

        return clx_s_reg, coh_best, (h_shift_map, w_shift_map)

    @staticmethod
    def _apply_shift_map(image, h_shift_map, w_shift_map):
        """
        Apply per-pixel shifts to an image.

        Parameters
        ----------
        image : np.ndarray
            Input image.
        h_shift_map : np.ndarray
            Per-pixel shift in the vertical direction.
        w_shift_map : np.ndarray
            Per-pixel shift in the horizontal direction.

        Returns
        -------
        np.ndarray
            Shifted image.
        """
        height, width = image.shape
        shifted_image = np.zeros_like(image)
        h_indices, w_indices = np.meshgrid(np.arange(height), np.arange(width), indexing="ij")

        h_shifted = h_indices - h_shift_map
        w_shifted = w_indices - w_shift_map

        valid_mask = (
            (h_shifted >= 0) & (h_shifted < height) & (w_shifted >= 0) & (w_shifted < width)
        )

        h_valid = h_shifted[valid_mask].astype(np.int32)
        w_valid = w_shifted[valid_mask].astype(np.int32)
        shifted_image[valid_mask] = image[h_valid, w_valid]
        return shifted_image

    def _geocode_radar_to_geo(
        self,
        radar_image,
        top_az,
        left_rg,
        po_shift_azimuth,
        po_shift_range,
        use_count=True,
    ):
        """
        Map a radar image to geographic grid using precomputed indices.

        Parameters
        ----------
        radar_image : np.ndarray
            Radar-domain image to geocode.
        top_az : int
            Top azimuth index for cropping.
        left_rg : int
            Left range index for cropping.
        po_shift_azimuth : float
            Azimuth shift to apply before mapping.
        po_shift_range : float
            Range shift to apply before mapping.
        use_count : bool, optional
            Whether to average overlapping samples.

        Returns
        -------
        np.ndarray
            Geocoded image in DEM grid coordinates.
        """
        geocode = np.zeros((self.dem_height, self.dem_width), dtype=radar_image.dtype)
        count = np.zeros((self.dem_height, self.dem_width), dtype=np.int32)
        one = np.ones_like(radar_image, dtype=np.int32)

        shift_az = int(round(po_shift_azimuth))
        shift_rg = int(round(po_shift_range))

        for idx_lat in tqdm(range(self.dem_height), total=self.dem_height, desc="Geocoding"):
            idx_azimuth_lat = self.idx_azimuth[idx_lat,:]
            idx_range_lat = self.idx_range[idx_lat,:]

            idx_azimuth_lat = np.clip(
                idx_azimuth_lat - top_az - shift_az, 0, radar_image.shape[0] - 1
            )
            idx_range_lat = np.clip(
                idx_range_lat - left_rg - shift_rg, 0, radar_image.shape[1] - 1
            )

            geocode[idx_lat,:] += radar_image[idx_azimuth_lat, idx_range_lat]
            if use_count:
                count[idx_lat,:] += one[idx_azimuth_lat, idx_range_lat]

        if use_count:
            valid = count > 0
            geocode[valid] /= count[valid]

        geocode[self.idx_invalid] = np.nan
        return geocode

    @staticmethod
    def _save_geotiff(path, data, crs, transform):
        """
        Save a single-band GeoTIFF with basic geokeys.

        Parameters
        ----------
        path : str
            Output file path.
        data : np.ndarray
            2D array to write.
        crs : rasterio.crs.CRS or str
            Coordinate reference system.
        transform : rasterio.Affine
            Affine transform for the raster.
        """
        geokey_tags = Geocode._build_geokey_tags(crs)
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=data.shape[0],
            width=data.shape[1],
            count=1,
            dtype=data.dtype,
            crs=crs,
            transform=transform,
            nodata=np.nan,
        ) as dst:
            dst.write(data, 1)
            if geokey_tags:
                dst.update_tags(ns="GEOTIFF", **geokey_tags)

    @staticmethod
    def _save_multiband_geotiff(path, layers, crs, transform, metadata):
        """
        Save a multi-band GeoTIFF with metadata.

        Parameters
        ----------
        path : str
            Output file path.
        layers : list of dict
            Layer descriptors with keys: data, layer_name, process_name, format, scene_id.
        crs : rasterio.crs.CRS or str
            Coordinate reference system.
        transform : rasterio.Affine
            Affine transform for the raster.
        metadata : dict
            Global metadata to store as tags.

        Raises
        ------
        ValueError
            If no layers are provided.
        """
        count = len(layers)
        if count == 0:
            raise ValueError("No layers provided for GeoTIFF output")
        dtype = layers[0]["data"].dtype
        height, width = layers[0]["data"].shape
        geokey_tags = Geocode._build_geokey_tags(crs)
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=height,
            width=width,
            count=count,
            dtype=dtype,
            crs=crs,
            transform=transform,
            nodata=np.nan,
        ) as dst:
            for idx, layer in enumerate(layers, start=1):
                dst.write(layer["data"], idx)
                dst.set_band_description(idx, layer["layer_name"])
                dst.update_tags(
                    idx,
                    layer_name=layer["layer_name"],
                    process_name=layer["process_name"],
                    format=layer["format"],
                    scene_id=layer["scene_id"],
                )
            for key in sorted(metadata.keys()):
                value = metadata[key]
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=True)
                else:
                    value = str(value)
                dst.update_tags(**{key: value})
            if geokey_tags:
                dst.update_tags(ns="GEOTIFF", **geokey_tags)

    @staticmethod
    def _save_jpg(path, data):
        """
        Save a normalized grayscale JPEG representation of data.

        Parameters
        ----------
        path : str
            Output JPEG path.
        data : np.ndarray
            Input data array.
        """
        finite = np.isfinite(data)
        if not np.any(finite):
            norm = np.zeros(data.shape, dtype=np.uint8)
        else:
            values = data[finite]
            vmin = np.nanpercentile(values, 2)
            vmax = np.nanpercentile(values, 98)
            if np.isclose(vmax, vmin):
                vmax = vmin + 1.0
            norm = (data - vmin) / (vmax - vmin)
            norm = np.clip(norm, 0.0, 1.0)
            norm[~finite] = 0.0
            norm = (norm * 255.0).astype(np.uint8)

        cv2.imwrite(path, norm)

    @staticmethod
    def _build_geokey_tags(crs):
        """
        Build GeoTIFF key tags from a CRS.

        Parameters
        ----------
        crs : rasterio.crs.CRS or str
            CRS to convert into GeoTIFF tags.

        Returns
        -------
        dict
            GeoTIFF key tags, or empty dict if CRS is invalid.
        """
        if crs is None:
            return {}
        try:
            crs_obj = rasterio.crs.CRS.from_user_input(crs)
        except Exception:
            return {}
        epsg = crs_obj.to_epsg()
        if epsg is None:
            return {}
        return {
            "GTModelTypeGeoKey": "2",
            "GTRasterTypeGeoKey": "1",
            "GeographicTypeGeoKey": str(epsg),
        }

    def geocode(
        self,
        signal: np.ndarray,
        phase: np.ndarray=None,
        output_intensity_path: str=None,
        output_phase_path: str=None,
        register: bool=True,
    ):
        """
        Geocode radar-domain data to the DEM grid.

        Parameters
        ----------
        signal : np.ndarray
            Complex SAR image in radar coordinates.
        phase : np.ndarray, optional
            Optional phase or complex data to geocode alongside intensity.
        output_intensity_path : str, optional
            Output GeoTIFF path for intensity products.
        output_phase_path : str, optional
            Output GeoTIFF path for phase products.
        register : bool, optional
            Whether to perform DEM-to-image registration before geocoding.

        Returns
        -------
        dict
            Dictionary of geocoded products and registration outputs.

        Raises
        ------
        ValueError
            If the input signal is smaller than the SAR geometry.
        """
        if signal.shape[0] < self.sar.NUM_APERTURE_SAMPLE or signal.shape[1] < self.sar.NUM_PIXEL:
            raise ValueError("signal shape is smaller than SAR geometry")

        scene_id = getattr(self.sar, "PATH_CEOS_FOLDER", "unknown")
        scene_id = os.path.basename(scene_id)

        dem_radar_smooth, _ = self._geocode_dem_to_radar_smooth(
            self.dem,
            self.idx_azimuth,
            self.idx_range,
            self.sar.NUM_APERTURE_SAMPLE,
            self.sar.NUM_PIXEL,
        )
        
        del _
        gc.collect()

        idx_az_min = int(np.min(self.idx_azimuth))
        idx_az_max = int(np.max(self.idx_azimuth))
        idx_rg_min = int(np.min(self.idx_range))
        idx_rg_max = int(np.max(self.idx_range))

        top_az = max(idx_az_min - self.buffer_sample, 0)
        bot_az = min(idx_az_max + self.buffer_sample, dem_radar_smooth.shape[0])
        left_rg = max(idx_rg_min - self.buffer_sample, 0)
        right_rg = min(idx_rg_max + self.buffer_sample, dem_radar_smooth.shape[1])

        if top_az >= bot_az or left_rg >= right_rg:
            raise ValueError("No overlap between radar coordinates and DEM after cropping")

        dem_radar_smooth_cropped = dem_radar_smooth[top_az:bot_az, left_rg:right_rg]
        
        del dem_radar_smooth
        gc.collect()

        po_shift_dem_range = 0.0
        po_shift_dem_azimuth = 0.0
        fine_shift_map = None
        if register:
            dem_gradient_range = np.zeros_like(dem_radar_smooth_cropped, dtype=np.float32)
            # Equation - Condition: No 3.17 from No 1.19
            # # Range Gradient := DEM(x+1) - DEM(x-1)
            dem_gradient_range[:, 1:-1] = dem_radar_smooth_cropped[:, 2:] - dem_radar_smooth_cropped[:,:-2]

            # Equation - Condition: No 3.18 from No 1.17
            # # Intensity (dB) := 20 log10(|S|) - 10
            intensity_db = 20 * np.log10(np.clip(np.abs(signal), a_min=1e-10, a_max=None)) - 10
            intensity_crop = intensity_db[top_az:bot_az, left_rg:right_rg]

            difference, _ = cv2.phaseCorrelate(dem_gradient_range, intensity_crop)
            po_shift_dem_range, po_shift_dem_azimuth = difference

            intensity_coarse_reg = shift(
                intensity_crop,
                shift=(po_shift_dem_azimuth, po_shift_dem_range),
                mode="nearest",
            )

            _, _, fine_shift_map = self._coregistration_fine_correlation_vectorized(
                dem_gradient_range,
                intensity_coarse_reg,
                window_size=128,
                shift_range_min=-1,
                shift_range_max=1,
                stride=2,
            )
        else:
            dem_gradient_range = np.zeros_like(dem_radar_smooth_cropped, dtype=np.float32)
            # Equation - Condition: No 3.19 from No 1.19
            # # Range Gradient := DEM(x+1) - DEM(x-1)
            dem_gradient_range[:, 1:-1] = dem_radar_smooth_cropped[:, 2:] - dem_radar_smooth_cropped[:,:-2]
            fine_shift_map = (
                np.zeros_like(dem_radar_smooth_cropped, dtype=np.float32),
                np.zeros_like(dem_radar_smooth_cropped, dtype=np.float32),
            )
            
        del intensity_coarse_reg
        gc.collect()

        intensity = np.abs(signal)[top_az:bot_az, left_rg:right_rg]
        if register:
            intensity = shift(
                intensity,
                shift=(po_shift_dem_azimuth, po_shift_dem_range),
                mode="nearest",
            )
            intensity = self._apply_shift_map(intensity, fine_shift_map[0], fine_shift_map[1])

        geocode_intensity = self._geocode_radar_to_geo(intensity, top_az, left_rg, 0.0, 0.0).astype(
            np.float32
        )

        geocode_phase = None
        if phase is not None:
            phase_crop = phase[top_az:bot_az, left_rg:right_rg]
            if register:
                phase_crop = shift(
                    phase_crop,
                    shift=(po_shift_dem_azimuth, po_shift_dem_range),
                    mode="nearest",
                )
                phase_crop = self._apply_shift_map(phase_crop, fine_shift_map[0], fine_shift_map[1])
            if np.iscomplexobj(phase_crop):
                geocode_complex = self._geocode_radar_to_geo(phase_crop, top_az, left_rg, 0.0, 0.0)
                geocode_phase = np.angle(geocode_complex).astype(np.float32)
            else:
                geocode_phase = self._geocode_radar_to_geo(phase_crop, top_az, left_rg, 0.0, 0.0).astype(
                    np.float32
                )

        geocode_shift_az = self._geocode_radar_to_geo(
            fine_shift_map[0].astype(np.float32),
            top_az,
            left_rg,
            0.0,
            0.0,
            use_count=False,
        ).astype(np.float32)
        geocode_shift_rg = self._geocode_radar_to_geo(
            fine_shift_map[1].astype(np.float32),
            top_az,
            left_rg,
            0.0,
            0.0,
            use_count=False,
        ).astype(np.float32)
        geocode_dem_gradient = self._geocode_radar_to_geo(
            dem_gradient_range,
            top_az,
            left_rg,
            0.0,
            0.0,
            use_count=False,
        ).astype(np.float32)

        registration_metadata = {
            "shift_coarse": {
                "azimuth": float(po_shift_dem_azimuth),
                "range": float(po_shift_dem_range),
            },
            "shift_fine": {
                "azimuth_shape": [int(fine_shift_map[0].shape[0]), int(fine_shift_map[0].shape[1])],
                "range_shape": [int(fine_shift_map[1].shape[0]), int(fine_shift_map[1].shape[1])],
            },
            "buffer_sample": int(self.buffer_sample),
            "crop": {
                "top_az": int(top_az),
                "bot_az": int(bot_az),
                "left_rg": int(left_rg),
                "right_rg": int(right_rg),
            },
        }

        if output_intensity_path:
            layers = [
                {
                    "data": geocode_intensity,
                    "layer_name": "geocoded_intensity",
                    "process_name": "geocode_intensity",
                    "format": str(geocode_intensity.dtype),
                    "scene_id": scene_id,
                },
                {
                    "data": geocode_shift_az,
                    "layer_name": "shift_map_azimuth",
                    "process_name": "registration_shift_azimuth",
                    "format": str(geocode_shift_az.dtype),
                    "scene_id": scene_id,
                },
                {
                    "data": geocode_shift_rg,
                    "layer_name": "shift_map_range",
                    "process_name": "registration_shift_range",
                    "format": str(geocode_shift_rg.dtype),
                    "scene_id": scene_id,
                },
                {
                    "data": geocode_dem_gradient,
                    "layer_name": "dem_gradient_range",
                    "process_name": "dem_gradient_range",
                    "format": str(geocode_dem_gradient.dtype),
                    "scene_id": scene_id,
                },
            ]
            self._save_multiband_geotiff(
                output_intensity_path, layers, self.crs, self.transform, registration_metadata
            )
            jpg_path = f"{os.path.splitext(output_intensity_path)[0]}.jpg"
            self._save_jpg(jpg_path, geocode_intensity)
        if output_phase_path and geocode_phase is not None:
            layers = [
                {
                    "data": geocode_phase,
                    "layer_name": "geocoded_phase",
                    "process_name": "geocode_phase",
                    "format": str(geocode_phase.dtype),
                    "scene_id": scene_id,
                },
                {
                    "data": geocode_shift_az,
                    "layer_name": "shift_map_azimuth",
                    "process_name": "registration_shift_azimuth",
                    "format": str(geocode_shift_az.dtype),
                    "scene_id": scene_id,
                },
                {
                    "data": geocode_shift_rg,
                    "layer_name": "shift_map_range",
                    "process_name": "registration_shift_range",
                    "format": str(geocode_shift_rg.dtype),
                    "scene_id": scene_id,
                },
                {
                    "data": geocode_dem_gradient,
                    "layer_name": "dem_gradient_range",
                    "process_name": "dem_gradient_range",
                    "format": str(geocode_dem_gradient.dtype),
                    "scene_id": scene_id,
                },
            ]
            self._save_multiband_geotiff(
                output_phase_path, layers, self.crs, self.transform, registration_metadata
            )
            jpg_path = f"{os.path.splitext(output_phase_path)[0]}.jpg"
            self._save_jpg(jpg_path, geocode_phase)

        return {
            "dem_registered": dem_radar_smooth_cropped,
            "intensity_registered": intensity,
            "phase_registered": phase_crop if phase is not None else None,
            "geocode_intensity": geocode_intensity,
            "geocode_phase": geocode_phase,
            "shift_coarse": (po_shift_dem_azimuth, po_shift_dem_range),
            "shift_fine": fine_shift_map,
        }
