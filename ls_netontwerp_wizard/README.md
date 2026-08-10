# LS Netontwerp Wizard

Deze QGIS-plugin begeleidt de workflow van GEN XML/Excel-invoer naar ontwerpstroom, clustering, handmatige correcties, sleuven/routes en nette clustergebieden.

## Hoofdworkflow

De wizard gebruikt zes gekleurde hoofdstappen:

1. Invoer & ontwerpstroom
2. Brondata controleren
3. Clustering maken
4. Clustering aanpassen
5. Sleuven & routes
6. Clustergebieden

### Stap 3a – Automatische clustering

Gebruik `3a. Automatische clustering maken` wanneer de plugin zelf de clustering en eventuele nieuwe stations moet bepalen.

### Stap 3b – Handmatige clustering

`3b. Handmatige clustering maken` is een volledige alternatieve route:

1. Voer stap 1 uit en controleer zo nodig de brondata met stap 2.
2. Open stap 3b.
3. Selecteer aansluitingen met de lasso.
4. Maak H-xx-clusters en plaats per cluster het gewenste station met de gewenste kVA.
5. Zorg dat 100% van de aansluitingen aan een H-xx-cluster is gekoppeld.
6. Klik op `Handmatige clustering uitvoeren`.

Stap 3b maakt daarna zelf de resultaatlagen, kabelroutes en clustergebieden. Voor deze route worden geen extra automatische stations aangemaakt. Het resultaatproject wordt geopend en de voorbereide H-xx-indeling wordt automatisch exact toegepast. Je hoeft dus niet meer terug naar stap 3a en ook niet apart de voorbereide clusters af te dwingen.

De normale capaciteit-, route- en topologiecontroles blijven van toepassing. Wanneer een handmatig cluster bijvoorbeeld te zwaar is voor het gekozen station of niet geldig over het kabelnet kan worden aangesloten, kan de berekening worden geweigerd.

### Stap 4b – Visuele handmatige clustereditor

Na clustering kun je met stap 4b aansluitingen visueel verplaatsen, nieuwe H-xx-clusters/stations maken en bestaande resultaatclusters corrigeren.
