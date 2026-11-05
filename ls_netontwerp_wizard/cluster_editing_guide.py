"""A guided front end for the existing cluster correction and creation tools."""
from collections import Counter
from html import escape
import math

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QApplication, QCheckBox, QComboBox, QCompleter,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLayout, QProgressBar, QPushButton, QVBoxLayout)
from qgis.core import QgsProcessingFeedback, QgsProject, QgsVariantUtils
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsVectorLayer
from .ui_theme import role


def searchable(combo):
    combo.setEditable(True)
    combo.setInsertPolicy(getattr(QComboBox, "InsertPolicy", QComboBox).NoInsert)
    combo.completer().setCompletionMode(getattr(QCompleter, "CompletionMode", QCompleter).PopupCompletion)
    combo.completer().setFilterMode(getattr(Qt, "MatchFlag", Qt).MatchContains)
    combo.completer().setCaseSensitivity(getattr(Qt, "CaseSensitivity", Qt).CaseInsensitive)
    combo.setMinimumContentsLength(18)


class GuideFeedback(QgsProcessingFeedback):
    def __init__(self, guide):
        super().__init__()
        self.guide, self.message = guide, "Berekening starten"

    def setProgress(self, value):
        super().setProgress(value)
        self.guide.progress(value, self.message)

    def pushInfo(self, message):
        self.message = str(message)
        self.guide.progress(self.progress(), self.message)

    def pushWarning(self, message):
        self.pushInfo(message)

    def reportError(self, message, fatalError=False):
        self.pushInfo(message)


