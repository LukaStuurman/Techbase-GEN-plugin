"""Persist actionable clustering failures without claiming an invalid design."""
import json
import shutil
import traceback
from datetime import datetime
from pathlib import Path


def explain_failure(error):
    detail = str(error)
    text = detail.casefold()
    if "geannuleerd" in text:
        return "De clustering is gestopt op verzoek.", "Je kunt de berekening opnieuw starten."
    if any(word in text for word in ("capaciteit", "capaciteits", "stationsselectie", "geldige selectie", "geldige kabelverbonden", "stationsaantal")):
        return ("Geen geldige verdeling over stations gevonden met de huidige capaciteit en kabelverbindingen.",
                "Controleer grote ontwerpstromen/flatgroepen, gescheiden kabeldelen en stationscapaciteiten. "
                "Gebruik automatisch stationsaantal; extra stations helpen alleen waar een geschikte kabelverbinding bestaat.")
    if any(word in text for word in ("stationslocatie", "stationsknopen", "stationskn", "kabelknoop")):
        return ("Op minstens één kabeldeel is geen toegestane locatie voor een nieuw station gevonden.",
                "Controleer hoofdkabels, aansluitkabels, uitgesloten locaties en knooppunten. "
                "Zonder plangebied worden ook kleine losse kabeldelen onderzocht.")
    if any(word in text for word in ("exclave", "gebied", "voronoi", "geometr", "topologyexception")):
        return ("De clustergebieden voldoen nog niet aan de geometriecontrole.",
                "Controleer losse kabeldelen, kruisende routes en aansluitingen aan de gebiedsrand. "
                "Gebruik het controleproject en beperk zo nodig de berekening met een plangebied.")
    if any(word in text for word in ("kabelroute", "bereikbaar", "kabelcomponent", "topologisch", "harde grens")):
        return ("Niet alle aansluitingen hebben een geldige kabelroute binnen de ingestelde grenzen.",
                "Controleer de losse kabeldelen en knoopverbindingen, of pas de maximale routelengte bewust aan. "
                "Een rechte lijn over een ontbrekende kabel wordt niet als geldige route gebruikt.")
    if any(word in text for word in ("project", "layout", "render", "pdf", "png")):
        return ("De uitvoer of projectpresentatie kon niet volledig worden gemaakt.",
                "Als de resultaat-GeoPackage al bestaat, blijft die beschikbaar. "
                "Open de lagen direct of gebruik projectherstel; opnieuw clusteren is dan niet nodig.")
    return ("De clustering kon niet worden afgerond.",
            "Bekijk het technische rapport en het controleproject. De voorbereide invoer blijft beschikbaar; "
            "je hoeft XML en Excel niet opnieuw te importeren.")


def save_failure(error, output_dir, work_dir=None, messages=()):
    """Make a uniquely named report, snapshots and a simple review project."""
    folder = Path(output_dir) / ("controle_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    folder.mkdir(parents=True, exist_ok=False)
    summary, action = explain_failure(error)
    records = []
    if work_dir is not None:
        work_dir = Path(work_dir)
        for source in sorted(work_dir.glob("*.gpkg")):
            target = folder / source.name
            shutil.copy2(source, target)
            records.append(target)
        computed = work_dir / "resultaat" / "clustering_ontwerp.gpkg"
        if computed.exists():
            shutil.copy2(computed, folder / "berekende_lagen.gpkg")
        for filename in ("capaciteitsknelpunten.gpkg", "capaciteitsknelpunten.csv", "netwerkcontrole.gpkg", "gebiedscontrole.gpkg"):
            source = work_dir / "resultaat" / filename
            if filename=='gebiedscontrole.gpkg':source=work_dir/'resultaat'/'gebiedscontrole'/filename
            if source.exists():
                target = folder / filename
                shutil.copy2(source, target)
                if source.suffix == '.gpkg':
                    records.append(target)
    project_path = ""
    project_error = ""
    try:
        from qgis.core import QgsProject, QgsVectorLayer, QgsReferencedRectangle, QgsRectangle
        import sqlite3
        project = QgsProject()
        project.setTitle("Controleproject — clustering niet afgerond")
        for path in records:
            with sqlite3.connect(path) as database:
                tables = database.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'").fetchall()
            for (table,) in tables:
                layer = QgsVectorLayer(f"{path}|layername={table}", "Controle invoer: " + path.stem, "ogr")
                if layer.isValid():
                    project.addMapLayer(layer)
                    if path.stem == 'aansluitingen':
                        project.setCrs(layer.crs())
                        extent = QgsRectangle(layer.extent())
                        extent.grow(max(10., .05 * max(extent.width(), extent.height())))
                        project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(extent, layer.crs()))
                    if path.stem == 'capaciteitsknelpunten':
                        from qgis.core import QgsMarkerSymbol
                        layer.renderer().setSymbol(QgsMarkerSymbol.createSimple({'name':'circle', 'color':'230,35,35,255', 'size':'4'}))
                    elif path.stem == 'netwerkcontrole':
                        from qgis.core import QgsCategorizedSymbolRenderer, QgsRendererCategory, QgsLineSymbol
                        categories = []
                        for value, color in (("Zonder bestaand station", "230,35,35,255"),
                                             ("Met bestaand station", "30,110,190,255"),
                                             ("Geen aansluitingen", "155,155,155,255")):
                            symbol = QgsLineSymbol.createSimple({'line_color':color, 'line_width':'0.6'})
                            categories.append(QgsRendererCategory(value, symbol, value))
                        layer.setRenderer(QgsCategorizedSymbolRenderer('Controle', categories))
                        layer.setName('Controle: losse kabelcomponenten (rood = zonder bestaand station)')
        project_path = str(folder / "controleproject.qgz")
        if not project.write(project_path):
            raise RuntimeError("Controleproject schrijven mislukt")
    except Exception as exc:
        project_error = str(exc)
        project_path = ""
    report = {"status": "niet_afgerond", "summary": summary, "action": action,
              "technical_error": str(error), "traceback": traceback.format_exc(),
              "project": project_path, "project_error": project_error,
              "messages": list(messages), "input_snapshots": [path.name for path in records]}
    (folder / "diagnose.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / "LEESMIJ.txt").write_text(
        summary + "\n\n" + action + "\n\nTechnische melding:\n" + str(error) +
        "\n\nDit is een controleproject met invoerlagen, geen goedgekeurd clusterontwerp. "
        "Eventuele berekende_lagen.gpkg zijn een onvoltooide tussenuitvoer.\n\n" +
        "\n".join(messages), encoding="utf-8")
    return f"{summary}\n\n{action}\n\nOorzaak: {str(error)[:800]}\n\nControle en technisch rapport: {folder}"
