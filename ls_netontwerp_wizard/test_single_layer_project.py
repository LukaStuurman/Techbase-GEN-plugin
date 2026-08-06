"""Validate that the generated project uses one layer per result component."""

from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path

from qgis.core import (
    QgsApplication,
    QgsLayoutExporter,
    QgsLayoutItemMap,
    QgsProject,
)


def one(project, name):
    matches = project.mapLayersByName(name)
    assert len(matches) == 1, (name, len(matches))
    return matches[0]


app = QgsApplication([], False)
app.initQgis()
print("stage: app", flush=True)
project_path = Path(sys.argv[1]).resolve()
project = QgsProject.instance()
assert project.read(str(project_path)), project_path
print("stage: project read", flush=True)

names = [layer.name() for layer in project.mapLayers().values()]
assert not [name for name in names if "(layout " in name.casefold()], names
assert not [
    layer.name()
    for layer in project.mapLayers().values()
    if bool(layer.customProperty("LSNetontwerp/layout_helper", False))
]

connections = one(project, "Aansluitingen geclusterd")
stations = one(project, "Stations ontwerp")
routes = one(project, "Kabelroutes per cluster")
areas = one(project, "Clustergebieden")
cables = one(project, "Sleuven geknipt/genood")

layout = project.layoutManager().layoutByName("Clustering overzicht")
assert layout is not None
map_item = layout.itemById("clusterkaart")
assert isinstance(map_item, QgsLayoutItemMap)
layout_ids = {layer.id() for layer in map_item.layers()}
for layer in (connections, stations, routes, areas, cables):
    assert layer.id() in layout_ids, layer.name()
assert not map_item.layerStyleOverrides()
print("stage: layers checked", flush=True)

with zipfile.ZipFile(project_path) as archive:
    project_xml = archive.read(
        next(name for name in archive.namelist() if name.endswith(".qgs"))
    ).decode("utf-8")
assert project_xml.count("@layout_name") >= 4
print("stage: dynamic styles checked", flush=True)

settings = QgsLayoutExporter.ImageExportSettings()
settings.dpi = 96
preview = project_path.with_name("single_layer_layout_preview.png")
assert (
    QgsLayoutExporter(layout).exportToImage(str(preview), settings)
    == QgsLayoutExporter.Success
)
print("stage: layout exported", flush=True)
print(
    f"SINGLE_LAYER_PROJECT_TEST_OK layers={len(names)} preview={preview}",
    flush=True,
)
os._exit(0)
