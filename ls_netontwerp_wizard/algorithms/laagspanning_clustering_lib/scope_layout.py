"""Persistent, independent view of the current station assignments."""
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import (QgsCategorizedSymbolRenderer, QgsCoordinateTransform, QgsFeature, QgsField, QgsGeometry,
    QgsLayoutItemLabel, QgsLayoutPoint, QgsLayoutSize, QgsMarkerSymbol, QgsPalLayerSettings,
    QgsProperty, QgsReadWriteContext, QgsRendererCategory, QgsSymbolLayer, QgsVectorFileWriter,
    QgsVectorLayer, QgsVectorLayerSimpleLabeling, QgsVariantUtils)

from layout_style_utils import configure_layout_style


def text(value):
    return "" if QgsVariantUtils.isNull(value) else str(value).strip()


def field(layer, *names):
    return next((i for i, f in enumerate(layer.fields())
        if f.name().casefold() in {name.casefold() for name in names}), -1)


def snapshot(project, memory, path, name, first):
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName, options.layerName = "GPKG", name
    if not first:
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
    error, message, *_ = QgsVectorFileWriter.writeAsVectorFormatV3(
        memory, str(path), project.transformContext(), options)
    if error != QgsVectorFileWriter.NoError:
        raise RuntimeError(f"Scope-laag kon niet worden opgeslagen: {message}")
    layer = QgsVectorLayer(f"{path}|layername={name}", memory.name(), "ogr")
    if not layer.isValid():
        raise RuntimeError("De opgeslagen Scope-laag is ongeldig.")
    layer.setReadOnly(True)
    layer.setCustomProperty("LSNetontwerp/scope_snapshot", True)
    project.addMapLayer(layer, False)
    return layer


