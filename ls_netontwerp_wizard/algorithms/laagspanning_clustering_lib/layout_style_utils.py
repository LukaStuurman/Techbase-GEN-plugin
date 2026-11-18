"""One-layer QGIS styling for a compact print layout.

QGIS 4.2 is unstable when a plugin repeatedly installs serialized layer style
overrides.  Data-defined symbol and label sizes are safer: the normal canvas
size is used everywhere, while the named clustering layout receives its compact
physical size.  The project consequently contains exactly one layer per data
component.
"""

from __future__ import annotations

from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import (
    Qgis,
    QgsCategorizedSymbolRenderer,
    QgsMapLayerLegendUtils,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsProperty,
    QgsSymbolLayer,
    QgsSymbolLegendNode,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)


PROPERTY_ENABLED = "LSNetontwerp/layout_dynamic_style"
LAYOUT_NAME = "Clustering overzicht"
CONNECTION_LEGEND_PROPERTY = "LSNetontwerp/connections_legend"


def ensure_connection_labels(layer, *, label_scale=None, around_point=False):
    """Restore missing current labels without replacing an existing label style."""
    if not isinstance(layer, QgsVectorLayer) or layer.fields().lookupField("Ontwerp_A") < 0:
        return False
    changed = False
    if layer.labeling() is None:
        settings = QgsPalLayerSettings()
        settings.fieldName = 'format_number("Ontwerp_A", 1)'
        settings.isExpression = True
        settings.enabled = True
        settings.scaleVisibility = False
        settings.placement = (Qgis.LabelPlacement.AroundPoint if around_point
                              else Qgis.LabelPlacement.OverPoint)
        if around_point:
            settings.dist = 1.0
            settings.distUnits = Qgis.RenderUnit.Millimeters
            settings.offsetType = Qgis.LabelOffsetType.FromSymbolBounds
        settings.displayAll = True
        settings.priority = 9
        if not around_point:
            try:
                settings.quadOffset = Qgis.LabelQuadrantPosition.Over
            except AttributeError:
                pass
        font = QFont("Arial", 6)
        font.setBold(True)
        text_format = QgsTextFormat()
        text_format.setFont(font)
        text_format.setSize(5.7)
        text_format.setSizeUnit(Qgis.RenderUnit.Points)
        text_format.setColor(QColor(20, 20, 20))
        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)
        buffer.setSize(.55)
        buffer.setSizeUnit(Qgis.RenderUnit.Millimeters)
        buffer.setColor(QColor("white"))
        text_format.setBuffer(buffer)
        settings.setFormat(text_format)
        layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
        if label_scale is not None:
            configure_layout_style(layer, label_scale=label_scale)
        changed = True
    if not layer.labelsEnabled():
        layer.setLabelsEnabled(True)
        changed = True
    if changed:
        layer.triggerRepaint()
    return changed


def ensure_connections_legend(legend, layer):
    """Use one neutral circle in this layout's private legend, not its map style."""
    if legend is None or not isinstance(layer, QgsVectorLayer):
        return False
    changed = legend.autoUpdateModel()
    if changed:
        legend.setAutoUpdateModel(False)
    model = legend.model()
    root = model.rootGroup()
    nodes = [node for node in root.findLayers() if node.layerId() == layer.id()
             or node.customProperty(CONNECTION_LEGEND_PROPERTY, "")]
    matching = [node for node in nodes if node.layerId() == layer.id()]
    node = matching[0] if matching else root.addLayer(layer)
    changed = changed or not matching
    for duplicate in nodes:
        if duplicate is not node:
            duplicate.parent().removeChildNode(duplicate)
            changed = True
    originals = model.layerOriginalLegendNodes(node)
    symbol_index = next((index for index, item in enumerate(originals)
                         if isinstance(item, QgsSymbolLegendNode)), None)
    if symbol_index is None:
        # An empty categorized renderer has no symbol node to customize.
        return changed
    already_configured = (
        node.customProperty(CONNECTION_LEGEND_PROPERTY, "") == "1"
        and node.customProperty("legend/title-style", "") == "hidden"
        and QgsMapLayerLegendUtils.legendNodeOrder(node) == [symbol_index]
        and QgsMapLayerLegendUtils.legendNodeUserLabel(node, symbol_index) == "Aansluitingen"
        and QgsMapLayerLegendUtils.legendNodeCustomSymbol(node, symbol_index) is not None
    )
    if already_configured and not changed:
        return False
    symbol = QgsMarkerSymbol.createSimple({
        "name": "circle", "size": "1.8", "color": "#64748b",
        "outline_color": "#222222", "outline_width": "0.18",
    })
    QgsMapLayerLegendUtils.setLegendNodeOrder(node, [symbol_index])
    QgsMapLayerLegendUtils.setLegendNodeUserLabel(node, symbol_index, "Aansluitingen")
    QgsMapLayerLegendUtils.setLegendNodeCustomSymbol(node, symbol_index, symbol)
    node.setCustomProperty("legend/title-style", "hidden")
    node.setCustomProperty(CONNECTION_LEGEND_PROPERTY, "1")
    model.refreshLayerLegend(node)
    legend.updateLegend()
    return True


