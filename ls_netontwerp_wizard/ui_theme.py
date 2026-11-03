"""Shared TechBase styling and page structure for every plugin screen."""
from pathlib import Path

from qgis.PyQt.QtCore import QEvent, QObject, Qt
from qgis.PyQt.QtGui import QPixmap
from qgis.PyQt.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFrame, QGroupBox, QHBoxLayout,
    QFormLayout, QHeaderView, QLabel, QLayout, QPushButton, QScrollArea,
    QSizePolicy, QTableWidget, QVBoxLayout, QWidget,
)

BRAND = "#E86C12"
PALETTE = {"main": BRAND, "hover": "#C7580B", "soft": "#FFF4EA", "border": "#E5C4AB"}


STYLE = """
QWidget { color: #243246; font-family: 'Segoe UI'; font-size: 13px; }
QDialog, QWidget[uiRole="page"], QWidget[uiRole="content"] { background: #F5F7FA; }
QWidget[uiRole="header"], QWidget[uiRole="footer"] { background: #F5F7FA; }
QLabel { background: transparent; }
QLabel#techbaseTitle { font-size: 22px; font-weight: 700; color: #17263A; }
QLabel#techbaseSubtitle { font-size: 12px; color: #64748B; }
QLabel[uiRole="sectionTitle"] { color: #17263A; font-size: 15px; font-weight: 700; }
QLabel[uiRole="hint"] { color: #64748B; }
QLabel[uiRole="notice"] { background: #FFF4EA; border: 1px solid #E5C4AB; border-radius: 6px; padding: 10px; }
QGroupBox { background: #FFFFFF; border: 1px solid #DFE5EC; border-radius: 8px;
            margin-top: 0; padding: 10px; padding-top: 28px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: padding; subcontrol-position: top left;
                   left: 12px; top: 7px; padding: 0 5px; color: #243246; }
QFrame[uiRole="card"] { background: #FFFFFF; border: 1px solid #DFE5EC; border-radius: 8px; }
QPushButton { background: #FFFFFF; color: #334155; border: 1px solid #CBD5E1;
              border-radius: 6px; padding: 7px 12px; font-weight: 600; min-height: 18px; }
QPushButton:hover { background: #F1F5F9; border-color: #94A3B8; }
QPushButton:pressed { background: #E2E8F0; }
QPushButton:focus { border: 2px solid #E86C12; padding: 6px 11px; }
QPushButton[uiRole="primary"] { background: #E86C12; color: #FFFFFF; border-color: #E86C12; }
QPushButton[uiRole="primary"]:hover { background: #C7580B; border-color: #C7580B; }
QPushButton[uiRole="primary"]:pressed { background: #A84609; }
QPushButton[uiRole="map"] { color: #A84609; border-color: #E5C4AB; background: #FFF4EA; }
QPushButton[uiRole="map"]:hover { background: #FFE7D3; border-color: #E86C12; }
QPushButton[uiRole="danger"] { background: #FFFFFF; color: #B42318; border-color: #E8B4AE; }
QPushButton[uiRole="danger"]:hover { background: #FEF3F2; border-color: #B42318; }
QPushButton[uiRole="stop"] { background: #B42318; color: #FFFFFF; border-color: #B42318; padding: 0; min-height: 0; }
QPushButton[uiRole="stop"]:hover { background: #D92D20; }
QPushButton:disabled { background: #EDF1F5; color: #8995A3; border-color: #DFE5EC; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: #FFFFFF; color: #243246; border: 1px solid #CBD5E1;
    border-radius: 5px; padding: 6px 8px; min-height: 18px; selection-background-color: #FFE7D3; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #E86C12; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled { background: #F1F5F9; color: #8995A3; }
QComboBox { padding-right: 24px; }
QComboBox::drop-down { border: 0; width: 22px; }
QComboBox::down-arrow { image: url("@ICONS@/chevron-down.svg"); width: 14px; height: 14px; }
QSpinBox, QDoubleSpinBox { padding-right: 24px; }
QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 22px; border-left: 1px solid #DFE5EC; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 22px; border-left: 1px solid #DFE5EC; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url("@ICONS@/chevron-up.svg"); width: 12px; height: 12px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url("@ICONS@/chevron-down.svg"); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: #FFFFFF; color: #243246; selection-background-color: #FFE7D3; selection-color: #17263A; }
QCheckBox, QRadioButton { spacing: 8px; padding: 3px 0; background: transparent; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #94A3B8; border-radius: 3px; background: #FFFFFF; }
QCheckBox::indicator:checked { background: #E86C12; border-color: #E86C12; image: url("@ICONS@/check.svg"); }
QCheckBox::indicator:disabled { background: #EDF1F5; border-color: #DFE5EC; }
QCheckBox:disabled, QRadioButton:disabled { color: #8995A3; }
QCheckBox[uiRole="warning"] { color: #B54708; font-weight: 600; }
QTableWidget, QTableView, QPlainTextEdit, QTextEdit {
    background: #FFFFFF; alternate-background-color: #F8FAFC; border: 1px solid #CBD5E1;
    border-radius: 5px; padding: 4px; selection-background-color: #FFE7D3; selection-color: #17263A; }
QHeaderView::section { background: #F1F5F9; color: #334155; border: 0;
                       border-bottom: 1px solid #DFE5EC; padding: 8px; font-weight: 600; }
QTabWidget::pane { background: #FFFFFF; border: 1px solid #DFE5EC; border-radius: 6px; }
QTabBar::tab { background: #EDF1F5; color: #42546B; padding: 9px 12px; margin-right: 3px;
              border-top-left-radius: 5px; border-top-right-radius: 5px; }
QTabBar::tab:hover { background: #FFF4EA; }
QTabBar::tab:selected { background: #E86C12; color: #FFFFFF; }
QScrollArea { background: transparent; border: 0; }
QScrollArea > QWidget > QWidget { background: #F5F7FA; }
QScrollBar:vertical { background: #EDF1F5; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #CBD5E1; min-height: 30px; border-radius: 5px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QProgressBar { background: #EDF1F5; border: 1px solid #DFE5EC; border-radius: 4px;
               color: #334155; text-align: center; min-height: 8px; }
QProgressBar::chunk { background: #E86C12; border-radius: 3px; }
QToolTip { background: #17263A; color: #FFFFFF; border: 0; padding: 6px; }
QMenu { background: #FFFFFF; border: 1px solid #DFE5EC; padding: 4px; }
QMenu::item { padding: 7px 16px; }
QMenu::item:selected { background: #FFF4EA; color: #A84609; }
""".replace("@ICONS@", (Path(__file__).resolve().parent / "assets" / "ui").as_posix())


