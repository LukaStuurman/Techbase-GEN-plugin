# Clusterbewerking v1.26.0 — implementatie en validatie

Datum: 4 november 2026. Basis: v1.25.5 (`4ec5e88249c295221a461fece98a520a7c605c8d`).

## Werkelijk geïmplementeerd

Het echte gekleurde dashboard toont onder stap 4 nu 4a–4h. De oorspronkelijke 4a–4d blijven bestaan.

| Knop | Werking |
| --- | --- |
| 4e. Stationscapaciteit aanpassen | Selecteer een station in de lijst, stel ontwerp-kVA in en zet de wijziging klaar. De berekening werkt capaciteit, benutting en aansluitingsattributen in alle vier resultaatlagen bij. Overbelasting wordt geweigerd. De ontwerpkeuze wordt apart opgeslagen en bij volgende automatische clustering ingelezen. De fysieke broninventaris wordt niet gewijzigd. |
| 4f. Clusters samenvoegen | Kies het bronstation in de lijst en een expliciet doelstation. De bestaande gecontroleerde uitfaseerbewerking verplaatst alle aansluitingen en laat de bron vervallen. Bestaande stations krijgen ‘Te verwijderen’, nieuwe stations ‘Vervallen’. Bescherming, capaciteit en routes blijven van toepassing. Dit is een duidelijke extra ingang naar bestaande rekenfunctionaliteit. |
| 4g. Cluster splitsen / station bijplaatsen | Selecteer een deel van één cluster, geef een unieke naam en capaciteit op en kies een sleufknoop op de kaart. Een extra station en zijn afhankelijke records worden toegevoegd; aansluitingen krijgen echte kabelroutes vanaf die locatie. Het bronstation houdt minimaal één aansluiting. Het nieuwe station wordt vastgelegd voor volgende berekeningen. |
| 4h. Clusters controleren / herberekenen | Selecteer gebied/routes van één station, aansluitingen boven de maximale routelengte, nulstromen of ongeldige stationstoewijzingen. Zet herberekening voor één station of alle stations klaar met behoud van toewijzingen. Een terugval op een oude route wordt als fout gemeld. |

Alle nieuwe ontwerpwijzigingen gebruiken de bestaande wachtrij, voorstelcontrole, gezamenlijke GeoPackage-transactie, herstelkopie en laatste-toepassing-undo. De voorlopige belasting houdt ook rekening met klaargezette capaciteit en extra stations.

Toegevoegd: wachtrij volledig wissen, controle op tussentijds gewijzigde stationsregels, controle vlak vóór toepassen op gewijzigde bronlagen/regels, late annulering vóór opslaan en blokkeren van undo na latere wijzigingen in stationskeuzes. Nieuwe gebiedsberekeningen worden gecontroleerd op lege/ongeldige geometrie, overlap en volledige dekking van het plangebied. De bestaande enginecontrole op exclaves blijft actief. De releaseworkflow controleert nu ook alle Python-bronnen vóór publicatie.

## Gebruik

1. Maak of open een berekend clusterproject en open 4e, 4f, 4g of 4h.
2. Volg de uitleg bij het gekozen onderdeel. De stationslijst en het doelstation staan bovenaan dezelfde pagina. Scroll terug naar boven om een bronstation te kiezen.
3. Zet de wijziging klaar. De wachtrijvolgorde bepaalt de berekening: bijvoorbeeld eerst capaciteit verhogen en daarna samenvoegen.
4. Gebruik **Voorstel controleren** voor capaciteit en routes. Dit verandert het ontwerp niet; de definitieve gebiedscontrole volgt bij toepassen.
5. Gebruik **Alles toepassen**. Bij een fout wordt geen gedeeltelijk berekend ontwerp opgeslagen. **Laatste toepassing ongedaan maken** herstelt de vorige vier resultaatlagen en stationskeuzes.

## Uitgevoerde tests

Windows, geïnstalleerde QGIS 4.2.3 / Qt6 / Python 3.12. De scripts zijn met de eigen `python-qgis.bat` en `QT_QPA_PLATFORM=offscreen` uitgevoerd.

