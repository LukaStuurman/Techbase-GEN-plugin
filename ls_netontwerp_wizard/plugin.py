from pathlib import Path

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsApplication

from .dialog import LSNetontwerpDialog
from .provider import LSNetontwerpProvider


ICON_PATH = Path(__file__).resolve().parent / "assets" / "techbase-logo.png"


class LSNetontwerpPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.value_action = None
        self.housing_action = None
        self.station_action = None
        self.manual_action = None
        self.cluster_editor_action = None
        self.provider = None
        self.dialog = None
        self.cluster_editor_dialog = None

    def initProcessing(self):
        if self.provider is None:
            self.provider = LSNetontwerpProvider()
            QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):
        self.initProcessing()
        icon = QIcon(str(ICON_PATH))
        self.action = QAction(icon, "LS-netontwerp wizard", self.iface.mainWindow())
        self.action.setObjectName("lsNetontwerpWizardAction")
        self.action.setToolTip("XML + Excel naar ontwerpstroom en kabelclusters")
        self.action.triggered.connect(self.open_dialog)
        self.iface.addPluginToVectorMenu("LS Netontwerp", self.action)
        self.iface.addToolBarIcon(self.action)
        self.value_action = QAction(
            icon,
            "Hoogste trafo/kabel aanpassen (selectie)",
            self.iface.mainWindow(),
        )
        self.value_action.setObjectName("lsNetontwerpHighestValuesAction")
        self.value_action.setToolTip(
            "Hoogste Trafo en Hoogste Kabel voor geselecteerde aansluitingen aanpassen"
        )
        self.value_action.triggered.connect(self.open_value_tool)
        self.iface.addPluginToVectorMenu("LS Netontwerp", self.value_action)
        self.iface.addToolBarIcon(self.value_action)

        self.housing_action = QAction(
            icon,
            "Woningtype aanpassen en ontwerpstroom herberekenen (selectie)",
            self.iface.mainWindow(),
        )
        self.housing_action.setObjectName("lsNetontwerpHousingTypeAction")
        self.housing_action.setToolTip(
            "Wijzig geselecteerde BAG-woningen en bereken bijbehorende aansluitingen opnieuw"
        )
        self.housing_action.triggered.connect(self.open_housing_tool)
        self.iface.addPluginToVectorMenu("LS Netontwerp", self.housing_action)
        self.iface.addToolBarIcon(self.housing_action)

        self.station_action = QAction(
            icon,
            "Bestaande stations aanpassen/verwijderen (selectie)",
            self.iface.mainWindow(),
        )
        self.station_action.setObjectName("lsNetontwerpStationEditAction")
        self.station_action.setToolTip(
            "Wijzig de trafocapaciteit of verwijder geselecteerde bestaande stations"
        )
        self.station_action.triggered.connect(self.open_station_tool)
        self.iface.addPluginToVectorMenu("LS Netontwerp", self.station_action)
        self.iface.addToolBarIcon(self.station_action)

        self.manual_action = QAction(
            icon,
            "Handmatige clustercorrectie (selectie naar station)",
            self.iface.mainWindow(),
        )
        self.manual_action.setObjectName("lsNetontwerpManualClusterAction")
        self.manual_action.setToolTip(
            "Geselecteerde aansluitingen naar een ander station verplaatsen"
        )
        self.manual_action.triggered.connect(self.open_manual_tool)
        self.iface.addPluginToVectorMenu("LS Netontwerp", self.manual_action)

        self.cluster_editor_action = QAction(
            icon,
            "Visuele clustereditor (lasso naar station)",
            self.iface.mainWindow(),
        )
        self.cluster_editor_action.setObjectName("lsNetontwerpVisualClusterEditorAction")
        self.cluster_editor_action.setToolTip(
            "Teken rond aansluitingen, kies een doelstation en herbereken het cluster veilig"
        )
        self.cluster_editor_action.triggered.connect(self.open_cluster_editor)
        self.iface.addPluginToVectorMenu("LS Netontwerp", self.cluster_editor_action)
        self.iface.addToolBarIcon(self.cluster_editor_action)

    def unload(self):
        if self.action is not None:
            self.iface.removePluginVectorMenu("LS Netontwerp", self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
        for action in (
            self.value_action,
            self.housing_action,
            self.station_action,
            self.manual_action,
            self.cluster_editor_action,
        ):
            if action is not None:
                self.iface.removePluginVectorMenu("LS Netontwerp", action)
                self.iface.removeToolBarIcon(action)
                action.deleteLater()
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
        self.action = None
        self.value_action = None
        self.housing_action = None
        self.station_action = None
        self.manual_action = None
        self.cluster_editor_action = None
        self.provider = None
        self.dialog = None
        self.cluster_editor_dialog = None

    def open_dialog(self):
        if self.dialog is None:
            self.dialog = LSNetontwerpDialog(self.iface, self.iface.mainWindow())
        self.dialog.show_home_page()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def open_value_tool(self):
        if self.dialog is None:
            self.dialog = LSNetontwerpDialog(self.iface, self.iface.mainWindow())
        self.dialog.show_value_page()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def open_housing_tool(self):
        if self.dialog is None:
            self.dialog = LSNetontwerpDialog(self.iface, self.iface.mainWindow())
        self.dialog.show_housing_page()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def open_station_tool(self):
        if self.dialog is None:
            self.dialog = LSNetontwerpDialog(self.iface, self.iface.mainWindow())
        self.dialog.show_station_page()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def open_manual_tool(self):
        if self.dialog is None:
            self.dialog = LSNetontwerpDialog(self.iface, self.iface.mainWindow())
        self.dialog.show_manual_page(False)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def open_cluster_editor(self):
        from .cluster_paint_dialog import VisueleClusterEditorDialog

        if self.cluster_editor_dialog is None:
            self.cluster_editor_dialog = VisueleClusterEditorDialog(
                self.iface, self.iface.mainWindow()
            )
        self.cluster_editor_dialog.refresh_layers()
        self.cluster_editor_dialog.show()
        self.cluster_editor_dialog.raise_()
        self.cluster_editor_dialog.activateWindow()
