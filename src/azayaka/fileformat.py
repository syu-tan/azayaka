# -*- coding: utf-8 -*-
"""
Azayaka: 
    SAR/InSAR Format Module.
    - JAXA CEOS Format
        - ALOS PALSAR
            - L1.0 RAW, L1.1 SLC
        - ALOS-2 PALSAR-2
            - L1.1 SLC
        - ALOS-4 PALSAR-3
            - L1.2 RAW, L1.1 SLC
    - ESA SAFE Format (TODO 3)
        - Sentinel-1
    - NGA Fromat (TODO 1)
        - SICD CPHD
    - NASA/ISRO CEOS Format (TODO 2)
        - NISAR 
            - RAW, SLC

    Copyright (c) 2026 Syusuke Yasui, Yutaka Yamamoto, and contributors.
    Licensed under the APGL-3.0 License.
    
    Equation - Condition: No 2.xxx File.

"""

import os, gc, warnings, json, time
from typing import Optional, Union, Tuple

import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import interp1d
from tqdm import tqdm

# TODO: print -> logger
# TODO: Base Class Inheritance
#   utify geometory calculation functions and plotting functions

# comment JP -> ENG


def _write_observation_json(obj, output_path: str):
    """
    Write a JSON summary of observation geometry and metadata.

    Parameters
    ----------
    obj : object
        Reader instance containing observation attributes.
    output_path : str
        Output JSON file path.
    """

    def _to_list(value):
        """
        Convert numpy arrays to Python lists for JSON serialization.

        Parameters
        ----------
        value : array_like or None
            Value to convert.

        Returns
        -------
        list or None
            Converted list or None if input is None.
        """
        if value is None:
            return None
        return value.tolist()

    time_start = getattr(obj, "TIME_OBS_START_SEC", None)
    time_end = getattr(obj, "TIME_OBS_END_SEC", None)
    duration = None
    if time_start is not None and time_end is not None:
        # Equation - Condition: No 2.1
        # # Observation Duration := T_end - T_start
        duration = float(time_end - time_start)

    slant_range = getattr(obj, "SLANT_RANGE_SAMPLE", None)
    if slant_range is not None:
        # Equation - Condition: No 2.2
        # # Near/Far Range := min(R), max(R)
        near_range = float(np.min(slant_range))
        far_range = float(np.max(slant_range))
        # Equation - Condition: No 2.3
        # # Range Sample Spacing := R[i+1] - R[i]
        range_sample_spacing = float(getattr(obj, "DIS_RANGE_SLANT", slant_range[1] - slant_range[0]))
    else:
        near_range = None
        far_range = None
        range_sample_spacing = None

    height_sat = getattr(obj, "HEIGHT_SAT", None)
    # Equation - Condition: No 2.4
    # # Mean Height := mean(Height of Satellite)
    mean_height = float(np.mean(height_sat)) if height_sat is not None else None

    scene_id = os.path.basename(getattr(obj, "PATH_CEOS_FOLDER", "")) or None

    data = {
        "format": obj.__class__.__name__,
        "scene_id": scene_id,
        "observation": {
            "start_sec": None if time_start is None else float(time_start),
            "end_sec": None if time_end is None else float(time_end),
            "duration_sec": duration,
        },
        "orbit": {
            "P_X_SAT": _to_list(getattr(obj, "P_X_SAT", None)),
            "P_Y_SAT": _to_list(getattr(obj, "P_Y_SAT", None)),
            "P_Z_SAT": _to_list(getattr(obj, "P_Z_SAT", None)),
            "V_X_SAT": _to_list(getattr(obj, "V_X_SAT", None)),
            "V_Y_SAT": _to_list(getattr(obj, "V_Y_SAT", None)),
            "V_Z_SAT": _to_list(getattr(obj, "V_Z_SAT", None)),
        },
        "range": {
            "near_range_m": near_range,
            "far_range_m": far_range,
            "range_sample_spacing_m": range_sample_spacing,
        },
        "mean_sat_height_m": mean_height,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=True, indent=2)


