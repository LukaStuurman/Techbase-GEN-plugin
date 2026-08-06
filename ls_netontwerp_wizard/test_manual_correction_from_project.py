"""Exercise the isolated manual-correction worker on the latest test project."""

from datetime import datetime
from pathlib import Path
import sys

from qgis.core import (
    QgsApplication,
    QgsCategorizedSymbolRenderer,
    QgsLayoutExporter,
    QgsLayoutItemAttributeTable,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProject,
)


class ConsoleFeedback(QgsProcessingFeedback):
    def pushInfo(self, message):
        print(datetime.now().strftime("%H:%M:%S"), message, flush=True)

    def pushWarning(self, message):
        print(datetime.now().strftime("%H:%M:%S"), "WAARSCHUWING:", message, flush=True)

    def setProgress(self, progress):
        super().setProgress(progress)
        print(datetime.now().strftime("%H:%M:%S"), f"VOORTGANG {progress:.0f}%", flush=True)


def layer_by_name(name):
    layers = QgsProject.instance().mapLayersByName(name)
    if not layers:
        raise RuntimeError(f"Testlaag ontbreekt: {name}")
    return layers[0]


def main():
    plugin_dir = Path(__file__).resolve().parent
    project_path = (
        Path(sys.argv[1]).resolve()
        if len(sys.argv) > 1
        else plugin_dir.parent
        / "plugin_test_output"
        / "LS_netontwerp_resultaat_20260731_070834"
        / "05_clustering"
        / "clustering_ontwerp.qgz"
    )
    sys.path.insert(0, str(plugin_dir.parent))
    app = QgsApplication([], False)
    app.initQgis()
    try:
        if not QgsProject.instance().read(str(project_path)):
            raise RuntimeError(f"Testproject kon niet worden geopend: {project_path}")
        connections = layer_by_name("Aansluitingen geclusterd")
        stations = layer_by_name("Stations ontwerp")
        areas = layer_by_name("Clustergebieden")
        routes = layer_by_name("Kabelroutes per cluster")
        cables = layer_by_name("Sleuven geknipt/genood")
        plan = layer_by_name("Plangebied")

        station_features = list(stations.getFeatures())
        connection_features = list(connections.getFeatures())
        source_cluster = "N-10"
        source_candidates = [
            feature
            for feature in connection_features
            if str(feature["Cluster"]) == source_cluster
        ]
        if not source_candidates:
            counts = {}
            for feature in connection_features:
                cluster = str(feature["Cluster"])
                counts[cluster] = counts.get(cluster, 0) + 1
            source_cluster = min(counts, key=lambda cluster: (counts[cluster], cluster))
            source_candidates = [
                feature
                for feature in connection_features
                if str(feature["Cluster"]) == source_cluster
            ]
        target_station = next(
            (
                feature
                for feature in station_features
                if str(feature["Cluster"]) == "079.1010"
                and str(feature["Cluster"]) != source_cluster
            ),
            next(
                feature
                for feature in station_features
                if str(feature["Cluster"]) != source_cluster
            ),
        )
        best = (0.0, source_candidates[0].id(), target_station.id())
        if best is None:
            raise RuntimeError("Geen testverplaatsing gevonden")
        station_count_before = stations.featureCount()
        connections.selectByIds([best[1]])
        stations.selectByIds([best[2]])

        from ls_netontwerp_wizard.algorithms.handmatige_cluster_correctie_tool import (
            HandmatigeClusterCorrectieAlgorithm,
        )

        algorithm = HandmatigeClusterCorrectieAlgorithm()
        algorithm.initAlgorithm()
        output_dir = project_path.parent / "manual_test_output"
        result = algorithm.processAlgorithm(
            {
                algorithm.AANSLUITINGEN: connections,
                algorithm.STATIONS: stations,
                algorithm.GEBIEDEN: areas,
                algorithm.KABELROUTES: routes,
                algorithm.SLEUVEN: cables,
                algorithm.PLANGEBIED: plan,
                algorithm.HELE_BRONCLUSTER_VERWIJDEREN: True,
                algorithm.ALLES_TOESTAAN: True,
                algorithm.CONTROLE_MAX_ONTWERPSTROOM: True,
                algorithm.CONTROLE_MAX_KABELLENGTE: True,
                algorithm.CONTROLE_ROUTES_ANDERE_CLUSTERS: True,
                algorithm.CONTROLE_GEDEELDE_ROUTES_VERTAKKINGEN: True,
                algorithm.MAX_ROUTE_M: 10000.0,
                algorithm.KNOOP_TOLERANTIE_M: 0.0,
                algorithm.BACKUPMAP: str(output_dir),
            },
            QgsProcessingContext(),
            ConsoleFeedback(),
        )
        remaining_clusters = {str(feature["Cluster"]) for feature in stations.getFeatures()}
        assert source_cluster not in remaining_clusters
        assert stations.featureCount() == station_count_before - 1
        assert result[algorithm.VERPLAATST_AANTAL] >= 1
        for numbered_layer in (stations, areas, routes):
            assert numbered_layer.fields().lookupField("Volgnummer") >= 0
            numbers = sorted(
                int(feature["Volgnummer"])
                for feature in numbered_layer.getFeatures()
            )
            assert numbers == list(range(1, len(numbers) + 1))

        for styled_layer in (connections, areas, routes):
            renderer = styled_layer.renderer()
            if isinstance(renderer, QgsCategorizedSymbolRenderer):
                values = {str(category.value()) for category in renderer.categories()}
                assert source_cluster not in values

        assert not [
            layer
            for layer in QgsProject.instance().mapLayers().values()
            if bool(layer.customProperty("LSNetontwerp/layout_helper", False))
        ]
        layout = QgsProject.instance().layoutManager().layoutByName("Clustering overzicht")
        assert layout is not None
        tables = [
            frame
            for frame in layout.multiFrames()
            if isinstance(frame, QgsLayoutItemAttributeTable)
        ]
        assert len(tables) == 1
        assert tables[0].vectorLayer().id() == stations.id()
        assert tables[0].columns()[0].attribute() == '"Volgnummer"'
        preview_path = project_path.parent / "layout_after_manual.png"
        settings = QgsLayoutExporter.ImageExportSettings()
        settings.dpi = 150
        export_result = QgsLayoutExporter(layout).exportToImage(
            str(preview_path), settings
        )
        assert export_result == QgsLayoutExporter.Success
        assert preview_path.is_file()
        print("MANUAL_CORRECTION_TEST_OK", result, flush=True)
    finally:
        app.exitQgis()


if __name__ == "__main__":
    main()
