"""Integrated station and new-construction controls."""
from qgis.PyQt.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)
from qgis.core import QgsProject, QgsWkbTypes

from .algorithms.woningtype_selectie_herberekenen_tool import HOUSING_CHOICES
from .connection_sources import add_selected_objects, assign_station, pdok_objects_layer, text_value


class ConnectionSourcesPage(QWidget):
    def __init__(self, host, mode="newbouw"):
        super().__init__(host)
        self.host = host
        self.mode = mode
        outer = QVBoxLayout(self)
        title = "Stationskoppeling" if mode == "stations" else "Nieuwbouw uit verblijfsobjecten"
        host._add_subpage_header(outer, title, "TechBase • invoer en ontwerpstroom aanvullen")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        root = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        note = QLabel("Koppel de LOVION-export of wijzig het stationsnummer van geselecteerde aansluitingen. "
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

        station_group = QGroupBox("LOVION stationsnummers")
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
        load = QPushButton("PDOK-verblijfsobjecten laden")
        load.clicked.connect(self.load_bag)
        form.addRow(load)
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
        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        root.addStretch(1)

    def layer(self, combo):
        return QgsProject.instance().mapLayer(combo.currentData())

    def refresh(self):
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

    def add_objects(self):
        try:
            source, target = self.layer(self.source_combo), self.layer(self.target_combo)
            if source is None or target is None:
                raise ValueError("Kies de verblijfsobjecten- en ontwerpstroomlaag.")
            currents = [spin.value() for spin in self.currents] if self.manual.isChecked() else None
            result = add_selected_objects(source, target, self.layer(self.housing_combo), self.host.zero_current_page,
                                          self.type_combo.currentData(), currents, self.station_combo.currentText().strip())
            self.host._refresh_zero_current_count()
            summary = (f"{result['added']} aansluitingen toegevoegd; {result['skipped']} al aanwezig of zonder BAG-ID. "
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
