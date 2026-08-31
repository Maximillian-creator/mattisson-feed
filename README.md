# Mattisson feeds → Stock Sync

Haalt de catalogus van **Mattisson Healthstyle** (`mattisson.nl`) op en genereert
twee XML-feeds voor [Stock Sync](https://stock-sync.com). Beide draaien
automatisch via GitHub Actions; je hoeft niets handmatig te doen.

> **Waarom deze repo bestaat.** Tot 31-08-2026 liep de Mattisson-feed via een
> Channable-URL van de leverancier. Die is ingetrokken (HTTP 403 AccessDenied),
> waardoor de Stock Sync-taak elke nacht "0 updated / 505 total variants — geen
> overeenkomsten gevonden" gaf. Deze feed haalt dezelfde gegevens uit de publieke
> webshop, zodat we niet meer van hun export afhankelijk zijn.

| Feed | Script | Output | Doel | Schema |
|---|---|---|---|---|
| **Update-feed** | `scraper.py` | `mattisson_feed.xml` | Prijs + beschikbaarheid van **bestaande** producten | 2× per dag (05:00 + 17:00 UTC) |
| **Add-feed** | `add_scraper.py` | `mattisson_add_feed.xml` | **Nieuwe** producten aanmaken met álle info | 1× per week (ma 03:00 UTC) |

## Feed-URL's (Stock Sync)

```
Update:  https://raw.githubusercontent.com/Maximillian-creator/mattisson-feed/main/mattisson_feed.xml
Add:     https://raw.githubusercontent.com/Maximillian-creator/mattisson-feed/main/mattisson_add_feed.xml
```

## Waar de gegevens vandaan komen

Geen login, geen sleutel, geen CAPTCHA — alles is publiek:

| Bron | Levert |
|---|---|
| `sitemap.xml` | alle productpagina's (de blokken met `<image:>`) |
| GraphQL (`/graphql`, publiek endpoint) | artikelnummer per variant (`MT2336`), adviesprijs én actieprijs |
| JSON-LD op de productpagina | titel, omschrijving, afbeeldingen, voorraadstatus per variant |
| `initConfigurableOptions(...)` in de pagina-JS | **de EAN-code per variant** + het optielabel ("90 tabl") |

De EAN staat *niet* in GraphQL en de losse variantprijs staat *niet* in de
pagina-JS — daarom worden beide bronnen gekoppeld, op optielabel. Wat niet
koppelt, valt weg mét melding: liever een variant minder dan een prijs op het
verkeerde artikel.

## Matchen op EAN, niet op SKU

De `sku` van het ouderproduct in Magento is een **naam** ("Magnesium Bisglycinaat
tabletten"), geen artikelnummer. Belangrijker: **alle 505 Mattisson-varianten in
onze Shopify hebben een lege SKU** en alleen een barcode. Daarom:

> **Stock Sync → Product Identificeerder = Barcode (EAN).**

Het echte artikelnummer van Mattisson gaat wél mee in het veld `sku`, zodat die
lege SKU's later in één keer gevuld kunnen worden.

## Prijs: adviesprijs of actieprijs?

Mattisson voert wisselende kortingen op de eigen webshop (bv. advies € 19,95 →
€ 14,96, dus −25%). De feed levert allebei, zodat het een keuze is en geen
automatisme:

| Veld | Betekenis |
|---|---|
| `price` | **adviesprijs** (regular price, incl. BTW) |
| `actieprijs` | wat mattisson.nl vandaag vraagt (final price, incl. BTW) |

> Map standaard **`price`** op de verkoopprijs. Wie `actieprijs` mapt, neemt de
> tijdelijke acties van de leverancier over in de eigen winkel — inclusief het
> moment waarop die actie stopt.

Er staat **geen kostprijs** in de feed: de inkoopkorting van Mattisson ligt niet
vast in dit project. Zodra die bekend is, is dat één regel in `scraper.py`.

## Voorraad

De webshop geeft alleen in/uit voorraad (`schema.org/InStock`), geen aantallen.
Daarom levert de feed `available` = `true`/`false` en géén `quantity`.

> **Zet in Stock Sync "niet in feed" op _voorraad 0_, nooit op archiveren of
> concept.** Stock Sync heeft in deze winkel al drie keer een hele
> leverancierscatalogus stilgezet (tot 44 dagen onvindbaar) toen een feed leeg of
> half binnenkwam.

Als extra slot stoppen beide scripts zichzelf: onder **350 productpagina's** in de
sitemap of onder **400 varianten** in het resultaat wordt er géén XML
weggeschreven. De oude feed blijft dan staan — dat is veiliger dan een halve.

## Nieuwe producten aanmaken (add-feed)

De add-feed staat op `published = false` (concept-only) en is **plat per variant**,
gegroepeerd via `handle`. In Stock Sync "Add Products":

- Parent node = `products.product[*]`, **Variant Node leeg laten**
- Variantgroep-veld → `handle`, Variant Optie 1 → `option1`
- "Varianten samenvoegen in bestaande producten" **aan**
- **`description` niet mappen op de update-feed** (beschermt onze eigen teksten)

De teksten in de add-feed zijn letterlijk die van Mattisson. Draai daarom vóór
publiceren:

```bash
python themis_check.py
```

Dat schrijft `mattisson_themis.md` met elke claim die bij ons niet zomaar mag.
`mattisson_tekstbron.csv` laat per variant zien hoeveel tekst en hoeveel
afbeeldingen er zijn — zodat "412 producten met beschrijving" een getal is dat je
kunt nakijken.

## Lokaal draaien

```bash
pip install -r requirements.txt
INSECURE_SSL=1 MAX_PRODUCTEN=10 python scraper.py
```

- `INSECURE_SSL=1` — alleen lokaal, achter de SSL-onderscheppende proxy
- `MAX_PRODUCTEN=10` — beperk tot de eerste tien pagina's tijdens ontwikkelen
- `TEST_URL=<productpagina>` — één product doorrekenen
