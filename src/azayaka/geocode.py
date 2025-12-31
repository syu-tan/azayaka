# -*- coding: utf-8 -*-
"""
Azayaka: 
    SAR/InSAR Geocoding Module.
    This module provides functionalities for geocoding SAR/InSAR outputs data.

    Copyright (c) 2026 Syusuke Yasui, Yutaka Yamamoto, and contributors.
    Licensed under the APGL-3.0 License.

"""

import os, gc, json, time
from typing import Union, Tuple

import numpy as np
import matplotlib.pyplot as plt
from tqdm import tqdm
import rasterio
import cv2
from scipy.interpolate import (
    interp1d, RectBivariateSpline, griddata, NearestNDInterpolator, LinearNDInterpolator)
from scipy.ndimage import uniform_filter, shift, gaussian_filter, binary_dilation


class GRS80:
    """GRS80 (Geodetic Reference System 1980) 測地基準系のパラメータ"""
    AE = 6378137.0          # 赤道半径 (m)
    FLAT = 1.0 / 298.257222101 # 扁平率
    GM = 398600.436         # 地心重力定数 (km³/s²)
    OMFSQ = (1.0 - FLAT) ** 2  # (1 - f)²
    AP = AE * (1.0 - FLAT)     # 極半径 (m)
    FFACT = OMFSQ - 1.0        # 形状係数
    AM = AE * (1.0 - FLAT / 3.0 - FLAT * FLAT / 5.0)  # 平均半径
    AMSQ = AM ** 2             # 平均半径の二乗


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
    lats = np.arctan(GRS80.OMFSQ * np.tan(lat))
    
    # 楕円体上の点の地心距離
    rs = GRS80.AP / np.sqrt(1.0 + GRS80.FFACT * np.cos(lats) ** 2)
    
    # 高度を含めた実際の地心距離
    r = np.sqrt(height ** 2 + rs ** 2 + 2 * height * rs * np.cos(lat - lats))
    
    # 地心緯度の計算（高度による補正を含む）
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
    
    # 経度の計算（簡単）
    lon = np.arctan2(y, x)
    
    # XY平面での距離
    p = np.sqrt(x**2 + y**2)
    
    # Bowringの方法による緯度と高度の反復計算
    theta = np.arctan2(z * GRS80.AE, p * GRS80.AP)
    
    # 測地緯度の計算
    lat = np.arctan2(
        z + GRS80.FFACT * GRS80.AP * np.sin(theta)**3,
        p - GRS80.FFACT * GRS80.AE * np.cos(theta)**3
    )
    
    # 曲率半径
    N = GRS80.AE / np.sqrt(1.0 - (2.0 - GRS80.FLAT) * GRS80.FLAT * np.sin(lat)**2)
    
    # 高度の計算
    # 緯度が極に近い場合と赤道に近い場合で計算方法を分ける
    height = np.where(
        np.abs(lat) < np.pi/4,
        p / np.cos(lat) - N,
        z / np.sin(lat) - N * (1.0 - (2.0 - GRS80.FLAT) * GRS80.FLAT)
    )
    
    return lat, lon, height