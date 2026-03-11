# -*- coding: utf-8 -*
import os
import gc
import sys
import logging
import glob
from datetime import datetime

# qgis
from qgis.core import QgsRasterLayer, QgsProject
from qgis.PyQt.QtCore import QObject, pyqtSignal, QTimer, QThread
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QDialogButtonBox, QApplication

# azayaka qgis-plugin
from .resources import *
from .azayaka_plugin_dialog import AzayakaPluginDialog

# azayaka
try:
    from azayaka.fileformat import CEOS_PALSAR2_L11_SLC, check_ceos_polarization_orbit_exists
    from azayaka.interferometry import Interferometry
    from azayaka.geocode import Geocode
except ImportError as e:
    QMessageBox.warning(None, "Import Error", f"Failed to import azayaka modules: {str(e)}")


class QtLogHandler(QObject, logging.Handler):
    """Custom handler to output logs to QTextEdit"""
    log_signal = pyqtSignal(str)

    def __init__(self, text_widget):
        QObject.__init__(self)
        logging.Handler.__init__(self)
        self.text_widget = text_widget
        self.log_signal.connect(self._append_text)

    def emit(self, record):
        """output the log record to the text area"""
        msg = self.format(record)
        # Check if this is a cancellation message and color it red
        if "Processing cancellation requested" in msg:
            msg = f'<span style="color: red;">{msg}</span>'
        self.log_signal.emit(msg)
        # update the UI
        QApplication.processEvents()

    def _append_text(self, text):
        """append text to the text area (thread-safe)"""
        if self.text_widget:
            self.text_widget.append(text)
            # auto scroll
            scrollbar = self.text_widget.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())


