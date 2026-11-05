## Aanvulling v1.33.2: afzonderlijk 2.0-gasadvies uit ingesloten afbeeldingen

De eerdere vergelijking was onvolledig: **Kader 2.0 heeft wel degelijk een aparte gasadviesstaffel**, maar deze is in de Excel opgeslagen als **twee EMF-afbeeldingen** naast het werkblad `Ontwerpstroom_trafo`, niet als tabelcellen. De keuze voor Type 6/7 blijft gebaseerd op de **toekomstige** elektra-aansluitwaarde; het gasadvies kijkt naar **de huidige gas- én elektra-aansluiting** en verhoogt zo nodig de ontwerpstroom. De grootste van deze twee waarden geldt per netniveau.

| Huidige gascategorie | Huidige elektriciteit | Trafo: geadviseerde E-aansluiting | LS-kabel: geadviseerde E-aansluiting |
|---|---|---|---|
| G4/G6/geen | kleiner dan 3×35 A | 3×25 A | 3×25 A |
| G4/G6/geen | 3×35 t/m 3×160 A | Huidige E-aansluiting | Huidige E-aansluiting |
| G4/G6/geen | groter dan 3×160 A | 3×250 A | 3×250 A |
| G10 t/m G25 | kleiner dan 3×35 A | 3×50 A | 3×50 A |
| G10 t/m G25 | 3×35 t/m 3×50 A | 3×80 A | 3×80 A |
| G10 t/m G25 | 3×63 t/m 3×80 A | **3×160 A** | **3×80 A** |
| G10 t/m G25 | vanaf 3×100 A | 3×250 A | 3×250 A |
| >G25 | t/m 3×80 A | **3×250 A** | **3×80 A** |
| >G25 | vanaf 3×100 A | 3×250 A | 3×250 A |

Bij een **3×25 A** kleinzakelijke aansluiting zonder gasadvies geldt 8,7 A als minimum. Een kleinere zakelijke doorlaatwaarde (of niet-residentieel BAG zonder bekende doorlaat) krijgt **automatisch toekomstige 3×25 A**. Er wordt géén hogere bekende huidige aansluiting automatisch tot 3×25 A verlaagd. Voor gascategorieën als G10 en >G25 ligt het aanbevolen minimum hoger (bijvoorbeeld huidig 3×63 A met G10: **138 A trafo / 65 A kabel** bij een toekomstige 3×25 A-keuze).

De huishoudens blijven **tot en met 3×40 A** huishouden; boven 3×40 A volgt de zakelijke rekenlogica. Ook de gasstaffel verandert **geen enkele 3.2-waarde**: deze nieuwe regels zijn uitsluitend voor de 2.0-tak.

# Vergelijking Eea-0205.K 2.0 en 3.2 — QGIS-plugin v1.33.1

## Wat is de bron?

In deze vergelijking zijn beide **door de gebruiker aangeleverde** Excel-workbooks onderzocht:
- `Eea-0205.K 2.0.xlsx`: bladen `Ontwerpstroom_trafo`, `Ontwerpstroom_kabel`, `Ontwerpstroom_stijgleiding`.
- `Eea-0205.K 3.2.xlsx`: bladen `Transformator`, `(1)` t/m `(12)`, `Stijgleiding`, `Versie beheer`.

De 3.2-workbook biedt ook kleinzakelijk en grootverbruik; het verschil is **niet** het bestaan van die categorieën, maar hun **invoergrondslag**.

## Principieel verschillende zakelijk-tarieven

| Onderdeel | Kader 2.0 | Kader 3.2 |
|---|---|---|
| Kleinzakelijk (Type 6 in 2.0, Type 8 in 3.2) | **Toekomstige** E-aansluitwaarde, onafhankelijk van gas | **Huidige** E-aansluitwaarde + gasaansluitcategorie |
| Grootverbruik LS (Type 7 in 2.0, Type 9 in 3.2) | **Toekomstige** waarde; 3×160 en 3×250 expliciet, `overig` zonder vast Excel-tarief | **Huidige** waarde + gas; onder meer 3×100, 125, 160, 200 en 250 |
| Gas bij zakelijke aansluitingen | Geen aparte gasstaffel in 2.0-ontwerpstroomblaadjes | G4/G6/geen, G10–G25 en >G25 apart |
| Kaderkeuze in plugin | Geheel zelfstandige 2.0-rekenmodule | De **bestaande keuze met het oude opschrift 3.1**, nu hernoemd naar **3.2**, met alle oorspronkelijke pluginwaarden onveranderd |

### Voorbeelden in ampère per eenheid

