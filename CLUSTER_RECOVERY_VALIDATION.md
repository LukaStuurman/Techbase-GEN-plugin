# v1.27.0 — clusteringcontrole, stroom na clustering en handmatige nieuwbouw

**Historisch verslag:** de hieronder beschreven Vaartbroek-beperking is inmiddels opgelost in v1.27.3. De volledige proef met 4.266 aansluitingen is geslaagd; zie [de actuele validatie](VAARTBROEK_VALIDATION.md).

## Wat is toegevoegd

- **1.3. Nieuwbouw → Zelf nieuwbouwaansluitingen plaatsen — zonder BAG**: klik één keer per toekomstige aansluiting op de kaart. Rechtsklik/Enter keert terug; Esc wist de klaargezette punten. Losse punten verwijderen of de wachtrij wissen kan vóór het opslaan. Kies een projectomschrijving, gebruiksdoel, geplande aansluitwaarde en bouwjaar. Bereken de stroom uit een woningtype met de nieuwbouwtabellen, vul vier stroomwaarden in of kies expliciet ‘Later bepalen’ (0 A, nog te beoordelen).
- Punten worden als echte objecten in de bestaande ontwerpstroomlaag opgeslagen. Ze hebben een eigen `NWB_ID`, bron ‘Handmatig nieuwbouw (zonder BAG)’ en nieuwbouwmarkering. BAG-identificaties blijven leeg. De herkenning blijft behouden in de clusteruitvoer. Het eigen ID is geen verzonnen BAG- of GEN-identificatie.
- De laatste handmatige toevoeging kan worden teruggedraaid, ook na heropenen van het project. Als die punten later zijn gewijzigd, wordt undo geweigerd. Voeg ze vóór stap 3 toe, of voer stap 3 opnieuw uit om een bestaand ontwerp opnieuw te clusteren. Een bestaand resultaat wordt niet stilzwijgend aangevuld met nog niet toegewezen punten.
- **4i. Ontwerpstroom na clustering aanpassen**: stel `Ontwerp_A` voor geselecteerde geclusterde aansluitingen in. Stationsbelasting, capaciteit en benuttingsvelden worden gezamenlijk bijgewerkt met behoud van toewijzingen en routes. Overbelasting wordt afgewezen. Voorstelcontrole, de wachtrij en exact undo blijven beschikbaar. De oorspronkelijke vier verbruiks-/opwekvelden veranderen hierdoor niet; een latere automatische clustering gebruikt de bronvelden uit stap 2a opnieuw.

## Clustering zonder plangebied

Hersteld: automatische herhaalpogingen proberen geen aantallen onder de reeds vastgestelde topologische ondergrens meer. Voorheen kon dezelfde effectieve berekening van bijvoorbeeld 32 stations worden herhaald via lagere aangevraagde aantallen. Een kabeldeel met aansluitingen maar zonder station krijgt ook bij 0 A een benodigde stationslocatie. Losse kabeldelen zonder aansluitingen blokkeren de berekening niet meer doordat daar geen geschikte nieuwe stationslocatie bestaat.

Vóór de dure optimalisatie worden noodzakelijke capaciteitsgrenzen voor ondeelbare aansluitgroepen gecontroleerd. Bij een aantoonbaar te grote groep worden de locaties en capaciteitsgegevens apart opgeslagen. Een nieuw controlebestand toont de losse kabelcomponenten met belasting, bestaande capaciteit, stationsaantal en een capaciteitsmatige ondergrens voor extra stations. Rood betekent ‘zonder bestaand station’; dat is een onderzoekspunt en niet automatisch een fout.

Bij een rekenfout blijven een uniek gedateerd **controleproject**, invoerkopieën, een leesbare uitleg en een technisch JSON-rapport behouden. Het dashboard toont knoppen om die bestanden en het controleproject te openen. Zo'n controleproject is nadrukkelijk geen afgerond clusterontwerp. Het bevat geen fictief veilige routes of toewijzingen.

Een fout in PNG/PDF-export gooit een reeds gecontroleerd en opgeslagen ontwerp niet weg. Bij een fout in de uitgebreide project-/layoutgenerator wordt een eenvoudig QGIS-project met de vijf resultaatlagen gemaakt. Ontbrekende kaarten/templates worden niet als bestaande uitvoer gerapporteerd. De wizard toont de waarschuwingen; projectherstel blijft mogelijk.

