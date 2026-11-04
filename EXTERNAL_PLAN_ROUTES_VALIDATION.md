# v1.27.1 — kabelroutes buiten het plangebied

## Gedrag

In het echte venster **3a. Automatische clustering** staat een nieuwe optie standaard aan: **Kabels buiten het plangebied gebruiken om aansluitingen binnen het plangebied te bereiken**. Dezelfde instelling bestaat bij Geavanceerd → Berekening en in de Processing-tool.

De instelling bewaart het volledige kabelnet voor routering. De selectie van aansluitingen en bestaande stations blijft apart geregeld door ‘Alleen aansluitingen en stations binnen het plangebied clusteren’. Nieuwe stationslocaties blijven binnen het plangebied. Clustergebieden worden op het plangebied begrensd; alleen de kabelroute kan de grens passeren. De hele kabelroute, inclusief de buitenliggende delen, blijft meetellen voor de maximale routelengte. Capaciteit en exclusieve routes blijven gecontroleerd.

Bij uitgeschakelde optie worden kabels weer op de grens geknipt. Zonder plangebied staat de optie uitgeschakeld in het venster en heeft zij geen effect. Een eerder opgeslagen keuze wordt behouden; oude workflows zonder deze instelling beginnen met de standaardwaarde aan.

Nieuwe resultaatlagen bewaren het routingbeleid in `Buitenplan_toegestaan`. Daardoor gebruiken ook latere batchcorrecties, stroomwijzigingen en routeherberekeningen het volledige benodigde netwerk. Oude resultaten zonder dit veld houden hun oorspronkelijke beleid. De nieuwe instelling geldt voor die projecten na opnieuw uitvoeren van stap 3.

Een aangesloten kabelroute kan door een meerdelig/ingesneden plangebied lopen en binnen dat gebied meerdere vlakken bedienen. Dat is toegestaan als de route daadwerkelijk buiten de grens doorloopt en ieder gebiedsdeel de echte route raakt. Losliggende vlakken zonder zo'n verbinding blijven afgewezen. Kaart- en layoutuitsneden nemen de volledige gebruikte route mee.

## Uitgevoerde controles

QGIS 4.2.3 / Qt6 / Python 3.12 op Windows. Echte rekenengine, GeoPackages, Qt-instellingenvenster en native project-/layoutworkers; de UI-tests gebruiken een geïsoleerde offscreen testsessie.

`test_external_plan_routes.py` is geslaagd:

- Een U-vormige kabel verlaat een rechthoekig plangebied en komt terug. Een aansluiting binnen het gebied wordt correct bereikt vanaf het bestaande station; de volledige gemeten route is 40 m.
- Uitzetten van de optie voorkomt gebruik van die buitenroute. Een limiet van 30 m weigert de volledige 40-m-route ook als de optie aanstaat.
- Een buitenliggende aansluiting van 999 A en een buitenliggend station worden door het actieve plangebiedfilter uitgesloten. Alleen de twee binnenliggende aansluitingen en hun 15 A tellen mee.
- Bij hogere belasting wordt een echt nieuw station geplaatst. De nieuwe stationslocatie blijft binnen het plangebied, terwijl het netwerk buiten de grens beschikbaar is.
- Een meerdelig plangebied levert geldige binnenliggende vlakken die door de buitenroute worden verbonden. Een willekeurig losliggend vlak wordt afgewezen.
- Latere stroomwijziging en expliciete routeherberekening behouden het externe routingbeleid en de correcte routeafstand, ook bij een meerdelig plangebied. Een echte batchworker slaat de wijziging op in de GeoPackage; de herstelkopie zet attributen, geometrie en objectnummers exact terug.
- De echte 3a-checkbox is zichtbaar, standaard aangevinkt, kan uit en wordt opgeslagen/heropend. Workflow en Processing ontvangen dezelfde keuze; de Processing-standaard is ook aan. Zonder plangebied is de checkbox uitgeschakeld.

Bestaande tests zijn geslaagd: `test_clustering_options`, `test_cluster_management`, `test_cluster_extensions`, `test_clustering_recovery`, `test_guided_cluster_editing`, `test_uniform_ui` en `test_project_recovery`. De laatste test doorloopt drie echte native project-/layoutworkers. Alle 90 Python-bronnen zijn op syntax gecontroleerd; `git diff --check` slaagt.

Geen volledige nieuwe Vaartbroek-berekening of handmatige complete QGIS Desktop-kliktest uitgevoerd voor deze wijziging. QGIS 3 is niet afzonderlijk uitgevoerd. De eerder gemelde onopgeloste Vaartbroek-berekening zonder plangebied is hiermee niet als opgelost aangemerkt; zonder plangebied verandert deze instelling het routingbeleid niet.
