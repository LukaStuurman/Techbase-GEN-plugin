"""Expanded cluster actions and progress remain separate and reachable."""
import os
from pathlib import Path
import sys


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from qgis.core import QgsApplication
    from qgis.PyQt.QtCore import QPoint, QRect
    from qgis.PyQt.QtGui import QFont, QFontDatabase
    from qgis.PyQt.QtWidgets import QFrame, QLabel, QPushButton, QScrollArea

    app = QgsApplication([], False)
    app.initQgis()
    for name in ('segoeui.ttf', 'segoeuib.ttf'):
        path = Path('C:/Windows/Fonts') / name
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont('Segoe UI', 10))
    from ls_netontwerp_wizard.dashboard_warning_dialog import LSNetontwerpDashboardDialog

    dialog = LSNetontwerpDashboardDialog(None)
    dialog.show_home_page()
    dialog.show()
    card = dialog.findChild(QFrame, 'stepCard4')
    toggle = dialog.cluster_advanced_toggle
    scroll = next(s for s in dialog.main_page.findChildren(QScrollArea) if s.isAncestorOf(card))
    out = Path(sys.argv[sys.argv.index('--captures') + 1]) if '--captures' in sys.argv else None
    if out:
        out.mkdir(parents=True, exist_ok=True)

    def settle():
        for _ in range(4):
            app.sendPostedEvents()
            app.processEvents()

    def rect_in(widget, parent):
        return QRect(widget.mapTo(parent, QPoint()), widget.size())

    checks = 0
    for width, height in ((1180, 740), (1440, 960)):
        dialog.resize(width, height)
        for progress in ('hidden', 'running', 'complete'):
            if progress == 'hidden':
                dialog.progress_group.hide()
            else:
                update = dialog._make_progress('Clustering voorbereiden…')
                update(45, 'Kabelroutes berekenen…')
                if progress == 'complete':
                    dialog._finish_progress(100)
            for expanded in (True, False, True):
                state = (width, height, progress, expanded)
                toggle.setChecked(expanded)
                settle()
                buttons = [b for b in card.findChildren(QPushButton) if not b.isHidden()]
                assert len(buttons) == (9 if expanded else 1), (state, [b.text() for b in buttons])

                # The whole card, including wrapped notes and its last checkbox,
                # must participate in the scroll content's current geometry.
                assert dialog._dashboard_widget.rect().contains(rect_in(card, dialog._dashboard_widget)), state
                controls = [*buttons, toggle, *card.findChildren(QLabel)]
                for control in controls:
                    assert card.rect().contains(rect_in(control, card)), (state, control.geometry(), card.rect())
                for note in card.findChildren(QLabel):
                    assert note.height() >= note.heightForWidth(note.width()), (state, note.text())
                assert toggle.geometry().top() > buttons[-1].geometry().bottom(), state
                assert toggle.geometry().bottom() <= card.height() - card.layout().contentsMargins().bottom(), state

                for index, button in enumerate(buttons):
                    assert button.height() >= 34, (state, button.text())
                    assert button.width() >= button.fontMetrics().horizontalAdvance(button.text()) + 12
                    for other in buttons[index + 1:]:
                        assert not button.geometry().intersects(other.geometry()), (state, button.text(), other.text())
                    scroll.ensureWidgetVisible(button)
                    settle()
                    center = button.mapTo(scroll.viewport(), button.rect().center())
                    assert scroll.viewport().rect().contains(center), (state, button.text())
                    hit = scroll.viewport().childAt(center)
                    assert hit is button or button.isAncestorOf(hit), (state, button.text())

                scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
                settle()
                assert scroll.viewport().rect().contains(rect_in(toggle, scroll.viewport())), state
                if progress != 'hidden':
                    # Progress is a fixed row below the scroll viewport, also
                    # after repeatedly expanding and collapsing the card.
                    assert not scroll.isAncestorOf(dialog.progress_group), state
                    progress_rect = rect_in(dialog.progress_group, dialog.main_page)
                    assert dialog.main_page.rect().contains(progress_rect), state
                    assert progress_rect.top() > rect_in(scroll, dialog.main_page).bottom(), state
                    for widget in (dialog.progress_summary, dialog.progress_bar):
                        assert dialog.progress_group.rect().contains(rect_in(widget, dialog.progress_group)), state
                    for button in buttons:
                        assert not progress_rect.intersects(rect_in(button, dialog.main_page)), (state, button.text())
                if out and expanded:
                    dialog.grab().save(str(out / f'Uitgeklapt-{width}-{progress}.png'))
                checks += 1
    print(f'DASHBOARD_EXPANSION_OK ({checks} states: two sizes, repeated expand/collapse, hidden/running/completed progress, full checkbox and reachable buttons)', flush=True)
    os._exit(0)


if __name__ == '__main__':
    main()
