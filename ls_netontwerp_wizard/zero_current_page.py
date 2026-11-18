"""Review and repair connections without a design current."""

from __future__ import annotations

import math

from qgis.PyQt.QtCore import QSettings, QTimer, Qt, QVariant
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
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
    unit_currents, unit_future_connection, category_note,
)
from .current_edit_metadata import (
    business_choice_connection, current_choice, current_choice_values, save_current_choices,
)
from . import kader_20
from .current_inputs import connect_current_edits, set_current_values
from .bag_current_rules import (
    NEW_BUILD_FIELD, NEW_BUILD_TYPE_FIELD, NEW_BUILD_TYPE_3,
    has_residential_usage, is_bag_object, is_new_build_flag,
)


class ZeroCurrentPage(QWidget):
    """Table-driven manual categorization of zero-current connection points."""

    CATEGORY_CHOICES = (
        ("Huishoudelijk", "Huishoudelijk"),
        ("Zakelijk", "Zakelijk"),
        ("Oplaadpunt", "Oplaadpunt"),
        ("Straatmeubilair", "Straatmeubilair"),
    )
    CATEGORY_FIELD = "HerstelCat"
    KEEP_EXISTING_UNIT = "__keep_existing__"
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
        self._splitter_restored = False
        self._layout_settings = getattr(host, "settings", None) or QSettings()
        self._splitter_key = (
            getattr(host, "SETTINGS_PREFIX", "LSNetontwerpWizard/")
            + "zero_current_splitter"
        )
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 10)
        # This page already has a fixed header/footer and a scrollable editor.
        # Keep dashboard normalization from wrapping the splitter in a second
        # scroll area, which would prevent it from filling the window.
        self.setProperty("uiStructured", True)
        self.setProperty("uiFooter", True)
        self.setProperty("uiRole", "page")
        self.home_button = self.host._add_subpage_header(
            root,
            "Ontwerpstroom nulwaarden herstellen",
            "TechBase • controleer de aansluitingen waarvoor geen ontwerpstroom is berekend",
        )
        self.host.zero_current_home_button = self.home_button

        instructions = (
            "De lijst toont aansluitingen met een ontbrekende of nulwaarde in "
            "<b>Hoogste Trafo</b> en verblijfsobjecten met andere gebruiksdoelen "
            "die je nog moet beoordelen. Selecteer één of meerdere aansluitingen, "
            "gebruik Ctrl of Shift voor meerdere regels, zoom naar de "
            "kaartselectie en kies daarna de juiste categorie. Bij iedere "
            "categorie kun je trafo- en kabelverbruik en "
            "trafo- en kabelopwek apart instellen. Alle zes ontwerpstroomvelden "
            "worden opgeslagen; de hoogste waarden worden uit verbruik en opwek berekend."
        )
        note = QLabel(
            "Selecteer aansluitingen met Ctrl of Shift en kies hieronder de juiste categorie. "
            "<b>Sleep de balk onder de lijst</b> om de tabel groter of kleiner te maken."
        )
        note.setWordWrap(True)
        note.setToolTip(instructions)
        root.addWidget(note)

        orientation = Qt.Orientation.Vertical if hasattr(Qt, "Orientation") else Qt.Vertical
        self.splitter = QSplitter(orientation)
        self.splitter.setObjectName("zeroCurrentSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(12)
        self.splitter.setStyleSheet(
            "QSplitter#zeroCurrentSplitter::handle:vertical {"
            "background: #CBD5E1; margin: 2px 8px; border-radius: 3px;}"
            "QSplitter#zeroCurrentSplitter::handle:vertical:hover {background: #F59E0B;}"
        )
        root.addWidget(self.splitter, 1)

        selection_group = QGroupBox("Aansluitingen zonder ontwerpstroom")
        selection_layout = QVBoxLayout(selection_group)
        selection_top = QHBoxLayout()
        self.count_label = QLabel("Lijst nog niet vernieuwd")
        self.count_label.setStyleSheet("font-weight:700;")
        self.refresh_button = QPushButton("Lijst vernieuwen")
        self.refresh_button.clicked.connect(lambda _checked=False: self.refresh(review_layer=self.layer))
        self.zoom_button = QPushButton("Zoom naar selectie")
        self.zoom_button.setObjectName("secondaryButton")
        self.zoom_button.clicked.connect(self.zoom_to_selection)
        selection_top.addWidget(self.count_label, 1)
        selection_top.addWidget(self.zoom_button)
        selection_top.addWidget(self.refresh_button)
        selection_layout.addLayout(selection_top)

        self.table = QTableWidget(0, 14)
        expanding = QSizePolicy.Policy.Expanding if hasattr(QSizePolicy, "Policy") else QSizePolicy.Expanding
        self.table.setSizePolicy(expanding, expanding)
        self.table.setMinimumHeight(140)
        self.table.setHorizontalHeaderLabels(
            (
                "FID",
                "ID",
                "Adres",
                "Gebruiksdoel",
                "Doorlaatwaarde",
                "Gas (bron)",
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
        self.table.horizontalHeader().setSectionResizeMode(3, stretch)
        self.table.horizontalHeader().setSectionResizeMode(6, stretch)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.cellDoubleClicked.connect(lambda _row, _column: self.zoom_to_selection())
        selection_layout.addWidget(self.table, 1)
        selection_group.setMinimumHeight(200)
        self.splitter.addWidget(selection_group)

        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setMinimumHeight(140)
        no_frame = QFrame.Shape.NoFrame if hasattr(QFrame, "Shape") else QFrame.NoFrame
        self.editor_scroll.setFrameShape(no_frame)
        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 8, 0)
        constraints = QLayout.SizeConstraint if hasattr(QLayout, "SizeConstraint") else QLayout
        editor_layout.setSizeConstraint(constraints.SetMinimumSize)
        self.editor_scroll.setWidget(editor)
        self.splitter.addWidget(self.editor_scroll)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.handle(1).setToolTip(
            "Sleep omhoog of omlaag om de hoogte van de aansluitingenlijst aan te passen."
        )
        self.splitter.splitterMoved.connect(self._save_splitter_layout)

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
            "op basis van bouwjaar. Nieuwbouw-verblijfsobjecten houden altijd de "
            "nieuwbouwtabel, ook bij een ouder of onbekend pandbouwjaar."
        )
        self.housing_note.setWordWrap(True)
        category_form.addRow("", self.housing_note)
        self.kader20_type_combo = QComboBox()
        for label, value in (
            ("Bouwjaar-aanname (controleer verwarming)", None),
            ("Type 1 - laagbouw met individuele warmtepomp", "Type 1"),
            ("Type 2 - laagbouw met gas/stadsverwarming", "Type 2"),
            ("Type 3 - hoogbouw collectieve verwarming", "Type 3"),
            ("Type 4 - hoogbouw individuele warmtepomp", "Type 4"),
        ):
            self.kader20_type_combo.addItem(label, value)
        category_form.addRow("Kader 2.0 verwarming", self.kader20_type_combo)
        self.kader20_type_label = category_form.labelForField(self.kader20_type_combo)
        self.kader20_type_combo.currentIndexChanged.connect(self._household_changed)

        self.unit_group = QGroupBox("Type wooneenheid / aansluiting")
        self.unit_group.setProperty("uiContentMinimum", True)
        unit_form = QFormLayout(self.unit_group)
        self.unit_combo = QComboBox()
        unit_form.addRow("Type wooneenheid", self.unit_combo)
        self.gas_combo = QComboBox()
        self.fill_gas_choices(self.gas_combo)
        self.gas_label = QLabel("Gasaansluiting")
        unit_form.addRow(self.gas_label, self.gas_combo)
        self.unit_note = QLabel()
        self.unit_note.setWordWrap(True)
        unit_form.addRow(self.unit_note)
        self.unit_combo.currentIndexChanged.connect(self._unit_changed)
        self.gas_combo.currentIndexChanged.connect(self._gas_changed)
        editor_layout.addWidget(category_group)
        editor_layout.addWidget(self.unit_group)

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
        editor_layout.addWidget(self.current_values_group)
        editor_layout.addStretch(1)
        connect_current_edits(self._current_spins(), self.manual_checkbox)

        self.status_label = QLabel("Selecteer een of meer regels om te herstellen.")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        footer = QWidget()
        footer.setProperty("uiRole", "footer")
        buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.addStretch(1)
        self.apply_button = QPushButton("Categorie en ontwerpstroom opslaan")
        self.apply_button.clicked.connect(self.apply_category)
        buttons.addWidget(self.apply_button)
        close_button = QPushButton("Sluiten")
        close_button.setObjectName("secondaryButton")
        close_button.clicked.connect(self.host.close)
        buttons.addWidget(close_button)
        root.addWidget(footer)
        self._category_changed()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._splitter_restored:
            # Restore only after the host has assigned this page its final size.
            QTimer.singleShot(0, self._restore_splitter_layout)

    def _restore_splitter_layout(self):
        if self._splitter_restored:
            return
        state = self._layout_settings.value(self._splitter_key)
        restored = False
        if state is not None:
            try:
                restored = self.splitter.restoreState(state)
            except (TypeError, ValueError):
                pass
        if not restored:
            self.splitter.setSizes([640, 260])
        self._splitter_restored = True

    def _save_splitter_layout(self, _position, _index):
        if self._splitter_restored:
            self._layout_settings.setValue(
                self._splitter_key, self.splitter.saveState()
            )

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
        defaults = self.host._workflow_field_defaults()
        for feature in layer.getFeatures():
            value = self._numeric(feature[highest_field])
            unreviewed_object = (
                is_bag_object(self._field_value(feature, defaults.get("field_passthrough", "service_connection_type_type")))
                and not has_residential_usage(self._field_value(feature, defaults.get("field_usage", "Gebruiksdoel")))
                and not current_choice(layer, feature, "HerstelCat")
            )
            if unreviewed_object or value is None or value <= 0.0:
                result.append(feature)
        return result

    def refresh(self, select_first=False, review_layer=None):
        self.layer = review_layer if review_layer is not None else self._review_layer()
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
        gas_field = field(values.get("field_gas", "G_Type"), "G_Type")

        try:
            features = self._zero_features(self.layer)
        except ValueError as exc:
            self.count_label.setText("Laag mist ontwerpstroomvelden")
            self.status_label.setText(str(exc))
            self._sync_host_button(0)
            self.table.setSortingEnabled(True)
            self._changing_selection = False
            return 0

        self.count_label.setText(f"{len(features)} aansluiting(en) zonder ontwerpstroom of nog te beoordelen")
        self._sync_host_button(len(features))
        for feature in features:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values_to_show = (
                self._field_value(feature, fid_field, str(feature.id())),
                self._field_value(feature, id_field) or self._field_value(feature, "BAG_VBO_ID"),
                " ".join(filter(None, (self._field_value(feature, "street"),
                                       self._field_value(feature, "housenumber") + self._field_value(feature, "toevoeging"),
                                       self._field_value(feature, "huisnummertoevoeging"),
                                       self._field_value(feature, "zip_code"),
                                       self._field_value(feature, "parish")))),
                self._field_value(feature, usage_field),
                self._field_value(feature, pass_field),
                self._field_value(feature, gas_field) or "Onbekend (leeg)",
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
        type20_visible = (
            is_household
            and self.host._workflow_field_defaults().get("design_framework") == "2.0"
        )
        self.kader20_type_combo.setVisible(type20_visible)
        self.kader20_type_label.setVisible(type20_visible)
        if type20_visible:
            self.housing_note.setText(
                "Kader 2.0 onderscheidt verwarmingswijze, niet bouwjaar. "
                "Kies Type 1-4 als deze bekend is; anders is bouwjaar een "
                "gemarkeerde aanname."
            )
        self.current_values_group.setVisible(True)
        self.manual_checkbox.setChecked(False)
        self.unit_group.setVisible(not is_household)
        gas_relevant = code == "Zakelijk"
        self.gas_combo.setVisible(gas_relevant)
        self.gas_label.setVisible(gas_relevant)
        self.fill_unit_choices(self.unit_combo, code, self.host._workflow_field_defaults().get('design_framework'))
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
        try:
            rows = [
                self._household_currents(
                    self.layer, feature, self.housing_combo.currentData(),
                    context, self.kader20_type_combo.currentData(),
                )
                for feature in features
            ]
        except (ValueError, TypeError) as exc:
            self.housing_note.setText(str(exc))
            rows = []
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
            "De tabelberekening blijft per aansluiting actief, met eigen brongegevens en apart gasadvies voor trafo en kabel. "
            "De velden tonen het maximum in de selectie. Typ een waarde om zelf in te vullen."
        )

    def _unit_changed(self, *_args):
        category = self.category_combo.currentData()
        key = self.unit_combo.currentData()
        self.manual_checkbox.setChecked(False)
        ids = self._selected_feature_ids()
        features = list(self.layer.getFeatures(QgsFeatureRequest().setFilterFids(ids))) if self.layer is not None and ids else []
        currents, note = self.unit_preview(
            self._household_context(), features, category, key,
            self.gas_combo.currentData(), layer=self.layer,
        )
        self.unit_note.setText(note)
        if currents is not None:
            set_current_values(self._current_spins(), currents)
            self.current_values_note.setText(
                "Deze velden tonen het maximum per stroomsoort in de selectie. "
                "Bij opslaan wordt iedere aansluiting apart berekend; trafo en kabel kunnen verschillen."
            )
        elif category != "Huishoudelijk" and key is None:
            self.manual_checkbox.setChecked(True)

    def _gas_changed(self, *_args):
        if self.manual_checkbox.isChecked():
            self.unit_note.setText(
                "Je handmatige vier stroomwaarden blijven behouden. "
                + ("Elke aansluiting behoudt haar eigen gaswaarde."
                   if self.gas_combo.currentData() is None
                   else "De gekozen gascategorie wordt voor de selectie opgeslagen.")
            )
            return
        self._unit_changed()

    @staticmethod
    def fill_gas_choices(combo):
        fill_gas_combo(combo)
        combo.insertItem(0, "Bestaande gaswaarde per aansluiting behouden", None)
        combo.setCurrentIndex(0)

    @staticmethod
    def fill_unit_choices(combo, category, framework):
        fill_unit_combo(combo, category, framework)
        if category == "Zakelijk":
            previous = combo.blockSignals(True)
            label = (
                "Toekomstige waarde gebruiken; anders huidige aansluiting"
                if str(framework) == "2.0"
                else "Bestaande aansluitwaarde per aansluiting behouden"
            )
            combo.insertItem(0, label, ZeroCurrentPage.KEEP_EXISTING_UNIT)
            combo.setCurrentIndex(0)
            combo.blockSignals(previous)

    @staticmethod
    def _business_currents(feature, context, gas_category=None,
                           future_connection=None, unit_key=None, layer=None):
        """Return four currents, basis, gas, current supply and basis provenance."""
        module, values, standard, cable, opwek, opwek_cable = context
        current_service = ZeroCurrentPage._field_value(
            feature, values.get("field_passthrough", "service_connection_type_type")
        )
        actual_gas = (
            gas_category if gas_category is not None else ZeroCurrentPage._field_value(
                feature, values.get("field_gas", "G_Type")
            )
        )
        preset = unit_future_connection("Zakelijk", unit_key)
        saved_preset = ZeroCurrentPage._saved_business_connection(
            layer, feature, standard.get("FRAMEWORK_VERSION", "3.0")
        )
        chosen_future = None
        basis_provenance = "current"
        kwargs = {}
        service = current_service
        if standard.get("FRAMEWORK_VERSION") == "2.0":
            explicit_future = (
                future_connection or preset
                or ZeroCurrentPage._field_value(feature, "Kader20ToekomstigeAansluitwaarde")
                or saved_preset
            )
            phases, amps = module.parse_doorlaat(current_service)
            chosen_future, basis_provenance = module.kader_20.business_future_basis(
                phases, amps, explicit_future=explicit_future,
            )
            kwargs["kader20_future"] = chosen_future
        elif preset:
            service = preset
            basis_provenance = "explicit"
        elif saved_preset:
            service = saved_preset
            basis_provenance = "explicit"
        one_phase = bool(values.get("one_phase_exception", True))
        normal = float(module.calculate_ontwerpstroom(
            service, "bedrijf", "", 0, actual_gas, standard,
            feature.id(), None, one_phase, **kwargs
        ))
        cable_current = float(module.calculate_ontwerpstroom(
            service, "bedrijf", "", 0, actual_gas, cable,
            feature.id(), None, one_phase, **kwargs
        ))
        generation = float(module.calculate_opwek_ontwerpstroom(
            service, "bedrijf", "", actual_gas, opwek, standard,
            normal, one_phase, **kwargs
        ))
        generation_cable = float(module.calculate_opwek_ontwerpstroom(
            service, "bedrijf", "", actual_gas, opwek_cable, cable,
            cable_current, one_phase, **kwargs
        ))
        return (normal, cable_current, generation, generation_cable), chosen_future, actual_gas, (current_service if standard.get("FRAMEWORK_VERSION") == "2.0" else service), basis_provenance

    @staticmethod
    def _saved_business_connection(layer, feature, framework):
        return business_choice_connection(
            current_choice_values(layer, feature), framework,
        )

    @staticmethod
    def unit_preview(context, features, category, key, gas_category=None, layer=None):
        """Preview maxima without copying any connection's inputs to its peers."""
        if key is None:
            return None, "Vul de vier stroomwaarden zelf in; deze gelden voor de hele selectie."
        if category != "Zakelijk":
            return unit_currents(context, category, key), category_note(category, key, context[1].get("design_framework"))
        calculated = [ZeroCurrentPage._business_currents(
            feature, context, gas_category=gas_category, unit_key=key, layer=layer
        ) for feature in features]
        rows = [result[0] for result in calculated]
        preview = tuple(max(column) for column in zip(*rows)) if rows else (0.0,) * 4
        notes = [
            "Iedere aansluiting wordt apart berekend; de velden tonen het maximum per stroomsoort.",
            "Bestaande gaswaarden blijven per aansluiting behouden."
            if gas_category is None else "De gekozen gascategorie geldt voor alle geselecteerde aansluitingen.",
        ]
        if context[2].get("FRAMEWORK_VERSION") == "2.0":
            if key == ZeroCurrentPage.KEEP_EXISTING_UNIT:
                futures = sorted({str(result[1]) for result in calculated if result[1] and result[4] == "explicit"})
                if futures:
                    notes.append("Opgeslagen toekomstige aansluitwaarde(n): " + ", ".join(futures) + ".")
                current_bases = sorted({str(result[1]) for result in calculated if result[4] == "current"})
                if current_bases:
                    notes.append("Huidige aansluiting gebruikt: " + ", ".join(current_bases) + " (geen afzonderlijke toekomstige waarde vastgelegd).")
                if any(result[4] == "minimum" for result in calculated):
                    notes.append("Kleinzakelijke minimumregel: 3 x 25 A.")
                missing = sum(result[4] == "undefined" for result in calculated)
                if missing:
                    notes.append(f"Bij {missing} aansluiting(en) ontbreekt een ondersteunde aansluitwaarde; kies een toekomstige waarde of vul de stromen handmatig in.")
                unsupported = sum(result[4] == "explicit" and max(result[0][0], result[0][2]) <= 0 for result in calculated)
                if unsupported:
                    notes.append(f"Bij {unsupported} aansluiting(en) heeft de gekozen toekomstige waarde geen vaste kaderwaarde; bepaal een passende toekomstwaarde of vul de stromen handmatig in.")
            else:
                notes.append(category_note(category, key, "2.0"))
        elif calculated:
            services = sorted({str(result[3]) or "Onbekend" for result in calculated})
            notes.append("Aansluitwaarde(n) voor berekening: " + ", ".join(services) + ".")
            if key == ZeroCurrentPage.KEEP_EXISTING_UNIT:
                notes.append("Een opgeslagen herstelprofiel blijft behouden; anders geldt de eigen huidige doorlaatwaarde.")
        if gas_category is None and calculated:
            source_gas = sorted({str(result[2]) or "Onbekend (leeg)" for result in calculated})
            notes.append("Gas uit bron: " + ", ".join(source_gas) + ".")
            unknown = sum(str(result[2]).strip().casefold() in ("", "onbekend", "null", "none", "nvt", "n.v.t.", "n/a") for result in calculated)
            if unknown:
                notes.append(f"Bij {unknown} aansluiting(en) is de gasbron onbekend; de bestaande standaardgroep wordt toegepast. Controleer de gasbron; de bron blijft ongewijzigd.")
        return preview, "\n".join(notes)

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
            if self.category_combo.currentData() == "Huishoudelijk":
                self._household_changed()
            else:
                self._unit_changed()

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

    def _household_context(self):
        from .algorithms.woningtype_selectie_herberekenen_tool import (
            _configurations,
            _load_design_module,
        )

        module = _load_design_module()
        values = self.host._workflow_field_defaults()
        standard, cable, opwek, opwek_cable = _configurations(values, module)
        return module, values, standard, cable, opwek, opwek_cable

    def _household_currents(self, layer, feature, house_type, context, kader20_override=None):
        module, values, standard, cable, opwek, opwek_cable = context
        year_field = layer.fields().lookupField("Gevonden_Bouwjaar")
        year = feature[year_field] if year_field >= 0 else None
        try:
            year = int(float(year))
        except (TypeError, ValueError):
            year = 0
        year_limit = int(standard.get("DEFAULTS", {}).get("bouwjaar_grens", 2022))
        new_build = year >= year_limit or (
            is_bag_object(self._field_value(feature, values.get("field_passthrough", "service_connection_type_type")))
            and is_new_build_flag(self._field_value(feature, NEW_BUILD_FIELD))
        )
        usage = (
            "appartement" if "appartement" in str(house_type).casefold()
            else "woonhuis"
        )
        one_phase = bool(values.get("one_phase_exception", True))
        effective_year = max(year, year_limit) if new_build else year
        type_field = feature.fields().lookupField("Kader20Type")
        explicit_type = (
            str(feature[type_field]).strip()
            if type_field >= 0 and str(feature[type_field]).strip().casefold()
            not in ("", "null", "none")
            else None
        )
        if standard.get("FRAMEWORK_VERSION") == "2.0" and kader20_override:
            explicit_type = kader20_override
        if standard.get("FRAMEWORK_VERSION") == "2.0":
            actual_service = self._field_value(
                feature, values.get(
                    "field_passthrough", "service_connection_type_type"
                )
            )
            phases, amps = module.parse_doorlaat(actual_service)
            if phases and (phases > 3 or amps > 40):
                raise ValueError(
                    "Deze woonhuisaansluiting is zwaarder dan 3x40 A. "
                    "Gebruik de zakelijke Kader 2.0-categorie en kies de "
                    "toekomstige aansluitwaarde."
                )
            # Presets must calculate on the selected Kader, not always use
            # the legacy raw WOONHUIS matrix bypassing Kader 2.0.
            normal = float(module.calculate_ontwerpstroom(
                "3 x 25 A", usage, house_type, effective_year, "",
                standard, feature.id(), None, one_phase, True, explicit_type,
            ))
            cable_current = float(module.calculate_ontwerpstroom(
                "3 x 25 A", usage, house_type, effective_year, "",
                cable, feature.id(), None, one_phase, True, explicit_type,
            ))
        else:
            standard_table = standard.get("WOONHUIS_2022") if new_build else standard["WOONHUIS"]
            cable_table = cable.get("WOONHUIS_2022") if new_build else cable["WOONHUIS"]
            normal = float(module.woonhuis_ontwerp(house_type, standard_table))
            cable_current = float(module.woonhuis_ontwerp(house_type, cable_table))
        generation = float(module.calculate_opwek_ontwerpstroom(
            None, usage, house_type, "", opwek, standard, normal, one_phase,
            effective_year, explicit_type,
        ))
        generation_cable = float(module.calculate_opwek_ontwerpstroom(
            None, usage, house_type, "", opwek_cable, cable, cable_current,
            one_phase, effective_year, explicit_type,
        ))
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
        future_connection=None,
        kader20_override=None,
        unit_key=None,
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
        if category == "Huishoudelijk" and house_type is None:
            raise ValueError("Kies eerst een woningtype.")
        if category != "Huishoudelijk" or manual_override:
            if any(not math.isfinite(float(value)) or float(value) < 0 for value in currents.values()):
                raise ValueError("Vul geldige stroomwaarden van 0 A of hoger in.")
        selected_connection = unit_future_connection(category, unit_key) if not manual_override else None
        framework = self.host._workflow_field_defaults().get("design_framework", "3.0")
        metadata = {"HerstelCat": category, "HerstelType": str(house_type or unit_name or ""),
                    "HerstelHandmatig": "1" if manual_override else "0",
                    "HerstelKeuze": str(unit_key) if selected_connection else "",
                    "HerstelAansluitwaarde": selected_connection or "",
                    "HerstelKader": str(framework)}
        if framework == "2.0" and category == "Zakelijk" and not manual_override:
            future_connection = future_connection or selected_connection
        original_updates = {}
        if (
            framework == "2.0" and category == "Zakelijk"
            and future_connection is not None and not manual_override
        ):
            original_updates["Kader20ToekomstigeAansluitwaarde"] = future_connection
        if (
            framework == "2.0" and category == "Huishoudelijk"
            and kader20_override and not manual_override
        ):
            original_updates["Kader20Type"] = kader20_override
        if unit_name is not None and category != "Huishoudelijk":
            metadata["HerstelType"] = str(unit_name)
        if gas_category is not None and category == "Zakelijk":
            if gas_category not in {stored for _, stored, _ in GAS_CHOICES}:
                raise ValueError("Kies een geldige gasaansluitcategorie.")
            gas_field = self.host._workflow_field_defaults().get("field_gas", "G_Type")
            original_updates[gas_field] = gas_category
        editable_fields = set(original_updates)
        if framework == "2.0" and category == "Zakelijk" and not manual_override:
            # A preserved legacy preset/minimum can be known even when this
            # older layer has no future column yet. Store only the individually
            # resolved value below; never fill unknown futures for the group.
            editable_fields.add("Kader20ToekomstigeAansluitwaarde")
        for name in editable_fields:
            if layer.fields().lookupField(name) < 0:
                if not provider.addAttributes([QgsField(name, QVariant.String)]):
                    raise ValueError(f"Kolom '{name}' kon niet worden opgeslagen.")
                layer.updateFields()

        household_context = (
            self._household_context()
            if not manual_override and (
                category == "Huishoudelijk"
                or category == "Zakelijk"
            ) else None
        )
        selected_ids = {int(feature_id) for feature_id in feature_ids}
        changes = {}
        metadata_groups = {}
        request = QgsFeatureRequest().setFilterFids(list(selected_ids))
        for feature in layer.getFeatures(request):
            if int(feature.id()) not in selected_ids:
                continue
            auto_future_for_feature = None
            if category == "Huishoudelijk" and not manual_override:
                if house_type is None:
                    raise ValueError("Kies eerst een woningtype.")
                normal, cable_current, generation, generation_cable = (
                    self._household_currents(
                        layer, feature, house_type, household_context,
                        kader20_override,
                    )
                )
                stored_house_type = house_type
            elif category == "Zakelijk" and not manual_override:
                # Every Kader uses this connection's gas. In 2.0 the chosen
                # FUTURE supply stays separate from its CURRENT GEN supply.
                module, values_context, standard, cable_config, opwek, opwek_cable = household_context
                calculated, chosen_future, actual_gas, current_service, basis_provenance = self._business_currents(
                    feature, household_context, gas_category=gas_category,
                    future_connection=future_connection, unit_key=unit_key, layer=layer,
                )
                normal, cable_current, generation, generation_cable = calculated
                stored_house_type = self._field_value(
                    feature, "Gevonden_Woningtype"
                )
                if (chosen_future and basis_provenance in ("explicit", "minimum")
                        and not future_connection
                        and not self._field_value(feature, "Kader20ToekomstigeAansluitwaarde")):
                    auto_future_for_feature = chosen_future
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
            # New-build provenance survives manual corrections; the Type 3
            # description must reflect the chosen low-rise housing category.
            type_index = layer.fields().lookupField(NEW_BUILD_TYPE_FIELD)
            if type_index >= 0 and is_new_build_flag(self._field_value(feature, NEW_BUILD_FIELD)):
                attributes[type_index] = (
                    NEW_BUILD_TYPE_3 if category == "Huishoudelijk" and house_type
                    and "appartement" not in str(house_type).casefold() else ""
                )
            framework_index = layer.fields().lookupField("KaderVersie")
            if framework_index >= 0:
                attributes[framework_index] = str(framework)
            if framework == "2.0":
                type_index20 = layer.fields().lookupField("KaderType")
                if type_index20 >= 0 and category == "Zakelijk":
                    if manual_override:
                        attributes[type_index20] = "Kader 2.0 Type 6/7 - handmatig ingevoerd"
                    else:
                        current_phases, current_amp = module.parse_doorlaat(
                            current_service
                        )
                        future_phases, future_amp = module.parse_doorlaat(
                            chosen_future
                        )
                        _value, description, _warning = module.kader_20.current(
                            "trafo", 10, "", 0, future_phases, future_amp,
                            gas_category=module.normalize_gas(actual_gas),
                            current_phases=current_phases,
                            current_amp=current_amp,
                        )
                        if basis_provenance == "current":
                            description = description.replace("toekomstige aansluitwaarde", "huidige aansluitwaarde als automatische basis")
                            description += " (toekomstige waarde niet opgegeven)"
                        elif basis_provenance == "minimum":
                            description += " (automatisch kleinzakelijk min. 3x25A)"
                        if str(actual_gas).strip().casefold() in ("", "onbekend", "null", "none", "nvt", "n.v.t.", "n/a"):
                            description += " (gasbron onbekend; standaardgroep toegepast, controleren)"
                        attributes[type_index20] = description
                if type_index20 >= 0 and category == "Huishoudelijk":
                    if manual_override:
                        attributes[type_index20] = "Kader 2.0 - handmatig ingevoerd"
                    else:
                        raw_year = self._field_value(feature, "Gevonden_Bouwjaar")
                        try:
                            effective_year = int(float(raw_year))
                        except (ValueError, TypeError):
                            effective_year = 0
                        if is_new_build_flag(self._field_value(feature, NEW_BUILD_FIELD)):
                            effective_year = max(effective_year, 2022)
                        explicit = (
                            kader20_override
                            or self._field_value(feature, "Kader20Type")
                            or None
                        )
                        _current, label, _warning = kader_20.current(
                            "trafo", 4 if kader_20.normalize_housing(house_type)
                            == "appartement" else 1,
                            house_type, effective_year, 3, 25,
                            explicit_type=explicit,
                        )
                        attributes[type_index20] = label
            else:
                profile_index = layer.fields().lookupField("KaderType")
                if profile_index >= 0:
                    attributes[profile_index] = (
                        f"Kader {framework} - handmatig ingevoerd" if manual_override else ""
                    )
            attributes.update({layer.fields().lookupField(name): val
                               for name, val in original_updates.items()})
            if auto_future_for_feature:
                field_future = layer.fields().lookupField(
                    "Kader20ToekomstigeAansluitwaarde"
                )
                if field_future >= 0:
                    attributes[field_future] = auto_future_for_feature
            changes[int(feature.id())] = attributes
            feature_metadata = dict(metadata)
            if (category == "Zakelijk" and not manual_override
                    and framework != "2.0" and not selected_connection
                    and current_choice(layer, feature, "HerstelCat") == "Zakelijk"):
                # Preserve each existing 3.x profile when no common preset was
                # explicitly chosen for the selection.
                saved_connection = self._saved_business_connection(layer, feature, framework)
                feature_metadata["HerstelAansluitwaarde"] = saved_connection or ""
                feature_metadata["HerstelKeuze"] = current_choice(layer, feature, "HerstelKeuze") if saved_connection else ""
            metadata_groups.setdefault(tuple(sorted(feature_metadata.items())), []).append(int(feature.id()))

        if not changes:
            raise ValueError("De geselecteerde aansluitingen zijn niet meer beschikbaar.")
        if not provider.changeAttributeValues(changes):
            raise ValueError("De ontwerpstroomwaarden konden niet worden opgeslagen.")
        for choices, feature_ids in metadata_groups.items():
            save_current_choices(layer, feature_ids, dict(choices))
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
                unit_name=self.unit_combo.currentText() if category != "Huishoudelijk" else None,
                gas_category=(
                    self.gas_combo.currentData()
                    if category == "Zakelijk"
                    else None
                ),
                manual_override=self.manual_checkbox.isChecked(),
                future_connection=(
                    unit_future_connection(category, self.unit_combo.currentData())
                    if category == "Zakelijk"
                    and self.host._workflow_field_defaults().get("design_framework") == "2.0"
                    else None
                ),
                kader20_override=(
                    self.kader20_type_combo.currentData()
                    if category == "Huishoudelijk"
                    and self.host._workflow_field_defaults().get("design_framework") == "2.0"
                    else None
                ),
                unit_key=self.unit_combo.currentData() if category != "Huishoudelijk" else None,
            )
        except (ValueError, KeyError, TypeError) as exc:
            self.status_label.setText(str(exc))
            return
        self.layer.removeSelection()
        if self.host.iface is not None:
            self.host.iface.mapCanvas().refresh()
        remaining = self.refresh(review_layer=self.layer)
        self.status_label.setText(
            f"{count} aansluiting(en) opgeslagen als {self.category_combo.currentText()}. "
            f"Nog {remaining} aansluiting(en) zonder ontwerpstroom of nog te beoordelen."
        )