def branded_header(title, subtitle):
    header = QWidget()
    layout = QHBoxLayout(header)
    layout.setContentsMargins(0, 0, 0, 0)
    logo = QLabel()
    pixmap = QPixmap(str(Path(__file__).resolve().parent / "assets" / "techbase-logo.png"))
    keep = Qt.AspectRatioMode.KeepAspectRatio if hasattr(Qt, "AspectRatioMode") else Qt.KeepAspectRatio
    smooth = Qt.TransformationMode.SmoothTransformation if hasattr(Qt, "TransformationMode") else Qt.SmoothTransformation
    logo.setPixmap(pixmap.scaled(68, 68, keep, smooth))
    logo.setFixedSize(76, 76)
    layout.addWidget(logo)
    texts = QVBoxLayout()
    heading = QLabel(title)
    heading.setObjectName("techbaseTitle")
    note = QLabel(subtitle)
    note.setObjectName("techbaseSubtitle")
    texts.addStretch(1)
    texts.addWidget(heading)
    texts.addWidget(note)
    texts.addStretch(1)
    layout.addLayout(texts, 1)
    return header


def role(widget, name):
    widget.setProperty("uiRole", name)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def _button_role(button):
    if button.property("uiExplicitRole"):
        return str(button.property("uiExplicitRole"))
    name = button.text().strip().casefold()
    if button.objectName() == "dangerButton" or ("verwijderen" in name and "selectie wissen" not in name):
        return "danger"
    if name in {"annuleren", "stop", "✕"}:
        return "stop"
    if any(word in name for word in ("selecteren", "aanklikken", "tekenen", "kaart plaatsen", "grens van")):
        return "map"
    if any(word in name for word in ("opslaan", "uitvoeren", "maken", "afdwingen", "verplaatsen", "toevoegen", "koppelen", "nummer wijzigen")) and not name.startswith("regel "):
        return "primary"
    return "secondary"