## Vaartbroek: werkelijke uitkomst

Lokale kopieën van de bestaande Vaartbroek-import, ontwerpstroomlaag en BAG-typering uit `U:\Vaartbroek voor bram` zijn gebruikt, zonder plangebied. Er is in deze sessie geen nieuwe volledige XML/Excel-import en BAG-download uitgevoerd. De test omvatte **4.266 aansluitingen**, **29.978,7 A**, **39 kabelcomponenten** en een maximale route van **850 m**.

De herhaalfout is aangetoond in de eerdere code. Met de correcties gaat de berekening verder vanaf de relevante topologische ondergrens (33 nieuwe stations, inclusief het station voor een los 0-A-deel). De volledige automatische reeks tot en met 43 nieuwe stations leverde **nog geen geldige volledige stationsselectie** op. Er is dus geen geslaagde volledige Vaartbroek-clustering aangetoond en ook geen bewijs geleverd dat die wiskundig onmogelijk is.

Het controleproject is wel gemaakt en geverifieerd: negen geldige lagen, 4.266 invoerpunten en 39 kabelcomponenten; de lagen gebruiken relatieve paden en het project opent op de aansluitingen. Na het toevoegen van de componentenkaart is de laatste mislukte 43-stationspoging gericht herhaald om het controlepakket te vullen. Capaciteits- en routeveiligheid zijn niet uitgezet. Productiegegevens zijn niet in GitHub opgenomen.

## Uitgevoerde controles

QGIS 4.2.3, Qt6 en Python 3.12 op Windows; echte PyQGIS-widgets, QgsMapCanvas, rekenprocessen en GeoPackages. De interface is via de werkelijke dashboardklassen getest, met een kleine vervanger voor de Desktop-shell en offscreen schermafbeeldingen. Geen volledige handmatige kliktest in de QGIS Desktop-app en geen QGIS 3-test.

- `test_manual_newbuild.py`: geslaagd. Lege BAG-identificaties, unieke eigen ID's, stroomcomponenten/maxima, nieuwbouwberekening, later bepalen, ongeldige invoer, CRS-transformatie, meerdere punten op dezelfde locatie, echte kaartcallbacks, annuleren, bronopslag, beschermd undo, undo na heropenen en herkenning in echte automatische clusteruitvoer.
- `test_clustering_recovery.py`: geslaagd. Stationsaantallen respecteren de ondergrens; ondeelbare capaciteitsgrenzen; een volledig uitgesloten kabeldeel zonder aansluitingen blokkeert niet. Geïnjecteerde kaart- en layoutfouten behouden het ontwerp; de werkelijke Processing-wrapper levert een basisproject en waarschuwingen. Een geïnjecteerde rekenfout levert een blijvend controleproject en zichtbare dashboardacties. 4i wijzigt de afgeleide tabellen en ondersteunt niet-mutaterende preview, capaciteitsafwijzing en exact undo.
- Bestaande regressies geslaagd: `test_auto_clustering_efficiency`, `test_clustering_options`, `test_project_recovery`, `test_current_overwrite`, `test_cluster_management`, `test_cluster_extensions`, `test_uniform_ui`, `test_bag_usage_currents`, `test_newbouw_download` en `test_connection_sources`.
- Bij `test_connection_sources` faalde een oude verwachting ook ongewijzigd op v1.26.0. Die test verwachtte de oude woningtabel voor nieuw toegevoegde BAG-nieuwbouw zonder pand. De verwachting is gecorrigeerd naar de al bestaande 2022+-regel; de berekening zelf is daarvoor niet veranderd. De test is daarna geslaagd.
- Alle 89 Python-bestanden zijn op syntax gecontroleerd; `git diff --check` is geslaagd.

## Gebruik en beperkingen

Nieuwbouwpunten op de kaart zijn geplande aansluitingen; er wordt geen echte nieuwe kabel in de broninventaris bedacht. De bestaande clustering kan een ontbrekende aansluitkoppeling aanvullen, maar route- en capaciteitscontroles blijven bepalend. Pas zo nodig eerst het plangebied of de sleuven aan. ‘Later bepalen’ is een expliciete open controle, geen bevestiging dat een nulstroom technisch juist is.

Deze release verbetert herstelbaarheid en diagnose. Zij garandeert niet dat iedere combinatie van invoer, kabeltopologie, stationscapaciteit en routegrenzen volledig clusterbaar is.
