"""Regression: remove only the unnamed duplicate HTML frame behind the Scope table."""
from pathlib import Path
import os
import sys
import tempfile


def main():
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    from qgis.core import (QgsApplication, QgsProject, QgsPrintLayout, QgsLayoutItemLabel,
                           QgsLayoutItemHtml, QgsLayoutFrame, QgsLayoutPoint, QgsLayoutSize)
    app=QgsApplication([],False);app.initQgis()
    from ls_netontwerp_wizard.layout_repairs import repair_scope_layouts
    project=QgsProject.instance()
    layout=QgsPrintLayout(project);layout.initializeDefaults();layout.setName('Scope')
    project.layoutManager().addLayout(layout)
    table=QgsLayoutItemLabel(layout);table.setId('scope_stationsoverzicht');table.setText('Station list')
    table.attemptMove(QgsLayoutPoint(324.5,26));table.attemptResize(QgsLayoutSize(86,137));layout.addLayoutItem(table)
    for x in (324.5,20):
        html=QgsLayoutItemHtml(layout);layout.addMultiFrame(html)
        frame=QgsLayoutFrame(layout,html);frame.attemptMove(QgsLayoutPoint(x,26));frame.attemptResize(QgsLayoutSize(86,137));html.addFrame(frame)
    assert len(layout.multiFrames())==2
    assert repair_scope_layouts(project)==1
    assert len(layout.multiFrames())==1
    assert layout.itemById('scope_stationsoverzicht').text()=='Station list'
    assert repair_scope_layouts(project)==0
    with tempfile.TemporaryDirectory() as folder:
        path=str(Path(folder)/'test.qgz')
        assert project.write(path);project.clear();assert project.read(path)
        layout=project.layoutManager().layoutByName('Scope')
        assert len(layout.multiFrames())==1
        assert repair_scope_layouts(project)==0
        assert layout.itemById('scope_stationsoverzicht').text()=='Station list'
        project.clear()
    print('SCOPE_HTML_FRAME_REPAIR_TEST_OK',flush=True)
    os._exit(0)


if __name__=='__main__':
    main()
