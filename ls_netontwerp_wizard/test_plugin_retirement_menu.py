"""QGIS smoke test: station retirement has a direct menu entry.

Run with the QGIS Python environment:
    python -m ls_netontwerp_wizard.test_plugin_retirement_menu
"""

from pathlib import Path
import sys

from qgis.core import QgsApplication


class _FakeIface:
    def __init__(self):
        self.vector_items = []
        self.plugin_items = []
        self.removed_vector = []
        self.removed_plugin = []
        self.toolbar_items = []

    def mainWindow(self):
        return None

    def addPluginToVectorMenu(self, menu, action):
        self.vector_items.append((menu, action))

    def addPluginToMenu(self, menu, action):
        self.plugin_items.append((menu, action))

    def addToolBarIcon(self, action):
        self.toolbar_items.append(action)

    def removePluginVectorMenu(self, menu, action):
        self.removed_vector.append((menu, action))

    def removePluginMenu(self, menu, action):
        self.removed_plugin.append((menu, action))

    def removeToolBarIcon(self, action):
        pass


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    app = QgsApplication([], False)
    app.initQgis()
    from ls_netontwerp_wizard.plugin import LSNetontwerpPlugin

    iface = _FakeIface()
    plugin = LSNetontwerpPlugin(iface)
    plugin.initProcessing = lambda: None
    plugin._repair_project_presentation = lambda *_: None
    opened = []
    plugin.open_manual_tool = lambda: opened.append("stationsbeheer")
    plugin.initGui()

    action = plugin.manual_action
    assert action is not None
    assert "Station laten vervallen" in action.text()
    assert ("LS Netontwerp", action) in iface.vector_items
    assert ("LS Netontwerp", action) in iface.plugin_items
    action.trigger()
    assert opened == ["stationsbeheer"]
    plugin.unload()
    assert ("LS Netontwerp", action) in iface.removed_vector
    assert ("LS Netontwerp", action) in iface.removed_plugin
    print("OK: menuactie opent stationsbeheer en wordt bij unload opgeruimd")


if __name__ == "__main__":
    main()
