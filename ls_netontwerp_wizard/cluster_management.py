"""Queue cluster changes and retire stations without editing source records."""
import hashlib
import json
import math
from pathlib import Path

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QLabel,
    QPushButton, QComboBox, QDoubleSpinBox, QListWidget, QListWidgetItem,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QLineEdit,
)
from qgis.core import (QgsProject, QgsProcessingFeedback, QgsCoordinateTransform,
                       QgsFeatureRequest, QgsGeometry, QgsPointXY)
from qgis.gui import QgsMapTool

from .batch_editing import run_batch, apply_snapshot, station_rules, save_station_rules
from .station_policy import show_retired_stations

ROLE = Qt.ItemDataRole.UserRole if hasattr(Qt, "ItemDataRole") else Qt.UserRole
LEFT_BUTTON = Qt.MouseButton.LeftButton if hasattr(Qt, "MouseButton") else Qt.LeftButton
RIGHT_BUTTON = Qt.MouseButton.RightButton if hasattr(Qt, "MouseButton") else Qt.RightButton
ESCAPE_KEY = Qt.Key.Key_Escape if hasattr(Qt, "Key") else Qt.Key_Escape


class _StationRelocationMapTool(QgsMapTool):
    """One-shot map picker; right-click or Escape cancels without editing."""

    def __init__(self, canvas, clicked, canceled):
        super().__init__(canvas)
        self._clicked = clicked
        self._canceled = canceled

    def canvasReleaseEvent(self, event):
        if event.button() == RIGHT_BUTTON:
            self._canceled()
        elif event.button() == LEFT_BUTTON:
            self._clicked(self.toMapCoordinates(event.pos()))

    def keyPressEvent(self, event):
        if event.key() == ESCAPE_KEY:
            self._canceled()
            event.accept()
        else:
            super().keyPressEvent(event)


def layer_source(layer):
    if layer is None:
        return None
    parts = layer.source().split("|")
    return str(Path(parts[0]).resolve()).casefold()+"|"+"|".join(parts[1:])


def fingerprint(layers):
    digest = hashlib.sha256()
    for name, layer in sorted(layers.items()):
        if layer is None:
            continue
        digest.update(name.encode())
        digest.update(layer_source(layer).encode())
        for feature in layer.getFeatures():
            digest.update(str(feature.id()).encode())
            digest.update(json.dumps(feature.attributes(), default=str, ensure_ascii=False).encode())
            digest.update(bytes(feature.geometry().asWkb()))
    return digest.hexdigest()


