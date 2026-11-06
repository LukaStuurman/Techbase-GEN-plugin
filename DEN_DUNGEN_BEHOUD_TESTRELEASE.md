# Testrelease 1.33.3-rc.2 - eerst eindmof, dan pas richting vrijgeven

6 november 2026. Concept-PR #29, geen merge en geen productiegoedkeuring.

## Gewijzigd gedrag

Bij een overschrijding van stroom, trafovermogen of routeafstand wordt eerst vanaf het verre einde ingekort. De plugin stelt een knip/eindmof voor bij een bestaande, verifieerbare kabelknoop. Alleen de consumenten achter dat kabeldeel worden samen vrijgegeven; het berekenbaar passende voortraject blijft bij het oorspronkelijke station. Na iedere stap worden kabeldelen, gG-advies, routeafstand en trafo opnieuw getoetst. Een hele richting valt pas af wanneer geen passend voortraject met aansluitingen overblijft.

Afzonderlijk gecodeerde voedingen achter een verdeelkast houden hun eigen groepscontrole. Bij een overbelaste bovenliggende kabel wordt eerst het achterste deel geprobeerd, zodat de bovenliggende richting en andere aftakkingen niet onnodig vervallen. Meervoudige groepslidmaatschappen en flat-eenheden worden samen vrijgegeven. Bestaande stations krijgen nooit aansluitingen van een ander oud station; vrijgegeven/nieuwe aansluitingen gaan alleen naar nieuwe stations.

`eindmof_voorstellen.csv` bevat de pogingen en hun huidige status. `Actueel_voorstel` onderscheidt voorstellen die na verder inkorten nog actueel zijn; `Behoudbaar_voortraject` toont of er nog een voortraject met behouden aansluitingen ligt. Alleen actuele, geometrisch bewezen voorstellen komen in `eindmof_voorstellen.geojson` en bij een geslaagd ontwerp in de gelijknamige GeoPackage-laag. Het zijn conceptvoorstellen voor fysieke netwijzigingen, geen bestaande assets. Een niet bewezen bronroute krijgt geen verzonnen moflocatie.

## Overige vastgelegde bron- en rekenregels

- De aansluitingenlaag uit XML/Excel bepaalt de oorspronkelijke kabelgroepen; de stations-CSV vult alleen Station via exact Master Asset ID.
- Aansluitkabels blijven voor de verbinding bestaan, maar tellen niet mee voor elektrische kabelberekeningen of rekenlengte. Hun aansluitstromen blijven wel belasting voor hoofdnet en trafo.
- OV is optioneel uitsluitend route. OV-hoofdkabellengte telt wel voor de routegrens; elektrische OV-beoordeling blijft expliciet open. Er worden geen LS-rekenwaarden voor OV verzonnen.
- Onbekende LS-hoofdkabeltypen krijgen geen fictieve cataloguswaarden. Waar mogelijk wordt vóór dat deel een eindmof voorgesteld en blijft een toetsbaar voortraject behouden.
- Onzekere historische richtingen worden alleen in de expliciete CONCEPT-optie aan nieuwe stations aangeboden, met broncontrole als open punt. Een fout in een aftakking verwijdert niet automatisch iedere zustergroep. De strikte modus blijft blokkeren bij onbewezen routes.
- Getypeerde sourceindpunten en fysieke kabeleindcontacten blijven bij de historische trace bestaan. Een geometrische kruising bewijst geen elektrische koppeling. Interne kastverbindingen moeten in het kabelnet zijn bewezen.

## Validatie en beperkingen

De gerichte eindmofproef met aansluitingen op 40, 70 en 100 meter en een grens van 80 meter behoudt de eerste twee aansluitingen, 70 meter oorspronkelijk kabelpad en 40 A oorspronkelijke trafobelasting. Het eindmofvoorstel ligt op de echte knoop op 70 meter; de aansluiting op 100 meter is uitsluitend beschikbaar voor een nieuw station. Extra gevallen controleren trafobegrenzing, gezamenlijke vrijgave achter de knip, een verdeelkast met eigen code, onbekend LS-type en een richting zonder houdbaar voortraject.