def _layout_value_expression(normal_value, layout_value):
    return (
        "CASE WHEN coalesce(@layout_name, '') IN "
        f"('{LAYOUT_NAME}', 'Scope') THEN {float(layout_value):.12g} "
        f"ELSE {float(normal_value):.12g} END"
    )


def _configure_symbol(symbol, *, symbol_scale, line_scale, stroke_scale):
    if symbol_scale is not None and hasattr(symbol, "size") and hasattr(
        symbol, "setDataDefinedSize"
    ):
        normal = float(symbol.size())
        symbol.setDataDefinedSize(
            QgsProperty.fromExpression(
                _layout_value_expression(normal, normal * float(symbol_scale))
            )
        )
    if line_scale is not None and hasattr(symbol, "width") and hasattr(
        symbol, "setDataDefinedWidth"
    ):
        normal = float(symbol.width())
        symbol.setDataDefinedWidth(
            QgsProperty.fromExpression(
                _layout_value_expression(normal, normal * float(line_scale))
            )
        )
    if stroke_scale is not None:
        for index in range(symbol.symbolLayerCount()):
            symbol_layer = symbol.symbolLayer(index)
            if not hasattr(symbol_layer, "strokeWidth"):
                continue
            normal = float(symbol_layer.strokeWidth())
            symbol_layer.setDataDefinedProperty(
                QgsSymbolLayer.Property.StrokeWidth,
                QgsProperty.fromExpression(
                    _layout_value_expression(
                        normal, normal * float(stroke_scale)
                    )
                ),
            )
    return symbol


def configure_layout_style(
    layer,
    *,
    symbol_scale=None,
    line_scale=None,
    label_scale=None,
    label_distance_mm=None,
    stroke_scale=None,
):
    """Add layout-aware sizes to the normal style of one persistent layer."""
    if not isinstance(layer, QgsVectorLayer):
        return
    layer.setCustomProperty(PROPERTY_ENABLED, True)
    renderer = layer.renderer().clone()
    if isinstance(renderer, QgsCategorizedSymbolRenderer):
        for index, category in enumerate(renderer.categories()):
            renderer.updateCategorySymbol(
                index,
                _configure_symbol(
                    category.symbol().clone(),
                    symbol_scale=symbol_scale,
                    line_scale=line_scale,
                    stroke_scale=stroke_scale,
                ),
            )
    elif hasattr(renderer, "symbol") and renderer.symbol() is not None:
        renderer.setSymbol(
            _configure_symbol(
                renderer.symbol().clone(),
                symbol_scale=symbol_scale,
                line_scale=line_scale,
                stroke_scale=stroke_scale,
            )
        )
    layer.setRenderer(renderer)

    if layer.labeling() is not None and (
        label_scale is not None or label_distance_mm is not None
    ):
        settings = layer.labeling().settings()
        properties = settings.dataDefinedProperties()
        if label_scale is not None:
            normal_size = float(settings.format().size())
            properties.setProperty(
                QgsPalLayerSettings.Size,
                QgsProperty.fromExpression(
                    _layout_value_expression(
                        normal_size, normal_size * float(label_scale)
                    )
                ),
            )
            normal_buffer = float(settings.format().buffer().size())
            properties.setProperty(
                QgsPalLayerSettings.BufferSize,
                QgsProperty.fromExpression(
                    _layout_value_expression(
                        normal_buffer, normal_buffer * float(label_scale)
                    )
                ),
            )
        if label_distance_mm is not None:
            properties.setProperty(
                QgsPalLayerSettings.LabelDistance,
                QgsProperty.fromExpression(
                    _layout_value_expression(
                        float(settings.dist), float(label_distance_mm)
                    )
                ),
            )
        settings.setDataDefinedProperties(properties)
        layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
        layer.setLabelsEnabled(True)
