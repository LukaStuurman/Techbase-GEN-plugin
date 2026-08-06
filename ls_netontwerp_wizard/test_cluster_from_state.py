"""Resume the newest local prepared workflow state for clustering regression tests."""

import json
from pathlib import Path
import sys

from qgis.core import QgsApplication


def main():
    plugin_dir = Path(__file__).resolve().parent
    states = sorted(
        (plugin_dir.parent / "plugin_test_output").rglob(
            "ls_netontwerp_workflow.json"
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    state_path = next(
        path
        for path in states
        if json.loads(path.read_text(encoding="utf-8")).get("status")
        == "clustering_bezig"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    sys.path.insert(0, str(plugin_dir.parent))
    app = QgsApplication([], False)
    app.initQgis()
    try:
        from ls_netontwerp_wizard.workflow import WorkflowRunner

        def progress(percent, message):
            print(f"{percent:5.1f}% {message}", flush=True)

        result = WorkflowRunner(state["values"], progress).cluster(state)
        for key, value in result.items():
            print(f"{key}={value}")
        print("PLUGIN_CLUSTER_RESUME_TEST_OK")
    finally:
        app.exitQgis()


if __name__ == "__main__":
    main()
