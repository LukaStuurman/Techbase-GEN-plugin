"""The real editor has one readable progress meter and stable controls."""
import os,sys,tempfile
from pathlib import Path


def main():
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    from qgis.core import QgsApplication
    from qgis.PyQt.QtGui import QFont,QFontDatabase
    from qgis.PyQt.QtWidgets import QProgressBar,QPushButton,QScrollArea,QLabel
    app=QgsApplication([],False);app.initQgis()
    for name in ('segoeui.ttf','segoeuib.ttf'):QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+name)
    app.setFont(QFont('Segoe UI',10))
    from ls_netontwerp_wizard.test_guided_cluster_editing import fixture
    from ls_netontwerp_wizard.dashboard_warning_dialog import LSNetontwerpDashboardDialog
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        points,stations,*_=fixture(Path(tmp))
        host=LSNetontwerpDashboardDialog(None)
        host._open_visual_cluster_editor('result','move')
        editor=host._dashboard_visual_cluster_dialog;guide=editor.guide
        errors=[]
        def record_error(message):
            import traceback;traceback.print_exc();errors.append(str(message))
        editor._error=record_error
        points.selectByIds([4]);guide.target_combo.setCurrentIndex(guide.target_combo.findData(2))
        assert isinstance(guide.capacity,QLabel) and '87.5%' in guide.capacity.text()
        out=Path(sys.argv[sys.argv.index('--captures')+1]) if '--captures' in sys.argv else None
        if out:out.mkdir(parents=True,exist_ok=True)
        for width,height in ((1180,740),(1440,960)):
            host.resize(width,height);host.show();app.processEvents()
            def in_progress():
                guide.progress(48,'Kabelroutes voor de aangepaste clusters berekenen')
                app.processEvents();app.processEvents()
                bars=[b for b in editor.findChildren(QProgressBar) if b.isVisible()]
                assert bars==[guide.progress_bar]
                assert guide.progress_bar.height()>=24 and not guide.progress_bar.isTextVisible()
                assert guide.progress_label.isVisible() and guide.progress_label.text().startswith('48%')
                widgets=[editor.preview_label,guide.capacity,guide.safety_label,guide.progress_bar,guide.progress_label]
                for i,widget in enumerate(widgets):
                    assert guide.review_group.rect().contains(widget.geometry()),(widget.geometry(),guide.review_group.rect())
                    for other in widgets[i+1:]:assert not widget.geometry().intersects(other.geometry())
                    if isinstance(widget,QLabel):
                        assert widget.height()>=widget.heightForWidth(widget.width()),widget.text()
                assert guide.cancel.isVisible() and guide.cancel.height()>=34 and guide.cancel.isEnabled()
                assert not guide.commit.isEnabled()
                assert editor.status_label.isHidden()
                refresh=next(b for b in editor.findChildren(QPushButton) if b.text()=='Lagen/modus opnieuw zoeken')
                assert editor.options_group.isAncestorOf(refresh) and not refresh.isVisible()
                scroll=next(s for s in editor.findChildren(QScrollArea) if s.isAncestorOf(guide.review_group))
                scroll.ensureWidgetVisible(guide.review_group);app.processEvents()
                if out:host.grab().save(str(out/f'Clustereditor-voortgang-{width}.png'))
            guide.run_task(in_progress)
            assert not errors,errors
            assert not guide.busy and guide.cancel.isHidden()
            points.selectByIds([4]);guide.target_combo.setCurrentIndex(guide.target_combo.findData(2))
        print('CLUSTER_EDITOR_PROGRESS_OK (one meter, separate capacity text, readable percent/stage, non-overlapping controls, fixed footer, busy/idle at two sizes)',flush=True)
    os._exit(0)


if __name__=='__main__':main()
