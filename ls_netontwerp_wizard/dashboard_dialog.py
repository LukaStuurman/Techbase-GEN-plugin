"""Laatste QGIS 3/4 UI-afwerking voor het centrale workflowdashboard."""

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from qgis.PyQt.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .themed_dialog import LSNetontwerpDashboardDialog as _ThemedDashboardDialog


THREEDBAG_CAPABILITIES_URL = (
    "https://data.3dbag.nl/api/BAG3D/wfs?"
    "service=WFS&request=GetCapabilities&version=2.0.0"
)


class LSNetontwerpDashboardDialog(_ThemedDashboardDialog):
    """Dashboard met robuuste compacte invoer- en voortgangsweergave."""

    def __init__(self, iface, parent=None):
        super().__init__(iface, parent)
        self._fix_input_browse_buttons()
        self._fix_compact_progress()
        self._rename_manual_clustering_route()

    def _fix_input_browse_buttons(self):
        """Geef invoervelden en Kiezen-knoppen genoeg hoogte en breedte."""
        for group in self.main_page.findChildren(QGroupBox):
            if group.title() != "Benodigde invoer":
                continue

            group.setMinimumHeight(188)
            group.setMaximumHeight(198)
            layout = group.layout()
            if layout is not None:
                layout.setContentsMargins(8, 8, 8, 9)
                layout.setVerticalSpacing(6)
                layout.setHorizontalSpacing(9)

            for edit in (
                self.xml_edit,
                self.excel_edit,
                self.plan_edit,
                self.output_edit,
            ):
                edit.setMinimumHeight(31)
                edit.setMaximumHeight(33)

            for button in group.findChildren(QPushButton):
                button.setMinimumHeight(31)
                button.setMaximumHeight(33)
                button.setMinimumWidth(96)
                button.setStyleSheet(
                    "QPushButton {"
                    "background:#f47700; color:white; border:0; border-radius:5px; "
                    "padding:4px 12px; font-weight:600;"
                    "}"
                    "QPushButton:hover {background:#ff8b1a;}"
                    "QPushButton:pressed {background:#d85f00;}"
                    "QPushButton:disabled {background:#d8d8d8; color:#777777;}"
                )
            break

    def _fix_compact_progress(self):
        """Eén compacte voortgangsweergave met de stopknop naast de balk."""
        # De oude losse statusregel dupliceerde de tekst die al in het compacte
        # voortgangsvak staat.
        self.status_label.setVisible(False)
        self.status_label.setMaximumHeight(0)

        progress_layout = self.progress_group.layout()
        if progress_layout is None:
            return

        # De oorspronkelijke layout heeft bovenaan een rij met tekst + knop en
        # daaronder de voortgangsbalk. Haal de knop uit de tekstregel en zet hem
        # echt in dezelfde horizontale rij als de balk.
        top_item = progress_layout.itemAt(0)
        top_layout = top_item.layout() if top_item is not None else None
        if top_layout is not None:
            top_layout.removeWidget(self.progress_cancel_button)

        progress_layout.removeWidget(self.progress_bar)
        bar_row = QHBoxLayout()
        bar_row.setContentsMargins(0, 0, 0, 0)
        bar_row.setSpacing(6)
        bar_row.addWidget(self.progress_bar, 1)

        # QGIS 4 tekent de knop optisch een paar pixels lager dan de smalle balk.
        # Een klein houdertje met ondermarge trekt de knop circa 2 px omhoog,
        # zonder negatieve marges of platformafhankelijke geometrie-trucs.
        cancel_holder = QWidget()
        cancel_holder_layout = QVBoxLayout(cancel_holder)
        cancel_holder_layout.setContentsMargins(0, 0, 0, 4)
        cancel_holder_layout.setSpacing(0)
        cancel_holder_layout.addWidget(self.progress_cancel_button)
        bar_row.addWidget(cancel_holder, 0)
        progress_layout.insertLayout(1, bar_row)

        button = self.progress_cancel_button
        button.setText("✕")
        button.setToolTip("Huidige stap stoppen")
        button.setMinimumSize(24, 24)
        button.setMaximumSize(24, 24)
        button.setStyleSheet(
            "QPushButton {"
            "background:#C62828; color:white; border:1px solid #9F1F1F; "
            "border-radius:5px; padding:0px; font-size:15px; font-weight:900;"
            "}"
            "QPushButton:hover {background:#E53935; border-color:#B71C1C;}"
            "QPushButton:pressed {background:#B71C1C;}"
            "QPushButton:disabled {background:#D7A3A3; color:#F5E4E4; border-color:#D7A3A3;}"
        )

        # De balk zelf blijft dun. De compacte groep houdt voldoende ruimte voor
        # de 24 px stopknop zonder de werkstappen erboven samen te drukken.
        self.progress_group.setMaximumHeight(62)
        progress_layout.setContentsMargins(7, 4, 7, 5)
        progress_layout.setSpacing(3)
        self.progress_summary.setMinimumHeight(17)
        self.progress_summary.setMaximumHeight(17)
        self.progress_bar.setMinimumHeight(10)
        self.progress_bar.setMaximumHeight(10)

    @staticmethod
    def _three_d_bag_server_status():
        """Voer een korte WFS-capabilitiescontrole uit vóór stap 1."""
        request = Request(
            THREEDBAG_CAPABILITIES_URL,
            headers={
                "Accept": "application/xml,text/xml,*/*",
                "User-Agent": "LS-Netontwerp-Wizard/1.15",
            },
        )
        try:
            with urlopen(request, timeout=5) as response:
                status = int(getattr(response, "status", 200) or 200)
                # Lees slechts een klein deel: we willen bereikbaarheid toetsen,
                # niet de volledige capabilities in het geheugen laden.
                response.read(512)
            if 200 <= status < 400:
                return True, ""
            return False, f"HTTP-status {status}"
        except HTTPError as exc:
            return False, f"HTTP {exc.code}"
        except URLError as exc:
            reason = getattr(exc, "reason", exc)
            return False, str(reason)
        except (TimeoutError, OSError) as exc:
            return False, str(exc)

    def run_preparation(self):
        """Start stap 1 met een expliciete 3DBAG-offlinekeuze."""
        try:
            values = self.values()
        except Exception:
            # Laat de bestaande validatie/foutafhandeling verantwoordelijk zijn
            # als het uitlezen van de invoer zelf al mislukt.
            return super().run_preparation()

        if not bool(values.get("use_3dbag", False)):
            return super().run_preparation()

        reachable, reason = self._three_d_bag_server_status()
        if reachable:
            return super().run_preparation()

        message = (
            "3DBAG LoD 2.2 is aangevinkt, maar de 3DBAG-server kan momenteel "
            "niet worden bereikt.\n\n"
            "Wil je stap 1 direct verder uitvoeren zonder de 3DBAG LoD 2.2-"
            "controle? De gewone BAG-woningtypen worden dan wel gewoon verwerkt."
        )
        if reason:
            message += f"\n\nTechnische melding: {reason}"

        reply = QMessageBox.question(
            self,
            "3DBAG LoD 2.2 niet bereikbaar",
            message,
        )
        try:
            yes_button = QMessageBox.StandardButton.Yes
        except AttributeError:  # QGIS 3 / PyQt5
            yes_button = QMessageBox.Yes
        if reply != yes_button:
            return

        use_3dbag_widget = self.widgets.get("use_3dbag")
        if use_3dbag_widget is not None and hasattr(use_3dbag_widget, "setChecked"):
            use_3dbag_widget.setChecked(False)

        self.progress_summary.setText("3DBAG overgeslagen; stap 1 start met BAG-data")
        self.progress_summary.setToolTip(
            "3DBAG LoD 2.2 was niet bereikbaar en is voor deze uitvoering uitgezet."
        )
        QApplication.processEvents()
        return super().run_preparation()

    def _rename_manual_clustering_route(self):
        """Maak in het dashboard duidelijk dat 3b zelf de clustering afrondt."""
        if self._dashboard_widget is None:
            return
        for button in self._dashboard_widget.findChildren(QPushButton):
            if button.text().startswith("3b."):
                button.setText("3b. Handmatige clustering maken")
                button.setToolTip(
                    "Deel alle aansluitingen handmatig in, plaats de stations en "
                    "maak daarna direct de volledige clustering zonder extra "
                    "automatische stations."
                )
                break

    def _open_visual_cluster_editor(self, requested_mode):
        super()._open_visual_cluster_editor(requested_mode)
        editor = self._dashboard_visual_cluster_dialog
        if editor is None or requested_mode != "prepare":
            return

        editor.pre_group.setTitle("2C. Handmatige clusterindeling")
        editor.mode_label.setText(
            "<b>Modus: volledige handmatige clustering.</b> Selecteer alle "
            "aansluitingen en deel ze in bij H-xx-clusters met de gewenste "
            "stationslocaties en kVA. Als 100% is ingedeeld, klik je hieronder "
            "op <b>Handmatige clustering uitvoeren</b>. Stap 3b bouwt dan zelf "
            "de resultaatlagen, routes en gebieden en past jouw indeling toe."
        )

        if not hasattr(editor, "dashboard_manual_cluster_button"):
            editor.dashboard_manual_cluster_button = QPushButton(
                "Handmatige clustering uitvoeren"
            )
            editor.dashboard_manual_cluster_button.setToolTip(
                "Maak de volledige clustering met exact de voorbereide H-xx-indeling"
            )
            editor.dashboard_manual_cluster_button.clicked.connect(
                self._run_manual_clustering_from_editor
            )
            pre_layout = editor.pre_group.layout()
            if pre_layout is not None:
                pre_layout.addRow("", editor.dashboard_manual_cluster_button)

    @staticmethod
    def _manual_coverage(editor):
        layer = editor.source_connections
        if layer is None:
            return 0, 0
        field_index = layer.fields().lookupField("GebiedLabel")
        total = int(layer.featureCount())
        if field_index < 0:
            return 0, total
        manual = sum(
            1
            for feature in layer.getFeatures()
            if editor.MANUAL_LABEL_RE.fullmatch(
                str(feature.attribute(field_index) or "").strip()
            )
        )
        return manual, total

    def _show_manual_editor_again(self):
        editor = self._dashboard_visual_cluster_dialog
        if editor is None:
            return
        editor.refresh_layers()
        self.page_stack.setCurrentWidget(editor)
        self.setWindowTitle("LS Netontwerp Wizard – handmatige clustering")

    def _run_manual_clustering_from_editor(self):
        """Rond 3b af zonder dat de gebruiker daarna nog 3a hoeft te starten."""
        editor = self._dashboard_visual_cluster_dialog
        if editor is None:
            return
        if not self.prepared_state:
            QMessageBox.warning(
                self,
                "Ontwerpstroom ontbreekt",
                "Voer eerst stap 1 uit of open het eerder gemaakte werkproject.",
            )
            return

        manual, total = self._manual_coverage(editor)
        if total <= 0:
            QMessageBox.warning(
                self,
                "Geen aansluitingen",
                "Er zijn geen bron-aansluitingen gevonden voor de handmatige clustering.",
            )
            return
        if manual != total:
            QMessageBox.warning(
                self,
                "Handmatige indeling nog niet compleet",
                f"Er zijn {manual} van {total} aansluitingen handmatig ingedeeld.\n\n"
                "Voor 3b moeten alle aansluitingen aan een H-xx-cluster zijn "
                "gekoppeld. Deel eerst de resterende aansluitingen in.",
            )
            return

        reply = QMessageBox.question(
            self,
            "Handmatige clustering uitvoeren",
            f"Alle {total} aansluitingen zijn handmatig ingedeeld.\n\n"
            "Stap 3b maakt nu de volledige resultaatlagen, kabelroutes en "
            "clustergebieden. Er worden geen extra automatische stations "
            "aangemaakt en de H-xx-indeling wordt daarna automatisch exact "
            "toegepast.\n\nDoorgaan?",
        )
        try:
            yes_button = QMessageBox.StandardButton.Yes
        except AttributeError:  # QGIS 3 / PyQt5
            yes_button = QMessageBox.Yes
        if reply != yes_button:
            return

        # 3b gebruikt dezelfde stabiele route-/resultaatopbouw als stap 3a,
        # maar schakelt het automatisch toevoegen van stations uit. De H-xx-
        # toedeling wordt na het opbouwen automatisch exact afgedwongen.
        values = self.prepared_state.get("values", {})
        previous = {
            "automatic_stations": values.get("automatic_stations", True),
            "manual_station_count": values.get("manual_station_count", 0),
            "open_project": values.get("open_project", True),
        }
        values["automatic_stations"] = False
        values["manual_station_count"] = 0
        values["open_project"] = True
        self.open_project.setChecked(True)

        self.page_stack.setCurrentWidget(self.main_page)
        self.setWindowTitle("LS Netontwerp Wizard – handmatige clustering uitvoeren")
        update = self._make_progress("Handmatige clustering opbouwen…")
        self.run_button.setEnabled(False)
        self.edit_values_button.setEnabled(False)
        self.edit_housing_button.setEnabled(False)
        self.edit_stations_button.setEnabled(False)
        self.cluster_button.setEnabled(False)
        editor.dashboard_manual_cluster_button.setEnabled(False)
        QApplication.processEvents()

        try:
            from .workflow import WorkflowRunner

            result = WorkflowRunner(values, update).cluster(self.prepared_state)
        except Exception as exc:
            for key, value in previous.items():
                values[key] = value
            self._finish_progress()
            QMessageBox.critical(self, "Handmatige clustering mislukt", str(exc))
            self.edit_values_button.setEnabled(True)
            self.edit_housing_button.setEnabled(True)
            self.edit_stations_button.setEnabled(True)
            self.cluster_button.setEnabled(True)
            editor.dashboard_manual_cluster_button.setEnabled(True)
            self._show_manual_editor_again()
            return

        self._finish_progress(100)
        self.prepared_state = None

        # Het resultaatproject is hierboven bewust geopend, zodat de visuele
        # editor de zojuist gemaakte resultaatlagen direct kan vinden en alle
        # H-xx-keuzes automatisch kan afdwingen.
        editor.refresh_layers()
        if editor.mode != "result":
            QMessageBox.warning(
                self,
                "Resultaat gereed, handmatige toedeling niet toegepast",
                "De clustering is gemaakt, maar de resultaatlagen konden niet "
                "automatisch in de visuele editor worden gevonden. Open het "
                "resultaatproject en gebruik 4b om de indeling te controleren.",
            )
            self.show_home_page()
            return

        editor.enforce_prepared_clusters()
        editor.refresh_layers()
        self.page_stack.setCurrentWidget(editor)
        self.setWindowTitle("LS Netontwerp Wizard – handmatige clustering gereed")
        editor.dashboard_manual_cluster_button.setEnabled(False)
        QMessageBox.information(
            self,
            "Handmatige clustering gereed",
            "Stap 3b is volledig afgerond. De resultaatlagen, routes en gebieden "
            "zijn gemaakt en de voorbereide H-xx-clusters zijn automatisch "
            "toegepast.\n\n"
            f"Resultaatmap:\n{result['result_dir']}\n\n"
            f"QGIS-project:\n{result['project']}",
        )
        self.run_button.setEnabled(True)
