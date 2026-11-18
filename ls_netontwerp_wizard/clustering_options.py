"""Review-time clustering settings and persistent late plan-area snapshots."""
import copy
import math
from pathlib import Path
import uuid

from qgis.PyQt.QtCore import QEvent, Qt
from qgis.PyQt.QtWidgets import (QBoxLayout, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget)
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject,
    QgsVectorFileWriter, QgsVectorLayer, QgsWkbTypes)
from .workflow import WorkflowRunner
from .ui_theme import apply_theme, branded_header, role

CLUSTER_KEYS = ("field_design_current", "max_route", "new_station_kva", "target_utilization",
    "node_tolerance", "automatic_stations", "preserve_existing_directions", "manual_station_count", "node_trenches", "only_plan",
    "write_shapefiles", "field_multistory", "field_flat_id", "allow_external_routes")


def points_layer(state):
    uri = WorkflowRunner._layer(state["points_gpkg"], state.get("points_layer", Path(state["points_gpkg"]).stem))
    layer = WorkflowRunner._project_layer_by_source(uri) or QgsVectorLayer(uri, "LS-aansluitingen ontwerpstroom", "ogr")
    if not layer.isValid():
        raise ValueError("De ontwerpstroomlaag van het werkproject kan niet worden geopend.")
    return layer


def save_options(state, values, plan=None, selected_only=False):
    """Validate first, copy a chosen polygon layer, then persist the configuration."""
    source = points_layer(state)
    if source.fields().lookupField(values["field_design_current"]) < 0:
        raise ValueError("Kies een bestaande ontwerpstroomkolom.")
    for key in ("max_route", "new_station_kva", "target_utilization", "node_tolerance"):
        number = float(values[key])
        if not math.isfinite(number) or number < 0 or (key != "node_tolerance" and number <= 0):
            raise ValueError("Vul geldige grenzen en capaciteiten in.")
    if values["target_utilization"] > 100:
        raise ValueError("De voorkeursbenutting mag maximaal 100% zijn.")
    if int(values["manual_station_count"]) < 0:
        raise ValueError("Het aantal nieuwe stations mag niet negatief zijn.")
    data = copy.deepcopy(state)
    data["values"].update(values)
    if plan is None:
        data["plan_gpkg"] = ""
        data["values"].update(plan="", only_plan=False)
        for layer in QgsProject.instance().mapLayers().values():
            if layer.customProperty("LSNetontwerp/plan_layer", False):
                layer.setCustomProperty("LSNetontwerp/plan_layer", False)
    else:
        if not plan.isValid() or QgsWkbTypes.geometryType(plan.wkbType()) != QgsWkbTypes.PolygonGeometry:
            raise ValueError("Kies een geldig plangebied met vlakken.")
        if plan.isEditable():
            raise ValueError("Sla de bewerkingen van het plangebied eerst op.")
        if not plan.crs().isValid():
            raise ValueError("Stel eerst het juiste CRS voor het plangebied in QGIS in.")
        features = list(plan.selectedFeatures()) if selected_only else list(plan.getFeatures())
        if not features or any(not f.hasGeometry() or f.geometry().isEmpty() or not f.geometry().isGeosValid() for f in features):
            raise ValueError("Het gekozen plangebied of de selectie is leeg of bevat ongeldige geometrie.")
        project = QgsProject.instance()
        path = Path(state["result_dir"]) / f"02_plangebied_{uuid.uuid4().hex[:8]}.gpkg"
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName, options.layerName = "GPKG", "plangebied"
        options.onlySelectedFeatures = selected_only
        options.ct = QgsCoordinateTransform(plan.crs(), QgsCoordinateReferenceSystem("EPSG:28992"), project)
        result = QgsVectorFileWriter.writeAsVectorFormatV3(plan, str(path), project.transformContext(), options)
        if result[0] != QgsVectorFileWriter.NoError:
            raise ValueError(f"Het plangebied kon niet worden opgeslagen: {result[1]}")
        uri = WorkflowRunner._layer(path, "plangebied")
        saved = QgsVectorLayer(uri, "Plangebied", "ogr")
        if not saved.isValid() or not saved.featureCount():
            raise ValueError("Het opgeslagen plangebied is leeg of onleesbaar.")
        for layer in project.mapLayers().values():
            if layer.customProperty("LSNetontwerp/plan_layer", False):
                layer.setCustomProperty("LSNetontwerp/plan_layer", False)
        saved.setCustomProperty("LSNetontwerp/plan_layer", True)
        saved.setCustomProperty("LSNetontwerp/workflow_layer", True)
        WorkflowRunner._style_plan_area(saved)
        project.addMapLayer(saved)
        data["plan_gpkg"] = str(path)
        data["values"]["plan"] = str(path)
    data["status"] = "ontwerpstroom_controleren"
    return WorkflowRunner._write_state(data)



