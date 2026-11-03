from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from qgis.PyQt.QtCore import QSettings, QTimer, Qt
from qgis.PyQt.QtGui import QColor, QFont, QIcon, QPixmap
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    QgsCoordinateTransform,
    QgsGeometry,
    QgsProcessingFeedback,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis import processing

from .zero_current_page import ZeroCurrentPage
from .current_inputs import connect_current_edits, set_current_values, has_manual_currents
from .ui_theme import STYLE, apply_theme, install_dialog_theme
from .current_presets import (
    HOUSEHOLD_UNIT_CHOICES, fill_gas_combo, fill_unit_combo,
    unit_currents, unit_description, category_note, current_context,
)
from .station_name_csv import (
    find_master_asset_id_column,
    guess_station_name_column,
    load_station_name_lookup,
    read_station_csv,
)


TEXT_OPTIONS = {
    # Excel import
    "sheet_cable": ("Excel-tabblad kabels", "LS Kabel"),
    "sheet_joint": ("Excel-tabblad moffen", "LS OV Kabelmof"),
    "sheet_connection": ("Excel-tabblad aansluitkabels", "LS Aansluitkabel"),
    # Imported layer names
    "layer_points": ("LS-aansluitingenlaag", "e_lv_service_connection"),
    "layer_main_cables": ("Laagspanningskabellaag", "e_lv_map_cable"),
    "layer_connection_cables": ("Aansluitkabellaag", "e_lv_connection_cable"),
    "layer_flat_cabinets": ("Flatkastenlaag", "e_lv_multistory_connection"),
    "layer_stations": ("Stationspuntenlaag", "Station locatie"),
    "layer_station_enclosures": ("Stationomtrekkenlaag", "lvm_station_location"),
    "layer_distribution_cabinets": ("Verdeelkastenlaag", "e_lv_distribution_box"),
    # Design-current fields
    "field_passthrough": ("Kolom doorlaatwaarde", "service_connection_type_type"),
    "field_usage": ("Kolom gebruiksdoel", "Gebruiksdoel"),
    "field_gas": ("Kolom gascategorie", "G_Type"),
    "field_building_type": ("Kolom woningtype", "Woningtype"),
    "field_build_year": ("Kolom bouwjaar", "bouwjaar"),
    "field_design_current": ("Kolom ontwerpstroom voor clustering", "Hoogste Trafo"),
    # Network fields
    "field_multistory": ("Kolom multistory-koppeling", "multistory_connection_id"),
    "field_flat_id": ("Kolom flatkast-ID", "id"),
    "field_main_function": ("Function-kolom LS-kabels", "function"),
    "field_connection_function": ("Function-kolom aansluitkabels", "function"),
    "field_station_name": ("Kolom stationsnaam", "Station"),
    "field_station_capacity": ("Kolom trafocapaciteit", "trafo_power"),
    "field_enclosure_station": ("Kolom stationsnaam omtrekken", "Station"),
    "main_function_words": ("Function-woorden LS-kabels", "LS"),
    "connection_function_words": ("Function-woorden aansluitkabels", "LS"),
    "bag_api_url": ("BAG OGC API", "https://api.pdok.nl/kadaster/bag/ogc/v2"),
    "plan_source_crs": ("Bron-CRS plangebied indien onbekend", "EPSG:4326"),
    "opwek_zero_ids": ("Opwek: type-ID's die nul worden", "4, 8, 9"),
    "opwek_zero_text": ("Opwek: woningtypetekst die nul wordt", "appartement"),
}


# The supplied Eea-0205.K workbook is version 3.2. This requested 3.1 profile
# adopts only its new street-furniture values; other category updates are out
# of scope. Household, business, and charging rules stay unchanged.
FRAMEWORK_31_STREET_MATRIX = [
    0, 6, 4.3,
    7, 10, 8.7,
    11, 35, 5.8,
    40, 50, 22,
    63, 80, 36,
]


BOOL_OPTIONS = {
    "auto_cpu_threads": ("CPU-threads automatisch bepalen", True),
    "use_3dbag": ("AHN dakcontrole zelf berekenen (lokaal cachen, zonder 3DBAG)", True),
    "default_apartment": ("Appartement zonder doorlaat: standaardwaarde", True),
    "one_phase_exception": ("1-/2-fase woonhuis: tabelwaarde", True),
    "node_trenches": ("Kabels knippen/noden", True),
    "only_plan": ("Alleen objecten binnen plangebied", True),
    "automatic_stations": ("Aantal nieuwe stations automatisch", True),
    "write_shapefiles": ("Ook losse shapefiles schrijven", False),
}


NUMBER_OPTIONS = {
    "cpu_threads": (
        "Handmatig aantal CPU-threads",
        max(1, min(32, (os.cpu_count() or 4) - 1)),
        1,
        64,
        0,
    ),
    "building_year_limit": ("Grens nieuwbouwjaar", 2022, 1900, 2200, 0),
    "phase_limit": ("Fasegrens woonhuis/zakelijk", 3, 1, 20, 0),
    "amp_limit": ("Ampèregrens woonhuis/zakelijk", 40, 1, 1000, 0),
    "node_tolerance": ("Knooptolerantie (m)", 1.0, 0.0, 25.0, 2),
    "manual_station_count": ("Handmatig aantal nieuwe stations", 0, 0, 100, 0),
    "new_station_kva": ("Vermogen nieuw station (kVA)", 630.0, 1.0, 5000.0, 1),
    "target_utilization": ("Voorkeursbenutting (%)", 90.0, 1.0, 100.0, 1),
    "max_route": ("Maximale kabelroute (m)", 850.0, 1.0, 10000.0, 1),
    "fallback_laad": ("Fallback ontwerpstroom laadpunt (A)", 3.7, 0.0, 10000.0, 2),
}


DESIGN_MATRIX_OPTIONS = {
    "matrix_woonhuis": (
        "Woonhuis oud – trafo",
        ("Type", "A"),
        ["hoekwoning", 5.5, "tussen/geschakeld", 5.5, "twee-onder-een-kap", 6.3,
         "vrijstaand", 7.5, "appartement", 4.5, "onbekend", 5.9],
    ),
    "matrix_woonhuis_2022": (
        "Woonhuis nieuwbouw – trafo",
        ("Type", "A"),
        ["hoekwoning", 5.3, "tussen/geschakeld", 5.3, "twee-onder-een-kap", 5.9,
         "vrijstaand", 7.0, "appartement", 4.2, "onbekend", 5.6],
    ),
    "matrix_woonhuis_kabel": (
        "Woonhuis oud – kabel",
        ("Type", "A"),
        ["hoekwoning", 6.4, "tussen/geschakeld", 6.4, "twee-onder-een-kap", 7.1,
         "vrijstaand", 8.1, "appartement", 5.4, "onbekend", 6.8],
    ),
    "matrix_woonhuis_kabel_2022": (
        "Woonhuis nieuwbouw – kabel",
        ("Type", "A"),
        ["hoekwoning", 6.3, "tussen/geschakeld", 6.3, "twee-onder-een-kap", 6.8,
         "vrijstaand", 7.5, "appartement", 5.1, "onbekend", 6.4],
    ),
    "matrix_woonhuis_opwek": (
        "Opwek woonhuis – trafo",
        ("Type", "A"),
        ["hoekwoning", 5.7, "tussen/geschakeld", 5.7, "twee-onder-een-kap", 6.8,
         "vrijstaand", 8.9, "appartement", 0, "onbekend", 5.7],
    ),
    "matrix_woonhuis_opwek_kabel": (
        "Opwek woonhuis – kabel",
        ("Type", "A"),
        ["hoekwoning", 5.9, "tussen/geschakeld", 5.9, "twee-onder-een-kap", 7.0,
         "vrijstaand", 9.2, "appartement", 0, "onbekend", 5.9],
    ),
    "matrix_amp": (
        "Ampèrestaffel",
        ("Min", "Max", "Vast", "Factor"),
        [0, 34, 8.7, 0, 34, 40, 32, 0, 40, 50, 44, 0, 50, 63, 51, 0,
         63, 80, 65, 0, 80, 100, 85, 0, 100, 125, 106, 0,
         125, 160, 138, 0, 160, 200, 210, 0, 200, 250, 210, 0,
         250, 99999, 0, 0.85],
    ),
    "matrix_type": (
        "Gebruikstypen",
        ("ID", "Naam", "Vast", "Gebruik amp", "Gebruik wonen", "Gebruik straat"),
        [0, "Overig", 0.0, 1, 0, 0, 1, "Woon", 0.0, 1, 1, 0,
         4, "Appartement", 0.0, 1, 1, 0, 8, "Laad", 0.0, 0, 0, 0,
         9, "Straat", 0.0, 0, 0, 1, 10, "Zakelijk", 0.0, 1, 0, 0],
    ),
    "matrix_straat": (
        "Straataansluitingen",
        ("Min A", "Max A", "Ontwerp A"),
        [0, 35, 5.8, 40, 50, 22, 63, 80, 36],
    ),
    "matrix_straat_kader31": (
        "Straatmeubilair – Kader 3.1",
        ("Min A", "Max A", "Ontwerp A"),
        FRAMEWORK_31_STREET_MATRIX,
    ),
    "matrix_laad": (
        "Laadpunten – trafo",
        ("Min A", "Max A", "Ontwerp A"),
        [0, 35, 3.7, 40, 50, 22, 63, 80, 36],
    ),
    "matrix_laad_kabel": (
        "Laadpunten – kabel",
        ("Min A", "Max A", "Ontwerp A"),
        [0, 35, 4.8, 40, 50, 22, 63, 80, 36],
    ),
    "matrix_gas": (
        "Gasadvies – trafo",
        ("Gascategorie", "Max huidig A", "Advies A"),
        ["G10-G25", 34, 50, "G10-G25", 50, 80, "G10-G25", 80, 160,
         "G10-G25", 250, 250, ">G25", 250, 250],
    ),
    "matrix_gas_kabel": (
        "Gasadvies – kabel",
        ("Gascategorie", "Max huidig A", "Advies A"),
        ["G10-G25", 34, 50, "G10-G25", 50, 80, "G10-G25", 80, 80,
         "G10-G25", 9999, 250, ">G25", 80, 80, ">G25", 250, 250],
    ),
    "matrix_regex": (
        "Regexclassificatie",
        ("Patroon", "Type-ID"),
        [r"(^|\W)(riool|fontein|putkast|pompgemaal)", 9,
         r"(^|\W)(ov[\- ]?kast|vri[\- ]?kast|parkeer|slagboom|verkeer|brug|sluis)", 9,
         r"(^|\W)(abri|bushalte|reclame|cai|telecom|telefoon|sirene|camera|flits|bord)", 9,
         r"(^|\W)(verlichting|mast|lantaarn|marktkast|kermis|feest|afval|vuil|container|toilet|urinoir)", 9,
         r"(^|\W)(bouwaansluiting)", 9],
    ),
    "matrix_keywords": (
        "Trefwoordclassificatie",
        ("Trefwoorden (komma's)", "Type-ID"),
        ["appartement, flat, etagewoning, etagebouw, galerijwoning, portiekwoning, maisonnette, wozoco, hoogbouw", 4,
         "ov-kast, ov kast, abri, bushalte, openbare verlichting, straatmeubilair, diversen (niet zijnde gebouwen)", 9,
         "woonhuis, woonfunctie, aansluiting, vrijstaande woning, twee onder een kap, 2-onder-1-kap, eengezinswoning, villa, woonboot, rijtjeswoning, hoekwoning, tussenwoning", 1,
         "oplaadpunt, laadpunt, laadinfrastructuur, elektrisch vervoer,  ev ", 8,
         "bijeenkomstfunctie, kantoor, winkel, school, bedrijf, horeca, kerk, sport, loods, garage", 10],
    ),
}


try:
    CLOSE_BUTTON = QDialogButtonBox.StandardButton.Close
    ACCEPT_ROLE = QDialogButtonBox.ButtonRole.AcceptRole
    WINDOW_MODAL = Qt.WindowModality.WindowModal
except AttributeError:  # QGIS 3 / PyQt5
    CLOSE_BUTTON = QDialogButtonBox.Close
    ACCEPT_ROLE = QDialogButtonBox.AcceptRole
    WINDOW_MODAL = Qt.WindowModal


class InlineProcessingFeedback(QgsProcessingFeedback):
    """Send Processing progress and messages to a page inside the wizard."""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.last_message = "Berekening starten…"

    def _publish(self, message=None):
        if message:
            self.last_message = str(message)
        self.callback(int(round(float(self.progress()))), self.last_message)

    def setProgress(self, progress):
        super().setProgress(progress)
        self._publish()

    def pushInfo(self, info):
        super().pushInfo(info)
        self._publish(info)

    def pushWarning(self, warning):
        super().pushWarning(warning)
        self._publish(f"Waarschuwing: {warning}")

    def reportError(self, error, fatalError=False):
        super().reportError(error, fatalError)
        self._publish(f"Fout: {error}")


