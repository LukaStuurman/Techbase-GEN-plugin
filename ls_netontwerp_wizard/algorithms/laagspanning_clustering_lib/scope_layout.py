"""Persistent, independent view of the current station assignments."""
import hashlib
import html
import json
import re
from pathlib import Path
from uuid import uuid4

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import (Qgis, QgsCategorizedSymbolRenderer, QgsCoordinateTransform, QgsFeature, QgsField, QgsGeometry,
    QgsLayoutItemLabel, QgsLayoutPoint, QgsLayoutSize, QgsMarkerSymbol, QgsPalLayerSettings,
    QgsMessageLog, QgsProperty, QgsProviderRegistry, QgsReadWriteContext, QgsRectangle,
    QgsRendererCategory, QgsSymbolLayer, QgsTextBufferSettings, QgsTextFormat, QgsVectorFileWriter,
    QgsVectorLayer, QgsVectorLayerSimpleLabeling, QgsVariantUtils)

try:
    from .layout_style_utils import configure_layout_style, ensure_scope_connection_labels, ensure_connections_legend
    from ...scope_contrast_colors import choose_scope_colors
except ImportError:
    from layout_style_utils import configure_layout_style, ensure_scope_connection_labels, ensure_connections_legend
    from scope_contrast_colors import choose_scope_colors


def text(value):
    return "" if QgsVariantUtils.isNull(value) else str(value).strip()


def field(layer, *names):
    fields = {item.name().casefold(): index for index, item in enumerate(layer.fields())}
    return next((fields[str(name).casefold()] for name in names
                 if name and str(name).casefold() in fields), -1)


def _context_layer(uri, name, manifest):
    """Resolve portable OGR sources against their manifest, keeping URI options."""
    registry = QgsProviderRegistry.instance()
    parts = registry.decodeUri("ogr", str(uri))
    path = parts.get("path", "")
    if path and not Path(path).is_absolute():
        parts["path"] = str((manifest.parent / path).resolve())
        uri = registry.encodeUri("ogr", parts) or uri
    return QgsVectorLayer(str(uri), name, "ogr")


def _station_rows(project, source, target, context, linked_names, extent, *, original, extent_crs):
    """Keep source station types separate from the output's Bestaand/Nieuw status."""
    name_index = field(source, context.get("station_field", "Station"), "Station", "Cluster", "Stationsnaam", "Stationsnaa")
    type_index = field(source, "Type")
    rows = []
    for feature in source.getFeatures():
        kind = text(feature[type_index]).casefold() if type_index >= 0 else ""
        if kind in ("nieuw", "gepland", "new", "planned"):
            continue
        if not original and type_index >= 0 and kind != "bestaand":
            continue
        shape = QgsGeometry(feature.geometry())
        if shape.isEmpty():
            continue
        if source.crs() != target.crs():
            shape.transform(QgsCoordinateTransform(source.crs(), target.crs(), project))
        name = text(feature[name_index]) if name_index >= 0 else ""
        # Nearby existing stations also matter when they have no connection in
        # this selection. Linked stations outside the frame remain in scope.
        map_shape = QgsGeometry(shape)
        if target.crs() != extent_crs:
            map_shape.transform(QgsCoordinateTransform(target.crs(), extent_crs, project))
        if name not in linked_names and not extent.intersects(map_shape.boundingBox()):
            continue
        row = QgsFeature(target.fields())
        row.setGeometry(shape)
        row["Station"] = name
        rows.append(row)
    return rows


def ensure_scope_station_labels(stations):
    if stations.customProperty("LSNetontwerp/scope_station_labels", "") == "1" and stations.labelsEnabled():
        return False
    settings = QgsPalLayerSettings()
    settings.fieldName = "Station"
    settings.enabled = True
    settings.scaleVisibility = False
    settings.displayAll = True
    settings.priority = 10
    settings.obstacle = False
    settings.zIndex = 100.0
    try:
        placement = settings.placementSettings()
        placement.setAllowDegradedPlacement(True)
        placement.setOverlapHandling(Qgis.LabelOverlapHandling.AllowOverlapAtNoCost)
        settings.setPlacementSettings(placement)
    except (AttributeError, TypeError):
        pass
    font = QFont("Arial", 8)
    font.setBold(True)
    text_format = QgsTextFormat()
    text_format.setFont(font)
    text_format.setSize(8.0)
    text_format.setSizeUnit(Qgis.RenderUnit.Points)
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(.65)
    buffer.setSizeUnit(Qgis.RenderUnit.Millimeters)
    buffer.setColor(QColor("white"))
    text_format.setBuffer(buffer)
    settings.setFormat(text_format)
    stations.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    stations.setLabelsEnabled(True)
    configure_layout_style(stations, label_scale=.7)
    stations.setCustomProperty("LSNetontwerp/scope_station_labels", "1")
    return True