def apply_theme(root, clear_legacy=True):
    root.setStyleSheet(STYLE)
    root.setProperty("uiThemed", True)
    if clear_legacy:
        # Old page-local palettes override the shared root stylesheet in Qt.
        for child in root.findChildren(QWidget):
            if (isinstance(child, (QPushButton, QGroupBox)) or type(child) is QFrame) and child.styleSheet():
                child.setStyleSheet("")
            elif child in getattr(root, "_ui_pages", ()):
                child.setStyleSheet("")
    for button in root.findChildren(QPushButton):
        button.setStyleSheet("")
        role(button, _button_role(button))
        if button.property("uiRole") != "stop":
            button.setMinimumHeight(34)
            button.setMaximumHeight(16777215)
    for checkbox in root.findChildren(QCheckBox):
        if checkbox.text() == "Advanced":
            checkbox.setText("Geavanceerde opties")
        if "ALLES TOESTAAN" in checkbox.text():
            checkbox.setStyleSheet("")
            role(checkbox, "warning")
    for frame in root.findChildren(QFrame):
        if frame.objectName().startswith("stepCard"):
            role(frame, "card")
            for label in frame.findChildren(QLabel):
                label.setStyleSheet("")
                role(label, "sectionTitle" if label.text()[:1].isdigit() else "hint")
    for title in root.findChildren(QLabel):
        if title.objectName() in {"techbaseTitle", "techbaseSubtitle"}:
            title.setStyleSheet("")
    for layout in root.findChildren(QLayout):
        layout.setSpacing(8)
        if isinstance(layout, QFormLayout):
            layout.setVerticalSpacing(8)
            layout.setHorizontalSpacing(12)
        layout.invalidate()
    for group in root.findChildren(QGroupBox):
        layout = group.layout()
        if layout is not None:
            layout.setSpacing(8)
            if isinstance(layout, QFormLayout):
                layout.setVerticalSpacing(8)
                layout.setHorizontalSpacing(12)
        expanding = QSizePolicy.Policy.Expanding if hasattr(QSizePolicy, "Policy") else QSizePolicy.Expanding
        minimum = QSizePolicy.Policy.Minimum if hasattr(QSizePolicy, "Policy") else QSizePolicy.Minimum
        group.setSizePolicy(expanding, minimum)
        if layout is not None:
            constraints = QLayout.SizeConstraint if hasattr(QLayout, "SizeConstraint") else QLayout
            # Dynamic forms must grow when an extra row becomes visible.
            constraint = constraints.SetMinimumSize if group.property("uiContentMinimum") else constraints.SetDefaultConstraint
            layout.setSizeConstraint(constraint)
            group.ensurePolished()
            layout.activate()
    for table in root.findChildren(QTableWidget):
        header = table.horizontalHeader()
        contents = QHeaderView.ResizeMode.ResizeToContents if hasattr(QHeaderView, "ResizeMode") else QHeaderView.ResizeToContents
        header.setSectionResizeMode(contents)
        header.setResizeContentsPrecision(100)
        header.setMinimumSectionSize(80)
    for mirror, source in getattr(root, "_dashboard_mirrors", ()):
        role(mirror, "primary" if source is getattr(root, "run_button", None) else "secondary")
    stop = getattr(root, "progress_cancel_button", None)
    if stop is not None:
        role(stop, "stop")
        stop.setFixedSize(26, 26)
    basic = getattr(root, "basic_group", None)
    if basic is not None:
        basic.setMinimumHeight(0)
        basic.setMaximumHeight(16777215)
    if hasattr(root, "progress_summary"):
        root.progress_summary.setStyleSheet("")
        root.progress_group.setMaximumHeight(92)
    root.updateGeometry()
    for layout in reversed(root.findChildren(QLayout)):
        layout.invalidate()
        layout.activate()
        if layout.parentWidget() is not None:
            layout.parentWidget().updateGeometry()


