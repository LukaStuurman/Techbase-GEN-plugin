"""Visible dashboard workflow for cable-group based station attribution."""
from datetime import datetime
from pathlib import Path
import weakref

from qgis.PyQt import sip
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog,
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget)
from qgis.core import QgsApplication, QgsProject, QgsTask, QgsVectorLayer

from .schema_linking import build_mapping, compare_connections, export_report, attach_connection_cables
from .schema_dxf import build_dxf_mapping
from .schema_link_io import (apply_proposal, connection_records, eligible,
    station_records, undo_proposal, connection_cable_records, station_spatial_records)


class SchemaLinkPage(QWidget):
    def __init__(self, host):
        super().__init__(host)
        self.host, self.proposal, self.task = host, None, None
        self._station_snapshot = None
        self._cable_snapshot = None
        self._spatial_snapshot = None
        root = QVBoxLayout(self)
        host._add_subpage_header(root, '1.4. Voedend station uit LS-schema',
                                 'Kabelcode → veld en rail → verdeelkast → station')
        note = QLabel('Kies XML/Excel van veld, rail en smelt, of DXF-schema’s met geografische stationsankers in RD New. '
            'De DXF-route gebruikt echte eindpunten, mofsymbolen, smeltposities en de tekstvolgorde langs witte verwijslijnen. '
            'Een kruising of verwijslijn is geen elektrische verbinding. Onduidelijke labels, veldrollen en stationsankers blijven onbehandeld. '
            'In de XML-route controleert een LS-DXF ook fysieke veldnummers; OV vult daar alleen de herkomstregistratie aan. '
            'Een controle-CSV test uitsluitend op Master Asset ID en vult de voorspelling niet in.')
        note.setWordWrap(True); root.addWidget(note)
        group = QGroupBox('1. Bronnen en lagen'); form = QFormLayout(group)
        self.source_group = group
        self.method = QComboBox()
        self.method.addItem('XML + Excel van veld/rail/smelt (DXF-controle optioneel)', 'xml')
        self.method.addItem('DXF-schema’s + geografische stationslaag (zonder schema-XML/Excel)', 'dxf')
        form.addRow('Herleidingsmethode',self.method)
        self.files = {}
        self.file_buttons = {}
        for key, label, pattern in (('xml', 'Veld/rail/smelt XML', 'XML (*.xml)'),
            ('excel', 'Bijbehorende Excel', 'Excel (*.xlsx)'), ('dxf', 'LS-schema DXF (optioneel)', 'DXF (*.dxf)'),
            ('ov_dxf', 'OV-schema DXF (optioneel)', 'DXF (*.dxf)'),
            ('reference', 'Controle-CSV (optioneel)', 'CSV (*.csv)')):
            row = QHBoxLayout(); edit = QLineEdit(); button = QPushButton('Kiezen…')
            edit.setClearButtonEnabled(True)
            edit.setObjectName('schema_' + key); self.files[key] = edit
            self.file_buttons[key] = button
            edit.setText(str(host.settings.value(host.SETTINGS_PREFIX + 'schema_' + key, '')))
            button.clicked.connect(lambda checked=False, k=key, p=pattern: self.choose_file(k, p))
            edit.textChanged.connect(self.invalidate); row.addWidget(edit, 1); row.addWidget(button); form.addRow(label, row)
        self.target = QComboBox(); self.stations = QComboBox(); self.cables = QComboBox()
        self.asset = QComboBox(); self.cable = QComboBox()
        form.addRow('Aansluitingenlaag', self.target); form.addRow('Master Asset ID-kolom', self.asset)
        form.addRow('Kabelgroepkolom', self.cable); form.addRow('Stationslaag met SAP-nummer', self.stations)
        form.addRow('Aansluitkabelbron (optioneel, object-ID-relaties)', self.cables)
        refresh = QPushButton('Lagen vernieuwen'); refresh.clicked.connect(self.refresh); form.addRow(refresh)
        self.target.currentIndexChanged.connect(self.columns)
        for combo in (self.target, self.stations, self.cables, self.asset, self.cable): combo.currentIndexChanged.connect(self.invalidate)
        root.addWidget(group)
        self.sources_toggle = QPushButton('Bronnen en lagen verbergen')
        self.sources_toggle.clicked.connect(self.toggle_sources)
        root.addWidget(self.sources_toggle)
        self.reference_only = QCheckBox('Bij een controle-CSV alleen overeenkomende koppelingen toepassen')
        self.reference_only.setChecked(True)
        self.replace = QCheckBox('Ook bestaande stationsnamen vervangen door gecontroleerde voorstellen')
        self.reference_only.toggled.connect(self.count_eligible); self.replace.toggled.connect(self.count_eligible)
        root.addWidget(self.reference_only); root.addWidget(self.replace)
        self.status = QLabel('Maak eerst een voorstel. Er wordt nog niets aan de aansluitingen gewijzigd.')
        self.status.setWordWrap(True); root.addWidget(self.status)
        self.filter = QComboBox(); self.filter.addItems(['Alle aansluitingen', 'CSV-afwijkingen', 'Niet herleid', 'Toepasbaar'])
        self.filter.currentIndexChanged.connect(self.show_rows); root.addWidget(self.filter)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(['Master Asset ID', 'Kabelgroep', 'Voorgesteld station', 'Bestaand station', 'Referentiestation', 'CSV-controle', 'Status', 'Herkomst', 'Voedingspad'])
        edit_enum = getattr(QAbstractItemView, 'EditTrigger', QAbstractItemView)
        selection_enum = getattr(QAbstractItemView, 'SelectionBehavior', QAbstractItemView)
        self.table.setEditTriggers(getattr(edit_enum, 'NoEditTriggers', getattr(QAbstractItemView, 'NoEditTriggers', 0)))
        self.table.setSelectionBehavior(getattr(selection_enum, 'SelectRows', getattr(QAbstractItemView, 'SelectRows', 1)))
        self.table.setMinimumHeight(190); root.addWidget(self.table, 1)
        row = QHBoxLayout(); root.addLayout(row)
        self.check_button = QPushButton('Voorstel berekenen'); self.check_button.clicked.connect(self.analyze)
        self.cancel_button = QPushButton('Berekening stoppen'); self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.setEnabled(False)
        self.apply_button = QPushButton('Gecontroleerde koppelingen toepassen'); self.apply_button.clicked.connect(self.apply)
        self.undo_button = QPushButton('Laatste toepassing terugdraaien'); self.undo_button.clicked.connect(self.undo)
        self.export_button = QPushButton('Controlerapport opslaan'); self.export_button.clicked.connect(self.export)
        self.map_button = QPushButton('Tabelselectie op kaart'); self.map_button.clicked.connect(self.select_map)
        for button in (self.check_button, self.apply_button, self.undo_button, self.export_button, self.map_button, self.cancel_button):row.addWidget(button)
        self.apply_button.setEnabled(False); self.export_button.setEnabled(False)
        self.method.currentIndexChanged.connect(self.method_changed)
        self.eligible_label = QLabel(''); root.addWidget(self.eligible_label)
        QgsProject.instance().cleared.connect(self.project_cleared)

    def layer(self, combo):
        return QgsProject.instance().mapLayer(combo.currentData())

    def method_changed(self, *args):
        for key in ('xml','excel'):
            self.files[key].setEnabled(self.method.currentData()=='xml')
            self.file_buttons[key].setEnabled(self.method.currentData()=='xml')
        self.invalidate()

    def toggle_sources(self):
        self.source_group.setVisible(self.source_group.isHidden())
        self.sources_toggle.setText('Bronnen en lagen tonen' if self.source_group.isHidden() else 'Bronnen en lagen verbergen')

    def choose_file(self, key, pattern):
        path, _ = QFileDialog.getOpenFileName(self, 'Kies ' + key, self.files[key].text(), pattern)
        if path:
            self.files[key].setText(path)
            self.host.settings.setValue(self.host.SETTINGS_PREFIX + 'schema_' + key, path)

    def invalidate(self, *args):
        self.proposal = None
        if hasattr(self, 'apply_button'):
            self.apply_button.setEnabled(False); self.export_button.setEnabled(False)
            self.table.setRowCount(0); self.eligible_label.clear()

    def project_cleared(self):
        self.cancel(); self.invalidate()

    def refresh(self):
        if self.task: return
        project = QgsProject.instance()
        state = getattr(self.host, 'prepared_state', None) or {}
        if state.get('points_gpkg') and not any(
                isinstance(layer, QgsVectorLayer) and layer.source().split('|')[0].replace('\\', '/') == str(state['points_gpkg']).replace('\\', '/')
                for layer in project.mapLayers().values()):
            source = QgsVectorLayer(str(state['points_gpkg']) + '|layername=' + state.get('points_layer', '04_ls_aansluitingen'),
                                    'LS-aansluitingen ontwerpstroom', 'ogr')
            if source.isValid():
                source.setCustomProperty('LSNetontwerp/review_current_layer', True); project.addMapLayer(source)
        previous = (self.target.currentData(), self.stations.currentData(), self.cables.currentData())
        had_cables = self.cables.count() > 0
        for combo in (self.target, self.stations, self.cables):combo.blockSignals(True);combo.clear()
        self.cables.addItem('Niet gebruiken — alleen de kabelcodes van aansluitingen', None)
        targets = []
        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer): continue
            fields = set(layer.fields().names())
            if any('masterassetid' == ''.join(c.lower() for c in name if c.isalnum()) for name in fields) and not {'Cluster', 'Ontwerp_A'}.issubset(fields):
                targets.append(layer)
            if 'Station' in fields and any(c in fields for c in ('trafo_sap_structure_indicator', 'sap_structure_indicator')):
                self.stations.addItem(layer.name(), layer.id())
            if {'id','Kabel Subgroep','service_connections_id','cable_status','change_state'}.issubset(fields):
                self.cables.addItem(layer.name(), layer.id())
        targets.sort(key=lambda layer: not bool(layer.customProperty('LSNetontwerp/review_current_layer', False)))
        for layer in targets: self.target.addItem(layer.name(), layer.id())
        for combo, old in zip((self.target, self.stations, self.cables), previous):
            index = combo.findData(old)
            if index >= 0: combo.setCurrentIndex(index)
            combo.blockSignals(False)
        if not had_cables and self.cables.count()>1:self.cables.setCurrentIndex(1)
        self.columns(); self.invalidate()

    def columns(self, *args):
        layer = self.layer(self.target)
        self.asset.clear(); self.cable.clear()
        if layer is None:return
        names = layer.fields().names()
        self.asset.addItems(names); self.cable.addItems(names)
        asset = next((n for n in names if ''.join(c.lower() for c in n if c.isalnum()) == 'masterassetid'), '')
        cable = next((n for n in ('Kabel Subgroep', 'Kabel Subgroep Nummer', 'Kabel Subgroepen', 'cable_subgroup_number', 'group_number') if n in names), '')
        self.asset.setCurrentText(asset); self.cable.setCurrentText(cable)

    def analyze(self):
        if self.task:return
        self.invalidate()
        try:
            paths = {k: edit.text().strip() for k, edit in self.files.items()}
            method = self.method.currentData()
            if method=='xml' and (not paths['xml'] or not paths['excel']):
                raise ValueError('Kies de schema-XML en Excel, of kies de DXF-methode bovenaan bij Herleidingsmethode.')
            connections, digest = connection_records(self.layer(self.target), self.asset.currentText(), self.cable.currentText())
            stations = station_records(self.layer(self.stations)); self._station_snapshot = stations
            anchors = station_spatial_records(self.layer(self.stations)) if method=='dxf' else None
            self._spatial_snapshot = anchors
            cables = connection_cable_records(self.layer(self.cables)); self._cable_snapshot = cables
            connections = attach_connection_cables(connections, cables)
            signature = (method,self.target.currentData(), self.stations.currentData(), self.cables.currentData(), self.asset.currentText(), self.cable.currentText(), tuple(paths.values()))
            self.check_button.setEnabled(False); self.cancel_button.setEnabled(True)
            self.status.setText('Schematische verbindingen volgen en onafhankelijk op Master Asset ID vergelijken…')
            page_ref = weakref.ref(self)
            def work(task):
                mapping = (build_dxf_mapping(paths['dxf'], paths['ov_dxf'], anchors, task.isCanceled) if method=='dxf'
                    else build_mapping(paths['xml'], paths['excel'], paths['dxf'], canceled=task.isCanceled, ov_dxf_path=paths['ov_dxf']))
                if task.isCanceled(): raise ValueError('Herleiding geannuleerd; niets gewijzigd.')
                result = compare_connections(mapping, connections, stations, paths['reference'])
                result['layer_hash'] = digest
                return result
            def finished(exception, result=None):
                page = page_ref()
                if page is None or sip.isdeleted(page):return
                page.task = None; page.check_button.setEnabled(True); page.cancel_button.setEnabled(False)
                current = (page.method.currentData(),page.target.currentData(), page.stations.currentData(), page.cables.currentData(), page.asset.currentText(), page.cable.currentText(), tuple(e.text().strip() for e in page.files.values()))
                if current != signature:
                    page.status.setText('Invoer gewijzigd tijdens berekening; maak een nieuw voorstel.'); return
                if exception or not result:
                    page.status.setText(str(exception or 'Berekening geannuleerd.')); return
                page.proposal = result; page.export_button.setEnabled(True)
                page.source_group.hide(); page.sources_toggle.setText('Bronnen en lagen tonen')
                comparison = result['comparison']
                verification = (f"CSV: {comparison.get('Gelijk', 0)} gelijk, {comparison.get('Afwijkend', 0)} afwijkend, "
                    f"{comparison.get('Niet herleid', 0)} niet herleid; {len(result['reference_missing_in_layer'])} referentie-ID's buiten deze laag. "
                    if result['reference_file'] else 'Zonder controle-CSV berekend. ')
                page.status.setText(f"{len(result['rows'])} aansluitingen; {result['summary'].get('Herleid', 0)} herleid. "
                    + verification +
                    f"{len(result['mapping']['issues'])} schema-controles. Zie rapport voor alle gevallen.")
                page.show_rows(); page.count_eligible()
            self.task = QgsTask.fromFunction('Voedend station uit LS-schema', work, on_finished=finished)
            QgsApplication.taskManager().addTask(self.task)
        except Exception as exc:
            self.status.setText(str(exc)); self.check_button.setEnabled(True); self.cancel_button.setEnabled(False)

    def cancel(self):
        if self.task:self.task.cancel()

    def reference_guard(self):
        return bool(self.proposal and self.proposal.get('reference_file') and self.reference_only.isChecked())

    def count_eligible(self, *args):
        count = sum(eligible(row, self.reference_guard(), self.replace.isChecked()) for row in self.proposal['rows']) if self.proposal else 0
        self.apply_button.setEnabled(count > 0 and not self.task)
        self.eligible_label.setText(f'{count} toepasbare koppelingen. CSV-afwijkingen en dubbele ID’s worden altijd overgeslagen. Bronlaag wijzigen; clustering zo nodig opnieuw uitvoeren.')
        if self.filter.currentIndex() == 3:self.show_rows()

    def show_rows(self, *args):
        rows = self.proposal['rows'] if self.proposal else []
        mode = self.filter.currentIndex()
        if mode == 1: rows = [r for r in rows if r['Controle'] in ('Afwijkend', 'Dubbel referentie-ID', 'Tegenstrijdige referentie')]
        elif mode == 2: rows = [r for r in rows if r['Status'] != 'Herleid']
        elif mode == 3: rows = [r for r in rows if eligible(r, self.reference_guard(), self.replace.isChecked())]
        self.table.setRowCount(len(rows)); self._visible = rows
        for index, row in enumerate(rows):
            for col, key in enumerate(('Master Asset ID', 'Kabelgroep', 'Station', 'Bestaand station', 'Referentiestation', 'Controle', 'Status', 'Herkomst', 'Pad')):
                item = QTableWidgetItem(row[key]); item.setToolTip(row['Reden'] or row[key]); self.table.setItem(index, col, item)
        self.table.resizeColumnsToContents(); self.table.setColumnWidth(7, 270); self.table.setColumnWidth(8, 330)

    def apply(self):
        try:
            if not self.proposal:raise ValueError('Maak eerst een nieuw voorstel.')
            if station_records(self.layer(self.stations)) != self._station_snapshot:raise ValueError('Stationslaag gewijzigd; bereken opnieuw.')
            if self._spatial_snapshot is not None and station_spatial_records(self.layer(self.stations)) != self._spatial_snapshot:raise ValueError('Geografische stationsankers gewijzigd; bereken opnieuw.')
            if connection_cable_records(self.layer(self.cables)) != self._cable_snapshot:raise ValueError('Aansluitkabelbron gewijzigd; bereken opnieuw.')
            count = apply_proposal(self.layer(self.target), self.proposal, self.asset.currentText(), self.reference_guard(), self.replace.isChecked())
            self.invalidate(); self.status.setText(f'{count} koppelingen opgeslagen. De laatste toepassing kan worden teruggedraaid. Voer clustering zo nodig opnieuw uit.')
        except Exception as exc:self.status.setText(str(exc))

    def undo(self):
        try:
            count = undo_proposal(self.layer(self.target)); self.invalidate()
            self.status.setText(f'{count} koppelingen hersteld. Nieuw aangemaakte controlekolommen blijven leeg aanwezig.')
        except Exception as exc:self.status.setText(str(exc))

    def export(self):
        if not self.proposal:return
        directory = QFileDialog.getExistingDirectory(self, 'Kies map voor het controlerapport')
        if directory:
            try:
                name = 'Stationsherleiding_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f')
                self.status.setText('Rapport opgeslagen: ' + export_report(self.proposal, Path(directory) / name))
            except Exception as exc:self.status.setText(str(exc))

    def select_map(self):
        layer = self.layer(self.target)
        if layer is None:return
        indexes = {item.row() for item in self.table.selectedItems()}
        layer.selectByIds([self._visible[i]['fid'] for i in indexes])
        if self.host.iface is not None:
            self.host.iface.setActiveLayer(layer)
            if indexes:self.host.iface.mapCanvas().zoomToSelected(layer)