def _include_station_extent(map_item, stations):
    previous = map_item.extent()
    extent = QgsRectangle(previous)
    for feature in stations.getFeatures():
        if feature.hasGeometry() and not feature.geometry().isEmpty():
            shape = QgsGeometry(feature.geometry())
            if stations.crs() != map_item.crs():
                shape.transform(QgsCoordinateTransform(stations.crs(), map_item.crs(), map_item.layout().project()))
            extent.combineExtentWith(shape.boundingBox())
    if extent == previous:
        return False
    extent.grow(max(extent.width(), extent.height()) * .02)
    map_item.zoomToExtent(extent)
    return True


def repair_scope_station_snapshot(project, layout, points, stations):
    """Add missing original stations to an old snapshot; keep frozen positions."""
    if stations.customProperty("LSNetontwerp/scope_station_snapshot_version", "") == "2":
        return False
    map_item = layout.itemById("scopekaart")
    if map_item is None:
        return False
    linked_names = {text(feature["Station"]) for feature in points.getFeatures() if text(feature["Station"])}
    existing_names = {text(feature["Station"]) for feature in stations.getFeatures() if text(feature["Station"])}
    needs_source = stations.featureCount() == 0 or bool(linked_names - existing_names)
    path = QgsProviderRegistry.instance().decodeUri(points.providerType(), points.source()).get("path", "")
    manifest = Path(path).parent / "scope_invoer.json" if path else None

    def unavailable(message):
        if needs_source and layout.customProperty("LSNetontwerp/scope_station_warning", "") != message:
            layout.setCustomProperty("LSNetontwerp/scope_station_warning", message)
            QgsMessageLog.logMessage(message, "LS Netontwerp", Qgis.MessageLevel.Warning)
        return False

    if manifest is None or not manifest.exists():
        return unavailable("Bestaande Scope-stations konden niet worden hersteld: scope_invoer.json ontbreekt. De bevroren aansluitingen blijven behouden.")
    try:
        context = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return unavailable("Bestaande Scope-stations konden niet worden hersteld: de oorspronkelijke Scope-context is niet leesbaar.")
    uri = context.get("stations_uri")
    if not uri:
        return unavailable("Bestaande Scope-stations konden niet worden hersteld: de oorspronkelijke stationsbron is niet vastgelegd.")
    original = _context_layer(uri, "Scope stations bron", manifest)
    if not original.isValid():
        return unavailable("Bestaande Scope-stations konden niet worden hersteld: de oorspronkelijke stationsbron is niet beschikbaar.")
    candidates = _station_rows(project, original, stations, context, linked_names,
                               map_item.extent(), original=True, extent_crs=map_item.crs())
    existing_shapes = {bytes(feature.geometry().asWkb()) for feature in stations.getFeatures() if not text(feature["Station"])}
    additions = [feature for feature in candidates
                 if (text(feature["Station"]) and text(feature["Station"]) not in existing_names)
                 or (not text(feature["Station"]) and bytes(feature.geometry().asWkb()) not in existing_shapes)]
    if not additions and stations.featureCount() == 0:
        return unavailable("Bestaande Scope-stations konden niet worden hersteld: de oorspronkelijke bron bevat geen bruikbare bestaande stations voor deze Scope.")
    if additions:
        if not stations.dataProvider().addFeatures(additions)[0]:
            return unavailable("Bestaande Scope-stations konden niet aan de opgeslagen momentopname worden toegevoegd; controleer de schrijfrechten van het Scope-bestand.")
        stations.updateExtents()
        stations.triggerRepaint()
        layout.setCustomProperty("LSNetontwerp/scope_station_extent_pending", True)
    layout.removeCustomProperty("LSNetontwerp/scope_station_warning")
    # Repair an old snapshot once. Future source edits must not silently change
    # the existing-situation map when the project is opened again.
    stations.setCustomProperty("LSNetontwerp/scope_station_snapshot_version", "2")
    return True



