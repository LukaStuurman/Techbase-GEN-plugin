"""Keep automatic values distinct from deliberate edits in current fields."""

from qgis.PyQt.QtCore import QEvent, QObject, QSignalBlocker, Qt


class _CommitCurrentInput(QObject):
    """Enter commits the number without activating a dialog navigation button."""

    def eventFilter(self, watched, event):
        key_press = QEvent.Type.KeyPress if hasattr(QEvent, "Type") else QEvent.KeyPress
        keys = Qt.Key if hasattr(Qt, "Key") else Qt
        if event.type() == key_press and event.key() in (keys.Key_Return, keys.Key_Enter):
            self.parent().interpretText()
            self.parent().editingFinished.emit()
            return True
        return False


def set_current_values(spins, values):
    # Loading a preset or selection must not count as a manual edit.
    blockers = [QSignalBlocker(spin) for spin in spins]
    for spin, value in zip(spins, values):
        spin.setValue(value)
    del blockers


def connect_current_edits(spins, manual_checkbox):
    for spin in spins:
        spin.valueChanged.connect(lambda _value, checkbox=manual_checkbox: checkbox.setChecked(True))
        spin._current_commit_filter = _CommitCurrentInput(spin)
        spin.installEventFilter(spin._current_commit_filter)
        spin.lineEdit().installEventFilter(spin._current_commit_filter)


def has_manual_currents(feature):
    index = feature.fields().lookupField("HerstelHandmatig")
    return index >= 0 and str(feature[index]) == "1"