De regressies worden rechtstreeks met de geïnstalleerde QGIS 4.2.3-Python uitgevoerd, zonder computerbediening. Ze controleren Kader 2.0/3.2, stationsretentie, eindmofvolgorde, kabeltrace, oude/uitsluitend nieuwe stations, verdeelkasten, meervoudige groepen, aansluitkabeluitsluiting, conceptvrijgave, stationomtrekken, ontbrekende capaciteit, buitenroutes, netwerkherstel, LS-/OV-schema en pluginladen. De exacte laatste testuitslagen staan in het lokale controlepakket.

Echte GEN/XML/Excel/GeoPackage-gegevens voor Den Dungen zijn beschikbaar. De stations-CSV geeft 1.998 exacte matches op 2.763 bronpunten. Binnen het plangebied liggen 1.928 aansluitingen en zijn 15 bestaande stations met bruikbare capaciteit beschikbaar. De capaciteit van 044.532 en 044.052 ontbreekt; deze wordt niet verzonnen. Geïnstalleerde richtingzekeringen en actuele schakelingen zijn nog niet bevestigd. Zonder bevestigde gG zijn zekeringwaarden uitsluitend berekende adviesmaxima.

De voorlopige behoudcontrole beoordeelt 1.844 oorspronkelijke aansluitingen: 890 behouden, 718 rekenkundig vrijgegeven en 236 met open bron-/scheidingscontrole. Er zijn 660 knippogingen vastgelegd; daarvan staan 48 actuele, geometrisch bewezen voorstellen op de controlekaart. Deze aantallen zijn tussenresultaten, geen definitieve clusterindeling. De overige 84 punten binnen het plangebied hebben in deze behoudcontrole geen geldige oorspronkelijke station/groep-combinatie.

Een vervolgreplay op het daadwerkelijk opgebouwde Den Dungen-kabelnet gebruikt na herstel de expliciete flatkastterminals en alle aanwezige nul-rekenmeter verbindingen naar de originele stationsuitgangen. Die vervolgcontrole stopt bij aansluitingseenheid 39: het resterende vrijgegeven kabeldeel bevat geen veilige nieuwe stationslocatie in het huidige plaatsingsnet. Daar is nog een aantoonbaar uitvoerbare nieuwe locatie/voedingsroute nodig. De fysieke realisatie van knip/eindmof en nieuwe voeding blijft open; het softwarevoorstel alleen bewijst die uitvoering niet.

**De volledige Den Dungen-clustering is nog niet als geslaagd gevalideerd.** De voorlopige behoudcontrole en eindmofvoorstellen zijn nog geen goedgekeurde nieuwe clusterindeling. Ook als de conceptberekening kan worden afgerond, blijven broncontroles, fysieke knipuitvoering en elektrische OV-beoordeling afzonderlijk open. Deze testrelease mag lokaal worden beproefd, maar niet als vrijgegeven netontwerp worden gebruikt. QGIS 3 is niet lokaal getest.

## Lokale proef

Installeer de ZIP via QGIS > Plugins beheren en installeren > Installeren vanuit ZIP en herstart QGIS volledig. Werk op een projectkopie met een nieuwe uitvoermap. Kies automatische clustering en de behoudmodus. De optie **Eerst houdbaar voortraject met eindmof behouden** staat standaard aan. Vul voor schemabewijs de bijbehorende LS-schema XML, veld/rail/smelt-Excel en LS-schema-DXF in. Zet OV uitsluitend als route aan volgens de afgesproken werkwijze. De optie voor onzekere richtingen is een expliciete conceptkeuze en staat standaard uit.

Controleer per aansluiting het oorspronkelijke station, de oorspronkelijke volledige groepscodes en het behoud-/vrijgavebesluit. Controleer vervolgens de eindmofvoorstellen, actuele voortrajecten, aparte verdeelkastgroepen, routegrenzen, kabeltypen en de werkelijke beveiligingen/schakelingen. De openbare release bevat alleen software en deze notitie; lokale bronlagen, aansluitingslijsten en kaartresultaten blijven op de computer/netwerkschijf.
