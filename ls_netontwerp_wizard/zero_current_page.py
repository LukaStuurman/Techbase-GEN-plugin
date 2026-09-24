"""Review and repair connections without a design current."""

from __future__ import annotations

import math

from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
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
            "kaartselectie en kies daarna de juiste categorie. "
            "De categorie en bijbehorende stroomwaarden worden blijvend op de laag opgeslagen."
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

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            (
                "FID",
                "ID",
                "Gebruiksdoel",
                "Doorlaatwaarde",
                "Woningtype",
                "Bouwjaar",
                "Hoogste Trafo (A)",
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

        from .algorithms.woningtype_selectie_herberekenen_tool import HOUSING_CHOICES

        self.housing_combo = QComboBox()
        for label, stored in HOUSING_CHOICES:
            self.housing_combo.addItem(label, stored)
        category_form.addRow("Woningtype", self.housing_combo)
        self.housing_note = QLabel(
            "De ingestelde oude/nieuwbouwtabellen worden per aansluiting gekozen "
            "op basis van bouwjaar. Bij een onbekend bouwjaar wordt de oude tabel gebruikt."
        )
        self.housing_note.setWordWrap(True)
        category_form.addRow("", self.housing_note)

        self.current_values_group = QGroupBox("Handmatige ontwerpstroom")
        current_form = QFormLayout(self.current_values_group)
        self.trafo_spin = self._current_spin()
        self.cable_spin = self._current_spin()
        current_form.addRow("Hoogste Trafo (A)", self.trafo_spin)
        current_form.addRow("Hoogste Kabel (A)", self.cable_spin)
        category_form.addRow(self.current_values_group)
        root.addWidget(category_group)

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
                self._field_value(feature, "Hoogste Trafo", "0"),
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
        self.housing_note.setVisible(is_household)
        self.current_values_group.setVisible(not is_household)
        if code == "Straatmeubilair":
            default_trafo = self._matrix_value("matrix_straat", 5.8)
            default_cable = default_trafo
        elif code == "Oplaadpunt":
            default_trafo = self._matrix_value("matrix_laad", 3.7)
            default_cable = self._matrix_value("matrix_laad_kabel", 4.8)
        elif code == "Zakelijk":
            default_trafo = 0.0
            default_cable = 0.0
        else:
            default_trafo = default_cable = 0.0
        self.trafo_spin.setValue(default_trafo)
        self.cable_spin.setValue(default_cable)

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

    def _ensure_category_field(self, provider):
        field_index = self.layer.fields().lookupField(self.CATEGORY_FIELD)
        if field_index >= 0:
            return field_index
        if not provider.capabilities() & QgsVectorDataProvider.AddAttributes:
            return -1
        if not provider.addAttributes(
            [QgsField(self.CATEGORY_FIELD, QVariant.String, len=20)]
        ):
            return -1
        self.layer.updateFields()
        return self.layer.fields().lookupField(self.CATEGORY_FIELD)

    def _household_context(self):
        from .algorithms.woningtype_selectie_herberekenen_tool import (
            _configurations,
            _load_design_module,
        )

        module = _load_design_module()
        values = self.host._workflow_field_defaults()
        standard, cable, opwek, opwek_cable = _configurations(values, module)
        return module, values, standard, cable, opwek, opwek_cable

    def _household_currents(self, feature, house_type, context):
        module, values, standard, cable, opwek, opwek_cable = context
        year_field = self.layer.fields().lookupField("Gevonden_Bouwjaar")
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
        elif self.trafo_spin.value() <= 0 or self.cable_spin.value() <= 0:
            self.status_label.setText(
                "Vul voor beide velden een ontwerpstroom groter dan 0 A in."
            )
            return

        provider = self.layer.dataProvider()
        if not provider.capabilities() & QgsVectorDataProvider.ChangeAttributeValues:
            self.status_label.setText("De ontwerpstroomlaag kan niet worden aangepast.")
            return
        indices = {
            name: self.layer.fields().lookupField(name) for name in self.OUTPUT_FIELDS
        }
        required = ("Hoogste Trafo", "Hoogste Kabel")
        if any(indices[name] < 0 for name in required):
            self.status_label.setText(
                "De laag mist Hoogste Trafo en/of Hoogste Kabel. Vernieuw stap 1."
            )
            return
        category_index = self._ensure_category_field(provider)
        if category_index < 0:
            self.status_label.setText(
                "De ontwerpstroomlaag kan geen categorieveld 'HerstelCat' opslaan. "
                "Sla de aansluitingen eerst op in een bewerkbare laag en probeer opnieuw."
            )
            return
        selected = set(ids)
        household_context = (
            self._household_context() if category == "Huishoudelijk" else None
        )
        changes = {}
        request = QgsFeatureRequest().setFilterFids(ids)
        for feature in self.layer.getFeatures(request):
            feature_id = int(feature.id())
            if feature_id not in selected:
                continue
            if category == "Huishoudelijk":
                normal, cable_current, generation, generation_cable = (
                    self._household_currents(
                        feature, self.housing_combo.currentData(), household_context
                    )
                )
                stored_house_type = self.housing_combo.currentData()
            elif category == "Zakelijk":
                normal = self.trafo_spin.value()
                cable_current = self.cable_spin.value()
                generation = normal
                generation_cable = cable_current
                stored_house_type = self._field_value(feature, "Gevonden_Woningtype")
            else:
                normal = self.trafo_spin.value()
                cable_current = self.cable_spin.value()
                generation = 0.0
                generation_cable = 0.0
                stored_house_type = self._field_value(feature, "Gevonden_Woningtype")
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
            if category_index >= 0:
                attributes[category_index] = category
            changes[feature_id] = attributes

        if not changes:
            self.status_label.setText(
                "De selectie staat niet meer in de lijst. Vernieuw de lijst."
            )
            self.refresh()
            return
        if not provider.changeAttributeValues(changes):
            self.status_label.setText("De ontwerpstroomwaarden konden niet worden opgeslagen.")
            return
        self.layer.updateFields()
        self.layer.triggerRepaint()
        project = QgsProject.instance()
        project.setDirty(True)
        if project.fileName():
            project.write()
        self.layer.removeSelection()
        if self.host.iface is not None:
            self.host.iface.mapCanvas().refresh()
        remaining = self.refresh()
        self.status_label.setText(
            f"{len(changes)} aansluiting(en) opgeslagen als {self.category_combo.currentText()}. "
            f"Nog {remaining} aansluiting(en) zonder ontwerpstroom."
        )