class InterferometryWorker(QThread):
    """Worker class to run InSAR processing in a separate thread"""
    finished = pyqtSignal()
    error = pyqtSignal(str)
    log_message = pyqtSignal(str)
    progress = pyqtSignal(int)
    cancelled = pyqtSignal()

    def __init__(self, inputs, logger):
        super().__init__()
        self.inputs = inputs
        self.logger = logger

    def cancel(self):
        """Cancel the processing"""
        self.requestInterruption()
        self.log_message.emit("Processing cancellation requested. \nWait for a moment to completely stop the process. \nSome processes may not be stopped immediately.")

    def run(self):
        """run InSAR processing"""
        try:
            self.progress.emit(0)
            self.log_message.emit("Starting InSAR processing")
            QApplication.processEvents()

            if not self.inputs['pre_event_dir']:
                self.error.emit("Pre-event Dir is required")
                return
            if not self.inputs['post_event_dir']:
                self.error.emit("Post-event Dir is required")
                return
            if not self.inputs['output_dir']:
                self.error.emit("Output Dir is required")
                return
            if not self.inputs['dem_path']:
                self.error.emit("DEM Path is required")
                return

            polarization = self.inputs.get('polarization', 'HH')
            orbit = self.inputs.get('orbit', 'A')
            self.log_message.emit(f"Polarization: {polarization}")
            self.log_message.emit(f"Orbit: {orbit}")
            self.log_message.emit(f"Pre-event Dir: {self.inputs['pre_event_dir']}")
            QApplication.processEvents()

            # Check if polarization and orbit exist in file names
            try:
                check_ceos_polarization_orbit_exists(
                    self.inputs['pre_event_dir'], polarization, orbit
                )
                check_ceos_polarization_orbit_exists(
                    self.inputs['post_event_dir'], polarization, orbit
                )
            except FileNotFoundError as e:
                err_msg = (
                    f"{str(e)}\n\n"
                    "The specified orbit or polarization does not match any file in the current directory.\n"
                    "Please check the polarization and orbit in the CEOS files."
                )
                self.log_message.emit(str(e))
                self.log_message.emit("The specified orbit or polarization does not match any file in the current directory.")
                self.log_message.emit("Please check the polarization and orbit in the CEOS files.")
                self.error.emit(err_msg)
                return

            self.log_message.emit(f"Post-event Dir: {self.inputs['post_event_dir']}")
            self.log_message.emit(f"Output Dir: {self.inputs['output_dir']}")
            self.log_message.emit(f"DEM Path: {self.inputs['dem_path']}")
            QApplication.processEvents()

            os.makedirs(self.inputs['output_dir'], exist_ok=True)
            path_main_metadata_json = os.path.join(self.inputs['output_dir'], "main_metadata.json")
            path_sub_metadata_json = os.path.join(self.inputs['output_dir'], "sub_metadata.json")

            self.log_message.emit("Loading CEOS files...")
            QApplication.processEvents()

            main_ceos = CEOS_PALSAR2_L11_SLC(
                PATH_CEOS_FOLDER=self.inputs['pre_event_dir'],
                POLARIMETORY=polarization,
                ORBIT_NAME=orbit,
            )
            self.progress.emit(15)
            self.log_message.emit("Setting geometry for main CEOS...")
            QApplication.processEvents()
            if self.isInterruptionRequested():
                self.log_message.emit("Processing cancelled by user")
                self.cancelled.emit()
                return
            main_ceos.set_geometory(plot=False, output_json_path=path_main_metadata_json)

            sub_ceos = CEOS_PALSAR2_L11_SLC(
                PATH_CEOS_FOLDER=self.inputs['post_event_dir'],
                POLARIMETORY=polarization,
                ORBIT_NAME=orbit,
            )
            self.progress.emit(30)
            self.log_message.emit("Setting geometry for sub CEOS...")
            QApplication.processEvents()
            if self.isInterruptionRequested():
                self.log_message.emit("Processing cancelled by user")
                self.cancelled.emit()
                return
            sub_ceos.set_geometory(plot=False, output_json_path=path_sub_metadata_json)

            self.log_message.emit("Initializing Interferometry...")
            QApplication.processEvents()
            interferometry = Interferometry(main_ceos, sub_ceos)
            self.progress.emit(45)

            del main_ceos, sub_ceos
            gc.collect()

            self.log_message.emit("Starting interferometry processing...")
            QApplication.processEvents()
            if self.isInterruptionRequested():
                self.log_message.emit("Processing cancelled by user")
                self.cancelled.emit()
                return
            self.progress.emit(50)

            outputs = interferometry.process(
                output_dir=self.inputs['output_dir'],
                dem_path=self.inputs['dem_path'],
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

            self.log_message.emit("InSAR processing completed successfully")
            QApplication.processEvents()
            self.progress.emit(100)
            message = "InSAR processing completed successfully!\n\nOutput files:\n"
            for key, path in outputs.items():
                message += f"{key}: {path}\n"
                self.log_message.emit(f"Output file - {key}: {path}")
            self.finished.emit()

        except Exception as e:
            import traceback
            error_msg = f"InSAR processing failed: {str(e)}\n{traceback.format_exc()}"
            self.error.emit(error_msg)


class GeocodeWorker(QThread):
    """Worker class to run Geocoding processing in a separate thread"""
    finished = pyqtSignal()
    error = pyqtSignal(str)
    log_message = pyqtSignal(str)
    progress = pyqtSignal(int)
    cancelled = pyqtSignal()

    def __init__(self, inputs, logger):
        super().__init__()
        self.inputs = inputs
        self.logger = logger

    def cancel(self):
        """Cancel the processing"""
        self.requestInterruption()
        self.log_message.emit("Processing cancellation requested. \nWait for a moment to completely stop the process. \nSome processes may not be stopped immediately.")

    def run(self):
        """run Geocoding processing"""
        try:
            self.progress.emit(0)
            self.log_message.emit("Starting Geocoding processing")
            QApplication.processEvents()

            if not self.inputs['processing_start_level']:
                self.error.emit("Processing Start Level is required")
                return
            if not self.inputs['sar_dir']:
                self.error.emit("SAR Dir is required")
                return
            if not self.inputs['dem_path']:
                self.error.emit("DEM Path is required")
                return
            if not self.inputs['output_dir']:
                self.error.emit("Output Dir is required")
                return

            polarization = self.inputs.get('polarization', 'HH')
            orbit = self.inputs.get('orbit', 'A')
            self.log_message.emit(f"Polarization: {polarization}")
            self.log_message.emit(f"Orbit: {orbit}")
            self.log_message.emit(f"SAR Dir: {self.inputs['sar_dir']}")
            self.log_message.emit(f"DEM Path: {self.inputs['dem_path']}")
            self.log_message.emit(f"Output Dir: {self.inputs['output_dir']}")
            self.log_message.emit(f"Processing Start Level: {self.inputs['processing_start_level']}")
            QApplication.processEvents()

            # Check if polarization and orbit exist in file names
            try:
                check_ceos_polarization_orbit_exists(
                    self.inputs['sar_dir'], polarization, orbit
                )
            except FileNotFoundError as e:
                self.error.emit(str(e))
                return

            os.makedirs(self.inputs['output_dir'], exist_ok=True)
            output_geometory_json = os.path.join(self.inputs['output_dir'], "geocoded_geometry.json")
            out_intensity = os.path.join(self.inputs['output_dir'], "geocoded_intensity.tif")
            out_phase = os.path.join(self.inputs['output_dir'], "geocoded_phase.tif")
            out_kml = os.path.join(self.inputs['output_dir'], "geocoded_scene_footprint.kml")

            # only L1.1 is supported now(L1.0 implementation is required in the future)
            if self.inputs['processing_start_level'] == 'L1.1':
                self.log_message.emit("Loading CEOS file...")
                ceos = CEOS_PALSAR2_L11_SLC(
                    PATH_CEOS_FOLDER=self.inputs['sar_dir'],
                    POLARIMETORY=polarization,
                    ORBIT_NAME=orbit,
                )
                self.progress.emit(20)
            else:
                self.error.emit(f"Processing Start Level {self.inputs['processing_start_level']} is not yet supported")
                return

            self.log_message.emit("Setting geometry...")
            ceos.set_geometory(plot=False, output_json_path=output_geometory_json)
            if self.isInterruptionRequested():
                self.log_message.emit("Processing cancelled by user")
                self.cancelled.emit()
                return
            self.progress.emit(40)

            self.log_message.emit("Initializing Geocoder...")
            geocoder = Geocode(
                sar=ceos,
                dem_path=self.inputs['dem_path'],
                buffer_sample=0,
            )
            self.progress.emit(50)

            self.log_message.emit("Saving scene KML...")
            geocoder.save_scene_kml(out_kml, max_iter=2000)
            self.progress.emit(60)

            signal = ceos.signal

            self.log_message.emit("Starting geocoding (this may take a while)...")
            if self.isInterruptionRequested():
                self.log_message.emit("Processing cancelled by user")
                self.cancelled.emit()
                return
            self.progress.emit(65)

            out = geocoder.geocode(
                signal=signal,
                # phase=phase,
                output_intensity_path=out_intensity,
                output_phase_path=out_phase,
                register=True,
            )

            self.log_message.emit("Geocoding processing completed successfully!")
            self.log_message.emit(f"Output files - Intensity: {out_intensity}, Phase: {out_phase}, KML: {out_kml}")
            self.progress.emit(100)
            self.finished.emit()

        except Exception as e:
            import traceback
            error_msg = f"Geocoding processing failed: {str(e)}\n{traceback.format_exc()}"
            self.error.emit(error_msg)


class AzayakaPlugin:
    """QGIS Plugin Implementation."""
    
    # Maximum number of log files to keep
    MAX_LOG_FILES = 10

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

    def _add_output_tifs_to_qgis(self, output_dir):
        """Add all .tif files in the output directory to QGIS as raster layers"""
        try:
            if not output_dir:
                self.logger.warning("Output directory is not specified. Skipping adding layers to QGIS.")
                return

            if not os.path.isdir(output_dir):
                self.logger.warning(f"Output directory does not exist: {output_dir}")
                return

            tif_paths = glob.glob(os.path.join(output_dir, "*.tif"))

            if not tif_paths:
                self.logger.info(f"No .tif files found in output directory: {output_dir}")
                return

            project = QgsProject.instance()

            for tif_path in tif_paths:
                layer_name = os.path.basename(tif_path)
                raster_layer = QgsRasterLayer(tif_path, layer_name)

                if not raster_layer.isValid():
                    self.logger.warning(f"Failed to load raster layer: {tif_path}")
                    continue

                project.addMapLayer(raster_layer)
                self.logger.info(f"Added raster layer to QGIS: {tif_path}")

        except Exception as e:
            import traceback
            self.logger.error(f"Failed to add output .tif files to QGIS: {str(e)}\n{traceback.format_exc()}")
    
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
    
    def _cleanup_old_logs(self, log_dir):
        """Remove old log files if the number exceeds MAX_LOG_FILES
        
        :param log_dir: Directory containing log files
        :type log_dir: str
        """
        # Get all log files matching the pattern
        log_pattern = f"{log_dir}/azayaka_plugin_*.log"
        log_files = glob.glob(log_pattern)
        
        # If the number of log files exceeds MAX_LOG_FILES, remove the oldest ones
        if len(log_files) > self.MAX_LOG_FILES:
            # Sort by modification time (oldest first)
            log_files.sort(key=lambda x: os.path.getmtime(x))
            
            # Calculate how many files to delete
            files_to_delete = len(log_files) - self.MAX_LOG_FILES
            
            # Delete the oldest files
            for i in range(files_to_delete):
                try:
                    os.remove(log_files[i])
                except OSError as e:
                    # Log error if file deletion fails, but continue with other files
                    print(f"Failed to delete log file {log_files[i]}: {e}")
    
    def _setup_logger(self, dialog=None):
        """Setup logger with file handler and optional dialog handler"""
        logger = logging.getLogger('AzayakaPlugin')
        logger.setLevel(logging.INFO)
        
        # Remove existing handlers to avoid duplicates other than QtLogHandler
        existing_handlers = [h for h in logger.handlers if isinstance(h, QtLogHandler)]
        
        # Clear existing handlers
        logger.handlers.clear()
        
        # Create log directory if it doesn't exist
        plugin_dir = os.path.dirname(__file__)
        log_dir = os.path.join(plugin_dir, 'log')
        os.makedirs(log_dir, exist_ok=True)
        
        # Clean up old log files before creating a new one
        self._cleanup_old_logs(log_dir)
        
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
        
        # Dialog handler (if dialog is provided)
        if dialog and hasattr(dialog, 'plainTextEdit'):
            # Remove existing QtLogHandler instances to eliminate references to old dialogs
            for handler in existing_handlers:
                logger.removeHandler(handler)
            dialog_handler = QtLogHandler(dialog.plainTextEdit)
            dialog_handler.setLevel(logging.INFO)
            dialog_handler.setFormatter(formatter)
            logger.addHandler(dialog_handler)
        
        if not dialog:
            logger.info(f"Logger initialized. Log file: {log_file}")
        
        return logger
    
    def _add_dialog_handler(self, dialog):
        """add the dialog handler to the existing logger"""
        logger = logging.getLogger('AzayakaPlugin')
        
        # remove the existing QtLogHandler
        existing_handlers = [h for h in logger.handlers if isinstance(h, QtLogHandler)]
        for handler in existing_handlers:
            logger.removeHandler(handler)
        
        # add the new dialog handler
        if dialog and hasattr(dialog, 'plainTextEdit'):
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            dialog_handler = QtLogHandler(dialog.plainTextEdit)
            dialog_handler.setLevel(logging.INFO)
            dialog_handler.setFormatter(formatter)
            logger.addHandler(dialog_handler)

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
        if self.first_start == True:
            self.first_start = False
            self.dlg = AzayakaPluginDialog()
            # add the handler to output logs to the text area of the dialog
            self._add_dialog_handler(self.dlg)
            self.logger.info("Dialog created")
            # connect the signal of the OK button (overwrite the connection in the UI file)
            # disconnect all connections
            try:
                self.dlg.button_box.accepted.disconnect()
            except:
                pass
            self.dlg.button_box.accepted.connect(self._on_ok_clicked)
            # connect the signal of the rejected button
            try:
                self.dlg.button_box.rejected.disconnect()
            except:
                pass
            self.dlg.button_box.rejected.connect(self.dlg.reject)
        else:
            # update the dialog handler again
            self._add_dialog_handler(self.dlg)

        # clear the text area of the log-tab
        self.dlg.clear_log()
        # show the dialog (modal)
        self.dlg.exec_()

    def _on_ok_clicked(self):
        """Handler for OK button press
        switch to the log-tab and begin processing (the dialog remains open)
        """
        # get the index of the currently selected tab before switching to the log-tab
        current_tab = self.dlg.get_current_tab_index()
        # switch to the log-tab
        log_tab_index = 2
        self.dlg.tabWidget.setCurrentIndex(log_tab_index)
        # update the UI immediately
        QApplication.processEvents()
        # set the processing flag
        self.dlg._processing = True
        # disable the OK button (the button is disabled during processing)
        self.dlg.button_box.button(QDialogButtonBox.Ok).setEnabled(False)
        # disable the Cancel button (the button is disabled during processing)
        self.dlg.button_box.button(QDialogButtonBox.Cancel).setEnabled(False)
        # disable the Close button during processing
        self.dlg.closeButton.setEnabled(False)
        # update the UI
        QApplication.processEvents()
        # show the test message
        self.logger.info("=" * 50)
        self.logger.info("Processing started")
        self.logger.info(f"Current tab index: {current_tab}")
        # reset progress bar
        self.dlg.progressBar.setValue(0)
        QApplication.processEvents()
        # execute the processing asynchronously using QTimer (the UI is not blocked)
        QTimer.singleShot(100, lambda: self._start_processing(current_tab))

    def _start_processing(self, current_tab):
        """start the processing (called from QTimer)"""
        try:
            if current_tab == 0: # InSAR tab
                self._run_insar_processing_async()
            elif current_tab == 1: # Geocoding tab
                self._run_geocoding_processing_async()
            else:
                self.logger.warning(f"Unknown tab index: {current_tab}")
                QMessageBox.warning(self.dlg, "Error", "Unknown tab was found")
        except Exception as e:
            self.logger.error(f"Error occurred during processing: {str(e)}", exc_info=True)
            QMessageBox.critical(self.dlg, "Processing Error", f"An error occurred during processing:\n{str(e)}")
            QApplication.processEvents()
    
    def _run_insar_processing_async(self):
        """Run InSAR processing in a separate thread"""
        inputs = self.dlg.get_insar_inputs()

        # input check
        if not inputs['pre_event_dir']:
            self.logger.warning("Pre-event Dir is required")
            QMessageBox.warning(self.dlg, "Input Error", "Pre-event Dir is required")
            self.dlg.processing_completed()
            return
        if not inputs['post_event_dir']:
            self.logger.warning("Post-event Dir is required")
            QMessageBox.warning(self.dlg, "Input Error", "Post-event Dir is required")
            self.dlg.processing_completed()
            return
        if not inputs['output_dir']:
            self.logger.warning("Output Dir is required")
            QMessageBox.warning(self.dlg, "Input Error", "Output Dir is required")
            self.dlg.processing_completed()
            return
        if not inputs['dem_path']:
            self.logger.warning("DEM Path is required")
            QMessageBox.warning(self.dlg, "Input Error", "DEM Path is required")
            self.dlg.processing_completed()
            return

        # create the worker thread
        self.insar_worker = InterferometryWorker(inputs, self.logger)

        # connect the signals
        self.insar_worker.log_message.connect(lambda msg: self.logger.info(msg))
        self.insar_worker.progress.connect(self.dlg.progressBar.setValue)
        self.insar_worker.finished.connect(self._on_insar_finished)
        self.insar_worker.error.connect(self._on_insar_error)
        self.insar_worker.cancelled.connect(self._on_insar_cancelled)

        # setup cancel functionality
        self.dlg.cancelButton.setEnabled(True)
        self.dlg.cancelButton.setText("Stop")
        self.dlg._cancel_callback = self.insar_worker.cancel

        # start the worker thread
        self.insar_worker.start()

    def _on_insar_finished(self):
        """Handler for InSAR processing completed"""
        self.dlg.progressBar.setValue(100)
        self.dlg.cancelButton.setEnabled(False)
        self.dlg.cancelButton.setText("Stop")
        self.dlg.processing_completed()
        self.logger.info("Processing completed!")
        try:
            # get latest InSAR inputs to determine output directory
            inputs = self.dlg.get_insar_inputs()
            output_dir = inputs.get("output_dir")
        except Exception:
            output_dir = None

        # Add all .tif files in the output directory to QGIS
        self._add_output_tifs_to_qgis(output_dir)

        QMessageBox.information(
            self.dlg,
            "Success",
            "InSAR processing completed successfully!\n\n"
            "All output .tif files have been added to QGIS as raster layers (if available).",
        )
        QApplication.processEvents()

    def _on_insar_error(self, error_msg):
        """Handler for InSAR processing error"""
        self.logger.error(error_msg)
        self.dlg.cancelButton.setEnabled(False)
        self.dlg.processing_completed()
        QMessageBox.critical(self.dlg, "Processing Error", f"InSAR processing failed:\n{error_msg}")
        QApplication.processEvents()

    def _on_insar_cancelled(self):
        """Handler for InSAR processing cancelled"""
        self.dlg.progressBar.setValue(0)
        self.dlg.cancelButton.setEnabled(False)
        self.dlg.cancelButton.setText("The process stopped")
        self.dlg.clear_log()
        self.dlg.processing_completed()
        self.logger.info("Processing cancelled by user")
        # Wait for thread to finish
        if hasattr(self, 'insar_worker') and self.insar_worker.isRunning():
            self.insar_worker.wait()
        QApplication.processEvents()

    def _run_geocoding_processing_async(self):
        """Run Geocoding processing in a separate thread"""
        inputs = self.dlg.get_geocoding_inputs()
        
        # input check
        if not inputs['processing_start_level']:
            self.logger.warning("Processing Start Level is required")
            QMessageBox.warning(self.dlg, "Input Error", "Processing Start Level is required")
            self.dlg.processing_completed()
            return
        if not inputs['sar_dir']:
            self.logger.warning("SAR Dir is required")
            QMessageBox.warning(self.dlg, "Input Error", "SAR Dir is required")
            self.dlg.processing_completed()
            return
        if not inputs['dem_path']:
            self.logger.warning("DEM Path is required")
            QMessageBox.warning(self.dlg, "Input Error", "DEM Path is required")
            self.dlg.processing_completed()
            return
        if not inputs['output_dir']:
            self.logger.warning("Output Dir is required")
            QMessageBox.warning(self.dlg, "Input Error", "Output Dir is required")
            self.dlg.processing_completed()
            return
        
        # create the worker thread
        self.geocode_worker = GeocodeWorker(inputs, self.logger)

        # connect the signals
        self.geocode_worker.log_message.connect(lambda msg: self.logger.info(msg))
        self.geocode_worker.progress.connect(self.dlg.progressBar.setValue)
        self.geocode_worker.finished.connect(self._on_geocoding_finished)
        self.geocode_worker.error.connect(self._on_geocoding_error)
        self.geocode_worker.cancelled.connect(self._on_geocoding_cancelled)

        # setup cancel functionality
        self.dlg.cancelButton.setEnabled(True)
        self.dlg.cancelButton.setText("Stop")
        self.dlg._cancel_callback = self.geocode_worker.cancel
        
        # start the worker thread
        self.geocode_worker.start()
    
    def _on_geocoding_finished(self):
        """Handler for Geocoding processing completed"""
        self.dlg.progressBar.setValue(100)
        self.dlg.cancelButton.setEnabled(False)
        self.dlg.cancelButton.setText("Stop")
        self.dlg.processing_completed()
        self.logger.info("Processing completed!")
        try:
            # get latest Geocoding inputs to determine output directory
            inputs = self.dlg.get_geocoding_inputs()
            output_dir = inputs.get("output_dir")
        except Exception:
            output_dir = None

        # Add all .tif files in the output directory to QGIS
        self._add_output_tifs_to_qgis(output_dir)

        QMessageBox.information(
            self.dlg,
            "Success",
            "Geocoding processing completed successfully!\n\n"
            "All output .tif files have been added to QGIS as raster layers (if available).",
        )
        QApplication.processEvents()
    
    def _on_geocoding_error(self, error_msg):
        """Handler for Geocoding processing error"""
        self.logger.error(error_msg)
        self.dlg.cancelButton.setEnabled(False)
        self.dlg.processing_completed()
        QMessageBox.critical(self.dlg, "Processing Error", f"Geocoding processing failed:\n{error_msg}")
        QApplication.processEvents()

    def _on_geocoding_cancelled(self):
        """Handler for Geocoding processing cancelled"""
        self.dlg.progressBar.setValue(0)
        self.dlg.cancelButton.setEnabled(False)
        self.dlg.cancelButton.setText("Stop")
        self.dlg.clear_log()
        self.dlg.processing_completed()
        self.logger.info("Processing cancelled by user")
        # Wait for thread to finish
        if hasattr(self, 'geocode_worker') and self.geocode_worker.isRunning():
            self.geocode_worker.wait()
        QApplication.processEvents()
