# -*- coding: utf-8 -*-
"""
Azayaka: 
    SAR/InSAR Python Package.
    It includes various utilities for SAR/InSAR data processing and analysis.
    
    QGIS Plugin "Azayaka" is also provided for easy access to some functionalities.

    Copyright (c) 2026 Syusuke Yasui, Yutaka Yamamoto, and contributors.
    Licensed under the APGL-3.0 License.

"""

__all__ = ["__version__"]

__version__ = "0.1.1"

AA_STR = r"""
 ____    _    ____        _                                    _            
/ ___|  / \  |  _ \      / \     ____   __ _   _   _    __ _  | | __   __ _ 
\___ \ / _ \ | |_) |    / _ \   |_  /  / _` | | | | |  / _` | | |/ /  / _` |
 ___) / ___ \|  _ <    / ___ \   / /  | (_| | | |_| | | (_| | |   <  | (_| |
|____/_/   \_\_| \_\  /_/   \_\ /___|  \__,_|  \__, |  \__,_| |_|\_\  \__,_|
                                               |___/   
"""

print(AA_STR, f"Version {__version__}", flush=True)
