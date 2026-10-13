"""Laatste waarschuwingen, kaartselecties en consistente submenu-UX."""

from qgis.PyQt.QtCore import QTimer, Qt
from qgis.PyQt.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsVectorLayer

from .dashboard_dialog import LSNetontwerpDashboardDialog as _DashboardDialog
from .ui_theme import apply_theme, install_dialog_theme, normalize_page


BAG3D_WFS_URL = "https://data.3dbag.nl/api/BAG3D/wfs"
BAG3D_LOD22_TYPENAME = "BAG3D:lod22"
BAG3D_CRS_AUTHID = "EPSG:28992"


class LSNetontwerpDashboardDialog(_DashboardDialog):
    """Dashboard met 3b-achtige kaartselectie en consistente subpagina's."""

    def __init__(self, iface, parent=None):
        self._submenu_selection_layer = None
        self._submenu_selection_handler = None
        self._submenu_selection_page = None
        super().__init__(iface, parent)
        self._install_area_shape_mode()
        self._install_submenu_consistency()
        self._install_uniform_ui()

    def _install_uniform_ui(self):
        self._ui_pages = (
            self.main_page, self.value_page, self.housing_page, self.station_page,
            self.zero_current_page, self.connection_sources_page, self.manual_page,
            self.network_page, self.areas_page,
        )
        action_sets = (
            (self.value_page, (self.value_run_button,)),
            (self.housing_page, (self.housing_run_button,)),
            (self.station_page, (self.station_delete_button, self.station_save_button)),
            (self.zero_current_page, (self.zero_current_page.apply_button,)),
            (self.connection_sources_page, ()),
            (self.manual_page, (self.manual_run_button,)),
            (self.network_page, (self.network_draw_button, self.network_refresh_button, self.network_selected_refresh_button)),
            (self.areas_page, (self.areas_create_button, self.areas_draw_button)),
        )
        for page, actions in action_sets:
            normalize_page(page, self, actions)
        close = next((button for button in self.main_page.findChildren(QPushButton) if button.text() == "Sluiten"), None)
        normalize_page(self.main_page, self, (close,) if close is not None else (), home=False)
        apply_theme(self)
        install_dialog_theme(self)

    def show_connection_sources_page(self):
        self._prepare_fixed_subpage(self.connection_sources_page)
        return super().show_connection_sources_page()

    def _toggle_advanced(self, enabled):
        super()._toggle_advanced(enabled)
        self.header_widget.show()
        self.advanced_hint.setText("Geavanceerde instellingen · schakel Geavanceerde opties uit om de ontwerpstappen te starten.")
        self.advanced_container.setMinimumHeight(650 if enabled else 0)

    def _fix_compact_progress(self):
        """Zet de rode stopknop bewust iets hoger dan de smalle voortgangsbalk."""
        self.status_label.setVisible(False)
        self.status_label.setMaximumHeight(0)

        progress_layout = self.progress_group.layout()
        if progress_layout is None:
            return

        top_item = progress_layout.itemAt(0)
        top_layout = top_item.layout() if top_item is not None else None
        if top_layout is not None:
            top_layout.removeWidget(self.progress_cancel_button)

        progress_layout.removeWidget(self.progress_bar)

        try:
            align_vcenter = Qt.AlignmentFlag.AlignVCenter
            align_top = Qt.AlignmentFlag.AlignTop
        except AttributeError:  # QGIS 3 / PyQt5
            align_vcenter = Qt.AlignVCenter
            align_top = Qt.AlignTop

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

        bar_row = QHBoxLayout()
        bar_row.setContentsMargins(0, 0, 0, 0)
        bar_row.setSpacing(6)
        bar_row.addWidget(self.progress_bar, 1, align_vcenter)

        # De 24 px knop staat bewust circa 4 px hoger dan het midden van de
        # 10 px voortgangsbalk. Dit sluit visueel beter aan in QGIS 4.2.
        cancel_holder = QWidget(self.progress_group)
        cancel_holder.setFixedSize(24, 32)
        cancel_layout = QVBoxLayout(cancel_holder)
        cancel_layout.setContentsMargins(0, 0, 0, 8)
        cancel_layout.setSpacing(0)
        cancel_layout.addWidget(button, 0, align_top)
        bar_row.addWidget(cancel_holder, 0, align_vcenter)
        progress_layout.insertLayout(1, bar_row)

        self.progress_group.setMaximumHeight(62)
        progress_layout.setContentsMargins(7, 3, 7, 3)
        progress_layout.setSpacing(2)
        self.progress_summary.setMinimumHeight(17)
        self.progress_summary.setMaximumHeight(17)
        self.progress_bar.setMinimumHeight(10)
        self.progress_bar.setMaximumHeight(10)

    # ------------------------------------------------------------------
    # 3b als UX-patroon voor de andere subpagina's
    # ------------------------------------------------------------------

    @staticmethod
    def _group_by_title(page, title):
        if page is None:
            return None
        for group in page.findChildren(QGroupBox):
            if group.title() == title:
                return group
        return None

    def _replace_close_with_home(self, page):
        """Gebruik net als 3b één Home-knop rechtsonder in plaats van Sluiten."""
        if page is None:
            return
        for button in page.findChildren(QPushButton):
            if button.text().strip() != "Sluiten":
                continue
            try:
                button.clicked.disconnect()
            except (TypeError, RuntimeError):
                pass
            button.setText("←  Home")
            button.setToolTip("Terug naar het hoofdscherm")
            button.clicked.connect(self.show_home_page)

    def _hide_header_home_buttons(self):
        """3b heeft Home onderaan; gebruik die positie voortaan overal."""
        for attribute in (
            "value_home_button",
            "housing_home_button",
            "station_home_button",
            "zero_current_home_button",
            "manual_home_button",
            "network_home_button",
            "areas_home_button",
        ):
            button = getattr(self, attribute, None)
            if button is not None:
                button.setVisible(False)
                button.setMaximumWidth(0)

    def _insert_lasso_button(self, group, text, callback, tooltip):
        if group is None or group.layout() is None:
            return None
        button = QPushButton(text)
        button.setToolTip(tooltip)
        button.clicked.connect(callback)
        layout = group.layout()
        # De statuslabel blijft links staan; de kaartactie komt vóór de oude
        # vernieuwknop zodat dezelfde volgorde als in 3b ontstaat.
        insert_at = max(1, layout.count() - 1)
        try:
            layout.insertWidget(insert_at, button)
        except AttributeError:
            layout.addWidget(button)
        return button

    def _install_submenu_consistency(self):
        """Maak 2a/2b/2c/4a/5/6 visueel en functioneel gelijk aan 3b."""
        self._hide_header_home_buttons()
        for page in (
            self.value_page,
            self.housing_page,
            self.station_page,
            self.zero_current_page,
            self.manual_page,
            self.network_page,
            self.areas_page,
        ):
            self._replace_close_with_home(page)

        # Nummering en compacte taakvolgorde volgens 3b: eerst selecteren,
        # daarna de bewerking/instelling uitvoeren.
        value_selection = self._group_by_title(self.value_page, "Kaartselectie")
        housing_selection = self._group_by_title(self.housing_page, "Kaartselectie")
        station_selection = self._group_by_title(self.station_page, "Kaartselectie")
        manual_selection = self._group_by_title(self.manual_page, "Kaartselectie")
        value_values = self._group_by_title(self.value_page, "Nieuwe waarden")
        housing_choice = self._group_by_title(self.housing_page, "Nieuw woningtype")
        station_value = self._group_by_title(self.station_page, "Nieuwe stationswaarde")
        manual_options = self._group_by_title(self.manual_page, "Normale modus")

        if value_selection is not None:
            value_selection.setTitle("1. Aansluitingen selecteren")
        if housing_selection is not None:
            housing_selection.setTitle("1. BAG-panden selecteren")
        if station_selection is not None:
            station_selection.setTitle("1. Stations selecteren")
        if manual_selection is not None:
            manual_selection.setTitle("1. Aansluitingen en doelstation selecteren")
        if value_values is not None:
            value_values.setTitle("2. Nieuwe ontwerpstroomwaarden")
        if housing_choice is not None:
            housing_choice.setTitle("2. Nieuw woningtype")
        if station_value is not None:
            station_value.setTitle("2. Nieuwe stationswaarde")
        if manual_options is not None:
            manual_options.setTitle("2. Correctie-opties")
        if hasattr(self, "areas_shape_group"):
            self.areas_shape_group.setTitle("2. Gebiedsvorm")

        self.value_lasso_button = self._insert_lasso_button(
            value_selection,
            "Aansluitingen met lasso selecteren",
            self._lasso_value_connections,
            "Verberg de wizard tijdelijk en teken vrij rond de gewenste aansluitingen",
        )
        self.housing_lasso_button = self._insert_lasso_button(
            housing_selection,
            "Panden met lasso selecteren",
            self._lasso_housing,
            "Verberg de wizard tijdelijk en teken vrij rond de BAG-panden die je wilt aanpassen",
        )
        self.station_lasso_button = self._insert_lasso_button(
            station_selection,
            "Stations met lasso selecteren",
            self._lasso_stations,
            "Verberg de wizard tijdelijk en teken vrij rond één of meer bestaande stations",
        )
        self.manual_lasso_button = self._insert_lasso_button(
            manual_selection,
            "Aansluitingen met lasso selecteren",
            self._lasso_manual_connections,
            "Gebruik dezelfde vrije-handselectie als in 3b",
        )
        self.manual_station_pick_button = self._insert_lasso_button(
            manual_selection,
            "Doelstation aanklikken",
            self._pick_manual_station,
            "Verberg de wizard en klik precies één doelstation aan, zoals in 3b",
        )

        self._install_network_lasso()
        self._install_area_lasso()

    def _install_network_lasso(self):
        root = self.network_page.layout()
        if root is None or hasattr(self, "network_lasso_button"):
            return
        group = QGroupBox("1. Routes selecteren")
        row = QHBoxLayout(group)
        self.network_selection_label = QLabel(
            "Selecteer met de lasso routes wanneer je alleen geselecteerde clusters wilt verversen."
        )
        self.network_selection_label.setWordWrap(True)
        self.network_lasso_button = QPushButton("Routes met lasso selecteren")
        self.network_lasso_button.clicked.connect(self._lasso_network_routes)
        row.addWidget(self.network_selection_label, 1)
        row.addWidget(self.network_lasso_button)
        insert_at = root.indexOf(self.network_advanced_toggle)
        if insert_at < 0:
            insert_at = 2
        root.insertWidget(insert_at, group)
        self.network_selection_group = group

    def _install_area_lasso(self):
        root = self.areas_page.layout()
        if root is None or hasattr(self, "areas_lasso_button"):
            return
        label = self.areas_selection_label
        insert_at = root.indexOf(label)
        if insert_at < 0:
            insert_at = 2
        root.removeWidget(label)
        group = QGroupBox("1. Gebieden selecteren")
        row = QHBoxLayout(group)
        self.areas_lasso_button = QPushButton("Gebieden met lasso selecteren")
        self.areas_lasso_button.setToolTip(
            "Selecteer vrij twee aangrenzende clustergebieden voor het verleggen van hun grens"
        )
        self.areas_lasso_button.clicked.connect(self._lasso_areas)
        row.addWidget(label, 1)
        row.addWidget(self.areas_lasso_button)
        root.insertWidget(insert_at, group)
        self.areas_selection_group = group

    def _disconnect_submenu_selection(self):
        layer = self._submenu_selection_layer
        handler = self._submenu_selection_handler
        if layer is not None and handler is not None:
            try:
                layer.selectionChanged.disconnect(handler)
            except (TypeError, RuntimeError):
                pass
        self._submenu_selection_layer = None
        self._submenu_selection_handler = None
        self._submenu_selection_page = None

    def _restore_submenu_after_selection(self, page, refresh_callback=None):
        self._disconnect_submenu_selection()
        if page is not None:
            page.show()
            self.page_stack.setCurrentWidget(page)
        if refresh_callback is not None:
            try:
                refresh_callback()
            except TypeError:
                refresh_callback(False)
        self.show()
        self.raise_()
        self.activateWindow()
        self.page_stack.update()
        if page is not None:
            page.update()
            page.repaint()
        QApplication.processEvents()

    def _start_submenu_map_selection(
        self,
        page,
        layer,
        refresh_callback,
        status_label,
        status_text,
        single_click=False,
    ):
        """Zelfde selectieflow als 3b: kaart vrijgeven en automatisch terugkomen."""
        if self.iface is None:
            QMessageBox.warning(
                self,
                "Kaartselectie niet beschikbaar",
                "Deze selectie vereist QGIS Desktop.",
            )
            return
        if layer is None or not layer.isValid():
            QMessageBox.warning(
                self,
                "Laag ontbreekt",
                "De laag voor deze kaartselectie kon niet worden gevonden.",
            )
            return

        self._disconnect_submenu_selection()
        self.iface.setActiveLayer(layer)
        layer.removeSelection()
        action = self.iface.actionSelect() if single_click else self.iface.actionSelectFreehand()
        if action is None:
            QMessageBox.warning(
                self,
                "Selectietool niet beschikbaar",
                "De benodigde QGIS-selectietool is in deze QGIS-versie niet beschikbaar.",
            )
            return

        def selection_finished(*_args):
            # Een QGIS-selectiesignaal kan meer dan één keer worden uitgezonden.
            # Ontkoppel direct en herstel de submenu-pagina één keer.
            try:
                layer.selectionChanged.disconnect(selection_finished)
            except (TypeError, RuntimeError):
                pass
            self._submenu_selection_layer = None
            self._submenu_selection_handler = None
            QTimer.singleShot(
                0,
                lambda: self._restore_submenu_after_selection(
                    page, refresh_callback
                ),
            )

        self._submenu_selection_layer = layer
        self._submenu_selection_handler = selection_finished
        self._submenu_selection_page = page
        layer.selectionChanged.connect(selection_finished)
        if status_label is not None:
            status_label.setText(status_text)
        action.trigger()
        self.hide()

    def _lasso_value_connections(self):
        layer = self._layer_from_combo(self.value_layer_combo)
        self._start_submenu_map_selection(
            self.value_page,
            layer,
            lambda: self._refresh_value_selection_status(True),
            self.value_status_label,
            "Teken nu in de kaart rond de aansluitingen die je wilt aanpassen.",
        )

    def _lasso_housing(self):
        layer = self._layer_from_combo(self.housing_layer_combo)
        self._start_submenu_map_selection(
            self.housing_page,
            layer,
            lambda: self._refresh_housing_selection_status(True),
            self.housing_status_label,
            "Teken nu in de kaart rond de BAG-panden die je wilt aanpassen.",
        )

    def _lasso_stations(self):
        layer = self._layer_from_combo(self.station_layer_combo)
        self._start_submenu_map_selection(
            self.station_page,
            layer,
            lambda: self._refresh_station_selection_status(True),
            self.station_status_label,
            "Teken nu in de kaart rond de bestaande stations die je wilt aanpassen.",
        )

    def _lasso_manual_connections(self):
        layer = self._manual_selected_layer("AANSLUITINGEN")
        self._start_submenu_map_selection(
            self.manual_page,
            layer,
            self._refresh_manual_selection_status,
            self.manual_status_label,
            "Teken nu in de kaart rond de aansluitingen die je naar een ander cluster wilt verplaatsen.",
        )

    def _pick_manual_station(self):
        layer = self._manual_selected_layer("STATIONS")
        self._start_submenu_map_selection(
            self.manual_page,
            layer,
            self._refresh_manual_selection_status,
            self.manual_status_label,
            "Klik nu precies één doelstation aan.",
            single_click=True,
        )

    def _lasso_network_routes(self):
        layer = self._network_selected_layer("KABELROUTES")

        def refresh():
            count = len(layer.selectedFeatureIds()) if layer is not None else 0
            self.network_selection_label.setText(
                f"Geselecteerde kabelroutes: {count}. Gebruik daarna 'Geselecteerde routes verversen'."
            )

        self._start_submenu_map_selection(
            self.network_page,
            layer,
            refresh,
            self.network_status_label,
            "Teken nu in de kaart rond de kabelroutes/clusters die je wilt verversen.",
        )

    def _lasso_areas(self):
        layer = self._areas_selected_layer()
        self._start_submenu_map_selection(
            self.areas_page,
            layer,
            self._refresh_areas_selection_status,
            self.areas_status_label,
            "Teken nu in de kaart rond precies twee aangrenzende gebieden.",
        )

    def _prepare_fixed_subpage(self, page):
        if page is not None:
            page.show()
            page.setUpdatesEnabled(True)

    def show_value_page(self):
        self._prepare_fixed_subpage(self.value_page)
        return super().show_value_page()

    def show_housing_page(self):
        self._prepare_fixed_subpage(self.housing_page)
        return super().show_housing_page()

    def show_station_page(self):
        self._prepare_fixed_subpage(self.station_page)
        return super().show_station_page()

    def show_zero_current_page(self, _checked=False, select_first=True):
        self._prepare_fixed_subpage(self.zero_current_page)
        return super().show_zero_current_page(_checked, select_first)

    def show_manual_page(self, unrestricted=False):
        self._prepare_fixed_subpage(self.manual_page)
        return super().show_manual_page(unrestricted)

    def show_network_page(self):
        self._prepare_fixed_subpage(self.network_page)
        result = super().show_network_page()
        if hasattr(self, "network_selection_label"):
            layer = self._network_selected_layer("KABELROUTES")
            count = len(layer.selectedFeatureIds()) if layer is not None else 0
            self.network_selection_label.setText(
                f"Geselecteerde kabelroutes: {count}. Lasso selecteren is beschikbaar."
            )
        return result

    def show_areas_page(self):
        self._prepare_fixed_subpage(self.areas_page)
        return super().show_areas_page()

    def _open_visual_cluster_editor(self, requested_mode):
        """Heropen 3b/4b altijd als schone zichtbare stacked-widgetpagina."""
        result = super()._open_visual_cluster_editor(requested_mode)
        editor = self._dashboard_visual_cluster_dialog
        if editor is not None:
            apply_theme(editor)
            editor.setUpdatesEnabled(True)
            editor.show()
            self.page_stack.setCurrentWidget(editor)
            editor.updateGeometry()
            editor.update()
            editor.repaint()
            QApplication.processEvents()
        return result

    def _hard_home_repaint(self):
        if self.page_stack.currentWidget() is not self.main_page:
            return
        layout = self.main_page.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()
        self.main_page.updateGeometry()
        self.page_stack.updateGeometry()
        self.main_page.update()
        self.page_stack.update()
        self.main_page.repaint()
        self.page_stack.repaint()
        self.update()
        self.repaint()
        QApplication.processEvents()

    def show_home_page(self):
        """Wis de vorige subpagina echt uit de backing store vóór Home verschijnt."""
        self._disconnect_submenu_selection()
        current = self.page_stack.currentWidget()
        editor = getattr(self, "_dashboard_visual_cluster_dialog", None)

        self.page_stack.setUpdatesEnabled(False)
        try:
            if current is not None and current is not self.main_page:
                current.setUpdatesEnabled(False)
                current.hide()

            # 3b/4b is een ingebedde QDialog en gaf in QGIS 4 het sterkste
            # ghosting-effect. Verwijder die instantie volledig op Home; bij de
            # volgende opening wordt hij schoon opnieuw opgebouwd.
            if editor is not None:
                try:
                    editor._disconnect_signals()
                except (AttributeError, TypeError, RuntimeError):
                    pass
                self.page_stack.removeWidget(editor)
                editor.hide()
                editor.setParent(None)
                editor.deleteLater()
                self._dashboard_visual_cluster_dialog = None

            super().show_home_page()
            self.main_page.show()
            self.main_page.setUpdatesEnabled(True)
        finally:
            self.page_stack.setUpdatesEnabled(True)
            if current is not None and current is not self.main_page and current is not editor:
                current.setUpdatesEnabled(True)

        # Eén repaint is op QGIS 4/Windows soms onvoldoende. Doe direct en na
        # twee event-loopmomenten nogmaals zodat oude submenu-pixels verdwijnen.
        self._hard_home_repaint()
        QTimer.singleShot(0, self._hard_home_repaint)
        QTimer.singleShot(35, self._hard_home_repaint)
        QTimer.singleShot(100, self._hard_home_repaint)

    # ------------------------------------------------------------------
    # 3DBAG
    # ------------------------------------------------------------------

    @staticmethod
    def _three_d_bag_server_status():
        """Test exact dezelfde QGIS WFS-laag die stap 1 zelf gebruikt."""
        uri = (
            "pagingEnabled='true' "
            "pageSize='10000' "
            "restrictToRequestBBOX='1' "
            f"srsname='{BAG3D_CRS_AUTHID}' "
            f"typename='{BAG3D_LOD22_TYPENAME}' "
            f"url='{BAG3D_WFS_URL}' "
            "version='2.0.0'"
        )
        try:
            layer = QgsVectorLayer(uri, "3DBAG LoD 2.2 bereikbaarheidstest", "WFS")
            if not layer.isValid():
                try:
                    provider_error = str(layer.error().message()).strip()
                except Exception:
                    provider_error = ""
                reason = provider_error or (
                    f"QGIS kan {BAG3D_LOD22_TYPENAME} niet openen via "
                    f"{BAG3D_WFS_URL}"
                )
                return False, reason

            provider = layer.dataProvider()
            if provider is None or not provider.isValid():
                return False, "De QGIS WFS-provider voor 3DBAG is niet geldig."

            fields = layer.fields()
            field_names = {field.name().casefold() for field in fields}
            if "identificatie" not in field_names:
                return False, (
                    "De 3DBAG WFS opent wel, maar het verwachte veld "
                    "'identificatie' ontbreekt."
                )
            return True, ""
        except Exception as exc:
            return False, str(exc)

    # ------------------------------------------------------------------
    # Stap 6 – minimale vertices
    # ------------------------------------------------------------------

    def _install_area_shape_mode(self):
        """Toon minimale vertices als normale stap-6-keuze, niet alleen in Advanced."""
        root = self.areas_page.layout()
        if root is None:
            return

        group = QGroupBox("Gebiedsvorm")
        form = QFormLayout(group)
        self.areas_shape_mode = QComboBox()
        self.areas_shape_mode.addItem(
            "Minimale vertices – schuine grenzen toegestaan",
            "min_vertices",
        )
        self.areas_shape_mode.addItem(
            "Rechte blokken – 90°-hoeken waar mogelijk",
            "right_angles",
        )
        self.areas_shape_mode.setToolTip(
            "Minimale vertices kiest binnen de maximale tolerantie de geldige "
            "topologische dekking met het laagste aantal hoekpunten. Iedere "
            "aansluiting blijft in het gebied van zijn eigen cluster."
        )
        form.addRow("Vereenvoudigingsmodus", self.areas_shape_mode)
        note = QLabel(
            "Bij minimale vertices mogen gedeelde grenzen schuin lopen. De totale "
            "buitenrand blijft behouden en aansluitingen mogen nooit buiten hun "
            "eigen clustergebied vallen."
        )
        note.setWordWrap(True)
        form.addRow("", note)

        insert_index = root.indexOf(self.areas_advanced_toggle)
        if insert_index < 0:
            insert_index = 2
        root.insertWidget(insert_index, group)
        self.areas_shape_group = group

        self.areas_right_angles.setVisible(False)
        self.areas_shape_mode.currentIndexChanged.connect(
            self._sync_area_shape_mode
        )
        self._sync_area_shape_mode()

    def _sync_area_shape_mode(self, *_args):
        mode = str(self.areas_shape_mode.currentData() or "min_vertices")
        right_angles = mode == "right_angles"
        self.areas_right_angles.setChecked(right_angles)
        self.areas_min_width.setEnabled(right_angles)
        self.areas_junction_tolerance.setEnabled(right_angles)
        if right_angles:
            self.areas_create_button.setText("Rechte clustergebieden maken")
            self.areas_tolerance.setToolTip(
                "Maximale geometrische afwijking bij het vereenvoudigen van de gebieden."
            )
        else:
            self.areas_create_button.setText("Gebieden met minimale vertices maken")
            self.areas_tolerance.setToolTip(
                "Maximale afwijking waarbinnen de tool zoekt naar de geldige "
                "dekking met het laagste totale aantal vertices."
            )

    def run_area_simplification(self):
        """Gebruik de gekozen vormmodus en toon het vertexresultaat duidelijk."""
        minimal_vertices = (
            str(self.areas_shape_mode.currentData() or "") == "min_vertices"
        )
        super().run_area_simplification()
        if not minimal_vertices:
            return
        status = self.areas_status_label.text().strip()
        if not status.startswith("Gereed:"):
            return
        result_layer = self._areas_selected_layer()
        total_vertices = None
        if result_layer is not None:
            vertex_index = result_layer.fields().lookupField("Vertices")
            if vertex_index >= 0:
                total_vertices = sum(
                    int(feature.attribute(vertex_index) or 0)
                    for feature in result_layer.getFeatures()
                )
        vertex_text = (
            f" met in totaal {total_vertices} vertices"
            if total_vertices is not None
            else " met zo weinig mogelijk vertices"
        )
        self._set_areas_status(
            "Gereed: de clustergebieden zijn topologisch vereenvoudigd"
            f"{vertex_text}. Schuine gedeelde grenzen zijn toegestaan waar dat "
            "hoekpunten bespaart; alle aansluitingen zijn binnen hun eigen "
            "clustergebied gecontroleerd."
        )

    # ------------------------------------------------------------------
    # Stap 1 – 3DBAG-fallback
    # ------------------------------------------------------------------

    def _run_base_preparation(self):
        """Start de oorspronkelijke stap 1 zonder de oudere 3DBAG-precheck opnieuw te doen."""
        return super(_DashboardDialog, self).run_preparation()

    def run_preparation(self):
        """Start stap 1 en bied bij een onbruikbare 3DBAG WFS direct een BAG-fallback."""
        try:
            values = self.values()
        except Exception:
            return self._run_base_preparation()

        if not bool(values.get("use_3dbag", False)):
            return self._run_base_preparation()

        reachable, reason = self._three_d_bag_server_status()
        if reachable:
            return self._run_base_preparation()

        message = (
            "3DBAG LoD 2.2 is aangevinkt, maar QGIS kan de 3DBAG LoD 2.2 WFS "
            "momenteel niet openen.\n\n"
            "Wil je stap 1 direct verder uitvoeren zonder de 3DBAG LoD 2.2-"
            "controle? De gewone BAG-woningtypen worden dan wel gewoon verwerkt.\n\n"
            "LET OP – twee-onder-een-kapwoningen:\n"
            "Controleer na stap 1 extra goed de twee-onder-een-kapwoningen. "
            "Zonder de LoD 2.2-controle kunnen sommige daarvan als "
            "rijtjeswoning/tussenwoning worden geclassificeerd.\n\n"
            "Gebruik stap 2b – Woningtype aanpassen om deze woningen zo nodig "
            "direct te corrigeren."
        )
        if reason:
            message += f"\n\nTechnische melding: {reason}"

        box = QMessageBox(self)
        try:
            box.setIcon(QMessageBox.Icon.Warning)
            yes_button = QMessageBox.StandardButton.Yes
            no_button = QMessageBox.StandardButton.No
        except AttributeError:  # QGIS 3 / PyQt5
            box.setIcon(QMessageBox.Warning)
            yes_button = QMessageBox.Yes
            no_button = QMessageBox.No
        box.setWindowTitle("3DBAG LoD 2.2 niet bereikbaar")
        box.setText(message)
        box.setStandardButtons(yes_button | no_button)
        box.setDefaultButton(no_button)
        reply = box.exec()
        if reply != yes_button:
            return

        use_3dbag_widget = self.widgets.get("use_3dbag")
        if use_3dbag_widget is not None and hasattr(use_3dbag_widget, "setChecked"):
            use_3dbag_widget.setChecked(False)

        self.progress_summary.setText("3DBAG overgeslagen; controleer twee-onder-een-kap")
        self.progress_summary.setToolTip(
            "3DBAG LoD 2.2 is overgeslagen. Controleer na stap 1 vooral "
            "twee-onder-een-kapwoningen en corrigeer zo nodig via stap 2b – "
            "Woningtype aanpassen."
        )
        QApplication.processEvents()
        return self._run_base_preparation()