def add_scope_layout(project, layout, loaded, output_dir, cluster_rgb):
    """Freeze actual assignments; cluster edits must never recolor this map."""
    context = {}
    manifest = output_dir / "scope_invoer.json"
    if manifest.exists():
        context = json.loads(manifest.read_text(encoding="utf-8"))
    def geometry(layer, feature):
        result = QgsGeometry(feature.geometry())
        if layer.crs() != project.crs():
            result.transform(QgsCoordinateTransform(layer.crs(), project.crs(), project))
        return result
    source = loaded["aansluitingen_geclusterd"]
    from_original = False
    if field(source, "Station") < 0 and context.get("points_uri"):
        original = QgsVectorLayer(context["points_uri"], "Scope bron", "ogr")
        if original.isValid():
            source, from_original = original, True
    source_station = field(source, "Station")
    asset = field(source, "master_asset_id", "Master Asset ID")
    current = field(source, "Ontwerp_A", context.get("current_field", "Hoogste Trafo"))
    lookup = {}
    if source_station < 0 and context.get("station_csv"):
        # Explicit workflow context only; never guess an unrelated CSV.
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
        from ls_netontwerp_wizard.station_name_csv import load_station_name_lookup, normalize_asset_id
        lookup, _ = load_station_name_lookup(context["station_csv"], context.get("station_csv_field", "SourceFile"))
    else:
        normalize_asset_id = lambda value: text(value).casefold()
    points = QgsVectorLayer("Point?crs=EPSG:28992", "Aansluitingen bestaande stations (Scope)", "memory")
    points.dataProvider().addAttributes([QgsField("Station", QVariant.String),
        QgsField("Master_asset_id", QVariant.String), QgsField("Ontwerp_A", QVariant.Double)])
    points.updateFields()
    # Older results lost IDs. Select original features by their exact geometry,
    # without assigning one apartment's identity to another coincident point.
    result_geometries = {bytes(f.geometry().asWkb()) for f in loaded["aansluitingen_geclusterd"].getFeatures()}
    rows = []
    stations_seen = set()
    for feature in source.getFeatures():
        shape = geometry(source, feature)
        if from_original and bytes(shape.asWkb()) not in result_geometries:
            continue
        identity = text(feature[asset]) if asset >= 0 else ""
        station = text(feature[source_station]) if source_station >= 0 else lookup.get(normalize_asset_id(identity), "")
        if station:
            stations_seen.add(station)
        row = QgsFeature(points.fields())
        row.setGeometry(shape)
        row.setAttributes([station, identity, feature[current] if current >= 0 else None])
        rows.append(row)
    if not points.dataProvider().addFeatures(rows)[0]:
        raise RuntimeError("De Scope-aansluitingen konden niet worden voorbereid.")
    path = output_dir / f"scope_bestaande_stations_{uuid4().hex[:8]}.gpkg"
    points = snapshot(project, points, path, "aansluitingen_scope", True)

    def color(station):
        saved = context.get("station_colors", {}).get(station)
        if saved and QColor(saved).isValid():
            return QColor(saved)
        rgb = cluster_rgb.get(station)
        if rgb:
            return QColor(*rgb)
        hue = int(hashlib.sha256(station.encode()).hexdigest()[:8], 16) % 360
        return QColor.fromHsv(hue, 190, 220)

    categories = [QgsRendererCategory(station, QgsMarkerSymbol.createSimple({
        "name": "circle", "size": "4.7", "color": color(station).name(),
        "outline_color": "34,34,34", "outline_width": "0.22"}), station)
        for station in sorted(stations_seen)]
    categories.append(QgsRendererCategory("", QgsMarkerSymbol.createSimple({
        "name": "circle", "size": "4.7", "color": "#94a3b8"}), "Geen station gekoppeld"))
    points.setRenderer(QgsCategorizedSymbolRenderer("Station", categories))
    configure_layout_style(points, symbol_scale=.42)
    station_source = loaded["stations_ontwerp"]
    if context.get("stations_uri"):
        candidate = QgsVectorLayer(context["stations_uri"], "Scope stations bron", "ogr")
        if candidate.isValid():
            station_source = candidate
    name_index = field(station_source, context.get("station_field", "Station"), "Cluster", "Stationsnaam", "Stationsnaa")
    type_index = field(station_source, "Type")
    stations = QgsVectorLayer("Point?crs=EPSG:28992", "Bestaande stations (Scope)", "memory")
    stations.dataProvider().addAttributes([QgsField("Station", QVariant.String)])
    stations.updateFields()
    rows = []
    for feature in station_source.getFeatures():
        if type_index >= 0 and text(feature[type_index]) != "Bestaand":
            continue
        name = text(feature[name_index]) if name_index >= 0 else ""
        if name not in stations_seen:
            continue
        row = QgsFeature(stations.fields())
        row.setGeometry(geometry(station_source, feature))
        row.setAttributes([name])
        rows.append(row)
    stations.dataProvider().addFeatures(rows)
    stations = snapshot(project, stations, path, "stations_scope", False)
    symbol = QgsMarkerSymbol.createSimple({"name": "square", "size": "3.2", "color": "227,26,28", "outline_color": "0,0,0"})
    color_cases = ["WHEN \"Station\" = '" + station.replace("'", "''") + "' THEN '" + color(station).name() + "'" for station in sorted(stations_seen)]
    if color_cases:
        symbol.symbolLayer(0).setDataDefinedProperty(QgsSymbolLayer.Property.FillColor,
            QgsProperty.fromExpression("CASE " + " ".join(color_cases) + " ELSE '#94a3b8' END"))
    stations.renderer().setSymbol(symbol)
    label = QgsPalLayerSettings()
    label.fieldName = "Station"
    stations.setLabeling(QgsVectorLayerSimpleLabeling(label))
    stations.setLabelsEnabled(True)
    configure_layout_style(stations, symbol_scale=.7, label_scale=.7)
    group = project.layerTreeRoot().addGroup("Scope - bestaande situatie")
    group.addLayer(stations)
    group.addLayer(points)
    group.setItemVisibilityChecked(False)
    group.setExpanded(False)
    scope = project.layoutManager().duplicateLayout(layout, "Scope")
    if scope is None:
        raise RuntimeError("De Scope-layout kon niet worden gemaakt.")
    map_item = scope.itemById("clusterkaart")
    map_item.setId("scopekaart")
    map_layers = [stations, points]
    if "plangebied" in loaded:
        map_layers.append(loaded["plangebied"])
    map_layers.extend(layer for layer in layout.itemById("clusterkaart").layers() if layer.providerType() == "wms")
    map_item.setLayers(map_layers)
    map_item.setKeepLayerSet(True)
    title = scope.itemById("stationsoverzicht_titel")
    title.setText("Scope - bestaande stations")
    # QGIS 4's layout duplication drops HTML-label text/IDs. Replace the
    # cloned table explicitly; ordinary map/grid/legend items clone correctly.
    for item in list(scope.items()):
        if isinstance(item, QgsLayoutItemLabel) and abs(item.positionWithUnits().y() - 26.0) < .01:
            scope.removeLayoutItem(item)
    table = QgsLayoutItemLabel(scope)
    table.setMode(QgsLayoutItemLabel.Mode.ModeHtml)
    table.setMargin(0)
    table.setFont(QFont("Arial", 6))
    table.attemptMove(QgsLayoutPoint(324.5, 26.0))
    table.attemptResize(QgsLayoutSize(86.0, 137.0))
    scope.addLayoutItem(table)
    # A compact station key replaces the design table. Values are live in the
    # frozen snapshot, independent of later edits to the cluster result.
    lines = []
    import html
    for station in sorted(stations_seen) + [""]:
        escaped = station.replace("'", "''")
        condition = f'coalesce("Station", \'\') = \'{escaped}\''
        count = f"aggregate('{points.id()}', 'count', $id, {condition})"
        load = f"aggregate('{points.id()}', 'sum', \"Ontwerp_A\", {condition})"
        fill = color(station).name() if station else "#94a3b8"
        lines.append(f'<tr><td bgcolor="{fill}">&nbsp;</td><td>{html.escape(station or "Geen station gekoppeld")}</td>'
            f'<td>[% {count} %]</td><td>[% format_number({load}, 1) %]</td></tr>')
    table.setText('<table width="100%" border="1" cellspacing="0" cellpadding="0" style="font-family:Arial;font-size:6pt">'
        '<tr><th></th><th>Station</th><th>Aantal</th><th>Ontwerp A</th></tr>' + ''.join(lines) + '</table>')
    table.setId("scope_stationsoverzicht")
    legend = scope.itemById("legenda")
    legend.setLinkedMap(map_item)
    legend.model().rootGroup().removeAllChildren()
    legend.model().rootGroup().addLayer(stations)
    if "plangebied" in loaded:
        legend.model().rootGroup().addLayer(loaded["plangebied"])
    legend.updateLegend()
    scope.refresh()
    if not scope.saveAsTemplate(str(output_dir / "scope.qpt"), QgsReadWriteContext()):
        raise RuntimeError("De Scope-layouttemplate kon niet worden opgeslagen.")
    return scope
