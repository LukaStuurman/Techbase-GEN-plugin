# Den Dungen: clustering met plangebied, v1.27.2

## Aanleiding en oplossing

De opgeslagen diagnose meldde ‘Kabelroute 28 ligt 0.71 m buiten het eigen gebied’. Dit is gereproduceerd met het kabelnet geknipt op de plangebiedgrens. De lokaal geïnstalleerde versie was 1.27.0. Met de sinds 1.27.1 standaard ingeschakelde buitenroutes kon het volledige netwerk worden gebruikt en slaagde de routecontrole zonder de maximale afstand of capaciteit te verhogen.

Bij onafhankelijke gebiedscontrole bleken smalle verbindingsstroken bovendien circa 14,6326 m² overlap over negen grensvlakken te veroorzaken. `partition_cluster_overlaps` knipt uitsluitend die betwiste vlakken uit op basis van de echte routes, aansluitverbindingen en stationankers. Een leeg afgesneden fragment kon aan een buurgebied worden toegevoegd; de gezamenlijke grenzen zijn opnieuw geknoopt. Een geldige invoerdekking zonder overlap wordt ongewijzigd teruggegeven. Onoplosbare dekking of verdwijnende gebieden leveren een duidelijke fout; toewijzingen, stroom en routelimieten veranderen niet.

## Volledige productieproef

Uitgevoerd met lokale kopieën van de bestaande voorbereide GEN-import, woningtypen, aansluitingen en het actieve plangebied. De echte `WorkflowRunner.cluster` en de native QGIS-project-/layoutprocessen zijn gebruikt.

| Controle | Resultaat |
| --- | --- |
| Aansluitingen binnen de gekozen selectie | 1.985; aantallen en bron-ID's exact behouden |
| Bestaande / nieuwe stations | 16 / 18 |
| Som ontwerpstroom | 16.747 A; gelijk aan bronselectie |
| Maximale route | 642,8142 m; grens 850 m |
| Hoogste benutting | 99,99524%; geen station over capaciteit |
| Gebiedsoverlap | 4,66 × 10⁻¹⁰ m²; numerieke nul |
| Verschil met volledig plangebied | 0 m² |
| Native topologische dekkingscontrole | Geldig |
| Binnenliggende route buiten eigen gebied | 0 m bij bestaande controletolerantie |
| Door clusters gedeelde kabellengte | 0 m |
| Nieuwe stations binnen plangebied | Ja |
| Latere stroomwijziging | Werkelijke batchvoorstelcontrole geslaagd; resultaat onveranderd |
| QGIS-project / layouts | Alle vectorlagen geldig; twee layouts |

De definitieve clustering is na de grensreparatie opnieuw volledig uitgevoerd. PDF en PNG zijn gegenereerd en de kaart is visueel gecontroleerd. Er is een aparte kopie voor de gebruiker op de netwerkschijf gemaakt, inclusief voorbereide invoer, gekoppelde workflowinstellingen en twee opnieuw geopende projecten. De oorspronkelijke bronbestanden en mislukte uitvoer zijn behouden. Netwerk- en lokale pakketprojecten verwijzen ieder naar hun eigen invoerkopieën en workflowbestand.

## Regressies

Geslaagd in QGIS 4.2.3: `test_cluster_boundary_partition.py`, `test_cluster_management.py`, `test_cluster_extensions.py`, `test_external_plan_routes.py`, `test_guided_cluster_editing.py`, `test_clustering_recovery.py`, `test_project_recovery.py`, `test_uniform_ui.py`.

De nieuwe grensproef controleert parallelle routes op 0,8 m afstand met overlappende 0,75 m-stroken, het behouden van route-/punteigendom bij gesplitste overlap, behoud van stationankers bij fragmentoverdracht, oppervlaktebehoud en ongewijzigde geldige invoer. De definitieve productie-uitvoer is daarnaast onafhankelijk gecontroleerd op dekking, bronselectie, belastingen, route-exclusiviteit en projectgeldigheid.

## Grenzen van deze validatie

Geen volledige herimport van de ruwe XML/Excel en geen nieuwe BAG-aanvraag: de bestaande voorbereide resultaten zijn hergebruikt. Geen handmatige volledige QGIS Desktop-kliktest en geen uitvoering op QGIS 3. De uitgeschakelde buitenrouteoptie blijft een strikte netwerkbeperking; deze release claimt niet dat ieder daarmee onbereikbaar ontwerp alsnog uitvoerbaar is. De eerdere Vaartbroek-beperking blijft afzonderlijk beschreven in `CLUSTER_RECOVERY_VALIDATION.md`. Productiebestanden en bron-ID's zijn niet in de repository opgenomen.
