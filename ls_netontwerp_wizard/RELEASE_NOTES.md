# LS Netontwerp Wizard v1.33.5

Deze versie verbetert de responsiviteit van de QGIS-wizard en de zichtbaarheid van aangrenzende stationsgroepen op de Scope-kaart.

## Responsieve vensters

- Het venster **Automatische clustering – instellingen** heeft geen horizontale scrollbar meer nodig. De inhoud volgt de beschikbare breedte, ook wanneer het venster smaller wordt.
- Lange omschrijvingen, het advies bij **Behoud originele bestaande stations en kabelrichtingen**, en checkboxteksten lopen automatisch door op volgende regels. De bijbehorende labelhoogte wordt na een breedtewijziging opnieuw bepaald, zodat regels niet worden afgesneden.
- De plangebiedkeuze en knop voor het toevoegen van een bestand staan bij beperkte ruimte onder elkaar. De vaste knoppenbalk verdeelt **Instellingen opslaan**, **Clustering starten**, **Berekend project herstellen** en **Sluiten** over één, twee of vier kolommen, afhankelijk van de ruimte.
- De oorspronkelijke checkboxwaarden, aan/uit-afhankelijkheden, tooltips, signalen en opslagfunctionaliteit blijven behouden. Ook een klik op de tekst schakelt de betreffende optie in of uit.
- In de gedeelde formulieropmaak kunnen lange velden en toelichtingen meeschalen en waar nodig onder het veldlabel doorlopen. Verticale scrolling blijft beschikbaar, terwijl de knoppen bereikbaar blijven.

## Contrast in de Scope-layout

- De kleuren van stationsgroepen worden niet uitsluitend op basis van willekeurige/stationgebonden kleuren of opgeslagen kleuren gekozen. De plugin vergelijkt de geografische nabijheid van de aansluitingen en stations en kiest voor naburige groepen een goed onderscheidbaar alternatief.
- De kleurkeuze is reproduceerbaar: dezelfde invoer geeft dezelfde resultaten. Bestaande kleuren blijven behouden waar ze voldoende verschillen; alleen waar nodig verandert de kleur.
- Ieder station, zijn aansluitingbollen en het bijbehorende kleurvakje in het stationsoverzicht gebruiken dezelfde groepskleur. **Geen station gekoppeld** blijft grijs.
- Bestaande opgeslagen Scope-layouts uit eerdere versies worden eenmalig aangepast. Daarna blijven eigen stijlwijzigingen behouden; heropenen verandert het palette niet opnieuw.
- De kleurcorrectie verandert **geen bronwaarden, ontwerpstromen, geometrieën, stationskoppelingen of kaartuitsnede**. Het clusteringoverzicht zelf behoudt zijn eigen ontwerpstijl en de bestaande legenda met één item **Aansluitingen**.

## Controles

- Python-syntaxcontrole geslaagd voor **141 bronbestanden**.
- De bestaande regressies voor Kader 2.0, Kader 3.2, gasherstel, aansluitprofielen en kabel-/stationslogica zijn geslaagd.
- De nieuwe zuivere regressies controleren de contrastkleurkeuze, groepen met gelijke oorspronkelijke kleuren, geografische nabijheid, lange clustertracés, volgorde-onafhankelijkheid en stations met beperkte informatie.
- De echte offscreen **QGIS 3.40.15/PyQt5**-controle is geslaagd bij **520, 720, 980 en 1180 px** vensterbreedte: geen horizontale scrollbar, volledige waarschuwingstekst, passende knopbreedtes, klikbare checkboxtekst en consistente Scope-kleuren/tabelvakjes.
- De bestaande native QGIS-test voor **tien wizardpagina's**, geavanceerde tabbladen, navigatie en beide editorstanden is eveneens geslaagd.
- Zie [de geslaagde PR-controle](https://github.com/LukaStuurman/Techbase-GEN-plugin/actions/runs/44300233322) en [de wijzigingen in PR #32](https://github.com/LukaStuurman/Techbase-GEN-plugin/pull/32).

**Beperking:** deze controles zijn uitgevoerd met representatieve en synthetische gegevens; de Scope-kleurverdeling is niet tegen een volledige daadwerkelijke Den Dungen-layout visueel beoordeeld. QGIS 4 is niet native in deze testreeks uitgevoerd.

## Installatie

Installeer het ZIP-bestand via **QGIS → Plugins → Plugins beheren en installeren → Installeren vanuit ZIP**. Herstart QGIS volledig en open je project. Herkenbare bestaande Scope-layouts krijgen daarna de eenmalige stijlcorrectie.

[Vorige stabiele release v1.33.4](https://github.com/LukaStuurman/Techbase-GEN-plugin/releases/tag/v1.33.4) · [Eerdere releases](https://github.com/LukaStuurman/Techbase-GEN-plugin/releases)
