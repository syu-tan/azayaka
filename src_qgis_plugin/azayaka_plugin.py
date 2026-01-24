# -*- coding: utf-8 -*
import os
import sys
import logging
from datetime import datetime

# qgis
from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox

# azayaka qgis-plugin src files(dialog, resources, etc.)
from .resources import *
from .azayaka_plugin_dialog import AzayakaPluginDialog

# azayaka src modules
try:
    from azayaka.fileformat import CEOS_PALSAR2_L11_SLC
    from azayaka.interferometry import Interferometry
    from azayaka.geocode import Geocode
except ImportError as e:
    QMessageBox.warning(None, "Import Error", f"Failed to import azayaka modules: {str(e)}")


class AzayakaPlugin:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        self.iface = iface
        self.actions = []
        self.menu = '&Azayaka'
        self.first_start = None
        
        # Fix sys.stdout for tqdm in QGIS environment
        self._fix_stdout_for_tqdm()
        
        # Setup logger
        self.logger = self._setup_logger()
    
    def _fix_stdout_for_tqdm(self):
        """Fix sys.stdout for tqdm in QGIS plugin environment"""
        # QGIS plugin environment may have sys.stdout as None
        # tqdm requires a valid file-like object
        if sys.stdout is None:
            # Create a dummy file-like object that discards output
            # Using open(os.devnull, 'w') is better than StringIO for discarding
            sys.stdout = open(os.devnull, 'w', encoding='utf-8')
        # Also ensure stderr is set if it's None
        if sys.stderr is None:
            sys.stderr = open(os.devnull, 'w', encoding='utf-8')
    
    def _setup_logger(self):
        """Setup logger with file handler"""
        logger = logging.getLogger('AzayakaPlugin')
        logger.setLevel(logging.INFO)
        
        # Remove existing handlers to avoid duplicates
        logger.handlers.clear()
        
        # Create log directory if it doesn't exist
        plugin_dir = os.path.dirname(__file__)
        log_dir = os.path.join(plugin_dir, 'log')
        os.makedirs(log_dir, exist_ok=True)
        
        # Create log file with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = os.path.join(log_dir, f'azayaka_plugin_{timestamp}.log')
        
        # File handler
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        
        # Console handler (optional, for QGIS Python console)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        # Add handlers
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        
        logger.info(f"Logger initialized. Log file: {log_file}")
        
        return logger

    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None):
        """Add a toolbar icon to the toolbar"""
        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            self.iface.addToolBarIcon(action)

        if add_to_menu:
            self.iface.addPluginToMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""
        icon_path = ':/plugins/azayaka_plugin/icon.png'
        self.add_action(
            icon_path,
            text='Azayaka Plugin',
            callback=self.run,
            parent=self.iface.mainWindow())

        self.first_start = True


    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginMenu(
                '&Azayaka',
                action)
            self.iface.removeToolBarIcon(action)


    def run(self):
        """Run method that performs all the real work"""
        self.logger.info("Plugin run method called")
        if self.first_start == True:
            self.first_start = False
            self.dlg = AzayakaPluginDialog()
            self.logger.info("Dialog created")

        self.dlg.show()
        result = self.dlg.exec_()
        if result:
            try:
                current_tab = self.dlg.get_current_tab_index()
                self.logger.info(f"Processing started. Tab index: {current_tab}")
                
                if current_tab == 0: # InSAR tab
                    self._run_insar_processing()
                elif current_tab == 1: # Geocoding tab
                    self._run_geocoding_processing()
                else:
                    self.logger.warning(f"Unknown tab index: {current_tab}")
                    QMessageBox.warning(None, "Error", "Unknown tab was found")
            except Exception as e:
                self.logger.error(f"Error occurred during processing: {str(e)}", exc_info=True)
                QMessageBox.critical(None, "Processing Error", f"An error occurred during processing:\n{str(e)}")

    def _run_insar_processing(self):
        """Run InSAR processing"""
        self.logger.info("Starting InSAR processing")
        inputs = self.dlg.get_insar_inputs()
        
        if not inputs['pre_event_dir']:
            self.logger.warning("Pre-event Dir is required")
            QMessageBox.warning(None, "Input Error", "Pre-event Dir is required")
            return
        if not inputs['post_event_dir']:
            self.logger.warning("Post-event Dir is required")
            QMessageBox.warning(None, "Input Error", "Post-event Dir is required")
            return
        if not inputs['output_dir']:
            self.logger.warning("Output Dir is required")
            QMessageBox.warning(None, "Input Error", "Output Dir is required")
            return
        if not inputs['dem_path']:
            self.logger.warning("DEM Path is required")
            QMessageBox.warning(None, "Input Error", "DEM Path is required")
            return
        
        try:
            self.logger.info(f"Pre-event Dir: {inputs['pre_event_dir']}")
            self.logger.info(f"Post-event Dir: {inputs['post_event_dir']}")
            self.logger.info(f"Output Dir: {inputs['output_dir']}")
            self.logger.info(f"DEM Path: {inputs['dem_path']}")
            os.makedirs(inputs['output_dir'], exist_ok=True)
            path_main_metadata_json = os.path.join(inputs['output_dir'], "main_metadata.json")
            path_sub_metadata_json = os.path.join(inputs['output_dir'], "sub_metadata.json")
            
            # TODO: POLARIMETORY and ORBIT_NAME should be automatically determined from the files
            main_ceos = CEOS_PALSAR2_L11_SLC(
                PATH_CEOS_FOLDER=inputs['pre_event_dir'],
                POLARIMETORY="HH",
                ORBIT_NAME="A",
            )
            main_ceos.set_geometory(plot=False, output_json_path=path_main_metadata_json)
            
            sub_ceos = CEOS_PALSAR2_L11_SLC(
                PATH_CEOS_FOLDER=inputs['post_event_dir'],
                POLARIMETORY="HH",
                ORBIT_NAME="A",
            )
            sub_ceos.set_geometory(plot=False, output_json_path=path_sub_metadata_json)
            
            interferometry = Interferometry(main_ceos, sub_ceos)
            
            outputs = interferometry.process(
                output_dir=inputs['output_dir'],
                dem_path=inputs['dem_path'],
                output_prefix="insar",
                fine_registration=True,
                coherence_window=4,
                fine_shift_range=3,
                fine_stride=1,
                multilook_azimuth=16,
                multilook_range=16,
                goldstein_alpha=0.25,
                goldstein_patch_size=64,
                goldstein_step=16,
                goldstein_filter_size=3,
                dem_coreg_window_size=64,
                dem_coreg_shift_range=3,
                dem_coreg_stride=1,
                slc_coreg_coarse_downsample=4,
                sub_buffer=500,
                coherence_histogram_threshold=0.5,
            )
            
            self.logger.info("InSAR processing completed successfully")
            message = "InSAR processing completed successfully!\n\nOutput files:\n"
            for key, path in outputs.items():
                message += f"{key}: {path}\n"
                self.logger.info(f"Output file - {key}: {path}")
            QMessageBox.information(None, "Success", message)
            
        except Exception as e:
            self.logger.error(f"InSAR processing failed: {str(e)}", exc_info=True)
            QMessageBox.critical(None, "Processing Error", f"InSAR processing failed:\n{str(e)}")
            raise

    def _run_geocoding_processing(self):
        """Run Geocoding processing"""
        self.logger.info("Starting Geocoding processing")
        inputs = self.dlg.get_geocoding_inputs()
        
        if not inputs['processing_start_level']:
            self.logger.warning("Processing Start Level is required")
            QMessageBox.warning(None, "Input Error", "Processing Start Level is required")
            return
        if not inputs['sar_dir']:
            self.logger.warning("SAR Dir is required")
            QMessageBox.warning(None, "Input Error", "SAR Dir is required")
            return
        if not inputs['dem_path']:
            self.logger.warning("DEM Path is required")
            QMessageBox.warning(None, "Input Error", "DEM Path is required")
            return
        if not inputs['output_dir']:
            self.logger.warning("Output Dir is required")
            QMessageBox.warning(None, "Input Error", "Output Dir is required")
            return
        
        try:
            self.logger.info(f"SAR Dir: {inputs['sar_dir']}")
            self.logger.info(f"DEM Path: {inputs['dem_path']}")
            self.logger.info(f"Output Dir: {inputs['output_dir']}")
            self.logger.info(f"Processing Start Level: {inputs['processing_start_level']}")
            os.makedirs(inputs['output_dir'], exist_ok=True)
            output_geometory_json = os.path.join(inputs['output_dir'], "geocoded_geometry.json")
            out_intensity = os.path.join(inputs['output_dir'], "geocoded_intensity.tif")
            out_phase = os.path.join(inputs['output_dir'], "geocoded_phase.tif")
            out_kml = os.path.join(inputs['output_dir'], "geocoded_scene_footprint.kml")
            
            # TODO: POLARIMETORY and ORBIT_NAME should be automatically determined from the files
            # TODO: L1.0 implementation is required
            # only L1.1 is supported now(L1.0 implementation is required in the future)
            if inputs['processing_start_level'] == 'L1.1':
                ceos = CEOS_PALSAR2_L11_SLC(
                    PATH_CEOS_FOLDER=inputs['sar_dir'],
                    POLARIMETORY="HH",
                    ORBIT_NAME="A",
                )
            else:
                QMessageBox.warning(None, "Not Supported", f"Processing Start Level {inputs['processing_start_level']} is not yet supported")
                return
            
            ceos.set_geometory(plot=False, output_json_path=output_geometory_json)
            
            # ---- Prepare SAR data ----
            # Intensity uses np.abs(signal).
            # signal = ceos.signal

            # Optional: provide phase (e.g., interferogram or phase image).
            # If you have a complex interferogram, pass it directly.
            # Here is a placeholder that uses the signal's phase.
            # phase = np.angle(signal).astype(np.float32)
            
            geocoder = Geocode(
                sar=ceos,
                dem_path=inputs['dem_path'],
                buffer_sample=0,
            )
            
            geocoder.save_scene_kml(out_kml, max_iter=2000)
            # geocoder.save_intensity_geotiff_from_bounds(out_intensity_bounds)
            
            signal = ceos.signal
            
            out = geocoder.geocode(
                signal=signal,
                # phase=phase,
                output_intensity_path=out_intensity,
                output_phase_path=out_phase,
                register=True,
            )
            
            self.logger.info("Geocoding processing completed successfully")
            message = "Geocoding processing completed successfully!\n\nOutput files:\n"
            message += f"Intensity: {out_intensity}\n"
            message += f"Phase: {out_phase}\n"
            message += f"KML: {out_kml}\n"
            self.logger.info(f"Output files - Intensity: {out_intensity}, Phase: {out_phase}, KML: {out_kml}")
            QMessageBox.information(None, "Success", message)
            
        except Exception as e:
            self.logger.error(f"Geocoding processing failed: {str(e)}", exc_info=True)
            QMessageBox.critical(None, "Processing Error", f"Geocoding processing failed:\n{str(e)}")
            raise