class ClusterEditingGuide:
    def __init__(self, editor, root):
        self.editor = editor
        self.busy = self.failed = False
        self.last_selection = None
        self.selection_signature = None
        self._scope_key = self._scope_ids = None
        self.scope_error = ""
        self._updating = False
        self._target_searching = False
        self._last_location_mode = "auto"
        selection = editor.selection_group.layout()
        row = QHBoxLayout()
        self.cluster_combo = QComboBox()
        searchable(self.cluster_combo)
        self.select_cluster = QPushButton("Hele cluster selecteren")
        self.select_cluster.clicked.connect(self.select_whole_cluster)
        self.restore_selection = QPushButton("Vorige selectie terughalen")
        self.restore_selection.clicked.connect(self.restore_last_selection)
        row.addWidget(self.cluster_combo, 1)
        row.addWidget(self.select_cluster)
        row.addWidget(self.restore_selection)
        selection.insertLayout(0, row)
        self.source_map_button = QPushButton("Hele cluster: klik bronstation op kaart")
        self.source_map_button.clicked.connect(editor.start_source_station_pick)
        selection.insertWidget(0,self.source_map_button)
        editor.lasso_button.setText("Selectie tekenen op de kaart")

        self.action_group = QGroupBox("2. Kies wat je wilt doen")
        action_form = QFormLayout(self.action_group)
        self.action_combo = QComboBox()
        action_form.addRow("Actie", self.action_combo)
        root.insertWidget(root.indexOf(editor.selection_group) + 1, self.action_group)
        self.action_combo.currentIndexChanged.connect(self.action_changed)
        editor.switch_group.setTitle("Doelstation")
        self.target_combo = QComboBox()
        searchable(self.target_combo)
        target_form = QFormLayout()
        target_form.addRow("Zoek of kies een station", self.target_combo)
        editor.switch_group.layout().insertLayout(0, target_form)
        self.target_combo.currentIndexChanged.connect(self.target_changed)
        self.target_combo.lineEdit().textEdited.connect(self.target_text_changed)
        self.target_combo.activated.connect(self.target_changed)
        editor.station_button.setText("Klik doelstation op kaart")
        editor.switch_group.layout().itemAt(1).layout().removeWidget(editor.apply_button)
        editor.apply_button.hide()

        editor.new_group.setTitle("Nieuw cluster en station")
        editor.new_group.layout().removeWidget(editor.create_cluster_button)
        editor.create_cluster_button.hide()
        self.location_mode = QComboBox()
        self.location_mode.addItem("Automatisch bij de selectie, op een kabel", "auto")
        self.location_mode.addItem("Zelf een locatie op de kaart kiezen", "manual")
        location_row = editor.new_group.layout().itemAt(2, getattr(QFormLayout, "ItemRole", QFormLayout).FieldRole).layout()
        location_label = editor.new_group.layout().labelForField(location_row)
        if location_label is not None:
            location_label.hide()
        editor.new_group.layout().insertRow(2, "Stationslocatie", self.location_mode)
        self.location_mode.currentIndexChanged.connect(self.location_changed)
        editor.auto_station_button.hide()
        searchable(editor.pre_cluster_combo)
        editor.pre_cluster_combo.currentTextChanged.connect(self.refresh_preview)
        editor.pre_group.setTitle("Bestaand handmatig cluster")
        editor.pre_assign_button.hide()
        editor.pre_clear_button.hide()
        self.preparation_group = QGroupBox("Voortgang van je eigen indeling")
        preparation = QVBoxLayout(self.preparation_group)
        editor.pre_group.layout().removeWidget(editor.pre_coverage_label)
        preparation.addWidget(editor.pre_coverage_label)
        if hasattr(editor, "dashboard_manual_cluster_button"):
            editor.pre_group.layout().removeWidget(editor.dashboard_manual_cluster_button)
            preparation.addWidget(editor.dashboard_manual_cluster_button)
        root.insertWidget(root.indexOf(editor.options_group), self.preparation_group)

        self.advanced = QCheckBox("Geavanceerde instellingen en veiligheidscontroles")
        root.insertWidget(root.indexOf(editor.options_group), self.advanced)
        self.advanced.toggled.connect(self.update_visibility)
        editor.options_group.setTitle("Geavanceerde instellingen")
        editor.remove_source_cluster.hide()
        editor.enforce_button.clicked.disconnect()
        editor.enforce_button.clicked.connect(lambda: self.run_task(editor.enforce_prepared_clusters))

        review = QGroupBox("3. Controleer en pas toe")
        review.setProperty('uiContentMinimum',True)
        self.review_group = review
        review_layout = QVBoxLayout(review)
        review_layout.setSizeConstraint(getattr(QLayout,'SizeConstraint',QLayout).SetMinimumSize)
        editor.switch_group.layout().removeWidget(editor.preview_label)
        review_layout.addWidget(editor.preview_label)
        self.capacity = QLabel()
        self.capacity.setWordWrap(True)
        role(self.capacity,'hint')
        review_layout.addWidget(self.capacity)
        self.safety_label = QLabel()
        self.safety_label.setWordWrap(True)
        role(self.safety_label, "hint")
        review_layout.addWidget(self.safety_label)
        row = QHBoxLayout()
        self.commit = QPushButton("Verplaatsen")
        role(self.commit, "primary")
        self.commit.clicked.connect(self.execute)
        self.cancel = QPushButton("Berekening annuleren")
        role(self.cancel,'danger')
        self.cancel.setMinimumHeight(34)
        self.cancel.clicked.connect(self.cancel_calculation)
        self.cancel.hide()
        row.addWidget(self.commit)
        row.addWidget(self.cancel)
        row.addStretch(1)
        review_layout.addLayout(row)
        self.progress_bar = QProgressBar()
        role(self.progress_bar,'calculationProgress')
        self.progress_bar.setMinimumHeight(24)
        self.progress_bar.setTextVisible(False)
        self.progress_label = QLabel()
        self.progress_label.setWordWrap(True)
        review_layout.addWidget(self.progress_bar)
        review_layout.addWidget(self.progress_label)
        self.progress_bar.hide()
        self.progress_label.hide()
        root.insertWidget(root.indexOf(editor.status_label), review)
        for widget in (editor.check_capacity, editor.check_route, editor.block_other, editor.check_shared):
            widget.toggled.connect(self.refresh_preview)
        editor.new_cluster_kva.valueChanged.connect(self.refresh_preview)
        editor.new_cluster_name.textChanged.connect(self.refresh_preview)

    @property
    def action(self):
        return self.action_combo.currentData()

    def refresh_layers(self):
        e = self.editor
        self._scope_key = self._scope_ids = None
        self.scope_error = ""
        previous = self.action
        self.action_combo.blockSignals(True)
        self.action_combo.clear()
        choices = (("Verplaatsen naar een station", "move"), ("Nieuw cluster met een station maken", "new"),
            ("Hele clusters samenvoegen", "merge")) if e.mode == "result" else (
            ("Nieuw handmatig cluster met een station maken", "new"),
            ("Toewijzen aan een handmatig cluster", "assign"), ("Handmatige indeling van de selectie wissen", "clear"))
        for label, value in choices:
            self.action_combo.addItem(label, value)
        index = self.action_combo.findData(previous)
        if index >= 0:
            self.action_combo.setCurrentIndex(index)
        self.action_combo.blockSignals(False)
        self.refresh_choices()
        self.action_changed()

    def refresh_choices(self):
        e = self.editor
        source = e._active_connection_layer()
        self.cluster_field = e._field_name(source, ("Cluster",)) if e.mode == "result" else e._field_name(source, ("GebiedLabel", "Station"))
        previous = self.cluster_combo.currentData()
        self.cluster_combo.blockSignals(True)
        self.cluster_combo.clear()
        self.cluster_combo.addItem("Kies een bestaand cluster", None)
        if self.cluster_field:
            counts = Counter(self.value(f[self.cluster_field]) for f in source.getFeatures())
            for cluster, count in sorted(counts.items()):
                if cluster:
                    self.cluster_combo.addItem(f"{cluster} ({count} aansluitingen)", cluster)
        index = self.cluster_combo.findData(previous)
        self.cluster_combo.setCurrentIndex(max(0, index))
        self.cluster_combo.blockSignals(False)
        self.select_cluster.setEnabled(self.cluster_combo.count() > 1)
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        self.target_combo.addItem("Kies een doelstation", None)
        stations = e.layers.get("STATIONS") if e.mode == "result" else None
        if stations is not None:
            name_field = e._field_name(stations, ("Cluster", "Station", "Stationsnaam"))
            for feature in sorted(stations.getFeatures(), key=lambda f: self.value(f[name_field]) if name_field else str(f.id())):
                name = self.value(feature[name_field]) if name_field else str(feature.id())
                max_a, load_a = self.number(feature, stations, "Max_A"), self.number(feature, stations, "Belast_A")
                suffix = f" - vrij {max_a-load_a:.1f} A" if max_a is not None and load_a is not None else ""
                self.target_combo.addItem(name + suffix, feature.id())
        self.target_combo.blockSignals(False)
        self._target_searching = False

    def choose_action(self, action):
        index = self.action_combo.findData(action)
        if index >= 0:
            self.action_combo.setCurrentIndex(index)

    def action_changed(self, *_):
        if not self.busy:
            self.progress_bar.hide()
            self.progress_label.hide()
        self.editor.remove_source_cluster.setChecked(self.action == "merge")
        self.update_visibility()
        self.refresh_preview()

    def update_visibility(self, *_):
        e = self.editor
        e.switch_group.setVisible(self.action in ("move", "merge"))
        e.new_group.setVisible(self.action == "new")
        e.pre_group.setVisible(e.mode == "prepare" and self.action == "assign")
        self.preparation_group.setVisible(e.mode == "prepare")
        if hasattr(e, "dashboard_manual_cluster_button"):
            e.dashboard_manual_cluster_button.setVisible(e.mode == "prepare" and e.requested_mode != "result")
        e.options_group.setVisible(self.advanced.isChecked())
        e.enforce_group.setVisible(self.advanced.isChecked() and e.mode == "result" and e._prepared_result_labels_available())
        self.location_changed()

    def location_changed(self, *_):
        auto = self.location_mode.currentData() == "auto"
        mode = self.location_mode.currentData()
        if mode != self._last_location_mode:
            self.editor._new_station_geometry = self.editor._new_station_geometry_crs = None
            self.editor._clear_station_draw_layer()
        self._last_location_mode = mode
        self.editor.draw_station_button.setVisible(not auto)
        if auto and self.editor._new_station_geometry is None:
            self.editor.location_label.setText("De locatie wordt bij het maken automatisch op een kabel voorgesteld.")
            self.editor.location_label.setStyleSheet("")
            role(self.editor.location_label, "hint")

    def target_changed(self, *_):
        if self._updating or self.busy:
            return
        layer = self.editor.layers.get("STATIONS")
        self._target_searching = False
        if layer is not None:
            fid = self.target_combo.currentData()
            layer.selectByIds([fid] if fid is not None else [])
            self.refresh_preview()

    def target_text_changed(self, text):
        if self._updating or self.busy:
            return
        self._target_searching = text != self.target_combo.itemText(self.target_combo.currentIndex())
        self.refresh_preview()

    def select_whole_cluster(self):
        layer = self.editor._active_connection_layer()
        cluster = self.cluster_combo.currentData()
        valid_text = self.cluster_combo.currentText() == self.cluster_combo.itemText(self.cluster_combo.currentIndex())
        if layer is not None and self.cluster_field and cluster and valid_text:
            layer.selectByIds([f.id() for f in layer.getFeatures() if self.value(f[self.cluster_field]) == cluster])
            if self.editor.iface is not None:
                self.editor.iface.setActiveLayer(layer)

    def restore_last_selection(self):
        layer = self.editor._active_connection_layer()
        if layer is not None and self.last_selection and layer.id() == self.last_selection[0]:
            layer.selectByIds([fid for fid in self.last_selection[1] if layer.getFeature(fid).isValid()])

    @staticmethod
    def value(value):
        return "" if QgsVariantUtils.isNull(value) else str(value).strip()

    def number(self, feature, layer, *fields):
        name = self.editor._field_name(layer, fields)
        value = self.editor._number(feature[name]) if name else None
        return value if value is not None and math.isfinite(value) else None

    def design_field(self, layer):
        host = getattr(self.editor, "_host", None)
        state = getattr(host, "prepared_state", None) or {}
        preferred = state.get("values", {}).get("field_design_current", "Hoogste Trafo")
        return self.editor._field_name(layer, ("Ontwerp_A", preferred, "Hoogste Trafo", "Ontwerpstroom", "Ontwerpstro"))

    def relevant_features(self, layer, features):
        """Use the same saved plan and 5 cm boundary tolerance as clustering."""
        host = getattr(self.editor, "_host", None)
        state = getattr(host, "prepared_state", None) or {}
        if self.editor.mode != "prepare" or not state.get("plan_gpkg") or not state.get("values", {}).get("only_plan"):
            return features
        from pathlib import Path
        path = Path(state["plan_gpkg"])
        if not path.exists():
            self.scope_error = "Het gekoppelde plangebied ontbreekt. Koppel het opnieuw bij de clusteringinstellingen."
            return []
        key = (layer.id(), layer.featureCount(), str(path), path.stat().st_mtime_ns)
        if self._scope_key != key:
            from shapely import from_wkb
            from shapely.ops import unary_union
            plan = QgsVectorLayer(str(path) + "|layername=plangebied", "Plan voor indeling", "ogr")
            if not plan.isValid():
                self.scope_error = "Het gekoppelde plangebied kan niet worden gelezen."
                return []
            rd = QgsCoordinateReferenceSystem("EPSG:28992")
            def rd_shape(feature, source):
                geometry = QgsGeometry(feature.geometry())
                if source.crs() != rd:
                    geometry.transform(QgsCoordinateTransform(source.crs(), rd, QgsProject.instance()))
                return from_wkb(bytes(geometry.asWkb()))
            area = unary_union([rd_shape(f, plan).buffer(0) for f in plan.getFeatures()]).buffer(0).buffer(.05)
            self._scope_ids = {f.id() for f in layer.getFeatures() if f.hasGeometry() and area.covers(rd_shape(f, layer))}
            self._scope_key = key
            # Ordinary QGIS edits invalidate geometry membership, label edits
            # need not rebuild it. Reconnect only when the source changes.
            if getattr(self, "_scope_layer", None) is not layer:
                layer.geometryChanged.connect(self.invalidate_scope)
                self._scope_layer = layer
        return [f for f in features if f.id() in self._scope_ids]

    def invalidate_scope(self, *_):
        self._scope_key = self._scope_ids = None

    def load(self, features, layer):
        name = self.design_field(layer)
        numbers = [self.editor._number(f[name]) if name else None for f in features]
        valid = [n for n in numbers if n is not None and math.isfinite(n)]
        return sum(valid), len(numbers) - len(valid)

    def refresh_preview(self, *_):
        e = self.editor
        source = e._active_connection_layer()
        selected = e._selected_connections()
        selected_before_scope = len(selected)
        selected = self.relevant_features(source, selected) if source is not None else selected
        signature = (source.id(), tuple(sorted(f.id() for f in selected))) if source else None
        if signature != self.selection_signature and self.location_mode.currentData() == "auto":
            e._new_station_geometry = e._new_station_geometry_crs = None
            self.location_changed()
        self.selection_signature = signature
        self.restore_selection.setEnabled(bool(source and self.last_selection and source.id() == self.last_selection[0]))
        selected_load, missing = self.load(selected, source) if source else (0.0, 0)
        e.selection_label.setText(f"{len(selected)} aansluitingen geselecteerd - ontwerpstroom {selected_load:.1f} A"
            + (f" ({missing} ontbrekende waarden)" if missing else "")
            + (f"; {selected_before_scope-len(selected)} buiten het plangebied worden overgeslagen" if selected_before_scope != len(selected) else ""))
        stations = e.layers.get("STATIONS")
        target = list(stations.getSelectedFeatures()) if e.mode == "result" and stations is not None else []
        if self._target_searching:
            target = []
        self._updating = True
        self.target_combo.blockSignals(True)
        index = self.target_combo.findData(target[0].id()) if len(target) == 1 else 0
        if not self._target_searching:
            self.target_combo.setCurrentIndex(max(index, 0))
        self.target_combo.blockSignals(False)
        self._updating = False
        enabled = bool(selected)
        self.capacity.hide()
        lines = []
        if self.action in ("move", "merge"):
            enabled = enabled and len(target) == 1
            if len(target) == 1 and source is not None:
                destination = self.value(target[0]["Cluster"])
                source_clusters = {self.value(f["Cluster"]) for f in selected} - {destination}
                moving = [f for f in (source.getFeatures() if self.action == "merge" else selected)
                    if self.value(f["Cluster"]) in source_clusters]
                load, missing = self.load(moving, source)
                current = self.number(target[0], stations, "Belast_A", "Clust_A")
                capacity = self.number(target[0], stations, "Max_A")
                enabled = enabled and bool(moving)
                lines = [f"<b>{len(moving)} aansluitingen naar {escape(destination)}</b>",
                    "Van: " + escape(", ".join(sorted(source_clusters))), f"Toegevoegde ontwerpstroom: {load:.1f} A"]
                if self.action == "merge":
                    lines.append(f"De {len(source_clusters)} broncluster(s) en hun stations worden samengevoegd en verwijderd.")
                if current is not None and capacity is not None:
                    enabled = self.show_capacity(current + load, capacity, lines, enabled)
            else:
                lines = ["Selecteer aansluitingen en kies een doelstation uit de zoekresultaten of op de kaart."]
            self.commit.setText("Clusters samenvoegen" if self.action == "merge" else "Aansluitingen verplaatsen")
        elif self.action == "new":
            cap = float(e.new_cluster_kva.value()) / .23 / 3
            lines = [f"<b>Nieuw cluster {escape(e.new_cluster_name.text() or e._next_manual_cluster_name())}</b>",
                f"{len(selected)} aansluitingen, ontwerpstroom {selected_load:.1f} A, station {e.new_cluster_kva.value():g} kVA."]
            enabled = self.show_capacity(selected_load, cap, lines, enabled)
            enabled = enabled and e._target_station_layer_for_location() is not None
            name = e.new_cluster_name.text().strip().upper()
            if name and not e.MANUAL_LABEL_RE.fullmatch(name):
                lines.append("Gebruik een herkenbare naam zoals H-01 of H-02.")
                enabled = False
            if name and e.mode == "result" and e._result_cluster_exists(name):
                lines.append("Deze clusternaam bestaat al. Kies een nieuwe H-xx-naam.")
                enabled = False
            if name and e.mode == "prepare" and e.source_stations is not None:
                field = e._source_station_name_field()
                if field and any(self.value(f[field]).upper() == name for f in e.source_stations.getFeatures()):
                    lines.append("Deze clusternaam bestaat al. Kies Toewijzen om aansluitingen eraan toe te voegen.")
                    enabled = False
            if self.location_mode.currentData() == "manual" and e._new_station_geometry is None:
                lines.append("Kies eerst de stationslocatie op de kaart.")
                enabled = False
            self.commit.setText("Nieuw cluster maken" if e.mode == "result" else "Handmatig cluster vastleggen")
        elif self.action == "assign":
            enabled = enabled and e.pre_cluster_combo.findText(e.pre_cluster_combo.currentText()) >= 0
            enabled = enabled and e.source_stations is not None
            destination = e.pre_cluster_combo.currentText()
            lines = [f"{len(selected)} aansluitingen toewijzen aan {escape(destination)}."]
            name_field = e._source_station_name_field()
            capacity_field = e._source_station_capacity_field()
            matching = [f for f in e.source_stations.getFeatures() if name_field and self.value(f[name_field]) == destination] if e.source_stations is not None else []
            enabled = enabled and bool(matching)
            if matching and source is not None:
                label_field = e._field_name(source, ("GebiedLabel",))
                selected_ids = {f.id() for f in selected}
                current_members = self.relevant_features(source, list(source.getFeatures()))
                projected = [f for f in current_members if f.id() in selected_ids or (label_field and self.value(f[label_field]) == destination)]
                total_load, missing = self.load(projected, source)
                kva = e._number(matching[0][capacity_field]) if capacity_field else None
                if kva is not None and math.isfinite(kva):
                    enabled = self.show_capacity(total_load, kva / .23 / 3, lines, enabled)
            self.commit.setText("Toewijzen aan handmatig cluster")
        else:
            lines = [f"De handmatige indeling van {len(selected)} aansluitingen wordt hersteld naar de oorspronkelijke indeling."]
            self.commit.setText("Handmatige indeling wissen")
        if missing:
            lines.append(f"{missing} aansluitingen hebben geen geldige ontwerpstroom; het capaciteitsoverzicht is onvolledig.")
        lines.append("De definitieve route- en capaciteitscontroles worden bij toepassen uitgevoerd." if e.mode == "result"
            else "Routes worden gecontroleerd wanneer je de volledige handmatige clustering uitvoert.")
        e.preview_label.setText("<br>".join(lines))
        checks = sum(box.isChecked() for box in (e.check_capacity, e.check_route, e.block_other, e.check_shared))
        self.safety_label.setText("Alle veiligheidscontroles staan aan." if checks == 4 else f"Let op: {4-checks} veiligheidscontrole(s) zijn uitgeschakeld bij Geavanceerd.")
        self.commit.setEnabled(enabled and not self.busy)
        e.create_cluster_button.setEnabled(bool(selected))
        e.apply_button.setEnabled(bool(selected) and len(target) == 1)
        e._refresh_pre_coverage()
        if hasattr(e, "dashboard_manual_cluster_button") and e.mode == "prepare":
            layer = e.source_connections
            features = self.relevant_features(layer, list(layer.getFeatures())) if layer is not None else []
            total = len(features)
            manual = sum(1 for f in features if e.MANUAL_LABEL_RE.fullmatch(self.value(f["GebiedLabel"]))) if layer is not None and layer.fields().lookupField("GebiedLabel") >= 0 else 0
            e.pre_coverage_label.setText(f"{manual} van {total} aansluitingen in het gekozen gebied zijn ingedeeld. "
                + ("Je kunt de handmatige clustering uitvoeren." if total and manual == total else "Deel de overige aansluitingen in of gebruik 3a voor een automatische verdeling."))
            e.dashboard_manual_cluster_button.setEnabled(total > 0 and manual == total and not self.busy)
        if e.requested_mode == "result" and e.mode != "result":
            e.preview_label.setText("Er zijn nog geen berekende clusters. Bereken eerst de clustering bij 3a of maak je eigen indeling bij 3b.")
            self.commit.setEnabled(False)
        if self.scope_error:
            e.preview_label.setText(escape(self.scope_error))
            self.commit.setEnabled(False)

    def show_capacity(self, projected, capacity, lines, enabled):
        if capacity <= 0:
            return enabled
        percentage = projected / capacity * 100
        self.capacity.show()
        self.capacity.setText(f"Stationsbenutting na wijziging: {percentage:.1f}%")
        lines.append(f"Belasting na wijziging: {projected:.1f} / {capacity:.1f} A (vrij {capacity-projected:.1f} A).")
        if projected > capacity + 1e-6 and self.editor.check_capacity.isChecked():
            lines.append("Dit past niet binnen de stationscapaciteit. Kies minder aansluitingen of een ander station.")
            return False
        return enabled

    def execute(self):
        self.refresh_preview()
        if self.busy or not self.commit.isEnabled():
            return
        e = self.editor
        actions = {"move": e.apply_change, "merge": e.apply_change, "new": e.create_new_cluster,
            "assign": e.assign_prepared_cluster, "clear": e.clear_prepared_assignment}
        self.run_task(actions[self.action])

    def run_task(self, callback):
        if self.busy:
            return
        e = self.editor
        source = e._active_connection_layer()
        if e.mode == "prepare":
            source.selectByIds([f.id() for f in self.relevant_features(source, e._selected_connections())])
        remembered = (source.id(), list(source.selectedFeatureIds()))
        self.failed = False
        self.busy = True
        self.feedback = GuideFeedback(self)
        e._active_cluster_feedback = self.feedback
        groups = (e.selection_group, self.action_group, e.switch_group, e.new_group, e.pre_group, self.preparation_group, e.options_group, e.enforce_group, self.advanced)
        for widget in groups:
            widget.setEnabled(False)
        homes = [b for b in e.findChildren(QPushButton) if "Home" in b.text() or b.text() == "Sluiten"]
        for button in homes:
            button.setEnabled(False)
        self.commit.setEnabled(False)
        status_was_hidden=e.status_label.isHidden()
        e.status_label.hide()
        self.cancel.show()
        self.cancel.setEnabled(True)
        self.progress_bar.show()
        self.progress_label.show()
        self.progress_label.setStyleSheet("")
        self.progress(0, "Wijziging voorbereiden")
        try:
            callback()
            if not self.failed:
                if remembered[1]:
                    self.last_selection = remembered
                source.removeSelection()
                if e.mode == "result":
                    e.layers["STATIONS"].removeSelection()
                self.progress(100, "Gereed. Kies aansluitingen voor de volgende wijziging.")
        except Exception as exc:
            e._error(str(exc))
        finally:
            e._active_cluster_feedback = None
            self.busy = False
            e.status_label.setVisible(not status_was_hidden)
            self.cancel.hide()
            for widget in (*groups, *homes):
                widget.setEnabled(True)
            self.refresh_choices()
            self.refresh_preview()

    def progress(self, percent, message):
        self.progress_bar.setValue(round(percent))
        self.progress_label.setText(f"{round(percent)}% · {message}")
        self.cancel.setEnabled(percent < 88 and not self.feedback.isCanceled())
        QApplication.processEvents()

    def cancel_calculation(self):
        if self.busy:
            self.feedback.cancel()
            self.cancel.setEnabled(False)
            self.progress_label.setText("Annuleren zodra de huidige berekening stopt...")
