"""Integrated station and new-construction controls."""
from qgis.PyQt.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget, QLineEdit, QSpinBox,
)
from qgis.core import QgsApplication, QgsProject, QgsWkbTypes

from .algorithms.woningtype_selectie_herberekenen_tool import HOUSING_CHOICES
from .connection_sources import add_selected_objects, assign_station, pdok_objects_layer, text_value


class ConnectionSourcesPage(QWidget):
    def __init__(self, host, mode="newbouw"):
        super().__init__(host)
        self.host = host
        self.mode = mode
        self._bag_download = None
        self._download_project_active = False
        QgsProject.instance().cleared.connect(self.cancel_bag_download)
        outer = QVBoxLayout(self)
        title = "Stationskoppeling" if mode == "stations" else "Nieuwbouw — BAG of zelf aansluitpunten plaatsen"
        host._add_subpage_header(outer, title, "TechBase • invoer en ontwerpstroom aanvullen")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        root = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        note = QLabel("Haal aansluitingen uit LOVION op voor gekozen stations, koppel een CSV of wijzig een stationsnummer. "
                      "Aansluitingen krijgen een kleur per station." if mode == "stations" else
                      "Laad de BAG-verblijfsobjecten, selecteer de gewenste adressen op de kaart en voeg ze toe. "
                      "Bij woonfunctie volgen woningtype en ontwerpstroom het bijbehorende pand. "
                      "Andere gebruiksdoelen worden na toevoegen getoond in 'Nulwaarden herstellen', "
                      "waar je zelf de categorie en stroomwaarden kiest.")
        note.setWordWrap(True)
        root.addWidget(note)
        refresh = QPushButton("Lagen vernieuwen")
        refresh.clicked.connect(self.refresh)
        root.addWidget(refresh)
        target_group = QGroupBox("Aansluitingen")
        form = QFormLayout(target_group)
        self.target_combo = QComboBox()
        form.addRow("Ontwerpstroomlaag", self.target_combo)
        root.addWidget(target_group)

        self.lovion_panel = None
        if mode == "stations":
            from .lovion_panel import LovionStationPanel
            self.lovion_panel = LovionStationPanel(self)
            root.addWidget(self.lovion_panel)
        station_group = QGroupBox("CSV of handmatige stationskoppeling")
        form = QFormLayout(station_group)
        csv = QPushButton("LOVION CSV koppelen (Master Asset ID → Station)")
        csv.clicked.connect(self.import_csv)
        form.addRow(csv)
        self.station_combo = QComboBox()
        self.station_combo.setEditable(True)
        if mode == "stations":
            form.addRow("Stationsnummer", self.station_combo)
        row = QHBoxLayout()
        select = QPushButton("Aansluitingen op kaart selecteren")
        select.clicked.connect(lambda: self.select_on_map(self.target_combo))
        apply = QPushButton("Stationsnummer wijzigen voor selectie")
        apply.clicked.connect(self.apply_station)
        row.addWidget(select)
        row.addWidget(apply)
        form.addRow(row)
        root.addWidget(station_group)
        self.station_group = station_group
        station_group.setVisible(mode == "stations")

        bag_group = QGroupBox("Nieuwbouw uit BAG-verblijfsobjecten")
        form = QFormLayout(bag_group)
        if mode != "stations":
            form.addRow("Stationsnummer voor nieuwe adressen", self.station_combo)
        row = QHBoxLayout()
        self.bag_server_button = QPushButton("BAG-serververbinding")
        self.bag_server_button.clicked.connect(self.load_bag)
        self.bag_download_button = QPushButton("BAG downloaden (kaartuitsnede)")
        self.bag_download_button.clicked.connect(self.download_bag)
        row.addWidget(self.bag_server_button)
        row.addWidget(self.bag_download_button)
        form.addRow(row)
        hint = QLabel("Download maakt een lokale laag van de huidige kaartuitsnede. Deze blijft na het downloaden zonder serververbinding bruikbaar.")
        hint.setWordWrap(True)
        form.addRow(hint)
        self.source_combo, self.housing_combo = QComboBox(), QComboBox()
        form.addRow("Verblijfsobjectenlaag", self.source_combo)
        form.addRow("Panden met woningtypen", self.housing_combo)
        self.type_combo = QComboBox()
        self.type_combo.addItem("Nog niet bekend — later invullen", None)
        for label, stored in HOUSING_CHOICES:
            self.type_combo.addItem(label, stored)
        form.addRow("Woningtype als het pand geen type heeft", self.type_combo)
        self.manual = QCheckBox("Onderstaande stroom gebruiken als woonfunctie geen ontwerpstroom oplevert")
        form.addRow(self.manual)
        self.currents = []
        for label in ("Trafoverbruik (A)", "Kabelverbruik (A)", "Trafo-opwek (A)", "Kabelopwek (A)"):
            spin = QDoubleSpinBox()
            spin.setRange(0, 1000000)
            spin.setDecimals(2)
            spin.setEnabled(False)
            self.manual.toggled.connect(spin.setEnabled)
            self.currents.append(spin)
            form.addRow(label, spin)
        self.skip_existing = QCheckBox("Bestaande BAG-objecten en adressen overslaan")
        self.skip_existing.setChecked(False)
        form.addRow(self.skip_existing)
        row = QHBoxLayout()
        select = QPushButton("Verblijfsobjecten op kaart selecteren")
        select.clicked.connect(lambda: self.select_on_map(self.source_combo))
        add = QPushButton("Geselecteerde verblijfsobjecten toevoegen")
        add.clicked.connect(self.add_objects)
        row.addWidget(select)
        row.addWidget(add)
        form.addRow(row)
        root.addWidget(bag_group)
        self.bag_group = bag_group
        bag_group.setVisible(mode != "stations")
        self.manual_build_group = QGroupBox("Zelf nieuwbouwaansluitingen plaatsen — zonder BAG")
        manual_form = QFormLayout(self.manual_build_group)
        explanation = QLabel("Plaats één bolletje per toekomstige aansluiting. Er is geen BAG-object nodig. "
                             "De punten worden toegevoegd aan de ontwerpstroomlaag en blijven herkenbaar als "
                             "handmatig geplande nieuwbouw. Voer daarna stap 3 opnieuw uit om ze te clusteren; "
                             "een bestaand clusterresultaat wordt niet automatisch aangepast.")
        explanation.setWordWrap(True)
        manual_form.addRow(explanation)
        self.manual_label = QLineEdit()
        manual_form.addRow("Project / toelichting", self.manual_label)
        self.manual_usage = QComboBox()
        for label, stored in (("Woning", "woonfunctie"), ("Zakelijk / overig", "overige gebruiksfunctie"),
                              ("Oplaadpunt", "oplaadpunt"), ("Straatmeubilair", "straatmeubilair")):
            self.manual_usage.addItem(label, stored)
        manual_form.addRow("Gebruiksdoel", self.manual_usage)
        self.manual_year = QSpinBox()
        self.manual_year.setRange(2022, 2200)
        from qgis.PyQt.QtCore import QDate
        self.manual_year.setValue(QDate.currentDate().year())
        manual_form.addRow("Gepland bouwjaar", self.manual_year)
        self.manual_passthrough = QLineEdit("3 x 25 A")
        manual_form.addRow("Geplande aansluitwaarde", self.manual_passthrough)
        self.manual_housing = QComboBox()
        self.manual_housing.addItem("Kies een woningtype", None)
        for label, stored in HOUSING_CHOICES:
            self.manual_housing.addItem(label, stored)
        manual_form.addRow("Woningtype", self.manual_housing)
        self.manual_current_mode = QComboBox()
        self.manual_current_mode.addItem("Uit woningtype berekenen (nieuwbouwtabellen)", "housing")
        self.manual_current_mode.addItem("Vier stroomwaarden handmatig invullen", "manual")
        self.manual_current_mode.addItem("Later bepalen — 0 A, controle nodig", "later")
        manual_form.addRow("Ontwerpstroom", self.manual_current_mode)
        self.manual_build_currents = []
        for label in ("Trafoverbruik (A)", "Kabelverbruik (A)", "Trafo-opwek (A)", "Kabelopwek (A)"):
            spin = QDoubleSpinBox()
            spin.setRange(0, 1000000)
            spin.setDecimals(3)
            spin.setEnabled(False)
            self.manual_build_currents.append(spin)
            manual_form.addRow(label, spin)
        self.manual_current_mode.currentIndexChanged.connect(lambda *_: [
            spin.setEnabled(self.manual_current_mode.currentData() == "manual") for spin in self.manual_build_currents])
        self.manual_points_status = QLabel("Nog geen aansluitpunten klaargezet.")
        self.manual_points_status.setWordWrap(True)
        manual_form.addRow(self.manual_points_status)
        self._manual_points = []
        self._manual_markers = []
        self._manual_tool = None
        self._manual_previous_tool = None
        self._manual_target = None
        self._manual_target_crs = None
        for label, callback in (("Aansluitbolletjes op kaart plaatsen", self.start_manual_points),
                                ("Laatste klaargezette punt verwijderen", self.remove_manual_point),
                                ("Klaargezette punten wissen", self.clear_manual_points),
                                ("Nieuwbouwaansluitingen toevoegen", self.add_manual_points),
                                ("Laatste handmatige toevoeging ongedaan maken", self.undo_manual_addition)):
            button = QPushButton(label)
            button.setProperty("uiExplicitRole", "primary" if callback == self.add_manual_points else
                               "map" if callback == self.start_manual_points else "secondary")
            button.clicked.connect(callback)
            manual_form.addRow(button)
        root.addWidget(self.manual_build_group)
        self.manual_build_group.setVisible(mode != "stations")
        host.finished.connect(lambda *_: self.clear_manual_points())
        QgsProject.instance().cleared.connect(self.clear_manual_points)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        root.addStretch(1)

    def layer(self, combo):
        return QgsProject.instance().mapLayer(combo.currentData())

    def _finish_manual_points(self, restore=True):
        if self._manual_tool is not None and self.host.iface is not None:
            canvas = self.host.iface.mapCanvas()
            if canvas.mapTool() is self._manual_tool:
                if self._manual_previous_tool is not None:
                    canvas.setMapTool(self._manual_previous_tool)
                else:
                    canvas.unsetMapTool(self._manual_tool)
        self._manual_tool = self._manual_previous_tool = None
        if restore:
            self.host.show()
            self.host.raise_()
            self.host.activateWindow()

    def start_manual_points(self):
        try:
            target = self.layer(self.target_combo)
            if target is None:
                raise ValueError("Open eerst het werkproject met de ontwerpstroomlaag uit stap 1.")
            if target.isEditable():
                raise ValueError("Sla bestaande laagbewerkingen eerst op.")
            if self.host.iface is None:
                raise ValueError("Aansluitpunten plaatsen kan alleen op de kaart in QGIS Desktop.")
            if self._manual_tool is not None:
                return
            if self._manual_points and target.id() != self._manual_target:
                raise ValueError("Wis eerst de klaargezette punten voordat je een andere doellaag kiest.")
            from .manual_newbuild import NewBuildPointTool
            self._manual_target = target.id()
            self._manual_target_crs = target.crs()
            canvas = self.host.iface.mapCanvas()
            self._manual_previous_tool = canvas.mapTool()
            self._manual_tool = NewBuildPointTool(canvas, self._manual_point_clicked,
                                                  self._finish_manual_points, self._cancel_manual_drawing)
            canvas.setMapTool(self._manual_tool)
            self.manual_points_status.setText("Klik één keer per aansluiting. Rechtsklik of Enter sluit de kaartkeuze; Esc annuleert de klaargezette punten.")
            self.host.hide()
        except Exception as exc:
            self.status.setText(str(exc))

    def _manual_point_clicked(self, point):
        try:
            from qgis.core import QgsCoordinateTransform
            from qgis.gui import QgsVertexMarker
            from qgis.PyQt.QtGui import QColor
            canvas = self.host.iface.mapCanvas()
            transform = QgsCoordinateTransform(canvas.mapSettings().destinationCrs(), self._manual_target_crs, QgsProject.instance())
            self._manual_points.append(transform.transform(point))
            marker = QgsVertexMarker(canvas)
            marker.setCenter(point)
            marker.setIconType(QgsVertexMarker.ICON_CIRCLE)
            marker.setIconSize(10)
            marker.setColor(QColor('#cc4b00'))
            marker.setFillColor(QColor('#ff8b26'))
            self._manual_markers.append(marker)
            self.manual_points_status.setText(f"{len(self._manual_points)} aansluitpunten klaargezet, nog niet opgeslagen. Rechtsklik of Enter om terug te keren.")
        except Exception as exc:
            self.status.setText(str(exc))
            self._finish_manual_points()

    def _cancel_manual_drawing(self):
        self._finish_manual_points()
        self.clear_manual_points()
        self.manual_points_status.setText("Kaartkeuze geannuleerd; geen aansluitingen toegevoegd.")

    def remove_manual_point(self):
        if self._manual_points:
            self._manual_points.pop()
        if self._manual_markers:
            marker = self._manual_markers.pop()
            try:
                if marker.scene() is not None:
                    marker.scene().removeItem(marker)
            except RuntimeError:
                pass
        self.manual_points_status.setText(f"{len(self._manual_points)} aansluitpunten klaargezet.")

    def clear_manual_points(self):
        self._finish_manual_points(False)
        while self._manual_points or self._manual_markers:
            self.remove_manual_point()
        self._manual_target = self._manual_target_crs = None
        self.manual_points_status.setText("Nog geen aansluitpunten klaargezet.")

    def add_manual_points(self):
        try:
            from .manual_newbuild import add_manual_connections
            target = self.layer(self.target_combo)
            if target is None or target.id() != self._manual_target:
                raise ValueError("Kies de oorspronkelijke doellaag of plaats de punten opnieuw.")
            result = add_manual_connections(target, self._manual_points, self._manual_target_crs,
                self.host.zero_current_page, label=self.manual_label.text(),
                station=self.station_combo.currentText(), house_type=self.manual_housing.currentData(),
                year=self.manual_year.value(), usage=self.manual_usage.currentData(),
                passthrough=self.manual_passthrough.text(), mode=self.manual_current_mode.currentData(),
                currents=[spin.value() for spin in self.manual_build_currents])
            self.clear_manual_points()
            self.host._refresh_zero_current_count()
            self.status.setText(f"{result['added']} handmatige nieuwbouwaansluitingen opgeslagen; {result['missing']} nog zonder ontwerpstroom. "
                                "De nieuwe punten zijn geselecteerd. Voer stap 3 opnieuw uit om ze mee te clusteren.")
            if self.host.iface is not None:
                self.host.iface.mapCanvas().refresh()
        except Exception as exc:
            self.status.setText(str(exc))

    def undo_manual_addition(self):
        try:
            from .manual_newbuild import undo_manual_connections
            count = undo_manual_connections(self.layer(self.target_combo))
            self.host._refresh_zero_current_count()
            self.status.setText(f"De laatste {count} handmatig toegevoegde aansluitingen zijn teruggedraaid. Bereken een bestaand clusterresultaat zo nodig opnieuw.")
        except Exception as exc:
            self.status.setText(str(exc))

    def refresh(self):
        if self.lovion_panel and self.lovion_panel.worker:
            return
        previous = [combo.currentData() for combo in (self.target_combo, self.source_combo, self.housing_combo)]
        for combo in (self.target_combo, self.source_combo, self.housing_combo):
            combo.clear()
        self.housing_combo.addItem("Geen pandenlaag — handmatig aanvullen", None)
        for layer in QgsProject.instance().mapLayers().values():
            if not hasattr(layer, "fields"):
                continue
            names = {field.name() for field in layer.fields()}
            kind = QgsWkbTypes.geometryType(layer.wkbType())
            if kind == QgsWkbTypes.PointGeometry:
                if "Hoogste Trafo" in names and (layer.customProperty("LSNetontwerp/review_current_layer", False)
                                                  or layer.name() == "LS-aansluitingen ontwerpstroom"):
                    self.target_combo.addItem(layer.name(), layer.id())
                if "identificatie" in names and "huisnummer" in names:
                    self.source_combo.addItem(layer.name(), layer.id())
            elif kind == QgsWkbTypes.PolygonGeometry and self.host._workflow_field_defaults().get("field_building_type", "Woningtype") in names:
                self.housing_combo.addItem(layer.name(), layer.id())
        if not self.target_combo.count():
            # A finished cluster project normally omits the original review
            # layer. Reopen its persisted source when the workflow is known.
            state = self.host.prepared_state or {}
            if state.get('points_gpkg'):
                from pathlib import Path
                from qgis.core import QgsVectorLayer
                path = Path(state['points_gpkg'])
                if path.is_file():
                    name = state.get('points_layer', path.stem)
                    layer = QgsVectorLayer(f'{path}|layername={name}', 'LS-aansluitingen ontwerpstroom', 'ogr')
                    if layer.isValid() and layer.fields().lookupField('Hoogste Trafo') >= 0:
                        layer.setCustomProperty('LSNetontwerp/review_current_layer', True)
                        QgsProject.instance().addMapLayer(layer)
                        self.target_combo.addItem(layer.name(), layer.id())
        for combo, old in zip((self.target_combo, self.source_combo, self.housing_combo), previous):
            index = combo.findData(old)
            if index >= 0 and old is not None:
                combo.setCurrentIndex(index)
        if previous[2] is None and self.housing_combo.count() > 1:
            self.housing_combo.setCurrentIndex(1)
        current = self.station_combo.currentText()
        stations = set()
        for layer in QgsProject.instance().mapLayers().values():
            if hasattr(layer, "fields") and layer.fields().lookupField("Station") >= 0:
                stations.update(text_value(f, "Station") for f in layer.getFeatures())
        self.station_combo.clear()
        self.station_combo.addItem("")
        self.station_combo.addItems(sorted(stations - {""}))
        self.station_combo.setCurrentText(current)
        if self.lovion_panel:
            self.lovion_panel.refresh()

    def select_on_map(self, combo):
        layer = self.layer(combo)
        if layer is None:
            self.status.setText("Kies eerst de laag die je wilt selecteren.")
            return
        if self.host.iface is not None:
            if hasattr(self.host, "_start_submenu_map_selection"):
                self.host._start_submenu_map_selection(
                    self, layer,
                    lambda: self.status.setText(f"{layer.selectedFeatureCount()} objecten geselecteerd."),
                    self.status, "Selecteer de gewenste objecten op de kaart.",
                )
                return
            self.host.iface.setActiveLayer(layer)
            self.host.iface.actionSelect().trigger()
            self.host.hide()

    def import_csv(self):
        self.host.open_station_names_csv(target_layer=self.layer(self.target_combo))
        self.refresh()

    def apply_station(self):
        try:
            layer = self.layer(self.target_combo)
            if layer is None:
                raise ValueError("Kies de ontwerpstroomlaag.")
            count = assign_station(layer, self.station_combo.currentText())
            self.status.setText(f"Stationsnummer opgeslagen voor {count} geselecteerde aansluitingen.")
        except Exception as exc:
            self.status.setText(str(exc))

    def load_bag(self):
        self.status.setText("PDOK-verblijfsobjecten laden…")
        try:
            layer = pdok_objects_layer(self.host._workflow_field_defaults().get("bag_api_url", "https://api.pdok.nl/kadaster/bag/ogc/v2"))
            QgsProject.instance().addMapLayer(layer)
            self.refresh()
            self.source_combo.setCurrentIndex(self.source_combo.findData(layer.id()))
            if self.host.iface is not None:
                self.host.iface.setActiveLayer(layer)
            self.status.setText("BAG-laag geladen. Zoom naar de nieuwbouw en selecteer de gewenste verblijfsobjecten.")
        except Exception as exc:
            self.status.setText(str(exc))

    def download_bag(self):
        if self._bag_download:
            self._bag_download.cancel()
            self.status.setText("BAG-download wordt gestopt.")
            return
        try:
            from .bag_download import BagDownloadTask, download_path, map_bbox
            if self.host.iface is None:
                raise ValueError("Open het QGIS-project en zoom naar het gewenste downloadgebied.")
            bbox = map_bbox(self.host.iface.mapCanvas())
            path = download_path()
            api_url = self.host._workflow_field_defaults().get("bag_api_url", "https://api.pdok.nl/kadaster/bag/ogc/v2")
            task = BagDownloadTask(api_url, bbox, path, self.bag_download_finished)
            task.countChanged.connect(lambda count: self.status.setText(f"BAG downloaden: {count} verblijfsobjecten ontvangen."))
            self._bag_download = task
            self._download_project_active = True
            self.bag_server_button.setEnabled(False)
            self.bag_download_button.setText("BAG-download stoppen")
            self.status.setText("BAG-verblijfsobjecten voor de huidige kaartuitsnede downloaden...")
            QgsApplication.taskManager().addTask(task)
        except Exception as exc:
            self.status.setText(str(exc))

    def cancel_bag_download(self):
        self._download_project_active = False
        if self._bag_download:
            self._bag_download.cancel()

    def bag_download_finished(self, task, succeeded):
        self._bag_download = None
        self.bag_server_button.setEnabled(True)
        self.bag_download_button.setText("BAG downloaden (kaartuitsnede)")
        if not self._download_project_active:
            self.status.setText("Project gewijzigd; er is geen BAG-laag aan het nieuwe project toegevoegd.")
            return
        if not succeeded:
            self.status.setText(task.error)
            return
        if not task.count:
            self.status.setText("Geen BAG-verblijfsobjecten gevonden binnen de huidige kaartuitsnede.")
            return
        try:
            from .bag_download import local_objects_layer
            layer = local_objects_layer(task.path, task.bbox)
            QgsProject.instance().addMapLayer(layer)
            self.refresh()
            self.source_combo.setCurrentIndex(self.source_combo.findData(layer.id()))
            if self.host.iface:
                self.host.iface.setActiveLayer(layer)
            from .connection_sources import save_project
            save_project()
            self.status.setText(f"{task.count} BAG-verblijfsobjecten lokaal opgeslagen. Selecteer de gewenste adressen. Bestand: {task.path}")
        except Exception as exc:
            self.status.setText(str(exc))

    def add_objects(self):
        try:
            source, target = self.layer(self.source_combo), self.layer(self.target_combo)
            if source is None or target is None:
                raise ValueError("Kies de verblijfsobjecten- en ontwerpstroomlaag.")
            currents = [spin.value() for spin in self.currents] if self.manual.isChecked() else None
            result = add_selected_objects(source, target, self.layer(self.housing_combo), self.host.zero_current_page,
                                          self.type_combo.currentData(), currents, self.station_combo.currentText().strip(),
                                          skip_existing=self.skip_existing.isChecked())
            self.host._refresh_zero_current_count()
            skipped_reason = "al aanwezig of zonder BAG-ID" if self.skip_existing.isChecked() else "zonder BAG-ID"
            summary = (f"{result['added']} aansluitingen toegevoegd; {result['skipped']} {skipped_reason} overgeslagen. "
                       f"{result['missing']} zonder ontwerpstroom of nog te beoordelen.")
            self.status.setText(summary)
            if self.host.iface is not None:
                self.host.iface.mapCanvas().refresh()
            if result['added'] and result['missing']:
                self.host.show_zero_current_page(select_first=False, review_layer=target)
                self.host.zero_current_page.status_label.setText(
                    summary + " Selecteer de gewenste regels en kies per gebruiksdoel de categorie en stroomwaarden."
                )
        except Exception as exc:
            self.status.setText(str(exc))
