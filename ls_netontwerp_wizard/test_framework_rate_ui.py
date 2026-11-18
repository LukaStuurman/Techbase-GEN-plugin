"""Offscreen QGIS test: independent tables, edit, save, restore, migration."""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
import sys
import tempfile
from pathlib import Path
from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtWidgets import QTableWidgetItem
from qgis.core import QgsApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
app = QgsApplication([], False)
app.initQgis()

from ls_netontwerp_wizard.dialog import LSNetontwerpDialog
from ls_netontwerp_wizard.design_rate_profiles import parse_k20_rates, original_k20_tables
from ls_netontwerp_wizard.algorithms.woningtype_selectie_herberekenen_tool import _configurations, _load_design_module


def select(dialog, framework):
    index = dialog.framework_combo.findData(framework)
    assert index >= 0
    dialog.framework_combo.setCurrentIndex(index)
    assert dialog._rate_views[framework].isVisible() is False or dialog._rate_stack.currentWidget() is dialog._rate_views[framework]


def cell(dialog, framework, key, row, column):
    table = dialog._rate_tables[framework][key]
    return table.item(row, column)


def main():
    with tempfile.TemporaryDirectory() as folder:
        ini = str(Path(folder) / "rates.ini")
        dialog = LSNetontwerpDialog()
        dialog.SETTINGS_PREFIX = "RateProfilesTest/"
        dialog.settings = QSettings(ini, QSettings.Format.IniFormat if hasattr(QSettings, "Format") else QSettings.IniFormat)
        select(dialog, "3.0")
        assert cell(dialog, "3.0", "matrix_straat", 0, 2).text() == "5.8"
        cell(dialog, "3.0", "matrix_straat", 0, 2).setText("9.1")

        select(dialog, "3.2")
        assert cell(dialog, "3.2", "matrix_straat", 0, 2).text() == "4.3"
        cell(dialog, "3.2", "matrix_straat", 0, 2).setText("4.9")
        assert dialog.values()["matrix_straat"][:3] == ["0", "6", "4.9"]

        select(dialog, "2.0")
        assert cell(dialog, "2.0", "k20_street", 0, 2).text() == "5.8"
        cell(dialog, "2.0", "k20_street", 0, 2).setText("7.7")
        cell(dialog, "2.0", "k20_household", 0, 2).setText("12.5")
        cell(dialog, "2.0", "k20_gas", 5, 2).setText("144")
        custom = dialog.values()
        assert custom["design_framework"] == "2.0"
        assert custom["k20_street"][:4] == ["25", "25", "7.7", "5.8"]
        assert custom["framework_profiles"]["3.0"]["matrix_straat"][2] == "9.1"
        assert custom["framework_profiles"]["3.2"]["matrix_straat"][2] == "4.9"
        parse_k20_rates(custom)
        module = _load_design_module()
        cfg = _configurations(custom, module)
        assert module.calculate_ontwerpstroom(
            None, "straatmeubilair", "", 0, "Geen", cfg[0], 1, None, True
        ) == 7.7
        assert module.calculate_ontwerpstroom(
            "3 x 63 A", "bedrijf", "", 0, "G10", cfg[0], 1, None, True
        ) == 144

        dialog._save_rate_tables()
        settings_profile = json.loads(dialog.settings.value(dialog.SETTINGS_PREFIX + "framework_profiles_v1"))
        assert settings_profile["2.0"]["k20_household"][2] == "12.5"

        reopened = LSNetontwerpDialog()
        reopened.SETTINGS_PREFIX = "RateProfilesTest/"
        reopened.settings = QSettings(ini, QSettings.Format.IniFormat if hasattr(QSettings, "Format") else QSettings.IniFormat)
        reopened._restore_settings()
        select(reopened, "2.0")
        assert cell(reopened, "2.0", "k20_street", 0, 2).text() == "7.7"
        select(reopened, "3.0")
        assert cell(reopened, "3.0", "matrix_straat", 0, 2).text() == "9.1"
        select(reopened, "3.2")
        assert cell(reopened, "3.2", "matrix_straat", 0, 2).text() == "4.9"
        # Original per-table reset cannot affect the other two frameworks.
        select(reopened, "2.0")
        reopened._set_matrix_values(
            reopened._rate_tables["2.0"]["k20_street"],
            reopened._default_rate_values("2.0", "k20_street"),
        )
        assert cell(reopened, "2.0", "k20_street", 0, 2).text() == "5.8"
        assert cell(reopened, "2.0", "k20_household", 0, 2).text() == "12.5"
        assert cell(reopened, "3.0", "matrix_straat", 0, 2).text() == "9.1"
        assert cell(reopened, "3.2", "matrix_straat", 0, 2).text() == "4.9"
        print("FRAMEWORK_RATE_UI_OK (3 independent editors, QSettings, restored defaults and active calculation)", flush=True)
        sys.stdout.flush()
        os._exit(0)


if __name__ == "__main__":
    main()
