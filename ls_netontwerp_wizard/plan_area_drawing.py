"""Draw a persistent plan polygon directly on the QGIS map."""

from pathlib import Path
from datetime import datetime
from uuid import uuid4

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QPushButton
from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsFeature, QgsFillSymbol, QgsGeometry, QgsPointXY, QgsProject,
    QgsVectorFileWriter, QgsVectorLayer, QgsWkbTypes,
)
from qgis.gui import QgsMapTool, QgsRubberBand


class PlanAreaMapTool(QgsMapTool):
    completed = pyqtSignal(QgsGeometry)
    cancelled = pyqtSignal()
    problem = pyqtSignal(str)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.points = []
        self.band = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        self.band.setColor(QColor(244, 119, 0, 60))
        self.band.setStrokeColor(QColor(244, 119, 0))
        self.band.setWidth(2)
        self.setCursor(Qt.CursorShape.CrossCursor if hasattr(Qt, "CursorShape") else Qt.CrossCursor)

    def _preview(self, point=None):
        ring = list(self.points)
        if point is not None:
            ring.append(point)
        self.band.reset(QgsWkbTypes.PolygonGeometry)
        for vertex in ring:
            self.band.addPoint(vertex, False)
        self.band.show()
        self.band.updatePosition()

    def canvasReleaseEvent(self, event):
        buttons = Qt.MouseButton if hasattr(Qt, "MouseButton") else Qt
        if event.button() == buttons.RightButton:
            self.finish()
        elif event.button() == buttons.LeftButton:
            point = QgsPointXY(self.toMapCoordinates(event.pos()))
            if not self.points or point != self.points[-1]:
                self.points.append(point)
            self._preview()

    def canvasMoveEvent(self, event):
        if self.points:
            self._preview(QgsPointXY(self.toMapCoordinates(event.pos())))

    def keyPressEvent(self, event):
        keys = Qt.Key if hasattr(Qt, "Key") else Qt
        if event.key() == keys.Key_Escape:
            self.cancelled.emit()
        elif event.key() in (keys.Key_Backspace, keys.Key_Delete):
            if self.points:
                self.points.pop()
                self._preview()
        elif event.key() in (keys.Key_Return, keys.Key_Enter):
            self.finish()

    def finish(self):
        if len({(p.x(), p.y()) for p in self.points}) < 3:
            self.problem.emit("Klik minimaal drie verschillende hoekpunten. Backspace wist het laatste punt.")
            return
        geometry = QgsGeometry.fromPolygonXY([self.points + [self.points[0]]])
        if geometry.isEmpty() or not geometry.isGeosValid() or geometry.area() <= 0:
            self.problem.emit("De grens kruist zichzelf of heeft geen oppervlakte. Gebruik Backspace om punten te corrigeren.")
            return
        self.completed.emit(geometry)

    def dispose(self):
        if self.band is not None:
            self.canvas().scene().removeItem(self.band)
            self.band = None


def save_plan_area(geometry, source_crs, output_directory=""):
    """Save one polygon as a new RD GeoPackage; never overwrite an existing file."""
    if not source_crs.isValid():
        raise ValueError("De kaart heeft geen geldig coördinatenstelsel.")
    geometry = QgsGeometry(geometry)
    target = QgsCoordinateReferenceSystem("EPSG:28992")
    if source_crs != target:
        geometry.transform(QgsCoordinateTransform(source_crs, target, QgsProject.instance()))
    if geometry.isEmpty() or not geometry.isGeosValid() or geometry.area() <= 0:
        raise ValueError("Het getekende plangebied is geen geldig vlak.")
    directory = (Path(output_directory) if output_directory else
                 Path(QgsApplication.qgisSettingsDirPath()) / "ls_netontwerp_plangebieden")
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"plangebied_getekend_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:8]}.gpkg"
    path = directory / filename
    memory = QgsVectorLayer("Polygon?crs=EPSG:28992", "Plangebied (getekend)", "memory")
    feature = QgsFeature(memory.fields())
    feature.setGeometry(geometry)
    if not memory.dataProvider().addFeatures([feature])[0]:
        raise ValueError("Het getekende vlak kon niet aan de plangebiedlaag worden toegevoegd.")
    memory.updateExtents()
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = "plangebied"
    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        memory, str(path), QgsProject.instance().transformContext(), options,
    )
    if result[0] != QgsVectorFileWriter.NoError:
        raise ValueError(f"Plangebied opslaan mislukt: {result[1]}")
    layer = QgsVectorLayer(f"{path}|layername=plangebied", "Plangebied (getekend)", "ogr")
    if not layer.isValid() or layer.featureCount() != 1:
        raise ValueError("De opgeslagen plangebiedlaag kon niet worden geopend.")
    layer.renderer().setSymbol(QgsFillSymbol.createSimple({
        "color": "244,119,0,30", "outline_color": "244,119,0,255", "outline_width": "0.6",
    }))
    return layer, str(path)


class PlanAreaDrawingSession:
    INSTRUCTIONS = "Klik de hoekpunten op de kaart. Rechtsklik of Enter: afronden. Backspace: punt wissen. Esc: annuleren."

    def __init__(self, host):
        self.host = host
        self.canvas = host.iface.mapCanvas()
        self.source_crs = self.canvas.mapSettings().destinationCrs()
        self.previous_tool = self.canvas.mapTool()
        self.tool = PlanAreaMapTool(self.canvas)
        self.message = host.iface.messageBar().createMessage("Plangebied tekenen", self.INSTRUCTIONS)
        finish = QPushButton("Afronden")
        finish.clicked.connect(self.tool.finish)
        cancel = QPushButton("Annuleren")
        cancel.clicked.connect(self.cancel)
        self.message.layout().addWidget(finish)
        self.message.layout().addWidget(cancel)
        self.tool.completed.connect(self.complete)
        self.tool.cancelled.connect(self.cancel)
        self.tool.problem.connect(self.message.setText)
        self.tool.deactivated.connect(self.cancel)
        self.active = True

    def start(self):
        self.host.hide()
        self.host.iface.messageBar().pushWidget(self.message, duration=0)
        self.canvas.setMapTool(self.tool)
        self.canvas.setFocus()

    def complete(self, geometry):
        try:
            layer, path = save_plan_area(geometry, self.source_crs, self.host.output_edit.text().strip())
        except Exception as exc:
            self.message.setText(str(exc))
            return
        QgsProject.instance().addMapLayer(layer)
        self.host.plan_edit.setText(path)
        self.host.no_plan.setChecked(False)
        self.host.widgets["only_plan"].setChecked(True)
        self.host.iface.setActiveLayer(layer)
        self.cancel()
        self.host.iface.messageBar().pushSuccess("Plangebied aangemaakt", "De getekende laag is opgeslagen en als plangebied ingevuld.")

    def cancel(self, *_args, restore_window=True):
        if not self.active:
            return
        self.active = False
        if self.canvas.mapTool() == self.tool:
            if self.previous_tool is not None:
                self.canvas.setMapTool(self.previous_tool)
            else:
                self.canvas.unsetMapTool(self.tool)
        self.tool.dispose()
        self.tool.deleteLater()
        self.host.iface.messageBar().popWidget(self.message)
        self.host._plan_draw_session = None
        if restore_window:
            self.host.show()
            self.host.raise_()
            self.host.activateWindow()
