from __future__ import annotations

from qgis.PyQt.QtCore import QTimer, Qt
from qgis.PyQt.QtWidgets import (
    QApplication,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .dialog import LSNetontwerpDialog
from . import cluster_paint_dialog as _cluster_paint_dialog

VisueleClusterEditorDialog = _cluster_paint_dialog.VisueleClusterEditorDialog

try:
    SIZE_EXPANDING = QSizePolicy.Policy.Expanding
    SIZE_FIXED = QSizePolicy.Policy.Fixed
    FRAME_NONE = QFrame.Shape.NoFrame
    WIDGET_FLAG = Qt.WindowType.Widget
except AttributeError:  # QGIS 3 / PyQt5
    SIZE_EXPANDING = QSizePolicy.Expanding
    SIZE_FIXED = QSizePolicy.Fixed
    FRAME_NONE = QFrame.NoFrame
    WIDGET_FLAG = Qt.Widget


# QGIS 4 / PyQt6 moved TextSelectableByMouse into Qt.TextInteractionFlag.
# cluster_paint_dialog supports QGIS 3 as well, so provide a tiny runtime
# compatibility proxy without changing the editor's other Qt lookups.
if not hasattr(_cluster_paint_dialog.Qt, "TextSelectableByMouse"):
    class _ClusterQtCompat:
        def __getattr__(self, name):
            if name == "TextSelectableByMouse":
                return Qt.TextInteractionFlag.TextSelectableByMouse
            return getattr(Qt, name)

    _cluster_paint_dialog.Qt = _ClusterQtCompat()


class EmbeddedVisualClusterEditor(VisueleClusterEditorDialog):
    """Visuele clustereditor als interne pagina van de hoofdwizard."""

    def __init__(self, iface, host):
        self._host = host
        super().__init__(iface, host)
        self.setWindowFlags(WIDGET_FLAG)
        for button in self.findChildren(QPushButton):
            if button.text() == "Sluiten":
                button.setText("←  Home")

    def showMinimized(self):
        # Tijdens kaartselectie moet de QGIS-kaart volledig beschikbaar zijn.
        self._host.hide()

    def showNormal(self):
        self._host.show()
        self._host.raise_()
        self._host.activateWindow()

    def raise_(self):
        self._host.raise_()

    def activateWindow(self):
        self._host.activateWindow()

    def close(self):
        self._host.show_home_page()
        return True


class LSNetontwerpDashboardDialog(LSNetontwerpDialog):
    """Wizardvariant met een duidelijk gekleurd workflowdashboard."""

    STEP_PALETTES = {
        1: {"main": "#1565C0", "hover": "#0D47A1", "soft": "#E8F1FB", "border": "#90B7E3"},
        2: {"main": "#00897B", "hover": "#00695C", "soft": "#E4F4F1", "border": "#80CBC4"},
        3: {"main": "#6A1B9A", "hover": "#4A148C", "soft": "#F0E5F6", "border": "#CE93D8"},
        4: {"main": "#EF6C00", "hover": "#E65100", "soft": "#FFF0E2", "border": "#FFB56B"},
        5: {"main": "#2E7D32", "hover": "#1B5E20", "soft": "#E8F4E9", "border": "#9CCC9E"},
        6: {"main": "#C2185B", "hover": "#880E4F", "soft": "#FBE7EF", "border": "#F48FB1"},
    }

    def __init__(self, iface, parent=None):
        self._dashboard_visual_cluster_dialog = None
        self._dashboard_mirrors = []
        self._dashboard_widget = None
        super().__init__(iface, parent)
        self._install_author_credit()
        self._compact_input_section()
        self._install_dashboard()
        self._compact_progress_area()
        self._move_progress_to_bottom()
        self._apply_step_page_colors()
        self.setMinimumSize(1180, 740)
        self.resize(max(self.width(), 1180), max(self.height(), 760))

    def _install_author_credit(self):
        for label in self.main_page.findChildren(QLabel):
            if label.objectName() == "techbaseSubtitle":
                label.setText(
                    "TechBase • van GEN-data naar controleerbaar laagspanningsontwerp "
                    "• Gemaakt door Luka Stuurman"
                )
                break

    def _compact_input_section(self):
        for group in self.main_page.findChildren(QGroupBox):
            if group.title() != "Benodigde invoer":
                continue
            group.setMaximumHeight(132)
            layout = group.layout()
            if layout is not None:
                layout.setContentsMargins(8, 6, 8, 7)
                layout.setVerticalSpacing(3)
                layout.setHorizontalSpacing(7)
            for edit in (
                self.xml_edit,
                self.excel_edit,
                self.plan_edit,
                self.output_edit,
            ):
                edit.setMaximumHeight(24)
            for button in group.findChildren(QPushButton):
                button.setMaximumHeight(26)
            break

    def _compact_progress_area(self):
        self.progress_group.setTitle("")
        self.progress_group.setMaximumHeight(56)
        progress_layout = self.progress_group.layout()
        if progress_layout is not None:
            progress_layout.setContentsMargins(6, 3, 6, 4)
            progress_layout.setSpacing(2)

        self.progress_summary.setMaximumHeight(16)
        self.progress_summary.setStyleSheet(
            "font-size:11px; color:#555555; font-weight:600;"
        )
        self.progress_cancel_button.setText("Stop")
        self.progress_cancel_button.setMaximumHeight(22)
        self.progress_cancel_button.setMaximumWidth(58)
        self.progress_bar.setMaximumHeight(12)
        self.progress_bar.setTextVisible(False)
        self.progress_details_toggle.setVisible(False)
        self.progress_details.setVisible(False)

        self.status_label.setMaximumHeight(17)
        self.status_label.setStyleSheet("font-size:10px; color:#777777;")
        self.status_label.setWordWrap(False)

    def _move_progress_to_bottom(self):
        root = self.main_page.layout()
        if root is None:
            return
        root.removeWidget(self.status_label)
        root.removeWidget(self.progress_group)

        old_button_box = self.run_button.parentWidget()
        insert_at = root.indexOf(old_button_box)
        if insert_at < 0:
            insert_at = root.count()

        root.insertWidget(insert_at, self.status_label)
        root.insertWidget(insert_at + 1, self.progress_group)

    @staticmethod
    def _button_style(palette, secondary=False):
        if secondary:
            return (
                "QPushButton {"
                f"background:{palette['soft']}; color:{palette['main']}; "
                f"border:1px solid {palette['border']}; border-radius:6px; "
                "padding:8px 10px; font-weight:700; text-align:left;"
                "}"
                "QPushButton:hover {"
                f"background:{palette['main']}; color:white; border-color:{palette['main']};"
                "}"
                "QPushButton:disabled {background:#f1f1f1; color:#9e9e9e; border-color:#d8d8d8;}"
            )
        return (
            "QPushButton {"
            f"background:{palette['main']}; color:white; border:1px solid {palette['main']}; "
            "border-radius:6px; padding:9px 10px; font-weight:700; text-align:left;"
            "}"
            "QPushButton:hover {"
            f"background:{palette['hover']}; border-color:{palette['hover']};"
            "}"
            "QPushButton:disabled {background:#c9c9c9; color:#f4f4f4; border-color:#c9c9c9;}"
        )

    def _dashboard_button(
        self,
        text,
        step,
        target=None,
        callback=None,
        secondary=False,
        enabled_source=None,
    ):
        palette = self.STEP_PALETTES[step]
        button = QPushButton(text)
        button.setMinimumHeight(38)
        button.setSizePolicy(SIZE_EXPANDING, SIZE_FIXED)
        button.setStyleSheet(self._button_style(palette, secondary=secondary))
        if target is not None:
            button.clicked.connect(target.click)
            self._dashboard_mirrors.append((button, target))
        elif callback is not None:
            button.clicked.connect(callback)
            if enabled_source is not None:
                self._dashboard_mirrors.append((button, enabled_source))
        return button

    def _make_step_card(self, step, title, subtitle, actions):
        palette = self.STEP_PALETTES[step]
        card = QFrame()
        card.setObjectName(f"stepCard{step}")
        card.setFrameShape(FRAME_NONE)
        card.setMinimumHeight(166)
        card.setStyleSheet(
            f"QFrame#stepCard{step} {{"
            f"background:{palette['soft']}; border:1px solid {palette['border']}; "
            "border-radius:9px;}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 11, 12, 12)
        layout.setSpacing(7)
        header = QLabel(f"{step}. {title}")
        header.setStyleSheet(
            f"color:{palette['main']}; font-size:15px; font-weight:800; border:0;"
        )
        layout.addWidget(header)
        note = QLabel(subtitle)
        note.setWordWrap(True)
        note.setStyleSheet("color:#4f4f4f; border:0;")
        layout.addWidget(note)
        layout.addSpacing(2)
        for action in actions:
            layout.addWidget(action)
        layout.addStretch(1)
        return card

    def _install_dashboard(self):
        root = self.main_page.layout()
        if root is None:
            return

        old_button_box = self.run_button.parentWidget()
        if isinstance(old_button_box, QDialogButtonBox):
            old_button_box.setVisible(False)

        dashboard = QWidget(self.main_page)
        self._dashboard_widget = dashboard
        dashboard.setObjectName("workflowDashboard")
        dashboard.setMinimumHeight(360)
        dashboard.setSizePolicy(SIZE_EXPANDING, SIZE_EXPANDING)
        dashboard_layout = QVBoxLayout(dashboard)
        dashboard_layout.setContentsMargins(0, 2, 0, 0)
        dashboard_layout.setSpacing(7)

        title_row = QHBoxLayout()
        title = QLabel("Werkstappen")
        title.setStyleSheet("font-size:16px; font-weight:800; color:#333333;")
        hint = QLabel("Kies per fase de automatische of handmatige bewerking.")
        hint.setStyleSheet("color:#707070;")
        title_row.addWidget(title)
        title_row.addSpacing(10)
        title_row.addWidget(hint)
        title_row.addStretch(1)
        dashboard_layout.addLayout(title_row)

        grid = QGridLayout()
        grid.setHorizontalSpacing(9)
        grid.setVerticalSpacing(9)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        for row in range(2):
            grid.setRowStretch(row, 1)

        step1 = self._make_step_card(
            1,
            "Invoer & ontwerpstroom",
            "GEN en Excel importeren en de controlelaag voor het ontwerp opbouwen.",
            [
                self._dashboard_button(
                    "1. Ontwerpstroom maken", 1, target=self.run_button
                )
            ],
        )
        step2 = self._make_step_card(
            2,
            "Brondata controleren",
            "Corrigeer waarden voordat de clustering wordt opgebouwd.",
            [
                self._dashboard_button(
                    "2a. Stroom aanpassen", 2, target=self.edit_values_button
                ),
                self._dashboard_button(
                    "2b. Woningtype aanpassen",
                    2,
                    target=self.edit_housing_button,
                    secondary=True,
                ),
                self._dashboard_button(
                    "2c. Stations aanpassen",
                    2,
                    target=self.edit_stations_button,
                    secondary=True,
                ),
            ],
        )
        step3 = self._make_step_card(
            3,
            "Clustering maken",
            "Kies automatisch clusteren of deel aansluitingen vooraf volledig handmatig in.",
            [
                self._dashboard_button(
                    "3a. Automatische clustering maken",
                    3,
                    target=self.cluster_button,
                ),
                self._dashboard_button(
                    "3b. Handmatige clustering voorbereiden",
                    3,
                    callback=lambda: self._open_visual_cluster_editor("prepare"),
                    secondary=True,
                    enabled_source=self.cluster_button,
                ),
            ],
        )
        step4 = self._make_step_card(
            4,
            "Clustering aanpassen",
            "Wijzig bestaande clusters of gebruik de visuele lasso-editor voor nieuwe stations en clusters.",
            [
                self._dashboard_button(
                    "4a. Clustercorrectie", 4, target=self.edit_cluster_button
                ),
                self._dashboard_button(
                    "4b. Visuele handmatige clustereditor",
                    4,
                    callback=lambda: self._open_visual_cluster_editor("result"),
                    secondary=True,
                ),
            ],
        )
        step5 = self._make_step_card(
            5,
            "Sleuven & routes",
            "Teken of node sleuven en vernieuw geselecteerde of alle clusterroutes.",
            [
                self._dashboard_button(
                    "5. Sleuven/routes openen", 5, target=self.network_button
                )
            ],
        )
        step6 = self._make_step_card(
            6,
            "Clustergebieden",
            "Maak de eindgebieden compacter en pas gedeelde grenzen visueel aan.",
            [
                self._dashboard_button(
                    "6. Mooie clustergebieden", 6, target=self.areas_button
                )
            ],
        )

        for index, card in enumerate(
            (step1, step2, step3, step4, step5, step6)
        ):
            grid.addWidget(card, index // 3, index % 3)
        dashboard_layout.addLayout(grid)

        progress_index = root.indexOf(self.progress_group)
        if progress_index < 0:
            progress_index = max(0, root.count() - 1)
        root.insertWidget(progress_index, dashboard)

        self._dashboard_sync_timer = QTimer(self)
        self._dashboard_sync_timer.setInterval(300)
        self._dashboard_sync_timer.timeout.connect(self._sync_dashboard_buttons)
        self._dashboard_sync_timer.start()
        self._sync_dashboard_buttons()

    def _sync_dashboard_buttons(self):
        for mirror, source in self._dashboard_mirrors:
            mirror.setEnabled(source.isEnabled())
            mirror.setToolTip(source.toolTip())

    def _open_visual_cluster_editor(self, requested_mode):
        if self._dashboard_visual_cluster_dialog is None:
            self._dashboard_visual_cluster_dialog = EmbeddedVisualClusterEditor(
                self.iface, self
            )
            self.page_stack.addWidget(self._dashboard_visual_cluster_dialog)

        palette = self.STEP_PALETTES[3 if requested_mode == "prepare" else 4]
        self._dashboard_visual_cluster_dialog.setStyleSheet(
            "QPushButton {"
            f"background:{palette['main']}; color:white; border:1px solid {palette['main']}; "
            "border-radius:5px; padding:7px 10px; font-weight:650;"
            "}"
            "QPushButton:hover {"
            f"background:{palette['hover']}; border-color:{palette['hover']};"
            "}"
            "QPushButton:disabled {background:#c9c9c9; color:#f4f4f4; border-color:#c9c9c9;}"
            "QGroupBox {"
            f"border:1px solid {palette['border']}; border-radius:6px; margin-top:8px; "
            "padding-top:7px; font-weight:700;"
            "}"
            "QGroupBox::title {"
            f"color:{palette['main']}; subcontrol-origin:margin; left:8px; padding:0 4px;"
            "}"
        )
        self._dashboard_visual_cluster_dialog.refresh_layers()
        self.page_stack.setCurrentWidget(self._dashboard_visual_cluster_dialog)
        self.setWindowTitle(
            "LS Netontwerp Wizard – "
            + (
                "handmatige clustering voorbereiden"
                if requested_mode == "prepare"
                else "visuele clustereditor"
            )
        )
        self.resize(max(self.width(), 1180), max(self.height(), 820))

    def _page_style(self, step):
        palette = self.STEP_PALETTES[step]
        return (
            "QPushButton {"
            f"background:{palette['main']}; color:white; border:1px solid {palette['main']}; "
            "border-radius:5px; padding:7px 10px; font-weight:650;"
            "}"
            "QPushButton:hover {"
            f"background:{palette['hover']}; border-color:{palette['hover']};"
            "}"
            "QPushButton:disabled {background:#c9c9c9; color:#f4f4f4; border-color:#c9c9c9;}"
            "QPushButton#genInfoButton {"
            f"background:{palette['soft']}; color:{palette['main']}; "
            f"border:1px solid {palette['border']};"
            "}"
            "QGroupBox {"
            f"border:1px solid {palette['border']}; border-radius:6px; "
            "margin-top:8px; padding-top:7px; font-weight:700;"
            "}"
            "QGroupBox::title {"
            f"color:{palette['main']}; subcontrol-origin:margin; "
            "left:8px; padding:0 4px;"
            "}"
            "QProgressBar::chunk {"
            f"background:{palette['main']};"
            "}"
        )

    def _apply_step_page_colors(self):
        for page in (self.value_page, self.housing_page, self.station_page):
            page.setStyleSheet(self._page_style(2))
        self.manual_page.setStyleSheet(self._page_style(4))
        self.network_page.setStyleSheet(self._page_style(5))
        self.areas_page.setStyleSheet(self._page_style(6))

    def _force_home_repaint(self):
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
        self.update()
        self.repaint()
        QApplication.processEvents()

    def show_home_page(self):
        self.page_stack.setUpdatesEnabled(False)
        try:
            super().show_home_page()
        finally:
            self.page_stack.setUpdatesEnabled(True)
        self.resize(max(self.width(), 1180), max(self.height(), 760))
        QTimer.singleShot(0, self._force_home_repaint)
