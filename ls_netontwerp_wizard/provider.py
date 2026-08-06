from pathlib import Path

from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsProcessingProvider

from .algorithms.handmatige_cluster_correctie_tool import (
    HandmatigeClusterCorrectieAlgorithm,
)
from .algorithms.hoogste_waarden_selectie_tool import (
    HoogsteWaardenSelectieAlgorithm,
)
from .algorithms.stations_selectie_tool import StationsSelectieAlgorithm
from .algorithms.sleuf_route_tool import SleufRouteToevoegenAlgorithm
from .algorithms.clustergebieden_vereenvoudigen_tool import (
    ClustergebiedenVereenvoudigenAlgorithm,
)
from .algorithms.woningtype_selectie_herberekenen_tool import (
    WoningtypeSelectieHerberekenenAlgorithm,
)


class LSNetontwerpProvider(QgsProcessingProvider):
    def icon(self):
        return QIcon(
            str(Path(__file__).resolve().parent / "assets" / "techbase-logo.png")
        )

    def id(self):
        return "lsnetontwerp"

    def name(self):
        return "LS Netontwerp"

    def longName(self):
        return "LS Netontwerp Wizard"

    def loadAlgorithms(self):
        self.addAlgorithm(HoogsteWaardenSelectieAlgorithm())
        self.addAlgorithm(StationsSelectieAlgorithm())
        self.addAlgorithm(WoningtypeSelectieHerberekenenAlgorithm())
        self.addAlgorithm(HandmatigeClusterCorrectieAlgorithm())
        self.addAlgorithm(SleufRouteToevoegenAlgorithm())
        self.addAlgorithm(ClustergebiedenVereenvoudigenAlgorithm())
