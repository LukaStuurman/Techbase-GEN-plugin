"""Repair saved layout presentation without changing the map categories."""
from qgis.core import Qgis, QgsLayoutItemHtml, QgsLayoutItemLabel, QgsVectorLayer

from .algorithms.laagspanning_clustering_lib.layout_style_utils import (
    ensure_connection_labels, ensure_scope_connection_labels, ensure_connections_legend,
)
from .algorithms.laagspanning_clustering_lib.scope_layout import (
    _include_station_extent, ensure_scope_station_labels, repair_scope_station_snapshot,
)


def repair_scope_html_frames(layout):
    table = layout.itemById("scope_stationsoverzicht")
    if not isinstance(table, QgsLayoutItemLabel):
        return 0
    position = table.positionWithUnits()
    size = table.sizeWithUnits()
    removed = 0
    for multiframe in list(layout.multiFrames()):
        if not isinstance(multiframe, QgsLayoutItemHtml) or multiframe.frameCount() != 1:
            continue
        frame = multiframe.frame(0)
        location, dimensions = frame.positionWithUnits(), frame.sizeWithUnits()
        # Match the unnamed duplicate of this exact table. Other HTML content
        # deliberately placed by the user must remain untouched.
        if frame.id() or any(abs(first-second) > .1 for first, second in (
            (location.x(), position.x()), (location.y(), position.y()),
            (dimensions.width(), size.width()), (dimensions.height(), size.height()),
        )):
            continue
        multiframe.deleteFrames()
        layout.removeMultiFrame(multiframe)
        multiframe.deleteLater()
        removed += 1
    if removed:
        layout.refresh()
        layout.project().setDirty(True)
    return removed


def repair_scope_layouts(project):
    repaired = 0
    for layout in project.layoutManager().layouts():
        if layout.name() not in ("Scope", "Clustering overzicht"):
            continue
        is_scope = layout.name() == "Scope"
        changed = repair_scope_html_frames(layout) if is_scope else 0
        map_item = layout.itemById("scopekaart" if is_scope else "clusterkaart")
        if map_item is None:
            repaired += changed
            continue
        point_layers = [layer for layer in map_item.layers()
                        if isinstance(layer, QgsVectorLayer)
                        and layer.geometryType() == Qgis.GeometryType.Point]
        connections = next((layer for layer in point_layers
                            if layer.fields().lookupField("Ontwerp_A") >= 0
                            and (bool(layer.customProperty("LSNetontwerp/scope_snapshot", False)) == is_scope)), None)
        if connections is not None:
            changed += (ensure_scope_connection_labels(connections) if is_scope
                        else ensure_connection_labels(connections, label_scale=.40))
            changed += ensure_connections_legend(layout.itemById("legenda"), connections)
        if is_scope and connections is not None:
            stations = next((layer for layer in point_layers if layer is not connections
                             and layer.customProperty("LSNetontwerp/scope_snapshot", False)
                             and layer.fields().lookupField("Station") >= 0), None)
            if stations is not None:
                changed += ensure_scope_station_labels(stations)
                changed += repair_scope_station_snapshot(project, layout, connections, stations)
                if (layout.customProperty("LSNetontwerp/scope_station_extent_repaired", "") != "1"
                        or layout.customProperty("LSNetontwerp/scope_station_extent_pending", False)):
                    _include_station_extent(map_item, stations)
                    layout.setCustomProperty("LSNetontwerp/scope_station_extent_repaired", "1")
                    layout.removeCustomProperty("LSNetontwerp/scope_station_extent_pending")
                    changed += 1
        if changed:
            layout.refresh()
            project.setDirty(True)
        repaired += changed
    return repaired
