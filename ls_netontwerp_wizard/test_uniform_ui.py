"""Exercise every page, advanced tab, navigation and lazily created dialog."""
import os
from pathlib import Path
import sys

from qgis.PyQt.QtGui import QFont, QFontDatabase
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QCheckBox, QDialog, QLabel, QPushButton, QScrollArea, QTabWidget
from qgis.core import QgsApplication


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    app = QgsApplication([], False)
    app.initQgis()
    # Offscreen Windows Qt needs file-backed fonts for useful screenshots.
    for name in ("segoeui.ttf", "segoeuib.ttf"):
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont("Segoe UI", 10))
    from ls_netontwerp_wizard.dashboard_warning_dialog import LSNetontwerpDashboardDialog
    from ls_netontwerp_wizard.ui_theme import STYLE
    from ls_netontwerp_wizard.cluster_paint_dialog import VisueleClusterEditorDialog

    dialog = LSNetontwerpDashboardDialog(None)
    assert dialog.styleSheet() == STYLE
    assert len({p["main"] for p in dialog.STEP_PALETTES.values()}) == 1
    captures = Path(sys.argv[sys.argv.index("--captures") + 1]) if "--captures" in sys.argv else None
    if captures:
        captures.mkdir(parents=True, exist_ok=True)
        for edit, placeholder in ((dialog.xml_edit, "GEN-aansluitingen.xml"), (dialog.excel_edit, "Kabelgegevens.xlsx"), (dialog.plan_edit, "Plangebied.gpkg"), (dialog.output_edit, "Ontwerpmap")):
            edit.setText(placeholder)
    page_routes = (
        ("01-dashboard", dialog.show_home_page, dialog.main_page),
        ("02-stroom", dialog.show_value_page, dialog.value_page),
        ("03-woningtype", dialog.show_housing_page, dialog.housing_page),
        ("04-stations", dialog.show_station_page, dialog.station_page),
        ("05-nulwaarden", lambda: dialog.show_zero_current_page(select_first=False), dialog.zero_current_page),
        ("06-lovion-nieuwbouw", dialog.show_connection_sources_page, dialog.connection_sources_page),
        ("07-clustercorrectie", dialog.show_manual_page, dialog.manual_page),
        ("08-sleuven-routes", dialog.show_network_page, dialog.network_page),
        ("09-clustergebieden", dialog.show_areas_page, dialog.areas_page),
    )
    for name, show, page in page_routes:
        show()
        dialog.resize(1280, 960)
        dialog.show()
        app.processEvents()
        assert dialog.page_stack.currentWidget() is page
        assert page.updatesEnabled()
        assert page.property("uiStructured") and page.property("uiFooter")
        assert page.findChildren(QScrollArea), name
        assert page.styleSheet() == "", name
        for button in page.findChildren(QPushButton):
            assert button.styleSheet() == "", (name, button.text())
            assert button.property("uiRole") in {"primary", "secondary", "danger", "map", "stop"}, (name, button.text())
        if page is not dialog.main_page:
            home = [b for b in page.findChildren(QPushButton) if "Home" in b.text() and not b.isHidden()]
            assert len(home) == 1, (name, len(home))
            assert home[0].parentWidget().property("uiRole") == "footer"
            if captures:
                assert dialog.grab().save(str(captures / f"{name}.png"))
            home[0].click()
            app.processEvents()
            assert dialog.page_stack.currentWidget() is dialog.main_page, name
            show()
            app.processEvents()
            assert page.updatesEnabled() and page.isVisible(), name
        elif captures:
            assert dialog.grab().save(str(captures / f"{name}.png"))

    # Adding the business gas row must grow the group, also after a one-row category.
    for name, show, category, group, unit, gas, note in (
        ("stroom", dialog.show_value_page, dialog.value_category_combo, dialog.value_unit_group,
         dialog.value_unit_combo, dialog.value_gas_combo, dialog.value_unit_note),
        ("nulwaarden", lambda: dialog.show_zero_current_page(select_first=False),
         dialog.zero_current_page.category_combo, dialog.zero_current_page.unit_group,
         dialog.zero_current_page.unit_combo, dialog.zero_current_page.gas_combo, dialog.zero_current_page.unit_note),
    ):
        show()
        for width, height in ((1180, 740), (1440, 960)):
            dialog.resize(width, height)
            for code in ("Oplaadpunt", "Zakelijk", "Straatmeubilair", "Zakelijk", "Huishoudelijk", "Zakelijk"):
                category.setCurrentIndex(category.findData(code))
                app.processEvents()
                QTest.qWait(50)
                if code == "Huishoudelijk":
                    assert group.isHidden()
                    continue
                last_input = gas if code == "Zakelijk" else unit
                if code == "Zakelijk":
                    assert not gas.isHidden()
                    assert unit.geometry().bottom() < gas.geometry().top(), (name, code)
                assert note.geometry().top() > last_input.geometry().bottom(), (name, code, group.height(), last_input.geometry(), note.geometry())
                assert note.height() >= note.heightForWidth(note.width()), (name, code, note.geometry())
                assert note.geometry().bottom() < group.height(), (name, code, group.height(), note.geometry())
            if captures:
                assert group.grab().save(str(captures / f"14-zakelijk-{name}-{width}.png"))

    # Header Home is reused in the footer, so execution-time disable still works.
    dialog.show_value_page()
    dialog.value_home_button.setEnabled(False)
    assert not dialog.value_home_button.isEnabled()
    assert dialog.value_home_button.parentWidget().property("uiRole") == "footer"
    dialog.value_home_button.setEnabled(True)
    for attr in ("value_advanced_toggle", "housing_advanced_toggle", "station_advanced_toggle", "manual_advanced_toggle", "network_advanced_toggle", "areas_advanced_toggle"):
        toggle = getattr(dialog, attr)
        show = {"value_advanced_toggle": dialog.show_value_page, "housing_advanced_toggle": dialog.show_housing_page,
                "station_advanced_toggle": dialog.show_station_page, "manual_advanced_toggle": dialog.show_manual_page,
                "network_advanced_toggle": dialog.show_network_page, "areas_advanced_toggle": dialog.show_areas_page}[attr]
        show()
        assert toggle.text() == "Geavanceerde opties"
        toggle.setChecked(True)
        app.processEvents()
        if captures:
            assert dialog.grab().save(str(captures / f"13-{attr}.png"))
        toggle.setChecked(False)

    dialog.show_home_page()
    dialog.advanced_toggle.setChecked(True)
    assert dialog.header_widget.isVisible()
    for index in range(dialog.advanced_tabs.count()):
        dialog.advanced_tabs.setCurrentIndex(index)
        app.processEvents()
        if captures:
            assert dialog.grab().save(str(captures / f"10-advanced-{index}.png"))
    for key, widget in dialog.widgets.items():
        if not key.startswith("matrix_"):
            continue
        for tabs in dialog.findChildren(QTabWidget):
            for index in range(tabs.count()):
                if tabs.widget(index).isAncestorOf(widget):
                    tabs.setCurrentIndex(index)
                    break
        app.processEvents()
        assert widget.isVisible(), key
        if captures:
            assert dialog.grab().save(str(captures / f"12-{key}.png"))
    dialog.advanced_toggle.setChecked(False)
    for mode in ("prepare", "result"):
        dialog._open_visual_cluster_editor(mode)
        editor = dialog._dashboard_visual_cluster_dialog
        app.processEvents()
        QTest.qWait(100)
        assert editor.styleSheet() == STYLE
        assert editor.property("uiStructured")
        assert editor.apply_button.property("uiRole") == "primary"
        assert editor.lasso_button.property("uiRole") == "map"
        if editor.pre_group.isVisible():
            assert editor.pre_assign_button.geometry().bottom() < editor.pre_clear_button.geometry().top(), (mode, editor.pre_assign_button.geometry(), editor.pre_clear_button.geometry())
            assert editor.pre_assign_button.height() >= 34
            assert editor.pre_clear_button.height() >= 34
            if hasattr(editor, "dashboard_manual_cluster_button") and not editor.dashboard_manual_cluster_button.isHidden():
                assert editor.dashboard_manual_cluster_button.geometry().bottom() < editor.pre_group.height(), (editor.dashboard_manual_cluster_button.geometry(), editor.pre_group.geometry())
            assert editor.pre_group.geometry().bottom() < editor.options_group.geometry().top(), (editor.pre_group.geometry(), editor.options_group.geometry())
        if captures:
            assert dialog.grab().save(str(captures / f"11-clustereditor-{mode}.png"))
        home = next(b for b in editor.findChildren(QPushButton) if "Home" in b.text() and not b.isHidden())
        home.click()
        app.processEvents()
        assert dialog.page_stack.currentWidget() is dialog.main_page
    standalone = VisueleClusterEditorDialog(None)
    assert standalone.styleSheet() == STYLE
    assert standalone.property("uiStructured")
    standalone.close()
    # A plugin-owned information/message dialog gets the same theme on show.
    child = QDialog(dialog)
    child.show()
    app.processEvents()
    assert child.property("uiThemed") and child.styleSheet() == STYLE
    child.close()
    assert not any(c.text() == "Advanced" for c in dialog.findChildren(QCheckBox))
    assert dialog.station_delete_button.property("uiRole") == "danger"
    print("UNIFORM_UI_TEST_OK (9 pages, all advanced tabs, both editor modes, navigation and owned dialogs)", flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