class CEOS_PALSAR_L10_RAW(object):
    """
    CEOS PALSAR Level 1.0 RAW reader.

    Parses JAXA CEOS records and exposes acquisition metadata and raw signal data.
    """
    
    TIME_DAY_HOUR = 24
    TIME_DAY_MINITE = 60
    TIME_MINITE_SEC = 60
    TIME_DAY_SEC = TIME_DAY_HOUR * TIME_DAY_MINITE * TIME_MINITE_SEC  # sec
    SOL = 299792458.0  # m/s speed of light

    DIGIT4 = 1000.

    BYTE1 = 1
    BYTE2 = 2
    INTERGER4 = 4
    INTERGER6 = 6
    FLOAT16 = 16
    FLOAT22 = 22
    FLOAT32 = 32
    FLOAT64 = 64
    
    NUM_VELOCITY_CALC_SPAN_COUNT: int = 4
    NUM_TMP_SAMPLE: int = 36  # for satellite position interpolation
    NUM_VELOCITY_CALC_SAMPLE: int = 4  # for satellite velocity interpolation
    
    @classmethod
    def __init__(self,
    PATH_CEOS_FOLDER: str,
    POLARIMETORY: str='HH',
    ORBIT_NAME: str='A'
    ):
        
        """ Initialize CEOS Format Reader 
        Args:
            PATH_CEOS_FOLDER (str): Path to CEOS folder
            POLARIMETORY (str, optional): Polarimetry mode. Defaults to 'HH', 'HV', 'VV', 'VH'.
            ORBIT_NAME (str, optional): Orbit name, 'A' or 'D'. Defaults to 'A'.
        """
        self.PATH_CEOS_FOLDER = PATH_CEOS_FOLDER
        self.POLARIMETORY = POLARIMETORY
        self.ORBIT_NAME = ORBIT_NAME
        
        self.PATH_CEOS_FILE_NAME_BASE = os.path.basename(PATH_CEOS_FOLDER).replace('-L1.0', '-H1.0')
        self.PATH_IMG = os.path.join(self.PATH_CEOS_FOLDER, f'IMG-{self.POLARIMETORY}-{self.PATH_CEOS_FILE_NAME_BASE}__{self.ORBIT_NAME}')
        self.PATH_LED = os.path.join(self.PATH_CEOS_FOLDER, f'LED-{self.PATH_CEOS_FILE_NAME_BASE}__{self.ORBIT_NAME}')
        
        # check if the files exist
        if not os.path.exists(self.PATH_IMG) or not os.path.exists(self.PATH_LED):
            raise FileNotFoundError(
                f'--->>> {self.PATH_IMG} or {self.PATH_LED} does not exist'
                )
        
        """
        IMG File Reader
        """
        f = open(self.PATH_IMG, "rb")
        
        f.seek(8)
        self.NUM_SAR_DISCRIPTOR_RECORD = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print('6 9 － 12 B4 レコード長 = 720）10 ->', self.NUM_SAR_DISCRIPTOR_RECORD)

        f.seek(276)
        self.NUM_PREFIX = int(f.read(self.INTERGER4))
        print('46 277 － 280 I4 レコードあたりのPREFIX DATAのバイト数 ＝ b412 ：固定 ->', self.NUM_PREFIX)
        f.seek(180)
        self.NUM_SIGNAL_RECORD = int(f.read(self.INTERGER6))
        print('29 181 － 186 I6 SARデータレコード数 シグナルデータレコード数 ->', self.NUM_SIGNAL_RECORD)
        f.seek(186)
        self.signal_record_length = int(f.read(self.INTERGER6))

        print(f'{"="*10} Header {self.NUM_PREFIX} {"="*10}')

        f.seek(48 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.pol = int.from_bytes(f.read(self.BYTE2), byteorder="big")
        print('16 49 － 50 B2 SARチャンネルID = 1：1偏波、2：2偏波、4：ポラリメトリ ->', self.pol)
        f.seek(8 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.record_length = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print('6 9 － 12 B4 レコード長（観測モード及びオフナディア角から求められるレコードサイズで、実際のレコード長） ->', self.record_length) 
        f.seek(12 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.azimuth_line = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print('7 13 － 16 B4 SAR画像データライン番号 ＝ 1、2、3……・ ->', self.azimuth_line)
        f.seek(16 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.sar_image_index = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print('8 17 － 20 B4 SAR画像データレコードインデックス ＝ 1：固定 (画像ライン内でのレコード順序番号) ->', self.sar_image_index)
        f.seek(24 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.NUM_PIXEL = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print('10 25 － 28 B4 実際のデータピクセル数 ->', self.NUM_PIXEL)
        f.seek(28 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.NUM_BLANK_PIXEL = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print('11 29 － 32 B4 実際の右詰めのピクセル数 ->', self.NUM_BLANK_PIXEL)
        f.seek(56 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.prf = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print('20 57 － 60 B4 PRF [mHz] ->', self.prf)
        f.seek(66 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.chirp = int.from_bytes(f.read(self.BYTE2), byteorder="big")
        print('23 67 － 68 B2 チャープ形式指定者 0=LINEAR FM CHIRP 1=PHASE MODULATORS ->', self.chirp)
        f.seek(68 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.chirp_length = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print('24 69 － 72 B4 チャープ長(パルス幅) nsec （チャープ長さ） ->', self.chirp_length)
        f.seek(72 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.chirp_const = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print('25 73 － 76 B4 チャープ定数係数 Hz ノミナル値 ->', self.chirp_const)
        f.seek(76 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.chirp_coeff = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print('26 77 － 80 B4 チャープ一次係数 Hz/μsec ノミナル値 ->', self.chirp_coeff)
        f.seek(80 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.chirp_coeff2 = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print('27 81 － 84 B4 チャープ二次係数 Hz/μsec2 ノミナル値 ->', self.chirp_coeff2)
        f.seek(92 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.gain = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print('30 93 － 96 B4 受信機ゲイン dB ノミナル値 ->', self.gain)
        f.seek(116 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.DIS_NEAR_RANGE = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print('36 117 － 120 B4 最初のデータまでのスラントレンジ [m] ->', self.DIS_NEAR_RANGE)
        # 37 121 － 124 B4 データレコード窓位置（SAMPLE DELAY (nsec)）
        f.seek(124 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.TIME_GATE_DELAY_T = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print('37 121 － 124 B4 データレコード窓位置（SAMPLE DELAY (nsec)）->', self.TIME_GATE_DELAY_T)
        # 26 シグナルデータ 121 データレコード窓位置
        # （SAMPLE DELAY[nsec]） SAMPLE DELAYの計算式は、以下の通りで
        # Tsdlay =tRxs + toff
        # tRxs ： 受信ゲート開始時刻2 (観測補助)
        # toff ： オフセット(-8.31539μsec固定)
        # Equation - Condition: No 2.5
        # # Time Gate Delay := (T_sample - T_offset) / 1e9
        self.TIME_GATE_DELAY = (self.TIME_GATE_DELAY_T - 8315.39) / 1e9  # nsec to sec
        print('    -> 受信ゲート開始時刻2 (観測補助) Tsdlay =', self.TIME_GATE_DELAY, '[sec]')

        f.seek(self.NUM_SAR_DISCRIPTOR_RECORD)
        print('Num of Range: ', self.NUM_PIXEL, 'Num of Azimuth Line: ', self.NUM_SIGNAL_RECORD)
        
        self.signal = np.zeros((self.NUM_SIGNAL_RECORD, self.NUM_PIXEL), dtype=np.complex64)
        
        for i in tqdm(range(self.NUM_SIGNAL_RECORD)):
            if i == 0:
                print(f'{"="*10} Start Time {"="*10}');
                _ = f.read(36)
                self.TIME_OBS_START_YEAR = f.read(self.INTERGER4)
                self.TIME_OBS_START_YEAR = int.from_bytes(self.TIME_OBS_START_YEAR, 'big')
                print('13 37 － 40 B4 センサー取得年 ->', self.TIME_OBS_START_YEAR)
                self.TIME_OBS_START_DAY = f.read(self.INTERGER4)
                self.TIME_OBS_START_DAY = int.from_bytes(self.TIME_OBS_START_DAY, 'big')
                print('14 41 － 44 B4 センサー取得日（年内通算） ->', self.TIME_OBS_START_DAY)
                self.TIME_OBS_START_MSEC = f.read(self.INTERGER4)
                self.TIME_OBS_START_MSEC = int.from_bytes(self.TIME_OBS_START_MSEC, 'big')
                print('15 45 － 48 B4 センサー取得ミリ秒（日内通算） ->', self.TIME_OBS_START_MSEC)
                _ = f.read(self.NUM_PREFIX - (36 + 4 * 3))
                
            elif i == self.NUM_SIGNAL_RECORD - 1:
                
                print(f'{"="*10} End Time {"="*10}');
                _ = f.read(36)
                self.TIME_OBS_END_YEAR = f.read(self.INTERGER4)
                self.TIME_OBS_END_YEAR = int.from_bytes(self.TIME_OBS_END_YEAR, 'big')
                print('13 37 － 40 B4 センサー取得年 ->', self.TIME_OBS_END_YEAR)
                self.TIME_OBS_END_DAY = f.read(self.INTERGER4)
                self.TIME_OBS_END_DAY = int.from_bytes(self.TIME_OBS_END_DAY, 'big')
                print('14 41 － 44 B4 センサー取得日（年内通算） ->', self.TIME_OBS_END_DAY)
                self.TIME_OBS_END_MSEC = f.read(self.INTERGER4)
                self.TIME_OBS_END_MSEC = int.from_bytes(self.TIME_OBS_END_MSEC, 'big')
                print('15 45 － 48 B4 センサー取得ミリ秒（日内通算） ->', self.TIME_OBS_END_MSEC)
                _ = f.read(self.NUM_PREFIX - (36 + 4 * 3))
                
            else:
                _ = f.read(self.NUM_PREFIX)
            
            if i >= self.NUM_SIGNAL_RECORD - 2:
                # single processing
                for j in range(self.NUM_PIXEL):
                    byte_hh_r = f.read(self.BYTE1)
                    byte_hh_i = f.read(self.BYTE1)
                    hh_real = int.from_bytes(byte_hh_r, 'big') 
                    hh_imag = int.from_bytes(byte_hh_i, 'big')
                    self.signal[i, j] = hh_real + hh_imag * 1j
            else:
                # paralell processing
                byte_ri = f.read(self.NUM_PIXEL * 2)
                ri = np.frombuffer(byte_ri, dtype=np.uint8)
                ln = int(len(ri) / 2)
                self.signal[i,:ln] = ri[0::2] + ri[1::2] * 1j
                
            # right offset
            _ = f.read(self.NUM_BLANK_PIXEL * 2)
            
        f.close()
        
        """
        LED File Reader
        """
        
        f = open(self.PATH_LED, "rb")
        
        # ## 表3.3-4 SARリーダーファイルディスクリプタレコード
        f.seek(8)
        self.record_length = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        f.seek(180)
        self.summary_record = int(f.read(self.INTERGER6))
        print('25 181 － 186 I6 データセットサマリレコードの数 = bbbbb1 ->', self.summary_record)
        f.seek(186)
        self.summary_record_length = int(f.read(self.INTERGER6))
        print('26 187 － 192 I6 データセットサマリレコード長 = b4096 ->', self.summary_record_length)
        f.seek(192)
        self.map_record = int(f.read(self.INTERGER6))
        print('27 193 － 198 I6 地図投影データレコードの数 = bbbbb0 ->', self.map_record)
        f.seek(198)
        self.map_record_length = int(f.read(self.INTERGER6))
        print('28 199 － 204 I6 地図投影データレコード長 = bbbbb0 ->', self.map_record_length)
        f.seek(210)
        self.platform_record_length = int(f.read(self.INTERGER6))
        print('30 211 － 216 I6 プラットフォーム位置データレコード長 = b4680 ->', self.platform_record_length)
        f.seek(222)
        self.attitude_record_length = int(f.read(self.INTERGER6))
        print('32 223 － 228 I6 姿勢データレコード長 = b8192 ->', self.attitude_record_length)
        f.seek(234)
        self.radiometric_record_length = int(f.read(self.INTERGER6))
        print('34 235 － 240 I6 ラジオメトリックデータレコード長 = bbbbb0 ->', self.radiometric_record_length)
        f.seek(246)
        self.radiometric_comp_record_length = int(f.read(self.INTERGER6))
        print('36 247 － 252 I6 ラジオメトリック補償レコード長 = bbbbb0 ->', self.radiometric_comp_record_length)
        f.seek(258)
        self.data_quality_record_length = int(f.read(self.INTERGER6))
        print('38 259 － 264 I6 データ品質サマリレコード長 = bbbbb0 ->', self.data_quality_record_length)
        f.seek(270)
        self.data_histogram_record_length = int(f.read(self.INTERGER6))
        print('40 271 － 276 I6 データヒストグラムレコード長 = bbbbb0 ->', self.data_histogram_record_length)
        f.seek(282)
        self.range_spectrum_record_length = int(f.read(self.INTERGER6))
        print('42 283 － 288 I6 レンジスペクトルレコード長 = bbbbb0 ->', self.range_spectrum_record_length)
        f.seek(294)
        self.dem_record_length = int(f.read(self.INTERGER6))
        print('44 295 － 300 I6 DEMディスクリプタレコード長 = bbbbb0 ->', self.dem_record_length)
        f.seek(342)
        self.calibration_record_length = int(f.read(self.INTERGER6))
        print('52 343 － 348 I6 キャリブレーションレコード長 = b13212 ->', self.calibration_record_length)
        
        # ## 表3.3-5 データセットサマリレコード
        f.seek(self.record_length + 8)
        self.summary_record_length = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print('6 9 － 12 B4 データセットサマリレコード長 = 4096）10 ->', self.summary_record_length)
        f.seek(self.record_length + 20)
        self.scene_id = f.read(self.FLOAT32).decode('utf-8')
        print('9 21 － 52 A32 シーンID ->', self.scene_id)
        f.seek(self.record_length + 68)
        self.scene_time = f.read(self.FLOAT32).decode('utf-8')
        print('11 69 － 100 A32 シーンセンター時刻 ->', self.scene_time)
        f.seek(self.record_length + 164)
        self.ellipsoid_model = f.read(self.FLOAT16).decode('utf-8')
        print('16 165 － 180 A16 楕円体モデル ->', self.ellipsoid_model)
        f.seek(self.record_length + 180)
        self.ellipsoid_radius = float(f.read(self.FLOAT16))
        print('17 181 － 196 F16.7 楕円体の半長径(Km) ->', self.ellipsoid_radius)
        f.seek(self.record_length + 196)
        self.ellipsoid_short_radius = float(f.read(self.FLOAT16))
        print('18 197 － 212 F16.7 楕円体の短半径(Km) ->', self.ellipsoid_short_radius)
        f.seek(self.record_length + 212)
        self.earth_mass = float(f.read(self.FLOAT16))
        print('19 213 － 228 F16.7 地球の質量 (10^24 Kg) ->', self.earth_mass)
        f.seek(self.record_length + 244)
        self.j2 = float(f.read(self.FLOAT16))
        self.j3 = float(f.read(self.FLOAT16))
        self.j4 = float(f.read(self.FLOAT16))
        print('21 245 － 260 F16.7 長楕円パラメータ（力学的形状係数 J2項） ->', self.j2)
        print('22 261 － 276 F16.7 長楕円パラメータ（力学的形状係数 J3項） ->', self.j3)
        print('23 277 － 292 F16.7 長楕円パラメータ（力学的形状係数 J4項） ->', self.j4)
        f.seek(self.record_length + 308)
        self.ellipsoid_mean = f.read(self.FLOAT16)
        print('25 309 － 324 F16.7 シーン中央における楕円上の平均的な地形標高 ->', self.ellipsoid_mean)
        f.seek(self.record_length + 388)
        self.sar_channel = int(f.read(self.INTERGER4))
        print('31 389 － 392 I4 SARチャネル数 ->', self.sar_channel)
        f.seek(self.record_length + 396)
        self.sensor_platform = f.read(self.FLOAT16).decode('utf-8')
        print('33 397 － 412 A16 センサプラットフォーム名(ID) ->', self.sensor_platform)
        f.seek(self.record_length + 500)
        self.LAMBDA = float(f.read(16))
        print('波長λ: ', self.LAMBDA)
        f.seek(self.record_length + 516)
        self.motion_compensation = f.read(self.BYTE2).decode('utf-8')
        print('43 517 － 518 A2 Motion compensation indicator ＝ 00：固定 ->', self.motion_compensation)
        # 00 ： no compensation
        # 01 ： on board compensation
        # 10 ： in processor compensation
        # 11 ： both on board and in processor
        f.seek(self.record_length + 518)
        range_pulse_code = f.read(self.FLOAT16).decode('utf-8')
        print('44 519 － 534 A16 レンジパルスコード ->', range_pulse_code)
        f.seek(self.record_length + 534)
        self.range_pulse_amplitude = float(f.read(self.FLOAT16))
        self.range_pulse_amplitude2 = float(f.read(self.FLOAT16))
        self.range_pulse_amplitude3 = float(f.read(self.FLOAT16))
        self.range_pulse_amplitude4 = float(f.read(self.FLOAT16))
        self.range_pulse_amplitude5 = float(f.read(self.FLOAT16))
        print('45 535 － 550 E16.7 レンジパルス振幅係数1 ノミナル値 ->', self.range_pulse_amplitude)
        print('46 551 － 566 E16.7 レンジパルス振幅係数2 ノミナル値 ->', self.range_pulse_amplitude2)
        print('47 567 － 582 E16.7 レンジパルス振幅係数3 ノミナル値 ->', self.range_pulse_amplitude3)
        print('48 583 － 598 E16.7 レンジパルス振幅係数4 ノミナル値 ->', self.range_pulse_amplitude4)
        print('49 599 － 614 E16.7 レンジパルス振幅係数5 ノミナル値 ->', self.range_pulse_amplitude5)
        f.seek(self.record_length + 710)
        self.sampling_frequency_mhz = float(f.read(self.FLOAT16))
        print('57 711 － 726 F16.7 サンプリング周波数 (MHz) ノミナル値 ->', self.sampling_frequency_mhz)
        f.seek(self.record_length + 726)
        self.range_gate = float(f.read(self.FLOAT16))
        print('58 727 － 742 F16.7 レンジゲート（画像開始時の立ち上がり）(μsec) ->', self.range_gate)
        f.seek(self.record_length + 742)
        self.range_pulse_width = float(f.read(self.FLOAT16))
        print('59 743 － 758 F16.7 レンジパルス幅 (μsec) ->', self.range_pulse_width)
        f.seek(self.record_length + 806)
        self.quantization_descriptor = f.read(12).decode('utf-8')
        print('65 807 － 818 A12 量子化記述子 ->', self.quantization_descriptor)
        f.seek(self.record_length + 818)
        self.DC_BIAS_I = float(f.read(self.FLOAT16))
        self.DC_BIAS_Q = float(f.read(self.FLOAT16))
        self.gain_imbalance = float(f.read(self.FLOAT16))
        print('66 819 － 834 F16.7 Ｉ成分のＤＣバイアス ノミナル値 ->', self.DC_BIAS_I)
        print('67 835 － 850 F16.7 Ｑ成分のＤＣバイアス ノミナル値 ->', self.DC_BIAS_Q)
        print('68 851 － 866 F16.7 ＩとＱのゲイン不均衡 ノミナル値 ->', self.gain_imbalance)
        f.seek(self.record_length + 898)
        self.electronic_boresight = float(f.read(self.FLOAT16))
        print('71 899 － 914 F16.7 electronic boresight ->', self.electronic_boresight)
        f.seek(self.record_length + 914)
        self.mechanical_boresight = float(f.read(self.FLOAT16))
        print('72 915 － 930 F16.7 mechanical boresight ->', self.mechanical_boresight)
        f.seek(self.record_length + 934)
        self.prf = float(f.read(self.FLOAT16))
        print('74 935 － 950 F16.7 PRF (mHz) ->', self.prf)
        f.seek(self.record_length + 950)
        self.beam_width_elevation = float(f.read(self.FLOAT16))
        self.beam_width_azimuth = float(f.read(self.FLOAT16))
        print('75 951 － 966 F16.7 2ウェイアンテナビーム幅(エレベーション、実効値) ノミナル値 ->', self.beam_width_elevation)
        print('76 967 － 982 F16.7 2ウェイアンテナビーム幅(アジマス、実効値) ノミナル値 ->', self.beam_width_azimuth)
        f.seek(self.record_length + 982)
        self.binary_time = int(f.read(self.FLOAT16))
        self.clock_time = f.read(self.FLOAT32).decode('utf-8')
        self.clock_increase = int(f.read(self.FLOAT16))
        print('77 983 － 998 I16 衛星のバイナリ時刻コード： 時刻誤差情報の基準衛星時刻カウンタ(Tref) ->', self.binary_time)
        print('78 999 － 1030 A32 衛星のクロック時刻 ：時刻誤差情報の基準地上時刻(Tgref) ->', self.clock_time)
        print('79 1031 － 1046 I16 衛星のクロックの増加量 [nsec] ：時刻誤差情報の算出衛星カウンタ周期(Psc) ->', self.clock_increase)
        f.seek(self.record_length + 1174)
        # look_azimuth = float(f.read(FLOAT16))
        # print('87 1175 － 1190 F16.7 アジマス方向のルック数 ->', look_azimuth) # Blank
        f.seek(self.record_length + 1534)
        self.time_index = f.read(8).decode('utf-8')
        print('108 1535 － 1542 A8 ライン方向に沿った時間方向指標（計画値） ->', self.time_index)
        # 1シーン内でＰＲＦが変化していない場合 ="bbb0"
        # 1シーン内でＰＲＦが変化した場合 ="bbb1"
        # 広観測域モードの場合
        f.seek(self.record_length + 1802)
        self.prf_change_flag = f.read(self.INTERGER4).decode('utf-8')
        print('130 1803 － 1806 I4 PRF変化点フラグ ->', self.prf_change_flag)
        # 変化点なしの場合は、'bbbbbbb1'が格納される。
        # 広観測域モードの場合は、'bbbbbbb0'が格納される。
        f.seek(self.record_length + 1806)
        self.prf_change_line = int(f.read(8))
        print('131 1807 － 1814 I8 PRF変化開始ライン番号 ->', self.prf_change_line)
        # ヨーステアリングしていない場合 = "bbb1"
        # ヨーステアリングしている場合 = "bbb0"
        f.seek(self.record_length + 1830)
        self.yaw_steering_flag = f.read(self.INTERGER4).decode('utf-8')
        print('133 1831 － 1834 I4 ヨーステアリングの有無フラグ ->', self.yaw_steering_flag)
        f.seek(self.record_length + 1838)
        self.off_nadir_angle = float(f.read(self.FLOAT16))
        print('135 1839 － 1854 F16.7 オフナディア角 ->', self.off_nadir_angle)
        f.seek(self.record_length + 1854)
        self.antenna_beam_number = int(f.read(self.INTERGER4))
        print('136 1855 － 1858 I4 アンテナビーム番号 ->', self.antenna_beam_number)
        
        # ## 表3.3-6 プラットフォーム位置データ・レコード
        f.seek(self.record_length + self.summary_record_length + 8)
        self.platform_record_length = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print('6 9 － 12 B4 プラットフォーム位置データレコード長 ＝ 4680）10 ->', self.platform_record_length)
        # ALOS軌道情報（予測値） ： '0bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
        # ALOS軌道情報（決定値） ： '1bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
        # ALOS高精度軌道情報 ： '2bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
        f.seek(self.record_length + self.summary_record_length + 12)
        self.orbit_type = f.read(self.FLOAT32).decode('utf-8')
        print('7 13 － 44 A32 軌道要素種類 ->', self.orbit_type)
        # ALOS軌道情報（予測値） ： 'bb28'
        # ALOS軌道情報（決定値） ： 'bb28'
        # ALOS高精度軌道情報 ： 'bb28'
        f.seek(self.record_length + self.summary_record_length + 140)
        self.NUM_ORB_POINT = int(f.read(self.INTERGER4))
        print('14 141 － 144 I4 データポイント数 ->', self.NUM_ORB_POINT)
        f.seek(self.record_length + self.summary_record_length + 144)
        self.TIME_ORB_YEAR = int(f.read(self.INTERGER4))
        self.TIME_ORB_MONTH = int(f.read(self.INTERGER4))
        self.TIME_ORB_DAY = int(f.read(self.INTERGER4))
        self.TIME_ORB_COUNT_DAY = int(f.read(self.INTERGER4))
        self.TIME_ORB_SEC = float(f.read(self.FLOAT22))
        print('15 145 － 148 I4 第1ポイントの年 ->', self.TIME_ORB_YEAR)
        print('16 149 － 152 I4 第1ポイントの月 ->', self.TIME_ORB_MONTH)
        print('17 153 － 156 I4 第1ポイントの日 ->', self.TIME_ORB_DAY)
        print('18 157 － 160 I4 第1ポイントの通算日 ->', self.TIME_ORB_COUNT_DAY)
        print('19 161 － 182 E22.15 第1ポイントの通算秒 ->', self.TIME_ORB_SEC)
        f.seek(self.record_length + self.summary_record_length + 182)
        self.TIME_INTERVAL = float(f.read(self.FLOAT22))
        print('20 183 － 204 E22.15 ポイント間のインターバル時間（秒） ->', self.TIME_INTERVAL)
        f.seek(self.record_length + self.summary_record_length + 204)
        self.reference_coordinate = f.read(self.FLOAT64).decode('utf-8')
        print('21 205 － 268 A64 参照座標系 (ECI、ECR) ->', self.reference_coordinate)
        f.seek(self.record_length + self.summary_record_length + 290)
        self.position_error = float(f.read(self.FLOAT16))
        print('23 291 － 306 F16.7 進行方向の位置誤差 [m]ノミナル値 ->', self.position_error)
        f.seek(self.record_length + self.summary_record_length + 306)
        self.position_error2 = float(f.read(self.FLOAT16))
        print('24 307 － 322 F16.7 直交方向の位置誤差 [m]ノミナル値 ->', self.position_error2)
        f.seek(self.record_length + self.summary_record_length + 322)
        self.position_error3 = float(f.read(self.FLOAT16))
        print('25 323 － 338 F16.7 半径方向の位置誤差 [m]ノミナル値 ->', self.position_error3)
        f.seek(self.record_length + self.summary_record_length + 338)
        self.velocity_error = float(f.read(self.FLOAT16))
        print('26 339 － 354 F16.7 進行方向の速度誤差 [m/sec]ノミナル値 ->', self.velocity_error)
        f.seek(self.record_length + self.summary_record_length + 354)
        self.velocity_error2 = float(f.read(self.FLOAT16))
        print('27 355 － 370 F16.7 直交方向の速度誤差 [m/sec]ノミナル値 ->', self.velocity_error2)
        f.seek(self.record_length + self.summary_record_length + 370)
        self.velocity_error3 = float(f.read(self.FLOAT16))
        print('28 371 － 386 F16.7 半径方向の速度誤差 [m/sec]ノミナル値 ->', self.velocity_error3)
        f.seek(self.record_length + self.summary_record_length + 386)
        self.position_vector = np.zeros((28, 3))
        self.velocity_vector = np.zeros((28, 3))
        for i in range(28):
            self.position_vector[i, 0] = float(f.read(self.FLOAT22))
            self.position_vector[i, 1] = float(f.read(self.FLOAT22))
            self.position_vector[i, 2] = float(f.read(self.FLOAT22))
            self.velocity_vector[i, 0] = float(f.read(self.FLOAT22))
            self.velocity_vector[i, 1] = float(f.read(self.FLOAT22))
            self.velocity_vector[i, 2] = float(f.read(self.FLOAT22))
        print('29 387 － 452 E22.15 第1データポイント位置ベクトル (x) [m] ->', self.position_vector[0, 0])
        print('30 387 － 452 E22.15 第1データポイント位置ベクトル (y) [m] ->', self.position_vector[0, 1])
        print('31 387 － 452 E22.15 第1データポイント位置ベクトル (z) [m] ->', self.position_vector[0, 2])
        print('32 453 － 518 E22.15 第28データポイント速度ベクトル(x\') [m/sec] ->', self.velocity_vector[-1, 0])
        print('33 453 － 518 E22.15 第28データポイント速度ベクトル(y\') [m/sec] ->', self.velocity_vector[-1, 1])
        print('34 453 － 518 E22.15 第28データポイント速度ベクトル(z\') [m/sec] ->', self.velocity_vector[-1, 2])
        f.seek(self.record_length + self.summary_record_length + 4100)
        self.leap_second_flag = int(f.read(self.BYTE1))
        print('36 4101 － 4101 I1 うるう秒発生フラグ 0：無し、1：うるう秒あり ->', self.leap_second_flag)

        f.seek(self.record_length + self.summary_record_length + self.platform_record_length + 8)
        self.attitude_record_length = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print('6 9 － 12 B4 姿勢データ・レコード長 ＝ 8192）10 ->', self.attitude_record_length)
        f.seek(self.record_length + self.summary_record_length + self.platform_record_length + 28)
        self.pitch_quality = f.read(self.INTERGER4).decode('utf-8')
        self.roll_quality = f.read(self.INTERGER4).decode('utf-8')
        self.yaw_quality = f.read(self.INTERGER4).decode('utf-8')
        self.pitch = float(f.read(14))
        self.roll = float(f.read(14))
        self.yaw = float(f.read(14))
        self.pitch_rate_quality = f.read(self.INTERGER4).decode('utf-8')
        self.roll_rate_quality = f.read(self.INTERGER4).decode('utf-8')
        self.yaw_rate_quality = f.read(self.INTERGER4).decode('utf-8')
        print('10 29 － 32 I4 ピッチ・データ品質フラグ ->', self.pitch_quality)
        print('11 33 － 36 I4 ロール・データ品質フラグ ->', self.roll_quality)
        print('12 37 － 40 I4 ヨー・データ品質フラグ ->', self.yaw_quality)
        print('13 41 － 54 E14.6 ピッチ（度） ->', self.pitch)
        print('14 55 － 68 E14.6 ロール（度） ->', self.roll)
        print('15 69 － 82 E14.6 ヨー（度） ->', self.yaw)
        f.seek(self.record_length + self.summary_record_length + self.platform_record_length + 12)
        self.point_number = int(f.read(self.INTERGER4))
        print('7 13 － 16 I4 ポイント数 ->', self.point_number)
        f.seek(self.record_length + self.summary_record_length + self.platform_record_length + 94)
        self.points_pitches = np.zeros(self.point_number)
        self.points_rolls = np.zeros(self.point_number)
        self.points_yaws = np.zeros(self.point_number)
        for i in range(self.point_number - 1):
            self.points_pitches[i] = float(f.read(14))
            self.points_rolls[i] = float(f.read(14))
            self.points_yaws[i] = float(f.read(14))
            break
        print('19 95 － 108 E14.6 ピッチ率 ->', self.points_pitches)
        print('20 109 － 122 E14.6 ロール率 ->', self.points_rolls)
        print('21 123 － 136 E14.6 ヨー率 ->', self.points_yaws)
        
        # ## 表3.3-8 キャリブレーションデータレコード
        f.seek(self.record_length + self.summary_record_length + self.platform_record_length + self.attitude_record_length + 8)
        self.calibration_record_length = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print('6 9 － 12 B4 レコード長 ＝ 13212）10 ->', self.calibration_record_length)
        f.seek(self.record_length + self.summary_record_length + self.platform_record_length + self.attitude_record_length + 16)
        self.valid_sample = int(f.read(self.INTERGER4))
        self.calibration_start = f.read(17).decode('utf-8')
        self.calibration_end = f.read(17).decode('utf-8')
        self.attenuator = int(f.read(self.INTERGER4))
        self.alc = int(f.read(self.BYTE1))
        self.agc = int(f.read(self.BYTE1))
        self.pulse_width = int(f.read(self.INTERGER4))
        self.chirp_bandwidth = int(f.read(self.INTERGER4))
        self.sampling_frequency = int(f.read(self.INTERGER4))
        self.quantization_bit = int(f.read(self.INTERGER4))
        self.chirp_replica = int(f.read(self.INTERGER4))
        self.chirp_replica_line = int(f.read(self.INTERGER4))
        print('8 17 － 20 I4 有効サンプル数=Nsamp ->', self.valid_sample)
        print('9 21 － 37 A17 校正データ取得開始時刻 ->', self.calibration_start)
        print('10 38 － 54 A17 校正データ取得終了時刻 ->', self.calibration_end)
        print('11 55 － 58 I4 校正器ATT設定値 ->', self.attenuator)
        print('12 59 － 59 I1 校正器ALC ->', self.alc)
        print('13 60 － 60 I1 AGC/MGC ->', self.agc)
        print('14 61 － 64 I4 送信パルス幅 ->', self.pulse_width)
        print('15 65 － 68 I4 チャープ帯域 ->', self.chirp_bandwidth)
        print('16 69 － 72 I4 サンプリング周波数 ->', self.sampling_frequency)
        print('17 73 － 76 I4 量子化ビット数 ->', self.quantization_bit)
        print('18 77 － 80 I4 チャープレプリカデータ数 ->', self.chirp_replica)
        print('19 81 － 84 I4 チャープレプリカデータ積算ライン数ｎ ->', self.chirp_replica_line)
        # 20 85 － 85 I1 受信偏波1 0=H偏波、1=V偏波
        f.seek(self.record_length + self.summary_record_length + self.platform_record_length + self.attitude_record_length + 84)
        self.receive_polarization1 = int(f.read(self.BYTE1))
        print('20 85 － 85 I1 受信偏波1 ->', self.receive_polarization1)
        # 21 86 － α Nsamp*(2B2)
        # チャープレプリカデータ1
        # 取得した第1フレーム～ｎフレーム目の各サンプル毎の合計値
        # （ΣI1(n)、ΣＱ1(n)、ΣI2(n)、ΣQ2(n)…・,ΣINsamp(n)、ΣＱNsamp(n)の順）
        # （1サンプル（I,Q）各16ビット整数値）
        f.seek(self.record_length + self.summary_record_length + \
            self.platform_record_length + self.attitude_record_length + 85)
        self.chirp_replica_data1 = np.zeros((self.valid_sample, 2))
        for i in range(self.valid_sample):
            self.chirp_replica_data1[i, 0] = int.from_bytes(f.read(self.BYTE2), byteorder="big")
            self.chirp_replica_data1[i, 1] = int.from_bytes(f.read(self.BYTE2), byteorder="big")
        print('21 86 － α Nsamp*(2B2) チャープレプリカデータ1 ->', self.chirp_replica_data1.shape)
        f.seek(self.record_length + self.summary_record_length + self.platform_record_length + self.attitude_record_length + 6230)
        # receive_polarization2 = int(f.read(BYTE1)) # blank
        # print('22 6231 － 6231 I1 受信偏波2 ->', receive_polarization2)
        
        # ## 表3.3-9 設備関連データレコード
        
        # TT&Cシステムテレメトリデータ = 1,540,000）10
        # 姿勢決定3、GPSR生データ = 4,314,000）10
        # PALSARミッションテレメトリデータ = 345,000）10
        # ALOS軌道情報：予測値（ECR) = 325,000）10
        # ALOS軌道情報：決定値（ECR) = 325,000）10
        # 時刻誤差情報 = 3,072）10
        # ALOS高精度軌道情報 = 511,000）10
        # 高精度姿勢情報 = 4,370,000）10
        # 座標変換情報 = 728,000）10
        # ワークオーダ&ワークレポート = 15,000）10
        f.seek(self.record_length + self.summary_record_length + self.platform_record_length + self.attitude_record_length + self.calibration_record_length + 0)
        self.record_order = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print('1 1 － 4 B4 レコード順序番号 ->', self.record_order)

        f.seek(self.record_length + self.summary_record_length + self.platform_record_length + self.attitude_record_length + self.calibration_record_length + 7)
        self.sub_type = int.from_bytes(f.read(self.BYTE1), byteorder="big")
        print('5 8 － 8 B1 第3レコードサブタイプコード (JAXA=70)->', self.sub_type)

        # CEOS=20、CCRS=36、ESA=50、NASA=60、JPL=61
        # JAXA=70、DFVLR=80、RAE=90、TELESPAZIO=10
        # UNSPECIFIED=18、等
        f.seek(self.record_length + self.summary_record_length + self.platform_record_length + self.attitude_record_length + self.calibration_record_length + 8)  # 31484
        self.atla_record_length1 = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print('6 9 － 12 B4 レコード長 ->', self.atla_record_length1)  # TT&Cシステムテレメトリデータ = 1,540,000
        # 以降はブランクなので割愛
        f.close()
        print('CEOS PALSAR L1.0 RAWデータの読み込み完了\n')
        
        self.NUM_APERTURE_SAMPLE = self.NUM_SIGNAL_RECORD  # default full sample
        
        # スケール調整
        self.FREQ_AD_SAMPLE = self.sampling_frequency * 1e6
        self.FREQ_PULSE_REPETITION = self.prf * 1e-3
        self.TIME_PLUSE_DURATION = self.chirp_length * 1e-9
        self.DIS_ELLIPSOID_RADIUS = self.ellipsoid_radius * 1e3
        self.DIS_ELLIPSOID_SHORT_RADIUS = self.ellipsoid_short_radius * 1e3
        
    def set_geometory(self, plot=False, output_json_path: str=None, PATH_OUTPUT: str='./output'):
        """ 観測ジオメトリの設定 """
        
        self.TIME_SHIFT = 0.0  # [sec] 時刻シフト量
        self.NUM_APERTURE_SAMPLE = self.NUM_SIGNAL_RECORD  # アパーチャサンプル数の設定
        
        # # 軌道情報
        # 時間
        self.time_orbit = np.arange(self.TIME_DAY_SEC * self.TIME_ORB_COUNT_DAY + self.TIME_ORB_SEC,
                            self.TIME_DAY_SEC * self.TIME_ORB_COUNT_DAY + self.TIME_ORB_SEC + self.TIME_INTERVAL * self.NUM_ORB_POINT,
                            self.TIME_INTERVAL)
        # 補完関数
        self.func_intp_orbit_x_recode_time = interp1d(self.time_orbit, self.position_vector[:, 0], kind='cubic', axis=0)
        self.func_intp_orbit_y_recode_time = interp1d(self.time_orbit, self.position_vector[:, 1], kind='cubic', axis=0)
        self.func_intp_orbit_z_recode_time = interp1d(self.time_orbit, self.position_vector[:, 2], kind='cubic', axis=0)
        
        # # 観測時間
        self.TIME_OBS_START_ = self.TIME_OBS_START_DAY + (self.TIME_OBS_START_MSEC / self.DIGIT4 + self.TIME_SHIFT) / self.TIME_DAY_SEC
        self.TIME_OBS_START_SEC = self.TIME_DAY_SEC * self.TIME_OBS_START_ + \
            (self.NUM_APERTURE_SAMPLE * .0) / self.FREQ_PULSE_REPETITION
        self.TIME_OBS_END_SEC = self.TIME_DAY_SEC * self.TIME_OBS_START_ + \
            (self.NUM_APERTURE_SAMPLE * 1.0) / self.FREQ_PULSE_REPETITION

        print("観測開始時刻 (秒):", self.TIME_OBS_START_SEC)
        print("観測終了時刻 (秒):", self.TIME_OBS_END_SEC)
        print("観測期間 (秒):", self.TIME_OBS_END_SEC - self.TIME_OBS_START_SEC)

        if plot:
            num_orb_counts = np.arange(0, self.NUM_ORB_POINT, 1)
            plt.figure(figsize=(12, 4), dpi=80, facecolor='w', edgecolor='k')
            plt.title('ALOS PALSAR `Sub` TimeSeries')
            plt.scatter(num_orb_counts, self.time_orbit, label='Orbit Recording Point')
            plt.plot(num_orb_counts, self.time_orbit, label='Orbit Recording Line', linestyle='-', color='b')
            # hrizontal line
            plt.axhline(y=self.TIME_OBS_START_SEC, color='r', linestyle='-', label='Start time')
            plt.axhline(y=self.TIME_OBS_END_SEC, color='g', linestyle='--', label='End time')
            plt.legend(loc='upper left')

            plt.xlabel('Sample Count [n]')
            plt.ylabel('Time [sec]')
            plt.tight_layout()
            plt.savefig(os.path.join(PATH_OUTPUT, f'orbit_timeseries_sub.png'), bbox_inches='tight', format='png', dpi=160)
            plt.show();plt.clf();plt.close()
        
        # 衛星の位置ベクトル
        self.TIMES_OBS = np.linspace(
            self.TIME_OBS_START_SEC, self.TIME_OBS_END_SEC, self.NUM_APERTURE_SAMPLE)
        self.P_X_SAT = self.func_intp_orbit_x_recode_time(self.TIMES_OBS)
        self.P_Y_SAT = self.func_intp_orbit_y_recode_time(self.TIMES_OBS)
        self.P_Z_SAT = self.func_intp_orbit_z_recode_time(self.TIMES_OBS)
        self.P_SAT = np.sqrt(self.P_X_SAT ** 2 + self.P_Y_SAT ** 2 + self.P_Z_SAT ** 2)
        
        # 衛星の速度ベクトル
        self.func_intp_orbit_vx_recode_time = interp1d(
            self.time_orbit, self.velocity_vector[:, 0], kind='cubic', axis=0)
        self.func_intp_orbit_vy_recode_time = interp1d(
            self.time_orbit, self.velocity_vector[:, 1], kind='cubic', axis=0)
        self.func_intp_orbit_vz_recode_time = interp1d(
            self.time_orbit, self.velocity_vector[:, 2], kind='cubic', axis=0)

        # 観測期間の衛星速度を取得
        self.V_X_SAT = self.func_intp_orbit_vx_recode_time(self.TIMES_OBS)
        self.V_Y_SAT = self.func_intp_orbit_vy_recode_time(self.TIMES_OBS)
        self.V_Z_SAT = self.func_intp_orbit_vz_recode_time(self.TIMES_OBS)

        self.DIS_GATE_DELAY = self.TIME_GATE_DELAY * self.SOL  
        print("受信ゲートの遅延距離 [m]: ", self.DIS_GATE_DELAY)

        # レンジ方向のサンプル距離計算
        self.DIS_RANGE_SLANT = self.SOL / (2. * self.FREQ_AD_SAMPLE)  # DELTA
        self.DIS_FAR_RANGE = self.DIS_NEAR_RANGE + (self.NUM_PIXEL - 1) * self.DIS_RANGE_SLANT
        # 電離層遅延補正
        # self.dis_ionosphere_delay = (TIME_IONSPHERE_DELAY * 1e-3) * self.SOL
        self.dis_ionosphere_delay = 0  # 電離層遅延補正を無効化
        print(f"電離層遅延補正距離: {self.dis_ionosphere_delay:.2f} m")
        self.DIS_NEAR_RANGE -= self.dis_ionosphere_delay
        self.DIS_FAR_RANGE -= self.dis_ionosphere_delay
        self.SLANT_RANGE_SAMPLE = np.linspace(
            self.DIS_NEAR_RANGE + self.DIS_GATE_DELAY,
            self.DIS_FAR_RANGE + self.DIS_GATE_DELAY,
            self.NUM_PIXEL)
        
        # 高度計算
        self.P_SAT_LATITUDE = np.arcsin(self.P_Z_SAT / self.P_SAT)
        self.SIN_SAT_LATITUDE, self.COS_SAT_LATITUDE = np.sin(self.P_SAT_LATITUDE), np.cos(self.P_SAT_LATITUDE)
        self.P_EARTH_RADIUS = np.divide(1.,
            np.sqrt(
                self.COS_SAT_LATITUDE ** 2 / self.DIS_ELLIPSOID_RADIUS ** 2 + 
                self.SIN_SAT_LATITUDE ** 2 / self.DIS_ELLIPSOID_SHORT_RADIUS ** 2
            ))
        self.HEIGHT_SAT = self.P_SAT - self.P_EARTH_RADIUS
        # .  self.P_EARTH_RADIU = re2 -> re_c 変数
        print(f"平均衛星高度: {np.mean(self.HEIGHT_SAT):.2f} m")
        if output_json_path:
            _write_observation_json(self, output_json_path)
            
    def execute_focus(self, ground_velocity=None, PATH_OUTPUT: str='./output'):
        """
        フォーカシングの実行（チャープスケーリング法）。

        SAR の生データに対してチャープスケーリング（Chirp Scaling, CS）アルゴリズムを適用し、
        レンジ方向とアジマス方向の補正・圧縮を行って複素画像を生成します。

        処理の流れ（概要）:
        1. 観測ジオメトリを準備し、衛星位置・速度から中心時刻の速度を推定します
           （ground_velocity が指定されている場合はその値で上書き）。
        2. レンジ時間軸 TAU とドップラ中心 F_DOPPLER_CENTROID を定義します。
        3. H1: チャープスケーリングによるレンジ方向の位相補正。
        4. H2: バルク RCMC とレンジ圧縮。
        5. H3: 角度補正（位相誤差補正）。
        6. H4: アジマス圧縮。
        7. FFT/IFFT を用いて周波数領域と時刻領域を往復し、最終的な複素画像を返します。

        Args:
            ground_velocity (Optional[float]): 地上速度の手動指定。None の場合は推定値を使用します。
            PATH_OUTPUT (str): ジオメトリ生成時の出力先フォルダ。

        Returns:
            np.ndarray: フォーカシング後の複素画像 (azimuth x range)。
        """
        
        # ensure geometry is ready
        if not hasattr(self, "SLANT_RANGE_SAMPLE"):
            self.set_geometory(plot=False, output_json_path=None, PATH_OUTPUT=PATH_OUTPUT)
        if not hasattr(self, "NUM_CHIRP_EXTENSION"):
            self.NUM_CHIRP_EXTENSION = 0
        if not hasattr(self, "NUM_VELOCITY_CALC_SPAN_COUNT"):
            self.NUM_VELOCITY_CALC_SPAN_COUNT = 4
        if not hasattr(self, "NUM_TMP_SAMPLE"):
            self.NUM_TMP_SAMPLE = 16
        if not hasattr(self, "NUM_VELOCITY_CALC_SAMPLE"):
            self.NUM_VELOCITY_CALC_SAMPLE = 8
        if not hasattr(self, "NUM_POLYNOMIAL_COEFFICIENT_DIM"):
            self.NUM_POLYNOMIAL_COEFFICIENT_DIM = 3

        # processing synthetic aperture radar data
        num_aperture = min(self.NUM_SIGNAL_RECORD, self.NUM_APERTURE_SAMPLE)
        num_chirp_extension = int(self.NUM_CHIRP_EXTENSION)
        F_FFT_RANGE = self.NUM_PIXEL + num_chirp_extension * 2

        # range calculation
        TIME_NEAR_RANGE = (2 * self.DIS_NEAR_RANGE / self.SOL)
        TAU = np.linspace(
            TIME_NEAR_RANGE,
            TIME_NEAR_RANGE + (F_FFT_RANGE) / self.FREQ_AD_SAMPLE,
            F_FFT_RANGE,
        )
        F_DOPPLER_CENTROID = 0.0

        # platform velocity (m/s): ground velocity at scene center
        time_obs_start_day = np.array(self.TIME_OBS_START_DAY, dtype=np.float64)
        time_obs_start_msec = np.array(self.TIME_OBS_START_MSEC, dtype=np.float64)
        # time_obs_end_day = np.array(self.TIME_OBS_END_DAY, dtype=np.float64)
        # time_obs_end_msec = np.array(self.TIME_OBS_END_MSEC, dtype=np.float64)

        time_obs_start_ = time_obs_start_day + (time_obs_start_msec / self.DIGIT4 + self.TIME_SHIFT) / self.TIME_DAY_SEC
        time_obs_start_center_sec = (
            self.TIME_DAY_SEC * time_obs_start_
            +0.5 * (num_aperture/2) / self.FREQ_PULSE_REPETITION
        )
        time_obs_end_center_sec = (
            time_obs_start_center_sec
            +(num_aperture/2) / self.FREQ_PULSE_REPETITION * 3
        )

        time_obs_cmd_center = (time_obs_start_center_sec + time_obs_end_center_sec) / 2.0
        num_velocity_calc_span_count = int(self.NUM_VELOCITY_CALC_SPAN_COUNT)
        time_delta_center_start = time_obs_cmd_center - (num_velocity_calc_span_count / 2.0)
        time_delta_center_end = time_obs_cmd_center + (num_velocity_calc_span_count / 2.0)

        p_sat_center_x = self.func_intp_orbit_x_recode_time(time_obs_cmd_center)
        p_sat_center_y = self.func_intp_orbit_y_recode_time(time_obs_cmd_center)
        p_sat_center_z = self.func_intp_orbit_z_recode_time(time_obs_cmd_center)
        p_sat_center_xyz = np.sqrt(p_sat_center_x ** 2 + p_sat_center_y ** 2 + p_sat_center_z ** 2)

        p_sat_delta_pre_center_x = self.func_intp_orbit_x_recode_time(time_delta_center_start)
        p_sat_delta_pre_center_y = self.func_intp_orbit_y_recode_time(time_delta_center_start)
        p_sat_delta_pre_center_z = self.func_intp_orbit_z_recode_time(time_delta_center_start)
        p_sat_delta_post_center_x = self.func_intp_orbit_x_recode_time(time_delta_center_end)
        p_sat_delta_post_center_y = self.func_intp_orbit_y_recode_time(time_delta_center_end)
        p_sat_delta_post_center_z = self.func_intp_orbit_z_recode_time(time_delta_center_end)

        v_sat_center_x = (p_sat_delta_post_center_x - p_sat_delta_pre_center_x) / num_velocity_calc_span_count
        v_sat_center_y = (p_sat_delta_post_center_y - p_sat_delta_pre_center_y) / num_velocity_calc_span_count
        v_sat_center_z = (p_sat_delta_post_center_z - p_sat_delta_pre_center_z) / num_velocity_calc_span_count
        v_sat_center_xyz = np.sqrt(v_sat_center_x ** 2 + v_sat_center_y ** 2 + v_sat_center_z ** 2)

        p_sat_center_xyz_3dim = np.array(
            [p_sat_center_x, p_sat_center_y, p_sat_center_z], dtype=np.float64) / p_sat_center_xyz
        v_sat_center_xyz_3dim = np.array(
            [v_sat_center_x, v_sat_center_y, v_sat_center_z], dtype=np.float64) / v_sat_center_xyz
        p_sat_cross_product_3dim = np.array([
            p_sat_center_xyz_3dim[1] * v_sat_center_xyz_3dim[2] - p_sat_center_xyz_3dim[2] * v_sat_center_xyz_3dim[1],
            p_sat_center_xyz_3dim[2] * v_sat_center_xyz_3dim[0] - p_sat_center_xyz_3dim[0] * v_sat_center_xyz_3dim[2],
            p_sat_center_xyz_3dim[0] * v_sat_center_xyz_3dim[1] - p_sat_center_xyz_3dim[1] * v_sat_center_xyz_3dim[0],
        ])

        p_sat_latitude = np.arcsin(p_sat_center_z / p_sat_center_xyz)
        sin_sat_latitude = np.sin(p_sat_latitude)
        cos_sat_latitude = np.cos(p_sat_latitude)
        p_earth_radius = np.divide(1.0,
                                   np.sqrt(
                                       cos_sat_latitude ** 2 / self.DIS_ELLIPSOID_RADIUS ** 2 + 
                                       sin_sat_latitude ** 2 / self.DIS_ELLIPSOID_SHORT_RADIUS ** 2
                                   ))

        theta_sat_center_cosine_law = (p_sat_center_xyz ** 2 + self.DIS_NEAR_RANGE ** 2 - p_earth_radius ** 2) / (
            2.0 * p_sat_center_xyz * self.DIS_NEAR_RANGE
        )
        theta_sat_center_sin = np.sin(np.arccos(theta_sat_center_cosine_law))

        p_earth_radius_center_x = p_sat_center_x + self.DIS_NEAR_RANGE * (
            -theta_sat_center_sin * p_sat_cross_product_3dim[0] - theta_sat_center_cosine_law * p_sat_center_xyz_3dim[0]
        )
        p_earth_radius_center_y = p_sat_center_y + self.DIS_NEAR_RANGE * (
            -theta_sat_center_sin * p_sat_cross_product_3dim[1] - theta_sat_center_cosine_law * p_sat_center_xyz_3dim[1]
        )
        p_earth_radius_center_z = p_sat_center_z + self.DIS_NEAR_RANGE * (
            -theta_sat_center_sin * p_sat_cross_product_3dim[2] - theta_sat_center_cosine_law * p_sat_center_xyz_3dim[2]
        )

        num_tmp_sample = int(self.NUM_TMP_SAMPLE)
        idx_tmp_center = np.arange(0, num_tmp_sample, 1, dtype=np.int64) - num_tmp_sample / 2
        time_tmp_center = idx_tmp_center * 100.0 / self.FREQ_PULSE_REPETITION * 2
        time_tmp_start0 = time_obs_cmd_center + time_tmp_center
        p_sat_center_tmp_x = self.func_intp_orbit_x_recode_time(time_tmp_start0)
        p_sat_center_tmp_y = self.func_intp_orbit_y_recode_time(time_tmp_start0)
        p_sat_center_tmp_z = self.func_intp_orbit_z_recode_time(time_tmp_start0)

        p_difference_flat_slant = np.sqrt(
            (p_earth_radius_center_x - p_sat_center_tmp_x) ** 2 + 
            (p_earth_radius_center_y - p_sat_center_tmp_y) ** 2 + 
            (p_earth_radius_center_z - p_sat_center_tmp_z) ** 2
        ) - self.DIS_NEAR_RANGE

        num_velocity_calc_sample = int(self.NUM_VELOCITY_CALC_SAMPLE)
        num_polynomial_coeff_dim = int(self.NUM_POLYNOMIAL_COEFFICIENT_DIM)
        van = np.vander(
            time_tmp_center[:num_velocity_calc_sample],
            (num_polynomial_coeff_dim + 1),
            increasing=True,
        )
        polynominal_coeff = np.linalg.lstsq(
            van,
            p_difference_flat_slant[:num_velocity_calc_sample],
            rcond=None
        )[0]
        v_est = np.sqrt(2.0 * self.DIS_NEAR_RANGE * polynominal_coeff[2])
        
        if ground_velocity is not None:
            print(f"Indicete ground velocity: {ground_velocity:.2f} <-> [m/s] Estimated velocity: {v_est:.2f} [m/s]")
            v = ground_velocity
        else:
            print(f"--> Estimated velocity: {v_est:.2f} [m/s]")
            v = np.sqrt(2.0 * self.DIS_NEAR_RANGE * polynominal_coeff[2])
            
        B = -self.range_pulse_amplitude2 * self.TIME_PLUSE_DURATION

        DIS_SLANT_RANGE = (
            self.DIS_NEAR_RANGE
            + (F_FFT_RANGE) / self.FREQ_AD_SAMPLE * self.SOL / 4
        )
        ALPHA = 1.0
        f_a = np.linspace(
            -self.FREQ_PULSE_REPETITION / 2 + F_DOPPLER_CENTROID,
            F_DOPPLER_CENTROID + self.FREQ_PULSE_REPETITION / 2,
            num_aperture,
        )
        f_r = np.linspace(
            -self.FREQ_AD_SAMPLE / 2,
            self.FREQ_AD_SAMPLE / 2,
            F_FFT_RANGE,
        )
        
        # parameter check
        print(f"Ground velocity v: {v:.2f} m/s")
        print(f"Reference range DIS_SLANT_RANGE: {DIS_SLANT_RANGE:.2f} m")
        print(f"Chirp bandwidth B: {B/1e6:.2f} MHz")
        print(f"Chirp duration t_p: {self.TIME_PLUSE_DURATION*1e6:.2f} µsec")
        print(f"Radar wavelength λ: {self.LAMBDA:.4f} m")
        print(f"Number of aperture samples: {num_aperture}")
        print(f"Number of range samples (with extension): {F_FFT_RANGE}")

        data = np.zeros((num_aperture, F_FFT_RANGE), dtype=np.complex64)
        data[:num_aperture, num_chirp_extension:num_chirp_extension + self.NUM_PIXEL] = self.signal[:num_aperture,:]

        # azimuth fft
        for idx_axis in tqdm(range(data.shape[1]),
                             total=data.shape[1], desc="Azimuth FFT", leave=False):
            data[:, idx_axis] = np.fft.fftshift(
                np.fft.fft(np.fft.fftshift(data[:, idx_axis])))

        data[num_aperture // 2,:] = 0

        # chirp scaling, range scaling: H1
        BETA = (1 - (f_a * self.LAMBDA / 2 / v) ** 2) ** 0.5
        R = DIS_SLANT_RANGE / BETA
        A_SCALING = (
            (1.0 / BETA - 1.0)
            + ((1.0 - ALPHA) * (1.0 / BETA)) / ALPHA
        )
        K_CHIRP_RATIO = -(B / self.TIME_PLUSE_DURATION)

        K_CHIRP_RATIO_INVERSE = 1 / K_CHIRP_RATIO - (
            2 * self.LAMBDA * DIS_SLANT_RANGE * (BETA ** 2 - 1)
        ) / (self.SOL ** 2 * (BETA ** 3))
        K = 1 / K_CHIRP_RATIO_INVERSE

        TAU = np.asarray(TAU, dtype=np.float32)
        H1 = np.exp(
            -1j
            * np.pi
            * np.asarray(K * A_SCALING, dtype=np.float32)[:, None]
            * (TAU[None, :] - np.asarray(2.0 * R / self.SOL, dtype=np.float32)[:, None]) ** 2
        )
        data = data * H1

        del H1
        gc.collect()

        # range fft
        for idx_axis in tqdm(range(data.shape[0]),
                             total=data.shape[0], desc="Range FFT", leave=False):
            data[idx_axis,:] = np.fft.fftshift(
                np.fft.fft(np.fft.fftshift(data[idx_axis,:])))

        # bulk rcmc, range compression: H2
        echoes_i = int(np.asarray(A_SCALING).size)
        f_r_sq = f_r * f_r

        for i in tqdm(range(echoes_i),
                      total=echoes_i, desc="H2 row-wise", leave=False):
            h2_i = np.exp(
                -1j * np.pi
                * (1.0 / (K[i] * (1.0 + A_SCALING[i])))
                * f_r_sq
            ) * np.exp(
                1j
                * 4.0
                * np.pi
                * DIS_SLANT_RANGE
                / self.SOL
                * (f_r * (1.0 / BETA[i] - 1.0))
            )
            data[i,:] = data[i,:] * h2_i

        del h2_i, f_r_sq
        gc.collect()

        # range ifft
        for idx_axis in tqdm(range(data.shape[0]),
                             total=data.shape[0], desc="Range IFFT", leave=False):
            data[idx_axis,:] = np.fft.fftshift(
                np.fft.ifft(np.fft.fftshift(data[idx_axis,:])))

        # angle correction: H3
        R_ZERO = 0.5 * self.SOL * np.asarray(TAU)
        R_ZERO_DELTA_SQ = (R_ZERO - DIS_SLANT_RANGE) ** 2

        for i in tqdm(range(echoes_i),
                      total=echoes_i, desc="H3 row-wise", leave=False):
            dphi_i = 4.0 * np.pi * (
                K[i]
                * A_SCALING[i]
                * (1.0 / BETA[i]) ** 2
                / (self.SOL ** 2 * (1.0 + A_SCALING[i]))
            ) * R_ZERO_DELTA_SQ
            h3_i = np.exp(1j * dphi_i)
            data[i,:] = data[i,:] * h3_i

        del h3_i, R_ZERO_DELTA_SQ
        gc.collect()

        # azimuth compression: H4
        R_ZERO = np.asarray(R_ZERO, dtype=np.float64)
        ALPHAS = np.asarray(ALPHA, dtype=np.float64)

        for i in tqdm(range(echoes_i),
                      total=echoes_i, desc="H4 row-wise", leave=False):
            alpha_i = (ALPHAS if ALPHAS.ndim == 0 else ALPHAS[i])
            R_ZERO_SCALING_i = DIS_SLANT_RANGE + (R_ZERO - DIS_SLANT_RANGE) / alpha_i
            h4_i = np.exp(
                1j
                * 4.0
                * np.pi
                / self.LAMBDA
                * R_ZERO_SCALING_i
                * (BETA[i] - 1.0)
            )
            data[i,:] = data[i,:] * h4_i

        del h4_i, R_ZERO, ALPHAS
        gc.collect()

        # azimuth ifft
        for idx_axis in tqdm(range(data.shape[1]),
                             total=data.shape[1], desc="Azimuth IFFT", leave=False):
            data[:, idx_axis] = np.fft.fftshift(
                np.fft.ifft(np.fft.fftshift(data[:, idx_axis])))
        return data[:, num_chirp_extension:num_chirp_extension + self.NUM_PIXEL]

# 外部で定義されている想定
# PATH_OUTPUT = "..."
# TIME_IONSPHERE_DELAY = 0.0  # [msec] → ジオメトリ計算で 0 にしています


class CEOS_PALSAR_L11_SLC(object):
    """
    CEOS PALSAR Level 1.1 SLC reader.

    Parses ALOS PALSAR Level 1.1 CEOS products and exposes SLC data and metadata.
    """

    TIME_DAY_HOUR = 24
    TIME_DAY_MINITE = 60
    TIME_MINITE_SEC = 60
    TIME_DAY_SEC = TIME_DAY_HOUR * TIME_DAY_MINITE * TIME_MINITE_SEC  # sec
    SOL = 299792458.0  # m/s speed of light

    DIGIT4 = 1000.

    BYTE1 = 1
    BYTE2 = 2
    INTERGER4 = 4
    INTERGER6 = 6
    FLOAT16 = 16  # 16 バイト浮動小数 (F16.7 など)
    FLOAT22 = 22  # E22.15 など
    FLOAT32 = 32
    FLOAT64 = 64

    NUM_VELOCITY_CALC_SPAN_COUNT: int = 4

    def __init__(
        self,
        PATH_CEOS_FOLDER: str,
        POLARIMETORY: str="HH",
        ORBIT_NAME: str="A",
    ):
        """
        Initialize CEOS Format Reader (PALSAR Level 1.1/1.5)

        Args:
            PATH_CEOS_FOLDER (str): CEOS プロダクトが展開されているフォルダ
                                    例: ALPSRP021160650-L1.1/
            POLARIMETORY (str, optional): 偏波名 'HH', 'HV', 'VV', 'VH'.
            ORBIT_NAME (str, optional): 軌道名 'A' or 'D'.
        """

        self.PATH_CEOS_FOLDER = PATH_CEOS_FOLDER
        self.POLARIMETORY = POLARIMETORY
        self.ORBIT_NAME = ORBIT_NAME

        # 代表的なファイル名パターン
        # 実データに合わせて必要なら調整してください。
        # 例: IMG-HH-ALPSRP021160650-L1.1__A, LED-ALPSRP021160650-L1.1__A
        self.PATH_CEOS_FILE_NAME_BASE = os.path.basename(PATH_CEOS_FOLDER)[:-3]  # 例: ALPSRP021160650-L1.1

        self.PATH_IMG = os.path.join(
            self.PATH_CEOS_FOLDER,
            f"IMG-{self.POLARIMETORY}-{self.PATH_CEOS_FILE_NAME_BASE}__{self.ORBIT_NAME}",
        )
        self.PATH_LED = os.path.join(
            self.PATH_CEOS_FOLDER,
            f"LED-{self.PATH_CEOS_FILE_NAME_BASE}__{self.ORBIT_NAME}",
        )

        # ファイル存在チェック
        if not os.path.exists(self.PATH_IMG) or not os.path.exists(self.PATH_LED):
            raise FileNotFoundError(
                f"--->>> {self.PATH_IMG} or {self.PATH_LED} does not exist "
                "(L1.1 用の場合はファイル名パターンを適宜修正してください)"
            )

        # ------------------------------------------------------
        # IMG File Reader (イメージファイル / シグナルデータ用)
        # ------------------------------------------------------
        f = open(self.PATH_IMG, "rb")

        # イメージファイルディスクリプタレコード
        f.seek(8)
        self.NUM_SAR_DISCRIPTOR_RECORD = int.from_bytes(
            f.read(self.INTERGER4), byteorder="big"
        )
        print("IMG: B9-12 レコード長 = 720 ->", self.NUM_SAR_DISCRIPTOR_RECORD)

        # --- Level 1.1 の追加情報: サンプルグループフォーマット ---
        # 217-220 I4 サンプル当たりのビット長
        # 221-224 I4 データグループ当たりのサンプル数
        # 225-228 I4 データグループ当たりのバイト数
        #   レベル1.1: 32bit, 2 sample/group (I,Q), 8byte/group
        f.seek(216)  # Byte 217 の 0-origin offset
        # self.bits_per_sample = int.from_bytes(f.read(self.INTERGER4), "big")
        # self.samples_per_group = int.from_bytes(f.read(self.INTERGER4), "big")
        # self.bytes_per_group = int.from_bytes(f.read(self.INTERGER4), "big")
        # print("IMG: bits/sample ->", self.bits_per_sample)
        # print("IMG: samples/group ->", self.samples_per_group)
        # print("IMG: bytes/group ->", self.bytes_per_group)
        # bits/sample (I4)
        bits_per_sample_bytes = f.read(4)
        self.bits_per_sample = int(bits_per_sample_bytes.decode('ascii').strip())
        print("IMG: bits/sample ->", self.bits_per_sample)

        # samples/group (I4)
        samples_per_group_bytes = f.read(4)
        self.samples_per_group = int(samples_per_group_bytes.decode('ascii').strip())
        print("IMG: samples/group ->", self.samples_per_group)

        # bytes/group (I4)
        bytes_per_group_bytes = f.read(4)
        self.bytes_per_group = int(bytes_per_group_bytes.decode('ascii').strip())
        print("IMG: bytes/group ->", self.bytes_per_group)

        # 276-280 I4 レコードあたりの PREFIX DATA のバイト数
        f.seek(276)
        self.NUM_PREFIX = int(f.read(self.INTERGER4))
        print("IMG: B277-280 PREFIX DATA bytes/record ->", self.NUM_PREFIX)

        # 181-186 I6 SARデータレコード数（レンジライン数）
        f.seek(180)
        self.NUM_SIGNAL_RECORD = int(f.read(self.INTERGER6))
        print("IMG: B181-186 SARデータレコード数 ->", self.NUM_SIGNAL_RECORD)

        # 187-192 I6 SARデータレコード長（ゼロサプレス後）
        f.seek(186)
        self.signal_record_length = int(f.read(self.INTERGER6))
        print("IMG: B187-192 SARデータレコード長 ->", self.signal_record_length)

        print(f"{'='*10} IMG Header (prefix={self.NUM_PREFIX}) {'='*10}")

        # 49-50 B2 SAR チャンネル ID
        f.seek(48 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.pol = int.from_bytes(f.read(self.BYTE2), byteorder="big")
        print("IMG: B49-50 SARチャンネルID ->", self.pol)

        # 9-12 B4 レコード長
        f.seek(8 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.record_length = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B9-12 レコード長（シグナルレコード長） ->", self.record_length)

        # 13-16 B4 SAR画像データライン番号
        f.seek(12 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.azimuth_line = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B13-16 SAR画像データライン番号 ->", self.azimuth_line)

        # 17-20 B4 SAR画像データレコードインデックス
        f.seek(16 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.sar_image_index = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B17-20 SAR画像データレコードインデックス ->", self.sar_image_index)

        # 25-28 B4 実際のデータピクセル数 (1レンジラインのピクセル数)
        f.seek(24 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.NUM_PIXEL = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B25-28 実際のデータピクセル数 ->", self.NUM_PIXEL)

        # 29-32 B4 実際の右詰めの数 (レベル1.1では 0)
        f.seek(28 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.NUM_BLANK_PIXEL = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B29-32 実際の右詰めのピクセル数 ->", self.NUM_BLANK_PIXEL)

        # 57-60 B4 PRF [mHz]
        f.seek(56 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.prf = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B57-60 PRF [mHz] ->", self.prf)

        # 以下のチャープ関連はレベル1.0と同一 Byte 位置（仕様書の「レベル1.0の値をコピー」）
        f.seek(66 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.chirp = int.from_bytes(f.read(self.BYTE2), byteorder="big")
        print("IMG: B67-68 チャープ形式指定者 ->", self.chirp)

        f.seek(68 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.chirp_length = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B69-72 チャープ長(パルス幅) nsec ->", self.chirp_length)

        f.seek(72 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.chirp_const = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B73-76 チャープ定数係数 Hz ->", self.chirp_const)

        f.seek(76 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.chirp_coeff = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B77-80 チャープ一次係数 Hz/μsec ->", self.chirp_coeff)

        f.seek(80 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.chirp_coeff2 = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B81-84 チャープ二次係数 Hz/μsec^2 ->", self.chirp_coeff2)

        # 93-96 B4 受信機ゲイン (dB)
        f.seek(92 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.gain = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B93-96 受信機ゲイン dB ->", self.gain)

        # 117-120 B4 最初のデータまでのスラントレンジ (m)
        f.seek(116 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.DIS_NEAR_RANGE = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B117-120 最初のデータまでのスラントレンジ [m] ->", self.DIS_NEAR_RANGE)

        # 121-124 B4 SAMPLE DELAY (nsec)
        # レベル1.1 では 0 が格納される (仕様書より)
        f.seek(120 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.TIME_GATE_DELAY_T = int.from_bytes(
            f.read(self.INTERGER4), byteorder="big"
        )
        print("IMG: B121-124 SAMPLE DELAY [nsec] ->", self.TIME_GATE_DELAY_T)

        if self.TIME_GATE_DELAY_T == 0:
            # Level 1.1 仕様では 0 固定。ゲートオフセットは 0 とみなす
            self.TIME_GATE_DELAY = 0.0
        else:
            # レベル1.0 と同じ式（念のため残しておく）
            self.TIME_GATE_DELAY = (self.TIME_GATE_DELAY_T - 8315.39) / 1e9
        print("  -> TIME_GATE_DELAY [sec] =", self.TIME_GATE_DELAY)

        # シグナルデータレコードのループ
        f.seek(self.NUM_SAR_DISCRIPTOR_RECORD)
        print("Num of Range: ", self.NUM_PIXEL, "Num of Azimuth Line: ", self.NUM_SIGNAL_RECORD)
        
        self.signal = np.zeros((self.NUM_SIGNAL_RECORD, self.NUM_PIXEL), dtype=np.complex64)
        
        for i in tqdm(range(self.NUM_SIGNAL_RECORD)):
            if i == 0:
                print(f"{'='*10} Start Time {'='*10}")
                # 1-36 バイトをまとめて読み飛ばし
                _ = f.read(36)
                # 37-40 年
                self.TIME_OBS_START_YEAR = int.from_bytes(
                    f.read(self.INTERGER4), "big"
                )
                print("IMG: B37-40 センサー取得年 ->", self.TIME_OBS_START_YEAR)
                # 41-44 通算日
                self.TIME_OBS_START_DAY = int.from_bytes(
                    f.read(self.INTERGER4), "big"
                )
                print("IMG: B41-44 センサー取得日(通算) ->", self.TIME_OBS_START_DAY)
                # 45-48 ミリ秒
                self.TIME_OBS_START_MSEC = int.from_bytes(
                    f.read(self.INTERGER4), "big"
                )
                print("IMG: B45-48 センサー取得ミリ秒 ->", self.TIME_OBS_START_MSEC)

                # --- L1.1の追加情報 ---
                self.sar_channel_id = int.from_bytes(f.read(self.BYTE2), "big")
                self.sar_channel_code = int.from_bytes(f.read(self.BYTE2), "big")
                self.tx_polarization_code = int.from_bytes(f.read(self.BYTE2), "big")
                self.rx_polarization_code = int.from_bytes(f.read(self.BYTE2), "big")
                print("IMG Prefix: SARチャンネルID ->", self.sar_channel_id)
                print("IMG Prefix: SARチャンネルコード ->", self.sar_channel_code)
                print("IMG Prefix: Tx偏波コード ->", self.tx_polarization_code)
                print("IMG Prefix: Rx偏波コード ->", self.rx_polarization_code)

                # ここまでで Byte56 まで消費
                # 残りの prefix を読み飛ばし
                _ = f.read(self.NUM_PREFIX - (36 + 4 * 3 + 4 * 2))

            elif i == self.NUM_SIGNAL_RECORD - 1:
                print(f"{'='*10} End Time {'='*10}")
                _ = f.read(36)
                self.TIME_OBS_END_YEAR = int.from_bytes(f.read(self.INTERGER4), "big")
                print("IMG: B37-40 センサー取得年 ->", self.TIME_OBS_END_YEAR)
                self.TIME_OBS_END_DAY = int.from_bytes(f.read(self.INTERGER4), "big")
                print("IMG: B41-44 センサー取得日(通算) ->", self.TIME_OBS_END_DAY)
                self.TIME_OBS_END_MSEC = int.from_bytes(f.read(self.INTERGER4), "big")
                print("IMG: B45-48 センサー取得ミリ秒 ->", self.TIME_OBS_END_MSEC)

                # SAR チャンネル等は開始時と同じとみなして読み飛ばし
                _ = f.read(2 + 2 + 2 + 2)  # 49-56
                _ = f.read(self.NUM_PREFIX - (36 + 4 * 3 + 4 * 2))
            else:
                # 中間ラインの prefix
                _ = f.read(self.NUM_PREFIX)

            # =========================
            # データ部 (SLC L1.1 本体)
            # =========================

            # L1.1 の 1 ピクセルは 32bit(I) + 32bit(Q) = 8 byte のはず
            if self.bytes_per_group != 8:
                raise ValueError(
                    f"L1.1 SLC の 1 ピクセルは 8 byte のはずですが "
                    f"bytes_per_group={self.bytes_per_group} になっています。"
                )

            # 実データピクセル数分のバイト列を読み込む
            n_pix = self.NUM_PIXEL  # 実際のデータピクセル数 (ニア→ファー)
            n_bytes = n_pix * self.bytes_per_group

            buf = f.read(n_bytes)
            if len(buf) != n_bytes:
                raise IOError(
                    f"SAR データの読み込みに失敗しました: 期待 {n_bytes} byte, 実際 {len(buf)} byte"
                )

            # Big Endian float32 で I, Q を読む
            # buf の並び: I0, Q0, I1, Q1, ... (32bit float, Big Endian)
            iq = np.frombuffer(buf, dtype=">f4")  # Big Endian float32
            if iq.size != 2 * n_pix:
                raise IOError(
                    f"ピクセル数不整合: 期待 {2*n_pix} 要素, 実際 {iq.size} 要素"
                )

            iq = iq.astype(np.float32, copy=False).reshape(-1, 2)
            i_real = iq[:, 0]
            q_imag = iq[:, 1]

            # 複素数にして self.signal の 1 ラインに格納
            self.signal[i,:] = i_real + 1j * q_imag

            # 右詰めピクセル (レベル1.1では通常 0)
            if self.NUM_BLANK_PIXEL > 0:
                _ = f.read(self.NUM_BLANK_PIXEL * self.bytes_per_group)

        f.close()

        f.close()

        # ------------------------------------------------------
        # LED File Reader (リーダファイル)
        #   レベル1.1でも基本構造はレベル1.0と同じ
        #   一部、ライン/ピクセルスペーシング等の追加フィールドあり
        # ------------------------------------------------------
        f = open(self.PATH_LED, "rb")

        # 表3.3-4 SARリーダファイルディスクリプタレコード
        f.seek(8)
        self.record_length = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        f.seek(180)
        self.summary_record = int(f.read(self.INTERGER6))
        print("LED: データセットサマリレコード数 ->", self.summary_record)
        f.seek(186)
        self.summary_record_length = int(f.read(self.INTERGER6))
        print("LED: データセットサマリレコード長 ->", self.summary_record_length)
        f.seek(192)
        self.map_record = int(f.read(self.INTERGER6))
        print("LED: 地図投影データレコード数 ->", self.map_record)
        f.seek(198)
        self.map_record_length = int(f.read(self.INTERGER6))
        print("LED: 地図投影データレコード長 ->", self.map_record_length)
        f.seek(210)
        self.platform_record_length = int(f.read(self.INTERGER6))
        print("LED: プラットフォーム位置データレコード長 ->", self.platform_record_length)
        f.seek(222)
        self.attitude_record_length = int(f.read(self.INTERGER6))
        print("LED: 姿勢データレコード長 ->", self.attitude_record_length)
        f.seek(234)
        self.radiometric_record_length = int(f.read(self.INTERGER6))
        print("LED: ラジオメトリックデータレコード長 ->", self.radiometric_record_length)
        f.seek(246)
        self.radiometric_comp_record_length = int(f.read(self.INTERGER6))
        print("LED: ラジオメトリック補償レコード長 ->", self.radiometric_comp_record_length)
        f.seek(258)
        self.data_quality_record_length = int(f.read(self.INTERGER6))
        print("LED: データ品質サマリレコード長 ->", self.data_quality_record_length)
        f.seek(270)
        self.data_histogram_record_length = int(f.read(self.INTERGER6))
        print("LED: データヒストグラムレコード長 ->", self.data_histogram_record_length)
        f.seek(282)
        self.range_spectrum_record_length = int(f.read(self.INTERGER6))
        print("LED: レンジスペクトルレコード長 ->", self.range_spectrum_record_length)
        f.seek(294)
        self.dem_record_length = int(f.read(self.INTERGER6))
        print("LED: DEMディスクリプタレコード長 ->", self.dem_record_length)
        f.seek(342)
        self.calibration_record_length = int(f.read(self.INTERGER6))
        print("LED: キャリブレーションレコード長 ->", self.calibration_record_length)

        # 表3.3-5 データセットサマリレコード
        f.seek(self.record_length + 8)
        self.summary_record_length = int.from_bytes(
            f.read(self.INTERGER4), byteorder="big"
        )
        print("LED: データセットサマリレコード長(B4) ->", self.summary_record_length)

        f.seek(self.record_length + 20)
        self.scene_id = f.read(self.FLOAT32).decode("utf-8")
        print("LED: シーンID ->", self.scene_id)

        f.seek(self.record_length + 68)
        self.scene_time = f.read(self.FLOAT32).decode("utf-8")
        print("LED: シーンセンター時刻 ->", self.scene_time)

        f.seek(self.record_length + 164)
        self.ellipsoid_model = f.read(self.FLOAT16).decode("utf-8")
        print("LED: 楕円体モデル ->", self.ellipsoid_model)

        f.seek(self.record_length + 180)
        self.ellipsoid_radius = float(f.read(self.FLOAT16))
        print("LED: 楕円体の半長径(Km) ->", self.ellipsoid_radius)

        f.seek(self.record_length + 196)
        self.ellipsoid_short_radius = float(f.read(self.FLOAT16))
        print("LED: 楕円体の短半径(Km) ->", self.ellipsoid_short_radius)

        f.seek(self.record_length + 212)
        self.earth_mass = float(f.read(self.FLOAT16))
        print("LED: 地球の質量(10^24 Kg) ->", self.earth_mass)

        f.seek(self.record_length + 244)
        self.j2 = float(f.read(self.FLOAT16))
        self.j3 = float(f.read(self.FLOAT16))
        self.j4 = float(f.read(self.FLOAT16))
        print("LED: J2 ->", self.j2)
        print("LED: J3 ->", self.j3)
        print("LED: J4 ->", self.j4)

        f.seek(self.record_length + 308)
        self.ellipsoid_mean = f.read(self.FLOAT16)
        print("LED: シーン中央の平均的な地形標高 ->", self.ellipsoid_mean)

        f.seek(self.record_length + 388)
        self.sar_channel = int(f.read(self.INTERGER4))
        print("LED: SARチャネル数 ->", self.sar_channel)

        f.seek(self.record_length + 396)
        self.sensor_platform = f.read(self.FLOAT16).decode("utf-8")
        print("LED: センサプラットフォーム名 ->", self.sensor_platform)

        f.seek(self.record_length + 500)
        self.LAMBDA = float(f.read(16))
        print("LED: 波長 λ ->", self.LAMBDA)

        f.seek(self.record_length + 516)
        self.motion_compensation = f.read(self.BYTE2).decode("utf-8")
        print("LED: Motion compensation indicator ->", self.motion_compensation)

        f.seek(self.record_length + 518)
        self.range_pulse_code = f.read(self.FLOAT16).decode("utf-8")
        print("LED: レンジパルスコード ->", self.range_pulse_code)

        f.seek(self.record_length + 534)
        self.range_pulse_amplitude = float(f.read(self.FLOAT16))
        self.range_pulse_amplitude2 = float(f.read(self.FLOAT16))
        self.range_pulse_amplitude3 = float(f.read(self.FLOAT16))
        self.range_pulse_amplitude4 = float(f.read(self.FLOAT16))
        self.range_pulse_amplitude5 = float(f.read(self.FLOAT16))
        print("LED: レンジパルス振幅係数1 ->", self.range_pulse_amplitude)
        print("LED: レンジパルス振幅係数2 ->", self.range_pulse_amplitude2)
        print("LED: レンジパルス振幅係数3 ->", self.range_pulse_amplitude3)
        print("LED: レンジパルス振幅係数4 ->", self.range_pulse_amplitude4)
        print("LED: レンジパルス振幅係数5 ->", self.range_pulse_amplitude5)

        f.seek(self.record_length + 710)
        self.sampling_frequency_mhz = float(f.read(self.FLOAT16))
        print("LED: サンプリング周波数(MHz) ->", self.sampling_frequency_mhz)

        f.seek(self.record_length + 726)
        self.range_gate = float(f.read(self.FLOAT16))
        print("LED: レンジゲート(μsec) ->", self.range_gate)

        f.seek(self.record_length + 742)
        self.range_pulse_width = float(f.read(self.FLOAT16))
        print("LED: レンジパルス幅(μsec) ->", self.range_pulse_width)

        f.seek(self.record_length + 806)
        self.quantization_descriptor = f.read(12).decode("utf-8")
        print("LED: 量子化記述子 ->", self.quantization_descriptor)

        f.seek(self.record_length + 818)
        self.DC_BIAS_I = float(f.read(self.FLOAT16))
        self.DC_BIAS_Q = float(f.read(self.FLOAT16))
        self.gain_imbalance = float(f.read(self.FLOAT16))
        print("LED: I成分DCバイアス ->", self.DC_BIAS_I)
        print("LED: Q成分DCバイアス ->", self.DC_BIAS_Q)
        print("LED: I/Qゲイン不均衡 ->", self.gain_imbalance)

        f.seek(self.record_length + 898)
        self.electronic_boresight = float(f.read(self.FLOAT16))
        print("LED: electronic boresight ->", self.electronic_boresight)

        f.seek(self.record_length + 914)
        self.mechanical_boresight = float(f.read(self.FLOAT16))
        print("LED: mechanical boresight ->", self.mechanical_boresight)

        f.seek(self.record_length + 934)
        self.prf = float(f.read(self.FLOAT16))
        print("LED: PRF(mHz) ->", self.prf)

        f.seek(self.record_length + 950)
        self.beam_width_elevation = float(f.read(self.FLOAT16))
        self.beam_width_azimuth = float(f.read(self.FLOAT16))
        print("LED: 2wayビーム幅(El) ->", self.beam_width_elevation)
        print("LED: 2wayビーム幅(Az) ->", self.beam_width_azimuth)

        f.seek(self.record_length + 982)
        self.binary_time = int(f.read(self.FLOAT16))
        self.clock_time = f.read(self.FLOAT32).decode("utf-8")
        self.clock_increase = int(f.read(self.FLOAT16))
        print("LED: 衛星バイナリ時刻コード ->", self.binary_time)
        print("LED: 衛星クロック時刻 ->", self.clock_time)
        print("LED: クロック増加量[nsec] ->", self.clock_increase)

        f.seek(self.record_length + 1534)
        self.time_index = f.read(8).decode("utf-8")
        print("LED: 時間方向指標 ->", self.time_index)

        f.seek(self.record_length + 1802)
        self.prf_change_flag = f.read(self.INTERGER4).decode("utf-8")
        print("LED: PRF変化点フラグ ->", self.prf_change_flag)

        f.seek(self.record_length + 1806)
        self.prf_change_line = int(f.read(8))
        print("LED: PRF変化開始ライン番号 ->", self.prf_change_line)

        f.seek(self.record_length + 1830)
        self.yaw_steering_flag = f.read(self.INTERGER4).decode("utf-8")
        print("LED: ヨーステアリング有無 ->", self.yaw_steering_flag)

        f.seek(self.record_length + 1838)
        self.off_nadir_angle = float(f.read(self.FLOAT16))
        print("LED: オフナディア角 ->", self.off_nadir_angle)

        f.seek(self.record_length + 1854)
        self.antenna_beam_number = int(f.read(self.INTERGER4))
        print("LED: アンテナビーム番号 ->", self.antenna_beam_number)

        # --- Level 1.1 追加: レンジ/アジマスのスペーシングなど ---
        # 1671-1678 CH RANGE/OTHER
        # 1679-1682 CH YES/NO 等
        # 1683-1686 CH NOT 等
        # 1687-1702 F16.7 ラインスペーシング(m) (Az spacing)
        # 1703-1718 F16.7 ピクセルスペーシング(m) (Range spacing)
        # 1719-1734 CH 'EXTRACTEDbCHIRPb'
        f.seek(self.record_length + 1670)
        self.range_processing_mode = f.read(8).decode("utf-8")
        self.azimuth_look_flag = f.read(4).decode("utf-8")
        self.range_look_flag = f.read(4).decode("utf-8")
        self.line_spacing = float(f.read(self.FLOAT16))
        self.pixel_spacing = float(f.read(self.FLOAT16))
        self.chirp_extraction_mode = f.read(16).decode("utf-8")

        print("LED: RANGE/OTHER ->", self.range_processing_mode)
        print("LED: ラインスペーシング[m] ->", self.line_spacing)
        print("LED: ピクセルスペーシング[m] ->", self.pixel_spacing)

        # 表3.3-6 プラットフォーム位置データ・レコード
        f.seek(self.record_length + self.summary_record_length + 8)
        self.platform_record_length = int.from_bytes(
            f.read(self.INTERGER4), byteorder="big"
        )
        print("LED: プラットフォーム位置データレコード長(B4) ->", self.platform_record_length)

        f.seek(self.record_length + self.summary_record_length + 12)
        self.orbit_type = f.read(self.FLOAT32).decode("utf-8")
        print("LED: 軌道要素種類 ->", self.orbit_type)

        f.seek(self.record_length + self.summary_record_length + 140)
        self.NUM_ORB_POINT = int(f.read(self.INTERGER4))
        print("LED: データポイント数 ->", self.NUM_ORB_POINT)

        f.seek(self.record_length + self.summary_record_length + 144)
        self.TIME_ORB_YEAR = int(f.read(self.INTERGER4))
        self.TIME_ORB_MONTH = int(f.read(self.INTERGER4))
        self.TIME_ORB_DAY = int(f.read(self.INTERGER4))
        self.TIME_ORB_COUNT_DAY = int(f.read(self.INTERGER4))
        self.TIME_ORB_SEC = float(f.read(self.FLOAT22))
        print("LED: 第1ポイント年 ->", self.TIME_ORB_YEAR)
        print("LED: 第1ポイント通算日 ->", self.TIME_ORB_COUNT_DAY)
        print("LED: 第1ポイント通算秒 ->", self.TIME_ORB_SEC)

        f.seek(self.record_length + self.summary_record_length + 182)
        self.TIME_INTERVAL = float(f.read(self.FLOAT22))
        print("LED: ポイント間インターバル秒 ->", self.TIME_INTERVAL)

        f.seek(self.record_length + self.summary_record_length + 204)
        self.reference_coordinate = f.read(self.FLOAT64).decode("utf-8")
        print("LED: 参照座標系 ->", self.reference_coordinate)

        f.seek(self.record_length + self.summary_record_length + 290)
        self.position_error = float(f.read(self.FLOAT16))
        f.seek(self.record_length + self.summary_record_length + 306)
        self.position_error2 = float(f.read(self.FLOAT16))
        f.seek(self.record_length + self.summary_record_length + 322)
        self.position_error3 = float(f.read(self.FLOAT16))
        f.seek(self.record_length + self.summary_record_length + 338)
        self.velocity_error = float(f.read(self.FLOAT16))
        f.seek(self.record_length + self.summary_record_length + 354)
        self.velocity_error2 = float(f.read(self.FLOAT16))
        f.seek(self.record_length + self.summary_record_length + 370)
        self.velocity_error3 = float(f.read(self.FLOAT16))

        f.seek(self.record_length + self.summary_record_length + 386)
        self.position_vector = np.zeros((self.NUM_ORB_POINT, 3))
        self.velocity_vector = np.zeros((self.NUM_ORB_POINT, 3))
        for i in range(self.NUM_ORB_POINT):
            self.position_vector[i, 0] = float(f.read(self.FLOAT22))
            self.position_vector[i, 1] = float(f.read(self.FLOAT22))
            self.position_vector[i, 2] = float(f.read(self.FLOAT22))
            self.velocity_vector[i, 0] = float(f.read(self.FLOAT22))
            self.velocity_vector[i, 1] = float(f.read(self.FLOAT22))
            self.velocity_vector[i, 2] = float(f.read(self.FLOAT22))

        print("LED: 第1データポイント位置ベクトル ->", self.position_vector[0])
        print("LED: 最終データポイント速度ベクトル ->", self.velocity_vector[-1])

        f.seek(self.record_length + self.summary_record_length + 4100)
        self.leap_second_flag = int(f.read(self.BYTE1))
        print("LED: うるう秒フラグ ->", self.leap_second_flag)

        # 姿勢データレコード
        f.seek(self.record_length + self.summary_record_length + self.platform_record_length + 8)
        self.attitude_record_length = int.from_bytes(
            f.read(self.INTERGER4), byteorder="big"
        )
        print("LED: 姿勢データレコード長(B4) ->", self.attitude_record_length)

        f.seek(self.record_length + self.summary_record_length + self.platform_record_length + 28)
        self.pitch_quality = f.read(self.INTERGER4).decode("utf-8")
        self.roll_quality = f.read(self.INTERGER4).decode("utf-8")
        self.yaw_quality = f.read(self.INTERGER4).decode("utf-8")
        self.pitch = float(f.read(14))
        self.roll = float(f.read(14))
        self.yaw = float(f.read(14))
        self.pitch_rate_quality = f.read(self.INTERGER4).decode("utf-8")
        self.roll_rate_quality = f.read(self.INTERGER4).decode("utf-8")
        self.yaw_rate_quality = f.read(self.INTERGER4).decode("utf-8")

        f.seek(self.record_length + self.summary_record_length + self.platform_record_length + 12)
        self.point_number = int(f.read(self.INTERGER4))
        print("LED: 姿勢ポイント数 ->", self.point_number)

        f.seek(self.record_length + self.summary_record_length + self.platform_record_length + 94)
        self.points_pitches = np.zeros(self.point_number)
        self.points_rolls = np.zeros(self.point_number)
        self.points_yaws = np.zeros(self.point_number)
        for i in range(self.point_number - 1):
            self.points_pitches[i] = float(f.read(14))
            self.points_rolls[i] = float(f.read(14))
            self.points_yaws[i] = float(f.read(14))
            break  # 必要に応じて全ポイント読むように変更してください

        # キャリブレーションデータレコード
        f.seek(
            self.record_length
            +self.summary_record_length
            +self.platform_record_length
            +self.attitude_record_length
            +8
        )
        self.calibration_record_length = int.from_bytes(
            f.read(self.INTERGER4), byteorder="big"
        )
        print("LED: キャリブレーションレコード長(B4) ->", self.calibration_record_length)

        f.seek(
            self.record_length
            +self.summary_record_length
            +self.platform_record_length
            +self.attitude_record_length
            +16
        )
        # self.valid_sample = int(f.read(self.INTERGER4))
        # self.calibration_start = f.read(17).decode("utf-8")
        # self.calibration_end = f.read(17).decode("utf-8")
        # tmp = f.read(self.INTERGER4)
        # self.attenuator = 0 if not tmp == b"" else int(tmp)
        # tmp = f.read(self.BYTE1)
        # self.alc = 0 if not tmp == b"" else int(tmp)
        # tmp = f.read(self.BYTE1)
        # self.agc = 0 if not tmp == b"" else int(tmp)
        # self.pulse_width = int(f.read(self.INTERGER4))
        # self.chirp_bandwidth = int(f.read(self.INTERGER4))
        # self.sampling_frequency = int(f.read(self.INTERGER4))
        # self.quantization_bit = int(f.read(self.INTERGER4))
        # self.chirp_replica = int(f.read(self.INTERGER4))
        # self.chirp_replica_line = int(f.read(self.INTERGER4))

        # 受信偏波1
        f.seek(
            self.record_length
            +self.summary_record_length
            +self.platform_record_length
            +self.attitude_record_length
            +84
        )
        # self.receive_polarization1 = int(f.read(self.BYTE1))

        # チャープレプリカデータ1 (I,Q の積算値)
        f.seek(
            self.record_length
            +self.summary_record_length
            +self.platform_record_length
            +self.attitude_record_length
            +85
        )
        # self.chirp_replica_data1 = np.zeros((self.valid_sample, 2))
        # for i in range(self.valid_sample):
        #     self.chirp_replica_data1[i, 0] = int.from_bytes(
        #         f.read(self.BYTE2), byteorder="big"
        #     )
        #     self.chirp_replica_data1[i, 1] = int.from_bytes(
        #         f.read(self.BYTE2), byteorder="big"
        #     )

        # 設備関連データレコードの先頭だけ確認
        f.seek(
            self.record_length
            +self.summary_record_length
            +self.platform_record_length
            +self.attitude_record_length
            +self.calibration_record_length
            +0
        )
        self.record_order = int.from_bytes(f.read(self.INTERGER4), byteorder="big")

        f.seek(
            self.record_length
            +self.summary_record_length
            +self.platform_record_length
            +self.attitude_record_length
            +self.calibration_record_length
            +7
        )
        self.sub_type = int.from_bytes(f.read(self.BYTE1), byteorder="big")

        f.seek(
            self.record_length
            +self.summary_record_length
            +self.platform_record_length
            +self.attitude_record_length
            +self.calibration_record_length
            +8
        )
        self.atla_record_length1 = int.from_bytes(
            f.read(self.INTERGER4), byteorder="big"
        )

        f.close()
        print("CEOS PALSAR L1.1 SLC データの読み込み完了\n")

        # ------------------------------------------------------------------
        # スケール・幾何計算用の共通パラメータ
        # ------------------------------------------------------------------
        self.NUM_APERTURE_SAMPLE = self.NUM_SIGNAL_RECORD  # default full sample

        self.FREQ_AD_SAMPLE = self.sampling_frequency_mhz * 1e6
        self.FREQ_PULSE_REPETITION = self.prf * 1e-3
        self.TIME_PLUSE_DURATION = self.chirp_length * 1e-9
        self.DIS_ELLIPSOID_RADIUS = self.ellipsoid_radius * 1e3
        self.DIS_ELLIPSOID_SHORT_RADIUS = self.ellipsoid_short_radius * 1e3

    def set_geometory(self, plot=False, output_json_path: str=None):
        """観測ジオメトリの設定（L1.0 用実装と同じ変数名で動作）"""

        self.TIME_SHIFT = 0.0  # [sec]
        self.NUM_APERTURE_SAMPLE = self.NUM_SIGNAL_RECORD  # フルサンプル

        # 軌道情報の時刻配列
        self.time_orbit = np.arange(
            self.TIME_DAY_SEC * self.TIME_ORB_COUNT_DAY + self.TIME_ORB_SEC,
            self.TIME_DAY_SEC * self.TIME_ORB_COUNT_DAY
            +self.TIME_ORB_SEC
            +self.TIME_INTERVAL * self.NUM_ORB_POINT,
            self.TIME_INTERVAL,
        )

        # 補間関数
        self.func_intp_orbit_x_recode_time = interp1d(
            self.time_orbit, self.position_vector[:, 0], kind="cubic", axis=0
        )
        self.func_intp_orbit_y_recode_time = interp1d(
            self.time_orbit, self.position_vector[:, 1], kind="cubic", axis=0
        )
        self.func_intp_orbit_z_recode_time = interp1d(
            self.time_orbit, self.position_vector[:, 2], kind="cubic", axis=0
        )

        # 観測開始／終了時刻（アパーチャ長分だけ確保）
        self.TIME_OBS_START_ = self.TIME_OBS_START_DAY + (
            self.TIME_OBS_START_MSEC / self.DIGIT4 + self.TIME_SHIFT
        ) / self.TIME_DAY_SEC
        self.TIME_OBS_START_SEC = self.TIME_DAY_SEC * self.TIME_OBS_START_ + (
            self.NUM_APERTURE_SAMPLE * 0.0
        ) / self.FREQ_PULSE_REPETITION
        self.TIME_OBS_END_SEC = self.TIME_DAY_SEC * self.TIME_OBS_START_ + (
            self.NUM_APERTURE_SAMPLE * 1.0
        ) / self.FREQ_PULSE_REPETITION

        print("観測開始時刻 (秒):", self.TIME_OBS_START_SEC)
        print("観測終了時刻 (秒):", self.TIME_OBS_END_SEC)
        print("観測期間 (秒):", self.TIME_OBS_END_SEC - self.TIME_OBS_START_SEC)

        if plot:
            num_orb_counts = np.arange(0, self.NUM_ORB_POINT, 1)
            plt.figure(figsize=(12, 4), dpi=80, facecolor="w", edgecolor="k")
            plt.title("ALOS PALSAR L1.1 `Sub` TimeSeries")
            plt.scatter(num_orb_counts, self.time_orbit, label="Orbit Recording Point")
            plt.plot(
                num_orb_counts,
                self.time_orbit,
                label="Orbit Recording Line",
                linestyle="-",
            )
            plt.axhline(
                y=self.TIME_OBS_START_SEC, linestyle="-", label="Start time"
            )
            plt.axhline(
                y=self.TIME_OBS_END_SEC, linestyle="--", label="End time"
            )
            plt.legend(loc="upper left")
            plt.xlabel("Sample Count [n]")
            plt.ylabel("Time [sec]")
            plt.tight_layout()
            plt.savefig(
                os.path.join(
                    PATH_OUTPUT, "orbit_timeseries_sub_L11.png"
                ),
                bbox_inches="tight",
                format="png",
                dpi=160,
            )
            plt.show()
            plt.clf()
            plt.close()

        # 観測期間の衛星位置ベクトル
        self.TIMES_OBS = np.linspace(
            self.TIME_OBS_START_SEC, self.TIME_OBS_END_SEC, self.NUM_APERTURE_SAMPLE
        )
        self.P_X_SAT = self.func_intp_orbit_x_recode_time(self.TIMES_OBS)
        self.P_Y_SAT = self.func_intp_orbit_y_recode_time(self.TIMES_OBS)
        self.P_Z_SAT = self.func_intp_orbit_z_recode_time(self.TIMES_OBS)
        self.P_SAT = np.sqrt(
            self.P_X_SAT ** 2 + self.P_Y_SAT ** 2 + self.P_Z_SAT ** 2
        )

        # 観測期間の衛星速度ベクトル
        self.func_intp_orbit_vx_recode_time = interp1d(
            self.time_orbit, self.velocity_vector[:, 0], kind="cubic", axis=0
        )
        self.func_intp_orbit_vy_recode_time = interp1d(
            self.time_orbit, self.velocity_vector[:, 1], kind="cubic", axis=0
        )
        self.func_intp_orbit_vz_recode_time = interp1d(
            self.time_orbit, self.velocity_vector[:, 2], kind="cubic", axis=0
        )

        self.V_X_SAT = self.func_intp_orbit_vx_recode_time(self.TIMES_OBS)
        self.V_Y_SAT = self.func_intp_orbit_vy_recode_time(self.TIMES_OBS)
        self.V_Z_SAT = self.func_intp_orbit_vz_recode_time(self.TIMES_OBS)

        # ゲート遅延距離
        self.DIS_GATE_DELAY = self.TIME_GATE_DELAY * self.SOL
        print("受信ゲートの遅延距離 [m]: ", self.DIS_GATE_DELAY)

        # レンジ方向サンプル距離
        self.DIS_RANGE_SLANT = self.SOL / (2.0 * self.FREQ_AD_SAMPLE)
        self.DIS_FAR_RANGE = self.DIS_NEAR_RANGE + (self.NUM_PIXEL - 1) * self.DIS_RANGE_SLANT

        # 電離層遅延はここでは 0 として扱う
        self.dis_ionosphere_delay = 0.0
        print(f"電離層遅延補正距離: {self.dis_ionosphere_delay:.2f} m")

        self.DIS_NEAR_RANGE -= self.dis_ionosphere_delay
        self.DIS_FAR_RANGE -= self.dis_ionosphere_delay

        self.SLANT_RANGE_SAMPLE = np.linspace(
            self.DIS_NEAR_RANGE + self.DIS_GATE_DELAY,
            self.DIS_FAR_RANGE + self.DIS_GATE_DELAY,
            self.NUM_PIXEL,
        )

        # 高度計算
        self.P_SAT_LATITUDE = np.arcsin(self.P_Z_SAT / self.P_SAT)
        self.SIN_SAT_LATITUDE = np.sin(self.P_SAT_LATITUDE)
        self.COS_SAT_LATITUDE = np.cos(self.P_SAT_LATITUDE)

        self.P_EARTH_RADIUS = np.divide(
            1.0,
            np.sqrt(
                self.COS_SAT_LATITUDE ** 2 / self.DIS_ELLIPSOID_RADIUS ** 2
                +self.SIN_SAT_LATITUDE ** 2 / self.DIS_ELLIPSOID_SHORT_RADIUS ** 2
            ),
        )
        self.HEIGHT_SAT = self.P_SAT - self.P_EARTH_RADIUS
        print(f"平均衛星高度: {np.mean(self.HEIGHT_SAT):.2f} m")
        if output_json_path:
            _write_observation_json(self, output_json_path)


def check_ceos_polarization_orbit_exists(
    path_ceos_folder: str,
    polarimetry: str,
    orbit_name: str,
) -> None:
    """
    Check if IMG/LED files matching the given polarization and orbit exist in the CEOS folder.
    Raises FileNotFoundError if not found.

    Args:
        path_ceos_folder: CEOS product folder
        polarimetry: 偏波名 'HH', 'HV', 'VV', 'VH'
        orbit_name: 軌道名 'A' or 'D'

    Raises:
        FileNotFoundError: If the IMG/LED files matching the given polarization and orbit do not exist
    """
    ceos_files = os.listdir(path_ceos_folder)
    path_led = None
    path_img = None
    for name in ceos_files:
        if name.startswith("LED-") and name.endswith(f"__{orbit_name}"):
            path_led = os.path.join(path_ceos_folder, name)
        if name.startswith(f"IMG-{polarimetry}-") and name.endswith(f"__{orbit_name}"):
            path_img = os.path.join(path_ceos_folder, name)
    if path_img is None or path_led is None:
        raise FileNotFoundError(
            f"IMG/LED not found: PATH={path_ceos_folder}, "
            f"POL={polarimetry}, ORBIT={orbit_name}\n"
            "The specified orbit or polarization does not match any file in the current directory."
        )


class CEOS_PALSAR2_L11_SLC(object):
    """
    ALOS-2 PALSAR-2 Level 1.1 CEOS Format Reader

    - IMG: SAR image file (single-look complex, slant range, REAL*4 I/Q)
    - LED: SAR leader file (orbit, attitude, radiometric info)
    """

    # time / physical constants
    TIME_DAY_HOUR = 24
    TIME_DAY_MINITE = 60
    TIME_MINITE_SEC = 60
    TIME_DAY_SEC = TIME_DAY_HOUR * TIME_DAY_MINITE * TIME_MINITE_SEC  # [sec]
    SOL = 299792458.0  # [m/s] speed of light

    DIGIT4 = 1000.0

    # field byte-length helpers (for CEOS I4/I6/F16/E22 etc.)
    BYTE1 = 1
    BYTE2 = 2
    INTERGER4 = 4  # I4 / B4
    INTERGER6 = 6  # I6
    FLOAT16 = 16  # F16.x / E16.x (ASCII)
    FLOAT22 = 22  # F22.x / E22.x (ASCII)
    FLOAT32 = 32  # A32
    FLOAT64 = 64  # A64

    NUM_VELOCITY_CALC_SPAN_COUNT: int = 4

    def __init__(
        self,
        PATH_CEOS_FOLDER: str,
        POLARIMETORY: str="HH",
        ORBIT_NAME: str="A",
    ):
        """
        Initialize CEOS Format Reader (ALOS-2 PALSAR-2 Level 1.1)

        Args:
            PATH_CEOS_FOLDER (str): CEOS プロダクトが展開されているフォルダ
                                    例: ALOS2267860740-150210/
            POLARIMETORY (str, optional): 偏波名 'HH', 'HV', 'VV', 'VH'.
            ORBIT_NAME (str, optional): 軌道名 'A' or 'D'.
        """

        self.PATH_CEOS_FOLDER = PATH_CEOS_FOLDER
        self.POLARIMETORY = POLARIMETORY
        self.ORBIT_NAME = ORBIT_NAME

        # --------------------------------------------------
        # ファイル名の自動探索
        #   LED-*.??__A, IMG-HH-*.??__A などをディレクトリから検索
        #   （ALOS / ALOS-2 双方の命名規則にある程度対応）
        # --------------------------------------------------
        ceos_files = os.listdir(self.PATH_CEOS_FOLDER)

        self.PATH_LED = None
        self.PATH_IMG = None

        for name in ceos_files:
            if name.startswith("LED-") and name.endswith(f"__{self.ORBIT_NAME}"):
                self.PATH_LED = os.path.join(self.PATH_CEOS_FOLDER, name)
            if name.startswith(f"IMG-{self.POLARIMETORY}-") and name.endswith(
                f"__{self.ORBIT_NAME}"
            ):
                self.PATH_IMG = os.path.join(self.PATH_CEOS_FOLDER, name)

        if self.PATH_IMG is None or self.PATH_LED is None:
            raise FileNotFoundError(
                f"IMG/LED ファイルが見つかりません: PATH={self.PATH_CEOS_FOLDER}, "
                f"POL={self.POLARIMETORY}, ORBIT={self.ORBIT_NAME}"
            )

        # ------------------------------------------------------
        # IMG File Reader (イメージファイル / シグナルデータ用)
        #   表 3.3-13, 3.3-14 （SAR イメージファイルディスクリプタ／
        #   SAR イメージデータレコード）に対応
        # ------------------------------------------------------
        f = open(self.PATH_IMG, "rb")

        # SAR イメージファイルディスクリプタレコード長（通常 720 byte）
        f.seek(8)
        self.NUM_SAR_DISCRIPTOR_RECORD = int.from_bytes(
            f.read(self.INTERGER4), byteorder="big"
        )
        print("IMG: B9-12 SAR イメージファイルディスクリプタレコード長 ->",
              self.NUM_SAR_DISCRIPTOR_RECORD)

        # --- SAMPLE GROUP DATA (表 3.3-13) ---
        # 217-220 I4 サンプル当たりのビット長
        # 221-224 I4 データグループ当たりのサンプル数
        # 225-228 I4 データグループ当たりのバイト数
        f.seek(216)  # Byte 217 の 0-origin offset
        bits_per_sample_bytes = f.read(4)
        self.bits_per_sample = int(bits_per_sample_bytes.decode("ascii").strip())
        samples_per_group_bytes = f.read(4)
        self.samples_per_group = int(samples_per_group_bytes.decode("ascii").strip())
        bytes_per_group_bytes = f.read(4)
        self.bytes_per_group = int(bytes_per_group_bytes.decode("ascii").strip())

        print("IMG: bits/sample   ->", self.bits_per_sample)
        print("IMG: samples/group ->", self.samples_per_group)
        print("IMG: bytes/group   ->", self.bytes_per_group)

        # Level 1.1 では REAL*4 I,Q なので
        #  32 bit/sample, 2 sample/group (I,Q), 8 byte/group のはず
        if not (
            self.bits_per_sample == 32
            and self.samples_per_group == 2
            and self.bytes_per_group == 8
        ):
            raise ValueError(
                "PALSAR-2 L1.1 の SAMPLE GROUP DATA が想定と異なります: "
                f"bits={self.bits_per_sample}, samples/group={self.samples_per_group}, "
                f"bytes/group={self.bytes_per_group}"
            )

        # 276-280 I4 レコードあたりの PREFIX DATA のバイト数
        f.seek(276)
        self.NUM_PREFIX = int(f.read(self.INTERGER4))
        print("IMG: B277-280 PREFIX DATA bytes/record ->", self.NUM_PREFIX)

        # 181-186 I6 SARデータレコード数（レンジライン数）
        f.seek(180)
        self.NUM_SIGNAL_RECORD = int(f.read(self.INTERGER6))
        print("IMG: B181-186 SARデータレコード数 ->", self.NUM_SIGNAL_RECORD)

        # 187-192 I6 SARデータレコード長（ゼロサプレス後）
        f.seek(186)
        self.signal_record_length = int(f.read(self.INTERGER6))
        print("IMG: B187-192 SARデータレコード長 ->", self.signal_record_length)

        print(f"{'='*10} IMG Header (prefix={self.NUM_PREFIX}) {'='*10}")

        # prefix 直後のイメージデータレコード共通部
        # 49-50 B2 SAR チャンネル ID
        f.seek(48 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.pol = int.from_bytes(f.read(self.BYTE2), byteorder="big")
        print("IMG: B49-50 SARチャンネルID ->", self.pol)

        # 9-12 B4 レコード長（イメージデータレコード）
        f.seek(8 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.record_length = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B9-12 レコード長（シグナルレコード長） ->", self.record_length)

        # 13-16 B4 SAR画像データライン番号
        f.seek(12 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.azimuth_line = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B13-16 SAR画像データライン番号 ->", self.azimuth_line)

        # 17-20 B4 SAR画像データレコードインデックス
        f.seek(16 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.sar_image_index = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B17-20 SAR画像データレコードインデックス ->", self.sar_image_index)

        # 25-28 B4 実際のデータピクセル数 (1レンジラインのピクセル数)
        f.seek(24 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.NUM_PIXEL = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B25-28 実際のデータピクセル数 ->", self.NUM_PIXEL)

        # 29-32 B4 実際の右詰めの数
        f.seek(28 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.NUM_BLANK_PIXEL = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B29-32 実際の右詰めのピクセル数 ->", self.NUM_BLANK_PIXEL)

        # 57-60 B4 PRF [mHz] 
        f.seek(56 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.prf_mhz = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B57-60 PRF [mHz] ->", self.prf_mhz)

        # チャープ関連（Level 1.0 の値をコピーしているフィールド）
        f.seek(66 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.chirp = int.from_bytes(f.read(self.BYTE2), byteorder="big")
        print("IMG: B67-68 チャープ形式指定者 ->", self.chirp)

        f.seek(68 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.chirp_length = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B69-72 チャープ長(パルス幅) nsec ->", self.chirp_length)

        f.seek(72 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.chirp_const = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B73-76 チャープ定数係数 Hz ->", self.chirp_const)

        f.seek(76 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.chirp_coeff = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B77-80 チャープ一次係数 Hz/μsec ->", self.chirp_coeff)

        f.seek(80 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.chirp_coeff2 = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B81-84 チャープ二次係数 Hz/μsec^2 ->", self.chirp_coeff2)

        # 93-96 B4 受信機ゲイン (dB)
        f.seek(92 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.gain = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B93-96 受信機ゲイン dB ->", self.gain)

        # 117-120 B4 最初のデータまでのスラントレンジ (m)
        f.seek(116 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.DIS_NEAR_RANGE = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B117-120 最初のデータまでのスラントレンジ [m] ->",
              self.DIS_NEAR_RANGE)

        # 121-124 B4 SAMPLE DELAY (nsec)
        f.seek(120 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.TIME_GATE_DELAY_T = int.from_bytes(
            f.read(self.INTERGER4), byteorder="big"
        )
        print("IMG: B121-124 SAMPLE DELAY [nsec] ->", self.TIME_GATE_DELAY_T)

        if self.TIME_GATE_DELAY_T == 0:
            # Level 1.1 仕様では 0 固定。ゲートオフセットは 0 とみなす
            self.TIME_GATE_DELAY = 0.0
        else:
            self.TIME_GATE_DELAY = self.TIME_GATE_DELAY_T * 1e-9
            self.TIME_GATE_DELAY = 0
        print("  -> TIME_GATE_DELAY [sec] =", self.TIME_GATE_DELAY)

        # -----------------------------
        # シグナルデータレコードのループ
        # -----------------------------
        f.seek(self.NUM_SAR_DISCRIPTOR_RECORD)
        print(
            "Num of Range (pixels):", self.NUM_PIXEL,
            "Num of Azimuth Line:", self.NUM_SIGNAL_RECORD
        )

        self.signal = np.zeros(
            (self.NUM_SIGNAL_RECORD, self.NUM_PIXEL), dtype=np.complex64
        )

        for i in tqdm(range(self.NUM_SIGNAL_RECORD), desc="Read SLC (ALOS-2 L1.1)"):
            if i == 0:
                print(f"{'='*10} Start Time {'='*10}")
                # 1-36 バイトをまとめて読み飛ばし
                _ = f.read(36)
                # 37-40 年
                self.TIME_OBS_START_YEAR = int.from_bytes(
                    f.read(self.INTERGER4), "big"
                )
                print("IMG: B37-40 センサー取得年 ->", self.TIME_OBS_START_YEAR)
                # 41-44 通算日
                self.TIME_OBS_START_DAY = int.from_bytes(
                    f.read(self.INTERGER4), "big"
                )
                print("IMG: B41-44 センサー取得日(通算) ->", self.TIME_OBS_START_DAY)
                # 45-48 ミリ秒
                self.TIME_OBS_START_MSEC = int.from_bytes(
                    f.read(self.INTERGER4), "big"
                )
                print("IMG: B45-48 センサー取得ミリ秒 ->", self.TIME_OBS_START_MSEC)

                # L1.1 追加フィールド (SAR チャンネル/偏波コード等)
                self.sar_channel_id = int.from_bytes(f.read(self.BYTE2), "big")
                self.sar_channel_code = int.from_bytes(f.read(self.BYTE2), "big")
                self.tx_polarization_code = int.from_bytes(f.read(self.BYTE2), "big")
                self.rx_polarization_code = int.from_bytes(f.read(self.BYTE2), "big")
                print("IMG Prefix: SARチャンネルID ->", self.sar_channel_id)
                print("IMG Prefix: SARチャンネルコード ->", self.sar_channel_code)
                print("IMG Prefix: Tx偏波コード ->", self.tx_polarization_code)
                print("IMG Prefix: Rx偏波コード ->", self.rx_polarization_code)

                # ここまでで 36 + 4*3 + 2*4 = 56 byte 消費
                # 残りの prefix を読み飛ばし
                remain_prefix = self.NUM_PREFIX - 56
                if remain_prefix > 0:
                    _ = f.read(remain_prefix)

            elif i == self.NUM_SIGNAL_RECORD - 1:
                print(f"{'='*10} End Time {'='*10}")
                _ = f.read(36)
                self.TIME_OBS_END_YEAR = int.from_bytes(f.read(self.INTERGER4), "big")
                print("IMG: B37-40 センサー取得年 ->", self.TIME_OBS_END_YEAR)
                self.TIME_OBS_END_DAY = int.from_bytes(f.read(self.INTERGER4), "big")
                print("IMG: B41-44 センサー取得日(通算) ->", self.TIME_OBS_END_DAY)
                self.TIME_OBS_END_MSEC = int.from_bytes(f.read(self.INTERGER4), "big")
                print("IMG: B45-48 センサー取得ミリ秒 ->", self.TIME_OBS_END_MSEC)

                # SAR チャンネル等は開始時と同じとみなして読み飛ばし
                _ = f.read(2 + 2 + 2 + 2)  # 49-56
                remain_prefix = self.NUM_PREFIX - 56
                if remain_prefix > 0:
                    _ = f.read(remain_prefix)
            else:
                # 中間ラインの prefix は丸ごと読み飛ばす
                _ = f.read(self.NUM_PREFIX)

            # =========================
            # データ部 (SLC L1.1 本体)
            # =========================

            # L1.1 の 1 ピクセルは REAL*4 I/Q -> 32bit + 32bit = 8 byte
            n_pix = self.NUM_PIXEL
            n_bytes = n_pix * self.bytes_per_group

            buf = f.read(n_bytes)
            if len(buf) != n_bytes:
                raise IOError(
                    f"SAR データの読み込みに失敗しました: 期待 {n_bytes} byte, 実際 {len(buf)} byte"
                )

            # Big Endian float32 で I, Q を読む
            # buf の並び: I0, Q0, I1, Q1, ... (REAL*4, Big Endian)
            iq = np.frombuffer(buf, dtype=">f4")
            if iq.size != 2 * n_pix:
                raise IOError(
                    f"ピクセル数不整合: 期待 {2*n_pix} 要素, 実際 {iq.size} 要素"
                )

            iq = iq.astype(np.float32, copy=False).reshape(-1, 2)
            i_real = iq[:, 0]
            q_imag = iq[:, 1]

            # 複素数にして self.signal の 1 ラインに格納
            self.signal[i,:] = i_real + 1j * q_imag

            # 右詰めピクセル (通常 0)
            if self.NUM_BLANK_PIXEL > 0:
                _ = f.read(self.NUM_BLANK_PIXEL * self.bytes_per_group)

        f.close()

        # ------------------------------------------------------
        # LED File Reader (SAR リーダファイル)
        #   表 3.3-4, 3.3-5, 3.3-7 などに対応
        # ------------------------------------------------------
        f = open(self.PATH_LED, "rb")

        # 表3.3-4 SARリーダファイルディスクリプタレコード
        f.seek(8)
        self.led_record_length = int.from_bytes(
            f.read(self.INTERGER4), byteorder="big"
        )
        print("LED: B9-12 リーダファイルディスクリプタレコード長 ->",
              self.led_record_length)

        # 181-192: データセットサマリレコード数・長
        f.seek(180)
        self.summary_record = int(f.read(self.INTERGER6))
        print("LED: データセットサマリレコード数 ->", self.summary_record)
        f.seek(186)
        self.summary_record_length = int(f.read(self.INTERGER6))
        print("LED: データセットサマリレコード長 ->", self.summary_record_length)

        # 193-204: 地図投影データレコード数・長
        f.seek(192)
        self.map_record = int(f.read(self.INTERGER6))
        print("LED: 地図投影データレコード数 ->", self.map_record)
        f.seek(198)
        self.map_record_length = int(f.read(self.INTERGER6))
        print("LED: 地図投影データレコード長 ->", self.map_record_length)

        # 205-222: プラットフォーム位置データ・姿勢データレコード長
        f.seek(210)
        self.platform_record_length = int(f.read(self.INTERGER6))
        print("LED: プラットフォーム位置データレコード長 ->",
              self.platform_record_length)
        f.seek(222)
        self.attitude_record_length = int(f.read(self.INTERGER6))
        print("LED: 姿勢データレコード長 ->", self.attitude_record_length)

        # その他レコード長（必要に応じて使用）
        f.seek(234)
        self.radiometric_record_length = int(f.read(self.INTERGER6))
        f.seek(246)
        self.radiometric_comp_record_length = int(f.read(self.INTERGER6))
        f.seek(258)
        self.data_quality_record_length = int(f.read(self.INTERGER6))
        f.seek(270)
        self.data_histogram_record_length = int(f.read(self.INTERGER6))
        f.seek(282)
        self.range_spectrum_record_length = int(f.read(self.INTERGER6))
        f.seek(294)
        self.dem_record_length = int(f.read(self.INTERGER6))
        f.seek(342)
        self.calibration_record_length = int(f.read(self.INTERGER6))

        # 表3.3-5 データセットサマリレコード (レベル1.1/1.5/3.1 共通)
        f.seek(self.led_record_length + 8)
        self.summary_record_length_B4 = int.from_bytes(
            f.read(self.INTERGER4), byteorder="big"
        )
        print("LED: データセットサマリレコード長(B4) ->",
              self.summary_record_length_B4)

        # シーン ID
        f.seek(self.led_record_length + 20)
        self.scene_id = f.read(self.FLOAT32).decode("utf-8")
        print("LED: シーンID ->", self.scene_id.strip())

        # シーンセンター時刻
        f.seek(self.led_record_length + 68)
        self.scene_time = f.read(self.FLOAT32).decode("utf-8")
        print("LED: シーンセンター時刻 ->", self.scene_time.strip())

        # 楕円体モデル・半径など
        f.seek(self.led_record_length + 164)
        self.ellipsoid_model = f.read(self.FLOAT16).decode("utf-8")
        print("LED: 楕円体モデル ->", self.ellipsoid_model.strip())

        f.seek(self.led_record_length + 180)
        self.ellipsoid_radius = float(f.read(self.FLOAT16))
        print("LED: 楕円体の半長径(Km) ->", self.ellipsoid_radius)

        f.seek(self.led_record_length + 196)
        self.ellipsoid_short_radius = float(f.read(self.FLOAT16))
        print("LED: 楕円体の短半径(Km) ->", self.ellipsoid_short_radius)

        f.seek(self.led_record_length + 212)
        self.earth_mass = float(f.read(self.FLOAT16))
        print("LED: 地球の質量(10^24 Kg) ->", self.earth_mass)

        f.seek(self.led_record_length + 244)
        self.j2 = float(f.read(self.FLOAT16))
        self.j3 = float(f.read(self.FLOAT16))
        self.j4 = float(f.read(self.FLOAT16))
        print("LED: J2 ->", self.j2)
        print("LED: J3 ->", self.j3)
        print("LED: J4 ->", self.j4)

        # f.seek(self.led_record_length + 308)
        # self.ellipsoid_mean = float(f.read(self.FLOAT16))
        # print("LED: シーン中央の平均的な地形標高 ->", self.ellipsoid_mean)

        f.seek(self.led_record_length + 388)
        self.sar_channel = int(f.read(self.INTERGER4))
        print("LED: SARチャネル数 ->", self.sar_channel)

        f.seek(self.led_record_length + 396)
        self.sensor_platform = f.read(self.FLOAT16).decode("utf-8")
        print("LED: センサプラットフォーム名 ->",
              self.sensor_platform.strip())

        # 波長 λ [m]
        f.seek(self.led_record_length + 500)
        self.LAMBDA = float(f.read(self.FLOAT16))
        print("LED: 波長 λ [m] ->", self.LAMBDA)

        # Motion compensation indicator
        f.seek(self.led_record_length + 516)
        self.motion_compensation = f.read(self.BYTE2).decode("utf-8")
        print("LED: Motion compensation indicator ->",
              self.motion_compensation.strip())

        # レンジパルスコード種別
        f.seek(self.led_record_length + 518)
        self.range_pulse_code = f.read(self.FLOAT16).decode("utf-8")
        print("LED: レンジパルスコード ->", self.range_pulse_code.strip())

        # レンジパルス振幅係数 (1-5)
        f.seek(self.led_record_length + 534)
        self.range_pulse_amplitude = float(f.read(self.FLOAT16))
        self.range_pulse_amplitude2 = float(f.read(self.FLOAT16))
        self.range_pulse_amplitude3 = float(f.read(self.FLOAT16))
        self.range_pulse_amplitude4 = float(f.read(self.FLOAT16))
        self.range_pulse_amplitude5 = float(f.read(self.FLOAT16))
        print("LED: レンジパルス振幅係数1 ->", self.range_pulse_amplitude)
        print("LED: レンジパルス振幅係数2 ->", self.range_pulse_amplitude2)
        print("LED: レンジパルス振幅係数3 ->", self.range_pulse_amplitude3)
        print("LED: レンジパルス振幅係数4 ->", self.range_pulse_amplitude4)
        print("LED: レンジパルス振幅係数5 ->", self.range_pulse_amplitude5)

        # サンプリング周波数・レンジゲート・レンジパルス幅
        f.seek(self.led_record_length + 710)
        self.sampling_frequency_mhz = float(f.read(self.FLOAT16))
        print("LED: サンプリング周波数(MHz) ->", self.sampling_frequency_mhz)

        f.seek(self.led_record_length + 726)
        self.range_gate = float(f.read(self.FLOAT16))
        print("LED: レンジゲート(μsec) ->", self.range_gate)

        f.seek(self.led_record_length + 742)
        self.range_pulse_width = float(f.read(self.FLOAT16))
        print("LED: レンジパルス幅(μsec) ->", self.range_pulse_width)

        # 量子化記述子
        f.seek(self.led_record_length + 806)
        self.quantization_descriptor = f.read(12).decode("utf-8")
        print("LED: 量子化記述子 ->", self.quantization_descriptor.strip())

        # DC バイアス / I-Q ゲイン不均衡
        f.seek(self.led_record_length + 818)
        self.DC_BIAS_I = float(f.read(self.FLOAT16))
        self.DC_BIAS_Q = float(f.read(self.FLOAT16))
        self.gain_imbalance = float(f.read(self.FLOAT16))
        print("LED: I成分DCバイアス ->", self.DC_BIAS_I)
        print("LED: Q成分DCバイアス ->", self.DC_BIAS_Q)
        print("LED: I/Qゲイン不均衡 ->", self.gain_imbalance)

        # 電子および機械ボアサイト
        f.seek(self.led_record_length + 898)
        self.electronic_boresight = float(f.read(self.FLOAT16))
        print("LED: electronic boresight ->", self.electronic_boresight)

        f.seek(self.led_record_length + 914)
        self.mechanical_boresight = float(f.read(self.FLOAT16))
        print("LED: mechanical boresight ->", self.mechanical_boresight)

        # PRF (mHz) from LED (念のため IMG 側の値と整合チェック可能)
        f.seek(self.led_record_length + 934)
        self.prf_from_led = float(f.read(self.FLOAT16))
        print("LED: PRF(mHz) ->", self.prf_from_led)

        # 2-way ビーム幅 (elevation / azimuth)
        f.seek(self.led_record_length + 950)
        self.beam_width_elevation = float(f.read(self.FLOAT16))
        self.beam_width_azimuth = float(f.read(self.FLOAT16))
        print("LED: 2wayビーム幅(El) ->", self.beam_width_elevation)
        print("LED: 2wayビーム幅(Az) ->", self.beam_width_azimuth)

        # バイナリ時刻コード / 衛星クロック
        f.seek(self.led_record_length + 982)
        self.binary_time = int(f.read(self.FLOAT16))
        self.clock_time = f.read(self.FLOAT32).decode("utf-8")
        self.clock_increase = int(f.read(self.FLOAT16))
        print("LED: 衛星バイナリ時刻コード ->", self.binary_time)
        print("LED: 衛星クロック時刻 ->", self.clock_time.strip())
        print("LED: クロック増加量[nsec] ->", self.clock_increase)

        # 時間方向指標
        f.seek(self.led_record_length + 1534)
        self.time_index = f.read(8).decode("utf-8")
        print("LED: 時間方向指標 ->", self.time_index.strip())

        # PRF 変化点フラグ / ライン
        f.seek(self.led_record_length + 1802)
        self.prf_change_flag = f.read(self.INTERGER4).decode("utf-8")
        print("LED: PRF変化点フラグ ->", self.prf_change_flag.strip())

        f.seek(self.led_record_length + 1806)
        self.prf_change_line = int(f.read(8))
        print("LED: PRF変化開始ライン番号 ->", self.prf_change_line)

        # ヨーステアリング・オフナディア角・アンテナビーム番号
        f.seek(self.led_record_length + 1830)
        self.yaw_steering_flag = f.read(self.INTERGER4).decode("utf-8")
        print("LED: ヨーステアリング有無 ->", self.yaw_steering_flag.strip())

        f.seek(self.led_record_length + 1838)
        self.off_nadir_angle = float(f.read(self.FLOAT16))
        print("LED: オフナディア角[deg] ->", self.off_nadir_angle)

        f.seek(self.led_record_length + 1854)
        self.antenna_beam_number = int(f.read(self.INTERGER4))
        print("LED: アンテナビーム番号 ->", self.antenna_beam_number)

        # Level 1.1 追加: レンジ/アジマススペーシングなど
        f.seek(self.led_record_length + 1670)
        self.range_processing_mode = f.read(8).decode("utf-8")
        self.azimuth_look_flag = f.read(4).decode("utf-8")
        self.range_look_flag = f.read(4).decode("utf-8")
        self.line_spacing = float(f.read(self.FLOAT16))
        self.pixel_spacing = float(f.read(self.FLOAT16))
        self.chirp_extraction_mode = f.read(16).decode("utf-8")

        print("LED: RANGE/OTHER ->", self.range_processing_mode.strip())
        print("LED: ラインスペーシング[m] ->", self.line_spacing)
        print("LED: ピクセルスペーシング[m] ->", self.pixel_spacing)
        print("LED: CHIRP extraction mode ->",
              self.chirp_extraction_mode.strip())

        # ------------------------------------------------------
        # 表3.3-7 プラットフォーム位置データレコード
        #   （軌道データ：時刻、位置ベクトル、速度ベクトル）
        # ------------------------------------------------------
        f.seek(self.led_record_length + self.summary_record_length + 8)
        self.platform_record_length_B4 = int.from_bytes(
            f.read(self.INTERGER4), byteorder="big"
        )
        print("LED: プラットフォーム位置データレコード長(B4) ->",
              self.platform_record_length_B4)

        f.seek(self.led_record_length + self.summary_record_length + 12)
        self.orbit_type = f.read(self.FLOAT32).decode("utf-8")
        print("LED: 軌道要素種類 ->", self.orbit_type.strip())

        f.seek(self.led_record_length + self.summary_record_length + 140)
        self.NUM_ORB_POINT = int(f.read(self.INTERGER4))
        print("LED: データポイント数 ->", self.NUM_ORB_POINT)

        f.seek(self.led_record_length + self.summary_record_length + 144)
        self.TIME_ORB_YEAR = int(f.read(self.INTERGER4))
        self.TIME_ORB_MONTH = int(f.read(self.INTERGER4))
        self.TIME_ORB_DAY = int(f.read(self.INTERGER4))
        self.TIME_ORB_COUNT_DAY = int(f.read(self.INTERGER4))
        self.TIME_ORB_SEC = float(f.read(self.FLOAT22))
        print("LED: 第1ポイント年 ->", self.TIME_ORB_YEAR)
        print("LED: 第1ポイント通算日 ->", self.TIME_ORB_COUNT_DAY)
        print("LED: 第1ポイント通算秒 ->", self.TIME_ORB_SEC)

        f.seek(self.led_record_length + self.summary_record_length + 182)
        self.TIME_INTERVAL = float(f.read(self.FLOAT22))
        print("LED: ポイント間インターバル秒 ->", self.TIME_INTERVAL)

        f.seek(self.led_record_length + self.summary_record_length + 204)
        self.reference_coordinate = f.read(self.FLOAT64).decode("utf-8")
        print("LED: 参照座標系 ->", self.reference_coordinate.strip())

        # 位置・速度の誤差（必要なら利用）
        f.seek(self.led_record_length + self.summary_record_length + 290)
        self.position_error = float(f.read(self.FLOAT16))
        f.seek(self.led_record_length + self.summary_record_length + 306)
        self.position_error2 = float(f.read(self.FLOAT16))
        f.seek(self.led_record_length + self.summary_record_length + 322)
        self.position_error3 = float(f.read(self.FLOAT16))
        f.seek(self.led_record_length + self.summary_record_length + 338)
        self.velocity_error = float(f.read(self.FLOAT16))
        f.seek(self.led_record_length + self.summary_record_length + 354)
        self.velocity_error2 = float(f.read(self.FLOAT16))
        f.seek(self.led_record_length + self.summary_record_length + 370)
        self.velocity_error3 = float(f.read(self.FLOAT16))

        # 位置・速度ベクトル
        f.seek(self.led_record_length + self.summary_record_length + 386)
        self.position_vector = np.zeros((self.NUM_ORB_POINT, 3), dtype=np.float64)
        self.velocity_vector = np.zeros((self.NUM_ORB_POINT, 3), dtype=np.float64)
        for i in range(self.NUM_ORB_POINT):
            self.position_vector[i, 0] = float(f.read(self.FLOAT22))
            self.position_vector[i, 1] = float(f.read(self.FLOAT22))
            self.position_vector[i, 2] = float(f.read(self.FLOAT22))
            self.velocity_vector[i, 0] = float(f.read(self.FLOAT22))
            self.velocity_vector[i, 1] = float(f.read(self.FLOAT22))
            self.velocity_vector[i, 2] = float(f.read(self.FLOAT22))

        print("LED: 第1データポイント位置ベクトル ->", self.position_vector[0])
        print("LED: 最終データポイント速度ベクトル ->", self.velocity_vector[-1])

        # うるう秒フラグ
        f.seek(self.led_record_length + self.summary_record_length + 4100)
        self.leap_second_flag = int(f.read(self.BYTE1))
        print("LED: うるう秒フラグ ->", self.leap_second_flag)

        # ------------------------------------------------------
        # 姿勢データレコード（ここでは先頭部分のみ読んでおく）
        # ------------------------------------------------------
        f.seek(
            self.led_record_length + self.summary_record_length
            +self.platform_record_length + 8
        )
        self.attitude_record_length_B4 = int.from_bytes(
            f.read(self.INTERGER4), byteorder="big"
        )
        print("LED: 姿勢データレコード長(B4) ->", self.attitude_record_length_B4)

        f.seek(
            self.led_record_length + self.summary_record_length
            +self.platform_record_length + 12
        )
        self.point_number = int(f.read(self.INTERGER4))
        print("LED: 姿勢ポイント数 ->", self.point_number)

        # 姿勢時系列（ピッチ・ロール・ヨーなど）は必要に応じて実装
        self.points_pitches = np.zeros(self.point_number, dtype=np.float32)
        self.points_rolls = np.zeros(self.point_number, dtype=np.float32)
        self.points_yaws = np.zeros(self.point_number, dtype=np.float32)

        f.close()
        print("CEOS PALSAR-2 L1.1 SLC データの読み込み完了\n")

        # ------------------------------------------------------------------
        # スケール・幾何計算用の共通パラメータ
        # ------------------------------------------------------------------
        self.NUM_APERTURE_SAMPLE = self.NUM_SIGNAL_RECORD  # default full azimuth

        # Equation - Condition: No 2.6
        # # Sampling Frequency := f_s(MHz) * 10^6
        self.FREQ_AD_SAMPLE = self.sampling_frequency_mhz * 1e6
        # Equation - Condition: No 2.7
        # # PRF := PRF(mHz) * 10^-3
        self.FREQ_PULSE_REPETITION = self.prf_mhz * 1e-3
        # Equation - Condition: No 2.8
        # # Pulse Duration := T_chirp(nsec) * 10^-9
        self.TIME_PLUSE_DURATION = self.chirp_length * 1e-9
        # Equation - Condition: No 2.9
        # # Ellipsoid Semi-Major := a(km) * 10^3
        self.DIS_ELLIPSOID_RADIUS = self.ellipsoid_radius * 1e3
        # Equation - Condition: No 2.10
        # # Ellipsoid Semi-Minor := b(km) * 10^3
        self.DIS_ELLIPSOID_SHORT_RADIUS = self.ellipsoid_short_radius * 1e3
        
        print("共通パラメータの設定完了\n")

    # --------------------------------------------------------------
    # 観測ジオメトリ設定（ALOS-2 PALSAR-2 版）
    # --------------------------------------------------------------
    def set_geometory(self, plot: bool=False, PATH_OUTPUT: Optional[str]=None, output_json_path: str=None):
        """
        観測ジオメトリの設定

        IMG/LED から読み出した軌道情報を用いて、観測中の
        衛星位置ベクトル・速度ベクトル・スラントレンジサンプル
        などを計算する（ALOS-2 PALSAR-2 仕様に対応）。
        """

        self.TIME_SHIFT = 0.  # [sec]
        self.NUM_APERTURE_SAMPLE = self.NUM_SIGNAL_RECORD  # default full azimuth

        # 軌道情報の時刻配列
        # Equation - Condition: No 2.11
        # # Orbit Time Grid := t0 : dt : t0 + dt * N
        self.time_orbit = np.arange(
            self.TIME_DAY_SEC * self.TIME_ORB_COUNT_DAY + self.TIME_ORB_SEC,
            self.TIME_DAY_SEC * self.TIME_ORB_COUNT_DAY
            +self.TIME_ORB_SEC
            +self.TIME_INTERVAL * self.NUM_ORB_POINT,
            self.TIME_INTERVAL,
        )

        # 軌道位置ベクトルの補間関数
        self.func_intp_orbit_x_recode_time = interp1d(
            self.time_orbit, self.position_vector[:, 0], kind="cubic", axis=0
        )
        self.func_intp_orbit_y_recode_time = interp1d(
            self.time_orbit, self.position_vector[:, 1], kind="cubic", axis=0
        )
        self.func_intp_orbit_z_recode_time = interp1d(
            self.time_orbit, self.position_vector[:, 2], kind="cubic", axis=0
        )

        # 観測開始／終了時刻（アパーチャ長分だけ確保）
        self.TIME_OBS_START_ = self.TIME_OBS_START_DAY + (
            self.TIME_OBS_START_MSEC / self.DIGIT4 + self.TIME_SHIFT
        ) / self.TIME_DAY_SEC
        self.TIME_OBS_START_SEC = self.TIME_DAY_SEC * self.TIME_OBS_START_ + (
            self.NUM_APERTURE_SAMPLE * 0.
        ) / self.FREQ_PULSE_REPETITION
        self.TIME_OBS_END_SEC = self.TIME_DAY_SEC * self.TIME_OBS_START_ + (
            self.NUM_APERTURE_SAMPLE * 1.
        ) / self.FREQ_PULSE_REPETITION

        print("観測開始時刻 (秒):", self.TIME_OBS_START_SEC)
        print("観測終了時刻 (秒):", self.TIME_OBS_END_SEC)
        print("観測期間 (秒):", self.TIME_OBS_END_SEC - self.TIME_OBS_START_SEC)

        if plot and PATH_OUTPUT is not None:
            num_orb_counts = np.arange(0, self.NUM_ORB_POINT, 1)
            plt.figure(figsize=(12, 4), dpi=80, facecolor="w", edgecolor="k")
            plt.title("ALOS-2 PALSAR-2 L1.1 Orbit TimeSeries")
            plt.scatter(num_orb_counts, self.time_orbit, label="Orbit Recording Point")
            plt.plot(
                num_orb_counts,
                self.time_orbit,
                label="Orbit Recording Line",
                linestyle="-",
            )
            plt.axhline(
                y=self.TIME_OBS_START_SEC, linestyle="-", label="Start time"
            )
            plt.axhline(
                y=self.TIME_OBS_END_SEC, linestyle="--", label="End time"
            )
            plt.legend(loc="upper left")
            plt.xlabel("Sample Count [n]")
            plt.ylabel("Time [sec]")
            plt.tight_layout()
            plt.savefig(
                os.path.join(PATH_OUTPUT, "orbit_timeseries_ALOS2_L11.png"),
                bbox_inches="tight",
                format="png",
                dpi=160,
            )
            plt.close()

        # 観測期間の衛星位置ベクトル
        self.TIMES_OBS = np.linspace(
            self.TIME_OBS_START_SEC, self.TIME_OBS_END_SEC, self.NUM_APERTURE_SAMPLE
        )
        self.P_X_SAT = self.func_intp_orbit_x_recode_time(self.TIMES_OBS)
        self.P_Y_SAT = self.func_intp_orbit_y_recode_time(self.TIMES_OBS)
        self.P_Z_SAT = self.func_intp_orbit_z_recode_time(self.TIMES_OBS)
        self.P_SAT = np.sqrt(
            self.P_X_SAT ** 2 + self.P_Y_SAT ** 2 + self.P_Z_SAT ** 2
        )

        # 観測期間の衛星速度ベクトル
        self.func_intp_orbit_vx_recode_time = interp1d(
            self.time_orbit, self.velocity_vector[:, 0], kind="cubic", axis=0
        )
        self.func_intp_orbit_vy_recode_time = interp1d(
            self.time_orbit, self.velocity_vector[:, 1], kind="cubic", axis=0
        )
        self.func_intp_orbit_vz_recode_time = interp1d(
            self.time_orbit, self.velocity_vector[:, 2], kind="cubic", axis=0
        )

        self.V_X_SAT = self.func_intp_orbit_vx_recode_time(self.TIMES_OBS)
        self.V_Y_SAT = self.func_intp_orbit_vy_recode_time(self.TIMES_OBS)
        self.V_Z_SAT = self.func_intp_orbit_vz_recode_time(self.TIMES_OBS)

        # 受信ゲートの遅延距離
        self.DIS_GATE_DELAY = self.TIME_GATE_DELAY * self.SOL
        print("受信ゲートの遅延距離 [m]: ", self.DIS_GATE_DELAY)

        # レンジ方向サンプル距離
        self.DIS_RANGE_SLANT = self.SOL / (2.0 * self.FREQ_AD_SAMPLE)
        print("レンジ方向サンプル距離 [m]: ", self.DIS_RANGE_SLANT)
        self.DIS_FAR_RANGE = self.DIS_NEAR_RANGE + (self.NUM_PIXEL - 1) * self.DIS_RANGE_SLANT

        # 電離層遅延はここでは 0 として扱う
        self.dis_ionosphere_delay = 0.0
        print(f"電離層遅延補正距離: {self.dis_ionosphere_delay:.2f} m")

        self.DIS_NEAR_RANGE -= self.dis_ionosphere_delay
        self.DIS_FAR_RANGE -= self.dis_ionosphere_delay

        self.SLANT_RANGE_SAMPLE = np.linspace(
            self.DIS_NEAR_RANGE,
            self.DIS_FAR_RANGE,
            self.NUM_PIXEL,
        )
        print(f"ニアレンジ: {self.DIS_NEAR_RANGE} m, ファーレンジ: {self.DIS_FAR_RANGE} m")

        # 高度計算
        self.P_SAT_LATITUDE = np.arcsin(self.P_Z_SAT / self.P_SAT)
        self.SIN_SAT_LATITUDE = np.sin(self.P_SAT_LATITUDE)
        self.COS_SAT_LATITUDE = np.cos(self.P_SAT_LATITUDE)

        self.P_EARTH_RADIUS = np.divide(
            1.0,
            np.sqrt(
                self.COS_SAT_LATITUDE ** 2 / self.DIS_ELLIPSOID_RADIUS ** 2
                +self.SIN_SAT_LATITUDE ** 2 / self.DIS_ELLIPSOID_SHORT_RADIUS ** 2
            ),
        )
        self.HEIGHT_SAT = self.P_SAT - self.P_EARTH_RADIUS
        print(f"平均衛星高度: {np.mean(self.HEIGHT_SAT):.2f} m")
        if output_json_path:
            _write_observation_json(self, output_json_path)
            
        return self


class CEOS_PALSAR3_L11_SLC(object):
    """
    ALOS-4 PALSAR-3 Level 1.1 CEOS Format Reader

    - IMG: SAR image file (single-look complex, slant range, REAL*4 I/Q)
    - LED: SAR leader file (orbit, attitude, radiometric info)

    ALOS-2 PALSAR-2 の CEOS フォーマットを踏襲した
    ALOS-4 PALSAR-3 標準プロダクトフォーマット (FTR-240031A) に対応。
    """

    # time / physical constants
    TIME_DAY_HOUR = 24
    TIME_DAY_MINITE = 60
    TIME_MINITE_SEC = 60
    TIME_DAY_SEC = TIME_DAY_HOUR * TIME_DAY_MINITE * TIME_MINITE_SEC  # [sec]
    SOL = 299792458.0  # [m/s] speed of light

    DIGIT4 = 1000.0

    # field byte-length helpers (for CEOS I4/I6/F16/E22 etc.)
    BYTE1 = 1
    BYTE2 = 2
    INTERGER4 = 4  # I4 / B4
    INTERGER6 = 6  # I6
    FLOAT16 = 16  # F16.x / E16.x (ASCII)
    FLOAT22 = 22  # F22.x / E22.x (ASCII)
    FLOAT32 = 32  # A32
    FLOAT64 = 64  # A64

    NUM_VELOCITY_CALC_SPAN_COUNT: int = 4

    def __init__(
        self,
        PATH_CEOS_FOLDER: str,
        POLARIMETORY: str="HH",
        ORBIT_NAME: str="A",
    ):
        """
        Initialize CEOS Format Reader (ALOS-4 PALSAR-3 Level 1.1)

        Args:
            PATH_CEOS_FOLDER (str): CEOS プロダクトが展開されているフォルダ
                                    例: ALOS4xxxxxx.../
            POLARIMETORY (str, optional): 偏波名 'HH', 'HV', 'VV', 'VH'.
            ORBIT_NAME (str, optional): 軌道名 'A' or 'D'（ALOS-4 では ProductID 内に
                                        含まれるが、互換のためパラメータとして残す）。
        """

        self.PATH_CEOS_FOLDER = PATH_CEOS_FOLDER
        self.POLARIMETORY = POLARIMETORY
        self.ORBIT_NAME = ORBIT_NAME

        # --------------------------------------------------
        # ファイル名の自動探索
        #   ALOS-4 PALSAR-3:
        #     LED-シーンID-プロダクトID
        #     IMG-偏波-受信アンテナ-シーンID-プロダクトID
        #   （ALOS-2 の "__A", "__D" 付き命名とも両立するよう緩めに探索）
        # --------------------------------------------------
        ceos_files = os.listdir(self.PATH_CEOS_FOLDER)

        self.PATH_LED = None
        self.PATH_IMG = None

        for name in ceos_files:
            # LED
            if name.startswith("LED-"):
                # ALOS-2 形式: 末尾 "__A"/"__D" を優先
                if name.endswith(f"__{self.ORBIT_NAME}"):
                    self.PATH_LED = os.path.join(self.PATH_CEOS_FOLDER, name)
                    break
                if self.PATH_LED is None:
                    self.PATH_LED = os.path.join(self.PATH_CEOS_FOLDER, name)

        for name in ceos_files:
            # IMG: 偏波名でフィルタ
            if name.startswith(f"IMG-{self.POLARIMETORY}-"):
                if name.endswith(f"__{self.ORBIT_NAME}"):
                    self.PATH_IMG = os.path.join(self.PATH_CEOS_FOLDER, name)
                    break
                if self.PATH_IMG is None:
                    self.PATH_IMG = os.path.join(self.PATH_CEOS_FOLDER, name)

        if self.PATH_IMG is None or self.PATH_LED is None:
            raise FileNotFoundError(
                f"IMG/LED ファイルが見つかりません: PATH={self.PATH_CEOS_FOLDER}, "
                f"POL={self.POLARIMETORY}, ORBIT={self.ORBIT_NAME}"
            )

        # ------------------------------------------------------
        # IMG File Reader (イメージファイル / シグナルデータ用)
        #   表 4.6-14, 4.6-15 （SAR イメージファイルディスクリプタ／
        #   SAR イメージデータレコード）に対応
        # ------------------------------------------------------
        f = open(self.PATH_IMG, "rb")

        # SAR イメージファイルディスクリプタレコード長（通常 720 byte）
        f.seek(8)
        self.NUM_SAR_DISCRIPTOR_RECORD = int.from_bytes(
            f.read(self.INTERGER4), byteorder="big"
        )
        print(
            "IMG: B9-12 SAR イメージファイルディスクリプタレコード長 ->",
            self.NUM_SAR_DISCRIPTOR_RECORD,
        )

        # --- SAMPLE GROUP DATA ---
        # 217-220 I4 サンプル当たりのビット長
        # 221-224 I4 データグループ当たりのサンプル数
        # 225-228 I4 データグループ当たりのバイト数
        f.seek(216)  # Byte 217 の 0-origin offset
        bits_per_sample_bytes = f.read(4)
        self.bits_per_sample = int(bits_per_sample_bytes.decode("ascii").strip())
        samples_per_group_bytes = f.read(4)
        self.samples_per_group = int(samples_per_group_bytes.decode("ascii").strip())
        bytes_per_group_bytes = f.read(4)
        self.bytes_per_group = int(bytes_per_group_bytes.decode("ascii").strip())

        print("IMG: bits/sample   ->", self.bits_per_sample)
        print("IMG: samples/group ->", self.samples_per_group)
        print("IMG: bytes/group   ->", self.bytes_per_group)

        # レベル 1.1 では REAL*4 I,Q なので
        #  32 bit/sample, 2 sample/group (I,Q), 8 byte/group のはず
        if not (
            self.bits_per_sample == 32
            and self.samples_per_group == 2
            and self.bytes_per_group == 8
        ):
            raise ValueError(
                "PALSAR-3 L1.1 の SAMPLE GROUP DATA が想定と異なります: "
                f"bits={self.bits_per_sample}, samples/group={self.samples_per_group}, "
                f"bytes/group={self.bytes_per_group}"
            )

        # 276-280 I4 レコードあたりの PREFIX DATA のバイト数
        f.seek(276)
        self.NUM_PREFIX = int(f.read(self.INTERGER4))
        print("IMG: B277-280 PREFIX DATA bytes/record ->", self.NUM_PREFIX)

        # 181-186 I6 SARデータレコード数（レンジライン数）
        f.seek(180)
        self.NUM_SIGNAL_RECORD = int(f.read(self.INTERGER6))
        print("IMG: B181-186 SARデータレコード数 ->", self.NUM_SIGNAL_RECORD)

        # 187-192 I6 SARデータレコード長（ゼロサプレス後）
        f.seek(186)
        self.signal_record_length = int(f.read(self.INTERGER6))
        print("IMG: B187-192 SARデータレコード長 ->", self.signal_record_length)

        print(f"{'='*10} IMG Header (prefix={self.NUM_PREFIX}) {'='*10}")

        # prefix 直後のイメージデータレコード共通部
        # 49-50 B2 SAR チャンネル ID
        f.seek(48 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.pol = int.from_bytes(f.read(self.BYTE2), byteorder="big")
        print("IMG: B49-50 SARチャンネルID ->", self.pol)

        # 9-12 B4 レコード長（イメージデータレコード）
        f.seek(8 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.record_length = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B9-12 レコード長（シグナルレコード長） ->", self.record_length)

        # 13-16 B4 SAR画像データライン番号
        f.seek(12 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.azimuth_line = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B13-16 SAR画像データライン番号 ->", self.azimuth_line)

        # 17-20 B4 SAR画像データレコードインデックス
        f.seek(16 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.sar_image_index = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print(
            "IMG: B17-20 SAR画像データレコードインデックス ->",
            self.sar_image_index,
        )

        # 25-28 B4 実際のデータピクセル数 (1レンジラインのピクセル数)
        f.seek(24 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.NUM_PIXEL = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B25-28 実際のデータピクセル数 ->", self.NUM_PIXEL)

        # 29-32 B4 実際の右詰めの数
        f.seek(28 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.NUM_BLANK_PIXEL = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B29-32 実際の右詰めのピクセル数 ->", self.NUM_BLANK_PIXEL)

        # 57-60 B4 PRF [mHz]
        f.seek(56 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.prf_mhz = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B57-60 PRF [mHz] ->", self.prf_mhz)

        # チャープ関連
        f.seek(66 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.chirp = int.from_bytes(f.read(self.BYTE2), byteorder="big")
        print("IMG: B67-68 チャープ形式指定者 ->", self.chirp)

        f.seek(68 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.chirp_length = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B69-72 チャープ長(パルス幅) nsec ->", self.chirp_length)

        f.seek(72 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.chirp_const = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B73-76 チャープ定数係数 Hz ->", self.chirp_const)

        f.seek(76 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.chirp_coeff = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B77-80 チャープ一次係数 Hz/μsec ->", self.chirp_coeff)

        f.seek(80 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.chirp_coeff2 = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B81-84 チャープ二次係数 Hz/μsec^2 ->", self.chirp_coeff2)

        # 93-96 B4 受信機ゲイン (dB)
        f.seek(92 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.gain = int.from_bytes(f.read(self.INTERGER4), byteorder="big")
        print("IMG: B93-96 受信機ゲイン dB ->", self.gain)

        # 117-120 B4 最初のデータまでのスラントレンジ (cm -> m)
        f.seek(116 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.DIS_NEAR_RANGE = int.from_bytes(f.read(self.INTERGER4), byteorder="big") * 1e-2
        print(
            "IMG: B117-120 最初のデータまでのスラントレンジ [m] ->",
            self.DIS_NEAR_RANGE,
        )

        # 121-124 B4 SAMPLE DELAY (nsec)
        f.seek(120 + self.NUM_SAR_DISCRIPTOR_RECORD)
        self.TIME_GATE_DELAY_T = int.from_bytes(
            f.read(self.INTERGER4), byteorder="big"
        )
        print("IMG: B121-124 SAMPLE DELAY [nsec] ->", self.TIME_GATE_DELAY_T)

        if self.TIME_GATE_DELAY_T == 0:
            # Level 1.1 仕様では 0 固定。ゲートオフセットは 0 とみなす
            self.TIME_GATE_DELAY = 0.0
        else:
            self.TIME_GATE_DELAY = self.TIME_GATE_DELAY_T * 1e-9
            self.TIME_GATE_DELAY = 0.0
        print("  -> TIME_GATE_DELAY [sec] =", self.TIME_GATE_DELAY)

        # -----------------------------
        # シグナルデータレコードのループ
        # -----------------------------
        f.seek(self.NUM_SAR_DISCRIPTOR_RECORD)
        print(
            "Num of Range (pixels):",
            self.NUM_PIXEL,
            "Num of Azimuth Line:",
            self.NUM_SIGNAL_RECORD,
        )

        self.signal = np.zeros(
            (self.NUM_SIGNAL_RECORD, self.NUM_PIXEL), dtype=np.complex64
        )

        for i in tqdm(range(self.NUM_SIGNAL_RECORD), desc="Read SLC (ALOS-4 L1.1)"):
            if i == 0:
                print(f"{'='*10} Start Time {'='*10}")
                # 1-36 バイトをまとめて読み飛ばし
                _ = f.read(36)
                # 37-40 年
                self.TIME_OBS_START_YEAR = int.from_bytes(
                    f.read(self.INTERGER4), "big"
                )
                print("IMG: B37-40 センサー取得年 ->", self.TIME_OBS_START_YEAR)
                # 41-44 通算日
                self.TIME_OBS_START_DAY = int.from_bytes(
                    f.read(self.INTERGER4), "big"
                )
                print("IMG: B41-44 センサー取得日(通算) ->", self.TIME_OBS_START_DAY)
                # 45-48 ミリ秒
                self.TIME_OBS_START_MSEC = int.from_bytes(
                    f.read(self.INTERGER4), "big"
                )
                print("IMG: B45-48 センサー取得ミリ秒 ->", self.TIME_OBS_START_MSEC)

                # L1.1 追加フィールド (SAR チャンネル/偏波コード等)
                self.sar_channel_id = int.from_bytes(f.read(self.BYTE2), "big")
                self.sar_channel_code = int.from_bytes(f.read(self.BYTE2), "big")
                self.tx_polarization_code = int.from_bytes(f.read(self.BYTE2), "big")
                self.rx_polarization_code = int.from_bytes(f.read(self.BYTE2), "big")
                print("IMG Prefix: SARチャンネルID ->", self.sar_channel_id)
                print("IMG Prefix: SARチャンネルコード ->", self.sar_channel_code)
                print("IMG Prefix: Tx偏波コード ->", self.tx_polarization_code)
                print("IMG Prefix: Rx偏波コード ->", self.rx_polarization_code)

                # ここまでで 36 + 4*3 + 2*4 = 56 byte 消費
                # 残りの prefix を読み飛ばし
                remain_prefix = self.NUM_PREFIX - 56
                if remain_prefix > 0:
                    _ = f.read(remain_prefix)

            elif i == self.NUM_SIGNAL_RECORD - 1:
                print(f"{'='*10} End Time {'='*10}")
                _ = f.read(36)
                self.TIME_OBS_END_YEAR = int.from_bytes(f.read(self.INTERGER4), "big")
                print("IMG: B37-40 センサー取得年 ->", self.TIME_OBS_END_YEAR)
                self.TIME_OBS_END_DAY = int.from_bytes(f.read(self.INTERGER4), "big")
                print("IMG: B41-44 センサー取得日(通算) ->", self.TIME_OBS_END_DAY)
                self.TIME_OBS_END_MSEC = int.from_bytes(f.read(self.INTERGER4), "big")
                print("IMG: B45-48 センサー取得ミリ秒 ->", self.TIME_OBS_END_MSEC)

                # SAR チャンネル等は開始時と同じとみなして読み飛ばし
                _ = f.read(2 + 2 + 2 + 2)  # 49-56
                remain_prefix = self.NUM_PREFIX - 56
                if remain_prefix > 0:
                    _ = f.read(remain_prefix)
            else:
                # 中間ラインの prefix は丸ごと読み飛ばす
                _ = f.read(self.NUM_PREFIX)

            # =========================
            # データ部 (SLC L1.1 本体)
            # =========================

            # L1.1 の 1 ピクセルは REAL*4 I/Q -> 32bit + 32bit = 8 byte
            n_pix = self.NUM_PIXEL
            n_bytes = n_pix * self.bytes_per_group

            buf = f.read(n_bytes)
            if len(buf) != n_bytes:
                raise IOError(
                    f"SAR データの読み込みに失敗しました: 期待 {n_bytes} byte, 実際 {len(buf)} byte"
                )

            # Big Endian float32 で I, Q を読む
            # buf の並び: I0, Q0, I1, Q1, ... (REAL*4, Big Endian)
            iq = np.frombuffer(buf, dtype=">f4")
            if iq.size != 2 * n_pix:
                raise IOError(
                    f"ピクセル数不整合: 期待 {2*n_pix} 要素, 実際 {iq.size} 要素"
                )

            iq = iq.astype(np.float32, copy=False).reshape(-1, 2)
            i_real = iq[:, 0]
            q_imag = iq[:, 1]

            # 複素数にして self.signal の 1 ラインに格納
            self.signal[i,:] = i_real + 1j * q_imag

            # 右詰めピクセル (通常 0)
            if self.NUM_BLANK_PIXEL > 0:
                _ = f.read(self.NUM_BLANK_PIXEL * self.bytes_per_group)

        f.close()

        # ------------------------------------------------------
        # LED File Reader (SAR リーダファイル)
        #   表 4.6-4, 4.6-5, 4.6-7 などに対応
        # ------------------------------------------------------
        f = open(self.PATH_LED, "rb")

        # SAR リーダファイルディスクリプタレコード長
        f.seek(8)
        self.led_record_length = int.from_bytes(
            f.read(self.INTERGER4), byteorder="big"
        )
        print(
            "LED: B9-12 リーダファイルディスクリプタレコード長 ->",
            self.led_record_length,
        )

        # 181-192: 各種レコード数・長さ
        f.seek(180)
        self.summary_record = int(f.read(self.INTERGER6))
        print("LED: データセットサマリレコード数 ->", self.summary_record)
        f.seek(186)
        self.summary_record_length = int(f.read(self.INTERGER6))
        print("LED: データセットサマリレコード長 ->", self.summary_record_length)

        f.seek(192)
        self.map_record = int(f.read(self.INTERGER6))
        print("LED: 地図投影データレコード数 ->", self.map_record)
        f.seek(198)
        self.map_record_length = int(f.read(self.INTERGER6))
        print("LED: 地図投影データレコード長 ->", self.map_record_length)

        f.seek(210)
        self.platform_record_length = int(f.read(self.INTERGER6))
        print(
            "LED: プラットフォーム位置データレコード長 ->",
            self.platform_record_length,
        )
        f.seek(222)
        self.attitude_record_length = int(f.read(self.INTERGER6))
        print("LED: 姿勢データレコード長 ->", self.attitude_record_length)

        # その他のレコード長（必要になれば使用）
        f.seek(234)
        self.radiometric_record_length = int(f.read(self.INTERGER6))
        f.seek(246)
        self.radiometric_comp_record_length = int(f.read(self.INTERGER6))
        f.seek(258)
        self.data_quality_record_length = int(f.read(self.INTERGER6))
        f.seek(270)
        self.data_histogram_record_length = int(f.read(self.INTERGER6))
        f.seek(282)
        self.range_spectrum_record_length = int(f.read(self.INTERGER6))
        f.seek(294)
        self.dem_record_length = int(f.read(self.INTERGER6))
        f.seek(342)
        tmp = str(f.read(self.INTERGER6))
        self.calibration_record_length = tmp

        # 表 4.6-5 データセットサマリレコード
        f.seek(self.led_record_length + 8)
        self.summary_record_length_B4 = int.from_bytes(
            f.read(self.INTERGER4), byteorder="big"
        )
        print(
            "LED: データセットサマリレコード長(B4) ->",
            self.summary_record_length_B4,
        )

        # シーン ID
        f.seek(self.led_record_length + 20)
        self.scene_id = f.read(self.FLOAT32).decode("utf-8")
        print("LED: シーンID ->", self.scene_id.strip())

        # シーンセンター時刻
        f.seek(self.led_record_length + 68)
        self.scene_time = f.read(self.FLOAT32).decode("utf-8")
        print("LED: シーンセンター時刻 ->", self.scene_time.strip())

        # 楕円体モデル・半径など
        f.seek(self.led_record_length + 164)
        self.ellipsoid_model = f.read(self.FLOAT16).decode("utf-8")
        print("LED: 楕円体モデル ->", self.ellipsoid_model.strip())

        f.seek(self.led_record_length + 180)
        self.ellipsoid_radius = float(f.read(self.FLOAT16))
        print("LED: 楕円体の半長径(km) ->", self.ellipsoid_radius)

        f.seek(self.led_record_length + 196)
        self.ellipsoid_short_radius = float(f.read(self.FLOAT16))
        print("LED: 楕円体の短半径(km) ->", self.ellipsoid_short_radius)

        f.seek(self.led_record_length + 212)
        self.earth_mass = float(f.read(self.FLOAT16))
        print("LED: 地球の質量(10^24 kg) ->", self.earth_mass)

        f.seek(self.led_record_length + 244)
        self.j2 = float(f.read(self.FLOAT16))
        self.j3 = float(f.read(self.FLOAT16))
        self.j4 = float(f.read(self.FLOAT16))
        print("LED: J2 ->", self.j2)
        print("LED: J3 ->", self.j3)
        print("LED: J4 ->", self.j4)

        f.seek(self.led_record_length + 388)
        self.sar_channel = int(f.read(self.INTERGER4))
        print("LED: SARチャネル数 ->", self.sar_channel)

        f.seek(self.led_record_length + 396)
        self.sensor_platform = f.read(self.FLOAT16).decode("utf-8")
        print("LED: センサプラットフォーム名 ->", self.sensor_platform.strip())

        # 波長 λ [m]
        f.seek(self.led_record_length + 500)
        self.LAMBDA = float(f.read(self.FLOAT16))
        print("LED: 波長 λ [m] ->", self.LAMBDA)

        # Motion compensation indicator
        f.seek(self.led_record_length + 516)
        self.motion_compensation = f.read(self.BYTE2).decode("utf-8")
        print(
            "LED: Motion compensation indicator ->",
            self.motion_compensation.strip(),
        )

        # レンジパルスコード種別
        f.seek(self.led_record_length + 518)
        self.range_pulse_code = f.read(self.FLOAT16).decode("utf-8")
        print("LED: レンジパルスコード ->", self.range_pulse_code.strip())

        # レンジパルス振幅係数 (1-5)
        f.seek(self.led_record_length + 534)
        self.range_pulse_amplitude = float(f.read(self.FLOAT16))
        self.range_pulse_amplitude2 = float(f.read(self.FLOAT16))
        self.range_pulse_amplitude3 = float(f.read(self.FLOAT16))
        self.range_pulse_amplitude4 = float(f.read(self.FLOAT16))
        self.range_pulse_amplitude5 = float(f.read(self.FLOAT16))
        print("LED: レンジパルス振幅係数1 ->", self.range_pulse_amplitude)
        print("LED: レンジパルス振幅係数2 ->", self.range_pulse_amplitude2)
        print("LED: レンジパルス振幅係数3 ->", self.range_pulse_amplitude3)
        print("LED: レンジパルス振幅係数4 ->", self.range_pulse_amplitude4)
        print("LED: レンジパルス振幅係数5 ->", self.range_pulse_amplitude5)

        # サンプリング周波数・レンジゲート・レンジパルス幅
        f.seek(self.led_record_length + 710)
        self.sampling_frequency_mhz = float(f.read(self.FLOAT16))
        print("LED: サンプリング周波数(MHz) ->", self.sampling_frequency_mhz)

        f.seek(self.led_record_length + 726)
        self.range_gate = float(f.read(self.FLOAT16))
        print("LED: レンジゲート(μsec) ->", self.range_gate)

        f.seek(self.led_record_length + 742)
        self.range_pulse_width = float(f.read(self.FLOAT16))
        print("LED: レンジパルス幅(μsec) ->", self.range_pulse_width)

        # 量子化記述子
        f.seek(self.led_record_length + 806)
        self.quantization_descriptor = f.read(12).decode("utf-8")
        print("LED: 量子化記述子 ->", self.quantization_descriptor.strip())

        # DC バイアス / I-Q ゲイン不均衡
        f.seek(self.led_record_length + 818)
        self.DC_BIAS_I = float(f.read(self.FLOAT16))
        self.DC_BIAS_Q = float(f.read(self.FLOAT16))
        self.gain_imbalance = float(f.read(self.FLOAT16))
        print("LED: I成分DCバイアス ->", self.DC_BIAS_I)
        print("LED: Q成分DCバイアス ->", self.DC_BIAS_Q)
        print("LED: I/Qゲイン不均衡 ->", self.gain_imbalance)

        # 電子および機械ボアサイト
        f.seek(self.led_record_length + 898)
        tmp = str(f.read(self.INTERGER6))
        if tmp != "      ":
            warnings.warn("LED: 電子ボアサイトのフィールドに数値以外が含まれています")
        self.electronic_boresight = tmp
        print("LED: electronic boresight ->", self.electronic_boresight)

        f.seek(self.led_record_length + 914)
        tmp = str(f.read(self.INTERGER6))
        if tmp != "                ":
            warnings.warn("LED: 機械ボアサイトのフィールドに数値以外が含まれています")
        self.mechanical_boresight = tmp
        print("LED: mechanical boresight ->", self.mechanical_boresight)

        # PRF (mHz) from LED
        f.seek(self.led_record_length + 934)
        self.prf_from_led = float(f.read(self.FLOAT16))
        print("LED: PRF(mHz) ->", self.prf_from_led)

        # 2-way ビーム幅 (elevation / azimuth)
        f.seek(self.led_record_length + 950)
        tmp = str(f.read(self.INTERGER6))
        if tmp != "      ":
            warnings.warn("LED: 2wayビーム幅(El)のフィールドに数値以外が含まれています")
        self.beam_width_elevation_str = tmp
        f.seek(self.led_record_length + 966)
        tmp = str(f.read(self.INTERGER6))
        if tmp != "      ":
            warnings.warn("LED: 2wayビーム幅(Az)のフィールドに数値以外が含まれています")
        self.beam_width_azimuth_str = tmp
        print("LED: 2wayビーム幅(El) ->", self.beam_width_elevation_str)
        print("LED: 2wayビーム幅(Az) ->", self.beam_width_azimuth_str)

        # バイナリ時刻コード / 衛星クロック
        f.seek(self.led_record_length + 982)
        self.binary_time = int(f.read(self.FLOAT16))
        self.clock_time = f.read(self.FLOAT32).decode("utf-8")
        self.clock_increase = int(f.read(self.FLOAT16))
        print("LED: 衛星バイナリ時刻コード ->", self.binary_time)
        print("LED: 衛星クロック時刻 ->", self.clock_time.strip())
        print("LED: クロック増加量[nsec] ->", self.clock_increase)

        # 時間方向指標
        f.seek(self.led_record_length + 1534)
        self.time_index = f.read(8).decode("utf-8")
        print("LED: 時間方向指標 ->", self.time_index.strip())

        # PRF 変化点フラグ / ライン
        f.seek(self.led_record_length + 1802)
        self.prf_change_flag = f.read(self.INTERGER4).decode("utf-8")
        print("LED: PRF変化点フラグ ->", self.prf_change_flag.strip())

        f.seek(self.led_record_length + 1806)
        tmp = f.read(8).decode("utf-8")
        if tmp != "        ":
            warnings.warn("LED: PRF変化開始ライン番号のフィールドに数値以外が含まれています")
        self.prf_change_line = tmp
        print("LED: PRF変化開始ライン番号 ->", self.prf_change_line)
        
        # 110 1823-1830 A8ライン方向に沿った時間方向指標（実績値）アセンディング= 'ASCENDbb'ディセンディング= 'DESCENDb'
        f.seek(self.led_record_length + 1822)  # 1823 - 1
        self.time_direction_index = f.read(8).decode("utf-8")
        print("LED: ライン方向に沿った時間方向指標 ->", self.time_direction_index.strip())
        print(f"-->> 軌道方向: {'昇交点通過後' if self.time_direction_index.startswith('ASCEND') else '降交点通過後'}")

        # ヨーステアリング・オフナディア角・アンテナビーム番号
        # 表 4.6-24 に対応（バイト No. は 1 始まり）:contentReference[oaicite:1]{index=1}

        # 145: 2427–2430 I4 ヨーステアリングの有無フラグ
        f.seek(self.led_record_length + 2426)  # 2427 - 1
        self.yaw_steering_flag = f.read(self.INTERGER4).decode("ascii")
        print("LED: ヨーステアリング有無 ->", self.yaw_steering_flag.strip())

        # 146: 2431–2434 I4 パラメータ自動設定テーブル番号（必要なら保持）
        f.seek(self.led_record_length + 2430)  # 2431 - 1
        self.param_auto_table_no = f.read(self.INTERGER4).decode("ascii").strip()
        print("LED: パラメータ自動設定テーブル番号 ->", self.param_auto_table_no)

        # 147: 2435–2450 F16.7 オフナディア角 実績値
        f.seek(self.led_record_length + 2434)  # 2435 - 1
        off_nadir_raw = f.read(self.FLOAT16).decode("ascii")
        tokens = off_nadir_raw.split()
        if len(tokens) == 0:
            self.off_nadir_angle = float("nan")
        else:
            self.off_nadir_angle = float(tokens[0])
            if len(tokens) > 1:
                warnings.warn(
                    f"LED: オフナディア角フィールドに余分な値があります: {off_nadir_raw!r}"
                )
        print("LED: オフナディア角[deg] ->", self.off_nadir_angle)

        # 148: 2451–2454 I4 アンテナビーム番号
        f.seek(self.led_record_length + 2450)  # 2451 - 1
        beam_str = f.read(self.INTERGER4).decode("ascii").strip()
        self.antenna_beam_number = int(beam_str)
        print("LED: アンテナビーム番号 ->", self.antenna_beam_number)

        # Level 1.1 追加: レンジ/アジマススペーシングなど
        f.seek(self.led_record_length + 1670)
        self.range_processing_mode = f.read(8).decode("utf-8")
        self.azimuth_look_flag = f.read(4).decode("utf-8")
        tmp = f.read(4).decode("utf-8")
        if tmp != "    ":
            warnings.warn("LED: レンジルック数のフィールドに数値以外が含まれています")
        self.range_look_flag = tmp
        tmp = f.read(self.FLOAT16)
        if tmp != "    ":
            warnings.warn("LED: アジマスルック数のフィールドに数値以外が含まれています")
        self.line_spacing = tmp
        tmp = f.read(self.FLOAT16)
        if tmp != "    ":
            warnings.warn("LED: ピクセルスペーシングのフィールドに数値以外が含まれています")
        self.pixel_spacing = tmp
        self.chirp_extraction_mode = f.read(16).decode("utf-8")

        print("LED: RANGE/OTHER ->", self.range_processing_mode.strip())
        print("LED: ラインスペーシング[m] ->", self.line_spacing)
        print("LED: ピクセルスペーシング[m] ->", self.pixel_spacing)
        print("LED: CHIRP extraction mode ->", self.chirp_extraction_mode.strip())

        # ------------------------------------------------------
        # 表 4.6-7 プラットフォーム位置データレコード
        #   （軌道データ：時刻、位置ベクトル、速度ベクトル）
        # ------------------------------------------------------
        f.seek(self.led_record_length + self.summary_record_length + 8)
        self.platform_record_length_B4 = int.from_bytes(
            f.read(self.INTERGER4), byteorder="big"
        )
        print(
            "LED: プラットフォーム位置データレコード長(B4) ->",
            self.platform_record_length_B4,
        )

        f.seek(self.led_record_length + self.summary_record_length + 12)
        self.orbit_type = f.read(self.FLOAT32).decode("utf-8")
        print("LED: 軌道要素種類 ->", self.orbit_type.strip())

        f.seek(self.led_record_length + self.summary_record_length + 140)
        self.NUM_ORB_POINT = int(f.read(self.INTERGER4))
        print("LED: データポイント数 ->", self.NUM_ORB_POINT)

        f.seek(self.led_record_length + self.summary_record_length + 144)
        self.TIME_ORB_YEAR = int(f.read(self.INTERGER4))
        self.TIME_ORB_MONTH = int(f.read(self.INTERGER4))
        self.TIME_ORB_DAY = int(f.read(self.INTERGER4))
        self.TIME_ORB_COUNT_DAY = int(f.read(self.INTERGER4))
        self.TIME_ORB_SEC = float(f.read(self.FLOAT22))
        print("LED: 第1ポイント年 ->", self.TIME_ORB_YEAR)
        print("LED: 第1ポイント通算日 ->", self.TIME_ORB_COUNT_DAY)
        print("LED: 第1ポイント通算秒 ->", self.TIME_ORB_SEC)

        f.seek(self.led_record_length + self.summary_record_length + 182)
        self.TIME_INTERVAL = float(f.read(self.FLOAT22))
        print("LED: ポイント間インターバル秒 ->", self.TIME_INTERVAL)

        f.seek(self.led_record_length + self.summary_record_length + 204)
        self.reference_coordinate = f.read(self.FLOAT64).decode("utf-8")
        print("LED: 参照座標系 ->", self.reference_coordinate.strip())

        # 位置・速度の誤差（必要なら利用）
        f.seek(self.led_record_length + self.summary_record_length + 290)
        self.position_error = float(f.read(self.FLOAT16))
        f.seek(self.led_record_length + self.summary_record_length + 306)
        self.position_error2 = float(f.read(self.FLOAT16))
        f.seek(self.led_record_length + self.summary_record_length + 322)
        self.position_error3 = float(f.read(self.FLOAT16))
        f.seek(self.led_record_length + self.summary_record_length + 338)
        self.velocity_error = float(f.read(self.FLOAT16))
        f.seek(self.led_record_length + self.summary_record_length + 354)
        self.velocity_error2 = float(f.read(self.FLOAT16))
        f.seek(self.led_record_length + self.summary_record_length + 370)
        self.velocity_error3 = float(f.read(self.FLOAT16))

        # 位置・速度ベクトル
        f.seek(self.led_record_length + self.summary_record_length + 386)
        self.position_vector = np.zeros((self.NUM_ORB_POINT, 3), dtype=np.float64)
        self.velocity_vector = np.zeros((self.NUM_ORB_POINT, 3), dtype=np.float64)
        for i in range(self.NUM_ORB_POINT):
            self.position_vector[i, 0] = float(f.read(self.FLOAT22))
            self.position_vector[i, 1] = float(f.read(self.FLOAT22))
            self.position_vector[i, 2] = float(f.read(self.FLOAT22))
            self.velocity_vector[i, 0] = float(f.read(self.FLOAT22))
            self.velocity_vector[i, 1] = float(f.read(self.FLOAT22))
            self.velocity_vector[i, 2] = float(f.read(self.FLOAT22))

        print("LED: 第1データポイント位置ベクトル ->", self.position_vector[0])
        print("LED: 最終データポイント速度ベクトル ->", self.velocity_vector[-1])

        # うるう秒フラグ
        f.seek(self.led_record_length + self.summary_record_length + 4100)
        self.leap_second_flag = int(f.read(self.BYTE1))
        print("LED: うるう秒フラグ ->", self.leap_second_flag)

        # ------------------------------------------------------
        # 姿勢データレコード（ここでは先頭部分のみ読んでおく）
        # ------------------------------------------------------
        f.seek(
            self.led_record_length
            +self.summary_record_length
            +self.platform_record_length
            +8
        )
        self.attitude_record_length_B4 = int.from_bytes(
            f.read(self.INTERGER4), byteorder="big"
        )
        print("LED: 姿勢データレコード長(B4) ->", self.attitude_record_length_B4)

        f.seek(
            self.led_record_length
            +self.summary_record_length
            +self.platform_record_length
            +12
        )
        self.point_number = int(f.read(self.INTERGER4))
        print("LED: 姿勢ポイント数 ->", self.point_number)

        # 姿勢時系列（ピッチ・ロール・ヨーなど）は必要に応じて実装
        self.points_pitches = np.zeros(self.point_number, dtype=np.float32)
        self.points_rolls = np.zeros(self.point_number, dtype=np.float32)
        self.points_yaws = np.zeros(self.point_number, dtype=np.float32)

        f.close()
        print("CEOS PALSAR-3 L1.1 SLC データの読み込み完了\n")

        # ------------------------------------------------------------------
        # スケール・幾何計算用の共通パラメータ
        # ------------------------------------------------------------------
        self.NUM_APERTURE_SAMPLE = self.NUM_SIGNAL_RECORD  # default full azimuth

        self.FREQ_AD_SAMPLE = self.sampling_frequency_mhz * 1e6
        self.FREQ_PULSE_REPETITION = self.prf_mhz * 1e-3
        self.TIME_PLUSE_DURATION = self.chirp_length * 1e-9
        self.DIS_ELLIPSOID_RADIUS = self.ellipsoid_radius * 1e3
        self.DIS_ELLIPSOID_SHORT_RADIUS = self.ellipsoid_short_radius * 1e3

        print("共通パラメータの設定完了\n")

    # --------------------------------------------------------------
    # 観測ジオメトリ設定（ALOS-4 PALSAR-3 版）
    # --------------------------------------------------------------
    def set_geometory(self, plot: bool=False, PATH_OUTPUT: Optional[str]=None, output_json_path: str=None):
        """
        観測ジオメトリの設定

        IMG/LED から読み出した軌道情報を用いて、観測中の
        衛星位置ベクトル・速度ベクトル・スラントレンジサンプル
        などを計算する（ALOS-4 PALSAR-3 仕様に対応）。
        """

        self.TIME_SHIFT = 0.0  # [sec]
        self.NUM_APERTURE_SAMPLE = self.NUM_SIGNAL_RECORD  # default full azimuth

        # 軌道情報の時刻配列
        self.time_orbit = np.arange(
            self.TIME_DAY_SEC * self.TIME_ORB_COUNT_DAY + self.TIME_ORB_SEC,
            self.TIME_DAY_SEC * self.TIME_ORB_COUNT_DAY
            +self.TIME_ORB_SEC
            +self.TIME_INTERVAL * self.NUM_ORB_POINT,
            self.TIME_INTERVAL,
        )

        # 軌道位置ベクトルの補間関数
        self.func_intp_orbit_x_recode_time = interp1d(
            self.time_orbit, self.position_vector[:, 0], kind="cubic", axis=0
        )
        self.func_intp_orbit_y_recode_time = interp1d(
            self.time_orbit, self.position_vector[:, 1], kind="cubic", axis=0
        )
        self.func_intp_orbit_z_recode_time = interp1d(
            self.time_orbit, self.position_vector[:, 2], kind="cubic", axis=0
        )

        # 観測開始／終了時刻（アパーチャ長分だけ確保）
        # Equation - Condition: No 2.12
        # # Obs Day Fraction := D + (msec/10^4 + shift) / day_sec
        self.TIME_OBS_START_ = self.TIME_OBS_START_DAY + (
            self.TIME_OBS_START_MSEC / self.DIGIT4 + self.TIME_SHIFT
        ) / self.TIME_DAY_SEC
        # Equation - Condition: No 2.13
        # # Obs Start Time := day_sec * T_obs + (N * 0) / PRF
        self.TIME_OBS_START_SEC = self.TIME_DAY_SEC * self.TIME_OBS_START_ + (
            self.NUM_APERTURE_SAMPLE * 0.0
        ) / self.FREQ_PULSE_REPETITION
        # Equation - Condition: No 2.14
        # # Obs End Time := day_sec * T_obs + (N * 1) / PRF
        self.TIME_OBS_END_SEC = self.TIME_DAY_SEC * self.TIME_OBS_START_ + (
            self.NUM_APERTURE_SAMPLE * 1.0
        ) / self.FREQ_PULSE_REPETITION

        print("観測開始時刻 (秒):", self.TIME_OBS_START_SEC)
        print("観測終了時刻 (秒):", self.TIME_OBS_END_SEC)
        print("観測期間 (秒):", self.TIME_OBS_END_SEC - self.TIME_OBS_START_SEC)

        if plot and PATH_OUTPUT is not None:
            num_orb_counts = np.arange(0, self.NUM_ORB_POINT, 1)
            plt.figure(figsize=(12, 4), dpi=80, facecolor="w", edgecolor="k")
            plt.title("ALOS-4 PALSAR-3 L1.1 Orbit TimeSeries")
            plt.scatter(num_orb_counts, self.time_orbit, label="Orbit Recording Point")
            plt.plot(
                num_orb_counts,
                self.time_orbit,
                label="Orbit Recording Line",
                linestyle="-",
            )
            plt.axhline(y=self.TIME_OBS_START_SEC, linestyle="-", label="Start time")
            plt.axhline(y=self.TIME_OBS_END_SEC, linestyle="--", label="End time")
            plt.legend(loc="upper left")
            plt.xlabel("Sample Count [n]")
            plt.ylabel("Time [sec]")
            plt.tight_layout()
            plt.savefig(
                os.path.join(PATH_OUTPUT, "orbit_timeseries_ALOS4_L11.png"),
                bbox_inches="tight",
                format="png",
                dpi=160,
            )
            plt.close()

        # 観測期間の衛星位置ベクトル
        # Equation - Condition: No 2.15 from No 2.11
        # # Observation Time Grid := N samples linspace(T_start, T_end, N)
        self.TIMES_OBS = np.linspace(
            self.TIME_OBS_START_SEC, self.TIME_OBS_END_SEC, self.NUM_APERTURE_SAMPLE
        )
        self.P_X_SAT = self.func_intp_orbit_x_recode_time(self.TIMES_OBS)
        self.P_Y_SAT = self.func_intp_orbit_y_recode_time(self.TIMES_OBS)
        self.P_Z_SAT = self.func_intp_orbit_z_recode_time(self.TIMES_OBS)
        # Equation - Condition: No 2.16
        # # Satellite Range := sqrt(X² + Y² + Z²)
        self.P_SAT = np.sqrt(self.P_X_SAT ** 2 + self.P_Y_SAT ** 2 + self.P_Z_SAT ** 2)

        # 観測期間の衛星速度ベクトル
        self.func_intp_orbit_vx_recode_time = interp1d(
            self.time_orbit, self.velocity_vector[:, 0], kind="cubic", axis=0
        )
        self.func_intp_orbit_vy_recode_time = interp1d(
            self.time_orbit, self.velocity_vector[:, 1], kind="cubic", axis=0
        )
        self.func_intp_orbit_vz_recode_time = interp1d(
            self.time_orbit, self.velocity_vector[:, 2], kind="cubic", axis=0
        )

        self.V_X_SAT = self.func_intp_orbit_vx_recode_time(self.TIMES_OBS)
        self.V_Y_SAT = self.func_intp_orbit_vy_recode_time(self.TIMES_OBS)
        self.V_Z_SAT = self.func_intp_orbit_vz_recode_time(self.TIMES_OBS)

        # レンジ方向サンプル距離
        # Equation - Condition: No 2.17
        # # Slant Range Spacing := (Speed of Light) / (2 * f_s)
        self.DIS_RANGE_SLANT = self.SOL / (2.0 * self.FREQ_AD_SAMPLE)
        print("レンジ方向サンプル距離 [m]: ", self.DIS_RANGE_SLANT)
        # Equation - Condition: No 2.18
        # # Far Range := R_near + (N - 1) * dR
        self.DIS_FAR_RANGE = (
            self.DIS_NEAR_RANGE + (self.NUM_PIXEL - 1) * self.DIS_RANGE_SLANT
        )

        # 電離層遅延はここでは 0 として扱う
        self.dis_ionosphere_delay = 0.0
        print(f"電離層遅延補正距離: {self.dis_ionosphere_delay:.2f} m")

        self.DIS_NEAR_RANGE -= self.dis_ionosphere_delay
        self.DIS_FAR_RANGE -= self.dis_ionosphere_delay

        # Equation - Condition: No 2.19 from No 2.18
        # # Slant Range Samples := N samples linspace(R_near, R_far, N)
        self.SLANT_RANGE_SAMPLE = np.linspace(
            self.DIS_NEAR_RANGE,
            self.DIS_FAR_RANGE,
            self.NUM_PIXEL,
        )
        print(f"ニアレンジ: {self.DIS_NEAR_RANGE} m, ファーレンジ: {self.DIS_FAR_RANGE} m")

        # 高度計算
        # Equation - Condition: No 2.20
        # # Satellite Latitude angle phi φ := ArcSin(Z / |Position Satellite|)
        self.P_SAT_LATITUDE = np.arcsin(self.P_Z_SAT / self.P_SAT)
        self.SIN_SAT_LATITUDE = np.sin(self.P_SAT_LATITUDE)
        self.COS_SAT_LATITUDE = np.cos(self.P_SAT_LATITUDE)

        # Equation - Condition: No 2.21
        # # Earth Radius := 1 / sqrt(cos²φ/a² + sin²φ/b²)
        self.P_EARTH_RADIUS = np.divide(
            1.0,
            np.sqrt(
                self.COS_SAT_LATITUDE ** 2 / self.DIS_ELLIPSOID_RADIUS ** 2
                +self.SIN_SAT_LATITUDE ** 2 / self.DIS_ELLIPSOID_SHORT_RADIUS ** 2
            ),
        )
        # Equation - Condition: No 2.22
        # # Satellite Height := |Position Satellite| - Earth Radius
        self.HEIGHT_SAT = self.P_SAT - self.P_EARTH_RADIUS
        print(f"平均衛星高度: {np.mean(self.HEIGHT_SAT):.2f} m")
        if output_json_path:
            _write_observation_json(self, output_json_path)