class LSNetontwerpDialog(QDialog):
    SETTINGS_PREFIX = "LSNetontwerpWizard/"

    def __init__(self, iface=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.prepared_state = None
        self.setWindowTitle("LS Netontwerp Wizard")
        self.setWindowIcon(
            QIcon(
                str(
                    Path(__file__).resolve().parent
                    / "assets"
                    / "techbase-logo.png"
                )
            )
        )
        self.resize(1120, 700)
        self.settings = QSettings()
        self.widgets = {}
        self._active_feedback = None
        self.setStyleSheet(STYLE)
        self._build_ui()
        self._restore_settings()
        self._restore_prepared_state()
        apply_theme(self)
        install_dialog_theme(self)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.page_stack = QStackedWidget()
        outer.addWidget(self.page_stack)
        self.main_page = QWidget()
        root = QVBoxLayout(self.main_page)
        root.setContentsMargins(20, 14, 20, 16)
        root.setSpacing(10)
        header_widget = QWidget()
        header_widget.setFixedHeight(84)
        header = QHBoxLayout(header_widget)
        header.setContentsMargins(0, 0, 0, 0)
        logo = QLabel()
        pixmap = QPixmap(
            str(Path(__file__).resolve().parent / "assets" / "techbase-logo.png")
        )
        try:
            keep_aspect = Qt.AspectRatioMode.KeepAspectRatio
            smooth = Qt.TransformationMode.SmoothTransformation
        except AttributeError:
            keep_aspect = Qt.KeepAspectRatio
            smooth = Qt.SmoothTransformation
        if not pixmap.isNull():
            logo.setPixmap(pixmap.scaled(68, 68, keep_aspect, smooth))
        logo.setFixedSize(76, 76)
        title_box = QVBoxLayout()
        title = QLabel("LS Netontwerp Wizard")
        title.setObjectName("techbaseTitle")
        subtitle = QLabel("TechBase • van GEN-data naar controleerbaar laagspanningsontwerp")
        subtitle.setObjectName("techbaseSubtitle")
        title_box.addStretch(1)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        title_box.addStretch(1)
        header.addWidget(logo)
        header.addLayout(title_box, 1)
        self.info_button = QPushButton("Informatie over GEN-invoer")
        self.info_button.setObjectName("genInfoButton")
        self.info_button.setToolTip(
            "Uitleg over trail, GEN-query en het exporteren naar XML en Excel"
        )
        self.info_button.clicked.connect(self._show_gen_information)
        header.addWidget(self.info_button)
        root.addWidget(header_widget)
        self.header_widget = header_widget
        intro = QLabel(
            "Van GEN XML + Excel via BAG-woningtypen en ontwerpstroom naar "
            "kabelverbonden stationsclusters. In de standaardmodus zijn de "
            "bekende lagen en kolommen al ingevuld."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)
        self.intro_label = intro

        basic = QGroupBox("Benodigde invoer")
        input_layout = QGridLayout(basic)
        input_layout.setHorizontalSpacing(18)
        form = QFormLayout()
        right_form = QFormLayout()
        input_layout.addLayout(form, 0, 0)
        input_layout.addLayout(right_form, 0, 1)
        input_layout.setColumnStretch(0, 1)
        input_layout.setColumnStretch(1, 1)
        form.setSpacing(9)
        right_form.setSpacing(9)
        self.xml_edit = self._path_row(form, "GEN XML", "xml")
        self.excel_edit = self._path_row(right_form, "Kabelgegevens Excel", "excel")
        self.plan_edit = self._path_row(form, "Plangebied (optioneel)", "plan")
        self.no_plan = QCheckBox("Zonder plangebied werken")
        self.no_plan.setToolTip(
            "Gebruik de omvang van de geïmporteerde LS-aansluitingen voor de BAG-opvraag. "
            "De clustering wordt niet op een plangebied begrensd."
        )
        self.no_plan.toggled.connect(self._toggle_plan)
        form.addRow("", self.no_plan)
        self.output_edit = self._path_row(right_form, "Uitvoermap", "output")
        self.framework_combo = QComboBox()
        self.framework_combo.addItem("Kader 3.0 (huidige methode)", "3.0")
        self.framework_combo.addItem(
            "Kader 3.1 (nieuwe straatmeubilairwaarden)", "3.1"
        )
        self.framework_combo.setToolTip(
            "Kader 3.1 wijzigt alleen de straatmeubilairstaffel. De overige "
            "ontwerpstroomregels blijven gelijk aan de huidige pluginmethode."
        )
        right_form.addRow("Ontwerpstroomkader", self.framework_combo)
        root.addWidget(basic)
        self.basic_group = basic

        option_row = QHBoxLayout()
        self.advanced_toggle = QCheckBox("Advanced")
        self.advanced_toggle.setToolTip(
            "Toon alle laag-, kolom- en rekeninstellingen"
        )
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        self.open_project = QCheckBox("QGIS-project na afloop openen")
        self.open_project.setChecked(True)
        option_row.addWidget(self.advanced_toggle)
        option_row.addStretch(1)
        option_row.addWidget(self.open_project)
        root.addLayout(option_row)
        self.advanced_hint = QLabel(
            "Geavanceerde instellingen · schakel Geavanceerde opties uit om de ontwerpstappen te starten."
        )
        self.advanced_hint.setVisible(False)
        root.addWidget(self.advanced_hint)

        self.advanced_container = self._build_advanced()
        self.advanced_container.setVisible(False)
        root.addWidget(self.advanced_container, 1)

        self.progress_group = QGroupBox("Voortgang")
        progress_layout = QVBoxLayout(self.progress_group)
        progress_top = QHBoxLayout()
        self.progress_summary = QLabel("Gereed om te starten")
        self.progress_summary.setWordWrap(False)
        self.progress_summary.setToolTip("")
        self.progress_cancel_button = QPushButton("Annuleren")
        self.progress_cancel_button.clicked.connect(self._cancel_progress)
        progress_top.addWidget(self.progress_summary, 1)
        progress_top.addWidget(self.progress_cancel_button)
        progress_layout.addLayout(progress_top)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)
        self.progress_details_toggle = QCheckBox("Details tonen")
        self.progress_details = QPlainTextEdit()
        self.progress_details.setReadOnly(True)
        self.progress_details.setMaximumHeight(140)
        self.progress_details.setVisible(False)
        self.progress_details_toggle.toggled.connect(
            self.progress_details.setVisible
        )
        progress_layout.addWidget(self.progress_details_toggle)
        progress_layout.addWidget(self.progress_details)
        self.progress_group.setVisible(False)
        root.addWidget(self.progress_group)

        self.status_label = QLabel(
            "Stap 1: maak invoer, werkproject en ontwerpstroomcontrolelaag."
        )
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        actions = QGroupBox("Stappen in het ontwerp")
        action_grid = QGridLayout(actions)
        action_grid.setHorizontalSpacing(8)
        action_grid.setVerticalSpacing(8)
        self.run_button = QPushButton("1.1. Ontwerpstroom maken")
        self.run_button.setToolTip(
            "Maak het werkproject, importeer de invoer en bereken de ontwerpstroom"
        )
        self.run_button.clicked.connect(self.run_preparation)
        self.edit_values_button = QPushButton("2a. Stroom aanpassen")
        self.edit_values_button.setToolTip(
            "Kies huishoudelijk, zakelijk, laadpunt of straatmeubilair en pas "
            "verbruik en opwek aan"
        )
        self.edit_values_button.setEnabled(False)
        self.edit_values_button.clicked.connect(self.open_value_editor)
        self.edit_housing_button = QPushButton("2b. Woningtype aanpassen")
        self.edit_housing_button.setToolTip(
            "Wijzig geselecteerde BAG-woningen en bereken de aansluitingen opnieuw"
        )
        self.edit_housing_button.setEnabled(False)
        self.edit_housing_button.clicked.connect(self.open_housing_editor)
        self.edit_stations_button = QPushButton("2c. Stations aanpassen")
        self.edit_stations_button.setToolTip(
            "Wijzig de trafocapaciteit of verwijder geselecteerde bestaande stations"
        )
        self.edit_stations_button.setEnabled(False)
        self.edit_stations_button.clicked.connect(self.open_station_editor)
        self.edit_zero_current_button = QPushButton("2d. Nulwaarden herstellen (0)")
        self.edit_zero_current_button.setToolTip(
            "Bekijk aansluitingen met een ontbrekende of nulwaarde voor Hoogste Trafo, "
            "zoom naar de kaart en wijs een categorie en ontwerpstroom toe"
        )
        self.edit_zero_current_button.setObjectName("secondaryButton")
        self.edit_zero_current_button.setEnabled(False)
        self.edit_zero_current_button.clicked.connect(self.show_zero_current_page)
        self.station_names_button = QPushButton("1.2. Stationskoppeling")
        self.station_names_button.setToolTip(
            "Koppel LOVION-stationsnummers en kleur de aansluitingen per station"
        )
        self.station_names_button.setObjectName("secondaryButton")
        self.station_names_button.setEnabled(False)
        self.station_names_button.clicked.connect(self.show_station_link_page)
        self.new_buildings_button = QPushButton("1.3. Nieuwbouw")
        self.new_buildings_button.setObjectName("secondaryButton")
        self.new_buildings_button.setEnabled(False)
        self.new_buildings_button.clicked.connect(self.show_connection_sources_page)
        self.cluster_button = QPushButton("3. Clustering maken")
        self.cluster_button.setToolTip(
            "Maak de kabelverbonden clustering met de gecontroleerde waarden"
        )
        self.cluster_button.setEnabled(False)
        self.cluster_button.clicked.connect(self.open_clustering_options)
        self.edit_cluster_button = QPushButton("4. Clustering aanpassen")
        self.edit_cluster_button.setToolTip(
            "Verplaats geselecteerde aansluitingen naar het geselecteerde station "
            "en werk gebieden en statistieken bij"
        )
        self.edit_cluster_button.clicked.connect(self.open_cluster_editor)
        self.free_cluster_button = QPushButton("4b. Vrij aanpassen")
        self.free_cluster_button.setToolTip(
            "Open clustercorrectie met alle vier veiligheidscontroles uitgeschakeld"
        )
        self.free_cluster_button.clicked.connect(self.open_free_cluster_editor)
        # Vrij aanpassen is voortaan onderdeel van Advanced op de eigen
        # correctiepagina. Houd het object voor compatibiliteit met bestaande
        # projecten/tests, maar voorkom twee concurrerende ingangen in de UI.
        self.free_cluster_button.setVisible(False)
        self.network_button = QPushButton("5. Sleuven/routes")
        self.network_button.setToolTip(
            "Teken een nieuwe sleuf, node het kabelnet en ververs kortste clusterroutes"
        )
        self.network_button.clicked.connect(self.show_network_page)
        self.areas_button = QPushButton("6. Mooie clustergebieden")
        self.areas_button.setToolTip(
            "Maak topologisch vereenvoudigde gebieden en verleg daarna eenvoudig "
            "de grens tussen twee geselecteerde buurclusters"
        )
        self.areas_button.clicked.connect(self.show_areas_page)
        for button in (
            self.edit_values_button, self.edit_housing_button,
            self.edit_stations_button, self.edit_cluster_button,
            self.edit_zero_current_button, self.station_names_button,
            self.network_button, self.areas_button,
        ):
            button.setObjectName("secondaryButton")
        action_grid.addWidget(self.run_button, 0, 0)
        action_grid.addWidget(self.edit_values_button, 0, 1)
        action_grid.addWidget(self.edit_housing_button, 0, 2)
        action_grid.addWidget(self.edit_stations_button, 0, 3)
        action_grid.addWidget(self.cluster_button, 1, 0)
        action_grid.addWidget(self.edit_cluster_button, 1, 1)
        action_grid.addWidget(self.network_button, 1, 2)
        action_grid.addWidget(self.areas_button, 1, 3)
        action_grid.addWidget(self.edit_zero_current_button, 2, 0, 1, 4)
        action_grid.addWidget(self.station_names_button, 3, 0, 1, 2)
        action_grid.addWidget(self.new_buildings_button, 3, 2, 1, 2)
        root.addWidget(actions)
        self.actions_group = actions
        close_button = QPushButton("Sluiten")
        close_button.setObjectName("secondaryButton")
        close_button.clicked.connect(self.close)
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_row.addWidget(close_button)
        root.addLayout(close_row)
        self.page_stack.addWidget(self.main_page)
        self.manual_page = self._build_manual_page()
        self.page_stack.addWidget(self.manual_page)
        self.value_page = self._build_value_page()
        self.page_stack.addWidget(self.value_page)
        self.housing_page = self._build_housing_page()
        self.page_stack.addWidget(self.housing_page)
        self.station_page = self._build_station_page()
        self.page_stack.addWidget(self.station_page)
        self.network_page = self._build_network_page()
        self.page_stack.addWidget(self.network_page)
        self.areas_page = self._build_areas_page()
        self.page_stack.addWidget(self.areas_page)
        self.zero_current_page = ZeroCurrentPage(self)
        self.page_stack.addWidget(self.zero_current_page)
        from .connection_sources_page import ConnectionSourcesPage
        self.connection_sources_page = ConnectionSourcesPage(self, "newbouw")
        self.page_stack.addWidget(self.connection_sources_page)
        self.station_link_page = ConnectionSourcesPage(self, "stations")
        self.page_stack.addWidget(self.station_link_page)
        self.page_stack.setCurrentWidget(self.main_page)

    def _build_manual_page(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(10, 8, 10, 8)

        header_widget = QWidget()
        header_widget.setFixedHeight(84)
        header = QHBoxLayout(header_widget)
        header.setContentsMargins(0, 0, 0, 0)
        logo = QLabel()
        pixmap = QPixmap(
            str(Path(__file__).resolve().parent / "assets" / "techbase-logo.png")
        )
        try:
            keep_aspect = Qt.AspectRatioMode.KeepAspectRatio
            smooth = Qt.TransformationMode.SmoothTransformation
        except AttributeError:
            keep_aspect = Qt.KeepAspectRatio
            smooth = Qt.SmoothTransformation
        if not pixmap.isNull():
            logo.setPixmap(pixmap.scaled(68, 68, keep_aspect, smooth))
        logo.setFixedSize(76, 76)
        title_box = QVBoxLayout()
        title = QLabel("Handmatige clustercorrectie")
        title.setObjectName("techbaseTitle")
        subtitle = QLabel(
            "TechBase • aansluitingen verplaatsen en alle clusterlagen bijwerken"
        )
        subtitle.setObjectName("techbaseSubtitle")
        title_box.addStretch(1)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        title_box.addStretch(1)
        header.addWidget(logo)
        header.addLayout(title_box, 1)
        self.manual_home_button = QPushButton("←  Home")
        self.manual_home_button.setObjectName("genInfoButton")
        self.manual_home_button.clicked.connect(self.show_home_page)
        header.addWidget(self.manual_home_button)
        root.addWidget(header_widget)

        explanation = QLabel(
            "Selecteer in de kaart een of meer punten uit <b>Aansluitingen "
            "geclusterd</b> en precies één punt uit <b>Stations ontwerp</b>. "
            "De normale modus bewaakt capaciteit, kabellengte en geldige "
            "kabelroutes. Open Geavanceerde opties om alle invoerlagen en controles aan te passen."
        )
        explanation.setWordWrap(True)
        root.addWidget(explanation)

        selection_group = QGroupBox("Kaartselectie")
        selection_layout = QHBoxLayout(selection_group)
        self.manual_selection_label = QLabel("Selectie nog niet gecontroleerd")
        self.manual_selection_label.setWordWrap(True)
        refresh_button = QPushButton("Selectie vernieuwen")
        refresh_button.clicked.connect(self._refresh_manual_selection_status)
        selection_layout.addWidget(self.manual_selection_label, 1)
        selection_layout.addWidget(refresh_button)
        root.addWidget(selection_group)

        normal_group = QGroupBox("Normale modus")
        normal_layout = QVBoxLayout(normal_group)
        self.manual_remove_cluster = QCheckBox(
            "Hele broncluster samenvoegen en verwijderen"
        )
        self.manual_remove_cluster.setToolTip(
            "Eén geselecteerde aansluiting bepaalt de broncluster; alle "
            "aansluitingen daarvan worden naar het doelstation verplaatst."
        )
        normal_layout.addWidget(self.manual_remove_cluster)
        root.addWidget(normal_group)

        self.manual_advanced_toggle = QCheckBox("Advanced")
        self.manual_advanced_toggle.setToolTip(
            "Toon alle lagen, veiligheidscontroles en rekeninstellingen"
        )
        self.manual_advanced_toggle.toggled.connect(
            self._toggle_manual_advanced
        )
        root.addWidget(self.manual_advanced_toggle)

        advanced_scroll = QScrollArea()
        advanced_scroll.setWidgetResizable(True)
        advanced_content = QWidget()
        advanced_layout = QVBoxLayout(advanced_content)

        layers_group = QGroupBox("Resultaatlagen")
        layers_form = QFormLayout(layers_group)
        self.manual_layer_combos = {}
        for key, label in (
            ("AANSLUITINGEN", "Aansluitingen geclusterd"),
            ("STATIONS", "Stations ontwerp"),
            ("GEBIEDEN", "Clustergebieden"),
            ("KABELROUTES", "Kabelroutes per cluster"),
            ("SLEUVEN", "Sleuven geknipt/genood"),
            ("PLANGEBIED", "Plangebied (optioneel)"),
        ):
            combo = QComboBox()
            self.manual_layer_combos[key] = combo
            layers_form.addRow(label, combo)
        refresh_layers = QPushButton("Lagen opnieuw automatisch kiezen")
        refresh_layers.clicked.connect(self._refresh_manual_layer_choices)
        layers_form.addRow("", refresh_layers)
        advanced_layout.addWidget(layers_group)

        safety_group = QGroupBox("Veiligheidscontroles")
        safety_form = QFormLayout(safety_group)
        self.manual_allow_all = QCheckBox(
            "ALLES TOESTAAN (alle vier controles uitschakelen)"
        )
        self.manual_allow_all.setStyleSheet(
            "QCheckBox { color: #b54800; font-weight: 700; }"
        )
        safety_form.addRow(self.manual_allow_all)
        self.manual_safety_checks = {}
        for key, label in (
            ("CONTROLE_MAX_ONTWERPSTROOM", "Maximale ontwerpstroom bewaken"),
            ("CONTROLE_MAX_KABELLENGTE", "Maximale kabellengte bewaken"),
            ("CONTROLE_ROUTES_ANDERE_CLUSTERS", "Routes door andere clusters blokkeren"),
            (
                "CONTROLE_GEDEELDE_ROUTES_VERTAKKINGEN",
                "Gedeelde routes en onvolledige vertakkingen blokkeren",
            ),
        ):
            checkbox = QCheckBox()
            checkbox.setChecked(True)
            self.manual_safety_checks[key] = checkbox
            safety_form.addRow(label, checkbox)
        self.manual_allow_all.toggled.connect(
            lambda enabled: [
                checkbox.setEnabled(not enabled)
                for checkbox in self.manual_safety_checks.values()
            ]
        )
        advanced_layout.addWidget(safety_group)

        calculation_group = QGroupBox("Rekeninstellingen en herstelbestanden")
        calculation_form = QFormLayout(calculation_group)
        self.manual_max_route = QDoubleSpinBox()
        self.manual_max_route.setRange(1.0, 10000.0)
        self.manual_max_route.setDecimals(1)
        self.manual_max_route.setValue(850.0)
        self.manual_node_tolerance = QDoubleSpinBox()
        self.manual_node_tolerance.setRange(0.0, 25.0)
        self.manual_node_tolerance.setDecimals(2)
        self.manual_node_tolerance.setValue(0.0)
        calculation_form.addRow("Maximale kabelroute (m)", self.manual_max_route)
        calculation_form.addRow("Knooptolerantie (m)", self.manual_node_tolerance)
        backup_row = QHBoxLayout()
        self.manual_backup_edit = QLineEdit()
        backup_button = QPushButton("Kiezen…")
        backup_button.clicked.connect(self._browse_manual_backup_folder)
        backup_row.addWidget(self.manual_backup_edit, 1)
        backup_row.addWidget(backup_button)
        calculation_form.addRow("Map voor back-up en resultaatkopie", backup_row)
        advanced_layout.addWidget(calculation_group)
        advanced_layout.addStretch(1)
        advanced_scroll.setWidget(advanced_content)
        advanced_scroll.setVisible(False)
        self.manual_advanced_container = advanced_scroll
        root.addWidget(advanced_scroll, 1)

        self.manual_progress_group = QGroupBox("Voortgang")
        progress_layout = QVBoxLayout(self.manual_progress_group)
        progress_row = QHBoxLayout()
        self.manual_progress_summary = QLabel("Gereed voor een correctie")
        self.manual_progress_summary.setWordWrap(False)
        self.manual_cancel_button = QPushButton("Annuleren")
        self.manual_cancel_button.clicked.connect(self._cancel_manual_progress)
        progress_row.addWidget(self.manual_progress_summary, 1)
        progress_row.addWidget(self.manual_cancel_button)
        progress_layout.addLayout(progress_row)
        self.manual_progress_bar = QProgressBar()
        self.manual_progress_bar.setRange(0, 100)
        progress_layout.addWidget(self.manual_progress_bar)
        self.manual_progress_details = QPlainTextEdit()
        self.manual_progress_details.setReadOnly(True)
        self.manual_progress_details.setMaximumHeight(120)
        progress_layout.addWidget(self.manual_progress_details)
        self.manual_progress_group.setVisible(False)
        root.addWidget(self.manual_progress_group)

        self.manual_status_label = QLabel(
            "Maak de selecties in de kaart en klik daarna op Correctie uitvoeren."
        )
        self.manual_status_label.setWordWrap(True)
        root.addWidget(self.manual_status_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.manual_run_button = QPushButton("Correctie uitvoeren")
        self.manual_run_button.clicked.connect(self.run_manual_correction)
        close_button = QPushButton("Sluiten")
        close_button.clicked.connect(self.close)
        buttons.addWidget(self.manual_run_button)
        buttons.addWidget(close_button)
        root.addLayout(buttons)
        return page

    def show_home_page(self):
        self.page_stack.setCurrentWidget(self.main_page)
        self.setWindowTitle("LS Netontwerp Wizard")
        if self.advanced_toggle.isChecked():
            self.resize(max(self.width(), 1120), max(self.height(), 900))
        else:
            self.resize(1120, 640)

    def _build_network_page(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(10, 8, 10, 8)
        self.network_home_button = self._add_subpage_header(
            root,
            "Sleuven en clusterroutes",
            "TechBase • netwerk tekenen, knippen/noden en kortste routes verversen",
        )
        explanation = QLabel(
            "Met <b>Nieuwe sleuf tekenen</b> teken je rechtstreeks in de kaart. "
            "Na de rechter muisknop wordt de lijn blijvend toegevoegd en worden "
            "alle kruisingen en T-aansluitingen automatisch geknipt/genood. Met "
            "<b>Alle clusterroutes verversen</b> blijven de stations per aansluiting "
            "gelijk, maar worden alle kortste exclusieve routes, gebieden en "
            "routestatistieken opnieuw berekend."
        )
        explanation.setWordWrap(True)
        root.addWidget(explanation)

        self.network_advanced_toggle = QCheckBox("Advanced")
        self.network_advanced_toggle.toggled.connect(
            lambda enabled: self.network_advanced_container.setVisible(enabled)
        )
        root.addWidget(self.network_advanced_toggle)

        advanced = QGroupBox("Netwerklagen en controles")
        advanced_form = QFormLayout(advanced)
        self.network_layer_combos = {}
        for key, label in (
            ("AANSLUITINGEN", "Aansluitingen"),
            ("STATIONS", "Stations"),
            ("GEBIEDEN", "Clustergebieden"),
            ("KABELROUTES", "Kabelroutes"),
            ("SLEUVEN", "Sleuven geknipt/genood"),
            ("PLANGEBIED", "Plangebied"),
        ):
            combo = QComboBox()
            self.network_layer_combos[key] = combo
            advanced_form.addRow(label, combo)
        self.network_node_tolerance = QDoubleSpinBox()
        self.network_node_tolerance.setRange(0.0, 25.0)
        self.network_node_tolerance.setDecimals(2)
        self.network_node_tolerance.setValue(1.0)
        advanced_form.addRow("T-aansluitingstolerantie (m)", self.network_node_tolerance)
        self.network_max_route = QDoubleSpinBox()
        self.network_max_route.setRange(1.0, 10000.0)
        self.network_max_route.setDecimals(1)
        self.network_max_route.setValue(850.0)
        advanced_form.addRow("Maximale route bij verversen (m)", self.network_max_route)
        self.network_check_max_route = QCheckBox("Maximale routelengte bewaken")
        self.network_check_max_route.setChecked(True)
        self.network_block_other_routes = QCheckBox(
            "Bestaande routes van andere clusters blokkeren"
        )
        self.network_block_other_routes.setChecked(True)
        self.network_check_shared = QCheckBox(
            "Gedeelde routes en onvolledige vertakkingen blokkeren"
        )
        self.network_check_shared.setChecked(True)
        advanced_form.addRow(self.network_check_max_route)
        advanced_form.addRow(self.network_block_other_routes)
        advanced_form.addRow(self.network_check_shared)
        backup_row = QHBoxLayout()
        self.network_backup_edit = QLineEdit()
        backup_button = QPushButton("Kiezen…")
        backup_button.clicked.connect(self._browse_network_backup_folder)
        backup_row.addWidget(self.network_backup_edit, 1)
        backup_row.addWidget(backup_button)
        advanced_form.addRow("Back-upmap", backup_row)
        refresh_layers = QPushButton("Lagen opnieuw zoeken")
        refresh_layers.clicked.connect(self._refresh_network_layer_choices)
        advanced_form.addRow(refresh_layers)
        self.network_advanced_container = advanced
        self.network_advanced_container.setVisible(False)
        root.addWidget(self.network_advanced_container)

        self.network_progress_group = QGroupBox("Voortgang")
        progress_layout = QVBoxLayout(self.network_progress_group)
        self.network_progress_summary = QLabel("Gereed")
        self.network_progress_bar = QProgressBar()
        self.network_progress_bar.setRange(0, 100)
        self.network_progress_details = QPlainTextEdit()
        self.network_progress_details.setReadOnly(True)
        self.network_progress_details.setMaximumHeight(120)
        progress_layout.addWidget(self.network_progress_summary)
        progress_layout.addWidget(self.network_progress_bar)
        progress_layout.addWidget(self.network_progress_details)
        self.network_progress_group.setVisible(False)
        root.addWidget(self.network_progress_group)

        self.network_status_label = QLabel(
            "Gereed om een sleuf te tekenen of de routes te verversen."
        )
        self.network_status_label.setWordWrap(True)
        root.addWidget(self.network_status_label)
        root.addStretch(1)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.network_draw_button = QPushButton("Nieuwe sleuf tekenen")
        self.network_draw_button.clicked.connect(self.start_new_trench_drawing)
        self.network_refresh_button = QPushButton("Alle clusterroutes verversen")
        self.network_refresh_button.setToolTip(
            "Bouw alle clusterpaden opnieuw als kortste exclusieve kabelroutes op"
        )
        self.network_refresh_button.clicked.connect(
            lambda: self.run_route_refresh(False)
        )
        self.network_selected_refresh_button = QPushButton(
            "Geselecteerde routes verversen"
        )
        self.network_selected_refresh_button.setToolTip(
            "Selecteer eerst kabelroutes of stations in de kaart; alleen die clusters worden vernieuwd"
        )
        self.network_selected_refresh_button.clicked.connect(
            lambda: self.run_route_refresh(True)
        )
        close_button = QPushButton("Sluiten")
        close_button.clicked.connect(self.close)
        button_row.addWidget(self.network_draw_button)
        button_row.addWidget(self.network_selected_refresh_button)
        button_row.addWidget(self.network_refresh_button)
        button_row.addWidget(close_button)
        root.addLayout(button_row)
        self._network_draw_layer = None
        self._network_draw_processing = False
        return page

    def show_network_page(self):
        self._refresh_network_layer_choices()
        self.page_stack.setCurrentWidget(self.network_page)
        self.setWindowTitle("LS Netontwerp Wizard – sleuven en routes")
        self.resize(1120, 700 if not self.network_advanced_toggle.isChecked() else 820)

    def _build_areas_page(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(10, 8, 10, 8)
        self.areas_home_button = self._add_subpage_header(
            root,
            "Mooie en eenvoudig aanpasbare clustergebieden",
            "TechBase • topologische vereenvoudiging en gezamenlijke grenzen verleggen",
        )
        explanation = QLabel(
            "Maak eerst een nette versie met zo weinig mogelijk hoekpunten. De "
            "gedeelde grenzen blijven sluitend en iedere aansluiting blijft in "
            "zijn eigen cluster. Smalle lege uitlopers worden verwijderd zodat "
            "compacte rechthoekige blokgebieden zonder panhandles ontstaan. Voor "
            "lange grenzen mogen daarna recht schuin lopen als dat veel hoekpunten "
            "bespaart; samenkomstpunten blijven exact gesloten. Voor een handmatige "
            "wijziging selecteer je daarna "
            "precies twee aangrenzende gebieden en teken je hun nieuwe grens."
        )
        explanation.setWordWrap(True)
        root.addWidget(explanation)

        self.areas_selection_label = QLabel("Nog geen gebiedenlaag gekozen.")
        self.areas_selection_label.setStyleSheet("color: #b54800; font-weight: 700;")
        root.addWidget(self.areas_selection_label)

        self.areas_advanced_toggle = QCheckBox("Advanced")
        self.areas_advanced_toggle.toggled.connect(
            lambda enabled: self.areas_advanced_container.setVisible(enabled)
        )
        root.addWidget(self.areas_advanced_toggle)
        advanced = QGroupBox("Gebiedenlagen en vereenvoudiging")
        form = QFormLayout(advanced)
        self.areas_layer_combo = QComboBox()
        self.areas_connection_combo = QComboBox()
        self.areas_layer_combo.currentIndexChanged.connect(
            self._areas_layer_choice_changed
        )
        form.addRow("Clustergebieden", self.areas_layer_combo)
        form.addRow("Aansluitingen", self.areas_connection_combo)
        self.areas_cluster_field = QLineEdit("Cluster")
        self.areas_connection_cluster_field = QLineEdit("Cluster")
        form.addRow("Clusterkolom gebieden", self.areas_cluster_field)
        form.addRow("Clusterkolom aansluitingen", self.areas_connection_cluster_field)
        self.areas_tolerance = QDoubleSpinBox()
        self.areas_tolerance.setRange(0.01, 250.0)
        self.areas_tolerance.setDecimals(2)
        self.areas_tolerance.setValue(12.0)
        self.areas_tolerance.setSuffix(" m")
        form.addRow("Maximale vereenvoudiging", self.areas_tolerance)
        self.areas_right_angles = QCheckBox(
            "Interne grenzen horizontaal/verticaal met 90°-hoeken"
        )
        self.areas_right_angles.setChecked(True)
        form.addRow(self.areas_right_angles)
        self.areas_min_width = QDoubleSpinBox()
        self.areas_min_width.setRange(0.0, 100.0)
        self.areas_min_width.setDecimals(1)
        self.areas_min_width.setValue(20.0)
        self.areas_min_width.setSuffix(" m")
        self.areas_min_width.setToolTip(
            "Smalle gebiedshalzen en lege uitlopers onder deze breedte worden "
            "opgenomen in het aangrenzende compacte gebied"
        )
        form.addRow("Minimale blok-/halsbreedte", self.areas_min_width)
        self.areas_junction_tolerance = QDoubleSpinBox()
        self.areas_junction_tolerance.setRange(0.0, 50.0)
        self.areas_junction_tolerance.setDecimals(1)
        self.areas_junction_tolerance.setValue(12.0)
        self.areas_junction_tolerance.setSuffix(" m")
        self.areas_junction_tolerance.setToolTip(
            "Vereenvoudig alle gedeelde grenzen als één topologische dekking; "
            "schuine rechte lijnen zijn toegestaan en 3+-clusterpunten blijven exact gelijk"
        )
        form.addRow("Schuine grensvereenvoudiging", self.areas_junction_tolerance)
        refresh = QPushButton("Lagen opnieuw zoeken")
        refresh.clicked.connect(self._refresh_areas_layer_choices)
        form.addRow(refresh)
        self.areas_advanced_container = advanced
        self.areas_advanced_container.setVisible(False)
        root.addWidget(advanced)

        self.areas_progress_group = QGroupBox("Voortgang")
        progress_layout = QVBoxLayout(self.areas_progress_group)
        self.areas_progress_summary = QLabel("Gereed")
        self.areas_progress_bar = QProgressBar()
        self.areas_progress_bar.setRange(0, 100)
        self.areas_progress_details = QPlainTextEdit()
        self.areas_progress_details.setReadOnly(True)
        self.areas_progress_details.setMaximumHeight(110)
        progress_layout.addWidget(self.areas_progress_summary)
        progress_layout.addWidget(self.areas_progress_bar)
        progress_layout.addWidget(self.areas_progress_details)
        self.areas_progress_group.setVisible(False)
        root.addWidget(self.areas_progress_group)

        self.areas_status_label = QLabel(
            "Maak de vereenvoudigde laag of selecteer twee buurgebieden om hun grens te verleggen."
        )
        self.areas_status_label.setWordWrap(True)
        root.addWidget(self.areas_status_label)
        root.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.areas_create_button = QPushButton("Vereenvoudigde gebieden maken")
        self.areas_create_button.clicked.connect(self.run_area_simplification)
        self.areas_draw_button = QPushButton("Grens van 2 gebieden verleggen")
        self.areas_draw_button.clicked.connect(self.start_area_boundary_drawing)
        close_button = QPushButton("Sluiten")
        close_button.clicked.connect(self.close)
        buttons.addWidget(self.areas_create_button)
        buttons.addWidget(self.areas_draw_button)
        buttons.addWidget(close_button)
        root.addLayout(buttons)
        self._area_draw_layer = None
        self._area_draw_processing = False
        self._area_selected_ids = []
        return page

    def show_areas_page(self):
        self._refresh_areas_layer_choices()
        self.page_stack.setCurrentWidget(self.areas_page)
        self.setWindowTitle("LS Netontwerp Wizard – mooie clustergebieden")
        self.resize(1120, 650 if not self.areas_advanced_toggle.isChecked() else 790)

    def _areas_selected_layer(self, connections=False):
        combo = self.areas_connection_combo if connections else self.areas_layer_combo
        layer_id = combo.currentData()
        return QgsProject.instance().mapLayer(layer_id) if layer_id else None

    def _refresh_areas_layer_choices(self):
        project = QgsProject.instance()
        layers = list(project.layerTreeRoot().layerOrder()) or list(project.mapLayers().values())
        polygon_layers = [
            layer for layer in layers
            if isinstance(layer, QgsVectorLayer)
            and QgsWkbTypes.geometryType(layer.wkbType()) == QgsWkbTypes.PolygonGeometry
        ]
        point_layers = [
            layer for layer in layers
            if isinstance(layer, QgsVectorLayer)
            and QgsWkbTypes.geometryType(layer.wkbType()) == QgsWkbTypes.PointGeometry
        ]
        previous_area = self.areas_layer_combo.currentData()
        previous_points = self.areas_connection_combo.currentData()
        self.areas_layer_combo.clear()
        self.areas_connection_combo.clear()
        for layer in polygon_layers:
            self.areas_layer_combo.addItem(layer.name(), layer.id())
        for layer in point_layers:
            self.areas_connection_combo.addItem(layer.name(), layer.id())
        preferred_area = next(
            (layer.id() for layer in polygon_layers if layer.name() == "Clustergebieden vereenvoudigd"),
            None,
        ) or next(
            (layer.id() for layer in polygon_layers if layer.name() == "Clustergebieden"),
            previous_area,
        )
        preferred_points = next(
            (layer.id() for layer in point_layers if layer.name() == "Aansluitingen geclusterd"),
            previous_points,
        )
        for combo, value in (
            (self.areas_layer_combo, preferred_area),
            (self.areas_connection_combo, preferred_points),
        ):
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)
        self._areas_layer_choice_changed()

    def _areas_layer_choice_changed(self):
        selected_layer = self._areas_selected_layer()
        previous_layer = getattr(self, "_areas_selection_layer", None)
        if previous_layer is not None and previous_layer is not selected_layer:
            try:
                previous_layer.selectionChanged.disconnect(
                    self._refresh_areas_selection_status
                )
            except (TypeError, RuntimeError):
                pass
        if selected_layer is not None and previous_layer is not selected_layer:
            selected_layer.selectionChanged.connect(self._refresh_areas_selection_status)
        self._areas_selection_layer = selected_layer
        self._refresh_areas_selection_status()

    def _refresh_areas_selection_status(self):
        layer = self._areas_selected_layer()
        count = len(layer.selectedFeatureIds()) if layer is not None else 0
        valid = count == 2
        self.areas_selection_label.setStyleSheet(
            f"color: {'#2e7d32' if valid else '#b54800'}; font-weight: 700;"
        )
        self.areas_selection_label.setText(
            f"Geselecteerde aangrenzende gebieden: {count} (nodig: precies 2)"
        )

    def _areas_progress_update(self, percent, message):
        text = str(message).strip()
        self.areas_progress_bar.setValue(max(0, min(100, int(percent))))
        self.areas_progress_summary.setText(self._short_progress_message(text))
        self.areas_progress_summary.setToolTip(text)
        self._append_unique_progress(self.areas_progress_details, text)
        QApplication.processEvents()

    def _set_areas_status(self, message, error=False):
        self._set_page_status(self.areas_status_label, message, error)

    @staticmethod
    def _persistent_layer_path(layer):
        source = str(layer.source()).split("|", 1)[0]
        path = Path(source)
        return path if path.suffix.lower() in (".gpkg", ".shp") else None

    def run_area_simplification(self):
        areas = self._areas_selected_layer()
        connections = self._areas_selected_layer(True)
        if areas is None or connections is None:
            self._set_areas_status("Kies een geldige gebieden- en aansluitingenlaag.", True)
            return
        source_path = self._persistent_layer_path(areas)
        base_folder = source_path.parent if source_path else Path(QgsProject.instance().homePath())
        if not str(base_folder):
            self._set_areas_status("Het project heeft nog geen geldige opslagmap.", True)
            return
        output_path = base_folder / "clustergebieden_vereenvoudigd.gpkg"
        if source_path == output_path:
            original = next(
                (
                    layer
                    for layer in QgsProject.instance().mapLayers().values()
                    if isinstance(layer, QgsVectorLayer)
                    and layer.name() == "Clustergebieden"
                ),
                None,
            )
            if original is None:
                self._set_areas_status(
                    "Kies voor opnieuw maken eerst de oorspronkelijke laag Clustergebieden.",
                    True,
                )
                return
            areas = original
        # Release an older result before overwriting it, while keeping a backup.
        old_layers = [
            layer for layer in QgsProject.instance().mapLayers().values()
            if isinstance(layer, QgsVectorLayer)
            and self._persistent_layer_path(layer) == output_path
        ]
        for layer in old_layers:
            QgsProject.instance().removeMapLayer(layer.id())
        old_layers.clear()
        QApplication.processEvents()
        if output_path.exists():
            backup_folder = base_folder / "gebiedscorrecties"
            backup_folder.mkdir(parents=True, exist_ok=True)
            backup = backup_folder / f"clustergebieden_vereenvoudigd_backup_{datetime.now():%Y%m%d_%H%M%S_%f}.gpkg"
            output_path.replace(backup)
        self.areas_progress_group.setVisible(True)
        self.areas_progress_details.clear()
        self.areas_create_button.setEnabled(False)
        self.areas_draw_button.setEnabled(False)
        feedback = InlineProcessingFeedback(self._areas_progress_update)
        try:
            result = processing.run(
                "lsnetontwerp:clustergebieden_topologisch_vereenvoudigen",
                {
                    "GEBIEDEN": areas,
                    "AANSLUITINGEN": connections,
                    "GEBIED_CLUSTER": self.areas_cluster_field.text().strip() or "Cluster",
                    "AANSLUITING_CLUSTER": self.areas_connection_cluster_field.text().strip() or "Cluster",
                    "MAX_TOLERANTIE_M": self.areas_tolerance.value(),
                    "RECHTE_HOEKEN": self.areas_right_angles.isChecked(),
                    "MIN_BREEDTE_M": self.areas_min_width.value(),
                    "KNOOP_AFSCHUINING_M": self.areas_junction_tolerance.value(),
                    "OUTPUT": str(output_path),
                },
                feedback=feedback,
            )
            result_path = str(result.get("OUTPUT") or output_path)
            result_layer = QgsVectorLayer(result_path, "Clustergebieden vereenvoudigd", "ogr")
            if not result_layer.isValid():
                raise RuntimeError("De gemaakte gebiedenlaag kon niet worden geopend.")
            result_layer.setCustomProperty("LSNetontwerp/simplified_cluster_areas", True)
            if areas.renderer() is not None:
                result_layer.setRenderer(areas.renderer().clone())
            result_layer.setOpacity(1.0)
            result_layer.setScaleBasedVisibility(False)
            project = QgsProject.instance()
            project.addMapLayer(result_layer)
            root = project.layerTreeRoot()
            result_node = root.findLayer(result_layer.id())
            if result_node is not None:
                result_node.setItemVisibilityChecked(True)
            original_node = root.findLayer(areas.id())
            if original_node is not None:
                original_node.setItemVisibilityChecked(False)
            # The generated project uses a fixed custom draw order. A newly
            # added layer which is absent from that list can be selectable but
            # completely invisible. Insert the simplified areas at the exact
            # position of the original areas, always above OpenStreetMap.
            from .project_presentation import place_layer_before
            place_layer_before(result_layer, areas, project)
            project.write()
            self._areas_progress_update(100, "Vereenvoudigde clustergebieden gereed.")
            self._set_areas_status(
                f"Gereed: {result_layer.featureCount()} gebieden zijn topologisch "
                "vereenvoudigd tot compacte rechte blokken en blijvend opgeslagen. "
                "Selecteer nu twee buurgebieden "
                "om hun gezamenlijke grens te verleggen."
            )
            self._refresh_areas_layer_choices()
        except Exception as exc:
            self._set_areas_status(f"Vereenvoudigen mislukt: {exc}", True)
        finally:
            self.areas_create_button.setEnabled(True)
            self.areas_draw_button.setEnabled(True)
            if self.iface is not None:
                self.iface.mapCanvas().refresh()

    def start_area_boundary_drawing(self):
        if self._area_draw_layer is not None:
            self._clear_area_draw_layer()
            self._set_areas_status("Tekenen van de nieuwe grens is geannuleerd.")
            return
        if self.iface is None:
            self._set_areas_status("Interactief tekenen vereist QGIS Desktop.", True)
            return
        areas = self._areas_selected_layer()
        if areas is None or not areas.isValid():
            self._set_areas_status("Kies een geldige vereenvoudigde gebiedenlaag.", True)
            return
        selected_ids = list(areas.selectedFeatureIds())
        if len(selected_ids) != 2:
            self._set_areas_status("Selecteer eerst precies twee aangrenzende gebieden.", True)
            return
        if areas.isEditable():
            self._set_areas_status("Sla open bewerkingen in de gebiedenlaag eerst op.", True)
            return
        crs_text = areas.crs().authid() or areas.crs().toWkt()
        draw_layer = QgsVectorLayer(
            f"LineString?crs={crs_text}", "Nieuwe clustergrens (tekenen)", "memory"
        )
        symbol = draw_layer.renderer().symbol()
        symbol.setColor(QColor("#f47700"))
        symbol.setWidth(1.0)
        QgsProject.instance().addMapLayer(draw_layer)
        draw_layer.startEditing()
        self._area_draw_layer = draw_layer
        self._area_selected_ids = selected_ids
        self._area_draw_processing = False
        self.areas_draw_button.setText("Tekenen annuleren")
        draw_layer.featureAdded.connect(self._on_area_boundary_feature)
        self.iface.setActiveLayer(draw_layer)
        self.iface.actionAddFeature().trigger()
        self._set_areas_status(
            "Teken de gewenste nieuwe grens door het gezamenlijke vlak en sluit af "
            "met de rechter muisknop. De buitenrand blijft exact gelijk."
        )
        self.showMinimized()

    def _on_area_boundary_feature(self, feature_id):
        if self._area_draw_processing:
            return
        self._area_draw_processing = True
        QTimer.singleShot(0, self._process_area_boundary)

    def _clear_area_draw_layer(self):
        draw_layer = self._area_draw_layer
        if draw_layer is not None:
            try:
                draw_layer.featureAdded.disconnect(self._on_area_boundary_feature)
            except (TypeError, RuntimeError):
                pass
            if draw_layer.isEditable():
                draw_layer.rollBack()
            if draw_layer.id() in QgsProject.instance().mapLayers():
                QgsProject.instance().removeMapLayer(draw_layer.id())
        if self.iface is not None:
            self.iface.actionPan().trigger()
        self._area_draw_layer = None
        self._area_draw_processing = False
        self._area_selected_ids = []
        self.areas_draw_button.setText("Grens van 2 gebieden verleggen")

    def _process_area_boundary(self):
        draw_layer = self._area_draw_layer
        areas = self._areas_selected_layer()
        connections = self._areas_selected_layer(True)
        if draw_layer is None or areas is None or connections is None:
            self._clear_area_draw_layer()
            return
        try:
            draw_layer.featureAdded.disconnect(self._on_area_boundary_feature)
        except (TypeError, RuntimeError):
            pass
        if not draw_layer.commitChanges():
            self._set_areas_status("De getekende grens kon niet worden vastgelegd.", True)
            self._clear_area_draw_layer()
            self.showNormal()
            return
        cut_features = [
            feature for feature in draw_layer.getFeatures()
            if feature.hasGeometry() and feature.geometry().length() > 0.0
        ]
        self.showNormal()
        self.raise_()
        self.activateWindow()
        try:
            if not cut_features:
                raise RuntimeError("De getekende grens heeft geen geldige lengte.")
            feature_map = {
                feature.id(): feature
                for feature in areas.getFeatures()
                if feature.id() in self._area_selected_ids
            }
            if len(feature_map) != 2:
                raise RuntimeError("De twee geselecteerde gebieden zijn niet meer beschikbaar.")
            first, second = [feature_map[fid] for fid in self._area_selected_ids]
            area_field = self.areas_cluster_field.text().strip() or "Cluster"
            point_field = self.areas_connection_cluster_field.text().strip() or "Cluster"
            if areas.fields().lookupField(area_field) < 0 or connections.fields().lookupField(point_field) < 0:
                raise RuntimeError("De ingestelde clusterkolom ontbreekt.")
            first_cluster = str(first[area_field]).strip()
            second_cluster = str(second[area_field]).strip()
            transform = None
            if connections.crs() != areas.crs():
                transform = QgsCoordinateTransform(
                    connections.crs(), areas.crs(), QgsProject.instance()
                )
            points = {first_cluster: [], second_cluster: []}
            for connection in connections.getFeatures():
                cluster = str(connection[point_field]).strip()
                if cluster not in points or not connection.hasGeometry():
                    continue
                geometry = QgsGeometry(connection.geometry()).centroid()
                if transform is not None:
                    geometry.transform(transform)
                points[cluster].append(bytes(geometry.asWkb()))
            from .algorithms.clustergebied_grens import replace_shared_boundary
            first_wkb, second_wkb = replace_shared_boundary(
                bytes(first.geometry().asWkb()),
                bytes(second.geometry().asWkb()),
                bytes(cut_features[-1].geometry().asWkb()),
                points[first_cluster],
                points[second_cluster],
            )
            source_path = self._persistent_layer_path(areas)
            if source_path is None:
                raise RuntimeError("De vereenvoudigde gebiedenlaag moet blijvend zijn opgeslagen.")
            backup_folder = source_path.parent / "gebiedscorrecties"
            backup_folder.mkdir(parents=True, exist_ok=True)
            backup = backup_folder / f"clustergebieden_grens_backup_{datetime.now():%Y%m%d_%H%M%S_%f}.gpkg"
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = "clustergebieden_vereenvoudigd"
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile
            write_result = QgsVectorFileWriter.writeAsVectorFormatV3(
                areas,
                str(backup),
                QgsProject.instance().transformContext(),
                options,
            )
            if write_result[0] != QgsVectorFileWriter.NoError:
                raise RuntimeError(f"Back-up maken mislukt: {write_result[1]}")
            if not areas.startEditing():
                raise RuntimeError("Bewerken van de gebiedenlaag kon niet starten.")
            try:
                first_geometry = QgsGeometry()
                first_geometry.fromWkb(first_wkb)
                second_geometry = QgsGeometry()
                second_geometry.fromWkb(second_wkb)
                if QgsWkbTypes.isMultiType(areas.wkbType()):
                    first_geometry.convertToMultiType()
                    second_geometry.convertToMultiType()
                if not areas.changeGeometry(first.id(), first_geometry):
                    raise RuntimeError("Het eerste gebied kon niet worden gewijzigd.")
                if not areas.changeGeometry(second.id(), second_geometry):
                    raise RuntimeError("Het tweede gebied kon niet worden gewijzigd.")
                vertex_index = areas.fields().lookupField("Vertices")
                if vertex_index >= 0:
                    areas.changeAttributeValue(
                        first.id(), vertex_index, sum(1 for _ in first_geometry.vertices())
                    )
                    areas.changeAttributeValue(
                        second.id(), vertex_index, sum(1 for _ in second_geometry.vertices())
                    )
                if not areas.commitChanges():
                    raise RuntimeError("Opslaan van de nieuwe clustergrens is mislukt.")
            except Exception:
                areas.rollBack()
                raise
            areas.updateExtents()
            areas.triggerRepaint()
            QgsProject.instance().write()
            self._set_areas_status(
                f"Gereed: de grens tussen {first_cluster} en {second_cluster} is verlegd. "
                "Alle aansluitingen zijn gecontroleerd; overlap en gaten zijn voorkomen."
            )
        except Exception as exc:
            self._set_areas_status(f"Grens verleggen mislukt: {exc}", True)
        finally:
            self._clear_area_draw_layer()
            self._refresh_areas_selection_status()
            if self.iface is not None:
                self.iface.mapCanvas().refresh()

    def _refresh_network_layer_choices(self):
        try:
            from .algorithms.handmatige_cluster_correctie_tool import (
                HandmatigeClusterCorrectieAlgorithm,
            )
            defaults = HandmatigeClusterCorrectieAlgorithm._project_layer_defaults()
        except Exception:
            defaults = {}
        project = QgsProject.instance()
        layers = list(project.layerTreeRoot().layerOrder()) or list(
            project.mapLayers().values()
        )
        layers = [layer for layer in layers if hasattr(layer, "geometryType")]
        expected = {
            "AANSLUITINGEN": "Aansluitingen geclusterd",
            "STATIONS": "Stations ontwerp",
            "GEBIEDEN": "Clustergebieden",
            "KABELROUTES": "Kabelroutes per cluster",
            "SLEUVEN": "Sleuven geknipt/genood",
            "PLANGEBIED": "Plangebied",
        }
        for key, combo in self.network_layer_combos.items():
            previous = combo.currentData()
            combo.clear()
            if key == "PLANGEBIED":
                combo.addItem("(geen plangebied)", "")
            for layer in layers:
                combo.addItem(layer.name(), layer.id())
            preferred = defaults.get(key) or previous
            index = combo.findData(preferred) if preferred else -1
            if index < 0:
                index = combo.findText(expected[key])
            if index >= 0:
                combo.setCurrentIndex(index)
        if not self.network_backup_edit.text().strip():
            home = project.homePath()
            if home:
                self.network_backup_edit.setText(str(Path(home) / "netwerk_onderhoud"))

    def _network_selected_layer(self, key):
        layer_id = self.network_layer_combos[key].currentData()
        return QgsProject.instance().mapLayer(layer_id) if layer_id else None

    def _browse_network_backup_folder(self):
        start = self.network_backup_edit.text().strip()
        if not start:
            start = QgsProject.instance().homePath() or str(Path.home())
        selected = QFileDialog.getExistingDirectory(
            self, "Kies map voor netwerkback-ups", start
        )
        if selected:
            self.network_backup_edit.setText(selected)

    def _network_progress_update(self, percent, message):
        text = str(message).strip()
        self.network_progress_bar.setValue(max(0, min(100, int(percent))))
        self.network_progress_summary.setText(self._short_progress_message(text))
        self.network_progress_summary.setToolTip(text)
        self._append_unique_progress(self.network_progress_details, text)
        QApplication.processEvents()

    def _set_network_status(self, message, error=False):
        self._set_page_status(self.network_status_label, message, error)

    def start_new_trench_drawing(self):
        if self._network_draw_layer is not None:
            self._clear_network_draw_layer()
            self._set_network_status("Tekenen van de nieuwe sleuf is geannuleerd.")
            return
        if self.iface is None:
            self._set_network_status("Interactief tekenen vereist QGIS Desktop.", True)
            return
        cables = self._network_selected_layer("SLEUVEN")
        if cables is None or not cables.isValid():
            self._set_network_status("Kies een geldige sleuvenlaag.", True)
            return
        if cables.isEditable():
            self._set_network_status(
                "Sla de open bewerkingen in de sleuvenlaag eerst op.", True
            )
            return
        crs_text = cables.crs().authid() or cables.crs().toWkt()
        draw_layer = QgsVectorLayer(
            f"LineString?crs={crs_text}", "Nieuwe sleuf (tekenen)", "memory"
        )
        if not draw_layer.isValid():
            self._set_network_status("De tijdelijke tekenlaag kon niet worden gemaakt.", True)
            return
        symbol = draw_layer.renderer().symbol()
        symbol.setColor(QColor("#f47700"))
        symbol.setWidth(0.8)
        QgsProject.instance().addMapLayer(draw_layer)
        draw_layer.startEditing()
        self._network_draw_layer = draw_layer
        self._network_draw_processing = False
        self.network_draw_button.setText("Tekenen annuleren")
        draw_layer.featureAdded.connect(self._on_new_trench_feature)
        self.iface.setActiveLayer(draw_layer)
        self.iface.actionAddFeature().trigger()
        self._set_network_status(
            "Klik de sleufroute in de kaart en sluit af met de rechter muisknop. "
            "Daarna wordt het netwerk automatisch geknipt/genood."
        )
        self.showMinimized()

    def _on_new_trench_feature(self, feature_id):
        if self._network_draw_processing:
            return
        self._network_draw_processing = True
        QTimer.singleShot(0, lambda: self._process_drawn_trench(int(feature_id)))

    def _clear_network_draw_layer(self):
        draw_layer = self._network_draw_layer
        if draw_layer is None:
            self.network_draw_button.setText("Nieuwe sleuf tekenen")
            return
        try:
            draw_layer.featureAdded.disconnect(self._on_new_trench_feature)
        except (TypeError, RuntimeError):
            pass
        if draw_layer.isEditable():
            draw_layer.rollBack()
        if self.iface is not None:
            self.iface.actionPan().trigger()
        if draw_layer.id() in QgsProject.instance().mapLayers():
            QgsProject.instance().removeMapLayer(draw_layer.id())
        self._network_draw_layer = None
        self._network_draw_processing = False
        self.network_draw_button.setText("Nieuwe sleuf tekenen")

    def _process_drawn_trench(self, feature_id):
        draw_layer = self._network_draw_layer
        if draw_layer is None:
            return
        try:
            draw_layer.featureAdded.disconnect(self._on_new_trench_feature)
        except (TypeError, RuntimeError):
            pass
        if not draw_layer.commitChanges():
            self._set_network_status("De getekende sleuf kon niet worden vastgelegd.", True)
            self._clear_network_draw_layer()
            self.showNormal()
            return
        # A committed memory-layer feature receives a new provider FID. The
        # featureAdded signal still contains the former negative edit-buffer
        # FID, so look up the committed geometry itself instead of reusing it.
        valid_features = [
            feature
            for feature in draw_layer.getFeatures()
            if feature.isValid()
            and not feature.geometry().isNull()
            and not feature.geometry().isEmpty()
            and feature.geometry().length() > 0.0
        ]
        if not valid_features:
            self._set_network_status("De getekende sleuf heeft geen geldige lengte.", True)
            self._clear_network_draw_layer()
            self.showNormal()
            return
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.network_progress_group.setVisible(True)
        self.network_progress_details.clear()
        self.network_draw_button.setEnabled(False)
        self.network_refresh_button.setEnabled(False)
        self.network_selected_refresh_button.setEnabled(False)
        feedback = InlineProcessingFeedback(self._network_progress_update)
        try:
            layers = {
                key: self._network_selected_layer(key)
                for key in self.network_layer_combos
            }
            required = ("SLEUVEN", "AANSLUITINGEN", "STATIONS")
            if any(layers[key] is None for key in required):
                raise RuntimeError("Niet alle verplichte netwerklagen zijn gevonden.")
            backup = self.network_backup_edit.text().strip()
            if not backup:
                backup = str(Path(QgsProject.instance().homePath()) / "netwerk_onderhoud")
                self.network_backup_edit.setText(backup)
            result = processing.run(
                "lsnetontwerp:sleufroute_toevoegen_en_noden",
                {
                    "SLEUVEN": layers["SLEUVEN"],
                    "NIEUWE_SLEUF": draw_layer,
                    "AANSLUITINGEN": layers["AANSLUITINGEN"],
                    "STATIONS": layers["STATIONS"],
                    "PLANGEBIED": layers["PLANGEBIED"],
                    "KNOOP_TOLERANTIE_M": self.network_node_tolerance.value(),
                    "BACKUPMAP": backup,
                },
                feedback=feedback,
            )
            self._network_progress_update(100, "Nieuwe sleuf volledig genood.")
            self._set_network_status(
                f"Gereed: nieuwe sleuf toegevoegd; het netwerk bevat "
                f"{int(result.get('AANTAL_DELEN', 0))} geknipte/genode delen. "
                "Handmatige clustercorrectie kan deze route nu gebruiken."
            )
        except Exception as exc:
            self._set_network_status(f"Nieuwe sleuf verwerken mislukt: {exc}", True)
        finally:
            self._clear_network_draw_layer()
            self.network_draw_button.setEnabled(True)
            self.network_refresh_button.setEnabled(True)
            self.network_selected_refresh_button.setEnabled(True)
            if self.iface is not None:
                self.iface.mapCanvas().refresh()

    def run_route_refresh(self, selected_only=False):
        layers = {
            key: self._network_selected_layer(key)
            for key in self.network_layer_combos
        }
        required = ("AANSLUITINGEN", "STATIONS", "GEBIEDEN", "KABELROUTES", "SLEUVEN")
        missing = [key for key in required if layers[key] is None]
        if missing:
            self._set_network_status(
                "Verplichte resultaatlagen ontbreken: " + ", ".join(missing), True
            )
            return
        selected_clusters = set()
        if selected_only:
            for layer in (layers["KABELROUTES"], layers["STATIONS"]):
                cluster_field = layer.fields().lookupField("Cluster")
                if cluster_field < 0:
                    continue
                selected_clusters.update(
                    str(feature.attribute(cluster_field)).strip()
                    for feature in layer.getSelectedFeatures()
                    if str(feature.attribute(cluster_field)).strip()
                )
            if not selected_clusters:
                self._set_network_status(
                    "Selecteer eerst één of meer kabelroutes of stations in de kaart.",
                    True,
                )
                return
        backup = self.network_backup_edit.text().strip()
        if not backup:
            home = QgsProject.instance().homePath()
            if not home:
                self._set_network_status("Kies bij Geavanceerde opties een back-upmap.", True)
                return
            backup = str(Path(home) / "netwerk_onderhoud")
            self.network_backup_edit.setText(backup)
        self.network_progress_group.setVisible(True)
        self.network_progress_details.clear()
        self.network_draw_button.setEnabled(False)
        self.network_refresh_button.setEnabled(False)
        self.network_selected_refresh_button.setEnabled(False)
        action_text = (
            "Geselecteerde clusterroutes worden vernieuwd…"
            if selected_only
            else "Alle kortste clusterroutes worden vernieuwd…"
        )
        self._set_network_status(action_text)
        feedback = InlineProcessingFeedback(self._network_progress_update)
        try:
            processing.run(
                "lsnetontwerp:handmatige_clustercorrectie_selectie",
                {
                    "AANSLUITINGEN": layers["AANSLUITINGEN"],
                    "STATIONS": layers["STATIONS"],
                    "GEBIEDEN": layers["GEBIEDEN"],
                    "KABELROUTES": layers["KABELROUTES"],
                    "SLEUVEN": layers["SLEUVEN"],
                    "PLANGEBIED": layers["PLANGEBIED"],
                    "HELE_BRONCLUSTER_VERWIJDEREN": False,
                    "ALLE_ROUTES_VERVERSEN": True,
                    "ALLEEN_GESELECTEERDE_ROUTES": bool(selected_only),
                    "ROUTE_CLUSTERS": ", ".join(sorted(selected_clusters)),
                    "ALLES_TOESTAAN": False,
                    "CONTROLE_MAX_ONTWERPSTROOM": False,
                    "CONTROLE_MAX_KABELLENGTE": self.network_check_max_route.isChecked(),
                    "CONTROLE_ROUTES_ANDERE_CLUSTERS": self.network_block_other_routes.isChecked(),
                    "CONTROLE_GEDEELDE_ROUTES_VERTAKKINGEN": self.network_check_shared.isChecked(),
                    "MAX_ROUTE_M": self.network_max_route.value(),
                    "KNOOP_TOLERANTIE_M": 0.0,
                    "BACKUPMAP": backup,
                },
                feedback=feedback,
            )
            self._network_progress_update(
                100,
                "Geselecteerde clusterroutes vernieuwd."
                if selected_only
                else "Alle clusterroutes vernieuwd.",
            )
            self._set_network_status(
                (
                    "Gereed: geselecteerde kortste routes, Route_m, "
                    "stationsinformatie, clustergebieden, tabel en layout zijn "
                    "vernieuwd."
                    if selected_only
                    else "Gereed: kortste routes, Route_m, stationsinformatie, "
                    "clustergebieden, tabel en layout zijn vernieuwd."
                )
            )
        except Exception as exc:
            self._set_network_status(f"Routes verversen mislukt: {exc}", True)
        finally:
            self.network_draw_button.setEnabled(True)
            self.network_refresh_button.setEnabled(True)
            self.network_selected_refresh_button.setEnabled(True)
            if self.iface is not None:
                self.iface.mapCanvas().refresh()

    def show_manual_page(self, unrestricted=False):
        self._refresh_manual_layer_choices()
        self.manual_allow_all.setChecked(bool(unrestricted))
        if not unrestricted:
            for checkbox in self.manual_safety_checks.values():
                checkbox.setChecked(True)
            self.manual_max_route.setValue(850.0)
            self.manual_node_tolerance.setValue(0.0)
        self.manual_advanced_toggle.setChecked(bool(unrestricted))
        self._refresh_manual_selection_status()
        self.page_stack.setCurrentWidget(self.manual_page)
        self.setWindowTitle("LS Netontwerp Wizard – handmatige clustercorrectie")
        self.resize(1120, 650 if not self.manual_advanced_toggle.isChecked() else 820)

    def _toggle_manual_advanced(self, enabled):
        self.manual_advanced_container.setVisible(enabled)
        self.resize(1120, 820 if enabled else 650)

    def _browse_manual_backup_folder(self):
        start = self.manual_backup_edit.text().strip()
        if not start:
            start = QgsProject.instance().homePath() or str(Path.home())
        selected = QFileDialog.getExistingDirectory(
            self, "Kies map voor correctieback-ups", start
        )
        if selected:
            self.manual_backup_edit.setText(selected)

    def _refresh_manual_layer_choices(self):
        project = QgsProject.instance()
        try:
            from .algorithms.handmatige_cluster_correctie_tool import (
                HandmatigeClusterCorrectieAlgorithm,
            )

            defaults = HandmatigeClusterCorrectieAlgorithm._project_layer_defaults()
        except Exception:
            defaults = {}
        ordered_layers = list(project.layerTreeRoot().layerOrder())
        if not ordered_layers:
            ordered_layers = list(project.mapLayers().values())
        vector_layers = [
            layer for layer in ordered_layers if hasattr(layer, "geometryType")
        ]
        expected_names = {
            "AANSLUITINGEN": "Aansluitingen geclusterd",
            "STATIONS": "Stations ontwerp",
            "GEBIEDEN": "Clustergebieden",
            "KABELROUTES": "Kabelroutes per cluster",
            "SLEUVEN": "Sleuven geknipt/genood",
            "PLANGEBIED": "Plangebied",
        }
        for key, combo in self.manual_layer_combos.items():
            previous_id = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            if key == "PLANGEBIED":
                combo.addItem("(geen plangebied)", "")
            for layer in vector_layers:
                combo.addItem(layer.name(), layer.id())
            preferred_id = defaults.get(key) or previous_id
            index = combo.findData(preferred_id) if preferred_id else -1
            if index < 0:
                index = combo.findText(expected_names[key])
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)
        if not self.manual_backup_edit.text().strip():
            project_home = project.homePath()
            if project_home:
                self.manual_backup_edit.setText(
                    str(Path(project_home) / "handmatige_correcties")
                )

    def _manual_selected_layer(self, key):
        layer_id = self.manual_layer_combos[key].currentData()
        return QgsProject.instance().mapLayer(layer_id) if layer_id else None

    def _refresh_manual_selection_status(self):
        connections = self._manual_selected_layer("AANSLUITINGEN")
        stations = self._manual_selected_layer("STATIONS")
        connection_count = (
            len(connections.selectedFeatureIds()) if connections is not None else 0
        )
        station_count = len(stations.selectedFeatureIds()) if stations is not None else 0
        valid = connection_count >= 1 and station_count == 1
        color = "#2e7d32" if valid else "#b54800"
        self.manual_selection_label.setStyleSheet(
            f"color: {color}; font-weight: 700;"
        )
        self.manual_selection_label.setText(
            f"Geselecteerde aansluitingen: {connection_count}  •  "
            f"geselecteerde doelstations: {station_count}"
        )
        return valid

    def _add_subpage_header(self, root, title_text, subtitle_text):
        header_widget = QWidget()
        header_widget.setFixedHeight(84)
        header = QHBoxLayout(header_widget)
        header.setContentsMargins(0, 0, 0, 0)
        logo = QLabel()
        pixmap = QPixmap(
            str(Path(__file__).resolve().parent / "assets" / "techbase-logo.png")
        )
        try:
            keep_aspect = Qt.AspectRatioMode.KeepAspectRatio
            smooth = Qt.TransformationMode.SmoothTransformation
        except AttributeError:
            keep_aspect = Qt.KeepAspectRatio
            smooth = Qt.SmoothTransformation
        if not pixmap.isNull():
            logo.setPixmap(pixmap.scaled(68, 68, keep_aspect, smooth))
        logo.setFixedSize(76, 76)
        title_box = QVBoxLayout()
        title = QLabel(title_text)
        title.setObjectName("techbaseTitle")
        subtitle = QLabel(subtitle_text)
        subtitle.setObjectName("techbaseSubtitle")
        title_box.addStretch(1)
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        title_box.addStretch(1)
        header.addWidget(logo)
        header.addLayout(title_box, 1)
        home_button = QPushButton("←  Home")
        home_button.setObjectName("genInfoButton")
        home_button.clicked.connect(self.show_home_page)
        header.addWidget(home_button)
        root.addWidget(header_widget)
        return home_button

    def _build_value_page(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(10, 8, 10, 8)
        self.value_home_button = self._add_subpage_header(
            outer,
            "Ontwerpstroom aanpassen",
            "TechBase • verbruik en opwek voor kaartselecties",
        )
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        root = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll)
        note = QLabel(
            "Selecteer een of meer punten in <b>LS-aansluitingen "
            "ontwerpstroom</b> en vul voor alle geselecteerde punten de "
            "trafo- en kabelstromen voor verbruik en opwek in. Hoogste Trafo en "
            "Hoogste Kabel worden daarna automatisch uit die waarden berekend."
        )
        note.setWordWrap(True)
        root.addWidget(note)

        category_group = QGroupBox("Categorie")
        category_form = QFormLayout(category_group)
        self.value_category_combo = QComboBox()
        for label, stored in ZeroCurrentPage.CATEGORY_CHOICES:
            self.value_category_combo.addItem(label, stored)
        self.value_category_combo.currentIndexChanged.connect(
            self._value_category_changed
        )
        category_form.addRow("Aansluittype", self.value_category_combo)
        root.addWidget(category_group)

        self.value_housing_group = QGroupBox("Woningtype voor huishoudelijk")
        housing_layout = QVBoxLayout(self.value_housing_group)
        self.value_housing_combo = QComboBox()
        for label, stored in HOUSEHOLD_UNIT_CHOICES:
            self.value_housing_combo.addItem(label, stored)
        housing_layout.addWidget(self.value_housing_combo)
        self.value_housing_combo.currentIndexChanged.connect(self._value_household_changed)
        self.value_housing_note = QLabel(
            "Oude of nieuwbouwtabellen worden per aansluiting gekozen op basis "
            "van bouwjaar."
        )
        self.value_housing_note.setWordWrap(True)
        housing_layout.addWidget(self.value_housing_note)
        root.addWidget(self.value_housing_group)

        self.value_unit_group = QGroupBox("Type wooneenheid / aansluiting")
        self.value_unit_group.setProperty("uiContentMinimum", True)
        unit_form = QFormLayout(self.value_unit_group)
        self.value_unit_combo = QComboBox()
        unit_form.addRow("Type wooneenheid", self.value_unit_combo)
        self.value_gas_combo = QComboBox()
        fill_gas_combo(self.value_gas_combo)
        self.value_gas_label = QLabel("Gasaansluiting")
        unit_form.addRow(self.value_gas_label, self.value_gas_combo)
        self.value_unit_note = QLabel()
        self.value_unit_note.setWordWrap(True)
        unit_form.addRow(self.value_unit_note)
        self.value_unit_combo.currentIndexChanged.connect(self._value_unit_changed)
        self.value_gas_combo.currentIndexChanged.connect(self._value_unit_changed)
        root.addWidget(self.value_unit_group)

        selection_group = QGroupBox("Kaartselectie")
        selection_row = QHBoxLayout(selection_group)
        self.value_selection_label = QLabel("Selectie nog niet gecontroleerd")
        refresh = QPushButton("Selectie en waarden vernieuwen")
        refresh.clicked.connect(self._refresh_value_selection_status)
        selection_row.addWidget(self.value_selection_label, 1)
        selection_row.addWidget(refresh)
        root.addWidget(selection_group)

        values_group = QGroupBox("Verbruik en opwek")
        self.value_manual_group = values_group
        values_form = QFormLayout(values_group)
        self.value_manual_checkbox = QCheckBox("Zelf ingevulde stroomwaarden gebruiken")
        values_form.addRow(self.value_manual_checkbox)
        self.value_manual_checkbox.toggled.connect(self._value_manual_mode_changed)
        self.value_trafo = QDoubleSpinBox()
        self.value_trafo.setRange(0.0, 1000000.0)
        self.value_trafo.setDecimals(3)
        self.value_cable = QDoubleSpinBox()
        self.value_cable.setRange(0.0, 1000000.0)
        self.value_cable.setDecimals(3)
        self.value_generation_trafo = QDoubleSpinBox()
        self.value_generation_trafo.setRange(0.0, 1000000.0)
        self.value_generation_trafo.setDecimals(3)
        self.value_generation_cable = QDoubleSpinBox()
        self.value_generation_cable.setRange(0.0, 1000000.0)
        self.value_generation_cable.setDecimals(3)
        values_form.addRow("Trafo verbruik (A)", self.value_trafo)
        values_form.addRow("Kabel verbruik (A)", self.value_cable)
        values_form.addRow("Trafo opwek (A)", self.value_generation_trafo)
        values_form.addRow("Kabel opwek (A)", self.value_generation_cable)
        root.addWidget(values_group)
        self.value_highest_preview = QLabel()
        self.value_highest_preview.setWordWrap(True)
        root.addWidget(self.value_highest_preview)
        for spin in (
            self.value_trafo,
            self.value_cable,
            self.value_generation_trafo,
            self.value_generation_cable,
        ):
            spin.valueChanged.connect(self._update_value_highest_preview)
        connect_current_edits(self._value_current_spins(), self.value_manual_checkbox)

        self.value_advanced_toggle = QCheckBox("Advanced")
        root.addWidget(self.value_advanced_toggle)
        self.value_advanced_container = QGroupBox("Invoerlaag")
        advanced_form = QFormLayout(self.value_advanced_container)
        self.value_layer_combo = QComboBox()
        self.value_layer_combo.currentIndexChanged.connect(
            self._refresh_value_selection_status
        )
        advanced_form.addRow("LS-aansluitingenlaag", self.value_layer_combo)
        self.value_advanced_container.setVisible(False)
        self.value_advanced_toggle.toggled.connect(
            self.value_advanced_container.setVisible
        )
        root.addWidget(self.value_advanced_container)

        self.value_progress_group = QGroupBox("Voortgang")
        progress_layout = QVBoxLayout(self.value_progress_group)
        self.value_progress_summary = QLabel("Gereed voor een wijziging")
        self.value_progress_bar = QProgressBar()
        self.value_progress_bar.setRange(0, 100)
        self.value_progress_details = QPlainTextEdit()
        self.value_progress_details.setReadOnly(True)
        self.value_progress_details.setMaximumHeight(100)
        progress_layout.addWidget(self.value_progress_summary)
        progress_layout.addWidget(self.value_progress_bar)
        progress_layout.addWidget(self.value_progress_details)
        self.value_progress_group.setVisible(False)
        root.addWidget(self.value_progress_group)
        self.value_status_label = QLabel(
            "Maak een kaartselectie en vul de gewenste waarden in."
        )
        self.value_status_label.setWordWrap(True)
        root.addWidget(self.value_status_label)
        root.addStretch(1)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.value_run_button = QPushButton("Waarden opslaan")
        self.value_run_button.clicked.connect(self.run_value_edit)
        close_button = QPushButton("Sluiten")
        close_button.clicked.connect(self.close)
        button_row.addWidget(self.value_run_button)
        button_row.addWidget(close_button)
        root.addLayout(button_row)
        self._value_category_changed()
        self._update_value_highest_preview()
        return page

    def _build_station_page(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(10, 8, 10, 8)
        self.station_home_button = self._add_subpage_header(
            root,
            "Bestaande stations aanpassen",
            "TechBase • trafocapaciteit, Max_A en stationsselectie",
        )
        note = QLabel(
            "Selecteer één of meer rode stationsvierkanten in "
            "<b>Bestaande stations (bron)</b>. Sla een nieuwe "
            "trafocapaciteit op of verwijder de geselecteerde stations. "
            "De clustering in stap 3 gebruikt de gewijzigde bronlaag direct."
        )
        note.setWordWrap(True)
        root.addWidget(note)

        selection_group = QGroupBox("Kaartselectie")
        selection_row = QHBoxLayout(selection_group)
        self.station_selection_label = QLabel("Selectie nog niet gecontroleerd")
        refresh = QPushButton("Selectie en waarde vernieuwen")
        refresh.clicked.connect(self._refresh_station_selection_status)
        selection_row.addWidget(self.station_selection_label, 1)
        selection_row.addWidget(refresh)
        root.addWidget(selection_group)

        capacity_group = QGroupBox("Nieuwe stationswaarde")
        capacity_form = QFormLayout(capacity_group)
        self.station_capacity = QDoubleSpinBox()
        self.station_capacity.setRange(0.001, 1000000.0)
        self.station_capacity.setDecimals(3)
        self.station_capacity.setValue(630.0)
        self.station_max_preview = QLabel("Max_A: 913,0 A")
        self.station_max_preview.setStyleSheet(
            "color: #e66700; font-weight: 700;"
        )
        self.station_capacity.valueChanged.connect(
            self._update_station_max_preview
        )
        capacity_form.addRow("Trafocapaciteit (kVA)", self.station_capacity)
        capacity_form.addRow("Berekende maximale ontwerpstroom", self.station_max_preview)
        root.addWidget(capacity_group)

        self.station_advanced_toggle = QCheckBox("Advanced")
        root.addWidget(self.station_advanced_toggle)
        self.station_advanced_container = QGroupBox("Laag en kolommen")
        advanced_form = QFormLayout(self.station_advanced_container)
        self.station_layer_combo = QComboBox()
        self.station_layer_combo.currentIndexChanged.connect(
            self._refresh_station_fields
        )
        self.station_layer_combo.currentIndexChanged.connect(
            self._refresh_station_selection_status
        )
        self.station_field_combos = {
            key: QComboBox()
            for key in (
                "STATIONSNAAM_VELD",
                "TRAFO_CAPACITEIT_VELD",
                "MAX_STROOM_VELD",
            )
        }
        advanced_form.addRow("Stationslaag", self.station_layer_combo)
        for key, label in (
            ("STATIONSNAAM_VELD", "Kolom stationsnaam"),
            ("TRAFO_CAPACITEIT_VELD", "Kolom trafocapaciteit"),
            ("MAX_STROOM_VELD", "Kolom maximale ontwerpstroom"),
        ):
            advanced_form.addRow(label, self.station_field_combos[key])
        self.station_advanced_container.setVisible(False)
        self.station_advanced_toggle.toggled.connect(
            self.station_advanced_container.setVisible
        )
        root.addWidget(self.station_advanced_container)

        self.station_status_label = QLabel(
            "Maak een kaartselectie en kies daarna wijzigen of verwijderen."
        )
        self.station_status_label.setWordWrap(True)
        root.addWidget(self.station_status_label)
        root.addStretch(1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.station_save_button = QPushButton("Trafocapaciteit opslaan")
        self.station_save_button.clicked.connect(self.run_station_edit)
        self.station_delete_button = QPushButton("Geselecteerde stations verwijderen")
        self.station_delete_button.setObjectName("dangerButton")
        self.station_delete_button.clicked.connect(self.run_station_delete)
        close_button = QPushButton("Sluiten")
        close_button.clicked.connect(self.close)
        button_row.addWidget(self.station_save_button)
        button_row.addWidget(self.station_delete_button)
        button_row.addWidget(close_button)
        root.addLayout(button_row)
        return page

    def _build_housing_page(self):
        from .algorithms.woningtype_selectie_herberekenen_tool import HOUSING_CHOICES

        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(10, 8, 10, 8)
        self.housing_home_button = self._add_subpage_header(
            root,
            "Woningtype aanpassen",
            "TechBase • BAG-woningtype wijzigen en ontwerpstroom herberekenen",
        )
        note = QLabel(
            "Selecteer een of meer panden in <b>Woningtypen BAG/3DBAG</b>. "
            "Het gekozen woningtype wordt opgeslagen en de ontwerpstroom van "
            "alle bijbehorende LS-aansluitingen wordt direct herberekend."
        )
        note.setWordWrap(True)
        root.addWidget(note)

        selection_group = QGroupBox("Kaartselectie")
        selection_row = QHBoxLayout(selection_group)
        self.housing_selection_label = QLabel("Selectie nog niet gecontroleerd")
        refresh = QPushButton("Selectie vernieuwen")
        refresh.clicked.connect(self._refresh_housing_selection_status)
        selection_row.addWidget(self.housing_selection_label, 1)
        selection_row.addWidget(refresh)
        root.addWidget(selection_group)

        choice_group = QGroupBox("Nieuw woningtype")
        choice_form = QFormLayout(choice_group)
        self.housing_type_combo = QComboBox()
        for label, stored in HOUSING_CHOICES:
            self.housing_type_combo.addItem(label, stored)
        choice_form.addRow("Woningtype", self.housing_type_combo)
        root.addWidget(choice_group)

        self.housing_advanced_toggle = QCheckBox("Advanced")
        root.addWidget(self.housing_advanced_toggle)
        self.housing_advanced_container = QScrollArea()
        self.housing_advanced_container.setWidgetResizable(True)
        advanced_content = QWidget()
        advanced_form = QFormLayout(advanced_content)
        self.housing_layer_combo = QComboBox()
        self.housing_points_combo = QComboBox()
        self.housing_field_combos = {
            key: QComboBox()
            for key in (
                "VELD_WONINGTYPE",
                "VELD_BOUWJAAR",
                "VELD_DOORLAAT",
                "VELD_GEBRUIK",
                "VELD_GAS",
            )
        }
        advanced_form.addRow("Woningtypenlaag", self.housing_layer_combo)
        advanced_form.addRow("LS-aansluitingenlaag", self.housing_points_combo)
        for key, label in (
            ("VELD_WONINGTYPE", "Kolom woningtype"),
            ("VELD_BOUWJAAR", "Kolom bouwjaar"),
            ("VELD_DOORLAAT", "Kolom doorlaatwaarde"),
            ("VELD_GEBRUIK", "Kolom gebruiksdoel"),
            ("VELD_GAS", "Kolom gascategorie"),
        ):
            advanced_form.addRow(label, self.housing_field_combos[key])
        self.housing_layer_combo.currentIndexChanged.connect(
            self._refresh_housing_fields
        )
        self.housing_layer_combo.currentIndexChanged.connect(
            self._refresh_housing_selection_status
        )
        self.housing_points_combo.currentIndexChanged.connect(
            self._refresh_housing_fields
        )
        self.housing_advanced_container.setWidget(advanced_content)
        self.housing_advanced_container.setVisible(False)
        self.housing_advanced_toggle.toggled.connect(
            self.housing_advanced_container.setVisible
        )
        root.addWidget(self.housing_advanced_container, 1)

        self.housing_progress_group = QGroupBox("Voortgang")
        progress_layout = QVBoxLayout(self.housing_progress_group)
        self.housing_progress_summary = QLabel("Gereed voor een wijziging")
        self.housing_progress_bar = QProgressBar()
        self.housing_progress_bar.setRange(0, 100)
        self.housing_progress_details = QPlainTextEdit()
        self.housing_progress_details.setReadOnly(True)
        self.housing_progress_details.setMaximumHeight(100)
        progress_layout.addWidget(self.housing_progress_summary)
        progress_layout.addWidget(self.housing_progress_bar)
        progress_layout.addWidget(self.housing_progress_details)
        self.housing_progress_group.setVisible(False)
        root.addWidget(self.housing_progress_group)
        self.housing_status_label = QLabel(
            "Maak een kaartselectie en kies het nieuwe woningtype."
        )
        self.housing_status_label.setWordWrap(True)
        root.addWidget(self.housing_status_label)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.housing_run_button = QPushButton("Woningtype opslaan en herberekenen")
        self.housing_run_button.clicked.connect(self.run_housing_edit)
        close_button = QPushButton("Sluiten")
        close_button.clicked.connect(self.close)
        button_row.addWidget(self.housing_run_button)
        button_row.addWidget(close_button)
        root.addLayout(button_row)
        return page

    @staticmethod
    def _vector_project_layers():
        project = QgsProject.instance()
        ordered = list(project.layerTreeRoot().layerOrder())
        if not ordered:
            ordered = list(project.mapLayers().values())
        return [layer for layer in ordered if hasattr(layer, "geometryType")]

    @staticmethod
    def _fill_layer_combo(combo, layers, preferred_layer=None):
        previous_id = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for layer in layers:
            combo.addItem(layer.name(), layer.id())
        preferred_id = preferred_layer.id() if preferred_layer is not None else previous_id
        index = combo.findData(preferred_id) if preferred_id else -1
        if index >= 0:
            combo.setCurrentIndex(index)
        combo.blockSignals(False)

    @staticmethod
    def _layer_from_combo(combo):
        layer_id = combo.currentData()
        return QgsProject.instance().mapLayer(layer_id) if layer_id else None

    def show_value_page(self):
        from .algorithms.hoogste_waarden_selectie_tool import (
            HoogsteWaardenSelectieAlgorithm,
        )

        preferred = HoogsteWaardenSelectieAlgorithm._default_layer()
        self._fill_layer_combo(
            self.value_layer_combo, self._vector_project_layers(), preferred
        )
        self.value_advanced_toggle.setChecked(False)
        layer = self._layer_from_combo(self.value_layer_combo)
        self._value_category_changed()
        self._choose_value_category_from_selection(layer)
        self._refresh_value_selection_status(True)
        self.page_stack.setCurrentWidget(self.value_page)
        self.setWindowTitle("LS Netontwerp Wizard – ontwerpstroom aanpassen")
        self.resize(920, 620)

    def _choose_value_category_from_selection(self, layer):
        selected = list(layer.selectedFeatures()) if layer is not None else []
        if not selected:
            return
        known_categories = {
            self.value_category_combo.itemData(index): index
            for index in range(self.value_category_combo.count())
        }

        def text_value(feature, field_name):
            index = layer.fields().lookupField(field_name)
            if index < 0:
                return ""
            value = feature[index]
            return "" if value is None else str(value).strip().casefold()

        sample = selected[0]
        stored_category = self.zero_current_page._field_value(sample, "HerstelCat")
        use = " ".join(
            text_value(sample, field_name)
            for field_name in ("Gebruiksdoel", "Gevonden_Woningtype", "G_Type")
        )
        type_code = text_value(sample, "G_Type")
        if "laad" in use or "oplaad" in use or type_code == "8":
            category = "Oplaadpunt"
        elif "straat" in use or any(
            token in use
            for token in ("abri", "bushalte", "reclamezuil", "verlichting", "lantaarn")
        ) or type_code == "9":
            category = "Straatmeubilair"
        elif any(
            token in use
            for token in (
                "woon",
                "appartement",
                "woning",
                "huishoud",
                "hoekwoning",
                "tussen/geschakeld",
                "vrijstaand",
                "onder-een-kap",
            )
        ) or type_code in ("1", "4"):
            category = "Huishoudelijk"
        else:
            category = "Zakelijk"
        if stored_category in known_categories:
            category = stored_category
        if category in known_categories:
            self.value_category_combo.setCurrentIndex(known_categories[category])
        house_type = text_value(sample, "Gevonden_Woningtype")
        if house_type:
            index = self.value_housing_combo.findData(house_type)
            if index < 0:
                index = self.value_housing_combo.findText(house_type)
            if index >= 0:
                self.value_housing_combo.setCurrentIndex(index)
        if category != "Huishoudelijk":
            stored_unit = text_value(sample, "HerstelType")
            index = next((i for i in range(self.value_unit_combo.count()) if self.value_unit_combo.itemText(i).casefold() == stored_unit), -1)
            if index >= 0:
                self.value_unit_combo.setCurrentIndex(index)
            elif stored_unit:
                self.value_unit_combo.setCurrentIndex(self.value_unit_combo.findData(None))
            if category == "Zakelijk":
                module = current_context(self)[0]
                gas_field = self._workflow_field_defaults().get("field_gas", "G_Type")
                gas = module.normalize_gas(text_value(sample, gas_field))
                self.value_gas_combo.setCurrentIndex(self.value_gas_combo.findData(gas))

    def _value_matrix_current(self, key, fallback):
        items = self._workflow_field_defaults().get(key)
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

    def _value_category_changed(self, *_args):
        if not hasattr(self, "value_category_combo"):
            return
        category = self.value_category_combo.currentData()
        household = category == "Huishoudelijk"
        self.value_housing_group.setVisible(household)
        self.value_manual_group.setVisible(True)
        self.value_manual_checkbox.setChecked(False)
        self.value_unit_group.setVisible(not household)
        self.value_gas_combo.setVisible(category == "Zakelijk")
        self.value_gas_label.setVisible(category == "Zakelijk")
        fill_unit_combo(self.value_unit_combo, category)
        if category == "Straatmeubilair":
            trafo = self._value_matrix_current("matrix_straat", 5.8)
            cable = trafo
        elif category == "Oplaadpunt":
            trafo = self._value_matrix_current("matrix_laad", 3.7)
            cable = self._value_matrix_current("matrix_laad_kabel", 4.8)
        else:
            trafo = cable = 0.0
        set_current_values(self._value_current_spins(), (trafo, cable, 0, 0))
        self._value_unit_changed()
        self._value_household_changed()
        self._update_value_highest_preview()

    def _value_current_spins(self):
        return (self.value_trafo, self.value_cable, self.value_generation_trafo, self.value_generation_cable)

    def _value_household_changed(self, *_args):
        if not hasattr(self, "zero_current_page") or self.value_category_combo.currentData() != "Huishoudelijk":
            return
        self.value_manual_checkbox.setChecked(False)
        layer = self._layer_from_combo(self.value_layer_combo)
        features = list(layer.selectedFeatures()) if layer is not None else []
        context = self.zero_current_page._household_context()
        rows = [self.zero_current_page._household_currents(layer, feature, self.value_housing_combo.currentData(), context) for feature in features]
        set_current_values(self._value_current_spins(), [max(column) for column in zip(*rows)] if rows else (0, 0, 0, 0))
        self._update_value_highest_preview()

    def _value_manual_mode_changed(self, manual):
        if not manual:
            if self.value_category_combo.currentData() == "Huishoudelijk":
                self._value_household_changed()
            else:
                self._value_unit_changed()
        self._update_value_highest_preview()

    def _value_unit_changed(self, *_args):
        category = self.value_category_combo.currentData()
        key = self.value_unit_combo.currentData()
        self.value_manual_checkbox.setChecked(False)
        self.value_unit_note.setText(category_note(category, key) + "\nDe stroomwaarden volgen de ingestelde tabellen en kunnen hieronder worden aangepast.")
        currents = unit_currents(current_context(self), category, key, self.value_gas_combo.currentData())
        if currents is not None:
            set_current_values(self._value_current_spins(), currents)
        elif category != "Huishoudelijk" and key is None:
            self.value_manual_checkbox.setChecked(True)
        self._update_value_highest_preview()

    def _update_value_highest_preview(self, *_args):
        if not hasattr(self, "value_highest_preview"):
            return
        if self.value_category_combo.currentData() == "Huishoudelijk" and not self.value_manual_checkbox.isChecked():
            self.value_highest_preview.setText(
                "Hoogste Trafo en Hoogste Kabel worden per aansluiting berekend "
                "op basis van het gekozen woningtype en bouwjaar. De velden tonen het maximum "
                "in de selectie. Typ een waarde om je eigen vier waarden op te slaan."
            )
            return
        highest_trafo = max(self.value_trafo.value(), self.value_generation_trafo.value())
        highest_cable = max(self.value_cable.value(), self.value_generation_cable.value())
        self.value_highest_preview.setText(
            f"Voor alle geselecteerde aansluitingen: Hoogste Trafo {highest_trafo:.3f} A · "
            f"Hoogste Kabel {highest_cable:.3f} A"
        )

    def _refresh_value_selection_status(self, update_values=True):
        layer = self._layer_from_combo(self.value_layer_combo)
        selected = list(layer.selectedFeatures()) if layer is not None else []
        color = "#2e7d32" if selected else "#b54800"
        self.value_selection_label.setStyleSheet(
            f"color: {color}; font-weight: 700;"
        )
        self.value_selection_label.setText(
            f"Geselecteerde LS-aansluitingen: {len(selected)}"
        )
        if update_values and selected:
            loaded = []
            for field_name, spin in (
                ("Ontwerpstroom", self.value_trafo),
                ("Ontwerpstroom kabel", self.value_cable),
                ("Opwek ontwerpstroom", self.value_generation_trafo),
                ("Kabel opwek ontwerpstroom", self.value_generation_cable),
            ):
                values = []
                for feature in selected:
                    try:
                        values.append(float(feature[field_name]))
                    except (KeyError, TypeError, ValueError):
                        continue
                loaded.append(max(values) if values else 0.0)
            set_current_values(self._value_current_spins(), loaded)
            self.value_manual_checkbox.setChecked(all(has_manual_currents(feature) for feature in selected))
            self._update_value_highest_preview()
        return bool(selected)

    def show_station_page(self):
        from .algorithms.stations_selectie_tool import StationsSelectieAlgorithm

        preferred = StationsSelectieAlgorithm._default_layer()
        self._fill_layer_combo(
            self.station_layer_combo, self._vector_project_layers(), preferred
        )
        self.station_advanced_toggle.setChecked(False)
        self._refresh_station_fields()
        self._refresh_station_selection_status(True)
        self.page_stack.setCurrentWidget(self.station_page)
        self.setWindowTitle("LS Netontwerp Wizard – stations aanpassen")
        self.resize(920, 620)

    def _refresh_station_fields(self):
        values = self._workflow_field_defaults()
        layer = self._layer_from_combo(self.station_layer_combo)
        defaults = {
            "STATIONSNAAM_VELD": str(
                layer.customProperty(
                    "LSNetontwerp/station_name_field",
                    values.get("field_station_name", "Station"),
                )
            )
            if layer is not None
            else values.get("field_station_name", "Station"),
            "TRAFO_CAPACITEIT_VELD": str(
                layer.customProperty(
                    "LSNetontwerp/station_capacity_field",
                    values.get("field_station_capacity", "trafo_power"),
                )
            )
            if layer is not None
            else values.get("field_station_capacity", "trafo_power"),
            "MAX_STROOM_VELD": str(
                layer.customProperty("LSNetontwerp/station_max_field", "Max_A")
            )
            if layer is not None
            else "Max_A",
        }
        for key, combo in self.station_field_combos.items():
            previous = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            if layer is not None:
                combo.addItems([field.name() for field in layer.fields()])
            index = combo.findText(defaults[key])
            if index < 0 and previous:
                index = combo.findText(previous)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)
        self._refresh_station_selection_status(True)

    def _refresh_station_selection_status(self, update_value=True):
        from .algorithms.stations_selectie_tool import parse_station_kva

        layer = self._layer_from_combo(self.station_layer_combo)
        selected = list(layer.selectedFeatures()) if layer is not None else []
        color = "#2e7d32" if selected else "#b54800"
        self.station_selection_label.setStyleSheet(
            f"color: {color}; font-weight: 700;"
        )
        names = []
        name_field = self.station_field_combos[
            "STATIONSNAAM_VELD"
        ].currentText().strip()
        capacity_field = self.station_field_combos[
            "TRAFO_CAPACITEIT_VELD"
        ].currentText().strip()
        if selected and name_field:
            names = [
                str(feature[name_field] or "").strip()
                for feature in selected[:3]
                if str(feature[name_field] or "").strip()
            ]
        suffix = ""
        if names:
            suffix = ": " + ", ".join(names)
            if len(selected) > len(names):
                suffix += ", …"
        self.station_selection_label.setText(
            f"Geselecteerde bestaande stations: {len(selected)}{suffix}"
        )
        if update_value and selected and capacity_field:
            capacities = [
                parse_station_kva(feature[capacity_field]) for feature in selected
            ]
            capacities = [value for value in capacities if value is not None]
            if capacities:
                self.station_capacity.setValue(max(capacities))
        self._update_station_max_preview()
        return bool(selected)

    def _update_station_max_preview(self, *_args):
        maximum_current = self.station_capacity.value() / 0.23 / 3.0
        text = f"Max_A: {maximum_current:,.1f} A"
        text = text.replace(",", "X").replace(".", ",").replace("X", ".")
        self.station_max_preview.setText(text)

    def show_housing_page(self):
        from .algorithms.woningtype_selectie_herberekenen_tool import (
            WoningtypeSelectieHerberekenenAlgorithm,
        )

        preferred_housing, preferred_points = (
            WoningtypeSelectieHerberekenenAlgorithm._default_layers()
        )
        layers = self._vector_project_layers()
        self._fill_layer_combo(self.housing_layer_combo, layers, preferred_housing)
        self._fill_layer_combo(self.housing_points_combo, layers, preferred_points)
        self.housing_advanced_toggle.setChecked(False)
        self._refresh_housing_fields()
        self._refresh_housing_selection_status(True)
        self.page_stack.setCurrentWidget(self.housing_page)
        self.setWindowTitle("LS Netontwerp Wizard – woningtype aanpassen")
        self.resize(920, 650)

    def show_zero_current_page(self, _checked=False, select_first=True, review_layer=None):
        count = self.zero_current_page.refresh(select_first=select_first, review_layer=review_layer)
        self.page_stack.setCurrentWidget(self.zero_current_page)
        self.setWindowTitle("LS Netontwerp Wizard – nulwaarden herstellen")
        self.resize(1120, 720)
        if count == 0:
            self.zero_current_page.status_label.setText(
                "Er zijn geen aansluitingen met een ontbrekende of nulwaarde in "
                "Hoogste Trafo."
            )

    def _refresh_zero_current_count(self):
        if hasattr(self, "zero_current_page"):
            return self.zero_current_page.refresh()
        return 0

    def _workflow_field_defaults(self):
        values = dict((self.prepared_state or {}).get("values") or {})
        if values:
            return values
        state_file = str(
            QgsProject.instance().readEntry("LSNetontwerp", "state_file", "")[0]
        ).strip()
        try:
            if state_file:
                return dict(
                    json.loads(Path(state_file).read_text(encoding="utf-8")).get(
                        "values", {}
                    )
                )
        except (OSError, ValueError, TypeError):
            pass
        return {}

    def _refresh_housing_fields(self):
        values = self._workflow_field_defaults()
        housing = self._layer_from_combo(self.housing_layer_combo)
        points = self._layer_from_combo(self.housing_points_combo)
        configuration = (
            ("VELD_WONINGTYPE", housing, values.get("field_building_type", "Woningtype")),
            ("VELD_BOUWJAAR", housing, values.get("field_build_year", "bouwjaar")),
            (
                "VELD_DOORLAAT",
                points,
                values.get("field_passthrough", "service_connection_type_type"),
            ),
            ("VELD_GEBRUIK", points, values.get("field_usage", "Gebruiksdoel")),
            ("VELD_GAS", points, values.get("field_gas", "G_Type")),
        )
        for key, layer, default in configuration:
            combo = self.housing_field_combos[key]
            previous = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            if layer is not None:
                combo.addItems([field.name() for field in layer.fields()])
            index = combo.findText(default)
            if index < 0 and previous:
                index = combo.findText(previous)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)

    def _refresh_housing_selection_status(self, update_choice=False):
        housing = self._layer_from_combo(self.housing_layer_combo)
        selected = list(housing.selectedFeatures()) if housing is not None else []
        color = "#2e7d32" if selected else "#b54800"
        self.housing_selection_label.setStyleSheet(
            f"color: {color}; font-weight: 700;"
        )
        self.housing_selection_label.setText(
            f"Geselecteerde BAG-panden: {len(selected)}"
        )
        if update_choice and selected:
            field_name = self.housing_field_combos["VELD_WONINGTYPE"].currentText()
            if field_name:
                current_values = {
                    str(feature[field_name] or "").strip().casefold()
                    for feature in selected
                }
                if len(current_values) == 1:
                    index = self.housing_type_combo.findData(next(iter(current_values)))
                    if index >= 0:
                        self.housing_type_combo.setCurrentIndex(index)
        return bool(selected)

    @staticmethod
    def _gen_query_text():
        query_path = Path(__file__).resolve().parent / "assets" / "gen_query.txt"
        try:
            return query_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            return f"De meegeleverde GEN-query kon niet worden gelezen: {exc}"

    def _show_gen_information(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Informatie over invoer uit GEN")
        dialog.setWindowIcon(self.windowIcon())
        dialog.resize(780, 720)
        layout = QVBoxLayout(dialog)

        title = QLabel("GEN-bestanden voorbereiden")
        title.setObjectName("techbaseTitle")
        layout.addWidget(title)

        explanation = QLabel(
            "De XML- en Excelbestanden voor deze plugin zijn afkomstig uit GEN. "
            "Volg deze stappen voordat je stap 1 van de wizard start:<br><br>"
            "<b>1.</b> Teken in GEN een <i>trail</i> ruim om het volledige "
            "plangebied heen.<br>"
            "<b>2.</b> Voer de onderstaande query uit. De query gebruikt de "
            "getekende trail als ruimtelijke selectie.<br>"
            "<b>3.</b> Selecteer alle gevonden resultaten en kies "
            "<b>Exporteren als XML</b>.<br>"
            "<b>4.</b> Exporteer daarna dezelfde volledige selectie als "
            "<b>Excel</b>.<br>"
            "<b>5.</b> Zodra het Excelbestand geopend is, klik je vóór iedere "
            "andere handeling in Excel nogmaals op <b>Exporteren als Excel</b>. "
            "Kies dan de gewenste opslaglocatie. Zonder deze extra exportstap "
            "kan het geopende Excelbestand niet normaal worden opgeslagen."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        query_label = QLabel("GEN-query")
        query_label.setStyleSheet("color: #e66700; font-weight: 700; font-size: 13px;")
        layout.addWidget(query_label)
        query_text = self._gen_query_text()
        query_box = QTextEdit()
        query_box.setReadOnly(True)
        query_box.setPlainText(query_text)
        query_box.setFont(QFont("Consolas", 9))
        try:
            no_wrap = QTextEdit.LineWrapMode.NoWrap
        except AttributeError:
            no_wrap = QTextEdit.NoWrap
        query_box.setLineWrapMode(no_wrap)
        layout.addWidget(query_box, 1)

        button_row = QHBoxLayout()
        copied_label = QLabel("")
        copied_label.setStyleSheet("color: #388e3c; font-weight: 600;")
        copy_button = QPushButton("Query naar klembord kopiëren")

        def copy_query():
            QApplication.clipboard().setText(query_text)
            copied_label.setText("Query is gekopieerd.")

        copy_button.clicked.connect(copy_query)
        close_button = QPushButton("Sluiten")
        close_button.clicked.connect(dialog.accept)
        button_row.addWidget(copy_button)
        button_row.addWidget(copied_label)
        button_row.addStretch(1)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)
        dialog.exec()

    def _path_row(self, form, label, kind):
        row = QHBoxLayout()
        edit = QLineEdit()
        button = QPushButton("Kiezen…")
        if kind == "plan":
            self.plan_button = button
        button.clicked.connect(lambda: self._browse(edit, kind))
        row.addWidget(edit, 1)
        row.addWidget(button)
        form.addRow(label, row)
        return edit

    def _toggle_plan(self, without_plan):
        self.plan_edit.setEnabled(not without_plan)
        self.plan_button.setEnabled(not without_plan)
        self.widgets["only_plan"].setEnabled(not without_plan)

    def _browse(self, edit, kind):
        start = edit.text().strip() or str(Path.home())
        if kind == "xml":
            value, _ = QFileDialog.getOpenFileName(
                self, "Kies GEN XML", start, "XML (*.xml)"
            )
        elif kind == "excel":
            value, _ = QFileDialog.getOpenFileName(
                self, "Kies Excel", start, "Excel (*.xlsx *.xls);;CSV (*.csv)"
            )
        elif kind == "plan":
            value, _ = QFileDialog.getOpenFileName(
                self,
                "Kies plangebied",
                start,
                "Vectorlaag (*.gpkg *.shp *.geojson *.json)",
            )
        else:
            value = QFileDialog.getExistingDirectory(self, "Kies uitvoermap", start)
        if value:
            edit.setText(value)

    def _build_advanced(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        tabs = QTabWidget()
        self.advanced_tabs = tabs
        layout.addWidget(tabs)

        import_tab = QWidget()
        import_form = QFormLayout(import_tab)
        for key in ("sheet_cable", "sheet_joint", "sheet_connection"):
            self._add_text_option(import_form, key)
        self._add_bool_option(import_form, "use_3dbag")
        self._add_text_option(import_form, "plan_source_crs")
        tabs.addTab(import_tab, "Import en BAG")

        layer_tab = QWidget()
        layer_form = QFormLayout(layer_tab)
        for key in (
            "layer_points",
            "layer_main_cables",
            "layer_connection_cables",
            "layer_flat_cabinets",
            "layer_stations",
            "layer_station_enclosures",
            "layer_distribution_cabinets",
        ):
            self._add_text_option(layer_form, key)
        tabs.addTab(layer_tab, "Lagen")

        field_tab = QWidget()
        field_form = QFormLayout(field_tab)
        for key in (
            "field_passthrough",
            "field_usage",
            "field_gas",
            "field_building_type",
            "field_build_year",
            "field_design_current",
            "field_multistory",
            "field_flat_id",
            "field_main_function",
            "field_connection_function",
            "field_station_name",
            "field_station_capacity",
            "field_enclosure_station",
        ):
            self._add_text_option(field_form, key)
        tabs.addTab(field_tab, "Kolommen")

        calculation_tab = QWidget()
        calculation_form = QFormLayout(calculation_tab)
        for key in (
            "auto_cpu_threads",
            "default_apartment",
            "one_phase_exception",
            "node_trenches",
            "only_plan",
            "automatic_stations",
            "write_shapefiles",
        ):
            self._add_bool_option(calculation_form, key)
        for key in (
            "cpu_threads",
            "building_year_limit",
            "phase_limit",
            "amp_limit",
            "node_tolerance",
            "manual_station_count",
            "new_station_kva",
            "target_utilization",
            "max_route",
        ):
            self._add_number_option(calculation_form, key)
        self._add_text_option(calculation_form, "main_function_words")
        self._add_text_option(calculation_form, "connection_function_words")
        self._add_text_option(calculation_form, "bag_api_url")
        tabs.addTab(calculation_tab, "Berekening")

        tables_tab = self._build_design_tables()
        tabs.addTab(tables_tab, "Ontwerpstroomtabellen")

        scroll.setWidget(content)
        return scroll

    def _build_design_tables(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        note = QLabel(
            "Pas de rekenwaarden per categorie aan. Trafo, kabel en opwek hebben "
            "eigen tabellen. Selecteer een regel om die te kopiëren of te verplaatsen; "
            "met kopiëren en plakken kun je waarden ook in een spreadsheet bewerken."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        categories = QTabWidget()
        category_keys = (
            (
                "Wonen en opwek",
                (
                    "matrix_woonhuis",
                    "matrix_woonhuis_2022",
                    "matrix_woonhuis_kabel",
                    "matrix_woonhuis_kabel_2022",
                    "matrix_woonhuis_opwek",
                    "matrix_woonhuis_opwek_kabel",
                ),
            ),
            ("Ampère en typen", ("matrix_amp", "matrix_type")),
            (
                "Straat en laden",
                (
                    "matrix_straat",
                    "matrix_straat_kader31",
                    "matrix_laad",
                    "matrix_laad_kabel",
                ),
            ),
            ("Gas", ("matrix_gas", "matrix_gas_kabel")),
            ("Classificatie", ("matrix_regex", "matrix_keywords")),
        )
        for category_name, keys in category_keys:
            inner = QTabWidget()
            for key in keys:
                label, _headers, _default = DESIGN_MATRIX_OPTIONS[key]
                inner.addTab(self._matrix_editor(key), label)
            categories.addTab(inner, category_name)
        layout.addWidget(categories, 1)

        loose = QGroupBox("Aanvullende ontwerpstroominstellingen")
        loose_form = QFormLayout(loose)
        self._add_text_option(loose_form, "opwek_zero_ids")
        self._add_text_option(loose_form, "opwek_zero_text")
        self._add_number_option(loose_form, "fallback_laad")
        layout.addWidget(loose)
        return container

    def _matrix_editor(self, key):
        _label, headers, default = DESIGN_MATRIX_OPTIONS[key]
        container = QWidget()
        layout = QVBoxLayout(container)
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(list(headers))
        try:
            resize_mode = QHeaderView.ResizeMode.Stretch
        except AttributeError:
            resize_mode = QHeaderView.Stretch
        table.horizontalHeader().setSectionResizeMode(resize_mode)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setMinimumHeight(260)
        table.setToolTip("Dubbelklik op een cel om de waarde te wijzigen.")
        self._set_matrix_values(table, default)
        self.widgets[key] = table
        layout.addWidget(table, 1)
        row = QHBoxLayout()
        add_button = QPushButton("Regel toevoegen")
        add_button.clicked.connect(lambda _checked=False, t=table: self._add_matrix_row(t))
        duplicate_button = QPushButton("Regel dupliceren")
        duplicate_button.clicked.connect(
            lambda _checked=False, t=table: self._duplicate_matrix_row(t)
        )
        up_button = QPushButton("Omhoog")
        up_button.clicked.connect(
            lambda _checked=False, t=table: self._move_matrix_row(t, -1)
        )
        down_button = QPushButton("Omlaag")
        down_button.clicked.connect(
            lambda _checked=False, t=table: self._move_matrix_row(t, 1)
        )
        remove_button = QPushButton("Geselecteerde regel verwijderen")
        remove_button.clicked.connect(
            lambda _checked=False, t=table: self._remove_matrix_rows(t)
        )
        reset_button = QPushButton("Standaard herstellen")
        reset_button.clicked.connect(
            lambda _checked=False, t=table, values=default: self._set_matrix_values(
                t, values
            )
        )
        row.addWidget(add_button)
        row.addWidget(duplicate_button)
        row.addWidget(up_button)
        row.addWidget(down_button)
        row.addWidget(remove_button)
        row.addStretch(1)
        layout.addLayout(row)
        transfer = QHBoxLayout()
        copy_button = QPushButton("Tabel kopiëren")
        copy_button.clicked.connect(
            lambda _checked=False, t=table: self._copy_matrix(t)
        )
        paste_button = QPushButton("Tabel plakken")
        paste_button.clicked.connect(
            lambda _checked=False, t=table: self._paste_matrix(t)
        )
        for button in (copy_button, paste_button, reset_button):
            button.setObjectName("secondaryButton")
        transfer.addWidget(copy_button)
        transfer.addWidget(paste_button)
        transfer.addStretch(1)
        transfer.addWidget(reset_button)
        layout.addLayout(transfer)
        return container

    @staticmethod
    def _set_matrix_values(table, flat_values):
        columns = table.columnCount()
        rows = int(len(flat_values) / columns) if columns else 0
        table.setRowCount(rows)
        for row in range(rows):
            for column in range(columns):
                value = flat_values[row * columns + column]
                table.setItem(row, column, QTableWidgetItem(str(value)))

    @staticmethod
    def _add_matrix_row(table):
        table.insertRow(table.rowCount())
        for column in range(table.columnCount()):
            table.setItem(table.rowCount() - 1, column, QTableWidgetItem(""))
        table.selectRow(table.rowCount() - 1)

    @staticmethod
    def _selected_matrix_row(table):
        rows = sorted({index.row() for index in table.selectedIndexes()})
        return rows[0] if rows else None

    @classmethod
    def _duplicate_matrix_row(cls, table):
        source = cls._selected_matrix_row(table)
        if source is None:
            return
        target = source + 1
        values = [
            table.item(source, column).text() if table.item(source, column) else ""
            for column in range(table.columnCount())
        ]
        table.insertRow(target)
        for column, value in enumerate(values):
            table.setItem(target, column, QTableWidgetItem(value))
        table.selectRow(target)

    @classmethod
    def _move_matrix_row(cls, table, direction):
        source = cls._selected_matrix_row(table)
        if source is None:
            return
        target = source + direction
        if target < 0 or target >= table.rowCount():
            return
        for column in range(table.columnCount()):
            first = table.takeItem(source, column)
            second = table.takeItem(target, column)
            table.setItem(source, column, second or QTableWidgetItem(""))
            table.setItem(target, column, first or QTableWidgetItem(""))
        table.selectRow(target)

    @staticmethod
    def _remove_matrix_rows(table):
        selected_rows = sorted(
            {index.row() for index in table.selectedIndexes()}, reverse=True
        )
        for row in selected_rows:
            table.removeRow(row)

    @staticmethod
    def _copy_matrix(table):
        lines = []
        for row in range(table.rowCount()):
            lines.append("\t".join(
                table.item(row, column).text() if table.item(row, column) else ""
                for column in range(table.columnCount())
            ))
        QApplication.clipboard().setText("\n".join(lines))

    def _paste_matrix(self, table):
        rows = [line.split("\t") for line in QApplication.clipboard().text().splitlines()
                if line.strip()]
        if not rows or any(len(row) != table.columnCount() for row in rows):
            QMessageBox.warning(
                self, "Tabel plakken",
                f"Plak regels met precies {table.columnCount()} kolommen, gescheiden door tabs.",
            )
            return
        self._set_matrix_values(table, [value.strip() for row in rows for value in row])

    @staticmethod
    def _matrix_values(table):
        values = []
        for row in range(table.rowCount()):
            row_values = []
            for column in range(table.columnCount()):
                item = table.item(row, column)
                row_values.append(item.text().strip() if item is not None else "")
            if any(value != "" for value in row_values):
                values.extend(row_values)
        return values

    def _add_text_option(self, form, key):
        label, default = TEXT_OPTIONS[key]
        widget = QLineEdit(default)
        self.widgets[key] = widget
        form.addRow(label, widget)

    def _add_bool_option(self, form, key):
        label, default = BOOL_OPTIONS[key]
        widget = QCheckBox()
        widget.setChecked(default)
        self.widgets[key] = widget
        form.addRow(label, widget)

    def _add_number_option(self, form, key):
        label, default, minimum, maximum, decimals = NUMBER_OPTIONS[key]
        if decimals:
            widget = QDoubleSpinBox()
            widget.setDecimals(decimals)
        else:
            widget = QSpinBox()
        widget.setRange(minimum, maximum)
        widget.setValue(default)
        self.widgets[key] = widget
        form.addRow(label, widget)

    def _toggle_advanced(self, enabled):
        self.advanced_container.setVisible(enabled)
        for widget in (
            self.header_widget, self.intro_label, self.basic_group,
            self.status_label, self.actions_group,
        ):
            widget.setVisible(not enabled)
        self.advanced_hint.setVisible(enabled)
        if enabled:
            self.resize(max(self.width(), 1120), max(self.height(), 900))
        else:
            self.resize(1120, 700)

    def values(self):
        values = {
            "xml": self.xml_edit.text().strip(),
            "excel": self.excel_edit.text().strip(),
            "plan": "" if self.no_plan.isChecked() else self.plan_edit.text().strip(),
            "output": self.output_edit.text().strip(),
            "open_project": self.open_project.isChecked(),
            "design_framework": str(self.framework_combo.currentData() or "3.0"),
        }
        for key, widget in self.widgets.items():
            if isinstance(widget, QLineEdit):
                values[key] = widget.text().strip()
            elif isinstance(widget, QCheckBox):
                values[key] = widget.isChecked()
            elif isinstance(widget, QTableWidget):
                values[key] = self._matrix_values(widget)
            else:
                values[key] = widget.value()
        if not values["plan"]:
            values["only_plan"] = False
        if values["design_framework"] == "3.1":
            values["matrix_straat"] = list(values["matrix_straat_kader31"])
        return values

    def _restore_settings(self):
        self.xml_edit.setText(self.settings.value(self.SETTINGS_PREFIX + "xml", ""))
        self.excel_edit.setText(self.settings.value(self.SETTINGS_PREFIX + "excel", ""))
        self.plan_edit.setText(self.settings.value(self.SETTINGS_PREFIX + "plan", ""))
        self.no_plan.setChecked(
            str(self.settings.value(self.SETTINGS_PREFIX + "no_plan", "false")).lower()
            in ("true", "1")
        )
        self.output_edit.setText(self.settings.value(self.SETTINGS_PREFIX + "output", ""))
        framework = str(
            self.settings.value(self.SETTINGS_PREFIX + "design_framework", "3.0")
        )
        index = self.framework_combo.findData(framework)
        self.framework_combo.setCurrentIndex(index if index >= 0 else 0)

    def _save_settings(self, values):
        for key in ("xml", "excel", "plan", "output"):
            stored = self.plan_edit.text().strip() if key == "plan" else values[key]
            self.settings.setValue(self.SETTINGS_PREFIX + key, stored)
        self.settings.setValue(self.SETTINGS_PREFIX + "no_plan", self.no_plan.isChecked())
        self.settings.setValue(
            self.SETTINGS_PREFIX + "design_framework",
            str(values.get("design_framework", "3.0")),
        )

    def _restore_prepared_state(self):
        state_file = str(
            QgsProject.instance().readEntry(
                "LSNetontwerp", "state_file", ""
            )[0]
        ).strip()
        if not state_file or not Path(state_file).exists():
            return
        try:
            state = json.loads(Path(state_file).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return
        if state.get("status") not in (
            "ontwerpstroom_controleren",
            "clustering_bezig",
            "gereed",
        ):
            return
        self.prepared_state = state
        self.plan_edit.setText(str(state["values"].get("plan", "")))
        self.no_plan.setChecked(not bool(state.get("plan_gpkg")))
        from .clustering_options import CLUSTER_KEYS
        for key in CLUSTER_KEYS:
            if key not in state["values"] or key not in self.widgets:
                continue
            widget = self.widgets[key]
            if isinstance(widget, QCheckBox):
                widget.setChecked(state["values"][key])
            elif isinstance(widget, QLineEdit):
                widget.setText(str(state["values"][key]))
            else:
                widget.setValue(state["values"][key])
        self._upgrade_prepared_project_presentation()
        self.edit_values_button.setEnabled(True)
        self.edit_housing_button.setEnabled(True)
        self.edit_stations_button.setEnabled(True)
        self.station_names_button.setEnabled(True)
        self.new_buildings_button.setEnabled(True)
        self.cluster_button.setEnabled(True)
        self._refresh_zero_current_count()
        self.status_label.setText(
            "Ontwerpstroomcontrole hervat. Pas aansluitingen, woningtypen en "
            "bestaande stations aan en start daarna stap 3."
        )

    def _upgrade_prepared_project_presentation(self):
        """Herstel de laagweergave en stationsymbolen in oudere werkprojecten."""
        project = QgsProject.instance()
        try:
            current_version = int(
                project.readNumEntry(
                    "LSNetontwerp", "presentation_version", 0
                )[0]
            )
        except (TypeError, ValueError):
            current_version = 0
        from .project_presentation import PRESENTATION_VERSION, repair_generated_project
        if current_version >= PRESENTATION_VERSION:
            return

        if current_version >= 146:
            repair_generated_project(project)
            return

        layers = list(project.mapLayers().values())

        def by_property(property_name):
            return next(
                (
                    layer
                    for layer in layers
                    if bool(layer.customProperty(property_name, False))
                ),
                None,
            )

        def by_name(name):
            return next((layer for layer in layers if layer.name() == name), None)

        osm_layer = by_property("LSNetontwerp/osm_layer") or by_name(
            "OpenStreetMap"
        )
        review_layer = by_property("LSNetontwerp/review_current_layer") or by_name(
            "LS-aansluitingen ontwerpstroom"
        )
        plan_layer = by_property("LSNetontwerp/plan_layer") or by_name("Plangebied")
        housing_layer = by_name("Woningtypen BAG/3DBAG")
        connection_layer = by_name("Aansluitkabels (bron)")
        main_layer = by_name("Laagspanningskabels (bron)")
        station_layer = by_property("LSNetontwerp/review_station_layer") or by_name(
            "Bestaande stations (bron)"
        )

        try:
            from .workflow import WorkflowRunner

            if review_layer is not None:
                WorkflowRunner._style_review_connections(review_layer)
            if station_layer is not None:
                values = self._workflow_field_defaults()
                station_name_field = values.get("field_station_name", "Station")
                station_capacity_field = values.get(
                    "field_station_capacity", "trafo_power"
                )
                max_field = WorkflowRunner._ensure_station_max_current(
                    station_layer, station_capacity_field
                )
                WorkflowRunner._style_review_stations(
                    station_layer,
                    station_name_field,
                    station_capacity_field,
                    max_field,
                )
            WorkflowRunner._set_step_one_layer_visibility(
                (
                    osm_layer,
                    housing_layer,
                    review_layer,
                    station_layer,
                    connection_layer,
                    main_layer,
                    plan_layer,
                )
            )
            WorkflowRunner._set_step_one_render_order(
                (
                    station_layer,
                    review_layer,
                    plan_layer,
                    connection_layer,
                    main_layer,
                    housing_layer,
                ),
                osm_layer,
            )
            project.writeEntry(
                "LSNetontwerp", "presentation_version", PRESENTATION_VERSION
            )
            project.write()
        except Exception:
            # Een oud of handmatig gewijzigd project mag de wizard niet blokkeren.
            return

    def open_value_editor(self):
        self.show_value_page()

    def open_housing_editor(self):
        self.show_housing_page()

    def open_station_editor(self):
        self.show_station_page()

    def show_connection_sources_page(self):
        self.connection_sources_page.refresh()
        self.page_stack.setCurrentWidget(self.connection_sources_page)
        self.setWindowTitle("LS Netontwerp Wizard – nieuwbouw")

    def show_station_link_page(self):
        self.station_link_page.refresh()
        self.page_stack.setCurrentWidget(self.station_link_page)
        self.setWindowTitle("LS Netontwerp Wizard – stationskoppeling")

    def open_station_names_csv(self, target_layer=None):
        if not self.prepared_state and target_layer is None:
            QMessageBox.warning(
                self,
                "Ontwerpstroom ontbreekt",
                "Maak eerst de ontwerpstroomlaag met stap 1.",
            )
            return
        start = str(
            self.settings.value(self.SETTINGS_PREFIX + "station_names_csv", "")
        ).strip() or str(Path.home())
        csv_path, _ = QFileDialog.getOpenFileName(
            self,
            "Kies CSV met stationsnamen",
            start,
            "CSV (*.csv);;Alle bestanden (*.*)",
        )
        if not csv_path:
            return

        try:
            headers, _rows = read_station_csv(csv_path)
            key_column = find_master_asset_id_column(headers)
            if key_column is None:
                raise ValueError(
                    "De CSV bevat geen kolom 'Master Asset ID'."
                )
            name_column = guess_station_name_column(headers)
            if name_column is None:
                initial_index = 0
                name_column, accepted = QInputDialog.getItem(
                    self,
                    "Stationsnaamkolom kiezen",
                    "Welke CSV-kolom bevat de stationsnaam?",
                    headers,
                    initial_index,
                    False,
                )
                if not accepted:
                    return
            load_station_name_lookup(csv_path, name_column)

            review_layer = target_layer or next(
                (
                    layer
                    for layer in QgsProject.instance().mapLayers().values()
                    if bool(
                        layer.customProperty(
                            "LSNetontwerp/review_current_layer", False
                        )
                    )
                ),
                None,
            )
            if review_layer is None:
                review_layer = next(
                    (
                        layer
                        for layer in QgsProject.instance().mapLayers().values()
                        if layer.name() == "LS-aansluitingen ontwerpstroom"
                    ),
                    None,
                )
            if review_layer is None or not review_layer.isValid():
                raise ValueError(
                    "De laag 'LS-aansluitingen ontwerpstroom' is niet beschikbaar."
                )

            from .workflow import WorkflowRunner

            summary = WorkflowRunner._apply_station_names_from_csv(
                review_layer,
                {
                    "station_names_csv": csv_path,
                    "station_name_csv_field": name_column,
                },
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Stationsnamen niet gekoppeld",
                str(exc),
            )
            return

        self.settings.setValue(
            self.SETTINGS_PREFIX + "station_names_csv", csv_path
        )
        self.settings.setValue(
            self.SETTINGS_PREFIX + "station_name_csv_field", name_column
        )
        if QgsProject.instance().fileName():
            QgsProject.instance().write()
        if self.iface is not None:
            self.iface.mapCanvas().refresh()
        self.status_label.setText(
            f"Stationsnamen gekoppeld: {summary['matched']} van "
            f"{summary['layer_features']} aansluitingen."
        )
        QMessageBox.information(
            self,
            "Stationsnamen gekoppeld",
            f"Kolom '{name_column}' gekoppeld via '{key_column}'.\n\n"
            f"Gekoppeld: {summary['matched']} aansluitingen.\n"
            f"Niet gekoppeld: {summary['unmatched']} aansluitingen.",
        )

    @staticmethod
    def _append_unique_progress(details, message):
        text = str(message).strip()
        if not text:
            return
        lines = details.toPlainText().splitlines()
        if not lines or lines[-1] != text:
            details.appendPlainText(text)

    def _value_progress_update(self, percent, message):
        text = str(message).strip()
        self.value_progress_bar.setValue(max(0, min(100, int(percent))))
        self.value_progress_summary.setText(self._short_progress_message(text))
        self.value_progress_summary.setToolTip(text)
        self._append_unique_progress(self.value_progress_details, text)
        QApplication.processEvents()

    def _housing_progress_update(self, percent, message):
        text = str(message).strip()
        self.housing_progress_bar.setValue(max(0, min(100, int(percent))))
        self.housing_progress_summary.setText(self._short_progress_message(text))
        self.housing_progress_summary.setToolTip(text)
        self._append_unique_progress(self.housing_progress_details, text)
        QApplication.processEvents()

    @staticmethod
    def _set_page_status(label, message, error=False):
        color = "#c62828" if error else "#2e7d32"
        label.setStyleSheet(f"color: {color}; font-weight: 700;")
        label.setText(str(message))

    def run_station_edit(self):
        self._run_station_operation(False)

    def run_station_delete(self):
        layer = self._layer_from_combo(self.station_layer_combo)
        count = len(layer.selectedFeatureIds()) if layer is not None else 0
        if count < 1:
            self._set_page_status(
                self.station_status_label,
                "Selecteer eerst minimaal één bestaand station in de kaart.",
                True,
            )
            return
        reply = QMessageBox.question(
            self,
            "Stations verwijderen",
            f"Wil je {count} geselecteerde station(s) definitief uit de "
            "bronlaag verwijderen?\n\nDeze stations worden daarna niet in "
            "stap 3 gebruikt.",
        )
        try:
            yes_button = QMessageBox.StandardButton.Yes
        except AttributeError:
            yes_button = QMessageBox.Yes
        if reply == yes_button:
            self._run_station_operation(True)

    def _run_station_operation(self, deleting):
        layer = self._layer_from_combo(self.station_layer_combo)
        if layer is None or not layer.isValid():
            self._set_page_status(
                self.station_status_label, "Kies een geldige stationslaag.", True
            )
            return
        if not layer.selectedFeatureIds():
            self._set_page_status(
                self.station_status_label,
                "Selecteer eerst minimaal één bestaand station in de kaart.",
                True,
            )
            return
        fields = {
            key: combo.currentText().strip()
            for key, combo in self.station_field_combos.items()
        }
        if any(not value for value in fields.values()):
            self._set_page_status(
                self.station_status_label,
                "Kies bij Geavanceerde opties alle drie benodigde stationskolommen.",
                True,
            )
            return
        self.station_save_button.setEnabled(False)
        self.station_delete_button.setEnabled(False)
        self.station_home_button.setEnabled(False)
        action = "verwijderen" if deleting else "bijwerken"
        self._set_page_status(
            self.station_status_label, f"Geselecteerde stations {action}…"
        )
        feedback = InlineProcessingFeedback(
            lambda _percent, message: self._set_page_status(
                self.station_status_label, message
            )
        )
        try:
            result = processing.run(
                "lsnetontwerp:bestaande_stations_selectie",
                {
                    "STATIONS": layer,
                    **fields,
                    "NIEUWE_CAPACITEIT_KVA": self.station_capacity.value(),
                    "VERWIJDEREN": bool(deleting),
                },
                feedback=feedback,
            )
        except Exception as exc:
            self._set_page_status(
                self.station_status_label, f"Stationswijziging mislukt: {exc}", True
            )
        else:
            count = int(result.get("AANTAL", 0))
            if deleting:
                message = f"Gereed: {count} station(s) blijvend verwijderd."
            else:
                maximum_current = self.station_capacity.value() / 0.23 / 3.0
                message = (
                    f"Gereed: {count} station(s) ingesteld op "
                    f"{self.station_capacity.value():g} kVA; Max_A opnieuw "
                    f"berekend op {maximum_current:.1f} A."
                )
            self._set_page_status(self.station_status_label, message)
            layer.updateExtents()
            if self.iface is not None:
                self.iface.mapCanvas().refresh()
        finally:
            self.station_save_button.setEnabled(True)
            self.station_delete_button.setEnabled(True)
            self.station_home_button.setEnabled(True)
            self._refresh_station_selection_status(False)

    def run_value_edit(self):
        layer = self._layer_from_combo(self.value_layer_combo)
        if layer is None:
            self._set_page_status(
                self.value_status_label, "Kies een geldige aansluitingenlaag.", True
            )
            return
        if not layer.selectedFeatureIds():
            self._set_page_status(
                self.value_status_label,
                "Selecteer eerst minimaal één LS-aansluiting in de kaart.",
                True,
            )
            return
        category = self.value_category_combo.currentData()
        house_type = self.value_housing_combo.currentData()
        if category == "Huishoudelijk" and house_type is None:
            self._set_page_status(
                self.value_status_label, "Kies een woningtype.", True
            )
            return
        if category != "Huishoudelijk" and not self.value_manual_checkbox.isChecked() and max(
            self.value_trafo.value(), self.value_generation_trafo.value()
        ) <= 0:
            self._set_page_status(
                self.value_status_label,
                "Vul voor trafoverbruik of trafo-opwek een waarde groter dan 0 A in.",
                True,
            )
            return
        self.value_progress_group.setVisible(True)
        self.value_progress_details.clear()
        self.value_run_button.setEnabled(False)
        self.value_home_button.setEnabled(False)
        self._value_progress_update(10, "Geselecteerde ontwerpstroomwaarden opslaan…")
        try:
            count = self.zero_current_page.apply_values_to_layer(
                layer,
                layer.selectedFeatureIds(),
                category,
                {
                    "consumption_trafo": self.value_trafo.value(),
                    "consumption_cable": self.value_cable.value(),
                    "generation_trafo": self.value_generation_trafo.value(),
                    "generation_cable": self.value_generation_cable.value(),
                },
                house_type,
                unit_name=unit_description(category, self.value_unit_combo.currentData()) if category != "Huishoudelijk" else None,
                gas_category=self.value_gas_combo.currentData() if category == "Zakelijk" else None,
                manual_override=self.value_manual_checkbox.isChecked(),
            )
        except Exception as exc:
            self._value_progress_update(0, f"Wijziging mislukt: {exc}")
            self._set_page_status(
                self.value_status_label, f"Wijziging mislukt: {exc}", True
            )
        else:
            self._value_progress_update(100, "Ontwerpstroomwaarden opgeslagen.")
            self._set_page_status(
                self.value_status_label,
                f"Gereed: {count} aansluiting(en) blijvend aangepast als {category}; "
                "verbruik, opwek en hoogste stromen zijn opgeslagen.",
            )
            if self.iface is not None:
                self.iface.mapCanvas().refresh()
            self._refresh_zero_current_count()
        finally:
            self.value_run_button.setEnabled(True)
            self.value_home_button.setEnabled(True)
            self._refresh_value_selection_status(False)

    def run_housing_edit(self):
        housing = self._layer_from_combo(self.housing_layer_combo)
        points = self._layer_from_combo(self.housing_points_combo)
        if housing is None or points is None:
            self._set_page_status(
                self.housing_status_label,
                "Kies een geldige woningtypen- en aansluitingenlaag.",
                True,
            )
            return
        if not housing.selectedFeatureIds():
            self._set_page_status(
                self.housing_status_label,
                "Selecteer eerst minimaal één BAG-pand in de kaart.",
                True,
            )
            return
        fields = {
            key: combo.currentText().strip()
            for key, combo in self.housing_field_combos.items()
        }
        if any(not value for value in fields.values()):
            self._set_page_status(
                self.housing_status_label,
                "Kies bij Geavanceerde opties alle vijf benodigde kolommen.",
                True,
            )
            return
        self.housing_progress_group.setVisible(True)
        self.housing_progress_details.clear()
        self.housing_run_button.setEnabled(False)
        self.housing_home_button.setEnabled(False)
        self._housing_progress_update(10, "Woningtype en ontwerpstroom bijwerken…")
        feedback = InlineProcessingFeedback(self._housing_progress_update)
        self._active_feedback = feedback
        try:
            result = processing.run(
                "lsnetontwerp:woningtype_selectie_herberekenen",
                {
                    "WONINGEN": housing,
                    "AANSLUITINGEN": points,
                    **fields,
                    "NIEUW_WONINGTYPE": self.housing_type_combo.currentIndex(),
                },
                feedback=feedback,
            )
        except Exception as exc:
            self._housing_progress_update(0, f"Wijziging mislukt: {exc}")
            self._set_page_status(
                self.housing_status_label, f"Wijziging mislukt: {exc}", True
            )
        else:
            self._housing_progress_update(100, "Woningtype en ontwerpstroom bijgewerkt.")
            buildings = int(result.get("AANTAL_WONINGEN", 0))
            connections = int(result.get("AANTAL_AANSLUITINGEN", 0))
            self._set_page_status(
                self.housing_status_label,
                f"Gereed: {buildings} pand(en) gewijzigd en {connections} "
                "aansluiting(en) opnieuw berekend.",
            )
            if self.iface is not None:
                self.iface.mapCanvas().refresh()
            self._refresh_zero_current_count()
        finally:
            self._active_feedback = None
            self.housing_run_button.setEnabled(True)
            self.housing_home_button.setEnabled(True)
            self._refresh_housing_selection_status(False)

    def open_cluster_editor(self):
        """Show manual correction inside the branded wizard."""
        self.show_manual_page(False)

    def open_free_cluster_editor(self):
        """Show the same page with Advanced and unrestricted mode active."""
        self.show_manual_page(True)

    def _manual_progress_update(self, percent, message):
        full_message = str(message).strip()
        self.manual_progress_bar.setValue(max(0, min(100, int(percent))))
        self.manual_progress_summary.setText(
            self._short_progress_message(full_message)
        )
        self.manual_progress_summary.setToolTip(full_message)
        if full_message:
            existing = self.manual_progress_details.toPlainText().splitlines()
            if not existing or existing[-1] != full_message:
                self.manual_progress_details.appendPlainText(full_message)
        QApplication.processEvents()

    def _cancel_manual_progress(self):
        if self._active_feedback is not None:
            self._active_feedback.cancel()
        self.manual_progress_summary.setText(
            "Annuleren zodra de huidige netwerkstap stopt…"
        )
        self.manual_cancel_button.setEnabled(False)

    def _set_manual_status(self, message, error=False):
        color = "#c62828" if error else "#2e7d32"
        self.manual_status_label.setStyleSheet(
            f"color: {color}; font-weight: 700;"
        )
        self.manual_status_label.setText(str(message))

    def run_manual_correction(self):
        """Run the correction without opening QGIS' Processing dialog."""
        self._refresh_manual_selection_status()
        layers = {
            key: self._manual_selected_layer(key)
            for key in self.manual_layer_combos
        }
        required = (
            "AANSLUITINGEN",
            "STATIONS",
            "GEBIEDEN",
            "KABELROUTES",
            "SLEUVEN",
        )
        missing = [key for key in required if layers[key] is None]
        if missing:
            self._set_manual_status(
                "Kies eerst alle verplichte resultaatlagen. Ontbrekend: "
                + ", ".join(missing),
                True,
            )
            return
        if not layers["AANSLUITINGEN"].selectedFeatureIds():
            self._set_manual_status(
                "Selecteer eerst minimaal één aansluiting in de kaart.", True
            )
            return
        if len(layers["STATIONS"].selectedFeatureIds()) != 1:
            self._set_manual_status(
                "Selecteer precies één doelstation in de kaart.", True
            )
            return

        backup_folder = self.manual_backup_edit.text().strip()
        if not backup_folder:
            project_home = QgsProject.instance().homePath()
            if not project_home:
                self._set_manual_status(
                    "Kies bij Geavanceerde opties een map voor back-up en resultaatkopie.",
                    True,
                )
                return
            backup_folder = str(Path(project_home) / "handmatige_correcties")
            self.manual_backup_edit.setText(backup_folder)

        allow_all = self.manual_allow_all.isChecked()
        parameters = {
            "AANSLUITINGEN": layers["AANSLUITINGEN"],
            "STATIONS": layers["STATIONS"],
            "GEBIEDEN": layers["GEBIEDEN"],
            "KABELROUTES": layers["KABELROUTES"],
            "SLEUVEN": layers["SLEUVEN"],
            "PLANGEBIED": layers["PLANGEBIED"],
            "HELE_BRONCLUSTER_VERWIJDEREN": self.manual_remove_cluster.isChecked(),
            "ALLES_TOESTAAN": allow_all,
            "MAX_ROUTE_M": self.manual_max_route.value(),
            "KNOOP_TOLERANTIE_M": self.manual_node_tolerance.value(),
            "BACKUPMAP": backup_folder,
        }
        for key, checkbox in self.manual_safety_checks.items():
            parameters[key] = checkbox.isChecked() and not allow_all

        self.manual_progress_group.setVisible(True)
        self.manual_progress_details.clear()
        self.manual_progress_bar.setValue(0)
        self.manual_cancel_button.setVisible(True)
        self.manual_cancel_button.setEnabled(True)
        self.manual_run_button.setEnabled(False)
        self.manual_home_button.setEnabled(False)
        self._set_manual_status("Handmatige correctie wordt berekend…")
        feedback = InlineProcessingFeedback(self._manual_progress_update)
        self._active_feedback = feedback
        try:
            result = processing.run(
                "lsnetontwerp:handmatige_clustercorrectie_selectie",
                parameters,
                feedback=feedback,
            )
        except Exception as exc:
            self._manual_progress_update(
                self.manual_progress_bar.value(), f"Correctie mislukt: {exc}"
            )
            self._set_manual_status(f"Correctie mislukt: {exc}", True)
        else:
            self._manual_progress_update(100, "Correctie volledig verwerkt.")
            moved = int(result.get("VERPLAATST_AANTAL", 0))
            station = result.get("DOELSTATION", "het doelstation")
            self._set_manual_status(
                f"Gereed: {moved} aansluiting(en) verplaatst naar {station}. "
                "Gebieden, routes en statistieken zijn bijgewerkt."
            )
            if self.iface is not None:
                self.iface.mapCanvas().refresh()
        finally:
            self._active_feedback = None
            self.manual_cancel_button.setVisible(False)
            self.manual_run_button.setEnabled(True)
            self.manual_home_button.setEnabled(True)
            self._refresh_manual_selection_status()

    def _cancel_progress(self):
        self._progress_cancel_requested = True
        self.progress_summary.setText("Annuleren zodra de huidige bewerking stopt…")
        self.progress_cancel_button.setEnabled(False)

    @staticmethod
    def _short_progress_message(message):
        text = " ".join(str(message).split())
        if len(text) <= 105:
            return text
        return text[:102].rstrip() + "…"

    def _make_progress(self, text):
        self._progress_cancel_requested = False
        self._last_progress_detail = None
        self.progress_group.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_cancel_button.setVisible(True)
        self.progress_cancel_button.setEnabled(True)
        self.progress_details.clear()
        self.progress_summary.setText(self._short_progress_message(text))
        self.progress_summary.setToolTip(str(text))
        self.status_label.setText(self._short_progress_message(text))
        self.resize(max(self.width(), 940), max(self.height(), 620))
        QApplication.processEvents()

        def update(percent, message):
            full_message = str(message).strip()
            short_message = self._short_progress_message(full_message)
            self.progress_bar.setValue(max(0, min(100, int(percent))))
            self.progress_summary.setText(short_message)
            self.progress_summary.setToolTip(full_message)
            self.status_label.setText(short_message)
            if full_message and full_message != self._last_progress_detail:
                self.progress_details.appendPlainText(full_message)
                self._last_progress_detail = full_message
            QApplication.processEvents()
            if self._progress_cancel_requested:
                raise RuntimeError("Geannuleerd door gebruiker")

        return update

    def _finish_progress(self, value=None):
        if value is not None:
            self.progress_bar.setValue(max(0, min(100, int(value))))
        self.progress_cancel_button.setVisible(False)
        QApplication.processEvents()

    def run_preparation(self):
        values = self.values()
        missing = [
            label
            for key, label in (
                ("xml", "GEN XML"),
                ("excel", "Excel"),
                ("output", "Uitvoermap"),
            )
            if not values[key]
        ]
        if missing:
            QMessageBox.warning(
                self, "Invoer ontbreekt", "Kies eerst: " + ", ".join(missing)
            )
            return
        for key in ("xml", "excel") + (("plan",) if values["plan"] else ()):
            if not Path(values[key]).exists():
                QMessageBox.warning(
                    self, "Bestand ontbreekt", f"Niet gevonden: {values[key]}"
                )
                return
        self._save_settings(values)
        if self.iface is not None:
            try:
                created = self.iface.newProject(True)
            except TypeError:
                created = self.iface.newProject()
            if created is False:
                return
        update = self._make_progress("Workflow voorbereiden…")
        self.run_button.setEnabled(False)
        self.station_names_button.setEnabled(False)
        self.new_buildings_button.setEnabled(False)

        try:
            from .workflow import WorkflowRunner

            state = WorkflowRunner(values, update).prepare()
        except Exception as exc:
            self._finish_progress()
            QMessageBox.critical(self, "Workflow mislukt", str(exc))
            self.status_label.setText(f"Mislukt: {exc}")
        else:
            self._finish_progress(55)
            self.prepared_state = state
            self.edit_values_button.setEnabled(True)
            self.edit_housing_button.setEnabled(True)
            self.edit_stations_button.setEnabled(True)
            self.station_names_button.setEnabled(True)
            self.new_buildings_button.setEnabled(True)
            self.cluster_button.setEnabled(True)
            review_layer = next(
                (
                    layer
                    for layer in QgsProject.instance().mapLayers().values()
                    if bool(
                        layer.customProperty(
                            "LSNetontwerp/review_current_layer", False
                        )
                    )
                ),
                None,
            )
            if review_layer is not None and self.iface is not None:
                self.iface.setActiveLayer(review_layer)
                plan_layer = next(
                    (
                        layer
                        for layer in QgsProject.instance().mapLayers().values()
                        if bool(
                            layer.customProperty(
                                "LSNetontwerp/plan_layer", False
                            )
                        )
                    ),
                    None,
                )
                extent_layer = plan_layer or review_layer
                self.iface.mapCanvas().setExtent(extent_layer.extent())
                self.iface.mapCanvas().refresh()
            zero_count = self._refresh_zero_current_count()
            self.status_label.setText(
                "Ontwerpstroom gereed. Pas stroomwaarden aan met 2a of wijzig "
                "geselecteerde BAG-woningen met 2b. Bestaande stations wijzig "
                "of verwijder je met 2c; herstel eventuele nulwaarden met 2d "
                "en start daarna stap 3."
            )
            if zero_count:
                zero_message = (
                    f"Aansluitingen zonder ontwerpstroom: {zero_count}.\n"
                    "Gebruik '2d. Nulwaarden herstellen' om ze te bekijken, naar de "
                    "kaart te zoomen en handmatig te categoriseren.\n\n"
                )
            else:
                zero_message = (
                    "Geen aansluitingen met een ontbrekende of nulwaarde in "
                    "Hoogste Trafo gevonden.\n\n"
                )
            info_message = (
                "Het QGIS-werkproject en de ontwerpstroomlaag zijn gereed.\n\n"
                "Stationsnamen toevoegen is optioneel: gebruik daarvoor "
                "'1.2. Stationskoppeling' en '1.3. Nieuwbouw'.\n\n"
                "Stroomwaarde handmatig wijzigen:\n"
                "1. Selecteer één of meer aansluitingen.\n"
                "2. Gebruik '2a. Stroom aanpassen'.\n\n"
                "Woningtype corrigeren en automatisch herberekenen:\n"
                "1. Selecteer één of meer panden in 'Woningtypen BAG/3DBAG'.\n"
                "2. Gebruik '2b. Woningtype aanpassen'.\n"
                "3. Kies het juiste woningtype.\n\n"
                "Bestaande stations wijzigen of verwijderen:\n"
                "1. Selecteer één of meer rode stationsvierkanten.\n"
                "2. Gebruik '2c. Stations aanpassen'.\n"
                "3. Sla een nieuwe kVA-waarde op of verwijder de selectie.\n\n"
                + zero_message
                + "Herhaal de correcties zo vaak als nodig en klik daarna op "
                "'Clustering maken'.\n\n"
                "Kies bij stap 3 de ontwerpstroomkolom, het plangebied en de grenzen.\n\n"
                + f"Werkproject:\n{state['work_project']}"
            )
            QMessageBox.information(self, "Ontwerpstroom controleren", info_message)
            if zero_count:
                self.show_zero_current_page(select_first=True)
        finally:
            self.run_button.setEnabled(True)

    def open_clustering_options(self):
        if not self.prepared_state:
            self._restore_prepared_state()
        if not self.prepared_state:
            QMessageBox.warning(self, "Ontwerpstroom ontbreekt", "Voer eerst stap 1 uit of open het eerder gemaakte werkproject.")
            return
        try:
            from .clustering_options import ClusteringOptionsDialog
            options = ClusteringOptionsDialog(self)
            options.exec()
            if options.start_requested:
                self.run_clustering()
        except Exception as exc:
            QMessageBox.critical(self, "Clusteringinstellingen", str(exc))

    def run_clustering(self):
        if not self.prepared_state:
            QMessageBox.warning(
                self,
                "Ontwerpstroom ontbreekt",
                "Voer eerst stap 1 uit of open het eerder gemaakte werkproject.",
            )
            return
        update = self._make_progress("Clustering voorbereiden…")
        self.run_button.setEnabled(False)
        self.edit_values_button.setEnabled(False)
        self.edit_housing_button.setEnabled(False)
        self.edit_stations_button.setEnabled(False)
        self.station_names_button.setEnabled(False)
        self.new_buildings_button.setEnabled(False)
        self.cluster_button.setEnabled(False)
        try:
            from .workflow import WorkflowRunner

            result = WorkflowRunner(
                self.prepared_state["values"], update
            ).cluster(self.prepared_state)
        except Exception as exc:
            self._finish_progress()
            QMessageBox.critical(self, "Clustering mislukt", str(exc))
            self.status_label.setText(f"Mislukt: {exc}")
            self.edit_values_button.setEnabled(True)
            self.edit_housing_button.setEnabled(True)
            self.edit_stations_button.setEnabled(True)
            self.station_names_button.setEnabled(True)
            self.new_buildings_button.setEnabled(True)
            self.cluster_button.setEnabled(True)
        else:
            self._finish_progress(100)
            self.status_label.setText(f"Gereed: {result['result_dir']}")
            self.cluster_button.setEnabled(True)
            self.station_names_button.setEnabled(False)
            self.new_buildings_button.setEnabled(False)
            QMessageBox.information(
                self,
                "LS-netontwerp gereed",
                "De clustering is gereed.\n\n"
                "Voor handmatige correcties:\n"
                "1. Selecteer aansluitingen in 'Aansluitingen geclusterd'.\n"
                "2. Selecteer precies één doelstation in 'Stations ontwerp'.\n"
                "3. Klik in dit venster op '4. Clustering aanpassen'. De bekende "
                "resultaatlagen worden automatisch ingevuld.\n\n"
                f"Resultaatmap:\n{result['result_dir']}\n\n"
                f"QGIS-project:\n{result['project']}",
            )
        finally:
            self.run_button.setEnabled(True)