SCOPE_COLOR_VERSION = "LSNetontwerp/scope_contrast_colors"


def _scope_marker_colors(points):
    renderer = points.renderer()
    if not isinstance(renderer, QgsCategorizedSymbolRenderer):
        return {}
    return {text(category.value()): category.symbol().color().name()
            for category in renderer.categories()
            if text(category.value()) and category.symbol() is not None}


def _point_coords(layer, geometry, project, target_crs):
    if geometry is None or geometry.isEmpty():
        return None
    try:
        shape = QgsGeometry(geometry)
        if layer.crs() != target_crs:
            shape.transform(QgsCoordinateTransform(layer.crs(), target_crs, project))
        point = shape.asMultiPoint()[0] if shape.isMultipart() else shape.asPoint()
        return float(point.x()), float(point.y())
    except (AttributeError, IndexError, TypeError, ValueError):
        return None


def _recolor_scope_table(table, colors):
    """Update only the generated swatches, not user-edited columns or formulas."""
    if not isinstance(table, QgsLayoutItemLabel):
        return False
    original = table.text()
    if '<th>Station</th><th>Aantal</th><th>Ontwerp A</th>' not in original:
        return False
    pattern = re.compile(r'(<td bgcolor=")[^"]+(">&nbsp;</td><td>)([^<]*)(</td>)')
    def substitute(match):
        station = html.unescape(match.group(3))
        value = "#94a3b8" if station == "Geen station gekoppeld" else colors.get(station)
        if value is None:
            return match.group(0)
        return match.group(1) + value + match.group(2) + match.group(3) + match.group(4)
    changed = pattern.sub(substitute, original)
    if changed != original:
        table.setText(changed)
        return True
    return False


