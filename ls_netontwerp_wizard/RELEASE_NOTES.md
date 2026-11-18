# LS Netontwerp Wizard v1.33.6

## Ontwerpstroomtabellen per kader

- Onder **Geavanceerde opties → Ontwerpstroomtabellen** toont de plugin de tabellen die horen bij het bovenaan geselecteerde **Kader 2.0, 3.0 of 3.2**.
- Ieder kader heeft een onafhankelijke set tabelwaarden. De eerder gebruikte keuze 3.1 wordt als de huidige 3.2 behandeld. De bewaarde 3.1/3.2-rekenwaarden blijven de standaard voor 3.2.
- Per tabel kun je rijen aanpassen, toevoegen, kopiëren, verplaatsen of verwijderen en waarden uit een spreadsheet plakken. Met **Standaard herstellen** herstel je één tabel.
- Met **Kader X opslaan** bewaar je alle tabellen van het gekozen kader lokaal en in het geopende werkproject. Met **Kader X standaard herstellen** zet je de oorspronkelijke waarden voor dat ene kader terug, na bevestiging. Andere kaders blijven intact.
- Bij opnieuw openen worden eerder opgeslagen wijzigingen hersteld. Voor oudere werkprojecten met enkelvoudige tabellen is een migratieroute toegevoegd. Handmatig aanpaste waarden blijven gescheiden van de ingebouwde bronwaarden.

## Volledige Kader 2.0-tabellen

- **Wonen Type 1–4:** per woningtype afzonderlijk trafo- en kabelverbruik én afzonderlijke opwek.
- **Zakelijk Type 6/7:** toekomstige aansluitwaarde, eigen ontwerpstroom voor trafo en kabel, inclusief bestaande kleine en zware aansluitprofielen.
- **Gasadvies:** gascategorie en huidige elektrische aansluitwaarde, met onafhankelijk trafo- en kabeladvies (zoals 138 A tegenover 65 A). De oorspronkelijke afhankelijkheid van de huidige aansluiting kan als **-1 = huidige aansluiting volgen** worden vastgelegd.
- **Straatmeubilair Type 9:** laagste 3×25 A-profiel bij ontbrekende doorlaat, en aparte regels voor precies 3×35 A versus 3×40–50 A.
- **Publiek laden Type 8:** afzonderlijke stroomwaarden voor trafo en kabel.
- **Stijgleidingen:** Type 3/4 en zakelijke Type 6-aansluitingen, als afzonderlijke hulprekenregels.
- **Aanvullende ampèrestaffel:** de bestaande 3.2-omzetting voor zwaardere 2.0-aansluitingen zonder vaste originele staffel heeft een eigen bewerkbare tabel.

### Berekening en invoer

De Kader 2.0-tabellen worden bij de ontwerpstroomberekening en bij latere herberekeningen daadwerkelijk gebruikt. De oorspronkelijke Excel-constanten blijven intact als bron voor **Standaard herstellen**. Geldigheid van numerieke waarden, gascategorieën, overlappende bereiken en woningtypes wordt bij het opslaan gecontroleerd.

**Let op:** het bewerken van tabellen verandert niet stilzwijgend een eerder berekende QGIS-laag. Voer een nieuwe ontwerpstroomberekening uit om bestaande aansluitingen te actualiseren. De Type 5-verwarmingstoeslag en afzonderlijke stijgleidingberekening hebben nog geen volledige automatische invoer in de normale GEN-workflow; tabellen voor stijgleidingen zijn voorbereid voor die aparte berekening.

## Validatie

- De GitHub-regressietests [run 44322567060](https://github.com/LukaStuurman/Techbase-GEN-plugin/actions/runs/44322567060) zijn geslaagd.
- **144 Python-bronbestanden** zijn syntactisch gecontroleerd.
- Bestaande Kader 2.0/3.2-regressies, gasherstel, straatmeubilair, kabelgroepen en stationscontroles zijn geslaagd.
- De aangepaste Kader 2.0-tabellen zijn met zuivere Python-regressies gecontroleerd op echte toepassing in de berekening, originele waarden, gasverschillen en afwijzen van ongeldige tabelcellen.
- Echte offscreen **QGIS/PyQt**-tests zijn geslaagd voor drie onafhankelijke kaders, wijzigen, QSettings-opslag, heropenen, herstellen en verwerking van gewijzigde ontwerpstroomwaarden. Ook de wizardcontrole over tien pagina's en de bestaande UI-tests is geslaagd.
- Er is geen afzonderlijke volledige handmatige eindgebruikerstest met een live Den Dungen-project uitgevoerd. QGIS 4 is in deze reeks niet native getest.

## Installatie

Download de ZIP en installeer via **QGIS → Plugins → Plugins beheren en installeren → Installeren vanuit ZIP**. Herstart QGIS volledig. Open het instellingenvenster, kies je gewenste kader en bewerk tabellen onder **Geavanceerde opties → Ontwerpstroomtabellen**.

[Vorige versie v1.33.5](https://github.com/LukaStuurman/Techbase-GEN-plugin/releases/tag/v1.33.5) · [Pull request #33](https://github.com/LukaStuurman/Techbase-GEN-plugin/pull/33)
