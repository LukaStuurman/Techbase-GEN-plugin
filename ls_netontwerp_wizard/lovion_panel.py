"""QGIS station queue and asynchronous bundled LOVION worker."""
import json
import os
from pathlib import Path
import uuid

from qgis.PyQt.QtCore import QObject, QProcess, QStandardPaths, pyqtSignal
from qgis.PyQt.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
from qgis.core import QgsProject, QgsWkbTypes

from .lovion_session import LovionSession, selected_station_numbers, station_numbers, stations_in_plan
from .station_name_csv import find_master_asset_id_column

ACTIVE_WORKERS = set()
STATUS = {"pending": "Nog te verwerken", "running": "Bezig", "done": "Gekoppeld",
          "planned": "Gepland - geen aansluitingen", "manual": "Handmatige controle nodig", "error": "Niet voltooid"}


def run_storage_root():
    return Path(QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)) / "TechBase" / "LOVION"


class LovionWorker(QObject):
    event_received = pyqtSignal(dict)
    completed = pyqtSignal(str)

    def __init__(self, session, numbers, fixture=None):
        super().__init__(QApplication.instance())
        self.session, self.numbers = session, list(numbers)
        project = QgsProject.instance()
        # Windows PowerShell 5 and its .NET file operations cannot reliably
        # use long paths, even when Python can create the same directories.
        # Keep worker files independent of project, network and OneDrive paths.
        folder = run_storage_root() / session.data["id"] / uuid.uuid4().hex[:12]
        folder.mkdir(parents=True, exist_ok=True)
        self.report, self.cancel_file = folder / "result.json", folder / "cancel.flag"
        request = folder / "request.json"
        request.write_text(json.dumps({"Stations": self.numbers}), encoding="utf-8")
        self.process = QProcess(self)
        self.buffer, self.errors = b"", ""
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.readyReadStandardError.connect(self._stderr)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        script = Path(__file__).parent / "assets" / "lovion" / "Run-LovionExtractor.ps1"
        self.args = ["-NoLogo", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                     "-File", str(script), "-RequestPath", str(request), "-ReportPath", str(self.report),
                     "-CancelPath", str(self.cancel_file)]
        if fixture:
            self.args += ["-TestFixturePath", str(fixture)]
        self.program = str(Path(os.environ.get("SystemRoot", "C:/Windows")) /
                           "System32/WindowsPowerShell/v1.0/powershell.exe")
        self.finished = False
        project.cleared.connect(self.stop)
        QApplication.instance().aboutToQuit.connect(self.shutdown)

    def start(self):
        ACTIVE_WORKERS.add(self)
        self.process.start(self.program, self.args)

    def stop(self):
        if not self.finished:
            self.cancel_file.write_text("stop", encoding="utf-8")

    def shutdown(self):
        self.stop()
        # Allow native finally blocks to release held keys before Qt destroys
        # the process object during application shutdown.
        if not self.finished:
            self.process.waitForFinished(30000)

    def _read(self):
        self.buffer += bytes(self.process.readAllStandardOutput())
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            try:
                event = json.loads(line.decode("utf-8-sig"))
                if isinstance(event, dict):
                    self.event_received.emit(event)
            except (ValueError, UnicodeError):
                pass

    def _stderr(self):
        self.errors += bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")

    def _process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.errors += "LOVION-verwerking kon niet starten. Windows PowerShell is niet beschikbaar."
            self._finished(-1, QProcess.ExitStatus.CrashExit)

    def _finished(self, code, _status):
        if self.finished:
            return
        self.finished = True
        self._read()
        self._stderr()
        project = QgsProject.instance()
        try:
            project.cleared.disconnect(self.stop)
            QApplication.instance().aboutToQuit.disconnect(self.shutdown)
        except (TypeError, RuntimeError):
            pass
        try:
            if project.mapLayer(self.session.layer.id()) is not self.session.layer:
                message = f"Project gewijzigd: resultaten bewaard in {self.report.parent}."
            elif self.report.exists():
                result = self.session.apply_report(self.report, self.numbers)
                done = sum(entry["status"] in {"done", "planned"} for entry in result.values())
                linked = sum(self.session.data["stations"][n]["matched"] for n in self.numbers)
                message = f"Ronde afgerond: {done}/{len(self.numbers)} stations gecontroleerd; {linked} aansluitingen gekoppeld."
                if code or done < len(self.numbers):
                    message += " Controleer de stationsstatus en start de resterende stations opnieuw."
            else:
                message = self.errors.strip() or "Geen LOVION-resultaat ontvangen. Start de resterende stations opnieuw."
        except Exception as exc:
            message = f"Resultaat niet toegepast: {exc} Rapport bewaard in {self.report.parent}."
        ACTIVE_WORKERS.discard(self)
        self.completed.emit(message)
        self.deleteLater()


