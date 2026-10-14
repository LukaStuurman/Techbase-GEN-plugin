"""Assign persistent random colors to station categories on connection points."""
import json
import random

from qgis.PyQt.QtGui import QColor
from qgis.core import QgsCategorizedSymbolRenderer, QgsMarkerSymbol, QgsRendererCategory, QgsRenderContext, QgsVariantUtils

from .project_presentation import show_connection_legend


def color_connections_by_station(layer):
    index = layer.fields().lookupField("Station")
    if index < 0:
        return
    try:
        colors = json.loads(str(layer.customProperty("LSNetontwerp/station_colors", "{}")))
        if not isinstance(colors, dict):
            colors = {}
    except (ValueError, TypeError):
        colors = {}
    renderer = layer.renderer()
    if renderer is not None and renderer.type() == "singleSymbol":
        base = renderer.symbol().clone()
    elif renderer is not None and renderer.symbols(QgsRenderContext()):
        base = renderer.symbols(QgsRenderContext())[0].clone()
    else:
        base = QgsMarkerSymbol.createSimple({"name": "circle", "size": "4"})
    values = list(layer.uniqueValues(index))
    known = sorted(str(value) for value in values if not QgsVariantUtils.isNull(value) and str(value).strip())
    generator = random.SystemRandom()
    used = set(colors.values())
    categories = []
    for station in known:
        if not QColor(str(colors.get(station, ""))).isValid():
            color = QColor.fromHsv(generator.randrange(360), generator.randrange(160, 236), generator.randrange(195, 256)).name()
            while color in used:
                color = QColor.fromHsv(generator.randrange(360), generator.randrange(160, 236), generator.randrange(195, 256)).name()
            colors[station] = color
            used.add(color)
        symbol = base.clone()
        symbol.setColor(QColor(colors[station]))
        categories.append(QgsRendererCategory(station, symbol, station))
    neutral = base.clone()
    neutral.setColor(QColor("#94A3B8"))
    # The default category also covers NULL and newly added, unclassified values.
    categories.append(QgsRendererCategory("", neutral, "Geen station gekoppeld"))
    layer.setRenderer(QgsCategorizedSymbolRenderer("Station", categories))
    layer.setCustomProperty("LSNetontwerp/station_colors", json.dumps(colors))
    layer.setCustomProperty("LSNetontwerp/station_coloring", True)
    show_connection_legend(layer)
    layer.triggerRepaint()
