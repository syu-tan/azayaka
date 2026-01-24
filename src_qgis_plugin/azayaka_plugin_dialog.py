# -*- coding: utf-8 -*-
import os

from qgis.PyQt import uic
from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QApplication


FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'azayaka_plugin_dialog_base.ui'))


class AzayakaPluginDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        """Constructor."""
        super(AzayakaPluginDialog, self).__init__(parent)
        self.setupUi(self)
        self._processing = False
        # Initialize the text area in the log tab
        self.plainTextEdit.clear()

    def accept(self):
        """Handler for OK button press
        show the log-tab and begin processing (the dialog remains open)
        """
        # get the index of the log-tab (logTab is the third tab, index=2)
        log_tab_index = 2
        self.tabWidget.setCurrentIndex(log_tab_index)
        # update the UI immediately
        QApplication.processEvents()
        # set the processing flag
        self._processing = True
        # disable the OK button (the button is disabled during processing)
        self.button_box.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
        # disable the Cancel button (the button is disabled during processing)
        self.button_box.button(QtWidgets.QDialogButtonBox.Cancel).setEnabled(False)
        # update the UI
        QApplication.processEvents()

    def clear_log(self):
        """clear the text area of the log-tab"""
        self.plainTextEdit.clear()

    def processing_completed(self):
        """processing completed: re-enable the buttons"""
        self._processing = False
        # re-enable the OK button (the button is enabled after processing)
        self.button_box.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(True)
        # re-enable the Cancel button (the button is enabled after processing)
        self.button_box.button(QtWidgets.QDialogButtonBox.Cancel).setEnabled(True)
        # change the text of the OK button (the text is changed after processing)
        # self.button_box.button(QtWidgets.QDialogButtonBox.Ok).setText("閉じる")

    def get_insar_inputs(self):
        """get the input values of the InSAR-tab"""
        dem_path = self.PreEventDir_2.filePath() if self.PreEventDir_2.filePath() else None
        pre_event_dir = self.PreEventDir.filePath() if self.PreEventDir.filePath() else None
        post_event_dir = self.PostEventDir.filePath() if self.PostEventDir.filePath() else None
        output_dir = self.OutputDir.filePath() if self.OutputDir.filePath() else None
        return {
            'dem_path': dem_path,
            'pre_event_dir': pre_event_dir,
            'post_event_dir': post_event_dir,
            'output_dir': output_dir,
        }

    def get_geocoding_inputs(self):
        """get the input values of the Geocoding-tab"""
        processing_start_level = self.ProcessingStartLevel.currentText()
        dem_path = self.DEMPath.filePath() if self.DEMPath.filePath() else None
        sar_dir = self.SARDir.filePath() if self.SARDir.filePath() else None
        output_dir = self.OutputDir_2.filePath() if self.OutputDir_2.filePath() else None
        return {
            'processing_start_level': processing_start_level,
            'sar_dir': sar_dir,
            'dem_path': dem_path,
            'output_dir': output_dir,
        }

    def get_current_tab_index(self):
        """get the index of the currently selected tab"""
        return self.tabWidget.currentIndex()
