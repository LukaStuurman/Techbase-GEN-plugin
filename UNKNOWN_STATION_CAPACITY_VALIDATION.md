# Station met onbekende capaciteit — v1.28.1

## Oorzaak

In de echte Den Dungen-import staat station 044.532 in `Station locatie`, met geldige puntgeometrie, `trafo_power = NULL` en `Max_A = NULL`. Het station was dus niet uit de bronimport verdwenen. De stationsrenderer had uitsluitend regels voor `Max_A > 0`; ook de labeluitdrukking gaf bij NULL een lege tekst. Daardoor leek het station in het ontwerpstroomresultaat te ontbreken.

## Herstel

De ontwerpstroomcontrole heeft nu vier elkaar uitsluitende weergaveregels: benoemd/geldige capaciteit (rood), onbenoemd/geldige capaciteit (geel), benoemd/onbekende capaciteit (oranje), onbenoemd/onbekende capaciteit (grijs). De laatste twee regels hebben een leesbaar label met **Capaciteit onbekend**. Geen enkele geïmporteerde rij wordt op capaciteit uit de kaartweergave gefilterd.

Het presentatieversienummer is verhoogd naar 148. De bestaande herstelroute voor gegenereerde projecten vernieuwt de stijl van hun stationscontrolelaag. Deze migratie wijzigt geen capaciteit, geometrie of stationsidentiteit. Nieuwe imports gebruiken de stijl rechtstreeks. De bestaande mogelijkheid om capaciteit expliciet aan te passen via 2c blijft beschikbaar.

De rekenregels veranderen niet: onbekende capaciteit wordt niet als nul of als een fictief positief vermogen ingevuld en levert geen stilzwijgend bruikbare capaciteit voor clustering. Het berekende `Max_A` blijft NULL. Dit is een herstel van de zichtbaarheid in de bron-/ontwerpstroomcontrole, geen garantie dat een onbekend station al als veilig ontwerppunt in een clusterresultaat kan worden gebruikt.

## Controles

- Echte bestaande Den Dungen-import ingelezen, 044.532 exact op naam gevonden en gecontroleerd op niet-lege geometrie en beide NULL-waarden.
- Native `QgsMapRendererParallelJob` uitgevoerd. Het gerenderde labelresultaat bevat exact `044.532` en `Capaciteit onbekend`; de PNG toont het oranje stationssymbool. De oorspronkelijke gegevens zijn hierbij niet geschreven.
- `test_unknown_station_capacity.py`: NULL, geldig, onbekende tekst, nulvermogen en beide naamgevallen. Iedere feature past precies in één renderregel. Positieve capaciteit behoudt de bestaande kleur en ampèrelabel. Een oude projectstijl uit presentatieversie 147 is opgeslagen, gemigreerd, heropend en opnieuw gecontroleerd; alle zes testrijen blijven behouden en NULL blijft NULL.
- Regressies voor stationspresentatie, schemaherleiding en uniforme dashboardwidgets. De oudere headless laadtest is bijgewerkt om de reeds bestaande navigatie naar stationsbeheer te controleren en daarna de klassieke handmatige pagina expliciet te openen; de overige ontwerpstroom-/symboolcontroles blijven behouden.

Getest in QGIS 4.2.3 op Windows. Geen nieuwe volledige XML/Excel/BAG-import of volledige automatische clustering voor deze presentatiewijziging, geen volledige handmatige Desktop-kliktest en geen QGIS 3-uitvoering. De bronimport is rechtstreeks geïnspecteerd en de nieuwe weergave is echt gerenderd. Geen productiegegevens naar GitHub geüpload.
