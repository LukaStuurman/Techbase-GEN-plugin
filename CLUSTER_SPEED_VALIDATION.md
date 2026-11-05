# Exact kleiner optimalisatiemodel — v1.31.1

De Den Dungen-log toont herhaaldelijk ongeveer 120 seconden voor stationskeuze en vervolgrondes met een limiet van 240 seconden voor definitieve toedeling. Terugval/herstart kan die stappen herhalen. Een kleinere variabelenruimte en het overslaan van bewezen onmogelijke benuttingsniveaus pakken een deel van deze rekentijd aan.

## Geïmplementeerd

1. Stationskeuze en definitieve toedeling verwijderen vóór de solver alle variabelen met bovengrens exact nul. Dit zijn toewijzingen die de oorspronkelijke route-/bereikbaarheidsvoorwaarden al verboden. Dezelfde doelstelling, integrale variabelen en alle constraint-rijen blijven behouden. Na de solver wordt de oorspronkelijke kolomindeling met nullen hersteld. Geen heuristische kandidaatselectie of versoepeling van capaciteit, routes of geometrie.
2. De definitieve toedeling slaat een benuttingsniveau over als de totale belasting kleiner is dan de benodigde minimale belasting, of als een station zelfs alle binnen de maximale route bereikbare belasting samen onvoldoende is om dat minimum te halen. Dit zijn noodzakelijke rekenvoorwaarden. Een mislukte solverzoekactie wordt niet als onmogelijkheid bewezen verklaard; alleen deze harde ondergrenzen rechtvaardigen overslaan.
3. De log toont de oorspronkelijke en verkleinde variabelenaantallen. De bestaande solverlimieten en overige route-/gebiedscontroles blijven behouden.

## Bewijs en metingen

- `test_compact_assignment.py` vergelijkt twaalf onafhankelijke integrale toewijzingsproblemen via het oorspronkelijke volledige model en het compacte model. Optimale doelwaarden komen binnen 1e-8 overeen. De teruggezette kolommen, exact-nulgrenzen, toewijzingsregels en capaciteitsvoorwaarden zijn apart gecontroleerd.
- Een onbereikbaar station bewijst vijf positieve minimale benuttingsniveaus onmogelijk. De test toont dat alleen de geldige 0%-ronde de solver aanroept, met correcte toedeling.
- De nieuwe Den Dungen-productierun verkleint het eerste stationskeuzemodel van **61.744 naar 27.155 variabelen (56,0% minder)**. Dit is een gemeten reductie van het model, geen claim van 56% minder totale rekentijd.
- `test_clustering_recovery.py`, `test_station_enclosure_connection.py` en `test_plugin_headless.py` controleren bestaande berekening/terugval, netwerkverbinding en bestaande-stationsvoorrang naast de nieuwe exacte-modeltest.

Uitgevoerd in de QGIS 4.2.3-Pythonomgeving. De volledige geoptimaliseerde Den Dungen-run is gestart in een aparte uitvoermap. Bij voorbereiding van deze wijziging was deze nog niet afgerond; er is dus **nog geen bewezen totale versnelfactor of gevalideerd nieuw totaalontwerp**. Voor andere datasets of solverzoekpaden kan de tijdwinst verschillen. Geen QGIS 3-uitvoering. De oorspronkelijke productiegegevens zijn niet gewijzigd.