def _qt_constant(parent, name):
    return getattr(getattr(parent, "MouseButton", parent), name)


class _ResponsiveTextLabel(QLabel):
    """Reserve the complete wrapped height as the form's width changes."""

    def resizeEvent(self, event):
        super().resizeEvent(event)
        required = self.heightForWidth(max(1, self.width()))
        if required >= 0 and abs(self.minimumHeight() - (required + 2)) > 1:
            self.setMinimumHeight(required + 2)
            self.updateGeometry()


class _CheckDescription(_ResponsiveTextLabel):
    """A wrapping, clickable label belonging to an unchanged QCheckBox."""

    def __init__(self, checkbox):
        super().__init__(checkbox.text())
        self.checkbox = checkbox
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setCursor(Qt.CursorShape.PointingHandCursor if hasattr(Qt, "CursorShape")
                       else Qt.PointingHandCursor)
        self.setEnabled(checkbox.isEnabled())
        checkbox.installEventFilter(self)

    def eventFilter(self, watched, event):
        enabled_change = QEvent.Type.EnabledChange if hasattr(QEvent, "Type") else QEvent.EnabledChange
        if watched is self.checkbox and event.type() == enabled_change:
            self.setEnabled(self.checkbox.isEnabled())
        return super().eventFilter(watched, event)

    def mouseReleaseEvent(self, event):
        if self.isEnabled() and event.button() == _qt_constant(Qt, "LeftButton"):
            self.checkbox.click()
            event.accept()
            return
        super().mouseReleaseEvent(event)


def _wrapped_checkbox(form, checkbox):
    """Let a long option wrap without hiding or replacing its stateful checkbox."""
    label = _CheckDescription(checkbox)
    original = checkbox.text()
    checkbox.setText("")
    checkbox.setAccessibleName(original)
    label.setBuddy(checkbox)
    label.setToolTip(checkbox.toolTip())
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(7)
    row.addWidget(checkbox, 0, Qt.AlignmentFlag.AlignTop if hasattr(Qt, "AlignmentFlag") else Qt.AlignTop)
    row.addWidget(label, 1)
    form.addRow(row)
    return label


def _note(text):
    note = _ResponsiveTextLabel(text)
    note.setWordWrap(True)
    note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return note


