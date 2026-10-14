"""One-layer QGIS styling for a compact print layout.

QGIS 4.2 is unstable when a plugin repeatedly installs serialized layer style
overrides.  Data-defined symbol and label sizes are safer: the normal canvas
size is used everywhere, while the named clustering layout receives its compact
physical size.  The project consequently contains exactly one layer per data
component.
"""

from __future__ import annotations

from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsPalLayerSettings,
    QgsProperty,
    QgsSymbolLayer,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)


PROPERTY_ENABLED = "LSNetontwerp/layout_dynamic_style"
LAYOUT_NAME = "Clustering overzicht"


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
