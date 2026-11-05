from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from qgis import processing
from qgis.PyQt.QtCore import Qt, QTimer, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
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
from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRendererCategory,
    QgsSpatialIndex,
    QgsVectorDataProvider,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)

from .algorithms.handmatige_cluster_correctie_tool import (
    HandmatigeClusterCorrectieAlgorithm,
)
from .ui_theme import apply_theme, branded_header, install_dialog_theme, normalize_page

try:
    NON_MODAL = Qt.WindowModality.NonModal
except AttributeError:
    NON_MODAL = Qt.NonModal


class VisueleClusterEditorDialog(QDialog):
    """Visuele editor voor bestaande én vooraf handmatig ontworpen clusters."""

    REQUIRED = ("AANSLUITINGEN", "STATIONS", "GEBIEDEN", "KABELROUTES", "SLEUVEN")
    MANUAL_LABEL_RE = re.compile(r"^H-(\d+)$", re.I)

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.layers = {}
        self.mode = "result"
        self.source_connections = None
        self.source_stations = None
        self.source_cables = None
        self._waiting = None
        self._station_draw_layer = None
        self._new_station_geometry = None
        self._new_station_geometry_crs = None
        self.requested_mode = None
        self._active_cluster_feedback = None

        self.setWindowTitle("LS Netontwerp – visuele handmatige clustereditor")
        self.setMinimumWidth(780)
        self.setWindowModality(NON_MODAL)

        root = QVBoxLayout(self)
        header = branded_header("Visuele handmatige clustereditor", "TechBase • aansluitingen verdelen en stations ontwerpen")
        root.addWidget(header)

        self.mode_label = QLabel()
        self.mode_label.setWordWrap(True)
        self.mode_label.setStyleSheet(
            "background:#eef3f6; border:1px solid #c8d3da; padding:7px;"
        )
        self.mode_label.setProperty("uiRole", "notice")
        root.addWidget(self.mode_label)

        selection_group = QGroupBox("1. Aansluitingen selecteren")
        self.selection_group = selection_group
        selection_layout = QVBoxLayout(selection_group)
        selection_buttons = QHBoxLayout()
        self.lasso_button = QPushButton("Aansluitingen met lasso selecteren")
        self.lasso_button.clicked.connect(self.start_lasso)
        clear_selection = QPushButton("Selectie wissen")
        clear_selection.clicked.connect(self.clear_connection_selection)
        selection_buttons.addWidget(self.lasso_button)
        selection_buttons.addWidget(clear_selection)
        selection_buttons.addStretch(1)
        selection_layout.addLayout(selection_buttons)
        self.selection_label = QLabel("Nog geen aansluitingen geselecteerd.")
        self.selection_label.setWordWrap(True)
        selection_layout.addWidget(self.selection_label)
        root.addWidget(selection_group)

        self.switch_group = QGroupBox("2A. Naar bestaand cluster verplaatsen")
        switch_layout = QVBoxLayout(self.switch_group)
        switch_row = QHBoxLayout()
        self.station_button = QPushButton("Doelstation aanklikken")
        self.station_button.clicked.connect(self.start_station_pick)
        self.apply_button = QPushButton("Naar geselecteerd cluster verplaatsen")
        self.apply_button.clicked.connect(self.apply_change)
        switch_row.addWidget(self.station_button)
        switch_row.addWidget(self.apply_button)
        switch_layout.addLayout(switch_row)
        self.preview_label = QLabel("Selecteer aansluitingen en één doelstation.")
        self.preview_label.setWordWrap(True)
        self.preview_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse if hasattr(Qt, "TextInteractionFlag") else Qt.TextSelectableByMouse)
        switch_layout.addWidget(self.preview_label)
        root.addWidget(self.switch_group)

        self.new_group = QGroupBox("2B. Nieuw cluster met nieuw station maken")
        new_layout = QFormLayout(self.new_group)
        self.new_cluster_name = QLineEdit()
        self.new_cluster_name.setPlaceholderText("Bijvoorbeeld H-01")
        self.new_cluster_kva = QDoubleSpinBox()
        self.new_cluster_kva.setRange(1.0, 5000.0)
        self.new_cluster_kva.setDecimals(1)
        self.new_cluster_kva.setValue(630.0)
        self.new_cluster_kva.setSuffix(" kVA")
        new_layout.addRow("Nieuwe clusternaam", self.new_cluster_name)
        new_layout.addRow("Vermogen nieuw station", self.new_cluster_kva)

        location_row = QHBoxLayout()
        self.auto_station_button = QPushButton("Station automatisch bij selectie")
        self.draw_station_button = QPushButton("Station op kaart plaatsen")
        self.auto_station_button.clicked.connect(self.auto_station_location)
        self.draw_station_button.clicked.connect(self.start_station_drawing)
        location_row.addWidget(self.auto_station_button)
        location_row.addWidget(self.draw_station_button)
        new_layout.addRow("Stationslocatie", location_row)
        self.location_label = QLabel("Nog geen nieuwe stationslocatie gekozen.")
        self.location_label.setWordWrap(True)
        new_layout.addRow("", self.location_label)

        self.create_cluster_button = QPushButton("Nieuw cluster maken")
        self.create_cluster_button.clicked.connect(self.create_new_cluster)
        new_layout.addRow("", self.create_cluster_button)
        root.addWidget(self.new_group)

        self.pre_group = QGroupBox("2C. Handmatige indeling vóór de clustering")
        pre_layout = QVBoxLayout(self.pre_group)
        self.pre_cluster_combo = QComboBox()
        self.pre_assign_button = QPushButton(
            "Geselecteerde aansluitingen aan handmatig cluster koppelen"
        )
        self.pre_assign_button.clicked.connect(self.assign_prepared_cluster)
        self.pre_clear_button = QPushButton(
            "Handmatige indeling van selectie herstellen/wissen"
        )
        self.pre_clear_button.clicked.connect(self.clear_prepared_assignment)
        self.pre_coverage_label = QLabel()
        self.pre_coverage_label.setWordWrap(True)
        pre_fields = QFormLayout()
        pre_fields.addRow("Bestaand handmatig cluster", self.pre_cluster_combo)
        pre_layout.addLayout(pre_fields)
        pre_layout.addWidget(self.pre_assign_button)
        pre_layout.addWidget(self.pre_clear_button)
        pre_layout.addWidget(self.pre_coverage_label)
        if hasattr(getattr(self, "_host", None), "_run_manual_clustering_from_editor"):
            self.dashboard_manual_cluster_button = QPushButton("Handmatige clustering uitvoeren")
            self.dashboard_manual_cluster_button.setToolTip("Maak de volledige clustering met exact de voorbereide H-xx-indeling")
            self.dashboard_manual_cluster_button.clicked.connect(self._host._run_manual_clustering_from_editor)
            pre_layout.addWidget(self.dashboard_manual_cluster_button)
        root.addWidget(self.pre_group)

        self.enforce_group = QGroupBox("2D. Voorbereide handmatige clusters afdwingen")
        enforce_layout = QVBoxLayout(self.enforce_group)
        enforce_note = QLabel(
            "Na de normale clustering kan deze knop alle H-xx-keuzes uit "
            "<b>Oud_gebied</b> exact naar hun gelijknamige stations zetten. "
            "Daarna blijven gewone clusterwissels via de lasso beschikbaar."
        )
        enforce_note.setWordWrap(True)
        enforce_layout.addWidget(enforce_note)
        self.enforce_button = QPushButton("Voorbereide handmatige clusters afdwingen")
        self.enforce_button.clicked.connect(self.enforce_prepared_clusters)
        enforce_layout.addWidget(self.enforce_button)
        root.addWidget(self.enforce_group)

        options_group = QGroupBox("3. Veiligheidscontroles")
        self.options_group = options_group
        options = QFormLayout(options_group)
        self.remove_source_cluster = QCheckBox(
            "Hele broncluster(s) samenvoegen en verwijderen"
        )
        self.remove_source_cluster.setToolTip(
            "Alle aansluitingen uit de broncluster(s) gaan dan naar het doelstation."
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
        refresh_button = QPushButton("Lagen/modus opnieuw zoeken")
        refresh_button.clicked.connect(self.refresh_layers)
        close_button = QPushButton("Sluiten")
        close_button.clicked.connect(self.close)
        buttons.addWidget(refresh_button)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

        from .cluster_editing_guide import ClusterEditingGuide
        self.guide = ClusterEditingGuide(self, root)
        self.refresh_layers()
        self.mode_label.setStyleSheet("")
        apply_theme(self)
        install_dialog_theme(self)
        if not hasattr(self, "_host"):
            normalize_page(self, self, (self.guide.commit, self.guide.cancel, close_button), home=False)
            self.guide.cancel.hide()

    @staticmethod
    def _field_name(layer, candidates):
        if layer is None:
            return None
        fields = {field.name().casefold(): field.name() for field in layer.fields()}
        for candidate in candidates:
            name = fields.get(str(candidate).casefold())
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

    @staticmethod
    def _project_vector_layers():
        project = QgsProject.instance()
        ordered = list(project.layerTreeRoot().layerOrder())
        if not ordered:
            ordered = list(project.mapLayers().values())
        return [
            layer
            for layer in ordered
            if isinstance(layer, QgsVectorLayer) and layer.isValid()
        ]

    @staticmethod
    def _is_point_layer(layer):
        return (
            layer is not None
            and QgsWkbTypes.geometryType(layer.wkbType())
            == QgsWkbTypes.PointGeometry
        )

    @staticmethod
    def _is_line_layer(layer):
        return (
            layer is not None
            and QgsWkbTypes.geometryType(layer.wkbType())
            == QgsWkbTypes.LineGeometry
        )

    def _find_source_layers(self):
        layers = self._project_vector_layers()
        points = [layer for layer in layers if self._is_point_layer(layer)]
        lines = [layer for layer in layers if self._is_line_layer(layer)]

        def choose(candidates, exact_names, contains, excludes=()):
            for name in exact_names:
                match = next(
                    (layer for layer in candidates if layer.name().casefold() == name.casefold()),
                    None,
                )
                if match is not None:
                    return match
            scored = []
            for order, layer in enumerate(candidates):
                text = layer.name().casefold()
                if any(exclude in text for exclude in excludes):
                    continue
                score = sum(1 for token in contains if token in text)
                if score:
                    scored.append((score, -order, layer))
            return max(scored, default=(0, 0, None))[2]

        self.source_connections = choose(
            points,
            (
                "LS-aansluitingen ontwerpstroom",
                "e_lv_service_connection",
                "LS-aansluitingen",
            ),
            ("aansluit", "service"),
            ("geclusterd", "scope"),
        )
        self.source_stations = choose(
            points,
            ("Bestaande stations (bron)", "Station locatie"),
            ("station",),
            ("ontwerp", "scope"),
        )
        self.source_cables = choose(
            lines,
            ("e_lv_map_cable", "Laagspanningskabels", "Sleuven geknipt/genood"),
            ("kabel", "sleuf"),
        )

    def _disconnect_signals(self):
        possible = [
            self.layers.get("AANSLUITINGEN"),
            self.layers.get("STATIONS"),
            self.source_connections,
            self.source_stations,
        ]
        for layer in possible:
            if layer is None:
                continue
            try:
                layer.selectionChanged.disconnect(self._selection_changed)
            except (TypeError, RuntimeError):
                pass

    def refresh_layers(self, requested_mode=None):
        if requested_mode in ("prepare", "result"):
            self.requested_mode = requested_mode
        self._disconnect_signals()
        project = QgsProject.instance()
        defaults = HandmatigeClusterCorrectieAlgorithm._project_layer_defaults()
        self.layers = {
            key: project.mapLayer(defaults.get(key)) if defaults.get(key) else None
            for key in (*self.REQUIRED, "PLANGEBIED")
        }
        result_ready = all(self.layers.get(key) is not None for key in self.REQUIRED)

        preparation_error = ""
        if self.requested_mode == "prepare":
            try:
                self._restore_preparation_layers()
            except Exception as exc:
                preparation_error = str(exc)
        self._find_source_layers()
        if result_ready and self.requested_mode != "prepare":
            self.mode = "result"
            self.mode_label.setText(
                "<b>Bestaande clustering aanpassen.</b> Selecteer aansluitingen en kies wat je wilt wijzigen."
            )
            for key in ("AANSLUITINGEN", "STATIONS"):
                layer = self.layers.get(key)
                if layer is not None:
                    layer.selectionChanged.connect(self._selection_changed)
            self.switch_group.setVisible(True)
            self.pre_group.setVisible(False)
            self.enforce_group.setVisible(self._prepared_result_labels_available())
        else:
            self.mode = "prepare"
            self.mode_label.setText(
                "<b>Modus: handmatig voorbereiden vóór clustering.</b> "
                "Selecteer aansluitingen, maak H-xx-clusters en plaats de bijbehorende "
                "stations. Daarna kun je stap 3 normaal uitvoeren en de voorbereide "
                "indeling in deze editor exact afdwingen."
            )
            if self.source_connections is not None:
                self.source_connections.selectionChanged.connect(self._selection_changed)
            self.switch_group.setVisible(False)
            self.pre_group.setVisible(True)
            self.enforce_group.setVisible(False)

        if not self.backup_edit.text().strip():
            home = project.homePath()
            if home:
                self.backup_edit.setText(str(Path(home) / "cluster_editor_backups"))

        if self.mode == "result":
            self._set_status(
                "Resultaatlagen gevonden. Kies een clusterwissel of maak een nieuw cluster."
            )
        elif self.source_connections is None or self.source_stations is None:
            missing = []
            if self.source_connections is None:
                missing.append("bronlaag met LS-aansluitingen")
            if self.source_stations is None:
                missing.append("bronlaag met stations")
            self._set_status(
                "Voorbereidingsmodus kan niet starten; ontbreekt: " + ", ".join(missing),
                True,
            )
        else:
            self._set_status(
                "Bronlagen gevonden. Handmatige clusters kunnen vóór stap 3 worden vastgelegd."
            )

        self._new_station_geometry = None
        self._new_station_geometry_crs = None
        self.location_label.setText("Nog geen nieuwe stationslocatie gekozen.")
        self.new_cluster_name.setText(self._next_manual_cluster_name())
        self._refresh_pre_cluster_choices()
        self.guide.refresh_layers()
        self._refresh_preview()
        if preparation_error:
            self._set_status("De bronlagen konden niet worden heropend: " + preparation_error, True)

    def _restore_preparation_layers(self):
        """Explicit preparation also works after opening a result project."""
        host = getattr(self, "_host", None)
        state = getattr(host, "prepared_state", None)
        if not state or not state.get("points_gpkg") or not state.get("import_gpkg"):
            return
        from .workflow import WorkflowRunner
        runner = WorkflowRunner(state["values"], lambda *_: None)
        points = runner._add_project_layer(
            runner._layer(state["points_gpkg"], state.get("points_layer", Path(state["points_gpkg"]).stem)),
            "LS-aansluitingen ontwerpstroom", True)
        points.setCustomProperty("LSNetontwerp/review_current_layer", True)
        for key, title, visible in (("layer_stations", "Bestaande stations (bron)", True),
            ("layer_main_cables", "Laagspanningskabels (bron)", True)):
            if state["values"].get(key):
                runner._add_project_layer(runner._layer(state["import_gpkg"], state["values"][key]), title, visible)

    def _selection_changed(self, *args):
        if self._waiting == 'source_station' and self.sender() is self.layers.get('STATIONS'):
            layer=self.layers['STATIONS'];features=layer.selectedFeatures()
            if len(features)!=1:return
            field=self._field_name(layer,('Cluster','Station','Stationsnaam'))
            name=str(features[0][field]).strip() if field else ''
            index=self.guide.cluster_combo.findData(name)
            if index<0:return
            self._waiting=None
            self.guide.cluster_combo.setCurrentIndex(index)
            self.guide.select_whole_cluster()
            layer.removeSelection()
            self._set_status(f'Hele cluster {name} geselecteerd. Klik nu het doelstation op de kaart.')
            self.start_station_pick()
            return
        try:
            current = self._active_connection_layer()
            if current is not None and QgsProject.instance().mapLayer(current.id()) is None:
                return
        except RuntimeError:
            return
        if hasattr(self, "guide") and self.sender() is self.layers.get("STATIONS"):
            self.guide._target_searching = False
        self._refresh_pre_cluster_choices()
        self._refresh_preview()
        if self._waiting in ("connections", "station"):
            self._waiting = None
            QTimer.singleShot(0, self._restore_window)

    def _restore_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _active_connection_layer(self):
        return (
            self.layers.get("AANSLUITINGEN")
            if self.mode == "result"
            else self.source_connections
        )

    def _selected_connections(self):
        layer = self._active_connection_layer()
        return list(layer.getSelectedFeatures()) if layer is not None else []

    def start_lasso(self):
        layer = self._active_connection_layer()
        if layer is None:
            self._error("De aansluitingenlaag is niet gevonden.")
            return
        self.iface.setActiveLayer(layer)
        layer.removeSelection()
        action = self.iface.actionSelectFreehand()
        if action is None:
            self._error("Vrije-handselectie is in deze QGIS-versie niet beschikbaar.")
            return
        self._waiting = "connections"
        action.trigger()
        self._set_status(
            "Teken nu in de kaart rond de gewenste aansluitingen. "
            "De nieuwe lasso vervangt de vorige selectie."
        )
        self.showMinimized()

    def start_station_pick(self):
        layer = self.layers.get("STATIONS")
        if self.mode != "result" or layer is None:
            self._error("Doelstations kunnen pas na het maken van clusterresultaten worden gekozen.")
            return
        self.iface.setActiveLayer(layer)
        layer.removeSelection()
        action = self.iface.actionSelect()
        if action is None:
            self._error("De QGIS-selectietool is niet beschikbaar.")
            return
        self._waiting = "station"
        action.trigger()
        self._set_status("Klik nu precies één bestaand doelstation aan.")
        self.showMinimized()

    def start_source_station_pick(self):
        layer=self.layers.get('STATIONS')
        if self.iface is None or self.mode!='result' or layer is None:
            self._error('Open een clusterresultaat in QGIS om een bronstation aan te klikken.');return
        layer.removeSelection();self.iface.setActiveLayer(layer)
        self._waiting='source_station'
        self.iface.actionSelect().trigger()
        self._set_status('Klik één bronstation: alle aansluitingen van dat cluster worden geselecteerd. Daarna kies je het doelstation.')
        self.showMinimized()

    def clear_connection_selection(self):
        layer = self._active_connection_layer()
        if layer is not None:
            layer.removeSelection()
        if self.mode == "result" and self.layers.get("STATIONS") is not None:
            self.layers["STATIONS"].removeSelection()
        self._refresh_preview()

    def _prepared_labels_from_layer(self, layer, field_name):
        if layer is None or not field_name or layer.fields().lookupField(field_name) < 0:
            return []
        return sorted(
            {
                str(feature[field_name]).strip().upper()
                for feature in layer.getFeatures()
                if self.MANUAL_LABEL_RE.fullmatch(str(feature[field_name]).strip())
            },
            key=lambda value: int(self.MANUAL_LABEL_RE.fullmatch(value).group(1)),
        )

    def _next_manual_cluster_name(self):
        used = set()
        for layer, field in (
            (self.source_connections, "GebiedLabel"),
            (self.source_stations, self._source_station_name_field()),
            (self.layers.get("STATIONS"), "Cluster"),
        ):
            if layer is None or not field or layer.fields().lookupField(field) < 0:
                continue
            for feature in layer.getFeatures():
                value = str(feature[field]).strip().upper()
                match = self.MANUAL_LABEL_RE.fullmatch(value)
                if match:
                    used.add(int(match.group(1)))
        number = 1
        while number in used:
            number += 1
        return f"H-{number:02d}"

    def _normalize_new_cluster_name(self):
        text = self.new_cluster_name.text().strip().upper()
        if not text:
            text = self._next_manual_cluster_name()
            self.new_cluster_name.setText(text)
        if not self.MANUAL_LABEL_RE.fullmatch(text):
            raise RuntimeError(
                "Gebruik voor handmatige clusters een naam als H-01, H-02, enzovoort."
            )
        return text

    def _refresh_preview(self):
        if hasattr(self, "guide"):
            self.guide.refresh_preview()
            return
        connections = self._selected_connections()
        self.selection_label.setText(
            f"Geselecteerde aansluitingen: {len(connections)}"
        )
        self.selection_label.setStyleSheet(
            f"color: {'#2e7d32' if connections else '#b54800'}; font-weight:700;"
        )
        self.create_cluster_button.setEnabled(
            bool(connections)
            and (
                self.mode == "result"
                or (self.source_connections is not None and self.source_stations is not None)
            )
        )

        if self.mode != "result":
            self.apply_button.setEnabled(False)
            self.preview_label.setText("Clusterwissels naar bestaande stations zijn na stap 3 beschikbaar.")
            self._refresh_pre_coverage()
            return

        stations_layer = self.layers.get("STATIONS")
        stations = (
            list(stations_layer.getSelectedFeatures())
            if stations_layer is not None
            else []
        )
        valid = bool(connections) and len(stations) == 1
        self.apply_button.setEnabled(valid)
        if not valid:
            self.preview_label.setText(
                "Selecteer minimaal één aansluiting en precies één doelstation."
            )
            return

        station = stations[0]
        connection_layer = self.layers["AANSLUITINGEN"]
        station_cluster = self._field_name(stations_layer, ("Cluster",))
        connection_cluster = self._field_name(connection_layer, ("Cluster",))
        station_name = self._field_name(
            stations_layer, ("Station", "Stationsnaam", "Naam", "Name", "Cluster")
        )
        design_field = self._field_name(
            connection_layer,
            ("Ontwerp_A", "Ontwerpstroom", "Ontwerpstro", "Ontwerpstr", "Hoogste Trafo"),
        )
        current_load_field = self._field_name(
            stations_layer, ("Belast_A", "Belasting_A", "Clust_A")
        )
        max_load_field = self._field_name(stations_layer, ("Max_A",))

        target_cluster = str(station[station_cluster]).strip() if station_cluster else ""
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
        source_clusters = (
            sorted(
                {
                    str(feature[connection_cluster]).strip()
                    for feature in moving
                    if str(feature[connection_cluster]).strip()
                }
            )
            if connection_cluster
            else []
        )
        moved_load = None
        if design_field:
            values = [self._number(feature[design_field]) for feature in moving]
            values = [value for value in values if value is not None]
            if values:
                moved_load = sum(values)
        current_load = self._number(station[current_load_field]) if current_load_field else None
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
            "<i>De definitieve capaciteit-, route- en topologiecontrole gebeurt bij Toepassen.</i>"
        )
        self.preview_label.setText("<br>".join(lines))

    def _target_station_layer_for_location(self):
        return self.layers.get("STATIONS") if self.mode == "result" else self.source_stations

    def _routing_cable_layer(self):
        return self.layers.get("SLEUVEN") if self.mode == "result" else self.source_cables

    def _snap_geometry_to_cable(self, geometry, geometry_crs):
        cable_layer = self._routing_cable_layer()
        if (
            cable_layer is None
            or geometry is None
            or geometry.isNull()
            or geometry.isEmpty()
        ):
            return QgsGeometry(geometry)
        working = QgsGeometry(geometry)
        if geometry_crs != cable_layer.crs():
            working.transform(
                QgsCoordinateTransform(
                    geometry_crs, cable_layer.crs(), QgsProject.instance()
                )
            )
        point = working.asPoint()
        index = QgsSpatialIndex(cable_layer.getFeatures())
        ids = index.nearestNeighbor(QgsPointXY(point), 8)
        best_geometry = None
        best_distance = None
        for feature_id in ids:
            feature = cable_layer.getFeature(feature_id)
            if not feature.isValid() or not feature.hasGeometry():
                continue
            candidate = feature.geometry().nearestPoint(working)
            distance = candidate.distance(working)
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_geometry = candidate
        if best_geometry is None:
            return QgsGeometry(geometry)
        if cable_layer.crs() != geometry_crs:
            best_geometry.transform(
                QgsCoordinateTransform(
                    cable_layer.crs(), geometry_crs, QgsProject.instance()
                )
            )
        return best_geometry

    def auto_station_location(self):
        selected = self._selected_connections()
        target_layer = self._target_station_layer_for_location()
        source_layer = self._active_connection_layer()
        if not selected:
            self._error("Selecteer eerst aansluitingen.")
            return
        if target_layer is None or source_layer is None:
            self._error("De stations- of aansluitingenlaag ontbreekt.")
            return
        transformer = (
            QgsCoordinateTransform(
                source_layer.crs(), target_layer.crs(), QgsProject.instance()
            )
            if source_layer.crs() != target_layer.crs()
            else None
        )
        x_values = []
        y_values = []
        for feature in selected:
            if not feature.hasGeometry():
                continue
            geometry = feature.geometry().centroid()
            if transformer is not None:
                geometry.transform(transformer)
            point = geometry.asPoint()
            x_values.append(float(point.x()))
            y_values.append(float(point.y()))
        if not x_values:
            self._error("De selectie bevat geen bruikbare puntgeometrie.")
            return
        point_geometry = QgsGeometry.fromPointXY(
            QgsPointXY(sum(x_values) / len(x_values), sum(y_values) / len(y_values))
        )
        point_geometry = self._snap_geometry_to_cable(point_geometry, target_layer.crs())
        self._new_station_geometry = point_geometry
        self._new_station_geometry_crs = target_layer.crs()
        point = point_geometry.asPoint()
        self.location_label.setText(
            f"Automatisch station op kabel: X {point.x():.2f}, Y {point.y():.2f}"
        )
        self.location_label.setStyleSheet("color:#2e7d32; font-weight:700;")

    def start_station_drawing(self):
        if self._station_draw_layer is not None:
            self._clear_station_draw_layer()
            self._set_status("Plaatsen van het nieuwe station geannuleerd.")
            return
        target_layer = self._target_station_layer_for_location()
        if target_layer is None:
            self._error("Geen stationslaag beschikbaar voor de stationslocatie.")
            return
        if self.iface is None:
            self._error("Interactief plaatsen vereist QGIS Desktop.")
            return
        crs_text = target_layer.crs().authid() or target_layer.crs().toWkt()
        draw_layer = QgsVectorLayer(
            f"Point?crs={crs_text}", "Nieuw handmatig station (tekenen)", "memory"
        )
        if not draw_layer.isValid():
            self._error("De tijdelijke stationslaag kon niet worden gemaakt.")
            return
        symbol = draw_layer.renderer().symbol()
        symbol.setColor(QColor("#f47700"))
        if hasattr(symbol, "setSize"):
            symbol.setSize(5.0)
        QgsProject.instance().addMapLayer(draw_layer)
        draw_layer.startEditing()
        self._station_draw_layer = draw_layer
        draw_layer.featureAdded.connect(self._on_station_drawn)
        self.iface.setActiveLayer(draw_layer)
        self.iface.actionAddFeature().trigger()
        self.draw_station_button.setText("Plaatsen annuleren")
        self._set_status(
            "Klik één locatie voor het nieuwe station. De locatie wordt daarna "
            "automatisch op het dichtstbijzijnde kabeldeel gesnapt."
        )
        self.showMinimized()

    def _on_station_drawn(self, feature_id):
        QTimer.singleShot(0, self._finish_station_drawing)

    def _finish_station_drawing(self):
        draw_layer = self._station_draw_layer
        if draw_layer is None:
            return
        try:
            draw_layer.featureAdded.disconnect(self._on_station_drawn)
        except (TypeError, RuntimeError):
            pass
        if not draw_layer.commitChanges():
            self._error("De gekozen stationslocatie kon niet worden vastgelegd.")
            self._clear_station_draw_layer()
            return
        features = [
            feature
            for feature in draw_layer.getFeatures()
            if feature.isValid() and feature.hasGeometry()
        ]
        if not features:
            self._error("Geen geldige stationslocatie getekend.")
            self._clear_station_draw_layer()
            return
        target_layer = self._target_station_layer_for_location()
        geometry = self._snap_geometry_to_cable(
            features[-1].geometry(), draw_layer.crs()
        )
        if draw_layer.crs() != target_layer.crs():
            geometry.transform(
                QgsCoordinateTransform(
                    draw_layer.crs(), target_layer.crs(), QgsProject.instance()
                )
            )
        self._new_station_geometry = geometry
        self._new_station_geometry_crs = target_layer.crs()
        point = geometry.asPoint()
        self.location_label.setText(
            f"Handmatig station, gesnapt op kabel: X {point.x():.2f}, Y {point.y():.2f}"
        )
        self.location_label.setStyleSheet("color:#2e7d32; font-weight:700;")
        self._clear_station_draw_layer()
        self._restore_window()
        self._refresh_preview()

    def _clear_station_draw_layer(self):
        draw_layer = self._station_draw_layer
        if draw_layer is None:
            self.draw_station_button.setText("Station op kaart plaatsen")
            return
        try:
            draw_layer.featureAdded.disconnect(self._on_station_drawn)
        except (TypeError, RuntimeError):
            pass
        if draw_layer.isEditable():
            draw_layer.rollBack()
        if self.iface is not None:
            self.iface.actionPan().trigger()
        if draw_layer.id() in QgsProject.instance().mapLayers():
            QgsProject.instance().removeMapLayer(draw_layer.id())
        self._station_draw_layer = None
        self.draw_station_button.setText("Station op kaart plaatsen")

    def choose_backup_folder(self):
        start = self.backup_edit.text().strip()
        if not start:
            start = QgsProject.instance().homePath() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(
            self, "Kies map voor clustereditor-back-ups", start
        )
        if folder:
            self.backup_edit.setText(folder)

    def _backup_folder(self):
        folder = self.backup_edit.text().strip()
        if not folder:
            home = QgsProject.instance().homePath()
            if not home:
                raise RuntimeError("Kies eerst een back-upmap.")
            folder = str(Path(home) / "cluster_editor_backups")
            self.backup_edit.setText(folder)
        path = Path(folder)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _write_snapshot(self, layers, prefix):
        folder = self._backup_folder()
        target = folder / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S_%f}.gpkg"
        first = True
        for layer_name, layer in layers:
            if layer is None or not layer.isValid():
                continue
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = layer_name
            options.fileEncoding = "UTF-8"
            options.actionOnExistingFile = (
                QgsVectorFileWriter.CreateOrOverwriteFile
                if first
                else QgsVectorFileWriter.CreateOrOverwriteLayer
            )
            result = QgsVectorFileWriter.writeAsVectorFormatV3(
                layer,
                str(target),
                QgsProject.instance().transformContext(),
                options,
            )
            if result[0] != QgsVectorFileWriter.NoError:
                raise RuntimeError(
                    f"Back-up van {layer.name()} mislukt: {result[1]}"
                )
            first = False
        if first:
            raise RuntimeError("Er waren geen lagen om te back-uppen.")
        return target

    def _run_existing_correction(self, remove_source_cluster=None):
        remove_source = (
            self.remove_source_cluster.isChecked()
            if remove_source_cluster is None
            else bool(remove_source_cluster)
        )
        return processing.run(
            "lsnetontwerp:handmatige_clustercorrectie_selectie",
            {
                "AANSLUITINGEN": self.layers["AANSLUITINGEN"],
                "STATIONS": self.layers["STATIONS"],
                "GEBIEDEN": self.layers["GEBIEDEN"],
                "KABELROUTES": self.layers["KABELROUTES"],
                "SLEUVEN": self.layers["SLEUVEN"],
                "PLANGEBIED": self.layers.get("PLANGEBIED"),
                "HELE_BRONCLUSTER_VERWIJDEREN": remove_source,
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
                "BACKUPMAP": str(self._backup_folder()),
            },
            feedback=self._active_cluster_feedback,
        )

    def apply_change(self):
        if self.mode != "result":
            self._error("Clusterwisselen naar een resultaatcluster is pas na stap 3 beschikbaar.")
            return
        connections = self._selected_connections()
        stations = list(self.layers["STATIONS"].getSelectedFeatures())
        if not connections or len(stations) != 1:
            self._error("Selecteer minimaal één aansluiting en precies één doelstation.")
            return
        self.apply_button.setEnabled(False)
        self._set_status("Clusterwijziging controleren en herberekenen…")
        try:
            result = self._run_existing_correction()
            moved = int(result.get("VERPLAATST_AANTAL", len(connections)) or 0)
            target = str(result.get("DOELSTATION", "") or "").strip()
            self._set_status(
                f"Gereed: {moved} aansluiting(en) verplaatst"
                + (f" naar {target}." if target else ".")
                + " Routes, statistieken en clustergebieden zijn bijgewerkt."
            )
            self.status_label.setStyleSheet("color:#2e7d32; font-weight:700;")
            if self.iface is not None:
                self.iface.mapCanvas().refresh()
        except Exception as exc:
            self._error(f"Clusterwijziging geweigerd of mislukt: {exc}")
        finally:
            self._refresh_preview()

    @staticmethod
    def _set_feature_if_present(feature, layer, field, value):
        index = layer.fields().lookupField(field)
        if index >= 0:
            feature.setAttribute(index, value)

    def _summary_values(self, cluster, kva):
        max_a = float(kva) / 0.23 / 3.0
        return {
            "Cluster": cluster,
            "Type": "Nieuw",
            "Status": f"Nieuw {kva:g}Kva",
            "KVA": float(kva),
            "Max_A": max_a,
            "Belast_A": 0.0,
            "Benut_pct": 0.0,
            "Aantal": 0,
            "Gem_route": 0.0,
            "Max_route": 0.0,
            "Route_km": 0.0,
            "Kandidaat": "Handmatig",
            "Plaatsing": "Handmatig",
        }

    def _add_feature(self, layer, values, geometry=None):
        if layer is None or not layer.isValid():
            raise RuntimeError("Een benodigde resultaatlaag is ongeldig.")
        provider = layer.dataProvider()
        if not provider.capabilities() & QgsVectorDataProvider.AddFeatures:
            raise RuntimeError(f"Laag '{layer.name()}' ondersteunt geen nieuwe objecten.")
        feature = QgsFeature(layer.fields())
        for field, value in values.items():
            self._set_feature_if_present(feature, layer, field, value)
        if geometry is not None and not geometry.isNull() and not geometry.isEmpty():
            feature.setGeometry(geometry)
        ok, added = provider.addFeatures([feature])
        if not ok:
            raise RuntimeError(f"Nieuw object toevoegen aan '{layer.name()}' is mislukt.")
        provider.forceReload()
        layer.updateExtents()
        layer.triggerRepaint()
        if added:
            return int(added[0].id())
        cluster_field = layer.fields().lookupField("Cluster")
        if cluster_field >= 0 and "Cluster" in values:
            matches = [
                int(candidate.id())
                for candidate in layer.getFeatures()
                if str(candidate.attribute(cluster_field)).strip() == str(values["Cluster"])
            ]
            if matches:
                return matches[-1]
        raise RuntimeError(f"Nieuw object in '{layer.name()}' kon niet worden teruggevonden.")

    def _delete_cluster_placeholders(self, cluster):
        for key in ("STATIONS", "GEBIEDEN", "KABELROUTES"):
            layer = self.layers.get(key)
            if layer is None:
                continue
            field = layer.fields().lookupField("Cluster")
            if field < 0:
                continue
            ids = [
                int(feature.id())
                for feature in layer.getFeatures()
                if str(feature.attribute(field)).strip() == cluster
            ]
            if not ids:
                continue
            provider = layer.dataProvider()
            if provider.capabilities() & QgsVectorDataProvider.DeleteFeatures:
                provider.deleteFeatures(ids)
                provider.forceReload()
                layer.updateExtents()
                layer.triggerRepaint()

    def _result_cluster_exists(self, cluster):
        station_layer = self.layers.get("STATIONS")
        if station_layer is None:
            return False
        field = station_layer.fields().lookupField("Cluster")
        return any(
            str(feature.attribute(field)).strip().casefold() == cluster.casefold()
            for feature in station_layer.getFeatures()
        ) if field >= 0 else False

    def _source_area_geometry_for_selection(self):
        area_layer = self.layers["GEBIEDEN"]
        connections = self._selected_connections()
        connection_layer = self.layers["AANSLUITINGEN"]
        cluster_field = connection_layer.fields().lookupField("Cluster")
        area_cluster_field = area_layer.fields().lookupField("Cluster")
        source_cluster = (
            str(connections[0].attribute(cluster_field)).strip()
            if connections and cluster_field >= 0
            else ""
        )
        if source_cluster and area_cluster_field >= 0:
            for feature in area_layer.getFeatures():
                if str(feature.attribute(area_cluster_field)).strip() == source_cluster:
                    return QgsGeometry(feature.geometry())
        first = next(area_layer.getFeatures(), None)
        return QgsGeometry(first.geometry()) if first is not None else QgsGeometry()

    def _add_cluster_renderer_category(self, cluster):
        hue = sum((index + 1) * ord(char) for index, char in enumerate(cluster)) % 360
        color = QColor.fromHsv(hue, 170, 220)
        for key in ("AANSLUITINGEN", "GEBIEDEN", "KABELROUTES"):
            layer = self.layers.get(key)
            if layer is None:
                continue
            renderer = layer.renderer()
            if not isinstance(renderer, QgsCategorizedSymbolRenderer):
                continue
            if str(renderer.classAttribute()).strip('"').casefold() != "cluster":
                continue
            existing = {str(category.value()).strip() for category in renderer.categories()}
            if cluster in existing:
                continue
            categories = renderer.categories()
            if not categories:
                continue
            symbol = categories[0].symbol().clone()
            symbol.setColor(color)
            renderer.addCategory(QgsRendererCategory(cluster, symbol, cluster))
            layer.setRenderer(renderer)
            layer.triggerRepaint()

    def _create_result_cluster(self, cluster, kva):
        if self._new_station_geometry is None:
            self.auto_station_location()
        if self._new_station_geometry is None:
            raise RuntimeError("Kies eerst een locatie voor het nieuwe station.")
        if self._result_cluster_exists(cluster):
            raise RuntimeError(f"Cluster {cluster} bestaat al.")

        snapshot = self._write_snapshot(
            [
                ("aansluitingen_geclusterd", self.layers["AANSLUITINGEN"]),
                ("stations_ontwerp", self.layers["STATIONS"]),
                ("clustergebieden", self.layers["GEBIEDEN"]),
                ("cluster_kabelroutes", self.layers["KABELROUTES"]),
                ("sleuven_genood", self.layers["SLEUVEN"]),
            ],
            "voor_nieuw_cluster",
        )
        values = self._summary_values(cluster, kva)
        values["Volgnummer"] = self.layers["STATIONS"].featureCount() + 1
        point = self._new_station_geometry.asPoint()
        values["Net_X"] = float(point.x())
        values["Net_Y"] = float(point.y())

        station_id = None
        try:
            station_id = self._add_feature(
                self.layers["STATIONS"], values, QgsGeometry(self._new_station_geometry)
            )
            area_id = self._add_feature(
                self.layers["GEBIEDEN"], values, self._source_area_geometry_for_selection()
            )
            route_id = self._add_feature(
                self.layers["KABELROUTES"], values, QgsGeometry()
            )
            _ = (area_id, route_id)
            self.layers["STATIONS"].selectByIds([station_id])
            result = self._run_existing_correction(remove_source_cluster=False)
            self._add_cluster_renderer_category(cluster)
            HandmatigeClusterCorrectieAlgorithm._refresh_project_layout_after_correction(
                self.layers["AANSLUITINGEN"],
                self.layers["STATIONS"],
                self.layers["GEBIEDEN"],
                self.layers["KABELROUTES"],
            )
            self._set_status(
                f"Gereed: nieuw cluster {cluster} met station {kva:g} kVA gemaakt. "
                f"{int(result.get('VERPLAATST_AANTAL', 0) or 0)} aansluiting(en) "
                f"zijn toegewezen. Extra herstelkopie: {snapshot}"
            )
            self.status_label.setStyleSheet("color:#2e7d32; font-weight:700;")
            self._new_station_geometry = None
            self._new_station_geometry_crs = None
            self.location_label.setText("Nog geen nieuwe stationslocatie gekozen.")
            self.new_cluster_name.setText(self._next_manual_cluster_name())
            if self.iface is not None:
                self.iface.mapCanvas().refresh()
        except Exception:
            self._delete_cluster_placeholders(cluster)
            raise

    def _source_station_name_field(self):
        layer = self.source_stations
        if layer is None:
            return None
        custom = str(
            layer.customProperty("LSNetontwerp/station_name_field", "")
        ).strip()
        return self._field_name(
            layer, tuple(value for value in (custom, "Station", "Stationsnaam", "Stationsnaa", "Naam", "Name") if value)
        )

    def _source_station_capacity_field(self):
        layer = self.source_stations
        if layer is None:
            return None
        custom = str(
            layer.customProperty("LSNetontwerp/station_capacity_field", "")
        ).strip()
        return self._field_name(
            layer,
            tuple(
                value
                for value in (custom, "trafo_power", "KVA", "Vermogen", "Status")
                if value
            ),
        )

    def _ensure_pre_fields(self):
        layer = self.source_connections
        if layer is None:
            raise RuntimeError("De bronlaag met aansluitingen ontbreekt.")
        provider = layer.dataProvider()
        missing = []
        if layer.fields().lookupField("GebiedLabel") < 0:
            missing.append(QgsField("GebiedLabel", QVariant.String, len=80))
        if layer.fields().lookupField("GebiedOrig") < 0:
            missing.append(QgsField("GebiedOrig", QVariant.String, len=80))
        if missing:
            if not provider.capabilities() & QgsVectorDataProvider.AddAttributes:
                raise RuntimeError(
                    f"Laag '{layer.name()}' kan geen handmatige clustervelden toevoegen."
                )
            if not provider.addAttributes(missing):
                raise RuntimeError("GebiedLabel/GebiedOrig konden niet worden toegevoegd.")
            layer.updateFields()

    def _set_prepared_label(self, cluster):
        self._ensure_pre_fields()
        layer = self.source_connections
        selected_ids = list(layer.selectedFeatureIds())
        if not selected_ids:
            raise RuntimeError("Selecteer eerst aansluitingen.")
        label_index = layer.fields().lookupField("GebiedLabel")
        original_index = layer.fields().lookupField("GebiedOrig")
        changes = {}
        for feature in layer.getSelectedFeatures():
            old_label = str(feature.attribute(label_index) or "").strip()
            original = str(feature.attribute(original_index) or "").strip()
            values = {label_index: cluster}
            if not original and not self.MANUAL_LABEL_RE.fullmatch(old_label):
                values[original_index] = old_label
            changes[int(feature.id())] = values
        if not layer.dataProvider().changeAttributeValues(changes):
            raise RuntimeError("Handmatige GebiedLabel-waarden konden niet worden opgeslagen.")
        layer.dataProvider().forceReload()
        layer.selectByIds(selected_ids)
        layer.triggerRepaint()

    def _add_source_station(self, cluster, kva):
        layer = self.source_stations
        name_field = self._source_station_name_field()
        capacity_field = self._source_station_capacity_field()
        if layer is None or not name_field or not capacity_field:
            raise RuntimeError(
                "Stationsnaam- of capaciteitskolom van de bronstations kon niet worden gevonden."
            )
        if self._new_station_geometry is None:
            self.auto_station_location()
        if self._new_station_geometry is None:
            raise RuntimeError("Kies eerst een nieuwe stationslocatie.")

        for feature in layer.getFeatures():
            if str(feature[name_field]).strip().casefold() == cluster.casefold():
                raise RuntimeError(f"Bronstation {cluster} bestaat al.")

        values = {name_field: cluster}
        capacity_kind = capacity_field.casefold()
        values[capacity_field] = (
            f"{kva:g} KVA" if capacity_kind == "status" else float(kva)
        )
        for alias in ("Station", "Stationsnaam", "Stationsnaa", "Naam"):
            if layer.fields().lookupField(alias) >= 0:
                values[alias] = cluster
        if layer.fields().lookupField("Status") >= 0:
            values["Status"] = f"{kva:g} KVA"
        if layer.fields().lookupField("KVA") >= 0:
            values["KVA"] = float(kva)
        if layer.fields().lookupField("Max_A") >= 0:
            values["Max_A"] = float(kva) / 0.23 / 3.0
        if layer.fields().lookupField("Type") >= 0:
            values["Type"] = "Nieuw"
        return self._add_feature(layer, values, QgsGeometry(self._new_station_geometry))

    def _delete_source_station(self, cluster):
        layer = self.source_stations
        name_field = self._source_station_name_field()
        if layer is None or not name_field:
            return
        ids = [
            int(feature.id())
            for feature in layer.getFeatures()
            if str(feature[name_field]).strip().casefold() == cluster.casefold()
        ]
        if ids and layer.dataProvider().capabilities() & QgsVectorDataProvider.DeleteFeatures:
            layer.dataProvider().deleteFeatures(ids)
            layer.dataProvider().forceReload()
            layer.updateExtents()
            layer.triggerRepaint()

    def _create_prepared_cluster(self, cluster, kva):
        if self.source_connections is None or self.source_stations is None:
            raise RuntimeError("Bronlagen voor handmatige voorbereiding ontbreken.")
        name_field = self._source_station_name_field()
        if name_field and any(str(f[name_field]).strip().casefold() == cluster.casefold() for f in self.source_stations.getFeatures()):
            raise RuntimeError(f"Handmatig cluster {cluster} bestaat al. Kies Toewijzen om aansluitingen eraan toe te voegen.")
        snapshot = self._write_snapshot(
            [
                ("aansluitingen_bron", self.source_connections),
                ("stations_bron", self.source_stations),
            ],
            "voor_handmatig_cluster",
        )
        self._ensure_pre_fields()
        try:
            self._add_source_station(cluster, kva)
            self._set_prepared_label(cluster)
        except Exception as exc:
            self._delete_source_station(cluster)
            raise RuntimeError(
                f"Handmatig cluster kon niet volledig worden opgeslagen. "
                f"Gebruik zo nodig de herstelkopie {snapshot}. Technische melding: {exc}"
            ) from exc
        self._set_status(
            f"Handmatig cluster {cluster} is voorbereid: geselecteerde aansluitingen "
            f"hebben GebiedLabel={cluster} en een bronstation van {kva:g} kVA is toegevoegd. "
            f"Herstelkopie: {snapshot}"
        )
        self.status_label.setStyleSheet("color:#2e7d32; font-weight:700;")
        self._new_station_geometry = None
        self.location_label.setText("Nog geen nieuwe stationslocatie gekozen.")
        self.new_cluster_name.setText(self._next_manual_cluster_name())
        self._refresh_pre_cluster_choices()
        if self.iface is not None:
            self.iface.mapCanvas().refresh()

    def _refresh_pre_cluster_choices(self):
        if self.source_connections is None:
            self.pre_cluster_combo.clear()
            self._refresh_pre_coverage()
            return
        labels = self._prepared_labels_from_layer(
            self.source_connections, "GebiedLabel"
        )
        previous = self.pre_cluster_combo.currentText()
        self.pre_cluster_combo.blockSignals(True)
        self.pre_cluster_combo.clear()
        self.pre_cluster_combo.addItems(labels)
        index = self.pre_cluster_combo.findText(previous)
        if index >= 0:
            self.pre_cluster_combo.setCurrentIndex(index)
        self.pre_cluster_combo.blockSignals(False)
        self.pre_assign_button.setEnabled(bool(labels) and self.mode == "prepare")
        self.pre_clear_button.setEnabled(self.mode == "prepare")
        self._refresh_pre_coverage()

    def _refresh_pre_coverage(self):
        layer = self.source_connections
        if layer is None or layer.fields().lookupField("GebiedLabel") < 0:
            self.pre_coverage_label.setText("Nog geen handmatige clusters vastgelegd.")
            return
        field = layer.fields().lookupField("GebiedLabel")
        total = layer.featureCount()
        manual = sum(
            1
            for feature in layer.getFeatures()
            if self.MANUAL_LABEL_RE.fullmatch(str(feature.attribute(field)).strip())
        )
        pct = 100.0 * manual / total if total else 0.0
        suffix = (
            " Volledig handmatig voorbereid."
            if total and manual == total
            else " Overige aansluitingen kunnen later automatisch worden verdeeld."
        )
        self.pre_coverage_label.setText(
            f"{manual} van {total} aansluitingen ({pct:.1f}%) handmatig gelabeld.{suffix}"
        )

    def assign_prepared_cluster(self):
        if self.mode != "prepare":
            self._error("Deze functie is bedoeld vóór het maken van clusterresultaten.")
            return
        cluster = self.pre_cluster_combo.currentText().strip()
        if not cluster:
            self._error("Maak of kies eerst een handmatig H-xx-cluster.")
            return
        try:
            snapshot = self._write_snapshot(
                [("aansluitingen_bron", self.source_connections)],
                "voor_clusterwissel_voorbereiding",
            )
            self._set_prepared_label(cluster)
            self._set_status(
                f"Geselecteerde aansluitingen zijn voorbereid voor {cluster}. "
                f"Herstelkopie: {snapshot}"
            )
            self.status_label.setStyleSheet("color:#2e7d32; font-weight:700;")
            self._refresh_pre_cluster_choices()
        except Exception as exc:
            self._error(f"Handmatig cluster wisselen mislukt: {exc}")

    def clear_prepared_assignment(self):
        if self.mode != "prepare" or self.source_connections is None:
            return
        try:
            self._ensure_pre_fields()
            layer = self.source_connections
            selected = list(layer.getSelectedFeatures())
            if not selected:
                raise RuntimeError("Selecteer eerst aansluitingen.")
            snapshot = self._write_snapshot(
                [("aansluitingen_bron", layer)],
                "voor_handmatige_indeling_wissen",
            )
            label_index = layer.fields().lookupField("GebiedLabel")
            original_index = layer.fields().lookupField("GebiedOrig")
            changes = {}
            ids = []
            for feature in selected:
                ids.append(int(feature.id()))
                original = str(feature.attribute(original_index) or "").strip()
                changes[int(feature.id())] = {label_index: original}
            if not layer.dataProvider().changeAttributeValues(changes):
                raise RuntimeError("De oorspronkelijke gebiedslabels konden niet worden hersteld.")
            layer.dataProvider().forceReload()
            layer.selectByIds(ids)
            layer.triggerRepaint()
            self._set_status(
                f"Handmatige indeling van {len(ids)} aansluiting(en) hersteld/gewist. "
                f"Herstelkopie: {snapshot}"
            )
            self._refresh_pre_cluster_choices()
        except Exception as exc:
            self._error(f"Handmatige indeling wissen mislukt: {exc}")

    def _prepared_result_labels_available(self):
        layer = self.layers.get("AANSLUITINGEN")
        if layer is None:
            return False
        field = self._field_name(layer, ("Oud_gebied", "Oud gebied", "GebiedLabel"))
        return bool(self._prepared_labels_from_layer(layer, field)) if field else False

    def _mark_result_clusters_new(self, labels):
        labels_upper = {str(label).strip().upper() for label in labels}
        for key in ("STATIONS", "GEBIEDEN", "KABELROUTES"):
            layer = self.layers.get(key)
            if layer is None:
                continue
            cluster_index = layer.fields().lookupField("Cluster")
            type_index = layer.fields().lookupField("Type")
            if cluster_index < 0 or type_index < 0:
                continue
            changes = {
                int(feature.id()): {type_index: "Nieuw"}
                for feature in layer.getFeatures()
                if str(feature.attribute(cluster_index)).strip().upper() in labels_upper
            }
            if changes:
                layer.dataProvider().changeAttributeValues(changes)
                layer.dataProvider().forceReload()
                layer.triggerRepaint()
        connections = self.layers.get("AANSLUITINGEN")
        if connections is not None:
            cluster_index = connections.fields().lookupField("Cluster")
            stat_type_index = connections.fields().lookupField("Stat_type")
            if cluster_index >= 0 and stat_type_index >= 0:
                changes = {
                    int(feature.id()): {stat_type_index: "Nieuw"}
                    for feature in connections.getFeatures()
                    if str(feature.attribute(cluster_index)).strip().upper() in labels_upper
                }
                if changes:
                    connections.dataProvider().changeAttributeValues(changes)
                    connections.dataProvider().forceReload()
                    connections.triggerRepaint()

    def enforce_prepared_clusters(self):
        if self.mode != "result":
            self._error("Voer eerst de normale clustering uit.")
            return
        connections = self.layers["AANSLUITINGEN"]
        stations = self.layers["STATIONS"]
        legacy_field = self._field_name(
            connections, ("Oud_gebied", "Oud gebied", "GebiedLabel")
        )
        if not legacy_field:
            self._error("De resultaatlaag bevat geen Oud_gebied/GebiedLabel.")
            return
        labels = self._prepared_labels_from_layer(connections, legacy_field)
        station_cluster_field = stations.fields().lookupField("Cluster")
        connection_cluster_field = connections.fields().lookupField("Cluster")
        station_by_cluster = {
            str(feature.attribute(station_cluster_field)).strip().upper(): int(feature.id())
            for feature in stations.getFeatures()
        } if station_cluster_field >= 0 else {}
        labels = [label for label in labels if label in station_by_cluster]
        if not labels:
            self._error(
                "Geen voorbereide H-xx-labels met een gelijknamig station gevonden."
            )
            return

        try:
            self._write_snapshot(
                [
                    ("aansluitingen_geclusterd", connections),
                    ("stations_ontwerp", stations),
                    ("clustergebieden", self.layers["GEBIEDEN"]),
                    ("cluster_kabelroutes", self.layers["KABELROUTES"]),
                ],
                "voor_handmatige_indeling_afdwingen",
            )
            self._mark_result_clusters_new(labels)
            total_moved = 0
            for label in labels:
                move_ids = [
                    int(feature.id())
                    for feature in connections.getFeatures()
                    if str(feature[legacy_field]).strip().upper() == label
                    and (
                        connection_cluster_field < 0
                        or str(feature.attribute(connection_cluster_field)).strip().upper()
                        != label
                    )
                ]
                if not move_ids:
                    continue
                connections.selectByIds(move_ids)
                stations.selectByIds([station_by_cluster[label]])
                result = self._run_existing_correction(remove_source_cluster=False)
                total_moved += int(result.get("VERPLAATST_AANTAL", len(move_ids)) or 0)
            self._mark_result_clusters_new(labels)
            HandmatigeClusterCorrectieAlgorithm._refresh_project_layout_after_correction(
                connections,
                stations,
                self.layers["GEBIEDEN"],
                self.layers["KABELROUTES"],
            )
            self._set_status(
                f"Gereed: voorbereide handmatige indeling afgedwongen voor "
                f"{len(labels)} cluster(s); {total_moved} aansluiting(en) gecorrigeerd. "
                "Je kunt hierna gewone lasso-clusterwissels blijven gebruiken."
            )
            self.status_label.setStyleSheet("color:#2e7d32; font-weight:700;")
            if self.iface is not None:
                self.iface.mapCanvas().refresh()
            self._refresh_preview()
        except Exception as exc:
            self._error(
                "Afdwingen van de voorbereide handmatige clusters is gestopt: "
                f"{exc}"
            )

    def create_new_cluster(self):
        selected = self._selected_connections()
        if not selected:
            self._error("Selecteer eerst aansluitingen voor het nieuwe cluster.")
            return
        try:
            cluster = self._normalize_new_cluster_name()
            kva = float(self.new_cluster_kva.value())
            if self._new_station_geometry is None:
                self.auto_station_location()
            if self._new_station_geometry is None:
                raise RuntimeError("Kies eerst een stationslocatie.")
            if self.mode == "result":
                self._create_result_cluster(cluster, kva)
            else:
                self._create_prepared_cluster(cluster, kva)
            self._refresh_preview()
        except Exception as exc:
            self._error(f"Nieuw cluster maken mislukt: {exc}")

    def _set_status(self, message, error=False):
        self.status_label.setText(message)
        self.status_label.setStyleSheet(
            "color:#b00020; font-weight:700;" if error else ""
        )

    def _error(self, message):
        self._set_status(message, True)
        if hasattr(self, "guide") and self.guide.busy:
            self.guide.failed = True
            self.guide.progress_label.setText(message)
            self.guide.progress_label.setStyleSheet("color:#b00020; font-weight:700;")
            return
        QMessageBox.warning(self, "Visuele handmatige clustereditor", message)

    def closeEvent(self, event):
        self._disconnect_signals()
        self._clear_station_draw_layer()
        super().closeEvent(event)
