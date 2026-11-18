"""Offscreen QGIS integration smoke test for responsive clustering options and Scope styling."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qgis.core import (QgsApplication, QgsCategorizedSymbolRenderer, QgsFeature, QgsField,
                       QgsGeometry, QgsLayoutItemLabel, QgsMarkerSymbol, QgsPointXY,
                       QgsPrintLayout, QgsProject, QgsRendererCategory, QgsSingleSymbolRenderer,
                       QgsVectorLayer)
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QWidget, QLabel, QScrollArea

app = QgsApplication([], False)
app.initQgis()

from ls_netontwerp_wizard import clustering_options
from ls_netontwerp_wizard.algorithms.laagspanning_clustering_lib.scope_layout import ensure_scope_color_contrast
from ls_netontwerp_wizard.scope_contrast_colors import perceptual_distance


def settle():
    for _ in range(6):
        app.sendPostedEvents()
        app.processEvents()


def make_layer(title, fields):
    layer = QgsVectorLayer("Point?crs=EPSG:28992", title, "memory")
    layer.dataProvider().addAttributes(fields)
    layer.updateFields()
    assert layer.isValid()
    return layer


def test_form():
    source = make_layer("Aansluitingen met een lange bronbeschrijving", [QgsField("Hoogste Trafo", QVariant.Double)])
    clustering_options.points_layer = lambda state: source

    class Host(QWidget):
        pass

    host = Host()
    host.widgets = {}
    host.prepared_state = {
        "values": {
            "field_design_current": "Hoogste Trafo", "new_station_kva": 630.0,
            "target_utilization": 90.0, "max_route": 850.0, "node_tolerance": 1.0,
            "automatic_stations": True, "manual_station_count": 0,
            "preserve_existing_directions": False, "node_trenches": True,
            "write_shapefiles": False, "only_plan": False,
            "allow_external_routes": False, "field_multistory": "",
            "field_flat_id": "", "use_flat_cabinets": True,
        },
        "plan_gpkg": "", "clustering_dir": "/tmp",
    }
    dialog = clustering_options.ClusteringOptionsDialog(host)
    dialog.show()
    settle()
    scroll = dialog.findChild(QScrollArea)
    assert scroll is not None
    warning = next(label for label in dialog.findChildren(QLabel)
                   if "Bestaande-richtingenmodus:" in label.text())
    assert warning.wordWrap()

    for size in ((520, 720), (720, 780), (980, 800), (1180, 840)):
        dialog.resize(*size)
        settle()
        assert scroll.horizontalScrollBar().maximum() == 0, (
            "horizontal scrolling is not permitted", size, dialog.size(),
            scroll.widget().size(), scroll.viewport().size())
        assert scroll.widget().width() <= scroll.viewport().width() + 1, (size, scroll.widget().size(), scroll.viewport().size())
        assert warning.width() <= scroll.viewport().width(), (size, warning.size(), scroll.viewport().size())
        assert warning.height() >= warning.heightForWidth(warning.width()) - 3, (
            "long warning clipped", size, warning.width(), warning.height())
        assert all(button.width() >= 85 for button in dialog.findChildren(
            QWidget) if button.__class__.__name__ == "QPushButton" and
            button.text() in ("Instellingen opslaan", "Clustering starten", "Sluiten", "Berekend project herstellen")), size

    check = dialog.selected_only
    text = next(label for label in dialog.findChildren(QLabel) if getattr(label, "checkbox", None) is check)
    before = check.isChecked()
    text.show()
    settle()
    left = Qt.MouseButton.LeftButton if hasattr(Qt, "MouseButton") else Qt.LeftButton
    QTest.mouseClick(text, left)
    assert check.isChecked() != before, "clicking the wrapping checkbox label must toggle the option"
    dialog.close()


def test_scope():
    project = QgsProject.instance()
    points = make_layer("Aansluitingen Scope", [
        QgsField("Station", QVariant.String), QgsField("Ontwerp_A", QVariant.Double)])
    stations = make_layer("Bestaande stations Scope", [QgsField("Station", QVariant.String)])
    original = "#9bc7cd"
    categories = []
    for idx, name in enumerate("ABCD"):
        symbol = QgsMarkerSymbol.createSimple({"name": "circle", "size": "4.7",
                                               "color": original, "outline_color": "0,0,0"})
        categories.append(QgsRendererCategory(name, symbol, name))
        for x, y in ((idx * 35, 0), (idx * 35 + 10, 10)):
            f = QgsFeature(points.fields())
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
            f.setAttributes([name, 8.7])
            assert points.dataProvider().addFeatures([f])[0]
        station = QgsFeature(stations.fields())
        station.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(idx * 35, 20)))
        station.setAttributes([name])
        assert stations.dataProvider().addFeatures([station])[0]
    points.setRenderer(QgsCategorizedSymbolRenderer("Station", categories))
    stations.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({
        "name": "square", "size": "3.2", "color": original})))
    scope = QgsPrintLayout(project)
    scope.initializeDefaults()
    table = QgsLayoutItemLabel(scope)
    scope.addLayoutItem(table)
    table.setText(
        '<table width="100%" border="1" cellspacing="0" cellpadding="0">'
        '<tr><th></th><th>Station</th><th>Aantal</th><th>Ontwerp A</th></tr>'
        '<tr><td bgcolor="#9bc7cd">&nbsp;</td><td>A</td><td>2</td><td>17,4</td></tr>'
        '<tr><td bgcolor="#9bc7cd">&nbsp;</td><td>B</td><td>2</td><td>17,4</td></tr></table>')
    changed, colors = ensure_scope_color_contrast(project, points, stations, table)
    assert changed and len(colors) == 4
    for name, expected in colors.items():
        assert expected in [category.symbol().color().name() for category in points.renderer().categories()]
        assert table.text().count(expected) >= (1 if name in "AB" else 0)
    for a in "ABC":
        b = chr(ord(a) + 1)
        assert perceptual_distance(colors[a], colors[b]) > 37, colors
    expr = stations.renderer().symbol().symbolLayer(0).dataDefinedProperties().property(
        3).expressionString() if False else ""
    assert all(value.startswith("#") for value in colors.values())
    unchanged, _ = ensure_scope_color_contrast(project, points, stations, table)
    assert not unchanged, "migration must not reapply or overwrite later manual style"


if __name__ == "__main__":
    test_form()
    test_scope()
    print("QGIS_RESPONSIVE_SCOPE_OK (4 widths, long text, clickable controls, palette and table)", flush=True)
    sys.stdout.flush()
    os._exit(0)