class ClusterManagementPage(QWidget):
    def __init__(self, host):
        super().__init__()
        self.host = host
        self.layers = {}
        self.signature = None
        self.rules_signature = None
        self.feedback = None
        self._location_tool = None
        self._previous_map_tool = None
        self._relocation_station = None
        self._relocation_candidate = None
        host.finished.connect(lambda *_: self._leave_location_mode(False))
        layout = QVBoxLayout(self)
        host._add_subpage_header(layout, "Clustering aanpassen",
                                "Wijzigingen klaarzetten • stationsbeheer • gezamenlijk toepassen")
        explanation = QLabel("Selecteer aansluitingen op de kaart en kies een doelstation. "
                             "Of selecteer een station hieronder om alle aansluitingen over te zetten "
                             "en het station te laten vervallen. Bestaande stations blijven in de broninventaris staan.")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Station", "Type", "Status", "Aansluitingen", "Belasting (A)", "Capaciteit (A)"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMaximumHeight(240)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        self._button(row, "Lijst vernieuwen", self.refresh)
        self._button(row, "Zoom naar station", self.zoom_station)
        self._button(row, "Aansluitingen van station selecteren", self.select_station_connections)
        self._button(row, "Bescherming aan/uit klaarzetten", self.queue_protection)
        self._button(row, "Station weer toestaan", self.queue_allow)
        layout.addLayout(row)
        group = QGroupBox("Wijziging klaarzetten")
        form = QFormLayout(group)
        self.target = QComboBox()
        form.addRow("Doelstation", self.target)
        self.maximum_route = QDoubleSpinBox()
        self.maximum_route.setRange(1, 10000)
        self.maximum_route.setValue(float((host.prepared_state or {}).get("values", {}).get("max_route", 850)))
        self.maximum_route.setSuffix(" m")
        form.addRow("Maximale kabelroute", self.maximum_route)
        self.exclusion_radius = QDoubleSpinBox()
        self.exclusion_radius.setRange(1, 500)
        self.exclusion_radius.setValue(20)
        self.exclusion_radius.setSuffix(" m")
        self.exclusion_radius.setToolTip("Na het laten vervallen van een nieuw station worden bij een nieuwe automatische clustering geen nieuwe stations binnen deze afstand geplaatst.")
        form.addRow("Uitgesloten straal bij vervallen nieuw station", self.exclusion_radius)
        buttons = QHBoxLayout()
        self._button(buttons, "Aansluitingen op kaart selecteren", self.select_on_map)
        self._button(buttons, "Selectie naar doelstation klaarzetten", self.queue_move)
        self._button(buttons, "Station laten vervallen", self.queue_retirement)
        form.addRow(buttons)
        note = QLabel("Kies bij het laten vervallen een doelstation of ‘Automatisch verdelen’. "
                      "De routecontrole houdt kabeltakken en flatgroepen bijeen en bewaakt capaciteit en routelengte.")
        note.setWordWrap(True)
        form.addRow(note)
        layout.addWidget(group)

        self.relocation_group = QGroupBox("Nieuw station verplaatsen op een sleuf")
        self.relocation_group.setObjectName("stationRelocationGroup")
        location_layout = QVBoxLayout(self.relocation_group)
        location_note = QLabel(
            "Selecteer in de stationslijst een station van type Nieuw. Klik op de kaart "
            "op een sleuf binnen zijn eigen cluster. De locatie wordt gesnapt naar "
            "een bestaande netwerkknoop, zodat de routes correct kunnen worden herberekend."
        )
        location_note.setWordWrap(True)
        location_layout.addWidget(location_note)
        self.location_status = QLabel("Nog geen nieuwe stationslocatie gekozen.")
        self.location_status.setWordWrap(True)
        location_layout.addWidget(self.location_status)
        location_actions = QHBoxLayout()
        self.pick_location_button = self._button(
            location_actions, "Nieuwe locatie op kaart kiezen", self.start_station_relocation
        )
        self.pick_location_button.setProperty("uiExplicitRole", "map")
        self.queue_location_button = self._button(
            location_actions, "Stationsverplaatsing klaarzetten", self.queue_station_relocation
        )
        self.queue_location_button.setProperty("uiExplicitRole", "primary")
        self.queue_location_button.setEnabled(False)
        location_layout.addLayout(location_actions)
        layout.addWidget(self.relocation_group)
        self.capacity_group = QGroupBox("Stationscapaciteit in het ontwerp aanpassen")
        capacity_form = QFormLayout(self.capacity_group)
        self.capacity = QDoubleSpinBox()
        self.capacity.setRange(1, 10000)
        self.capacity.setValue(630)
        self.capacity.setSuffix(" kVA")
        capacity_form.addRow("Nieuwe ontwerpcapaciteit", self.capacity)
        self._button(capacity_form, "Capaciteit geselecteerd station klaarzetten", self.queue_capacity)
        self.table.itemSelectionChanged.connect(self._load_capacity)
        layout.addWidget(self.capacity_group)

        self.merge_group = QGroupBox("Clusters samenvoegen")
        merge_layout = QVBoxLayout(self.merge_group)
        merge_note = QLabel("Selecteer het bronstation in de lijst en één ander doelstation hierboven. "
                            "Alle aansluitingen gaan naar het doel; het bronstation vervalt in het ontwerp. "
                            "De broninventaris blijft behouden. Capaciteit, bescherming en routes worden gecontroleerd.")
        merge_note.setWordWrap(True)
        merge_layout.addWidget(merge_note)
        self._button(merge_layout, "Broncluster met doelcluster samenvoegen klaarzetten", self.queue_merge)
        layout.addWidget(self.merge_group)

        self.create_group = QGroupBox("Cluster splitsen en extra station bijplaatsen")
        create_form = QFormLayout(self.create_group)
        create_note = QLabel("Selecteer een deel van één cluster op de kaart. Laat minstens één aansluiting "
                             "bij het bronstation en houd flatgroepen bijeen. Kies daarna een sleuflocatie "
                             "binnen het broncluster; het nieuwe station krijgt de geselecteerde aansluitingen.")
        create_note.setWordWrap(True)
        create_form.addRow(create_note)
        self.new_name = QLineEdit()
        self.new_name.setMaxLength(80)
        create_form.addRow("Unieke naam nieuw station", self.new_name)
        self.new_capacity = QDoubleSpinBox()
        self.new_capacity.setRange(1, 10000)
        self.new_capacity.setValue(630)
        self.new_capacity.setSuffix(" kVA")
        create_form.addRow("Capaciteit nieuw station", self.new_capacity)
        self._button(create_form, "Deel van cluster op kaart selecteren", self.select_on_map)
        self._button(create_form, "Locatie extra station op kaart kiezen", self.start_station_creation)
        self.create_status = QLabel("Nog geen locatie voor een extra station gekozen.")
        self.create_status.setWordWrap(True)
        create_form.addRow(self.create_status)
        self._button(create_form, "Splitsing met extra station klaarzetten", self.queue_creation)
        self._creation_candidate = None
        self._creation_ids = None
        layout.addWidget(self.create_group)

        self.validation_group = QGroupBox("Kaartselecties en herberekenen")
        validation_layout = QVBoxLayout(self.validation_group)
        for text, callback in (
            ("Clustergebied en routes selecteren", self.select_cluster_products),
            ("Aansluitingen boven maximale route selecteren", lambda: self.select_issues("route")),
            ("Aansluitingen met nulstroom selecteren", lambda: self.select_issues("zero")),
            ("Aansluitingen zonder geldig station selecteren", lambda: self.select_issues("assignment")),
            ("Routes geselecteerd station herberekenen klaarzetten", lambda: self.queue_rebuild(False)),
            ("Alle routes en gebieden herberekenen klaarzetten", lambda: self.queue_rebuild(True)),
        ):
            self._button(validation_layout, text, callback)
        layout.addWidget(self.validation_group)
        self.queue = QListWidget()
        self.queue.setMinimumHeight(80)
        self.queue.setMaximumHeight(145)
        layout.addWidget(QLabel("Wachtrij — nog niet toegepast"))
        layout.addWidget(self.queue)
        row = QHBoxLayout()
        self._button(row, "Uit wachtrij verwijderen", self.remove_queued)
        self._button(row, "Wachtrij wissen", self.clear_queue)
        self._button(row, "Omhoog", lambda: self.reorder(-1))
        self._button(row, "Omlaag", lambda: self.reorder(1))
        self._button(row, "Klassieke correctiepagina", self.classic)
        layout.addLayout(row)
        self.status = QLabel("Selecteer aansluitingen of een station om te beginnen.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.preview = QLabel("Capaciteit en routes worden gecontroleerd vóór het ontwerp wordt aangepast.")
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)
        row = QHBoxLayout()
        self.check_button = self._button(row, "Voorstel controleren", lambda: self.execute(True))
        self.apply_button = self._button(row, "Alles toepassen", lambda: self.execute(False))
        self.apply_button.setProperty("uiExplicitRole", "primary")
        self.undo_button = self._button(row, "Laatste toepassing ongedaan maken", self.undo)
        self.undo_button.setProperty("uiExplicitRole", "secondary")
        self.cancel = self._button(row, "Bewerking stoppen", self.stop)
        # The generic compact 'stop' role is intended for the tiny progress
        # bar X, not a full-size action button in this page's footer.
        self.cancel.setProperty("uiExplicitRole", "danger")
        self.cancel.setMinimumWidth(148)
        self.cancel.setToolTip("Annuleer de lopende berekening; alleen actief tijdens verwerken.")
        self.cancel.setEnabled(False)
        layout.addLayout(row)

    def _button(self, row, text, callback):
        button = QPushButton(text)
        button.clicked.connect(callback)
        row.addWidget(button)
        return button

    def operations(self):
        return [self.queue.item(index).data(ROLE) for index in range(self.queue.count())]

    def refresh(self, *_args):
        from .algorithms.handmatige_cluster_correctie_tool import HandmatigeClusterCorrectieAlgorithm
        defaults = HandmatigeClusterCorrectieAlgorithm._project_layer_defaults()
        project = QgsProject.instance()
        mapping = {"connections": "AANSLUITINGEN", "stations": "STATIONS", "areas": "GEBIEDEN",
                   "routes": "KABELROUTES", "cables": "SLEUVEN", "plan": "PLANGEBIED"}
        updated = {name: (project.mapLayer(defaults.get(key)) if isinstance(defaults.get(key), str) else defaults.get(key))
                   for name, key in mapping.items()}
        if self.queue.count() and any(self.layers.get(key) is not updated.get(key) for key in mapping):
            self.status.setText("De resultaatlagen zijn veranderd. Verwijder de oude wachtrij voordat je verder gaat.")
            return
        self.layers = updated
        self.table.setRowCount(0)
        previous_target = self.target.currentData()
        self.target.clear()
        self.target.addItem("Automatisch verdelen over geschikte stations", None)
        if any(self.layers[name] is None for name in ("connections", "stations", "areas", "routes", "cables")):
            self.status.setText("Open eerst een berekend clusterproject.")
            return
        rules = station_rules()
        active = set()
        for feature in self.layers["stations"].getFeatures():
            name = str(feature["Cluster"])
            active.add(name)
            load = float(feature["Belast_A"] or 0)
            capacity = float(feature["KVA"]) / .23 / 3
            self.target.addItem(f"{name} — {load:.1f} / {capacity:.1f} A", name)
            self._station_row(name, str(feature["Type"]), "Beschermd" if rules.get(name, {}).get("protected") else "In ontwerp",
                              str(feature["Aantal"]), f"{load:.1f}", f"{capacity:.1f}")
        for name, rule in rules.items():
            if name not in active and rule.get("status"):
                self._station_row(name, rule.get("type", ""), rule["status"], "0", "0", "—")
        index = self.target.findData(previous_target)
        if index >= 0:
            self.target.setCurrentIndex(index)
        self.table.resizeColumnsToContents()
        self.preview_capacity()

    def _station_row(self, *values):
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col, value in enumerate(values):
            self.table.setItem(row, col, QTableWidgetItem(str(value)))

    def selected_station(self):
        row = self.table.currentRow()
        if row < 0:
            raise ValueError("Selecteer eerst een station in de lijst.")
        return self.table.item(row, 0).text()

    def _ready(self):
        if any(self.layers.get(name) is None for name in ("connections", "stations", "areas", "routes", "cables")):
            raise ValueError("Open eerst een berekend clusterproject.")
        if self.signature and fingerprint(self.layers) != self.signature:
            raise ValueError("Het ontwerp is tussentijds aangepast. Wis de wachtrij en zet de wijzigingen opnieuw klaar.")
        if self.rules_signature is not None and self.rules_signature != station_rules():
            raise ValueError("De stationskeuzes zijn tussentijds aangepast. Wis de wachtrij.")

    def add_operation(self, operation, label):
        self._ready()
        if operation.get("target") and any(op.get("kind") == "retire" and op.get("source") == operation["target"] for op in self.operations()):
            raise ValueError("Dit doelstation is al klaargezet om te vervallen. Kies een ander station of wijzig de volgorde.")
        if operation.get("kind") == "relocate" and any(
            op.get("kind") in ("relocate", "retire") and
            op.get("source") == operation["source"]
            for op in self.operations()
        ):
            raise ValueError("Dit station staat al in de wachtrij. Pas die wijziging eerst toe.")
        if not self.queue.count():
            self.signature = fingerprint(self.layers)
            self.rules_signature = station_rules()
        item = QListWidgetItem(label)
        item.setData(ROLE, operation)
        self.queue.addItem(item)
        self.preview_capacity()
        self.status.setText(f"{self.queue.count()} wijziging(en) klaar; het ontwerp is nog niet aangepast.")

    def _station_for_relocation(self):
        """Require an active new station (never change the source inventory)."""
        name = self.selected_station()
        station = next(
            (feature for feature in self.layers["stations"].getFeatures()
             if str(feature["Cluster"]).strip() == name),
            None,
        )
        if station is None:
            raise ValueError("Selecteer een station dat nog in het ontwerp staat.")
        if not str(station["Type"]).strip().casefold().startswith("nieuw"):
            raise ValueError(
                "Dit is een bestaand station. Alleen nieuw geplaatste stations "
                "kunnen op een andere sleuflocatie worden gezet."
            )
        return name, station

    def _leave_location_mode(self, restore_window=True):
        tool = self._location_tool
        if tool is None:
            return
        self._location_tool = None
        previous = self._previous_map_tool
        self._previous_map_tool = None
        self._relocation_station = None
        iface = self.host.iface
        if iface is not None:
            canvas = iface.mapCanvas()
            if canvas.mapTool() is tool:
                if previous is not None and previous is not tool:
                    canvas.setMapTool(previous)
                else:
                    canvas.unsetMapTool(tool)
        if restore_window:
            self.host.show()
            self.host.raise_()
            self.host.activateWindow()

    def start_station_relocation(self):
        try:
            self._ready()
            name, _station = self._station_for_relocation()
            if self.queue.count():
                raise ValueError(
                    "Pas eerst de wijzigingen in de wachtrij toe of verwijder ze. "
                    "Daarna kun je een nieuwe stationslocatie kiezen."
                )
            if self.host.iface is None:
                raise ValueError("Een stationslocatie kiezen kan alleen in QGIS Desktop.")
            if self._location_tool is not None:
                raise ValueError("Er is al een kaartselectie actief.")
            self._relocation_candidate = None
            self.queue_location_button.setEnabled(False)
            self._relocation_station = name
            canvas = self.host.iface.mapCanvas()
            self._previous_map_tool = canvas.mapTool()
            self._location_tool = _StationRelocationMapTool(
                canvas, self._station_location_clicked, self._station_location_canceled
            )
            canvas.setMapTool(self._location_tool)
            self.location_status.setText(
                f"Klik op een sleuf binnen het cluster van {name}. "
                "Rechtsklik of druk Esc om te annuleren."
            )
            self.host.hide()
        except Exception as exc:
            self.location_status.setText(str(exc))

    def _station_location_canceled(self):
        self._leave_location_mode()
        self.location_status.setText("Het kiezen van een stationslocatie is geannuleerd.")

    def _station_location_clicked(self, map_point):
        name = self._relocation_station
        self._leave_location_mode()
        if not name:
            return
        try:
            candidate, snap_distance = self._snap_to_cluster_trench_node(name, map_point)
            self._relocation_candidate = {
                "kind": "relocate", "source": name,
                "x": float(candidate.x()), "y": float(candidate.y()),
            }
            self.queue_location_button.setEnabled(True)
            self.location_status.setText(
                f"Nieuwe locatie voor {name}: X {candidate.x():.2f}, "
                f"Y {candidate.y():.2f} "
                f"(gesnapt naar netwerkknoop, {snap_distance:.1f} m vanaf de klik). "
                "Klik op 'Stationsverplaatsing klaarzetten'."
            )
        except Exception as exc:
            self._relocation_candidate = None
            self.queue_location_button.setEnabled(False)
            self.location_status.setText(str(exc))

    def _snap_to_cluster_trench_node(self, name, map_point):
        """Return a real cable vertex *inside* the same cluster, not an arbitrary pixel."""
        areas = self.layers["areas"]
        cables = self.layers["cables"]
        stations = self.layers["stations"]
        if areas is None or cables is None or stations is None:
            raise ValueError("De clustergebieden, sleuven of stationslaag ontbreken.")
        if areas.crs().isGeographic() or cables.crs().isGeographic():
            raise ValueError("Voor stationsverplaatsing zijn geprojecteerde meter-CRS'en nodig.")
        region = next(
            (feature for feature in areas.getFeatures()
             if str(feature["Cluster"]).strip() == name),
            None,
        )
        if region is None or not region.hasGeometry():
            raise ValueError(f"Er is geen geldig clustergebied voor {name}.")
        polygon = QgsGeometry(region.geometry())
        if areas.crs() != cables.crs():
            polygon.transform(QgsCoordinateTransform(
                areas.crs(), cables.crs(), QgsProject.instance()
            ))
        query = QgsGeometry.fromPointXY(QgsPointXY(map_point))
        canvas_crs = self.host.iface.mapCanvas().mapSettings().destinationCrs()
        if canvas_crs != cables.crs():
            query.transform(QgsCoordinateTransform(
                canvas_crs, cables.crs(), QgsProject.instance()
            ))
        if not polygon.buffer(0.05, 8).intersects(query):
            raise ValueError(
                f"De aangeklikte locatie ligt buiten het clustergebied van {name}."
            )

        clicked = query.asPoint()
        best = None
        best_distance = float("inf")
        request = QgsFeatureRequest().setFilterRect(polygon.boundingBox())
        expanded_region = polygon.buffer(0.05, 8)
        for cable in cables.getFeatures(request):
            if not cable.hasGeometry():
                continue
            line = cable.geometry()
            if not line.intersects(polygon):
                continue
            for vertex in line.vertices():
                point = QgsPointXY(vertex)
                distance = math.hypot(point.x() - clicked.x(), point.y() - clicked.y())
                if distance >= best_distance:
                    continue
                if not expanded_region.intersects(QgsGeometry.fromPointXY(point)):
                    continue
                best = point
                best_distance = distance
        if best is None or best_distance > 30.0:
            raise ValueError(
                "Geen bestaande netwerkknoop op een sleuf binnen 30 m van de klik. "
                "Klik dichter bij een sleufknooppunt of voeg eerst een knooppunt "
                "toe via stap 5 (Sleuven/routes)."
            )

        candidate = QgsGeometry.fromPointXY(best)
        if cables.crs() != stations.crs():
            candidate.transform(QgsCoordinateTransform(
                cables.crs(), stations.crs(), QgsProject.instance()
            ))
        point = candidate.asPoint()
        new_xy = QgsPointXY(point)
        for station in stations.getFeatures():
            if str(station["Cluster"]).strip() == name or not station.hasGeometry():
                continue
            if station.geometry().distance(candidate) < 1.0:
                raise ValueError(
                    "De gesnapte locatie ligt te dicht bij een ander station. "
                    "Kies een ander netwerkknooppunt."
                )
        return new_xy, best_distance

    def queue_station_relocation(self):
        try:
            self._ready()
            operation = self._relocation_candidate
            if operation is None:
                raise ValueError("Kies eerst een nieuwe locatie op de kaart.")
            name, _station = self._station_for_relocation()
            if name != operation["source"]:
                raise ValueError(
                    "De geselecteerde stationsregel is gewijzigd. Kies de nieuwe locatie opnieuw."
                )
            self.add_operation(
                dict(operation),
                f"{name} verplaatsen naar sleufknoop "
                f"({operation['x']:.2f}, {operation['y']:.2f})",
            )
            self._relocation_candidate = None
            self.queue_location_button.setEnabled(False)
            self.location_status.setText(
                f"Verplaatsing van {name} staat in de wachtrij. "
                "Controleer het voorstel en klik daarna op Alles toepassen."
            )
        except Exception as exc:
            self.location_status.setText(str(exc))

    def queue_move(self):
        try:
            self._ready()
            target = self.target.currentData()
            if not target:
                raise ValueError("Kies voor een verplaatsing één doelstation.")
            ids = list(self.layers["connections"].selectedFeatureIds())
            if not ids:
                raise ValueError("Selecteer eerst aansluitingen op de kaart.")
            self.add_operation({"kind": "move", "point_ids": ids, "target": target}, f"{len(ids)} aansluiting(en) → {target}")
        except Exception as exc:
            self.status.setText(str(exc))

    def _load_capacity(self):
        try:
            name = self.selected_station()
            station = next(f for f in self.layers["stations"].getFeatures() if str(f["Cluster"]) == name)
            self.capacity.setValue(float(station["KVA"]))
        except (KeyError, ValueError, StopIteration, AttributeError):
            pass

    def queue_capacity(self):
        try:
            name = self.selected_station()
            self.add_operation({"kind": "capacity", "station": name, "kva": self.capacity.value()},
                               f"{name}: ontwerpcapaciteit → {self.capacity.value():g} kVA")
        except Exception as exc:
            self.status.setText(str(exc))

    def queue_merge(self):
        if not self.target.currentData():
            self.status.setText("Kies één doelstation om clusters samen te voegen.")
            return
        self.queue_retirement()

    def start_station_creation(self):
        try:
            self._ready()
            if self.queue.count():
                raise ValueError("Pas eerst de wachtrij toe of wis deze voordat je een locatie kiest.")
            if self.host.iface is None:
                raise ValueError("Een stationslocatie kiezen kan alleen in QGIS Desktop.")
            points = list(self.layers["connections"].getSelectedFeatures())
            names = {str(f["Cluster"]) for f in points}
            if not points or len(names) != 1:
                raise ValueError("Selecteer een deel van precies één cluster.")
            self._creation_candidate = None
            self._creation_ids = [f.id() for f in points]
            source = names.pop()
            if len(points) >= sum(str(f["Cluster"]) == source for f in self.layers["connections"].getFeatures()):
                raise ValueError("Laat minstens één aansluiting bij het bronstation.")
            self._relocation_station = source
            canvas = self.host.iface.mapCanvas()
            self._previous_map_tool = canvas.mapTool()
            self._location_tool = _StationRelocationMapTool(canvas, self._creation_location_clicked, self._creation_location_canceled)
            canvas.setMapTool(self._location_tool)
            self.create_status.setText(f"Klik op een sleufknoop binnen {source}; Esc of rechtsklik annuleert.")
            self.host.hide()
        except Exception as exc:
            self.create_status.setText(str(exc))

    def _creation_location_canceled(self):
        self._leave_location_mode()
        self._creation_candidate = None
        self.create_status.setText("Locatie kiezen geannuleerd.")

    def _creation_location_clicked(self, map_point):
        source = self._relocation_station
        self._leave_location_mode()
        try:
            candidate, distance = self._snap_to_cluster_trench_node(source, map_point)
            self._creation_candidate = (float(candidate.x()), float(candidate.y()))
            self.create_status.setText(f"Locatie X {candidate.x():.2f}, Y {candidate.y():.2f}; {distance:.1f} m gesnapt. Splitsing kan worden klaargezet.")
        except Exception as exc:
            self._creation_candidate = None
            self.create_status.setText(str(exc))

    def queue_creation(self):
        try:
            if self._creation_candidate is None or not self._creation_ids:
                raise ValueError("Selecteer eerst aansluitingen en kies een locatie voor het extra station.")
            name = self.new_name.text().strip()
            if not name:
                raise ValueError("Geef het nieuwe station een unieke naam.")
            x, y = self._creation_candidate
            self.add_operation({"kind": "create", "name": name, "kva": self.new_capacity.value(),
                                "point_ids": self._creation_ids, "x": x, "y": y},
                               f"Extra station {name}: {len(self._creation_ids)} aansluiting(en), {self.new_capacity.value():g} kVA")
            self._creation_candidate = None
            self.create_status.setText("Splitsing klaargezet; controleer het voorstel.")
        except Exception as exc:
            self.status.setText(str(exc))

    def queue_rebuild(self, all_stations):
        try:
            names = [] if all_stations else [self.selected_station()]
            self.add_operation({"kind": "rebuild", "stations": names},
                               "Routes en gebieden herberekenen: " + (", ".join(names) or "alle stations"))
        except Exception as exc:
            self.status.setText(str(exc))

    def clear_queue(self):
        self.queue.clear()
        self.signature = self.rules_signature = None
        self._creation_candidate = self._relocation_candidate = None
        self.queue_location_button.setEnabled(False)
        self.preview_capacity()
        self.status.setText("Wachtrij gewist; het ontwerp is ongewijzigd.")

    def select_cluster_products(self):
        try:
            self._ready()
            name = self.selected_station()
            for key in ("areas", "routes"):
                layer = self.layers[key]
                layer.selectByIds([f.id() for f in layer.getFeatures() if str(f["Cluster"]) == name])
            if self.host.iface is not None:
                self.host.iface.setActiveLayer(self.layers["areas"])
                self.host.iface.mapCanvas().zoomToSelected(self.layers["areas"])
            self.status.setText(f"Gebied en kabelroutes van {name} geselecteerd.")
        except Exception as exc:
            self.status.setText(str(exc))

    def select_issues(self, kind):
        try:
            self._ready()
            stations = {str(f["Cluster"]) for f in self.layers["stations"].getFeatures()}
            layer = self.layers["connections"]
            selected = []
            for feature in layer.getFeatures():
                match = (str(feature["Cluster"]) not in stations if kind == "assignment" else
                         float(feature["Ontwerp_A"] or 0) <= 0 if kind == "zero" else
                         float(feature["Route_m"] or 0) > self.maximum_route.value())
                if match:
                    selected.append(feature.id())
            layer.selectByIds(selected)
            if self.host.iface is not None:
                self.host.iface.setActiveLayer(layer)
                if selected:
                    self.host.iface.mapCanvas().zoomToSelected(layer)
            self.status.setText(f"{len(selected)} aansluiting(en) geselecteerd voor deze controle.")
        except Exception as exc:
            self.status.setText(str(exc))

    def queue_retirement(self):
        try:
            source = self.selected_station()
            target = self.target.currentData()
            if target == source:
                raise ValueError("Kies een ander doelstation dan het bronstation.")
            if any(op.get("source") == source for op in self.operations()):
                raise ValueError("Dit station staat al in de wachtrij om te vervallen.")
            self.add_operation({"kind": "retire", "source": source, "target": target, "radius": self.exclusion_radius.value()},
                               f"{source} laten vervallen → {target or 'automatisch verdelen'}")
        except Exception as exc:
            self.status.setText(str(exc))

    def queue_protection(self):
        try:
            name = self.selected_station()
            rules = station_rules()
            protected = rules.get(name, {}).get("protected", False)
            for operation in self.operations():
                if operation.get("kind") == "protect" and operation.get("station") == name:
                    protected = operation["protected"]
            self.add_operation({"kind": "protect", "station": name, "protected": not protected},
                               f"{name}: {'beschermen' if not protected else 'bescherming opheffen'}")
        except Exception as exc:
            self.status.setText(str(exc))

    def queue_allow(self):
        try:
            name = self.selected_station()
            self.add_operation({"kind": "allow", "station": name},
                               f"{name}: opnieuw toestaan bij een volgende clustering")
        except Exception as exc:
            self.status.setText(str(exc))

    def remove_queued(self):
        index = self.queue.currentRow()
        if index < 0:
            index = self.queue.count()-1
        if index >= 0:
            self.queue.takeItem(index)
        if not self.queue.count():
            self.signature = None
            self.rules_signature = None
        self.preview_capacity()

    def reorder(self, direction):
        index = self.queue.currentRow()
        other = index+direction
        if index >= 0 and 0 <= other < self.queue.count():
            item = self.queue.takeItem(index)
            self.queue.insertItem(other, item)
            self.queue.setCurrentRow(other)
            self.preview_capacity()

    def preview_capacity(self):
        if self.layers.get("connections") is None or self.layers.get("stations") is None:
            return
        points = {int(f.id()): [str(f["Cluster"]), float(f["Ontwerp_A"])] for f in self.layers["connections"].getFeatures()}
        capacities = {str(f["Cluster"]): float(f["KVA"])/.23/3 for f in self.layers["stations"].getFeatures()}
        changed_targets = set()
        automatic = False
        for operation in self.operations():
            if operation["kind"] == "capacity":
                capacities[operation["station"]] = operation["kva"]/.23/3
                changed_targets.add(operation["station"])
                continue
            if operation["kind"] == "create":
                ids, target = operation["point_ids"], operation["name"]
                capacities[target] = operation["kva"]/.23/3
            elif operation["kind"] == "move":
                ids, target = operation["point_ids"], operation["target"]
            elif operation["kind"] == "retire":
                ids = [fid for fid, (cluster, _) in points.items() if cluster == operation["source"]]
                target = operation.get("target")
                if not target:
                    automatic = True
                    continue
            else:
                continue
            changed_targets.add(target)
            for fid in ids:
                if fid in points:
                    points[fid][0] = target
        loads = {}
        for cluster, load in points.values():
            loads[cluster] = loads.get(cluster, 0)+load
        text = []
        for name, capacity in capacities.items():
            if name in changed_targets:
                load = loads.get(name, 0)
                text.append(f"{name}: {load:.1f} / {capacity:.1f} A ({load/capacity*100:.1f}%)")
        self.preview.setText(("Voorlopige doelbelasting: " + "; ".join(text) + ". " if text else "") +
                             ("Automatische verdeling wordt bij de voorstelcontrole gezocht. " if automatic else "") +
                             "Routes en kabeltakken worden gecontroleerd bij ‘Voorstel controleren’ of ‘Alles toepassen’.")

    def directory(self):
        folder = QgsProject.instance().homePath()
        if not folder:
            folder = str(Path(self.layers["connections"].source().split("|", 1)[0]).parent)
        return Path(folder) / "handmatige_correcties"

    def execute(self, preview):
        if self.feedback is not None:
            return
        buttons = []
        try:
            self._ready()
            operations = self.operations()
            if not operations:
                raise ValueError("De wachtrij is leeg.")
            rules_before = station_rules()
            self.feedback = QgsProcessingFeedback()
            buttons = [(button, button.isEnabled()) for button in self.findChildren(QPushButton)]
            for button, _ in buttons:
                button.setEnabled(False)
            self.target.setEnabled(False)
            self.maximum_route.setEnabled(False)
            self.exclusion_radius.setEnabled(False)
            self.table.setEnabled(False)
            self.queue.setEnabled(False)
            for widget in (self.capacity, self.new_capacity, self.new_name):
                widget.setEnabled(False)
            self.cancel.setEnabled(True)
            self.status.setText("Voorstel en kabelroutes worden gecontroleerd…" if preview else "Alle wijzigingen worden gezamenlijk berekend…")
            summary, backup, result = run_batch(self.layers, operations, self.directory(), self.maximum_route.value(), preview, self.feedback, rules_before)
            if preview:
                moved = summary.get("relocated_stations", [])
                description = (
                    f" Nieuw station verplaatst: {', '.join(moved)}."
                    if moved else ""
                )
                self.status.setText(
                    f"Capaciteit en routes akkoord: {summary['moved_count']} aansluiting(en), "
                    f"{len(summary['removed_source_clusters'])} station(s) laten vervallen."
                    f"{description} Langste route: {summary['maximum_route_m']:.1f} m. "
                    f"Nieuw: {len(summary.get('created_stations', []))}; capaciteit gewijzigd: {len(summary.get('capacity_changed', []))}; routes ververst: {len(summary.get('refreshed_stations', []))}. "
                    "Gebiedscontrole volgt bij toepassen; het ontwerp is nog ongewijzigd."
                )
            else:
                try:
                    save_station_rules(summary["station_rules"])
                    show_retired_stations(summary["station_rules"], self.directory())
                except Exception:
                    apply_snapshot(self.layers, backup)
                    save_station_rules(rules_before)
                    show_retired_stations(rules_before, self.directory())
                    raise
                undo = {"backup": backup, "rules": rules_before,
                        "rules_after": summary["station_rules"],
                        "sources": {key: layer_source(layer) for key, layer in self.layers.items()},
                        "after": fingerprint(self.layers)}
                project = QgsProject.instance()
                project.writeEntry("LSNetontwerp", "batch_undo", json.dumps(undo, ensure_ascii=False))
                from .algorithms.handmatige_cluster_correctie_tool import HandmatigeClusterCorrectieAlgorithm
                HandmatigeClusterCorrectieAlgorithm._refresh_project_layout_after_correction(self.layers["connections"], self.layers["stations"], self.layers["areas"], self.layers["routes"])
                for layer in project.mapLayers().values():
                    if layer.customProperty("LSNetontwerp/simplified_cluster_areas", False) and str(layer.customProperty("LSNetontwerp/areas_base_uri", "")) == self.layers["areas"].source():
                        node = project.layerTreeRoot().findLayer(layer.id())
                        if node is not None:
                            node.setItemVisibilityChecked(False)
                original_node = project.layerTreeRoot().findLayer(self.layers["areas"].id())
                if original_node is not None:
                    original_node.setItemVisibilityChecked(True)
                self.queue.clear()
                self.signature = None
                self.rules_signature = None
                self.refresh()
                if project.fileName():
                    project.write()
                moved = summary.get("relocated_stations", [])
                description = (
                    f" Nieuw station verplaatst: {', '.join(moved)}."
                    if moved else ""
                )
                self.status.setText(
                    f"Gereed: {summary['moved_count']} aansluiting(en) bijgewerkt; "
                    f"{len(summary['removed_source_clusters'])} station(s) vervallen."
                    f"{description} Routes en gebieden bijgewerkt. "
                    f"Nieuw: {len(summary.get('created_stations', []))}; capaciteit gewijzigd: {len(summary.get('capacity_changed', []))}; routes ververst: {len(summary.get('refreshed_stations', []))}. "
                    "De toepassing kan ongedaan gemaakt worden."
                )
        except Exception as exc:
            self.status.setText(str(exc))
        finally:
            if self.feedback is not None:
                self.feedback = None
                for button, enabled in buttons:
                    button.setEnabled(enabled)
                self.target.setEnabled(True)
                self.maximum_route.setEnabled(True)
                self.exclusion_radius.setEnabled(True)
                self.table.setEnabled(True)
                self.queue.setEnabled(True)
                for widget in (self.capacity, self.new_capacity, self.new_name):
                    widget.setEnabled(True)
                self.cancel.setEnabled(False)
            if self.host.iface is not None:
                self.host.iface.mapCanvas().refresh()

    def undo(self):
        try:
            if self.queue.count():
                raise ValueError("Verwijder eerst de nog niet toegepaste wijzigingen uit de wachtrij.")
            self._ready()
            record, _ = QgsProject.instance().readEntry("LSNetontwerp", "batch_undo", "")
            if not record:
                raise ValueError("Er is nog geen toepassing om ongedaan te maken.")
            record = json.loads(record)
            if "rules_after" in record and record["rules_after"] != station_rules():
                raise ValueError("De stationskeuzes zijn sinds de toepassing veranderd. Undo zou latere keuzes overschrijven.")
            if record["after"] != fingerprint(self.layers):
                raise ValueError("Het ontwerp is sinds de toepassing veranderd. Terugzetten zou latere wijzigingen overschrijven.")
            if record["sources"] != {key: layer_source(layer) for key, layer in self.layers.items()}:
                raise ValueError("Open het project waarin de toepassing is uitgevoerd.")
            apply_snapshot(self.layers, record["backup"])
            save_station_rules(record["rules"])
            show_retired_stations(record["rules"], self.directory())
            project = QgsProject.instance()
            project.writeEntry("LSNetontwerp", "batch_undo", "")
            from .algorithms.handmatige_cluster_correctie_tool import HandmatigeClusterCorrectieAlgorithm
            HandmatigeClusterCorrectieAlgorithm._refresh_project_layout_after_correction(self.layers["connections"], self.layers["stations"], self.layers["areas"], self.layers["routes"])
            self.refresh()
            if project.fileName():
                project.write()
            self.status.setText("De laatste toepassing is ongedaan gemaakt, inclusief stations, routes, gebieden en stationskeuzes.")
        except Exception as exc:
            self.status.setText(str(exc))

    def stop(self):
        self._leave_location_mode(False)
        if self.feedback is not None:
            self.feedback.cancel()
            self.status.setText("Bewerking stoppen…")

    def select_station_connections(self):
        try:
            name = self.selected_station()
            layer = self.layers["connections"]
            layer.selectByIds([f.id() for f in layer.getFeatures() if str(f["Cluster"]) == name])
            self.status.setText(f"{layer.selectedFeatureCount()} aansluitingen van {name} geselecteerd.")
        except Exception as exc:
            self.status.setText(str(exc))

    def zoom_station(self):
        try:
            name = self.selected_station()
            layer = self.layers["stations"]
            layer.selectByIds([f.id() for f in layer.getFeatures() if str(f["Cluster"]) == name])
            if self.host.iface is not None:
                self.host.iface.setActiveLayer(layer)
                self.host.iface.mapCanvas().zoomToSelected(layer)
        except Exception as exc:
            self.status.setText(str(exc))

    def select_on_map(self):
        try:
            self._ready()
            if self.host.iface is None:
                raise ValueError("Open de plugin in QGIS om op de kaart te selecteren.")
            self.host._start_submenu_map_selection(self, self.layers["connections"], self.preview_capacity,
                                                  self.status, "Selecteer aansluitingen op de kaart en keer terug om ze klaar te zetten.")
        except Exception as exc:
            self.status.setText(str(exc))

    def classic(self):
        self.host._show_classic_manual_page(False)
