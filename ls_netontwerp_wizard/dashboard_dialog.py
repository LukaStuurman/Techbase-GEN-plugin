"""Laatste QGIS 3/4 UI-afwerking voor het centrale workflowdashboard."""

from qgis.PyQt.QtWidgets import QGroupBox, QHBoxLayout, QPushButton

from .themed_dialog import LSNetontwerpDashboardDialog as _ThemedDashboardDialog


class LSNetontwerpDashboardDialog(_ThemedDashboardDialog):
    """Dashboard met robuuste compacte invoer- en voortgangsweergave."""

    def __init__(self, iface, parent=None):
        super().__init__(iface, parent)
        self._fix_input_browse_buttons()
        self._fix_compact_progress()

    def _fix_input_browse_buttons(self):
        """Houd 'Kiezen…' leesbaar, maar visueel in balans met de invoervelden."""
        for group in self.main_page.findChildren(QGroupBox):
            if group.title() != "Benodigde invoer":
                continue

            # De invoervelden zijn ongeveer 24 px hoog. Met een eigen kleine
            # verticale padding kan de knop 27–28 px blijven zonder dat QGIS 4
            # de onderkant van 'Kiezen…' afsnijdt.
            group.setMaximumHeight(140)
            for button in group.findChildren(QPushButton):
                button.setMinimumHeight(27)
                button.setMaximumHeight(28)
                button.setStyleSheet(
                    "QPushButton {"
                    "background:#f47700; color:white; border:0; border-radius:5px; "
                    "padding:2px 10px; font-weight:600;"
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
        bar_row.addWidget(self.progress_cancel_button, 0)
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

        # De balk zelf blijft dun. De rij krijgt zijn hoogte alleen van de 24 px
        # stopknop, waardoor alles netjes binnen hetzelfde oranje kader blijft.
        self.progress_group.setMaximumHeight(62)
        progress_layout.setContentsMargins(7, 4, 7, 5)
        progress_layout.setSpacing(3)
        self.progress_summary.setMinimumHeight(17)
        self.progress_summary.setMaximumHeight(17)
        self.progress_bar.setMinimumHeight(10)
        self.progress_bar.setMaximumHeight(10)
