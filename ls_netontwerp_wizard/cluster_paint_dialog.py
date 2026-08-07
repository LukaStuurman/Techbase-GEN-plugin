from __future__ import annotations

from pathlib import Path

from qgis import processing
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)
from qgis.core import QgsProject

from .algorithms.handmatige_cluster_correctie_tool import (
    HandmatigeClusterCorrectieAlgorithm,
)


class VisueleClusterEditorDialog(QDialog):
    """Visuele lasso-editor boven op de bestaande veilige clustercorrectie."""

    REQUIRED = ("AANSLUITINGEN", "STATIONS", "GEBIEDEN", "KABELROUTES", "SLEUVEN")

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.layers = {}
        self._waiting = None
        self.setWindowTitle("LS Netontwerp – visuele clustereditor")
        self.setMinimumWidth(720)
        self.setWindowModality(Qt.NonModal)

        root = QVBoxLayout(self)
        title = QLabel("<b>Visuele clustereditor</b>")
        title.setStyleSheet("font-size: 18px;")
        root.addWidget(title)

        intro = QLabel(
            "Teken met de vrije-handselectie rond de aansluitingen die naar een ander "
            "cluster moeten. Klik daarna één doelstation aan. De bestaande rekenkern "
            "controleert capaciteit, kabellengte en exclusieve routes en werkt routes, "
            "stationsstatistieken en clustergebieden gezamenlijk bij."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        select_group = QGroupBox("1. Selecteer in de kaart")
        select_layout = QVBoxLayout(select_group)
        row = QHBoxLayout()
        self.lasso_button = QPushButton("Aansluitingen met lasso selecteren")
        self.station_button = QPushButton("Doelstation aanklikken")
        clear_button = QPushButton("Selecties wissen")
        self.lasso_button.clicked.connect(self.start_lasso)
        self.station_button.clicked.connect(self.start_station_pick)
        clear_button.clicked.connect(self.clear_selections)
        row.addWidget(self.lasso_button)
        row.addWidget(self.station_button)
        row.addWidget(clear_button)
        select_layout.addLayout(row)
        self.selection_label = QLabel("Nog geen geldige selectie.")
        self.selection_label.setWordWrap(True)
        select_layout.addWidget(self.selection_label)
        root.addWidget(select_group)

        preview_group = QGroupBox("2. Voorbeeld")
        preview_layout = QVBoxLayout(preview_group)
        self.preview_label = QLabel("Selecteer aansluitingen en één doelstation.")
        self.preview_label.setWordWrap(True)
        self.preview_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        preview_layout.addWidget(self.preview_label)
        root.addWidget(preview_group)

        options_group = QGroupBox("3. Veiligheidscontroles")
        options = QFormLayout(options_group)
        self.remove_source_cluster = QCheckBox(
            "Hele broncluster(s) samenvoegen en verwijderen"
        )
        self.remove_source_cluster.setToolTip(
            "Eén geselecteerde aansluiting is dan voldoende om de volledige "
            "broncluster naar het doelstation te verplaatsen."
        )
        options.addRow(self.remove_source_cluster)

        self.max_route = QSpinBox()
        self.max_route.setRange(1, 10000)
        self.max_route.setValue(850)
        self.max_route.setSuffix(" m")
        options.addRow("Maximale kabelroute", self.max_route)

        self.check_capacity = QCheckBox("Stationscapaciteit bewaken")
        self.check_route = QCheckBox("Maximale kabellengte bewaken")
        self.block_other = QCheckBox("Routes door andere clusters blokkeren")
        self.check_shared = QCheckBox(
            "Gedeelde routes / onvolledige vertakkingen blokkeren"
        )
        for checkbox in (
            self.check_capacity,
            self.check_route,
            self.block_other,
            self.check_shared,
        ):
            checkbox.setChecked(True)
            options.addRow(checkbox)

        backup_row = QHBoxLayout()
        self.backup_edit = QLineEdit()
        browse = QPushButton("Kiezen…")
        browse.clicked.connect(self.choose_backup_folder)
        backup_row.addWidget(self.backup_edit, 1)
        backup_row.addWidget(browse)
        options.addRow("Back-upmap", backup_row)
        root.addWidget(options_group)

        self.status_label = QLabel("Gereed.")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.apply_button = QPushButton("Clusterwijziging toepassen")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply_change)
        refresh_button = QPushButton("Lagen opnieuw zoeken")
        refresh_button.clicked.connect(self.refresh_layers)
        close_button = QPushButton("Sluiten")
        close_button.clicked.connect(self.close)
        buttons.addWidget(refresh_button)
        buttons.addWidget(self.apply_button)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

        self.refresh_layers()

    @staticmethod
    def _field_name(layer, candidates):
        if layer is None:
            return None
        fields = {field.name().casefold(): field.name() for field in layer.fields()}
        for candidate in candidates:
            name = fields.get(candidate.casefold())
            if name:
                return name
        return None

    @staticmethod
    def _number(value):
        if value is None:
            return None
        text = str(value).strip().replace("\u00a0", "").replace(" ", "")
        if not text:
            return None
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        elif "," in text:
            text = text.replace(",", ".")
        try:
            return float(text)
        except (TypeError, ValueError):
            return None

    def _disconnect_signals(self):
        for key in ("AANSLUITINGEN", "STATIONS"):
            layer = self.layers.get(key)
            if layer is None:
                continue
            try:
                layer.selectionChanged.disconnect(self._selection_changed)
            except (TypeError, RuntimeError):
                pass

    def refresh_layers(self):
        self._disconnect_signals()
        project = QgsProject.instance()
        defaults = HandmatigeClusterCorrectieAlgorithm._project_layer_defaults()
        self.layers = {
            key: project.mapLayer(defaults.get(key)) if defaults.get(key) else None
            for key in (*self.REQUIRED, "PLANGEBIED")
        }
        for key in ("AANSLUITINGEN", "STATIONS"):
            layer = self.layers.get(key)
            if layer is not None:
                layer.selectionChanged.connect(self._selection_changed)

        missing = [key for key in self.REQUIRED if self.layers.get(key) is None]
        if missing:
            self._set_status(
                "Niet alle resultaatlagen zijn gevonden: " + ", ".join(missing), True
            )
        else:
            names = ", ".join(self.layers[key].name() for key in self.REQUIRED)
            self._set_status("Resultaatlagen gevonden: " + names)
            if not self.backup_edit.text().strip():
                home = project.homePath()
                if home:
                    self.backup_edit.setText(str(Path(home) / "cluster_editor_backups"))
        self._refresh_preview()

    def _selection_changed(self, *args):
        self._refresh_preview()
        if self._waiting:
            self._waiting = None
            QTimer.singleShot(0, self._restore_window)

    def _restore_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def start_lasso(self):
        layer = self.layers.get("AANSLUITINGEN")
        if layer is None:
            self._error("De laag Aansluitingen geclusterd is niet gevonden.")
            return
        self.iface.setActiveLayer(layer)
        action = self.iface.actionSelectFreehand()
        if action is None:
            self._error("Vrije-handselectie is in deze QGIS-versie niet beschikbaar.")
            return
        self._waiting = "connections"
        action.trigger()
        self._set_status(
            "Teken nu in de kaart rond de aansluitingen. Na loslaten verschijnt "
            "dit venster weer."
        )
        self.showMinimized()

    def start_station_pick(self):
        layer = self.layers.get("STATIONS")
        if layer is None:
            self._error("De laag Stations ontwerp is niet gevonden.")
            return
        self.iface.setActiveLayer(layer)
        layer.removeSelection()
        action = self.iface.actionSelect()
        if action is None:
            self._error("De QGIS-selectietool is niet beschikbaar.")
            return
        self._waiting = "station"
        action.trigger()
        self._set_status("Klik nu precies één doelstation aan.")
        self.showMinimized()

    def clear_selections(self):
        for key in ("AANSLUITINGEN", "STATIONS"):
            layer = self.layers.get(key)
            if layer is not None:
                layer.removeSelection()
        self._refresh_preview()

    def _selected(self):
        connections = self.layers.get("AANSLUITINGEN")
        stations = self.layers.get("STATIONS")
        return (
            list(connections.getSelectedFeatures()) if connections is not None else [],
            list(stations.getSelectedFeatures()) if stations is not None else [],
        )

    def _refresh_preview(self):
        connections, stations = self._selected()
        valid_layers = all(self.layers.get(key) is not None for key in self.REQUIRED)
        valid = bool(connections) and len(stations) == 1 and valid_layers
        self.apply_button.setEnabled(valid)
        self.selection_label.setText(
            f"Geselecteerde aansluitingen: {len(connections)} • "
            f"geselecteerde doelstations: {len(stations)}"
        )
        self.selection_label.setStyleSheet(
            f"color: {'#2e7d32' if valid else '#b54800'}; font-weight: 700;"
        )
        if not valid:
            self.preview_label.setText(
                "Selecteer minimaal één aansluiting en precies één doelstation."
            )
            return

        station = stations[0]
        connection_layer = self.layers["AANSLUITINGEN"]
        station_layer = self.layers["STATIONS"]
        connection_cluster = self._field_name(connection_layer, ("Cluster",))
        station_cluster = self._field_name(station_layer, ("Cluster",))
        station_name = self._field_name(
            station_layer, ("Station", "Stationsnaam", "Naam", "Name")
        )
        design_field = self._field_name(
            connection_layer,
            ("Ontwerpstroom", "Ontwerpstro", "Ontwerpstr", "Hoogste Trafo"),
        )
        current_load_field = self._field_name(
            station_layer, ("Belast_A", "Belasting_A", "Clust_A")
        )
        max_load_field = self._field_name(station_layer, ("Max_A",))

        target_cluster = (
            str(station[station_cluster]).strip() if station_cluster else ""
        )
        target_name = (
            str(station[station_name]).strip()
            if station_name
            else target_cluster or f"FID {station.id()}"
        )
        moving = connections
        if connection_cluster and target_cluster:
            moving = [
                feature
                for feature in connections
                if str(feature[connection_cluster]).strip() != target_cluster
            ]

        source_clusters = []
        if connection_cluster:
            source_clusters = sorted(
                {
                    str(feature[connection_cluster]).strip()
                    for feature in moving
                    if str(feature[connection_cluster]).strip()
                }
            )

        moved_load = None
        if design_field:
            values = [self._number(feature[design_field]) for feature in moving]
            values = [value for value in values if value is not None]
            if values:
                moved_load = sum(values)

        current_load = (
            self._number(station[current_load_field]) if current_load_field else None
        )
        max_load = self._number(station[max_load_field]) if max_load_field else None
        projected = (
            current_load + moved_load
            if current_load is not None and moved_load is not None
            else None
        )

        lines = [
            f"<b>Doelstation:</b> {target_name}",
            f"<b>Werkelijk te verplaatsen:</b> {len(moving)} aansluiting(en)",
        ]
        if source_clusters:
            lines.append("<b>Broncluster(s):</b> " + ", ".join(source_clusters))
        if moved_load is not None:
            lines.append(f"<b>Toegevoegde ontwerpstroom:</b> {moved_load:.1f} A")
        if current_load is not None:
            lines.append(f"<b>Huidige doelbelasting:</b> {current_load:.1f} A")
        if projected is not None:
            lines.append(f"<b>Voorlopige doelbelasting:</b> {projected:.1f} A")
        if max_load is not None:
            lines.append(f"<b>Maximale doelbelasting:</b> {max_load:.1f} A")
            if projected is not None and max_load:
                pct = projected / max_load * 100.0
                color = "#2e7d32" if projected <= max_load else "#b00020"
                lines.append(
                    f"<b>Voorlopige benutting:</b> "
                    f"<span style='color:{color}'>{pct:.1f}%</span>"
                )
        lines.append(
            "<i>De definitieve capaciteit-, route- en topologiecontrole gebeurt "
            "bij Toepassen.</i>"
        )
        self.preview_label.setText("<br>".join(lines))

    def choose_backup_folder(self):
        start = self.backup_edit.text().strip()
        if not start:
            start = QgsProject.instance().homePath() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(
            self, "Kies map voor clustereditor-back-ups", start
        )
        if folder:
            self.backup_edit.setText(folder)

    def apply_change(self):
        connections, stations = self._selected()
        if not connections or len(stations) != 1:
            self._error("Selecteer minimaal één aansluiting en precies één doelstation.")
            return
        backup = self.backup_edit.text().strip()
        if not backup:
            home = QgsProject.instance().homePath()
            if not home:
                self._error("Kies eerst een back-upmap.")
                return
            backup = str(Path(home) / "cluster_editor_backups")
            self.backup_edit.setText(backup)

        self.apply_button.setEnabled(False)
        self._set_status("Clusterwijziging controleren en herberekenen…")
        try:
            result = processing.run(
                "lsnetontwerp:handmatige_clustercorrectie_selectie",
                {
                    "AANSLUITINGEN": self.layers["AANSLUITINGEN"],
                    "STATIONS": self.layers["STATIONS"],
                    "GEBIEDEN": self.layers["GEBIEDEN"],
                    "KABELROUTES": self.layers["KABELROUTES"],
                    "SLEUVEN": self.layers["SLEUVEN"],
                    "PLANGEBIED": self.layers.get("PLANGEBIED"),
                    "HELE_BRONCLUSTER_VERWIJDEREN": self.remove_source_cluster.isChecked(),
                    "ALLE_ROUTES_VERVERSEN": False,
                    "ALLEEN_GESELECTEERDE_ROUTES": False,
                    "ROUTE_CLUSTERS": "",
                    "ALLES_TOESTAAN": False,
                    "CONTROLE_MAX_ONTWERPSTROOM": self.check_capacity.isChecked(),
                    "CONTROLE_MAX_KABELLENGTE": self.check_route.isChecked(),
                    "CONTROLE_ROUTES_ANDERE_CLUSTERS": self.block_other.isChecked(),
                    "CONTROLE_GEDEELDE_ROUTES_VERTAKKINGEN": self.check_shared.isChecked(),
                    "MAX_ROUTE_M": float(self.max_route.value()),
                    "KNOOP_TOLERANTIE_M": 0.0,
                    "BACKUPMAP": backup,
                },
            )
            moved = int(result.get("VERPLAATST_AANTAL", len(connections)) or 0)
            target = str(result.get("DOELSTATION", "") or "").strip()
            self._set_status(
                f"Gereed: {moved} aansluiting(en) verplaatst"
                + (f" naar {target}." if target else ".")
                + " Routes, stationsstatistieken en clustergebieden zijn bijgewerkt."
            )
            self.status_label.setStyleSheet("color: #2e7d32; font-weight: 700;")
            self.iface.mapCanvas().refresh()
            self._refresh_preview()
        except Exception as exc:
            self._error(f"Clusterwijziging geweigerd of mislukt: {exc}")
        finally:
            self._refresh_preview()

    def _set_status(self, message, error=False):
        self.status_label.setText(message)
        self.status_label.setStyleSheet(
            "color: #b00020; font-weight: 700;" if error else ""
        )

    def _error(self, message):
        self._set_status(message, True)
        QMessageBox.warning(self, "Visuele clustereditor", message)

    def closeEvent(self, event):
        self._disconnect_signals()
        super().closeEvent(event)
