# -*- coding: utf-8 -*-
"""
Azayaka: 
    Interferometry SAR Module.
    This module provides functionalities for SAR interferometric processing and filtering.

    Copyright (c) 2026 Syusuke Yasui, Yutaka Yamamoto, and contributors.
    Licensed under the APGL-3.0 License.

"""
import os
import gc
from typing import Dict, Tuple, Optional

import numpy as np
import cv2
import matplotlib.cm as cm
from tqdm import tqdm
from scipy.ndimage import shift, uniform_filter
from scipy.interpolate import RectBivariateSpline

from . import geocode


class Interferometry:
    """Interferometry SAR Module Class."""

    def __init__(self, main, sub):
        self.main = main
        self.sub = sub
        self._align_signals_to_main()
        self._init_baseline_geometry()

    def _align_signals_to_main(self) -> None:
        main_shape = self.main.signal.shape
        sub_shape = self.sub.signal.shape
        if main_shape != sub_shape:
            print(
                f"Warning: main/sub size mismatch. "
                f"Main: {main_shape}, Sub: {sub_shape}. "
            )
        target_shape = (
            min(main_shape[0], sub_shape[0]),
            min(main_shape[1], sub_shape[1]),
        )
        # Crop to the common area to avoid allocating padded arrays.
        self.main.signal = self.main.signal[: target_shape[0], : target_shape[1]]
        self.sub.signal = self.sub.signal[: target_shape[0], : target_shape[1]]
        print(f"Aligned main/sub signals to shape: {target_shape}")

    def _init_baseline_geometry(self) -> None:
        num_aperture_sample = min(
            int(self.main.NUM_APERTURE_SAMPLE), int(self.sub.NUM_APERTURE_SAMPLE)
        )
        self.num_aperture_sample = num_aperture_sample
        self.num_pixel = min(int(self.main.NUM_PIXEL), int(self.sub.NUM_PIXEL))

        self.baseline_xyz = np.stack(
            [
                self.sub.P_X_SAT[:num_aperture_sample] - self.main.P_X_SAT[:num_aperture_sample],
                self.sub.P_Y_SAT[:num_aperture_sample] - self.main.P_Y_SAT[:num_aperture_sample],
                self.sub.P_Z_SAT[:num_aperture_sample] - self.main.P_Z_SAT[:num_aperture_sample],
            ],
            axis=1,
        )
        self.baseline = np.sqrt(
            self.baseline_xyz[:, 0] ** 2
            + self.baseline_xyz[:, 1] ** 2
            + self.baseline_xyz[:, 2] ** 2
        )

        rho_unit_x = self.main.P_X_SAT / self.main.P_SAT
        rho_unit_y = self.main.P_Y_SAT / self.main.P_SAT
        rho_unit_z = self.main.P_Z_SAT / self.main.P_SAT

        baseline_sign = self._earth_sign(
            self.main.P_X_SAT,
            self.main.P_Y_SAT,
            self.sub.P_X_SAT[:num_aperture_sample],
            self.sub.P_Y_SAT[:num_aperture_sample],
            getattr(self.main, "ORBIT_NAME", ""),
        )
        self.baseline_vertical = (
            (self.sub.P_X_SAT[:num_aperture_sample] - self.main.P_X_SAT[:num_aperture_sample])
            * rho_unit_x[:num_aperture_sample]
            + (self.sub.P_Y_SAT[:num_aperture_sample] - self.main.P_Y_SAT[:num_aperture_sample])
            * rho_unit_y[:num_aperture_sample]
            + (self.sub.P_Z_SAT[:num_aperture_sample] - self.main.P_Z_SAT[:num_aperture_sample])
            * rho_unit_z[:num_aperture_sample]
        )
        self.baseline_horizontal = baseline_sign * np.sqrt(
            np.maximum(self.baseline**2 - self.baseline_vertical**2, 0.0)
        )

        self.baseline_offset = 0.0
        self.baseline_angle_alpha = np.arctan2(
            self.baseline_vertical + self.baseline_offset, self.baseline_horizontal
        )
        self.baseline_cos_alpha = np.cos(self.baseline_angle_alpha)
        self.baseline_sin_alpha = np.sin(self.baseline_angle_alpha)

        self.height_sat = self.main.HEIGHT_SAT[:num_aperture_sample]
        print("Initialized baseline geometry for interferometry processing.")

    @staticmethod
    def _earth_sign(x11, y11, x21, y21, orbit_name: str) -> int:
        rlnref = np.arctan2(y11, x11)
        rlnrep = np.arctan2(y21, x21)
        sign = 1
        if str(orbit_name).upper() == "D":
            sign *= -1
        if np.all(rlnrep < rlnref):
            sign *= -1
        return sign

    @staticmethod
    def _coherence_vectorized(clx_m: np.ndarray, clx_s: np.ndarray, window_size: int) -> np.ndarray:
        ifg = clx_m * np.conj(clx_s)
        mean_ifg = uniform_filter(ifg.real, size=window_size, mode="constant") + 1j * uniform_filter(
            ifg.imag, size=window_size, mode="constant"
        )
        mean_m_squared = uniform_filter(np.abs(clx_m) ** 2, size=window_size, mode="constant")
        mean_s_squared = uniform_filter(np.abs(clx_s) ** 2, size=window_size, mode="constant")
        denominator = np.sqrt(mean_m_squared * mean_s_squared)

        coherence = np.zeros_like(denominator, dtype=np.float32)
        valid_mask = denominator > 1e-10
        coherence[valid_mask] = np.abs(mean_ifg[valid_mask]) / denominator[valid_mask]
        return coherence

    @classmethod
    def _coregistration_fine_coherence_vectorized(
        cls,
        clx_m: np.ndarray,
        clx_s: np.ndarray,
        window_size: int = 4,
        shift_range_min: int = -2,
        shift_range_max: int = 2,
        stride: int = 1,
    ) -> Tuple[np.ndarray, np.ndarray, Tuple[np.ndarray, np.ndarray]]:
        height, width = clx_m.shape
        clx_s = clx_s[:height, :width]

        shifts = np.arange(shift_range_min, shift_range_max + 1)
        h_points = np.arange(0, height, stride)
        w_points = np.arange(0, width, stride)

        h_shift_sparse = np.zeros((len(h_points), len(w_points)), dtype=np.float32)
        w_shift_sparse = np.zeros((len(h_points), len(w_points)), dtype=np.float32)
        coh_best_sparse = np.zeros((len(h_points), len(w_points)), dtype=np.float32)

        with tqdm(total=len(shifts) ** 2, desc="Computing coherence shifts") as pbar:
            for h_shift in shifts:
                for w_shift in shifts:
                    clx_s_shifted = np.zeros_like(clx_s)
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

                    coherence_map = cls._coherence_vectorized(clx_m, clx_s_shifted, window_size)
                    for i, h_idx in enumerate(h_points):
                        for j, w_idx in enumerate(w_points):
                            if coherence_map[h_idx, w_idx] > coh_best_sparse[i, j]:
                                coh_best_sparse[i, j] = coherence_map[h_idx, w_idx]
                                h_shift_sparse[i, j] = h_shift
                                w_shift_sparse[i, j] = w_shift
                    pbar.update(1)

        h_interp = RectBivariateSpline(h_points, w_points, h_shift_sparse, kx=1, ky=1)
        w_interp = RectBivariateSpline(h_points, w_points, w_shift_sparse, kx=1, ky=1)
        coh_interp = RectBivariateSpline(h_points, w_points, coh_best_sparse, kx=1, ky=1)

        h_full = np.arange(height)
        w_full = np.arange(width)
        h_shift_map = h_interp(h_full, w_full).astype(np.int32)
        w_shift_map = w_interp(h_full, w_full).astype(np.int32)
        coh_best = coh_interp(h_full, w_full)

        clx_s_reg = geocode.Geocode._apply_shift_map(clx_s, h_shift_map, w_shift_map)
        return clx_s_reg, coh_best, (h_shift_map, w_shift_map)

    @staticmethod
    def _multilook_filter(image: np.ndarray, looks_azimuth: int, looks_range: int) -> np.ndarray:
        if looks_azimuth <= 1 and looks_range <= 1:
            return image
        if np.iscomplexobj(image):
            real = uniform_filter(image.real, size=(looks_azimuth, looks_range), mode="nearest")
            imag = uniform_filter(image.imag, size=(looks_azimuth, looks_range), mode="nearest")
            return real + 1j * imag
        return uniform_filter(image, size=(looks_azimuth, looks_range), mode="nearest")

    @staticmethod
    def _convolve2d(image: np.ndarray, kernel: np.ndarray) -> np.ndarray:
        shape = (
            image.shape[0] - kernel.shape[0] + 1,
            image.shape[1] - kernel.shape[1] + 1,
        ) + kernel.shape
        strides = image.strides * 2
        strided_image = np.lib.stride_tricks.as_strided(image, shape, strides)
        return np.einsum("kl,ijkl->ij", kernel, strided_image)

    @staticmethod
    def _pad_singlechannel_image(image: np.ndarray, kernel_shape: Tuple[int, int], boundary: str) -> np.ndarray:
        return np.pad(
            image,
            ((int(kernel_shape[0] / 2),), (int(kernel_shape[1] / 2),)),
            boundary,
        )

    @classmethod
    def _convolve2d_safe(cls, image: np.ndarray, kernel: np.ndarray, boundary: str = "edge") -> np.ndarray:
        pad_image = cls._pad_singlechannel_image(image, kernel.shape, boundary) if boundary else image
        return cls._convolve2d(pad_image, kernel)

    @staticmethod
    def _create_averaging_kernel(size: Tuple[int, int]) -> np.ndarray:
        return np.full(size, 1.0 / (size[0] * size[1]))

    @classmethod
    def _goldstein_filter_patch(
        cls, patch: np.ndarray, alpha: float, filter_kernel: np.ndarray
    ) -> np.ndarray:
        patch_fft = np.fft.fft2(patch)
        patch_fft = np.fft.fftshift(patch_fft)
        if alpha > 0:
            smooth = cls._convolve2d_safe(patch_fft, np.conj(filter_kernel))
            amp = np.abs(smooth) ** alpha
            patch_fft = patch_fft * amp
        patch_fft = np.fft.ifftshift(patch_fft)
        return np.fft.ifft2(patch_fft)

    @classmethod
    def _goldstein_phase_filter(
        cls,
        image: np.ndarray,
        alpha: float = 0.4,
        patch_size: int = 64,
        step: int = 8,
        filter_size: int = 3,
    ) -> np.ndarray:
        if patch_size <= 1:
            return image
        filter_kernel = cls._create_averaging_kernel((filter_size, filter_size))
        height, width = image.shape
        output = np.zeros_like(image, dtype=np.complex64)
        count = np.zeros_like(image, dtype=np.float32)

        for y in tqdm(range(0, height - patch_size + 1, step), desc="Goldstein filter"):
            for x in range(0, width - patch_size + 1, step):
                patch = image[y : y + patch_size, x : x + patch_size]
                filtered = cls._goldstein_filter_patch(patch, alpha, filter_kernel)
                output[y : y + patch_size, x : x + patch_size] += filtered
                count[y : y + patch_size, x : x + patch_size] += 1.0

        valid = count > 0
        output[valid] /= count[valid]
        output[~valid] = image[~valid]
        return output

    def _compute_topography_phase(self, dem_radar: np.ndarray) -> np.ndarray:
        dem_radar = dem_radar[: self.num_aperture_sample, : self.num_pixel]
        ret = self.main.DIS_ELLIPSOID_RADIUS + dem_radar

        grad_slant_range = np.zeros((self.num_aperture_sample, self.num_pixel), dtype=np.float32)
        slant_range = self.main.SLANT_RANGE_SAMPLE

        for idx_line in tqdm(range(self.num_aperture_sample), desc="Topography phase"):
            ret2 = ret[idx_line, :] ** 2
            c = self.sub.DIS_ELLIPSOID_RADIUS + self.height_sat[idx_line]
            c2 = c**2

            cos_height = (slant_range**2 + c2 - ret2) / (2.0 * slant_range * c)
            sin_height = np.sqrt(np.maximum(1.0 - cos_height**2, 0.0))

            topo_phase = (
                slant_range**2
                + self.baseline[idx_line] ** 2
                - 2.0
                * slant_range
                * self.baseline[idx_line]
                * (
                    sin_height * self.baseline_cos_alpha[idx_line]
                    - cos_height * self.baseline_sin_alpha[idx_line]
                )
                - self.baseline_offset**2
            )
            topo_phase = np.maximum(topo_phase, 0.0)
            grad_slant_range[idx_line, :] = -slant_range + np.sqrt(topo_phase)

        cnst = -4.0 * np.pi / self.sub.LAMBDA
        topography = np.exp(1j * cnst * grad_slant_range).astype(np.complex64)
        del grad_slant_range
        gc.collect()
        return topography

    def _compute_topography_phase_cropped(
        self, dem_radar_crop: np.ndarray, top_az: int, left_rg: int
    ) -> np.ndarray:
        crop_lines, crop_pixels = dem_radar_crop.shape
        slant_range = self.main.SLANT_RANGE_SAMPLE[left_rg : left_rg + crop_pixels]
        ret = self.main.DIS_ELLIPSOID_RADIUS + dem_radar_crop

        grad_slant_range = np.zeros((crop_lines, crop_pixels), dtype=np.float32)

        for idx_line in tqdm(range(crop_lines), desc="Topography phase (crop)"):
            az_idx = top_az + idx_line
            ret2 = ret[idx_line, :] ** 2
            c = self.sub.DIS_ELLIPSOID_RADIUS + self.height_sat[az_idx]
            c2 = c**2

            cos_height = (slant_range**2 + c2 - ret2) / (2.0 * slant_range * c)
            sin_height = np.sqrt(np.maximum(1.0 - cos_height**2, 0.0))

            topo_phase = (
                slant_range**2
                + self.baseline[az_idx] ** 2
                - 2.0
                * slant_range
                * self.baseline[az_idx]
                * (
                    sin_height * self.baseline_cos_alpha[az_idx]
                    - cos_height * self.baseline_sin_alpha[az_idx]
                )
                - self.baseline_offset**2
            )
            topo_phase = np.maximum(topo_phase, 0.0)
            grad_slant_range[idx_line, :] = -slant_range + np.sqrt(topo_phase)

        cnst = -4.0 * np.pi / self.sub.LAMBDA
        topography = np.exp(1j * cnst * grad_slant_range).astype(np.complex64)
        del grad_slant_range
        gc.collect()
        return topography

    @staticmethod
    def _pad_to_shape(
        data: np.ndarray, target_shape: Tuple[int, int], fill_value
    ) -> np.ndarray:
        padded = np.full(target_shape, fill_value, dtype=data.dtype)
        height = min(target_shape[0], data.shape[0])
        width = min(target_shape[1], data.shape[1])
        padded[:height, :width] = data[:height, :width]
        return padded

    def _coregister_slc(
        self,
        slc_main: np.ndarray,
        slc_sub: np.ndarray,
        fine: bool = True,
        coherence_window: int = 4,
        fine_shift_range: int = 2,
        fine_stride: int = 1,
    ) -> Tuple[np.ndarray, np.ndarray, Tuple[float, float], Tuple[np.ndarray, np.ndarray]]:
        intensity_main = 10.0 * np.log10(
            np.clip(np.abs(slc_main) ** 2, a_min=1e-10, a_max=1e+10)
        )
        intensity_sub = 10.0 * np.log10(
            np.clip(np.abs(slc_sub) ** 2, a_min=1e-10, a_max=1e+10)
        )

        difference, _ = cv2.phaseCorrelate(
            intensity_main, intensity_sub
        )
        shift_range, shift_azimuth = difference

        slc_sub_coarse = shift(
            slc_sub,
            shift=(-shift_azimuth, -shift_range),
            mode="nearest",
        )
        del intensity_main
        del intensity_sub
        gc.collect()

        if fine:
            slc_sub_fine, coherence_reg, shift_map = self._coregistration_fine_coherence_vectorized(
                slc_main,
                slc_sub_coarse,
                window_size=coherence_window,
                shift_range_min=-fine_shift_range,
                shift_range_max=fine_shift_range,
                stride=fine_stride,
            )
        else:
            slc_sub_fine = slc_sub_coarse
            coherence_reg = self._coherence_vectorized(
                slc_main,
                slc_sub_fine,
                window_size=coherence_window,
            )
            shift_map = (
                np.zeros_like(slc_sub_fine, dtype=np.int32),
                np.zeros_like(slc_sub_fine, dtype=np.int32),
            )

        return slc_sub_fine, coherence_reg, (shift_range, shift_azimuth), shift_map

    def _prepare_geocode_registration(
        self,
        geocoder: geocode.Geocode,
        signal: np.ndarray,
        dem_coreg_window_size: int,
        dem_coreg_shift_range: int,
        dem_coreg_stride: int,
    ):
        dem_radar_smooth, _ = geocoder._geocode_dem_to_radar_smooth(
            geocoder.dem,
            geocoder.idx_azimuth,
            geocoder.idx_range,
            geocoder.sar.NUM_APERTURE_SAMPLE,
            geocoder.sar.NUM_PIXEL,
        )

        idx_az_min = int(np.min(geocoder.idx_azimuth))
        idx_az_max = int(np.max(geocoder.idx_azimuth))
        idx_rg_min = int(np.min(geocoder.idx_range))
        idx_rg_max = int(np.max(geocoder.idx_range))

        top_az = max(idx_az_min - geocoder.buffer_sample, 0)
        bot_az = min(idx_az_max + geocoder.buffer_sample, dem_radar_smooth.shape[0])
        left_rg = max(idx_rg_min - geocoder.buffer_sample, 0)
        right_rg = min(idx_rg_max + geocoder.buffer_sample, dem_radar_smooth.shape[1])

        if top_az >= bot_az or left_rg >= right_rg:
            raise ValueError("No overlap between radar coordinates and DEM after cropping")

        dem_radar_smooth_cropped = dem_radar_smooth[top_az:bot_az, left_rg:right_rg]
        dem_gradient_range = np.zeros_like(dem_radar_smooth_cropped, dtype=np.float32)
        dem_gradient_range[:, 1:-1] = dem_radar_smooth_cropped[:, 2:] - dem_radar_smooth_cropped[:, :-2]

        signal_crop = signal[top_az:bot_az, left_rg:right_rg]
        intensity_crop = (
            10.0 * np.log10(np.clip(np.abs(signal_crop) ** 2, a_min=1e-10, a_max=None)) - 10.0
        )
        difference, _ = cv2.phaseCorrelate(
            dem_gradient_range.astype(np.float32), intensity_crop.astype(np.float32)
        )
        shift_range, shift_azimuth = difference

        intensity_coarse = shift(
            intensity_crop,
            shift=(shift_azimuth, shift_range),
            mode="nearest",
        )
        _, _, fine_shift_map = geocoder._coregistration_fine_correlation_vectorized(
            dem_gradient_range,
            intensity_coarse,
            window_size=dem_coreg_window_size,
            shift_range_min=-dem_coreg_shift_range,
            shift_range_max=dem_coreg_shift_range,
            stride=dem_coreg_stride,
        )

        del dem_radar_smooth
        del dem_gradient_range
        del intensity_crop
        del intensity_coarse
        gc.collect()

        return {
            "dem_radar_smooth": dem_radar_smooth_cropped,
            "top_az": top_az,
            "bot_az": bot_az,
            "left_rg": left_rg,
            "right_rg": right_rg,
            "shift_range": shift_range,
            "shift_azimuth": shift_azimuth,
            "fine_shift_map": fine_shift_map,
        }

    @staticmethod
    def _apply_geocode_registration(
        geocoder: geocode.Geocode, radar_image: np.ndarray, registration: Dict
    ) -> np.ndarray:
        top_az = registration["top_az"]
        bot_az = registration["bot_az"]
        left_rg = registration["left_rg"]
        right_rg = registration["right_rg"]
        shift_range = registration["shift_range"]
        shift_azimuth = registration["shift_azimuth"]
        fine_shift_map = registration["fine_shift_map"]

        radar_crop = radar_image[top_az:bot_az, left_rg:right_rg]
        radar_crop = shift(
            radar_crop,
            shift=(shift_azimuth, shift_range),
            mode="nearest",
        )
        radar_crop = geocoder._apply_shift_map(radar_crop, fine_shift_map[0], fine_shift_map[1])
        return geocoder._geocode_radar_to_geo(radar_crop, top_az, left_rg, 0.0, 0.0)

    @staticmethod
    def _apply_geocode_registration_cropped(
        geocoder: geocode.Geocode, radar_crop: np.ndarray, registration: Dict
    ) -> np.ndarray:
        top_az = registration["top_az"]
        left_rg = registration["left_rg"]
        shift_range = registration["shift_range"]
        shift_azimuth = registration["shift_azimuth"]
        fine_shift_map = registration["fine_shift_map"]

        radar_crop = shift(
            radar_crop,
            shift=(shift_azimuth, shift_range),
            mode="nearest",
        )
        radar_crop = geocoder._apply_shift_map(radar_crop, fine_shift_map[0], fine_shift_map[1])
        return geocoder._geocode_radar_to_geo(radar_crop, top_az, left_rg, 0.0, 0.0)

    @staticmethod
    def _save_jpg(
        image: np.ndarray,
        path: str,
        vmin: Optional[float] = None,
        vmax: Optional[float] = None,
        cmap: Optional[str] = None,
    ) -> None:
        if vmin is None:
            vmin = float(np.nanmin(image))
        if vmax is None:
            vmax = float(np.nanmax(image))
        if vmax <= vmin:
            scaled = np.zeros_like(image, dtype=np.float32)
        else:
            scaled = np.clip((image - vmin) / (vmax - vmin), 0.0, 1.0)
        if cmap:
            colormap = cm.get_cmap(cmap)
            rgb = (colormap(scaled)[..., :3] * 255.0).astype(np.uint8)
            bgr = rgb[..., ::-1]
            cv2.imwrite(path, bgr)
        else:
            gray = (scaled * 255.0).astype(np.uint8)
            cv2.imwrite(path, gray)

    @staticmethod
    def _save_histogram_jpg(
        values: np.ndarray,
        path: str,
        bins: int = 256,
        vmin: float = 0.0,
        vmax: float = 1.0,
        threshold: Optional[float] = None,
    ) -> None:
        valid = np.isfinite(values)
        values = values[valid]
        if values.size == 0:
            cv2.imwrite(path, np.zeros((200, bins, 3), dtype=np.uint8))
            return
        hist, _ = np.histogram(values, bins=bins, range=(vmin, vmax))
        hist = hist.astype(np.float32)
        hist_max = float(hist.max()) if hist.size else 0.0
        height = 200
        width = bins
        image = np.zeros((height, width, 3), dtype=np.uint8)
        if hist_max > 0:
            for idx, count in enumerate(hist):
                bar_height = int((count / hist_max) * (height - 1))
                if bar_height > 0:
                    cv2.line(
                        image,
                        (idx, height - 1),
                        (idx, height - 1 - bar_height),
                        (255, 255, 255),
                        1,
                    )
        if threshold is not None:
            thr = int((threshold - vmin) / (vmax - vmin) * (bins - 1))
            thr = max(0, min(bins - 1, thr))
            cv2.line(image, (thr, 0), (thr, height - 1), (0, 0, 255), 1)
        cv2.imwrite(path, image)

    def process(
        self,
        output_dir: str,
        dem_path: Optional[str] = None,
        dem_bounds: Optional[Tuple[float, float, float, float]] = None,
        dem_shape: Optional[Tuple[int, int]] = None,
        dem_transform=None,
        dem_crs: str = "EPSG:4326",
        buffer_sample: int = 0,
        look_direction: str = "R",
        output_prefix: str = "interferometry",
        fine_registration: bool = True,
        coherence_window: int = 4,
        fine_shift_range: int = 2,
        fine_stride: int = 1,
        multilook_azimuth: int = 3,
        multilook_range: int = 4,
        goldstein_alpha: float = 0.4,
        goldstein_patch_size: int = 64,
        goldstein_step: int = 16,
        goldstein_filter_size: int = 3,
        coherence_threshold_quantile: Optional[float] = 1.0 / 3.0,
        dem_coreg_window_size: int = 128,
        dem_coreg_shift_range: int = 1,
        dem_coreg_stride: int = 2,
    ) -> Dict[str, str]:
        geocoder = geocode.Geocode(
            self.main,
            dem_path=dem_path,
            dem_bounds=dem_bounds,
            dem_shape=dem_shape,
            dem_transform=dem_transform,
            dem_crs=dem_crs,
            buffer_sample=buffer_sample,
            look_direction=look_direction,
        )
        geocode_registration = self._prepare_geocode_registration(
            geocoder,
            self.main.signal,
            dem_coreg_window_size=dem_coreg_window_size,
            dem_coreg_shift_range=dem_coreg_shift_range,
            dem_coreg_stride=dem_coreg_stride,
        )
        dem_radar_crop = geocode_registration["dem_radar_smooth"]
        top_az = geocode_registration["top_az"]
        bot_az = geocode_registration["bot_az"]
        left_rg = geocode_registration["left_rg"]
        right_rg = geocode_registration["right_rg"]

        main_crop = self.main.signal[top_az:bot_az, left_rg:right_rg]
        intensity_crop = np.abs(main_crop).astype(np.float32)

        sub_buffer = 2000
        sub_top = max(top_az - sub_buffer, 0)
        sub_bot = min(bot_az + sub_buffer, self.sub.signal.shape[0])
        sub_left = max(left_rg - sub_buffer, 0)
        sub_right = min(right_rg + sub_buffer, self.sub.signal.shape[1])
        sub_crop = self.sub.signal[sub_top:sub_bot, sub_left:sub_right]

        main_offset_az = top_az - sub_top
        main_offset_rg = left_rg - sub_left
        main_padded = np.zeros(sub_crop.shape, dtype=main_crop.dtype)
        main_padded[
            main_offset_az : main_offset_az + main_crop.shape[0],
            main_offset_rg : main_offset_rg + main_crop.shape[1],
        ] = main_crop

        slc_sub_reg, coherence_reg, _, _ = self._coregister_slc(
            main_padded,
            sub_crop,
            fine=fine_registration,
            coherence_window=coherence_window,
            fine_shift_range=fine_shift_range,
            fine_stride=fine_stride,
        )

        slc_sub_reg_main = slc_sub_reg[
            main_offset_az : main_offset_az + main_crop.shape[0],
            main_offset_rg : main_offset_rg + main_crop.shape[1],
        ]
        coherence_main = coherence_reg[
            main_offset_az : main_offset_az + main_crop.shape[0],
            main_offset_rg : main_offset_rg + main_crop.shape[1],
        ].astype(np.float32)

        interferogram = main_crop * np.conj(slc_sub_reg_main)

        topography_phase = self._compute_topography_phase_cropped(dem_radar_crop, top_az, left_rg)
        interferogram_topo_removed = interferogram * topography_phase

        interferogram_topo_multilook = self._multilook_filter(
            interferogram_topo_removed, multilook_azimuth, multilook_range
        )
        interferogram_topo_filtered = self._goldstein_phase_filter(
            interferogram_topo_multilook,
            alpha=goldstein_alpha,
            patch_size=goldstein_patch_size,
            step=goldstein_step,
            filter_size=goldstein_filter_size,
        )

        coherence_for_hist = coherence_main
        coherence_threshold = None
        if coherence_threshold_quantile is not None:
            finite = coherence_main[np.isfinite(coherence_main)]
            if finite.size > 0:
                coherence_threshold = float(np.quantile(finite, coherence_threshold_quantile))
                mask = coherence_main >= coherence_threshold
                intensity_crop = np.where(mask, intensity_crop, 0.0)
                interferogram = np.where(mask, interferogram, 0.0)
                interferogram_topo_removed = np.where(mask, interferogram_topo_removed, 0.0)
                interferogram_topo_filtered = np.where(mask, interferogram_topo_filtered, 0.0)
                coherence_main = np.where(mask, coherence_main, 0.0)

        geocode_intensity = self._apply_geocode_registration_cropped(
            geocoder, intensity_crop, geocode_registration
        ).astype(np.float32)
        geocode_phase_initial = np.angle(
            self._apply_geocode_registration_cropped(
                geocoder, interferogram, geocode_registration
            )
        ).astype(np.float32)
        geocode_phase_topo_removed = np.angle(
            self._apply_geocode_registration_cropped(
                geocoder, interferogram_topo_removed, geocode_registration
            )
        ).astype(np.float32)
        geocode_phase_topo_multilook = np.angle(
            self._apply_geocode_registration_cropped(
                geocoder, interferogram_topo_filtered, geocode_registration
            )
        ).astype(np.float32)
        geocode_coherence = self._apply_geocode_registration_cropped(
            geocoder, coherence_main, geocode_registration
        ).astype(np.float32)

        del main_padded
        del sub_crop
        del slc_sub_reg
        del slc_sub_reg_main
        del coherence_reg
        del coherence_main
        del interferogram
        del interferogram_topo_removed
        del interferogram_topo_multilook
        del interferogram_topo_filtered
        del intensity_crop
        del topography_phase
        del dem_radar_crop
        gc.collect()

        os.makedirs(output_dir, exist_ok=True)
        outputs = {
            "intensity": os.path.join(output_dir, f"{output_prefix}_intensity.tif"),
            "interferogram_phase": os.path.join(
                output_dir, f"{output_prefix}_interferogram_phase.tif"
            ),
            "topography_removed_phase": os.path.join(
                output_dir, f"{output_prefix}_topography_removed_phase.tif"
            ),
            "topography_removed_phase_multilook": os.path.join(
                output_dir, f"{output_prefix}_topography_removed_phase_multilook.tif"
            ),
            "coherence": os.path.join(output_dir, f"{output_prefix}_coherence.tif"),
            "intensity_jpg": os.path.join(output_dir, f"{output_prefix}_intensity.jpg"),
            "interferogram_phase_jpg": os.path.join(
                output_dir, f"{output_prefix}_interferogram_phase.jpg"
            ),
            "topography_removed_phase_jpg": os.path.join(
                output_dir, f"{output_prefix}_topography_removed_phase.jpg"
            ),
            "topography_removed_phase_multilook_jpg": os.path.join(
                output_dir, f"{output_prefix}_topography_removed_phase_multilook.jpg"
            ),
            "coherence_jpg": os.path.join(output_dir, f"{output_prefix}_coherence.jpg"),
            "coherence_histogram_jpg": os.path.join(
                output_dir, f"{output_prefix}_coherence_histogram.jpg"
            ),
        }

        geocode.Geocode._save_geotiff(outputs["intensity"], geocode_intensity, geocoder.crs, geocoder.transform)
        geocode.Geocode._save_geotiff(
            outputs["interferogram_phase"], geocode_phase_initial, geocoder.crs, geocoder.transform
        )
        geocode.Geocode._save_geotiff(
            outputs["topography_removed_phase"], geocode_phase_topo_removed, geocoder.crs, geocoder.transform
        )
        geocode.Geocode._save_geotiff(
            outputs["topography_removed_phase_multilook"],
            geocode_phase_topo_multilook,
            geocoder.crs,
            geocoder.transform,
        )
        geocode.Geocode._save_geotiff(
            outputs["coherence"], geocode_coherence, geocoder.crs, geocoder.transform
        )
        self._save_jpg(geocode_intensity, outputs["intensity_jpg"])
        self._save_jpg(
            geocode_phase_initial,
            outputs["interferogram_phase_jpg"],
            vmin=-np.pi,
            vmax=np.pi,
            cmap="hsv",
        )
        self._save_jpg(
            geocode_phase_topo_removed,
            outputs["topography_removed_phase_jpg"],
            vmin=-np.pi,
            vmax=np.pi,
            cmap="hsv",
        )
        self._save_jpg(
            geocode_phase_topo_multilook,
            outputs["topography_removed_phase_multilook_jpg"],
            vmin=-np.pi,
            vmax=np.pi,
            cmap="hsv",
        )
        self._save_jpg(
            geocode_coherence,
            outputs["coherence_jpg"],
            vmin=0.0,
            vmax=1.0,
            cmap="inferno",
        )
        self._save_histogram_jpg(
            coherence_for_hist,
            outputs["coherence_histogram_jpg"],
            vmin=0.0,
            vmax=1.0,
            threshold=coherence_threshold,
        )

        return outputs


class Interferometory(Interferometry):
    """Backward-compatible spelling for Interferometry."""
    
