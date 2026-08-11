"""Laatste waarschuwingen en zichtbare kwaliteitskeuzes op het dashboard."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
)

from .dashboard_dialog import LSNetontwerpDashboardDialog as _DashboardDialog


class LSNetontwerpDashboardDialog(_DashboardDialog):
    """Dashboard met 3DBAG-waarschuwing en expliciete gebiedsvormkeuze."""

    def __init__(self, iface, parent=None):
        super().__init__(iface, parent)
        self._install_area_shape_mode()

    def _fix_compact_progress(self):
        """Centreer voortgangsbalk en rode stopknop exact op dezelfde middenlijn."""
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
        except AttributeError:  # QGIS 3 / PyQt5
            align_vcenter = Qt.AlignVCenter

        bar_row = QHBoxLayout()
        bar_row.setContentsMargins(0, 0, 0, 0)
        bar_row.setSpacing(6)
        bar_row.addWidget(self.progress_bar, 1, align_vcenter)
        bar_row.addWidget(self.progress_cancel_button, 0, align_vcenter)
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

        # Geen houder, ondermarge of pixel-offset meer: beide widgets worden
        # door exact dezelfde horizontale layout rond dezelfde verticale as
        # gecentreerd. Dit voorkomt de te lage stopknop in QGIS 4.
        self.progress_group.setMaximumHeight(62)
        progress_layout.setContentsMargins(7, 4, 7, 5)
        progress_layout.setSpacing(3)
        self.progress_summary.setMinimumHeight(17)
        self.progress_summary.setMaximumHeight(17)
        self.progress_bar.setMinimumHeight(10)
        self.progress_bar.setMaximumHeight(10)

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

        # De oude Advanced-checkbox blijft als intern compatibiliteitsobject
        # bestaan; de zichtbare combobox bestuurt voortaan dezelfde parameter.
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

    def _run_base_preparation(self):
        """Start de oorspronkelijke stap 1 zonder de oudere 3DBAG-precheck opnieuw te doen."""
        return super(_DashboardDialog, self).run_preparation()

    def run_preparation(self):
        """Start stap 1 en waarschuw duidelijk voor classificatierisico zonder 3DBAG."""
        try:
            values = self.values()
        except Exception:
            # Sla de extra controle over en laat de bestaande invoervalidatie de
            # fout op de gebruikelijke manier afhandelen.
            return self._run_base_preparation()

        if not bool(values.get("use_3dbag", False)):
            return self._run_base_preparation()

        reachable, reason = self._three_d_bag_server_status()
        if reachable:
            return self._run_base_preparation()

        message = (
            "3DBAG LoD 2.2 is aangevinkt, maar de 3DBAG-server kan momenteel "
            "niet worden bereikt.\n\n"
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

        # De keuze is al gemaakt en de checkbox staat inmiddels uit.
        return self._run_base_preparation()