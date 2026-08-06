"""Volledige lokale integratietest met de Buitenpepers-bestanden."""

from pathlib import Path
import sys

from qgis.core import QgsApplication


def main():
    plugin_dir = Path(__file__).resolve().parent
    data_dir = plugin_dir.parent
    sys.path.insert(0, str(plugin_dir.parent))
    app = QgsApplication([], False)
    app.initQgis()
    try:
        from ls_netontwerp_wizard.dialog import (
            BOOL_OPTIONS,
            DESIGN_MATRIX_OPTIONS,
            NUMBER_OPTIONS,
            TEXT_OPTIONS,
        )
        from ls_netontwerp_wizard.workflow import WorkflowRunner

        values = {key: default for key, (_label, default) in TEXT_OPTIONS.items()}
        values.update({key: default for key, (_label, default) in BOOL_OPTIONS.items()})
        values.update(
            {key: default for key, (_label, default, *_rest) in NUMBER_OPTIONS.items()}
        )
        values.update(
            {
                key: list(default)
                for key, (_label, _headers, default) in DESIGN_MATRIX_OPTIONS.items()
            }
        )
        values.update(
            {
                "xml": str(data_dir / "Buitenpepers v2.xml"),
                "excel": str(data_dir / "Big excel buitenpepers v2.xlsx"),
                "plan": str(data_dir / "plangebied.shp"),
                "output": str(data_dir / "plugin_test_output"),
                "open_project": False,
            }
        )
        last_message = [None]

        def progress(percent, message):
            if message != last_message[0]:
                print(f"{percent:5.1f}% {message}", flush=True)
                last_message[0] = message

        result = WorkflowRunner(values, progress).run()
        for key, value in result.items():
            print(f"{key}={value}")
        print("PLUGIN_WORKFLOW_TEST_OK")
    finally:
        app.exitQgis()


if __name__ == "__main__":
    main()
