"""Laatste waarschuwingen bovenop het centrale workflowdashboard."""

from qgis.PyQt.QtWidgets import QApplication, QMessageBox

from .dashboard_dialog import LSNetontwerpDashboardDialog as _DashboardDialog


class LSNetontwerpDashboardDialog(_DashboardDialog):
    """Dashboard met expliciete kwaliteitswaarschuwing bij 3DBAG-uitval."""

    def run_preparation(self):
        """Start stap 1 en waarschuw duidelijk voor classificatierisico zonder 3DBAG."""
        try:
            values = self.values()
        except Exception:
            # Sla de extra controle over en laat de bestaande invoervalidatie de
            # fout op de gebruikelijke manier afhandelen.
            return super(_DashboardDialog, self).run_preparation()

        if not bool(values.get("use_3dbag", False)):
            return super(_DashboardDialog, self).run_preparation()

        reachable, reason = self._three_d_bag_server_status()
        if reachable:
            return super(_DashboardDialog, self).run_preparation()

        message = (
            "3DBAG LoD 2.2 is aangevinkt, maar de 3DBAG-server kan momenteel "
            "niet worden bereikt.\n\n"
            "Wil je stap 1 direct verder uitvoeren zonder de 3DBAG LoD 2.2-"
            "controle? De gewone BAG-woningtypen worden dan wel gewoon verwerkt.\n\n"
            "LET OP: controleer na stap 1 extra goed de twee-onder-een-kapwoningen. "
            "Zonder de LoD 2.2-controle kunnen sommige twee-onder-een-kapwoningen "
            "als rijtjeswoning/tussenwoning worden geclassificeerd. Gebruik zo nodig "
            "stap 2b 'Woningtype aanpassen' om deze woningen te corrigeren."
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

        self.progress_summary.setText("3DBAG overgeslagen; controleer twee-onder-een-kap")
        self.progress_summary.setToolTip(
            "3DBAG LoD 2.2 is overgeslagen. Controleer na stap 1 vooral "
            "twee-onder-een-kapwoningen en corrigeer zo nodig via stap 2b."
        )
        QApplication.processEvents()

        # Omzeil de oudere 3DBAG-pop-up in dashboard_dialog.py: de keuze is hier
        # al gemaakt en de checkbox staat inmiddels uit.
        return super(_DashboardDialog, self).run_preparation()
