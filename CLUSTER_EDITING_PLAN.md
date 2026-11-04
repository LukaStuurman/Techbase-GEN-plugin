# Automatische clusters aanpassen — uitvoeringsplan

Uitgangspunt: main/v1.25.5. Het gekleurde dashboard in `themed_dialog.py` is de echte ingang; de verborgen oude actiegroep is onvoldoende. Bestaande 4a–4d blijven bereikbaar.

## Uit te voeren

1. Voeg zichtbare dashboardingangen 4e–4h toe voor capaciteit, samenvoegen, splitsen/bijplaatsen en controleren/herberekenen. Gebruik de bestaande snapshot-wachtrij en transactie voor alle wijzigingen.
2. Capaciteit: wijzig ontwerp-kVA van een actief station; werk alle afgeleide tabellen bij, wijs overbelasting af en bewaar de ontwerpkeuze voor volgende clustering.
3. Samenvoegen: expliciete bron/doelkeuze via de bestaande veilige retire-bewerking. Beschermde stations blijven beschermd; broninventaris blijft behouden.
4. Splitsen/bijplaatsen: selecteer een deel van één cluster, kies een unieke stationsnaam/capaciteit en een echte sleufknoop binnen het brongebied. Voeg station en afhankelijke records met unieke objectnummers toe; bereken echte routes. Geen leeg station of willekeurige vrije kaartlocatie.
5. Herberekenen: geselecteerd station of alle routes opnieuw berekenen met behoud van toewijzingen. Meld en blokkeer terugvallen op oude routes. Bouw gebieden één keer op en controleer geldigheid, dekking en overlap.
6. Kaartselecties: clustergebied/routes, lange routes, nulwaarden en ontbrekende stationstoewijzingen. Maak wachtrij wissen bereikbaar. Beveilig tegen gewijzigde bronlagen én stationsregels en tegen dubbel starten tijdens verwerken.
7. Test met QGIS 4.2.3: bestaande regressies, nieuwe rekengevallen, echte Qt-dashboardnavigatie, kaartlocaties/CRS, GeoPackage-toepassen en exact undo, afwijzingen en rollback. Controleer ook QGIS 3.44 waar uitvoerbaar. Bewaar schermafbeeldingen en benoem beperkingen.
8. Pas versie pas aan na geslaagde controles; commit op main en laat de bestaande GitHub-releaseworkflow de installatie-ZIP publiceren. Controleer release-uitkomst.

## Afbakening

Automatisch opnieuw optimaliseren van alle clusters, lege reserve-stations, vrije ligging buiten sleuven, willekeurige kabeltakdoorsnijding en handmatig onveilige geforceerde toewijzing vallen buiten deze uitbreiding. Bestaande geavanceerde gereedschappen blijven beschikbaar. Synthetische representatieve netten vervangen geen acceptatietest met de volledige productiegegevens.
