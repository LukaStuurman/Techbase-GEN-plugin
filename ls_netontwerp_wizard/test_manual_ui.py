"""Regression test for two corrections on the wizard's internal manual page."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from qgis.core import QgsApplication, QgsProcessingContext, QgsProject, QgsVectorLayer


DISPLAY_LAYERS = (
    ("aansluitingen_geclusterd", "Aansluitingen geclusterd"),
    ("stations_ontwerp", "Stations ontwerp"),
    ("clustergebieden", "Clustergebieden"),
    ("cluster_kabelroutes", "Kabelroutes per cluster"),
    ("sleuven_genood", "Sleuven geknipt/genood"),
    ("plangebied", "Plangebied"),
)


def by_name(name):
    matches = QgsProject.instance().mapLayersByName(name)
    assert len(matches) == 1, (name, len(matches))
    return matches[0]


def select_small_cluster(connections, stations):
    counts = {}
    first_feature = {}
    for feature in connections.getFeatures():
        cluster = str(feature["Cluster"])
        counts[cluster] = counts.get(cluster, 0) + 1
        first_feature.setdefault(cluster, feature.id())
    station_features = list(stations.getFeatures())
    target = max(
        station_features,
        key=lambda feature: (float(feature["Max_A"]), str(feature["Cluster"])),
    )
    target_cluster = str(target["Cluster"])
    source_cluster = min(
        (cluster for cluster in counts if cluster != target_cluster),
        key=lambda cluster: (counts[cluster], cluster),
    )
    connections.removeSelection()
    stations.removeSelection()
    connections.selectByIds([first_feature[source_cluster]])
    stations.selectByIds([target.id()])
    return source_cluster


def main():
    gpkg = Path(sys.argv[1]).resolve()
    plugin_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(plugin_dir.parent))
    app = QgsApplication([], False)
    app.initQgis()

    project = QgsProject.instance()
    project.setFileName(str(gpkg.with_name("manual_ui_test.qgz")))
    for source_name, display_name in DISPLAY_LAYERS:
        layer = QgsVectorLayer(
            f"{gpkg}|layername={source_name}", display_name, "ogr"
        )
        assert layer.isValid(), source_name
        project.addMapLayer(layer)

    import ls_netontwerp_wizard.dialog as dialog_module
    from ls_netontwerp_wizard.algorithms.handmatige_cluster_correctie_tool import (
        HandmatigeClusterCorrectieAlgorithm,
    )
    from ls_netontwerp_wizard.dialog import LSNetontwerpDialog

    def run_manual_algorithm(_algorithm_id, parameters, feedback=None, **_kwargs):
        algorithm = HandmatigeClusterCorrectieAlgorithm()
        algorithm.initAlgorithm()
        return algorithm.processAlgorithm(
            parameters, QgsProcessingContext(), feedback
        )

    # python-qgis.bat does not load QGIS Desktop's Processing plugin. Replace
    # only the dispatch function; the real algorithm, worker and layer updates
    # are still exercised twice through the wizard page.
    dialog_module.processing.run = run_manual_algorithm
    dialog = LSNetontwerpDialog()
    dialog._show_classic_manual_page(False)
    assert dialog.page_stack.currentWidget() is dialog.manual_page
    assert dialog.manual_advanced_container.isHidden()
    dialog.manual_advanced_toggle.setChecked(True)
    dialog.manual_allow_all.setChecked(True)
    dialog.manual_remove_cluster.setChecked(True)
    dialog.manual_backup_edit.setText(str(gpkg.parent / "manual_ui_backups"))

    connections = by_name("Aansluitingen geclusterd")
    stations = by_name("Stations ontwerp")
    for iteration in range(2):
        source_cluster = select_small_cluster(connections, stations)
        before = stations.featureCount()
        dialog._refresh_manual_selection_status()
        assert "doelstations: 1" in dialog.manual_selection_label.text()
        dialog.run_manual_correction()
        assert dialog.manual_status_label.text().startswith("Gereed:"), (
            iteration,
            dialog.manual_status_label.text(),
        )
        remaining = {str(feature["Cluster"]) for feature in stations.getFeatures()}
        assert source_cluster not in remaining
        assert stations.featureCount() == before - 1
        dialog.show_home_page()
        assert dialog.page_stack.currentWidget() is dialog.main_page
        dialog._show_classic_manual_page(False)
        dialog.manual_advanced_toggle.setChecked(True)
        dialog.manual_allow_all.setChecked(True)
        dialog.manual_remove_cluster.setChecked(True)
        dialog.manual_backup_edit.setText(str(gpkg.parent / "manual_ui_backups"))

    print("MANUAL_UI_REPEAT_TEST_OK", flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
