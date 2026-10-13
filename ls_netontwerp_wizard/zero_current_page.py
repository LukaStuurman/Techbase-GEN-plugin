"""Review and repair connections without a design current."""

from __future__ import annotations

import math

from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    QgsCoordinateTransform,
    QgsField,
    QgsFeatureRequest,
    QgsProject,
    QgsRectangle,
    QgsVectorDataProvider,
)

from .current_presets import (
    HOUSEHOLD_UNIT_CHOICES, GAS_CHOICES, fill_gas_combo, fill_unit_combo,
    unit_currents, unit_description, category_note,
)
from .current_inputs import connect_current_edits, set_current_values


class ZeroCurrentPage(QWidget):
    """Table-driven manual categorization of zero-current connection points."""

    CATEGORY_CHOICES = (
        ("Huishoudelijk", "Huishoudelijk"),
        ("Zakelijk", "Zakelijk"),
        ("Oplaadpunt", "Oplaadpunt"),
        ("Straatmeubilair", "Straatmeubilair"),
    )
    CATEGORY_FIELD = "HerstelCat"
    OUTPUT_FIELDS = (
        "Ontwerpstroom",
        "Ontwerpstroom kabel",
        "Opwek ontwerpstroom",
        "Kabel opwek ontwerpstroom",
        "Hoogste Trafo",
        "Hoogste Kabel",
        "Gevonden_Woningtype",
    )

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.layer = None
        self._changing_selection = False
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        self.home_button = self.host._add_subpage_header(
            root,
            "Ontwerpstroom nulwaarden herstellen",
            "TechBase • controleer de aansluitingen waarvoor geen ontwerpstroom is berekend",
        )
        self.host.zero_current_home_button = self.home_button

        note = QLabel(
            "De lijst toont aansluitingen met een ontbrekende of nulwaarde in "
            "<b>Hoogste Trafo</b>. Selecteer één of meerdere aansluitingen, "
            "gebruik Ctrl of Shift voor meerdere regels, zoom naar de "
            "kaartselectie en kies daarna de juiste categorie. Bij iedere "
            "categorie kun je trafo- en kabelverbruik en "
            "trafo- en kabelopwek apart instellen. Alle zes ontwerpstroomvelden "
            "worden opgeslagen; de hoogste waarden worden uit verbruik en opwek berekend."
        )
        note.setWordWrap(True)
        root.addWidget(note)

        selection_group = QGroupBox("Aansluitingen zonder ontwerpstroom")
        selection_layout = QVBoxLayout(selection_group)
        selection_top = QHBoxLayout()
        self.count_label = QLabel("Lijst nog niet vernieuwd")
        self.count_label.setStyleSheet("font-weight:700;")
        self.refresh_button = QPushButton("Lijst vernieuwen")
        self.refresh_button.clicked.connect(self.refresh)
        self.zoom_button = QPushButton("Zoom naar selectie")
        self.zoom_button.setObjectName("secondaryButton")
        self.zoom_button.clicked.connect(self.zoom_to_selection)
        selection_top.addWidget(self.count_label, 1)
        selection_top.addWidget(self.zoom_button)
        selection_top.addWidget(self.refresh_button)
        selection_layout.addLayout(selection_top)

        self.table = QTableWidget(0, 12)
        self.table.setHorizontalHeaderLabels(
            (
                "FID",
                "ID",
                "Gebruiksdoel",
                "Doorlaatwaarde",
                "Woningtype",
                "Bouwjaar",
                "Trafo verbruik (A)",
                "Kabel verbruik (A)",
                "Trafo opwek (A)",
                "Kabel opwek (A)",
                "Hoogste Trafo (A)",
                "Hoogste Kabel (A)",
            )
        )
        try:
            self.table.setSelectionBehavior(
                QAbstractItemView.SelectionBehavior.SelectRows
            )
            self.table.setSelectionMode(
                QAbstractItemView.SelectionMode.ExtendedSelection
            )
        except AttributeError:  # QGIS 3 / PyQt5
            self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
            self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        else:
            self.table.setEditTriggers(
                QAbstractItemView.EditTrigger.NoEditTriggers
            )
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        try:
            stretch = QHeaderView.ResizeMode.Stretch
        except AttributeError:  # QGIS 3 / PyQt5
            stretch = QHeaderView.Stretch
        self.table.horizontalHeader().setSectionResizeMode(2, stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, stretch)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.cellDoubleClicked.connect(lambda _row, _column: self.zoom_to_selection())
        selection_layout.addWidget(self.table, 1)
        root.addWidget(selection_group, 3)

        category_group = QGroupBox("Categorie en ontwerpstroom")
        category_form = QFormLayout(category_group)
        self.category_combo = QComboBox()
        for label, stored in self.CATEGORY_CHOICES:
            self.category_combo.addItem(label, stored)
        self.category_combo.currentIndexChanged.connect(self._category_changed)
        category_form.addRow("Categorie", self.category_combo)

        self.housing_combo = QComboBox()
        for label, stored in HOUSEHOLD_UNIT_CHOICES:
            self.housing_combo.addItem(label, stored)
        category_form.addRow("Woningtype", self.housing_combo)
        self.housing_label = category_form.labelForField(self.housing_combo)
        self.housing_combo.currentIndexChanged.connect(self._household_changed)
        self.housing_note = QLabel(
            "De ingestelde oude/nieuwbouwtabellen worden per aansluiting gekozen "
            "op basis van bouwjaar. Bij een onbekend bouwjaar wordt de oude tabel gebruikt."
        )
        self.housing_note.setWordWrap(True)
        category_form.addRow("", self.housing_note)

        self.unit_group = QGroupBox("Type wooneenheid / aansluiting")
        unit_form = QFormLayout(self.unit_group)
        self.unit_combo = QComboBox()
        unit_form.addRow("Type wooneenheid", self.unit_combo)
        self.gas_combo = QComboBox()
        fill_gas_combo(self.gas_combo)
        self.gas_label = QLabel("Gasaansluiting")
        unit_form.addRow(self.gas_label, self.gas_combo)
        self.unit_note = QLabel()
        self.unit_note.setWordWrap(True)
        unit_form.addRow(self.unit_note)
        self.unit_combo.currentIndexChanged.connect(self._unit_changed)
        self.gas_combo.currentIndexChanged.connect(self._unit_changed)
        root.addWidget(category_group)
        root.addWidget(self.unit_group)

        self.current_values_group = QGroupBox("Verbruik en opwek")
        current_form = QFormLayout(self.current_values_group)
        self.manual_checkbox = QCheckBox("Zelf ingevulde stroomwaarden gebruiken")
        current_form.addRow(self.manual_checkbox)
        self.manual_checkbox.toggled.connect(self._manual_mode_changed)
        self.trafo_spin = self._current_spin()
        self.cable_spin = self._current_spin()
        self.generation_trafo_spin = self._current_spin()
        self.generation_cable_spin = self._current_spin()
        current_form.addRow("Trafo verbruik (A)", self.trafo_spin)
        current_form.addRow("Kabel verbruik (A)", self.cable_spin)
        current_form.addRow("Trafo opwek (A)", self.generation_trafo_spin)
        current_form.addRow("Kabel opwek (A)", self.generation_cable_spin)
        self.current_values_note = QLabel(
            "Hoogste Trafo en Hoogste Kabel worden automatisch berekend als de "
            "hoogste waarde van verbruik en opwek. Typ een waarde om je eigen vier "
            "stroomwaarden voor de selectie op te slaan. Zonder handmatige invoer "
            "blijft bij huishoudelijk woningtype en bouwjaar per aansluiting gelden."
        )
        self.current_values_note.setWordWrap(True)
        current_form.addRow("", self.current_values_note)
        root.addWidget(self.current_values_group)
        connect_current_edits(self._current_spins(), self.manual_checkbox)

        self.status_label = QLabel("Selecteer een of meer regels om te herstellen.")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.apply_button = QPushButton("Categorie en ontwerpstroom opslaan")
        self.apply_button.clicked.connect(self.apply_category)
        buttons.addWidget(self.apply_button)
        close_button = QPushButton("Sluiten")
        close_button.setObjectName("secondaryButton")
        close_button.clicked.connect(self.host.close)
        buttons.addWidget(close_button)
        root.addLayout(buttons)
        self._category_changed()

    @staticmethod
    def _current_spin():
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 1000000.0)
        spin.setDecimals(3)
        spin.setSuffix(" A")
        spin.setSingleStep(0.1)
        return spin

    @staticmethod
    def _field_value(feature, field_name, default=""):
        if not field_name:
            return default
        try:
            value = feature[field_name]
        except (KeyError, TypeError, IndexError):
            return default
        if value is None:
            return default
        text = str(value).strip()
        return text if text.casefold() not in ("null", "none") else default

    @staticmethod
    def _numeric(value):
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None

    def _review_layer(self):
        project = QgsProject.instance()
        layers = list(project.mapLayers().values())
        return next(
            (
                layer
                for layer in layers
                if hasattr(layer, "fields")
                and bool(layer.customProperty("LSNetontwerp/review_current_layer", False))
            ),
            next(
                (
                    layer
                    for layer in layers
                    if hasattr(layer, "fields")
                    and layer.name() == "LS-aansluitingen ontwerpstroom"
                ),
                None,
            ),
        )

    def _zero_features(self, layer):
        highest_field = "Hoogste Trafo"
        if layer.fields().lookupField(highest_field) < 0:
            highest_field = "Ontwerpstroom"
        if layer.fields().lookupField(highest_field) < 0:
            raise ValueError("De laag mist 'Hoogste Trafo' en 'Ontwerpstroom'.")
        result = []
        for feature in layer.getFeatures():
            value = self._numeric(feature[highest_field])
            if value is None or value <= 0.0:
                result.append(feature)
        return result

    def refresh(self, select_first=False):
        self.layer = self._review_layer()
        self._changing_selection = True
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        if self.layer is None or not self.layer.isValid():
            self.count_label.setText("Ontwerpstroomlaag niet gevonden")
            self.status_label.setText(
                "Open het voorbereide QGIS-werkproject of voer eerst stap 1 uit."
            )
            self._sync_host_button(0)
            self.table.setSortingEnabled(True)
            self._changing_selection = False
            return 0

        values = self.host._workflow_field_defaults()
        fields = {field.name().casefold(): field.name() for field in self.layer.fields()}

        def field(*names):
            for name in names:
                if name and name.casefold() in fields:
                    return fields[name.casefold()]
            return ""

        fid_field = field("fid", "FID")
        id_field = field("id", "ID")
        usage_field = field(values.get("field_usage", "Gebruiksdoel"), "Gebruiksdoel")
        pass_field = field(
            values.get("field_passthrough", "service_connection_type_type"),
            "service_connection_type_type",
        )
        house_field = field("Gevonden_Woningtype", values.get("field_building_type", "Woningtype"))
        year_field = field("Gevonden_Bouwjaar", values.get("field_build_year", "bouwjaar"))

        try:
            features = self._zero_features(self.layer)
        except ValueError as exc:
            self.count_label.setText("Laag mist ontwerpstroomvelden")
            self.status_label.setText(str(exc))
            self._sync_host_button(0)
            self.table.setSortingEnabled(True)
            self._changing_selection = False
            return 0

        self.count_label.setText(f"{len(features)} aansluiting(en) zonder ontwerpstroom")
        self._sync_host_button(len(features))
        for feature in features:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values_to_show = (
                self._field_value(feature, fid_field, str(feature.id())),
                self._field_value(feature, id_field),
                self._field_value(feature, usage_field),
                self._field_value(feature, pass_field),
                self._field_value(feature, house_field),
                self._field_value(feature, year_field),
                self._field_value(feature, "Ontwerpstroom", "—"),
                self._field_value(feature, "Ontwerpstroom kabel", "—"),
                self._field_value(feature, "Opwek ontwerpstroom", "—"),
                self._field_value(feature, "Kabel opwek ontwerpstroom", "—"),
                self._field_value(feature, "Hoogste Trafo", "0"),
                self._field_value(feature, "Hoogste Kabel", "—"),
            )
            for column, text in enumerate(values_to_show):
                item = QTableWidgetItem(text)
                user_role = (
                    Qt.ItemDataRole.UserRole
                    if hasattr(Qt, "ItemDataRole")
                    else Qt.UserRole
                )
                item.setData(user_role, int(feature.id()))
                self.table.setItem(row, column, item)
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()
        self._changing_selection = False
        if select_first and features:
            self.table.selectRow(0)
            self._selection_changed()
            self.zoom_to_selection()
        else:
            if select_first and self.layer is not None:
                self.layer.removeSelection()
            self.status_label.setText(
                "Selecteer een of meer regels. Dubbelklik op een regel of gebruik "
                "'Zoom naar selectie' om de aansluiting op de kaart te vinden."
            )
        return len(features)

    def _sync_host_button(self, count):
        button = getattr(self.host, "edit_zero_current_button", None)
        if button is not None:
            button.setText(f"2d. Nulwaarden herstellen ({int(count)})")
            button.setEnabled(int(count) > 0)

    def _category_changed(self, *_args):
        code = self.category_combo.currentData()
        is_household = code == "Huishoudelijk"
        self.housing_combo.setVisible(is_household)
        self.housing_label.setVisible(is_household)
        self.housing_note.setVisible(is_household)
        self.current_values_group.setVisible(True)
        self.manual_checkbox.setChecked(False)
        self.unit_group.setVisible(not is_household)
        self.gas_combo.setVisible(code == "Zakelijk")
        self.gas_label.setVisible(code == "Zakelijk")
        fill_unit_combo(self.unit_combo, code)
        if code == "Straatmeubilair":
            default_trafo = self._matrix_value("matrix_straat", 5.8)
            default_cable = default_trafo
            default_generation_trafo = 0.0
            default_generation_cable = 0.0
        elif code == "Oplaadpunt":
            default_trafo = self._matrix_value("matrix_laad", 3.7)
            default_cable = self._matrix_value("matrix_laad_kabel", 4.8)
            default_generation_trafo = 0.0
            default_generation_cable = 0.0
        elif code == "Zakelijk":
            default_trafo = 0.0
            default_cable = 0.0
            default_generation_trafo = 0.0
            default_generation_cable = 0.0
        else:
            default_trafo = default_cable = 0.0
            default_generation_trafo = default_generation_cable = 0.0
        set_current_values(self._current_spins(), (default_trafo, default_cable,
                          default_generation_trafo, default_generation_cable))
        self._unit_changed()
        self._household_changed()

    def _current_spins(self):
        return (self.trafo_spin, self.cable_spin, self.generation_trafo_spin, self.generation_cable_spin)

    def _household_changed(self, *_args):
        if self.category_combo.currentData() != "Huishoudelijk":
            return
        self.manual_checkbox.setChecked(False)
        ids = self._selected_feature_ids()
        features = list(self.layer.getFeatures(QgsFeatureRequest().setFilterFids(ids))) if self.layer is not None and ids else []
        context = self._household_context()
        rows = [self._household_currents(self.layer, feature, self.housing_combo.currentData(), context) for feature in features]
        set_current_values(self._current_spins(), [max(column) for column in zip(*rows)] if rows else (0, 0, 0, 0))

    def _manual_mode_changed(self, manual):
        if not manual:
            if self.category_combo.currentData() == "Huishoudelijk":
                self._household_changed()
            else:
                self._unit_changed()
        self.current_values_note.setText(
            "Je eigen vier stroomwaarden worden voor alle geselecteerde aansluitingen opgeslagen. "
            "Hoogste Trafo en Hoogste Kabel volgen het maximum van verbruik en opwek."
            if manual else
            "De tabelberekening blijft actief. Bij huishoudelijk geldt woningtype en bouwjaar per aansluiting. "
            "De velden tonen het maximum in de selectie. Typ een waarde om zelf in te vullen."
        )

    def _unit_changed(self, *_args):
        category = self.category_combo.currentData()
        key = self.unit_combo.currentData()
        self.manual_checkbox.setChecked(False)
        self.unit_note.setText(category_note(category, key) + "\nJe kunt de vier stroomwaarden hieronder ook zelf typen.")
        currents = unit_currents(self._household_context(), category, key, self.gas_combo.currentData())
        if currents is not None:
            set_current_values(self._current_spins(), currents)
        elif category != "Huishoudelijk" and key is None:
            self.manual_checkbox.setChecked(True)

    def _matrix_value(self, key, fallback):
        values = self.host._workflow_field_defaults()
        items = values.get(key)
        try:
            for index in range(0, len(items or []), 3):
                minimum = float(items[index])
                maximum = float(items[index + 1])
                current = float(items[index + 2])
                if minimum <= 25 <= maximum:
                    return current
        except (IndexError, TypeError, ValueError):
            pass
        return float(fallback)

    def _selected_feature_ids(self):
        user_role = (
            Qt.ItemDataRole.UserRole if hasattr(Qt, "ItemDataRole") else Qt.UserRole
        )
        ids = []
        for model_index in self.table.selectionModel().selectedRows():
            row = model_index.row()
            item = self.table.item(row, 0)
            if item is not None:
                try:
                    ids.append(int(item.data(user_role)))
                except (TypeError, ValueError):
                    pass
        return ids

    def _selection_changed(self):
        if self._changing_selection or self.layer is None:
            return
        ids = self._selected_feature_ids()
        try:
            self._changing_selection = True
            self.layer.selectByIds(ids)
        finally:
            self._changing_selection = False
        self.status_label.setText(
            f"Geselecteerd: {len(ids)} aansluiting(en). Kies een categorie en sla op."
            if ids
            else "Selecteer een of meer regels om te herstellen."
        )
        if not self.manual_checkbox.isChecked():
            self._household_changed()

    def zoom_to_selection(self):
        ids = self._selected_feature_ids()
        if self.layer is None or not ids:
            self.status_label.setText("Selecteer eerst een of meer aansluitingen in de lijst.")
            return
        if self.host.iface is None:
            self.status_label.setText("Zoomen is alleen beschikbaar in QGIS Desktop.")
            return
        request = QgsFeatureRequest().setFilterFids(ids)
        features_by_id = {
            int(feature.id()): feature for feature in self.layer.getFeatures(request)
        }
        rectangle = None
        canvas = self.host.iface.mapCanvas()
        project = QgsProject.instance()
        transform = None
        if self.layer.crs() != canvas.mapSettings().destinationCrs():
            transform = QgsCoordinateTransform(
                self.layer.crs(), canvas.mapSettings().destinationCrs(), project
            )
        for feature_id in ids:
            feature = features_by_id.get(feature_id)
            if feature is None or feature.geometry().isEmpty():
                continue
            geometry = feature.geometry()
            if transform is not None:
                geometry = geometry.clone()
                geometry.transform(transform)
            bounds = geometry.boundingBox()
            if rectangle is None:
                rectangle = QgsRectangle(bounds)
            else:
                rectangle.combineExtentWith(bounds)
        if rectangle is None:
            self.status_label.setText("De selectie bevat geen zoom-bare geometrie.")
            return
        margin = max(rectangle.width(), rectangle.height()) * 0.35
        rectangle.grow(max(margin, 8.0))
        canvas.setExtent(rectangle)
        self.host.iface.setActiveLayer(self.layer)
        canvas.refresh()
        self.status_label.setText(f"Kaart ingezoomd op {len(ids)} aansluiting(en).")

    def _ensure_category_field(self, provider, layer=None):
        layer = layer or self.layer
        field_index = layer.fields().lookupField(self.CATEGORY_FIELD)
        if field_index >= 0:
            return field_index
        if not provider.capabilities() & QgsVectorDataProvider.AddAttributes:
            return -1
        if not provider.addAttributes(
            [QgsField(self.CATEGORY_FIELD, QVariant.String, len=20)]
        ):
            return -1
        layer.updateFields()
        return layer.fields().lookupField(self.CATEGORY_FIELD)

    def _household_context(self):
        from .algorithms.woningtype_selectie_herberekenen_tool import (
            _configurations,
            _load_design_module,
        )

        module = _load_design_module()
        values = self.host._workflow_field_defaults()
        standard, cable, opwek, opwek_cable = _configurations(values, module)
        return module, values, standard, cable, opwek, opwek_cable

    def _household_currents(self, layer, feature, house_type, context):
        module, values, standard, cable, opwek, opwek_cable = context
        year_field = layer.fields().lookupField("Gevonden_Bouwjaar")
        year = feature[year_field] if year_field >= 0 else None
        try:
            year = int(float(year))
        except (TypeError, ValueError):
            year = 0
        year_limit = int(standard.get("DEFAULTS", {}).get("bouwjaar_grens", 2022))
        new_build = year >= year_limit
        standard_table = standard.get("WOONHUIS_2022") if new_build else standard["WOONHUIS"]
        cable_table = cable.get("WOONHUIS_2022") if new_build else cable["WOONHUIS"]
        normal = float(module.woonhuis_ontwerp(house_type, standard_table))
        cable_current = float(module.woonhuis_ontwerp(house_type, cable_table))
        usage = (
            "appartement"
            if "appartement" in str(house_type).casefold()
            else "woonhuis"
        )
        one_phase = bool(values.get("one_phase_exception", True))
        generation = float(
            module.calculate_opwek_ontwerpstroom(
                None, usage, house_type, "", opwek, standard, normal, one_phase
            )
        )
        generation_cable = float(
            module.calculate_opwek_ontwerpstroom(
                None,
                usage,
                house_type,
                "",
                opwek_cable,
                standard,
                cable_current,
                one_phase,
            )
        )
        return normal, cable_current, generation, generation_cable

    def apply_values_to_layer(
        self,
        layer,
        feature_ids,
        category,
        currents,
        house_type=None,
        unit_name=None,
        gas_category=None,
        manual_override=False,
    ):
        """Write all four component currents and both derived maxima."""
        if layer is None or not layer.isValid():
            raise ValueError("Kies een geldige ontwerpstroomlaag.")
        if layer.isEditable():
            raise ValueError("Sla de bestaande bewerkingen eerst op.")
        provider = layer.dataProvider()
        if not provider.capabilities() & QgsVectorDataProvider.ChangeAttributeValues:
            raise ValueError("De ontwerpstroomlaag kan niet worden aangepast.")

        indices = {
            name: layer.fields().lookupField(name) for name in self.OUTPUT_FIELDS
        }
        required = (
            "Ontwerpstroom",
            "Ontwerpstroom kabel",
            "Opwek ontwerpstroom",
            "Kabel opwek ontwerpstroom",
            "Hoogste Trafo",
            "Hoogste Kabel",
        )
        if any(indices[name] < 0 for name in required):
            raise ValueError(
                "De laag mist een of meer verbruiks-, opwek- of hoogste stroomvelden."
            )
        category_index = self._ensure_category_field(provider, layer)
        if category_index < 0:
            raise ValueError("Het categorieveld 'HerstelCat' kan niet worden opgeslagen.")

        if category == "Huishoudelijk" and house_type is None:
            raise ValueError("Kies eerst een woningtype.")
        if category != "Huishoudelijk" or manual_override:
            if any(not math.isfinite(float(value)) or float(value) < 0 for value in currents.values()):
                raise ValueError("Vul geldige stroomwaarden van 0 A of hoger in.")
        metadata = {"HerstelHandmatig": "1" if manual_override else "0"}
        if unit_name is not None and category != "Huishoudelijk":
            metadata["HerstelType"] = str(unit_name)
        if gas_category is not None and category == "Zakelijk":
            if gas_category not in {stored for _, stored, _ in GAS_CHOICES}:
                raise ValueError("Kies een geldige gasaansluitcategorie.")
            gas_field = self.host._workflow_field_defaults().get("field_gas", "G_Type")
            metadata[gas_field] = gas_category
        for name in metadata:
            if layer.fields().lookupField(name) < 0:
                if not provider.addAttributes([QgsField(name, QVariant.String)]):
                    raise ValueError(f"Kolom '{name}' kon niet worden opgeslagen.")
                layer.updateFields()

        household_context = (
            self._household_context() if category == "Huishoudelijk" and not manual_override else None
        )
        selected_ids = {int(feature_id) for feature_id in feature_ids}
        changes = {}
        request = QgsFeatureRequest().setFilterFids(list(selected_ids))
        for feature in layer.getFeatures(request):
            if int(feature.id()) not in selected_ids:
                continue
            if category == "Huishoudelijk" and not manual_override:
                if house_type is None:
                    raise ValueError("Kies eerst een woningtype.")
                normal, cable_current, generation, generation_cable = (
                    self._household_currents(
                        layer, feature, house_type, household_context
                    )
                )
                stored_house_type = house_type
            else:
                normal = float(currents["consumption_trafo"])
                cable_current = float(currents["consumption_cable"])
                generation = float(currents["generation_trafo"])
                generation_cable = float(currents["generation_cable"])
                stored_house_type = self._field_value(
                    feature, "Gevonden_Woningtype"
                )
                if category == "Huishoudelijk":
                    stored_house_type = house_type
            values = {
                "Ontwerpstroom": normal,
                "Ontwerpstroom kabel": cable_current,
                "Opwek ontwerpstroom": generation,
                "Kabel opwek ontwerpstroom": generation_cable,
                "Hoogste Trafo": max(normal, generation),
                "Hoogste Kabel": max(cable_current, generation_cable),
                "Gevonden_Woningtype": stored_house_type,
            }
            attributes = {
                indices[name]: value
                for name, value in values.items()
                if indices[name] >= 0
            }
            attributes[category_index] = category
            if category == "Huishoudelijk" and layer.fields().lookupField("HerstelType") >= 0:
                attributes[layer.fields().lookupField("HerstelType")] = house_type
            attributes.update({layer.fields().lookupField(name): val for name, val in metadata.items()})
            changes[int(feature.id())] = attributes

        if not changes:
            raise ValueError("De geselecteerde aansluitingen zijn niet meer beschikbaar.")
        if not provider.changeAttributeValues(changes):
            raise ValueError("De ontwerpstroomwaarden konden niet worden opgeslagen.")
        layer.updateFields()
        layer.triggerRepaint()
        project = QgsProject.instance()
        project.setDirty(True)
        if project.fileName():
            project.write()
        return len(changes)

    def apply_category(self):
        ids = self._selected_feature_ids()
        if self.layer is None or not ids:
            self.status_label.setText("Selecteer eerst een of meer regels uit de lijst.")
            return
        if self.layer.isEditable():
            QMessageBox.warning(
                self,
                "Laag in bewerkingsmodus",
                "Sla de bestaande bewerkingen in de ontwerpstroomlaag eerst op.",
            )
            return

        category = self.category_combo.currentData()
        if category == "Huishoudelijk":
            if self.housing_combo.currentData() is None:
                self.status_label.setText("Kies eerst een woningtype.")
                return
        elif not self.manual_checkbox.isChecked() and max(
            self.trafo_spin.value(), self.generation_trafo_spin.value()
        ) <= 0:
            self.status_label.setText(
            "Vul voor trafoverbruik of trafo-opwek een ontwerpstroom groter dan 0 A in."
            )
            return

        currents = {
            "consumption_trafo": self.trafo_spin.value(),
            "consumption_cable": self.cable_spin.value(),
            "generation_trafo": self.generation_trafo_spin.value(),
            "generation_cable": self.generation_cable_spin.value(),
        }
        try:
            count = self.apply_values_to_layer(
                self.layer,
                ids,
                category,
                currents,
                self.housing_combo.currentData(),
                unit_name=unit_description(category, self.unit_combo.currentData()) if category != "Huishoudelijk" else None,
                gas_category=self.gas_combo.currentData() if category == "Zakelijk" else None,
                manual_override=self.manual_checkbox.isChecked(),
            )
        except (ValueError, KeyError, TypeError) as exc:
            self.status_label.setText(str(exc))
            return
        self.layer.removeSelection()
        if self.host.iface is not None:
            self.host.iface.mapCanvas().refresh()
        remaining = self.refresh()
        self.status_label.setText(
            f"{count} aansluiting(en) opgeslagen als {self.category_combo.currentText()}. "
            f"Nog {remaining} aansluiting(en) zonder ontwerpstroom."
        )
