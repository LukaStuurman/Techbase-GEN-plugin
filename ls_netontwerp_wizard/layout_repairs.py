"""Remove the unsupported HTML frame created when QGIS clones an HTML label."""
from qgis.core import QgsLayoutItemHtml, QgsLayoutItemLabel


def repair_scope_html_frames(layout):
    table = layout.itemById("scope_stationsoverzicht")
    if not isinstance(table, QgsLayoutItemLabel):
        return 0
    position = table.positionWithUnits()
    size = table.sizeWithUnits()
    removed = 0
    for multiframe in list(layout.multiFrames()):
        if not isinstance(multiframe, QgsLayoutItemHtml) or multiframe.frameCount() != 1:
            continue
        frame = multiframe.frame(0)
        location, dimensions = frame.positionWithUnits(), frame.sizeWithUnits()
        # Match the unnamed duplicate of this exact table. Other HTML content
        # deliberately placed by the user must remain untouched.
        if frame.id() or any(abs(first-second) > .1 for first, second in (
            (location.x(), position.x()), (location.y(), position.y()),
            (dimensions.width(), size.width()), (dimensions.height(), size.height()),
        )):
            continue
        multiframe.deleteFrames()
        layout.removeMultiFrame(multiframe)
        multiframe.deleteLater()
        removed += 1
    if removed:
        layout.refresh()
        layout.project().setDirty(True)
    return removed


def repair_scope_layouts(project):
    return sum(repair_scope_html_frames(layout) for layout in project.layoutManager().layouts()
               if layout.name() == "Scope")
