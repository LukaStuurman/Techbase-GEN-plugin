# Nieuwe 150Al en behoud van oorspronkelijke richtingen

Status: ontwikkeling in draft PR #29. Geen productievrijgave en geen nieuwe gepubliceerde release.

De optionele keuze **Waar nodig nieuwe 150Al-aanloopkabels langs hoofdkabeltracés voorstellen** maakt afzonderlijke ontwerpkabels. Zij verandert bronkabels niet in 150Al. Kabelgroepen blijven afkomstig van de aansluitingenlaag. De CSV levert uitsluitend de gecontroleerde stationskoppeling.

## Gedrag

- Behoud alleen oorspronkelijke aansluitingen op een bestaand station. Vrijgegeven en nieuwe aansluitingen kunnen uitsluitend naar nieuwe stations.
- Onderscheid daadwerkelijke GEN-kabel-ID's op een gezamenlijk tracé. Een geometrische kruising of gelijke ligging bewijst geen elektrische verbinding.
- Controleer een aftakking zelfstandig. Een fout in de child maakt een gezonde parent niet automatisch ongeldig.
- Onderzoek bij een te zware richting eerst een houdbaar voortraject met een eindmofvoorstel. Geen LS-eindmoffen in aansluitkabels of OV-routegeleiders. Bij combikabels blijft de OV-continuïteit een expliciet controlepunt.
- Aansluitkabels leveren klantbelasting en aansluitbewijs, maar geen elektrische rekenmeters of gratis doorgaande route.
- Expliciet buiten bedrijf gestelde kabels en niet toetsbare hoofdgeleiders zijn geen beschikbare nieuwe LS-capaciteit. Een bewezen broncontact kan wel een afzonderlijk voorstel voor overzetten naar nieuwe 150Al opleveren.
- Gebruik de expliciete flatkastrelatie ook voor nieuw ontwerp zonder bekend historisch station. Dat bewijst geen oude voeding.
- Kies eerst bruikbaar hergebruik. Onderzoek ook de kortste en een impedantiegewogen route. Toets daarna de echte materialen en lengtes; een lage routekost is geen elektrische goedkeuring.
- Geef elke nieuwe richting een afzonderlijke ontwerpkabel-ID. Nieuwe kabels mogen dezelfde corridor volgen; een bestaande geleider mag niet in twee richtingen worden hergebruikt.
- Houd een gemeenschappelijk aansluitpunt ondeelbaar. Toets verbruik en opwek afzonderlijk, alle betrokken paden, de richtingbelasting en de routegrens. Weiger lussen, geblokkeerde nieuwe geometrie en stations met meer dan tien voedende richtingen.

## Lokale validatie

De echte Den Dungen XML/Excel, GeoPackages, schema XML/Excel/DXF en stations-CSV zijn beschikbaar en gelezen. De volledige QGIS-workflow is uitgevoerd. Een volledige, gevalideerde clustering is nog niet bereikt: concrete broncontacten en ontwerpcontroles blijven open. De afzonderlijke controleberekening houdt onopgeloste aansluitingen zichtbaar op `-1`; de normale workflow stopt veilig en meldt geen compleet resultaat.

De lokale regressies omvatten 22 afzonderlijke programma's, waaronder kabeltype/lengte, bronrelaties, verdeelkastvoedingen, meervoudige groepen, behoud, eindmofvolgorde, kabelidentiteit, expliciete nieuwe 150Al, hergebruik, afzonderlijke richtingen en hoofdloos laden van de plugin. De bijbehorende GitHub-workflow voert de beschikbare bron- en geometrieproeven uit; dat vervangt geen QGIS-integratie met de private projectdata.

## Open voor vrijgave

- Alle werkelijke routecontacten en aansluitingen moeten een getoetste voeding krijgen.
- Stationsplaatsing en het aantal richtingen vragen verdere ontwerpoptimalisatie. Een scalar trafo-/afstandcluster is slechts een kandidaat.
- De bestaande behoudcontrole rekent op de gebruikte aansluitpaden. De fysieke-eindvariant, onbelaste kabelstaarten en de uiteindelijke knippenunie moeten nog integraal worden gecontroleerd.
- Werkelijke gG-beveiliging is niet overal eenduidig bevestigd. De rekenuitvoer bevat ontwerpvoorstellen en berekende maxima.
- OV wordt uitsluitend als route behandeld. OV-elektrische beoordeling, combi-continuïteit, daadwerkelijke schakelingen/moffen en uitvoering blijven apart open.
- BAG-uitsluitingen bewijzen geen volledige BGT-, vegetatie-, eigendoms- of uitvoerbaarheidscontrole. Het resultaat is geen uitgewerkt CAD-VO met ingevulde kader-werkboeken.

Private kaarten, adresregisters en controlebestanden blijven lokaal en op de aangewezen projectschijf. Zij worden niet in de repository opgenomen. Draft PR #29 mag niet worden gemerged of als gevalideerde release gepubliceerd voordat de open controles zijn afgerond.
