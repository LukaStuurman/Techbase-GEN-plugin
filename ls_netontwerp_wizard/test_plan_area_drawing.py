"""Exercise polygon drawing, persistent input, invalid geometry and cancellation in QGIS."""
import os
import sys
import tempfile
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from qgis.core import (QgsApplication, QgsProject, QgsCoordinateReferenceSystem,
                           QgsRectangle, QgsVectorLayer, QgsPointXY)
    from qgis.gui import QgsMapCanvas, QgsMapToolPan, QgsMessageBar
    from qgis.PyQt.QtCore import Qt, QPoint, QCoreApplication
    from qgis.PyQt.QtTest import QTest
    from qgis.PyQt.QtGui import QFont, QFontDatabase
    from qgis.PyQt.QtWidgets import QMainWindow, QWidget, QVBoxLayout
    app = QgsApplication([], False)
    app.initQgis()
    for filename in ('segoeui.ttf','segoeuib.ttf'):
        QFontDatabase.addApplicationFont(str(Path('C:/Windows/Fonts')/filename))
    app.setFont(QFont('Segoe UI',10))
    QCoreApplication.setOrganizationName('LSNetontwerpDrawingTests')
    QCoreApplication.setApplicationName('PlanAreaDrawing')
    from ls_netontwerp_wizard.dashboard_warning_dialog import LSNetontwerpDashboardDialog
    from ls_netontwerp_wizard.workflow import WorkflowRunner
    from ls_netontwerp_wizard.plan_area_drawing import save_plan_area

    window = QMainWindow()
    container = QWidget()
    layout = QVBoxLayout(container)
    bar = QgsMessageBar()
    canvas = QgsMapCanvas()
    layout.addWidget(bar)
    layout.addWidget(canvas)
    window.setCentralWidget(container)
    window.resize(900,700)
    window.show()
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem('EPSG:4326'))
    canvas.setExtent(QgsRectangle(5.0,51.4,5.02,51.42))
    previous = QgsMapToolPan(canvas)
    canvas.setMapTool(previous)
    class Iface:
        def mapCanvas(self): return canvas
        def messageBar(self): return bar
        def mainWindow(self): return window
        def setActiveLayer(self, layer): self.active_layer = layer; return True
    iface = Iface()
    dialog = LSNetontwerpDashboardDialog(iface, window)
    dialog.show()
    app.processEvents()
    assert dialog.draw_plan_button.text() == 'Tekenen…'
    assert dialog.draw_plan_button.isEnabled()
    buttons = Qt.MouseButton if hasattr(Qt,'MouseButton') else Qt
    keys = Qt.Key if hasattr(Qt,'Key') else Qt
    def click(x,y,button=None):
        QTest.mouseClick(canvas.viewport(), button or buttons.LeftButton, pos=QPoint(x,y))
        app.processEvents()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        dialog.output_edit.setText(folder)
        dialog.plan_edit.clear()
        dialog.no_plan.setChecked(True)
        QTest.mouseClick(dialog.draw_plan_button,buttons.LeftButton)
        app.processEvents()
        assert dialog.isHidden()
        session = dialog._plan_draw_session
        assert canvas.mapTool() == session.tool
        click(150,150)
        click(400,150)
        QTest.keyClick(canvas,keys.Key_Return)
        assert dialog._plan_draw_session is session
        assert not list(Path(folder).glob('*.gpkg'))
        QTest.keyClick(canvas,keys.Key_Escape)
        app.processEvents()
        assert dialog._plan_draw_session is None
        assert canvas.mapTool() == previous
        assert dialog.plan_edit.text() == '' and dialog.no_plan.isChecked()
        # Invalid self-crossing boundary stays editable and creates no file.
        dialog.draw_plan_button.click()
        session = dialog._plan_draw_session
        session.tool.points = [QgsPointXY(5,51.4),QgsPointXY(5.01,51.41),
                               QgsPointXY(5,51.41),QgsPointXY(5.01,51.4)]
        session.tool.finish()
        assert dialog._plan_draw_session is session
        assert not list(Path(folder).glob('*.gpkg'))
        session.cancel()
        # A save error keeps the drawing editable and the existing input intact.
        blocked = Path(folder)/'not_a_directory'
        blocked.write_text('keep me',encoding='utf-8')
        dialog.output_edit.setText(str(blocked))
        dialog.draw_plan_button.click()
        session = dialog._plan_draw_session
        session.tool.points = [QgsPointXY(5,51.4),QgsPointXY(5.01,51.4),QgsPointXY(5.01,51.41)]
        session.tool.finish()
        assert dialog._plan_draw_session is session
        assert dialog.plan_edit.text()=='' and blocked.read_text()=='keep me'
        session.cancel()
        dialog.output_edit.setText(folder)
        # Actual mouse input + undo + right-click completion.
        dialog.draw_plan_button.click()
        session = dialog._plan_draw_session
        for x,y in ((150,150),(450,150),(450,400),(300,300)):
            click(x,y)
        QTest.keyClick(canvas,keys.Key_Backspace)
        assert len(session.tool.points)==3
        click(150,400)
        click(160,410,buttons.RightButton)
        app.processEvents()
        assert dialog._plan_draw_session is None
        assert canvas.mapTool() == previous
        assert not dialog.no_plan.isChecked()
        assert dialog.widgets['only_plan'].isChecked()
        path = Path(dialog.plan_edit.text())
        assert path.exists() and path.parent == Path(folder)
        layer = iface.active_layer
        assert layer.isValid() and layer.featureCount()==1
        assert layer.crs().authid() == 'EPSG:28992'
        geometry = next(layer.getFeatures()).geometry()
        assert geometry.area()>0 and geometry.isGeosValid()
        assert len(geometry.asPolygon()[0]) == 5
        assert QgsProject.instance().mapLayer(layer.id()) is not None
        assert dialog.values()['plan'] == str(path)
        # The existing import workflow accepts the generated file directly.
        r = WorkflowRunner({}, lambda *args: None)
        imported,uri = r._write_plan(str(path),Path(folder)/'imported.gpkg')
        assert imported.isValid() and imported.featureCount()==1
        reopened = QgsVectorLayer(str(path),'saved','ogr')
        assert reopened.isValid() and reopened.featureCount()==1
        # Starting again and cancelling leaves the original input untouched.
        dialog.draw_plan_button.click()
        canvas.setMapTool(previous)
        app.processEvents()
        assert dialog._plan_draw_session is None
        assert dialog.plan_edit.text() == str(path)
        # Saved files always get unique names, including rapid successive drawings.
        second,second_path = save_plan_area(geometry,layer.crs(),folder)
        assert second_path != str(path) and Path(second_path).exists()
        from unittest.mock import patch
        with patch.object(QgsApplication,'qgisSettingsDirPath',return_value=folder):
            fallback,fallback_path = save_plan_area(geometry,layer.crs())
            assert Path(fallback_path).parent == Path(folder)/'ls_netontwerp_plangebieden'
            assert fallback.isValid()
        # Closing the wizard during drawing must not resurrect its window.
        dialog.draw_plan_button.click()
        dialog.reject()
        app.processEvents()
        assert dialog._plan_draw_session is None and not dialog.isVisible()
        assert canvas.mapTool() == previous
        if '--preview' in sys.argv:
            dialog.show()
            app.processEvents()
            assert dialog.grab().save(sys.argv[sys.argv.index('--preview')+1])
        print('PLAN_DRAWING_TEST_OK (mouse input, undo, validation, cancel, CRS, saved input, import, close)',flush=True)
    os._exit(0)


if __name__=='__main__':
    main()