| Test | Uitkomst / dekking |
| --- | --- |
| `test_cluster_extensions.py` | Geslaagd: splitsen met echt extra station, toewijzingen, route vanaf nieuwe locatie, unieke objectnummers, niet-mutaterende preview, capaciteit in alle afhankelijke tabellen, capaciteit + samenvoegen, één station herberekenen, behoud toewijzingen, invoer onveranderd. |
| Negatieve gevallen in dezelfde test | Geslaagd: dubbele naam, heel broncluster geselecteerd, meerdere bronclusters, locatie buiten cluster, locatie buiten netwerkknoop, niet-eindige capaciteit, onbereikbare route, te kleine capaciteit, ontbrekend station, gedeeltelijke flatgroep, terugval op oude route en overlappende gebieden afgewezen. |
| QGIS/Qt-interface in dezelfde test | Geslaagd: echte dashboardknoppen 4e–4h zichtbaar in de viewport en aanklikbaar, juiste pagina/sectie geopend, echte QgsMapCanvas-kaartkiezer, annuleren, transformatie van EPSG:3857-kaart naar EPSG:28992-lagen, kaartselecties voor gebieden/routes/lange routes/nulwaarden/toewijzingen. |
| GeoPackage en undo in dezelfde test | Geslaagd: nieuw station werkelijk invoegen, capaciteit werkelijk wijzigen, voorstellen zonder bronwijziging, exact herstel van attributen/geometrie/objectnummers, weigeren van verouderde stationsregels en undo die latere keuzes zou overschrijven. |
| `test_cluster_management.py` | Geslaagd: bestaande stationsverplaatsing, routevernieuwing, automatisch herverdelen, bescherming, capaciteitsafwijzing, annulering, SQLite-foutinjectie met rollback, exact undo na project heropenen en verouderde wachtrij. |
| `test_uniform_ui.py` | Geslaagd: bestaande dashboardingangen 4c/4d, vaste footer/stopknop, overige pagina's, geavanceerde tabbladen en navigatie. |
| `test_guided_cluster_editing.py` | Geslaagd: bestaande begeleide editor voor verplaatsen/nieuw/samenvoegen, echte workers en voorbereiding binnen plangebied. |
| `test_network_maintenance.py` | Geslaagd met apart gegenereerd representatief QGIS-project: lokaal noden versus volledig noden, repareren/behouden van routes, nieuwe sleuf, geselecteerde route opnieuw berekenen en overige routes behouden. |
| `test_repeat_area_modes.py` | Geslaagd: herhaald wisselen van gebiedsvorm en vorig goed resultaat bewaren bij fout. |
| `test_plugin_retirement_menu.py` | Geslaagd: bestaande directe menuactie en opruimen bij unload. |
| Syntax / whitespace | Alle 85 Python-bestanden geparseerd; `git diff --check` geslaagd. |

De netwerkonderhoudtest vereist een projectpad. De eerste aanroep zonder dat argument stopte vóór de test; de correcte aanroep met een speciaal gegenereerd testproject is geslaagd. De QGIS 3.44.5-map op deze computer bevat geen uitvoerbare QGIS/Python-runtime, waardoor die versie niet kon worden getest.

## Grenzen van de validatie

De UI-tests gebruiken echte PyQGIS/Qt-widgets, de werkelijke dashboardklasse, echte rekenprocessen en een echte kaartcanvas met een kleine vervanger voor de Desktop-shell. Er is geen handmatige kliktest in de volledige QGIS Desktop-app met een geladen productieproject uitgevoerd. Er is geen volledig automatisch herclustertraject met productie-GEN/XML/Excel doorgelopen voor de nieuwe capaciteitskeuzes. Grote netten, rekentijden, ingewikkelde flat-/takstructuren en alle externe gegevensvarianten vragen een praktijktest.

Splitsen voegt een station toe aan een bestaand cluster op een bestaande sleufknoop. Lege reserve-stations, vrije ligging buiten sleuven, automatisch optimaal splitsen van een heel gebied, vrij doorknippen van kabeltakken, meerdere undo-stappen en redo zijn niet toegevoegd. De routecontroles kunnen een gevraagde splitsing of samenvoeging terecht weigeren. Voeg zo nodig eerst bruikbare sleuven/knooppunten toe via stap 5.
