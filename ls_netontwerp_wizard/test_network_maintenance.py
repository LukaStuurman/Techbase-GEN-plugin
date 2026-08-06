"""Integration test for trench noding and fixed-assignment route refresh."""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np

from qgis.core import (
    QgsApplication,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProject,
    QgsVectorLayer,
)


class Feedback(QgsProcessingFeedback):
    def pushInfo(self, message):
        print(message, flush=True)

    def pushWarning(self, message):
        print("WAARSCHUWING:", message, flush=True)


def one(name):
    matches = QgsProject.instance().mapLayersByName(name)
    assert len(matches) == 1, (name, len(matches))
    return matches[0]


def main():
    project_path = Path(sys.argv[1]).resolve()
    plugin_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(plugin_dir.parent))
    app = QgsApplication([], False)
    app.initQgis()
    try:
        library = plugin_dir / "algorithms" / "laagspanning_clustering_lib"
        sys.path.insert(0, str(library))
        import maak_clustering_engine as engine
        import network_noding

        existing = engine.gpd.GeoDataFrame(
            {"Rekenfactor": [1.0, 1.0, 1.0]},
            geometry=[
                engine.LineString([(0.0, 0.0), (5.0, 0.0)]),
                engine.LineString([(5.0, 0.0), (10.0, 0.0)]),
                engine.LineString([(0.0, 10.0), (10.0, 10.0)]),
            ],
            crs=engine.CRS_RD,
        )
        new_trench = engine.gpd.GeoDataFrame(
            geometry=[engine.LineString([(5.0, -5.0), (5.0, 5.0)])],
            crs=engine.CRS_RD,
        )
        no_terminals = engine.gpd.GeoDataFrame(
            geometry=[], crs=engine.CRS_RD
        )
        fast_noded, affected_count, used_local = (
            network_noding.incremental_node_cable_network(
                existing,
                new_trench,
                no_terminals,
                no_terminals,
                1.0,
                full_rebuild_fraction=0.9,
            )
        )
        full_input = engine.gpd.GeoDataFrame(
            {"Rekenfactor": [1.0, 1.0, 1.0, 1.0]},
            geometry=[*existing.geometry.tolist(), *new_trench.geometry.tolist()],
            crs=engine.CRS_RD,
        )
        full_noded = engine.node_cable_network(
            full_input, no_terminals, no_terminals, 1.0
        )
        assert used_local and affected_count == 2
        assert engine.unary_union(fast_noded.geometry).symmetric_difference(
            engine.unary_union(full_noded.geometry)
        ).length < 1e-8

        graph = engine.nx.Graph()
        for first, second in (
            ((0.0, 0.0), (0.0, 10.0)),
            ((0.0, 10.0), (10.0, 10.0)),
            ((10.0, 10.0), (10.0, 0.0)),
            ((0.0, 0.0), (10.0, 0.0)),
        ):
            graph.add_edge(
                first,
                second,
                weight=engine.Point(first).distance(engine.Point(second)),
                calculation_factor=1.0,
            )
        old_route = engine.LineString(
            [(0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0)]
        )
        synthetic_routes, _lengths, synthetic_distances = (
            engine.build_refreshed_fixed_routes(
                graph,
                [(0.0, 0.0)],
                [(10.0, 0.0)],
                np.asarray([0], dtype=int),
                [old_route],
                ["Teststation"],
            )
        )
        assert abs(float(synthetic_distances[0]) - 10.0) < 1e-9
        assert abs(float(synthetic_routes[0].length) - 10.0) < 1e-9

        # A station and terminal which collapse to the same noded graph vertex
        # must not replace an existing visible route with an empty geometry.
        preserved = set()
        collapsed_routes, _collapsed_lengths, collapsed_distances = (
            engine.build_refreshed_fixed_routes(
                graph,
                [(0.0, 0.0)],
                [(0.0, 0.0)],
                np.asarray([0], dtype=int),
                [old_route],
                ["Samenvallend"],
                previous_point_route_distance=np.asarray([7.5]),
                preserved_station_indices=preserved,
            )
        )
        assert preserved == {0}
        assert collapsed_routes[0].equals(old_route)
        assert abs(float(collapsed_distances[0]) - 7.5) < 1e-9

        # An already missing old route should be repairable from the current
        # trench graph without requiring an old ownership anchor.
        repaired_routes, _repaired_lengths, repaired_distances = (
            engine.build_refreshed_fixed_routes(
                graph,
                [(0.0, 0.0)],
                [(10.0, 0.0)],
                np.asarray([0], dtype=int),
                [engine.LineString()],
                ["Ontbrekend"],
                previous_point_route_distance=np.asarray([0.0]),
            )
        )
        assert abs(float(repaired_routes[0].length) - 10.0) < 1e-9
        assert abs(float(repaired_distances[0]) - 10.0) < 1e-9

        assert QgsProject.instance().read(str(project_path))
        connections = one("Aansluitingen geclusterd")
        stations = one("Stations ontwerp")
        areas = one("Clustergebieden")
        routes = one("Kabelroutes per cluster")
        cables = one("Sleuven geknipt/genood")
        plan = one("Plangebied")
        assignment_before = {
            int(feature.id()): str(feature["Cluster"])
            for feature in connections.getFeatures()
        }
        route_before = {
            str(feature["Cluster"]): feature.geometry().asWkt()
            for feature in routes.getFeatures()
        }
        cable_count_before = cables.featureCount()

        source_geometry = next(cables.getFeatures()).geometry()
        midpoint = source_geometry.interpolate(source_geometry.length() / 2.0).asPoint()
        drawn = QgsVectorLayer(
            f"LineString?crs={cables.crs().authid()}", "test_sleuf", "memory"
        )
        feature = QgsFeature(drawn.fields())
        feature.setGeometry(
            QgsGeometry.fromPolylineXY(
                [
                    QgsPointXY(midpoint.x() - 4.0, midpoint.y() - 6.0),
                    QgsPointXY(midpoint.x() + 4.0, midpoint.y() + 6.0),
                ]
            )
        )
        assert drawn.dataProvider().addFeature(feature)

        from ls_netontwerp_wizard.algorithms.sleuf_route_tool import (
            SleufRouteToevoegenAlgorithm,
        )

        add_algorithm = SleufRouteToevoegenAlgorithm()
        add_algorithm.initAlgorithm()
        output_dir = project_path.parent / "network_test_output"
        add_result = add_algorithm.processAlgorithm(
            {
                add_algorithm.SLEUVEN: cables,
                add_algorithm.NIEUWE_SLEUF: drawn,
                add_algorithm.AANSLUITINGEN: connections,
                add_algorithm.STATIONS: stations,
                add_algorithm.PLANGEBIED: plan,
                add_algorithm.KNOOP_TOLERANTIE_M: 1.0,
                add_algorithm.BACKUPMAP: str(output_dir),
            },
            QgsProcessingContext(),
            Feedback(),
        )
        assert Path(add_result[add_algorithm.BACKUP_GPKG]).is_file()
        assert cables.featureCount() > cable_count_before

        from ls_netontwerp_wizard.algorithms.handmatige_cluster_correctie_tool import (
            HandmatigeClusterCorrectieAlgorithm,
        )

        refresh = HandmatigeClusterCorrectieAlgorithm()
        refresh.initAlgorithm()
        selected_route = next(routes.getFeatures())
        selected_cluster = str(selected_route["Cluster"])
        routes.selectByIds([selected_route.id()])
        refresh_result = refresh.processAlgorithm(
            {
                refresh.AANSLUITINGEN: connections,
                refresh.STATIONS: stations,
                refresh.GEBIEDEN: areas,
                refresh.KABELROUTES: routes,
                refresh.SLEUVEN: cables,
                refresh.PLANGEBIED: plan,
                refresh.HELE_BRONCLUSTER_VERWIJDEREN: False,
                refresh.ALLE_ROUTES_VERVERSEN: True,
                refresh.ALLEEN_GESELECTEERDE_ROUTES: True,
                refresh.ROUTE_CLUSTERS: "",
                refresh.ALLES_TOESTAAN: False,
                refresh.CONTROLE_MAX_ONTWERPSTROOM: False,
                refresh.CONTROLE_MAX_KABELLENGTE: True,
                refresh.CONTROLE_ROUTES_ANDERE_CLUSTERS: True,
                refresh.CONTROLE_GEDEELDE_ROUTES_VERTAKKINGEN: True,
                refresh.MAX_ROUTE_M: 10000.0,
                refresh.KNOOP_TOLERANTIE_M: 0.0,
                refresh.BACKUPMAP: str(output_dir),
            },
            QgsProcessingContext(),
            Feedback(),
        )
        assignment_after = {
            int(feature.id()): str(feature["Cluster"])
            for feature in connections.getFeatures()
        }
        assert assignment_after == assignment_before
        assert refresh_result[refresh.VERPLAATST_AANTAL] == 0
        assert all(float(feature["Route_m"]) >= 0.0 for feature in connections.getFeatures())
        for feature in routes.getFeatures():
            if str(feature["Cluster"]) != selected_cluster:
                assert feature.geometry().asWkt() == route_before[str(feature["Cluster"])]
        print("NETWORK_MAINTENANCE_TEST_OK", flush=True)
    finally:
        app.exitQgis()


if __name__ == "__main__":
    main()
