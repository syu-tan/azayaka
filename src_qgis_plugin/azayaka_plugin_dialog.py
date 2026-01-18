# -*- coding: utf-8 -*-
import os

from qgis.PyQt import uic
from qgis.PyQt import QtWidgets


FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'azayaka_plugin_dialog_base.ui'))


class AzayakaPluginDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        """Constructor."""
        super(AzayakaPluginDialog, self).__init__(parent)
        self.setupUi(self)

    def get_insar_inputs(self):
        """InSARタブの入力値を取得"""
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
        """Geocodingタブの入力値を取得"""
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
        """現在選択されているタブのインデックスを取得"""
        return self.tabWidget.currentIndex()
