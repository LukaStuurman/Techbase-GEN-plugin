# Begrensd gebiedsherstel en knooppuntkandidaten — v1.32.0

De oorspronkelijke nieuwe Den Dungen-proef stopte op losliggende delen bij clusterindex 26. De capaciteits- en routecontrole slaagden; de gebiedscontrole niet. Die uitkomst was geen geldig ontwerp.

## Herstel

- Na de laatste grensnoding worden losgeraakte vlakken zonder eigen route-, klantconnector- of stationsanker nogmaals gecontroleerd. Alleen een vlak met een werkelijk gedeelde rand kan aan een buur worden overgedragen. Een vlak met eigen ankers blijft behouden. De bestaande controles op totale dekking, overlap, eigen aansluitingen en eigen routes blijven actief.
- Bij een resterende exclave bewaart de plugin de exacte gebieden en routes in `gebiedscontrole/gebiedscontrole.gpkg`. Ook een volgende automatische poging behoudt dit bestand. Een foutverslag neemt deze geometrie mee naar het controleproject, zodat niet alleen invoer maar ook de werkelijke probleemgrens beschikbaar is.
- Bij automatisch stationsaantal volgt één herstart via de bestaande kabel-Voronoi-terugval met alle kabelkandidaten, in plaats van de oorspronkelijke geselecteerde subset. Capaciteit, maximale route, exclusiviteit en gebieden worden volledig opnieuw gecontroleerd. Een aanhoudende fout stopt na die ene herstelpoging. Bij handmatig vast stationsaantal wordt niet automatisch van strategie gewisseld.
- Nieuwe kandidaatlocaties op hoofdkabelknooppunten worden meegenomen wanneer meerdere richtingen betekenisvolle bereikbare belasting hebben. Huisaansluittakken tellen niet als extra hoofdrichting; gelijke kortste richtingen via lussen tellen niet dubbel. De shortlist is begrensd en ruimtelijk gespreid en omvat lokale alternatieven bij bestaande kandidaten. Een gekozen knooppunt wordt niet door geometrisch centreren terug naar een eindtak verplaatst. Dit is een kandidaatvoorkeur, geen garantie op optimale benutting of het kleinste stationsaantal.

## Geslaagde productieproef

Een gerichte Den Dungen-proef is volledig uitgevoerd met **expliciet afgedwongen bestaande kabel-Voronoi-terugval** om de geometrie zonder de lange voorafgaande solverzoektocht te onderzoeken. Dit is een andere zoekroute dan de oorspronkelijk mislukte run; het bewijst niet dat precies dezelfde oorspronkelijke clustergrens nu hersteld is.

- 1.928 aansluitingen toegewezen; aantal gecontroleerd tegen de oorspronkelijke bronselectie binnen het plangebied.
- 14 nieuwe stations; maximale benutting 99,7543%, geen overschreden capaciteit.
- Langste werkelijke route 642,8142 m bij een grens van 850 m.
- Alle eigen aansluitingen liggen binnen hun gebied; eigen routes binnen het relevante gebied. Geen gedeelde routelengte tussen clusters.
- Gebieden geldig, geen ongeldige exclaves, volledige dekking van het plangebied. Overlap binnen numerieke tolerantie (minder dan 0,001 m²); ontbrekende dekking 0 m².
- GeoPackage, QGIS-project, PNG en PDF succesvol gemaakt in een aparte uitvoermap. De oorspronkelijke productiegegevens zijn niet overschreven.

Deze proef behoudt de eerdere opgeslagen keuze **buitenroutes toegestaan**. Zij bewijst geen geslaagde volledige Den Dungen-run met buitenroutes uit. De standaard voor nieuwe instellingen blijft uit. Een vergelijking die bewijst dat N-01/N-03 nu optimaal geplaatst zijn of dat er minder stations nodig zijn, is niet geleverd.

## Regressies

`test_clustering_recovery.py` injecteert een echte geometriefout in de engine: precies één herstelpoging levert daarna een geldig resultaat en bewaart de foutgeometrie. Een blijvend geïnjecteerde fout geeft na twee pogingen een fout en schrijft geen resultaat-GeoPackage. `test_area_fragment_cleanup.py` controleert overdracht van een ankerloos vlak, behoud van een vlak met eigen route, ongewijzigde dekking en geen overlap. Verder slagen `test_cluster_boundary_partition.py`, `test_external_plan_routes.py`, `test_junction_candidates.py` en `test_compact_assignment.py` in QGIS 4.2.3.

Geen QGIS 3-uitvoering of volledige handmatige Desktop-test. Deze versie maakt de aangetoonde fout beter herstelbaar en controleerbaar; zij garandeert geen foutloze uitkomst voor iedere dataset.
