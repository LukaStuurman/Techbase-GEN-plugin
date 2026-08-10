"""Laatste QGIS 3/4 UI-afwerking voor het centrale workflowdashboard."""

from qgis.PyQt.QtWidgets import QGroupBox, QPushButton

from .themed_dialog import LSNetontwerpDashboardDialog as _ThemedDashboardDialog


class LSNetontwerpDashboardDialog(_ThemedDashboardDialog):
    """Dashboard met robuuste compacte invoer- en voortgangsweergave."""

    def __init__(self, iface, parent=None):
        super().__init__(iface, parent)
        self._fix_input_browse_buttons()
        self._fix_compact_progress()

    def _fix_input_browse_buttons(self):
        """Voorkom dat 'Kiezen…' in QGIS 4 verticaal wordt afgeknipt."""
        for group in self.main_page.findChildren(QGroupBox):
            if group.title() != "Benodigde invoer":
                continue
            # Iets meer hoogte dan de eerdere compacte 26 px; nog steeds compact.
            group.setMaximumHeight(148)
            for button in group.findChildren(QPushButton):
                button.setMinimumHeight(30)
                button.setMaximumHeight(32)
            break

    def _fix_compact_progress(self):
        """Eén statusweergave met een duidelijk rode annuleren-knop."""
        # De oude losse statusregel onder het dashboard dupliceerde de tekst die
        # al in het compacte voortgangsvak staat.
        self.status_label.setVisible(False)
        self.status_label.setMaximumHeight(0)

        # Geef de actieve annuleren-knop een eigen stijl, zodat de algemene
        # oranje TechBase-knopstijl hem niet overschrijft of leeg laat lijken.
        button = self.progress_cancel_button
        button.setText("✕")
        button.setToolTip("Huidige stap stoppen")
        button.setMinimumSize(30, 30)
        button.setMaximumSize(30, 30)
        button.setStyleSheet(
            "QPushButton {"
            "background:#C62828; color:white; border:1px solid #9F1F1F; "
            "border-radius:6px; padding:0px; font-size:18px; font-weight:900;"
            "}"
            "QPushButton:hover {background:#E53935; border-color:#B71C1C;}"
            "QPushButton:pressed {background:#B71C1C;}"
            "QPushButton:disabled {background:#D7A3A3; color:#F5E4E4; border-color:#D7A3A3;}"
        )

        # Houd de compacte balk hoog genoeg voor de rode X zonder de werkstappen
        # opnieuw samen te drukken.
        self.progress_group.setMaximumHeight(66)
        if self.progress_group.layout() is not None:
            self.progress_group.layout().setContentsMargins(7, 4, 7, 5)
            self.progress_group.layout().setSpacing(3)
        self.progress_summary.setMinimumHeight(18)
        self.progress_summary.setMaximumHeight(18)
        self.progress_bar.setMinimumHeight(12)
        self.progress_bar.setMaximumHeight(12)
