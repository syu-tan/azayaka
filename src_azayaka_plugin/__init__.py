# -*- coding: utf-8 -*-

# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load AzayakaPlugin class from file AzayakaPlugin.

    :param iface: A QGIS interface instance.
    :type iface: QgsInterface
    """
    #
    from .azayaka_plugin import AzayakaPlugin
    return AzayakaPlugin(iface)