class _ResponsivePlanRow(QWidget):
    def __init__(self, combo, choose):
        super().__init__()
        self._layout = QBoxLayout(QBoxLayout.Direction.LeftToRight if hasattr(QBoxLayout, "Direction") else QBoxLayout.LeftToRight, self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._layout.addWidget(combo, 1)
        self._layout.addWidget(choose)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._stacked = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        stacked = self.width() < 450
        if stacked != self._stacked:
            self._stacked = stacked
            direction = ("TopToBottom" if stacked else "LeftToRight")
            enum = QBoxLayout.Direction if hasattr(QBoxLayout, "Direction") else QBoxLayout
            self._layout.setDirection(getattr(enum, direction))
            self.updateGeometry()


class _ResponsiveFooter(QWidget):
    """The action buttons stay usable in one, two or four columns."""
    def __init__(self, buttons):
        super().__init__()
        self._buttons = list(buttons)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(8)
        self._columns = 0
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._reflow(960)

    def _reflow(self, width):
        columns = 4 if width >= 830 else (2 if width >= 390 else 1)
        if columns == self._columns:
            return
        self._columns = columns
        for button in self._buttons:
            self._grid.removeWidget(button)
        for index, button in enumerate(self._buttons):
            self._grid.addWidget(button, index // columns, index % columns)
        for col in range(4):
            self._grid.setColumnStretch(col, 1 if col < columns else 0)
        self._grid.invalidate()
        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow(self.width())


class ClusteringOptionsDialog(QDialog):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.start_requested = False
        self.setWindowTitle("Automatische clustering - instellingen")
        self.resize(980, 800)
        outer = QVBoxLayout(self)
        header = branded_header("Automatische clustering", "TechBase - plangebied, stroomkolom en grenzen")
        header.setFixedHeight(84)
        outer.addWidget(header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        root = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        self.values = copy.deepcopy(host.prepared_state["values"])
        # Advanced edits made after step 1 must participate in this round too.
        for key in CLUSTER_KEYS:
            widget = host.widgets.get(key)
            if hasattr(widget, "isChecked"):
                self.values[key] = widget.isChecked()
            elif hasattr(widget, "value"):
                self.values[key] = widget.value()
            elif widget is not None:
                self.values[key] = widget.text().strip()
        source = points_layer(host.prepared_state)
        group = QGroupBox("Invoer en plangebied")
        form = QFormLayout(group)
        form.addRow("Aansluitingen", QLabel(source.name()))
        self.current_field = QComboBox()
        self.current_field.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.current_field.setMinimumContentsLength(12)
        self.current_field.addItems([field.name() for field in source.fields()])
        index = self.current_field.findText(self.values.get("field_design_current", "Hoogste Trafo"))
        self.current_field.setCurrentIndex(index)
        form.addRow("Ontwerpstroomkolom (A)", self.current_field)
        self.plan_combo = QComboBox()
        self.plan_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.plan_combo.setMinimumContentsLength(12)
        self.plan_combo.addItem("Geen plangebied", None)
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and QgsWkbTypes.geometryType(layer.wkbType()) == QgsWkbTypes.PolygonGeometry:
                self.plan_combo.addItem(layer.name(), layer.id())
                if layer.customProperty("LSNetontwerp/plan_layer", False):
                    self.plan_combo.setCurrentIndex(self.plan_combo.count() - 1)
        if host.prepared_state.get("plan_gpkg") and self.plan_combo.currentData() is None:
            saved = QgsVectorLayer(WorkflowRunner._layer(host.prepared_state["plan_gpkg"], "plangebied"), "Plangebied (opgeslagen)", "ogr")
            if saved.isValid():
                QgsProject.instance().addMapLayer(saved)
                self.plan_combo.addItem(saved.name(), saved.id())
                self.plan_combo.setCurrentIndex(self.plan_combo.count() - 1)
        load = QPushButton("Plangebied uit bestand toevoegen")
        load.clicked.connect(self.load_plan)
        form.addRow("Plangebied", _ResponsivePlanRow(self.plan_combo, load))
        self.selected_only = QCheckBox("Alleen geselecteerde vlakken van het plangebied gebruiken")
        self.only_plan = QCheckBox("Alleen aansluitingen en stations binnen het plangebied clusteren")
        self.only_plan.setChecked(bool(self.values.get("only_plan")))
        self.plan_combo.currentIndexChanged.connect(lambda: self.only_plan.setChecked(self.plan_combo.currentData() is not None))
        _wrapped_checkbox(form, self.selected_only)
        _wrapped_checkbox(form, self.only_plan)
        self.allow_external_routes = QCheckBox("Kabels buiten het plangebied gebruiken om aansluitingen binnen het plangebied te bereiken")
        self.allow_external_routes.setChecked(bool(self.values.get("allow_external_routes", False)))
        self.allow_external_routes.setEnabled(self.plan_combo.currentData() is not None)
        self.plan_combo.currentIndexChanged.connect(lambda: self.allow_external_routes.setEnabled(self.plan_combo.currentData() is not None))
        self.allow_external_routes.setToolTip("De volledige kabelroute telt mee voor de maximale routelengte. Clustergebieden en nieuwe stations blijven binnen het plangebied.")
        _wrapped_checkbox(form, self.allow_external_routes)
        form.addRow(_note("Een gekozen plangebied wordt bij opslaan in het werkproject vastgelegd. Je kunt een eerder zonder plangebied gemaakte invoer daarmee alsnog begrenzen."))
        root.addWidget(group)
        group = QGroupBox("Capaciteiten en grenzen")
        form = QFormLayout(group)
        self.numbers = {}
        for key, label, minimum, maximum in (
            ("new_station_kva", "Nieuw station (kVA)", 1, 5000),
            ("target_utilization", "Voorkeursbenutting (%)", 1, 100),
            ("max_route", "Maximale kabelroute (m)", 1, 10000),
            ("node_tolerance", "Knooptolerantie (m)", 0, 25)):
            spin = QDoubleSpinBox()
            spin.setDecimals(2)
            spin.setRange(minimum, maximum)
            spin.setValue(self.values[key])
            self.numbers[key] = spin
            form.addRow(label, spin)
        self.automatic = QCheckBox("Aantal nieuwe stations automatisch bepalen")
        self.automatic.setChecked(self.values["automatic_stations"])
        self.count = QSpinBox()
        self.count.setRange(0, 100)
        self.count.setValue(self.values["manual_station_count"])
        self.count.setEnabled(not self.automatic.isChecked())
        self.automatic.toggled.connect(lambda checked: self.count.setEnabled(not checked))
        _wrapped_checkbox(form, self.automatic)
        self.preserve_existing = QCheckBox(
            "Behoud originele bestaande stations en kabelrichtingen (-00/-01/-02/...)"
        )
        self.preserve_existing.setChecked(
            self.values.get("preserve_existing_directions", False)
        )
        self.preserve_existing.setEnabled(self.automatic.isChecked())
        self.automatic.toggled.connect(
            lambda checked:self.preserve_existing.setEnabled(checked)
        )
        self.preserve_existing.setToolTip(
            "Controleer trafo, kabeltypen en gG per originele Kabel Subgroep. "
            "Bestaande stations mogen alleen hun eigen oorspronkelijke aansluitingen "
            "behouden. Afgevallen aansluitingen gaan uitsluitend naar nieuwe stations. "
            "Vereist echte GEN-kabellijnen met Type en Kabel Subgroep."
        )
        _wrapped_checkbox(form, self.preserve_existing)
        form.addRow(_note(
            "Bestaande-richtingenmodus: de werkelijke gG-afzekering moet "
            "worden gecontroleerd; zonder bevestigde gG is het "
            "kabelchecker-resultaat alleen een maximaal haalbaar advies. "
            "Vrijgegeven kabelpunten zonder fysiek gescheiden nieuwe route "
            "leveren een controlefout op, nooit een fictieve verbinding."
        ))
        form.addRow("Handmatig aantal nieuwe stations", self.count)
        form.addRow(_note("Kabelroute en trafocapaciteit zijn harde grenzen. Voorkeursbenutting stuurt de stationskeuze. Capaciteiten van bestaande stations pas je aan bij 2c. Stations aanpassen."))
        root.addWidget(group)
        group = QGroupBox("Netwerk")
        form = QFormLayout(group)
        self.node = QCheckBox("Kabels knippen en noden")
        self.node.setChecked(self.values["node_trenches"])
        self.flat = QCheckBox("Appartementen koppelen via flatkasten en BAG")
        self.flat.setChecked(self.values.get("use_flat_cabinets", True))
        self.shapes = QCheckBox("Ook losse shapefiles schrijven")
        self.shapes.setChecked(self.values["write_shapefiles"])
        for widget in (self.node, self.flat, self.shapes):
            _wrapped_checkbox(form, widget)
        root.addWidget(group)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        save = QPushButton("Instellingen opslaan")
        save.clicked.connect(self.save)
        start = QPushButton("Clustering starten")
        start.clicked.connect(self.start)
        close = QPushButton("Sluiten")
        close.clicked.connect(self.reject)
        recover = QPushButton("Berekend project herstellen")
        recover.clicked.connect(self.recover)
        recover.setEnabled((Path(host.prepared_state["clustering_dir"]) / "clustering_ontwerp.gpkg").exists())
        outer.addWidget(_ResponsiveFooter((save, start, recover, close)))
        for label in self.findChildren(QLabel):
            if label.wordWrap():
                label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._forms = self.findChildren(QFormLayout)
        for form in self._forms:
            policy = QFormLayout.FieldGrowthPolicy if hasattr(QFormLayout, "FieldGrowthPolicy") else QFormLayout
            form.setFieldGrowthPolicy(policy.AllNonFixedFieldsGrow)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff if hasattr(Qt, "ScrollBarPolicy") else Qt.ScrollBarAlwaysOff)
        apply_theme(self)
        self._update_responsive_forms()

        role(start, "primary")
        role(save, "secondary")

    def _update_responsive_forms(self):
        # A narrow window gets one field per row; wide windows keep compact labels.
        if not hasattr(self, "_forms"):
            return
        policy = QFormLayout.RowWrapPolicy if hasattr(QFormLayout, "RowWrapPolicy") else QFormLayout
        mode = policy.WrapAllRows if self.width() < 790 else policy.WrapLongRows
        for form in self._forms:
            if form.rowWrapPolicy() != mode:
                form.setRowWrapPolicy(mode)
                form.invalidate()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_responsive_forms()

    def load_plan(self):
        path, _ = QFileDialog.getOpenFileName(self, "Plangebied toevoegen", "", "Vectorlagen (*.gpkg *.shp *.geojson *.json);;Alle bestanden (*)")
        if not path:
            return
        layer = QgsVectorLayer(path, Path(path).stem, "ogr")
        if not layer.isValid() or QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.PolygonGeometry:
            self.status.setText("Kies een geldige polygonenlaag, of laad de gewenste laag eerst in QGIS.")
            return
        QgsProject.instance().addMapLayer(layer)
        self.plan_combo.addItem(layer.name(), layer.id())
        self.plan_combo.setCurrentIndex(self.plan_combo.count() - 1)

    def save(self):
        try:
            values = dict(self.values)
            values.update({key: spin.value() for key, spin in self.numbers.items()})
            values.update(field_design_current=self.current_field.currentText(), only_plan=self.only_plan.isChecked(),
                allow_external_routes=self.allow_external_routes.isChecked(),
                automatic_stations=self.automatic.isChecked(),
                preserve_existing_directions=self.preserve_existing.isChecked(),
                manual_station_count=self.count.value(),
                node_trenches=self.node.isChecked(), use_flat_cabinets=self.flat.isChecked(), write_shapefiles=self.shapes.isChecked())
            plan = QgsProject.instance().mapLayer(self.plan_combo.currentData())
            self.host.prepared_state = save_options(self.host.prepared_state, values, plan, self.selected_only.isChecked())
            for key in CLUSTER_KEYS:
                widget = self.host.widgets.get(key)
                if hasattr(widget, "setChecked"):
                    widget.setChecked(values[key])
                elif hasattr(widget, "setValue"):
                    widget.setValue(values[key])
                elif widget is not None:
                    widget.setText(str(values[key]))
            self.host.no_plan.setChecked(plan is None)
            self.host.plan_edit.setText(self.host.prepared_state["values"].get("plan", ""))
            self.status.setText("Clusteringinstellingen en plangebied opgeslagen in het werkproject.")
            return True
        except Exception as exc:
            self.status.setText(str(exc))
            return False

    def start(self):
        if self.save():
            self.start_requested = True
            self.accept()

    def recover(self):
        try:
            update = self.host._make_progress("Berekend project herstellen...")
            path = WorkflowRunner(self.host.prepared_state["values"], update).recover_project(self.host.prepared_state)
            self.status.setText(f"QGIS-project hersteld: {path}")
            self.accept()
        except Exception as exc:
            self.status.setText(str(exc))
        finally:
            self.host._finish_progress()
