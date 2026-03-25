![img](./doc/figure/001_project_icon.png)

Azayaka is a QGIS plugin for processing Synthetic Aperture Radar (SAR) data. It supports JAXA CEOS format SAR data and provides tools for InSAR (Interferometric SAR) analysis and geocoding.

## Installation

1. install required libraries for running azayaka-plugin in your QGIS environment
    - download azayaka\requirements.txt in your download directory
    - Open the OSGeo4W shell as an administrator and run the following command:
        - ```pip install -r 'path/to/requirements.txt'```
            where 'path/to/requirements.txt' means the absolute path to azayaka\requirements.txt

2. install "Azayaka" in the following two ways:
    - case-1(easy): Search for "Azayaka" in the QGIS Plugin Manager and install.
    - case-2: open OSGeo4W shell and run ```pip install azayaka```
        - OSGeo4W is available for Windows user

## Requirements

- Python 3.9+

## Usage

1. In QGIS, navigate to the menu and select "Plugins" → "Azayaka Plugin".
2. In the dialog, choose the desired processing tab (InSAR or Geocoding).
3. Set the required input parameters and click the OK button.
4. When the process is complete, results will be saved in your specified output directory.

## example usage on YouTube
coming soon

## License

Licensed under the GNU Affero General Public License v3.0.
