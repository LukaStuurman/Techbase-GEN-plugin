"""Keep the project layer list authoritative for rendering and legends."""
from qgis.core import QgsMapLayerLegendUtils, QgsProject

PRESENTATION_VERSION = 147


def use_layer_tree_order(project=None, foreground=(), background=()):
    project = project or QgsProject.instance()
    root = project.layerTreeRoot()
    root.setHasCustomLayerOrder(False)

    def move(layer, position):
        if layer is None:
            return
        node = root.findLayer(layer.id())
        if node is None:
            return
        clone = node.clone()
        clone.setItemVisibilityChecked(node.isVisible())
        parent = node.parent()
        root.insertChildNode(position, clone)
        parent.removeChildNode(node)

    for layer in reversed(tuple(foreground)):
        move(layer, 0)
    for layer in background:
        move(layer, len(root.children()))
    project.setDirty(True)


def show_connection_legend(layer):
    node = QgsProject.instance().layerTreeRoot().findLayer(layer.id())
    if node is None or layer.renderer() is None:
        return
    items = layer.renderer().legendSymbolItems()
    QgsMapLayerLegendUtils.setLegendNodeOrder(node, list(range(len(items))))
    if len(items) == 1 and layer.renderer().type() == "singleSymbol":
        QgsMapLayerLegendUtils.setLegendNodeUserLabel(node, 0, "Aansluitingen")
    else:
        for index, item in enumerate(items):
            QgsMapLayerLegendUtils.setLegendNodeUserLabel(node, index, item.label())
    node.setExpanded(True)
    if layer.legend() is not None:
        layer.legend().itemsChanged.emit()


def place_layer_before(layer, reference, project=None):
    project = project or QgsProject.instance()
    root = project.layerTreeRoot()
    root.setHasCustomLayerOrder(False)
    node = root.findLayer(layer.id())
    anchor = root.findLayer(reference.id()) if reference is not None else None
    if node is not None and anchor is not None:
        clone = node.clone()
        clone.setItemVisibilityChecked(node.isVisible())
        parent = anchor.parent()
        parent.insertChildNode(parent.children().index(anchor), clone)
        node.parent().removeChildNode(node)


def repair_generated_project(project=None):
    project = project or QgsProject.instance()
    names = {layer.name() for layer in project.mapLayers().values()}
    clustered = {"Aansluitingen geclusterd", "Stations ontwerp", "Clustergebieden"}.issubset(names)
    current_version = project.readNumEntry("LSNetontwerp", "presentation_version", 0)[0]
    if current_version >= PRESENTATION_VERSION:
        return
    if not current_version and not clustered:
        return
    backgrounds = [layer for layer in project.mapLayers().values()
                   if layer.customProperty("LSNetontwerp/osm_layer", False) or layer.name() == "OpenStreetMap"]
    use_layer_tree_order(project, background=backgrounds)
    for layer in project.mapLayers().values():
        if layer.customProperty("LSNetontwerp/review_current_layer", False) or layer.name() == "Aansluitingen geclusterd":
            show_connection_legend(layer)
    # Keep older prepared-project migrations available when still needed.
    if current_version >= 146 or clustered:
        project.writeEntry("LSNetontwerp", "presentation_version", PRESENTATION_VERSION)
    if project.fileName():
        project.write()
