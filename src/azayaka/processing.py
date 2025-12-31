# -*- coding: utf-8 -*-
"""
Azayaka: 
    SAR/InSAR Processing Handler Module.
    Summary module for various SAR/InSAR data processing tasks.

    Copyright (c) 2026 Syusuke Yasui, Yutaka Yamamoto, and contributors.
    Licensed under the APGL-3.0 License.

"""
    
# Import sub-modules
from . import fileformat
from . import geocode
from . import interferometory

__all__ = ["format", "geocode", "interferometory"]
