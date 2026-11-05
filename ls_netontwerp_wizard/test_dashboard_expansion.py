"""Expanded cluster actions remain separate, reachable and clickable."""
import os,sys
from pathlib import Path


def main():
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    from qgis.core import QgsApplication
    from qgis.PyQt.QtGui import QFont,QFontDatabase
    from qgis.PyQt.QtWidgets import QPushButton,QScrollArea
    from qgis.PyQt.QtCore import QPoint
    app=QgsApplication([],False);app.initQgis()
    for name in ('segoeui.ttf','segoeuib.ttf'):QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+name)
    app.setFont(QFont('Segoe UI',10))
    from ls_netontwerp_wizard.dashboard_warning_dialog import LSNetontwerpDashboardDialog
    dialog=LSNetontwerpDashboardDialog(None);dialog.show_home_page();dialog.show()
    out=Path(sys.argv[sys.argv.index('--captures')+1]) if '--captures' in sys.argv else None
    if out:out.mkdir(parents=True,exist_ok=True)
    for width,height in ((1180,740),(1440,960)):
        dialog.resize(width,height);app.processEvents()
        for expanded in (True,False,True):
            dialog.cluster_advanced_toggle.setChecked(expanded);app.processEvents();app.processEvents()
            card=dialog.findChild(__import__('qgis.PyQt.QtWidgets',fromlist=['QFrame']).QFrame,'stepCard4')
            buttons=[b for b in card.findChildren(QPushButton) if not b.isHidden()]
            assert len(buttons)==(9 if expanded else 1),[b.text() for b in buttons]
            for i,button in enumerate(buttons):
                assert button.height()>=34 and card.rect().contains(button.geometry()),(button.text(),button.geometry(),card.rect())
                assert button.width()>=button.fontMetrics().horizontalAdvance(button.text())+12
                for other in buttons[i+1:]:assert not button.geometry().intersects(other.geometry()),(button.text(),other.text())
                scroll=next(s for s in dialog.main_page.findChildren(QScrollArea) if s.isAncestorOf(button))
                scroll.ensureWidgetVisible(button);app.processEvents()
                center=button.mapTo(scroll.viewport(),button.rect().center())
                assert scroll.viewport().rect().contains(center),button.text()
                hit=scroll.viewport().childAt(center)
                assert hit is button or button.isAncestorOf(hit),button.text()
            if out and expanded:
                scroll.ensureWidgetVisible(card);app.processEvents();dialog.grab().save(str(out/f'Uitgeklapt-{width}.png'))
    print('DASHBOARD_EXPANSION_OK (two window sizes, repeated expand/collapse, all nine buttons separate, legible and mouse-reachable through scroll)',flush=True)
    os._exit(0)


if __name__=='__main__':main()