def ensure_scope_color_contrast(project, points, stations, table=None):
    """Color frozen Scope groups by proximity, once per generated snapshot.

    Existing 1.33.4 snapshots are migrated without touching geometries, actual
    station assignments or the layout extent. Later user recoloring is retained.
    """
    current = _scope_marker_colors(points)
    if not current:
        return False, {}
    if points.customProperty(SCOPE_COLOR_VERSION, "") == "1":
        return False, current
    locations = {station: [] for station in current}
    for layer in (points, stations):
        for feature in layer.getFeatures():
            station = text(feature["Station"])
            if not station:
                continue
            coordinate = _point_coords(layer, feature.geometry(), project, points.crs())
            if coordinate is not None:
                locations.setdefault(station, []).append(coordinate)
    colors = choose_scope_colors(locations, current)
    renderer = points.renderer().clone()
    for index, category in enumerate(renderer.categories()):
        station = text(category.value())
        if station in colors:
            symbol = category.symbol().clone()
            symbol.setColor(QColor(colors[station]))
            renderer.updateCategorySymbol(index, symbol)
    points.setRenderer(renderer)
    station_renderer = stations.renderer().clone()
    station_symbol = station_renderer.symbol().clone() if hasattr(station_renderer, "symbol") and station_renderer.symbol() else None
    if station_symbol is not None and station_symbol.symbolLayerCount():
        cases = ["WHEN \"Station\" = '" + station.replace("'", "''") +
                 "' THEN '" + colors[station] + "'" for station in sorted(colors)]
        station_symbol.symbolLayer(0).setDataDefinedProperty(
            QgsSymbolLayer.Property.FillColor,
            QgsProperty.fromExpression("CASE " + " ".join(cases) + " ELSE '#94a3b8' END"))
        station_renderer.setSymbol(station_symbol)
        stations.setRenderer(station_renderer)
    _recolor_scope_table(table, colors)
    points.setCustomProperty(SCOPE_COLOR_VERSION, "1")
    stations.setCustomProperty(SCOPE_COLOR_VERSION, "1")
    points.triggerRepaint()
    stations.triggerRepaint()
    return True, colors


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
    def geometry(layer, feature, target_crs):
        result = QgsGeometry(feature.geometry())
        if layer.crs() != target_crs:
            result.transform(QgsCoordinateTransform(layer.crs(), target_crs, project))
        return result
    source = loaded["aansluitingen_geclusterd"]
    from_original = False
    if field(source, "Station") < 0 and context.get("points_uri"):
        original = _context_layer(context["points_uri"], "Scope bron", manifest)
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
    points = QgsVectorLayer("Point", "Aansluitingen bestaande stations (Scope)", "memory")
    points.setCrs(loaded["aansluitingen_geclusterd"].crs())
    points.dataProvider().addAttributes([QgsField("Station", QVariant.String),
        QgsField("Master_asset_id", QVariant.String), QgsField("Ontwerp_A", QVariant.Double)])
    points.updateFields()
    # Older results lost IDs. Select original features by their exact geometry,
    # without assigning one apartment's identity to another coincident point.
    result_geometries = {bytes(geometry(loaded["aansluitingen_geclusterd"], feature, points.crs()).asWkb())
                         for feature in loaded["aansluitingen_geclusterd"].getFeatures()}
    rows = []
    stations_seen = set()
    for feature in source.getFeatures():
        shape = geometry(source, feature, points.crs())
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
    points.setCustomProperty("LSNetontwerp/scope_role", "connections")

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
    ensure_scope_connection_labels(points)
    station_source = loaded["stations_ontwerp"]
    original_stations = False
    if context.get("stations_uri"):
        candidate = _context_layer(context["stations_uri"], "Scope stations bron", manifest)
        if candidate.isValid():
            station_source = candidate
            original_stations = True
    stations = QgsVectorLayer("Point", "Bestaande stations (Scope)", "memory")
    stations.setCrs(points.crs())
    stations.dataProvider().addAttributes([QgsField("Station", QVariant.String)])
    stations.updateFields()
    rows = _station_rows(project, station_source, stations, context, stations_seen,
                         layout.itemById("clusterkaart").extent(), original=original_stations,
                         extent_crs=layout.itemById("clusterkaart").crs())
    if not stations.dataProvider().addFeatures(rows)[0]:
        raise RuntimeError("De bestaande Scope-stations konden niet worden voorbereid.")
    displayed_stations = {text(feature["Station"]) for feature in rows if text(feature["Station"])}
    stations = snapshot(project, stations, path, "stations_scope", False)
    stations.setCustomProperty("LSNetontwerp/scope_role", "stations")
    stations.setCustomProperty("LSNetontwerp/scope_station_snapshot_version", "2")
    symbol = QgsMarkerSymbol.createSimple({"name": "square", "size": "3.2", "color": "227,26,28", "outline_color": "0,0,0"})
    color_cases = ["WHEN \"Station\" = '" + station.replace("'", "''") + "' THEN '" + color(station).name() + "'" for station in sorted(stations_seen | displayed_stations)]
    if color_cases:
        symbol.symbolLayer(0).setDataDefinedProperty(QgsSymbolLayer.Property.FillColor,
            QgsProperty.fromExpression("CASE " + " ".join(color_cases) + " ELSE '#94a3b8' END"))
    stations.renderer().setSymbol(symbol)
    ensure_scope_station_labels(stations)
    configure_layout_style(stations, symbol_scale=.7)
    _, scope_colors = ensure_scope_color_contrast(project, points, stations)
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
    _include_station_extent(map_item, stations)
    scope.setCustomProperty("LSNetontwerp/scope_station_extent_repaired", "1")
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
    for station in sorted(stations_seen | displayed_stations) + [""]:
        escaped = station.replace("'", "''")
        condition = f'coalesce("Station", \'\') = \'{escaped}\''
        count = f"aggregate('{points.id()}', 'count', $id, {condition})"
        load = f"aggregate('{points.id()}', 'sum', \"Ontwerp_A\", {condition})"
        fill = (scope_colors.get(station, color(station).name()) if station else "#94a3b8")
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
    ensure_connections_legend(legend, points)
    legend.updateLegend()
    # duplicateLayout() creates an unsupported QgsLayoutItemHtml frame from
    # the source HTML label in QGIS 4, underneath the replacement label.
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from ls_netontwerp_wizard.layout_repairs import repair_scope_html_frames
    repair_scope_html_frames(scope)
    scope.refresh()
    if not scope.saveAsTemplate(str(output_dir / "scope.qpt"), QgsReadWriteContext()):
        raise RuntimeError("De Scope-layouttemplate kon niet worden opgeslagen.")
    return scope