def _take_widget(layout, widget):
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item.widget() is widget:
            layout.takeAt(index)
            return True
        if item.layout() is not None and _take_widget(item.layout(), widget):
            return True
    return False


def _remove_from_parent_layout(widget):
    parent = widget.parentWidget()
    if parent is not None and parent.layout() is not None:
        _take_widget(parent.layout(), widget)


def normalize_page(page, host, actions=(), home=True):
    """Keep the branded header and action bar fixed; scroll all options."""
    if page.property("uiStructured"):
        return
    outer = page.layout()
    if outer is None:
        return
    role(page, "page")
    outer.setContentsMargins(12, 8, 12, 10)
    outer.setSpacing(10)
    header = outer.itemAt(0).widget() if outer.count() else None
    if header is not None and header.findChild(QLabel, "techbaseTitle") is not None:
        role(header, "header")
        header.setFixedHeight(76)
        outer.removeWidget(header)
    else:
        header = None

    home_buttons = [button for button in page.findChildren(QPushButton) if "Home" in button.text()]
    for button in home_buttons:
        _remove_from_parent_layout(button)
        button.hide()
    footer = QWidget(page)
    role(footer, "footer")
    footer_layout = QHBoxLayout(footer)
    footer_layout.setContentsMargins(0, 0, 0, 0)
    footer_layout.setSpacing(8)
    footer_layout.addStretch(1)
    for button in actions:
        _remove_from_parent_layout(button)
        button.setParent(footer)
        footer_layout.addWidget(button)
        button.show()
    if home:
        back = home_buttons[0] if home_buttons else QPushButton("←  Home", footer)
        back.setParent(footer)
        back.setMaximumWidth(16777215)
        back.setText("←  Home")
        back.setToolTip("Terug naar het dashboard")
        if not home_buttons:
            back.clicked.connect(host.show_home_page)
        footer_layout.addWidget(back)
        back.show()

    # Pages that already have a single content scroll area keep that viewport.
    remaining = [outer.itemAt(i) for i in range(outer.count())]
    reuse = len(remaining) == 1 and isinstance(remaining[0].widget(), QScrollArea)
    if reuse:
        scroll = outer.takeAt(0).widget()
    else:
        scroll = QScrollArea(page)
        scroll.setWidgetResizable(True)
        body = QWidget()
        role(body, "content")
        content = QVBoxLayout(body)
        content.setContentsMargins(0, 0, 8, 0)
        content.setSpacing(10)
        while outer.count():
            item = outer.takeAt(0)
            widget = item.widget()
            if widget is not None:
                hidden = widget.isHidden()
                widget.setParent(body)
                content.addWidget(widget)
                widget.setVisible(not hidden)
            elif item.layout() is not None:
                content.addLayout(item.layout())
            else:
                content.addItem(item)
        content.addStretch(1)
        scroll.setWidget(body)
    if header is not None:
        outer.addWidget(header)
    outer.addWidget(scroll, 1)
    outer.addWidget(footer)
    page.setProperty("uiStructured", True)
    page.setProperty("uiFooter", True)


class _OwnedDialogTheme(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner

    def eventFilter(self, watched, event):
        show_event = QEvent.Type.Show if hasattr(QEvent, "Type") else QEvent.Show
        if event.type() == show_event and isinstance(watched, QDialog) and not watched.property("uiThemed"):
            parent = watched.parentWidget()
            while parent is not None:
                if parent is self.owner:
                    apply_theme(watched)
                    break
                parent = parent.parentWidget()
        return False


def install_dialog_theme(owner):
    if getattr(owner, "_ui_dialog_filter", None) is None:
        owner._ui_dialog_filter = _OwnedDialogTheme(owner)
        QApplication.instance().installEventFilter(owner._ui_dialog_filter)
