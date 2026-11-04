# Vaartbroek zonder plangebied — v1.27.3

## Oorzaken en correcties

De automatische stationsselectie vond met de oorspronkelijke kandidaatlocaties geen geldige oplossing. De kabelverbonden herstelstap stopte vervolgens soms voortijdig: na een routeoverschrijding waren de belastingen nog van de vorige toewijzing, en een fout in stationsworteleigendom leverde geen nieuw herstelknelpunt op. Daarnaast kon de iteratieve belastingverschuiving blijven wisselen zonder vooruitgang.

Beide herstelvarianten berekenen nu de actuele belasting vóór routecontrole, bewaren de werkelijk falende aansluitingseenheden en controleren alle stationswortels. Na 200 verschuivingen zonder vermindering van overbelasting probeert het automatische herstel een geschikte extra kabelknoop. Dit is een begrensde heuristische zoekstap, geen bewijs van onmogelijkheid of garantie van een globaal optimaal stationsaantal. Iedere geaccepteerde kandidaatverdeling behoudt alle punten, exclusieve verbonden routes, capaciteitsgrenzen en de oorspronkelijke maximale afstand. Kandidaten worden daarna met dezelfde controles gesnoeid. De handmatige exacte stationskeuze wordt hierdoor niet veranderd.

Daarna kwam een tweede fout aan het licht: een overlapvlak van circa 7,13 m² lag vrijwel op samenvallende grenzen. Het representatieve punt werd door afronding buiten één eigenaar geclassificeerd, hoewel vrijwel het hele vlak in beide gebieden lag. Gevolg: 0,78 m van een route en één aansluiting verloren hun eigen gebied. Eigenaren worden nu met de oppervlakte van het hele atomaire vlak bepaald. Voor numerieke snippers blijft de puntterugval beschikbaar; ontbrekende dekking wordt onafhankelijk begrensd. De werkelijke Vaartbroek-proef en de eerdere Den Dungen-geometrie slagen beide.

## Volledige berekening en onafhankelijke controle

De echte `WorkflowRunner.cluster` met de gebruikelijke optimalisaties is opnieuw uitgevoerd op lokale kopieën van de bestaande voorbereide import, woningtypen en ontwerpstroomlaag. Geen plangebied; maximale route 850 m, nieuw station 630 kVA, voorkeursbenutting 80%. De voorkeursbenutting is een optimalisatiedoel, geen harde ondergrens. Het net bevat 39 losse componenten; een totaal-capaciteitsberekening alleen is daarom onvoldoende om het benodigde stationsaantal te bepalen.

| Controle | Werkelijke uitkomst |
| --- | --- |
| Aansluitingen | 4.266; bron-ID's exact behouden, niets weggelaten |
| Som ontwerpstroom | 29.978,7 A; gelijk aan bronlaag |
| Bestaande / nieuwe stations | 24 / 41 |
| Langste route | 762,1561 m; oorspronkelijke grens 850 m |
| Maximale benutting | 99,96238%; geen overschrijding |
| Gebiedsoverlap | 4,66 × 10⁻¹⁰ m²; numerieke nul |
| Ontbrekende gebiedsdekking | 0 m² |
| Native topologische dekkingscontrole | Geldig |
| Punten en stations in eigen gebied | Allemaal |
| Route buiten eigen gebied | 0 m bij bestaande controletolerantie |
| Door clusters gedeelde route | 0 m |
| Clustergebieden | Alle gebieden geldige enkelvoudige polygonen |
| Latere stroomwijziging | Werkelijke batchvoorstelcontrole geslaagd; uitvoer onveranderd |
| QGIS-project | Geldige vectorlagen en twee layouts |

Het definitieve proces eindigt met ‘Volledig LS-netontwerp gereed’ en een lege waarschuwingenlijst. De feitelijk opgeslagen GeoPackage is onafhankelijk ingelezen voor aantallen, bronselectie, stroom, capaciteit, dekking, route-eigendom en exclusiviteit. QGIS-project en layouts zijn opnieuw ingelezen; PDF en PNG zijn gemaakt. Een afzonderlijk hersteld pakket op de netwerkschijf behoudt de oorspronkelijke bestanden en gebruikt eigen invoerkopieën en workflowkoppelingen.

## Regressies

- `test_station_recovery.py`: een synthetisch padnet dat v1.27.2 ten onrechte afwijst wordt door beide herstelvarianten veilig verdeeld met drie nieuwe stations. Werkelijke belasting, routegrens, stationsworteleigendom, verbonden gebieden en gelijke uitvoer van de gewone/versnelde variant worden gecontroleerd. Een echt te zware vaste stationswortel blijft afgewezen.
- `test_cluster_boundary_partition.py`: overlapverdeling, parallelle routes, smalle geknikte stroken op geprojecteerde coördinaten, route-/punteigendom, fragmentoverdracht en behoud van geldige invoer.
- `test_auto_clustering_efficiency.py`: bestaande representatieve gevallen behouden de exacte oude toewijzingen, stationskeuzes, afstanden en eigendom, inclusief onmogelijke vraag.
- Bestaande tests geslaagd voor clusteringherstel, clusterbeheer, splitsen/samenvoegen/capaciteit, buitenroutes, begeleide correcties en de echte dashboardwidgets.
- Productiegeometrie Den Dungen opnieuw opgebouwd met de gewijzigde grensclassificatie: alle route-/puntcontroles en native dekkingscontrole geslaagd.

## Beperkingen

QGIS 4.2.3/Qt6 op Windows. De bestaande voorbereide XML/Excel/BAG-resultaten zijn gebruikt; geen volledige nieuwe bronimport of BAG-download. Geen volledige handmatige Desktop-kliktest en geen QGIS 3-uitvoering. De gevonden stationsverdeling is veilig binnen de gecontroleerde voorwaarden; het minimale mogelijke stationsaantal is niet bewezen. Andere werkelijk onbereikbare of overbelaste invoer blijft een duidelijke fout opleveren. Geen productiegegevens, bron-ID's of geometrieën naar GitHub geüpload.