| Casus | Kader 2.0 | Excel 3.2 |
|---|---:|---:|
| Zakelijk, toekomstige 3×25 A | 8,7 A, trafo én kabel | Huidig <3×35 A, G4/G6/geen: 8,7 A |
| Zakelijk, toekomstige 3×63 A | 65 A, trafo én kabel | Huidig 3×63 A, G4/G6/geen: 51 A, trafo én kabel |
| Zakelijk, toekomstige 3×63 A | 65 A | Huidig 3×63 A, G10–G25: 138 A trafo / 65 A kabel |
| Zakelijk, toekomstige 3×160 A | 138 A | Huidig 3×160 A, G4/G6/geen: 138 A |
| Zakelijk, toekomstige 3×200 A | Geen vaste waarde: *overig* | Huidig 3×200 A, G4/G6/geen: 210 A |
| Publiek netbewust laden 3×25 A | 5,8 A trafo / 6,7 A kabel | 3,7 A trafo / 4,8 A kabel |

**Let op:** bovenstaande **3.2-Excelwaarden** dienen voor vergelijking; de reeds bestaande **3.1-profielwaarden in de plugin zijn niet aangepast** om overeenkomsten met de externe spreadsheet af te dwingen. De naamswijziging is alleen een naamswijziging. De regressietest bewaakt de voormalige pluginmatrices en rekent dezelfde fixtures met de labels 3.1 en 3.2 door.

## Verschillende woningtypen

**2.0** heeft laagbouw Type 1 (individuele warmtepomp) en Type 2 (gas/stadsverwarming), en hoogbouw Type 3 (collectief) en Type 4 (individuele warmtepomp). De warmtebron bepaalt het type; **bouwjaar bewijst de warmtebron niet**. Daarom kun je op de ontwerpstroomcorrectiepagina bij Kader 2.0 nu expliciet **Type 1–4** kiezen. `Kader20Type` wordt opgeslagen voor de gekozen aansluiting(en). Zonder keuze blijft de bestaande bouwjaar-aanname zichtbaar in `KaderType`.

**3.2** heeft zes huishoudtypen met een apart onderscheid **t/m 2021** en **vanaf 2022**. Daardoor is bijvoorbeeld Kader 3.2 Type 3 niet hetzelfde als Kader 2.0 Type 3. De plugin gebruikt het oude `OntwerpstroomType`-veld daarom **niet** rechtstreeks als Kader-2.0-type.

## Werkwijze Kader 2.0 in de plugin

1. Kies bovenaan **Kader 2.0** en bereken ontwerpstromen. Kader 3.2 is de hernoemde oude keuze.
2. Bij **zakelijke aansluitingen**: leg de **toekomstige** waarde vast via `Kader20ToekomstigeAansluitwaarde` (bv. `3 x 160 A`). Omdat die vóór de berekening vaak nog niet in GEN staat, worden zakelijke aansluitingen **zonder zo'n waarde op 0 A gezet met duidelijke waarschuwing**, in plaats van de huidige doorlaatwaarde te gebruiken.
3. Herstel deze nulwaarden in de bestaande ontwerpstroomcorrectie: kies **Zakelijk → Toekomstige aansluitwaarde**. De gekozen toekomstwaarde wordt nu **in de laag opgeslagen** en de stroom wordt op trafo- en kabelniveau met Kader 2.0 berekend. Gascategorie is voor Kader 2.0 verborgen; voor 3.2 blijft deze zichtbaar en werkzaam.
4. Bij **Huishoudelijk** kies je desgewenst Type 1/2 (laagbouw) of Type 3/4 (hoogbouw). Met `Zelf invullen` kunnen ongedefinieerde gevallen handmatig worden afgehandeld; handmatige wijzigingen blijven zichtbaar als zodanig.
5. Controleer `Hoogste Trafo`, `Hoogste Kabel`, `KaderVersie` en `KaderType` vóór clusteren. 0 A zonder ingevulde toekomstige waarde is **geen geldige zakelijke ontwerpaannname**.

**2.0-speciale gevallen:** in Excel ontbreekt een vaste Type-7-waarde voor toekomstig 3×100, 3×125, 3×200 of een andere `overig`-aansluiting. Hiervoor blijft de automatische waarde 0 A met waarschuwing. Type 5 verwarmingscomponenten vragen expliciete aantallen, elektrisch vermogen en gelijktijdigheidsfactor; er wordt zonder zulke invoer niets bijgeteld. De aparte stijgleidingtabellen worden niet automatisch bij trafostroom opgeteld.

## Testgrenzen

- `test_kader_20.py`: exact de vaste 2.0-tarieven uit trafo-, kabel- en stijgleidingbladen.
- `test_kader_comparison_20_32.py`: snapshots van de oude 3.1-pluginmatrices, *identieke* 3.1/3.2-uitkomsten bij voorbeelden, strikte toekomstige zakelijke waarde in 2.0, gas-onafhankelijkheid, en laden.
- GitHub Actions voert beide tests en syntaxcontroles uit bij wijzigingen en vóór publicatie.
- **Niet uitgevoerd:** de volledige QGIS-interface- en praktijktoets op de echte GEN-/sleufgegevens van de gebruiker. Ook station **044.529** is niet opnieuw met de echte projectdata doorgerekend. De QGIS-specifieke test bestaat apart.

De eerdere clusteringwijzigingen uit v1.33.0 (directe kabel-Voronoi, bestaande KVA/Max_A, routelijnen op de originele sleufgeometrie) blijven in v1.33.1 behouden.