def stop_active_workers():
    for worker in list(ACTIVE_WORKERS):
        worker.stop()


class LovionStationPanel(QWidget):
    def __init__(self, page):
        super().__init__(page)
        self.page, self.worker = page, None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.controls = QGroupBox("Stations uit LOVION ophalen")
        form = QFormLayout(self.controls)
        note = QLabel("Open in LOVION de lijst LS stroomtransformatorgroep, met alleen de eerste rij geselecteerd. "
                      "Zet LOVION volledig zichtbaar op het linker scherm. Na starten heb je vijf seconden; "
                      "gebruik daarna de muis en het toetsenbord niet. Zelf de muis bewegen stopt de verwerking.")
        note.setWordWrap(True)
        form.addRow(note)
        self.stations, self.field, self.plan = QComboBox(), QComboBox(), QComboBox()
        form.addRow("Stationslaag", self.stations)
        form.addRow("Kolom stationsnummer", self.field)
        form.addRow("Plangebied", self.plan)
        self.stations.currentIndexChanged.connect(self.refresh_fields)
        row = QHBoxLayout()
        self._button(row, "Stations op kaart selecteren", lambda: page.select_on_map(self.stations))
        self._button(row, "Geselecteerde stations toevoegen", self.add_selected)
        form.addRow(row)
        row = QHBoxLayout()
        self._button(row, "Plangebied op kaart selecteren", lambda: page.select_on_map(self.plan))
        self._button(row, "Stations in plangebied toevoegen", self.add_plan)
        form.addRow(row)
        hint = QLabel("Bij een geselecteerd plangebied worden alleen die vlakken gebruikt; anders alle vlakken uit de gekozen laag.")
        hint.setWordWrap(True)
        form.addRow(hint)
        self.manual = QPlainTextEdit()
        self.manual.setPlaceholderText("Stationsnummers, gescheiden door komma, puntkomma of een nieuwe regel")
        self.manual.setMaximumHeight(75)
        form.addRow("Zelf stations toevoegen", self.manual)
        add = QPushButton("Stationsnummers toevoegen")
        add.clicked.connect(self.add_manual)
        form.addRow(add)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Station", "Status", "LOVION-rijen", "Gekoppeld"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(170)
        self.table.horizontalHeader().setStretchLastSection(True)
        form.addRow(self.table)
        row = QHBoxLayout()
        self._button(row, "Selectie verwijderen", self.remove)
        self._button(row, "Selectie opnieuw klaarzetten", self.retry)
        self._button(row, "Alles resetten", self.reset)
        form.addRow(row)
        explanation = QLabel("Een volgende ronde verwerkt alleen nieuwe of opnieuw klaargezette stations. "
                             "Verwijderen en resetten herstellen de vorige stationswaarde van de gekoppelde aansluitingen.")
        explanation.setWordWrap(True)
        form.addRow(explanation)
        layout.addWidget(self.controls)
        row = QHBoxLayout()
        self.start_button = self._button(row, "LOVION starten (resterende stations)", self.start)
        self.stop_button = self._button(row, "Stoppen", self.stop)
        self.stop_button.setEnabled(False)
        layout.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        layout.addWidget(self.progress)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(100)
        self.log.document().setMaximumBlockCount(250)
        layout.addWidget(self.log)
        page.target_combo.currentIndexChanged.connect(self.refresh_table)

    def _button(self, row, text, action):
        button = QPushButton(text)
        button.clicked.connect(lambda _checked=False: self.guard(action))
        row.addWidget(button)
        return button

    def guard(self, action):
        try:
            action()
        except Exception as exc:
            self.status.setText(str(exc))

    def session(self):
        return LovionSession(self.page.layer(self.page.target_combo))

    def refresh(self):
        if self.worker:
            return
        for combo, polygon in ((self.stations, False), (self.plan, True)):
            old = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            preferred = None
            for layer in QgsProject.instance().mapLayers().values():
                if not hasattr(layer, "fields"):
                    continue
                kind = QgsWkbTypes.geometryType(layer.wkbType())
                if (polygon and kind == QgsWkbTypes.PolygonGeometry) or (not polygon and kind == QgsWkbTypes.PointGeometry):
                    combo.addItem(layer.name(), layer.id())
                    if (polygon and "plangebied" in layer.name().casefold()) or (
                            not polygon and layer.customProperty("LSNetontwerp/review_station_layer", False)):
                        preferred = layer.id()
            index = combo.findData(old if combo.findData(old) >= 0 else preferred)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.blockSignals(False)
        self.refresh_fields()
        self.refresh_table()

    def refresh_fields(self):
        old = self.field.currentText()
        self.field.clear()
        layer = self.page.layer(self.stations)
        if layer:
            self.field.addItems([f.name() for f in layer.fields()])
            preferred = self.page.host._workflow_field_defaults().get("field_station_name", "Station")
            index = self.field.findText(old or preferred)
            if index < 0:
                index = self.field.findText(preferred)
            if index >= 0:
                self.field.setCurrentIndex(index)

    def refresh_table(self):
        self.table.setRowCount(0)
        layer = self.page.layer(self.page.target_combo)
        if layer is None:
            return
        data = self.worker.session.data if self.worker else LovionSession(layer).data
        for number, entry in data["stations"].items():
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, value in enumerate((number, STATUS.get(entry["status"], entry["status"]), entry.get("rows", 0), entry.get("matched", 0))):
                item = QTableWidgetItem(str(value))
                item.setToolTip(entry.get("note", "") or (f"{entry.get('planned', 0)} geplande trafo's" if entry.get("planned") else ""))
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents()

    def add(self, numbers):
        if not numbers:
            raise ValueError("Geen stationsnummers gevonden.")
        count = self.session().add(numbers)
        self.refresh_table()
        self.status.setText(f"{count} nieuwe stations toegevoegd.")

    def add_selected(self):
        self.add(selected_station_numbers(self.page.layer(self.stations), self.field.currentText()))

    def add_plan(self):
        self.add(stations_in_plan(self.page.layer(self.stations), self.field.currentText(), self.page.layer(self.plan)))

    def add_manual(self):
        self.guard(lambda: self.add(station_numbers(self.manual.toPlainText())))

    def selection(self):
        numbers = [self.table.item(index.row(), 0).text() for index in self.table.selectionModel().selectedRows()]
        if not numbers:
            raise ValueError("Selecteer eerst stations in de lijst.")
        return numbers

    def remove(self):
        self.session().remove(self.selection())
        self.refresh_table()
        self.status.setText("Stations verwijderd en eerdere aansluitingswaarden hersteld.")

    def retry(self):
        self.session().retry(self.selection())
        self.refresh_table()
        self.status.setText("De geselecteerde stations worden in de volgende ronde opnieuw verwerkt.")

    def reset(self):
        self.session().reset()
        self.refresh_table()
        self.status.setText("Stationslijst gereset en eerdere aansluitingswaarden hersteld.")

    def start(self, fixture=None):
        if self.worker:
            return
        session = self.session()
        if session.layer.isEditable():
            raise ValueError("Sla eerst de laagbewerkingen op.")
        if find_master_asset_id_column([f.name() for f in session.layer.fields()]) is None:
            raise ValueError("De ontwerpstroomlaag mist Master Asset ID.")
        numbers = session.pending()
        if not numbers:
            raise ValueError("Voeg stations toe of zet een selectie opnieuw klaar.")
        self.worker = LovionWorker(session, numbers, fixture)
        self.worker.event_received.connect(self.on_event)
        self.worker.completed.connect(self.on_completed)
        self.controls.setEnabled(False)
        self.page.target_combo.setEnabled(False)
        self.page.station_group.setEnabled(False)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.progress.setRange(0, len(numbers))
        self.progress.setValue(0)
        self.log.clear()
        if not fixture:
            self.page.host.showMinimized()
        self.worker.start()

    def stop(self):
        if self.worker:
            self.worker.stop()
            self.status.setText("Stop aangevraagd; de huidige actie wordt veilig afgesloten.")
            self.stop_button.setEnabled(False)

    def on_event(self, event):
        message = event.get("message", "")
        self.status.setText(message)
        self.log.appendPlainText(message)
        if event.get("type") == "station_started":
            number = event.get("station")
            for row in range(self.table.rowCount()):
                if self.table.item(row, 0).text() == number:
                    self.table.item(row, 1).setText("Bezig")
        if event.get("type") == "station_finished":
            self.progress.setValue(self.progress.value() + 1)
            number = event.get("station")
            for row in range(self.table.rowCount()):
                if self.table.item(row, 0).text() == number:
                    self.table.item(row, 1).setText("Verwerkt - controle na ronde")

    def on_completed(self, message):
        self.worker = None
        self.controls.setEnabled(True)
        self.page.target_combo.setEnabled(True)
        self.page.station_group.setEnabled(True)
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status.setText(message)
        self.refresh_table()
        self.page.host.showNormal()
        self.page.host.raise_()
        if self.page.host.iface:
            self.page.host.iface.mapCanvas().refresh()
