# Techbase-GEN-plugin

## Handmatig herverdelen en eigen clusters maken (1.24.0)

Gebruik **4a. Aansluitingen herverdelen** om een bestaande clustering aan te passen, of **4b. Eigen cluster met station maken** om aansluitingen af te splitsen naar een nieuw station. Beide openen dezelfde begeleide editor:

1. Selecteer aansluitingen op de kaart, teken een selectie of kies een heel bestaand cluster.
2. Kies verplaatsen, een nieuw cluster maken of hele clusters samenvoegen. Zoek het doelstation op naam of kies het op de kaart. Nieuwe stations beginnen op 630 kVA; de locatie kan automatisch op een kabel worden voorgesteld of zelf op de kaart worden gekozen.
3. Controleer het aantal aansluitingen, de toegevoegde ontwerpstroom en de resterende stationscapaciteit. De uitvoerknop blijft onderaan zichtbaar tijdens het scrollen.

Samenvoegen neemt alle aansluitingen van de gekozen bronclusters mee en verwijdert hun stations na een geslaagde correctie. De vier bestaande veiligheidscontroles staan standaard aan en zijn bereikbaar onder **Geavanceerde instellingen en veiligheidscontroles**. De bestaande rekenengine werkt routes, statistieken, clustergebieden en layouts bij en maakt herstelkopieën. Tijdens de berekening zijn voortgang en annulering beschikbaar; annuleren wordt uitgeschakeld zodra het opslaan begint. Na een geslaagde wijziging worden de kaartselecties gewist. **Vorige selectie terughalen** haalt de laatste gebruikte aansluitingen terug; deze knop draait geen wijziging terug.

Gebruik **3b. Handmatige clustering maken** om vóór de berekening een eigen H-xx-indeling vast te leggen. Maak clusters, voeg aansluitingen toe aan een bestaand handmatig cluster of wis hun handmatige toewijzing. Als alleen het plangebied wordt berekend, telt de voortgang uitsluitend aansluitingen binnen dat gebied. Buiten het plangebied geselecteerde aansluitingen worden overgeslagen. Zodra alle relevante aansluitingen zijn ingedeeld, wordt **Handmatige clustering uitvoeren** beschikbaar. De editor heropent de bronlagen ook wanneer een resultaatproject is geladen.

Validatie: echte QGIS 4.2.3-widgetacties; echte correcties voor verplaatsen, nieuwe clusters en samenvoegen; voorbereiding, toewijzen en wissen binnen een plangebied; capaciteit, 630 kVA, dubbele namen, annulering en foutafhandeling; bestaande headless-, navigatie- en clustercorrectietests. De Qt-compatibiliteitscode voor QGIS 3 is behouden; deze versie is lokaal niet afzonderlijk uitgevoerd.
