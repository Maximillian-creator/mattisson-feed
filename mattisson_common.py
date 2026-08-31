"""
Mattisson Healthstyle — gedeelde kern
=====================================
mattisson.nl is een publieke **Magento 2**-winkel (Hyva-thema, geen login).
De oude leveranciersfeed liep via Channable en is op 31-08-2026 ingetrokken
(HTTP 403 AccessDenied) — deze feed vervangt hem, zonder afhankelijkheid.

Vier bronnen per product:

  1. `sitemap.xml`                  -> alle productpagina's (blokken met <image:>)
  2. GraphQL (publiek endpoint)     -> per variant: **artikelnummer** (MT2336),
                                      adviesprijs (regular) en actieprijs (final)
  3. JSON-LD op de productpagina    -> naam, omschrijving, afbeelding en de
                                      Magento-id per variant
  4. `initConfigurableOptions(...)` -> per variant: **EAN-code**, optie-label en
     (inline JS-blok)                 de `salable`-kaart (= de echte voorraad)

Bijzonderheden van deze winkel:
- De `sku` van het OUDERproduct is een naam ("Magnesium Bisglycinaat tabletten"),
  maar de VARIANT heeft wel een echt artikelnummer (MT2336). We matchen in Stock
  Sync toch op **EAN/barcode**: alle 505 Mattisson-varianten in Shopify hebben
  een lege SKU en alleen een barcode. Het artikelnummer gaat mee in de feed zodat
  die lege SKU's later gevuld kunnen worden.
- Producten met een enkele variant hebben geen EAN in het JS-blok; die staat in
  de specificatietabel (`data-th="EAN-code"`).
- Mattisson voert **wisselende kortingen** (regular 19,95 -> final 14,96). De feed
  levert allebei: `price` = adviesprijs, `actieprijs` = wat zij vandaag vragen.
  Welke van de twee je in Stock Sync mapt is een bewuste keuze, geen automatisme.
- Voorraad is alleen in/uit voorraad, geen aantal. Let op: de JSON-LD meldt
  ALTIJD `InStock`, ook op een pagina die "Niet op voorraad" toont. De echte
  voorraad zit in de `salable`-kaart (varianten) en in het voorraadmerk van de
  pagina zelf (producten zonder varianten). Zie test_feed.py.

Lokaal testen achter een SSL-onderscheppende proxy: INSECURE_SSL=1.
Een product testen: TEST_URL=<volledige productpagina-url>.
Beperken tijdens ontwikkelen: MAX_PRODUCTEN=10.
"""

import concurrent.futures as cf
import json
import os
import re
import time
from html import unescape

import requests

BASE_URL = "https://www.mattisson.nl"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
BRAND = "Mattisson"
REQUEST_DELAY = 0.4
# Hoeveel productpagina's tegelijk. Standaard EEN, en dat is gemeten, niet
# gegokt: 40 pagina's kostten 37s met een worker en 49s met acht. Mattisson
# knijpt per bezoeker af, dus meer tegelijk maakt elke losse pagina trager.
# De knop blijft staan voor als hun kant ooit verandert.
WORKERS = int(os.environ.get("MATTISSON_WORKERS") or 1)

# Anti-archiveerslot: onder deze grens schrijven de scrapers geen feed weg.
# Stock Sync archiveert producten die niet in de feed staan, dus een halve feed
# is gevaarlijker dan geen feed. Peiling 31-08-2026: 444 productpagina's.
MIN_PRODUCTPAGINAS = 350

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; GFY-MattissonFeed/1.0)",
    "Accept-Language": "nl-NL,nl;q=0.9",
}

VERIFY_SSL = os.environ.get("INSECURE_SSL") != "1"
if not VERIFY_SSL:
    import urllib3
    urllib3.disable_warnings()

# Een sessie hergebruikt de TLS-verbinding; zonder dit kost elke pagina een
# nieuwe handdruk. Requests-sessies zijn veilig voor gebruik uit meer threads.
SESSIE = requests.Session()
SESSIE.headers.update(HEADERS)

LD_RE = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.DOTALL)
EAN_TABEL_RE = re.compile(r'data-th="EAN-code"[^>]*>\s*([0-9]{8,14})\s*<')
EAN_RE = re.compile(r"^[0-9]{8,14}$")


def _get(url, retries=3):
    for attempt in range(retries):
        try:
            resp = SESSIE.get(url, timeout=30, verify=VERIFY_SSL)
            resp.raise_for_status()
            return resp
        except requests.HTTPError as e:
            # Een 404 wordt bij een tweede poging geen 200; niet wachten.
            if e.response is not None and 400 <= e.response.status_code < 500:
                raise
            if attempt < retries - 1:
                wait = (attempt + 1) * 15
                print(f"    !  Fout ({e}), opnieuw in {wait}s...")
                time.sleep(wait)
            else:
                raise
        except Exception as e:
            if attempt < retries - 1:
                wait = (attempt + 1) * 15
                print(f"    !  Fout ({e}), opnieuw in {wait}s...")
                time.sleep(wait)
            else:
                raise


def sitemap_urls():
    """Productpagina's uit de sitemap (productblokken hebben <image:>).

    De sitemap loopt achter: op 31-08-2026 gaven 8 van de 444 regels een 404.
    Daarom is dit maar een van de twee bronnen; zie product_urls().
    """
    xml = _get(SITEMAP_URL).text
    urls = []
    for blok in re.findall(r"<url>(.*?)</url>", xml, re.DOTALL):
        if "<image:" not in blok:
            continue
        m = re.search(r"<loc>(.*?)</loc>", blok)
        if m:
            urls.append(unescape(m.group(1).strip()))
    return urls


def _graphql(query, variables=None):
    resp = SESSIE.post(
        f"{BASE_URL}/graphql",
        json={"query": query, "variables": variables or {}},
        headers={"Content-Type": "application/json"},
        timeout=60, verify=VERIFY_SSL,
    )
    resp.raise_for_status()
    return resp.json()


def catalogus_url_keys():
    """url_keys van alle producten via de categorieboom in GraphQL.

    Vangt de producten die de sitemap mist (bv. de wei-proteine-poeders, die
    onder een nieuwe url draaien terwijl de sitemap de oude blijft noemen).
    """
    boom = _graphql(
        '{categoryList(filters:{parent_id:{eq:"2"}})'
        '{uid product_count children{uid product_count}}}'
    )
    uids = []
    for cat in (boom.get("data") or {}).get("categoryList") or []:
        uids.append(cat["uid"])
        uids += [kind["uid"] for kind in cat.get("children") or []]

    query = """query($u:String!,$p:Int!){
      products(filter:{category_uid:{eq:$u}}, pageSize:100, currentPage:$p){
        items{url_key}
      }
    }"""
    keys = set()
    for uid in uids:
        pagina = 1
        while True:
            data = _graphql(query, {"u": uid, "p": pagina})
            items = (((data.get("data") or {}).get("products") or {}).get("items")) or []
            keys.update(i["url_key"] for i in items if i.get("url_key"))
            if len(items) < 100:
                break
            pagina += 1
        time.sleep(REQUEST_DELAY)
    return keys


def product_urls():
    """Sitemap en catalogus samen - geen van beide is in zijn eentje compleet."""
    uit_sitemap = sitemap_urls()
    keys = {_handle(u) for u in uit_sitemap}
    urls = list(uit_sitemap)
    extra = 0
    try:
        for key in sorted(catalogus_url_keys() - keys):
            urls.append(f"{BASE_URL}/{key}")
            extra += 1
    except Exception as e:
        # De sitemap alleen is bruikbaar; melden en doorgaan is beter dan stoppen.
        print(f"    !  Catalogus via GraphQL faalt ({e}) - alleen de sitemap gebruikt")
    print(f"Bronnen: {len(uit_sitemap)} uit de sitemap + {extra} extra uit de catalogus")
    return urls


def _clean(html):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html or ""))).strip()


def _ld_product(html):
    """Het JSON-LD Product-blok van de pagina (of None)."""
    for blok in LD_RE.findall(html):
        try:
            data = json.loads(blok)
        except Exception:
            continue
        for kandidaat in (data if isinstance(data, list) else [data]):
            if isinstance(kandidaat, dict) and kandidaat.get("@type") == "Product":
                return kandidaat
    return None


def _config_json(html):
    """Het object uit initConfigurableOptions('<id>', {...}) via haakjes-tellen."""
    start = html.find("initConfigurableOptions(")
    if start == -1:
        return {}
    begin = html.find("{", start)
    if begin == -1:
        return {}
    diepte, in_string, escape = 0, False, False
    for i in range(begin, len(html)):
        c = html[i]
        if in_string:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            continue
        if c == '"':
            in_string = True
        elif c == "{":
            diepte += 1
        elif c == "}":
            diepte -= 1
            if diepte == 0:
                try:
                    return json.loads(html[begin:i + 1])
                except Exception:
                    return {}
    return {}


def _optie_labels(config):
    """Magento-kind-id -> optielabel ('90 tabl'), uit het attributes-blok."""
    labels = {}
    for attr in (config.get("attributes") or {}).values():
        for optie in attr.get("options", []):
            for kind in optie.get("products", []):
                labels[str(kind)] = optie.get("label") or ""
    return labels


def _leverbaar(config):
    """Kind-ids die Mattisson daadwerkelijk kan leveren, uit de `salable`-kaart.

    Vorm: {"142": {"339": ["444"], "480": ["824"]}} = attribuut -> optie -> kinderen.
    Een kind dat hier ontbreekt, is uitverkocht. Geeft None als de kaart er niet
    is (simpel product) - dan telt het voorraadmerk op de pagina.
    """
    kaart = config.get("salable")
    if not kaart:
        return None
    ids = set()
    for opties in kaart.values():
        for kinderen in (opties or {}).values():
            ids.update(str(k) for k in kinderen or [])
    return ids


def _pagina_uit_voorraad(html):
    """Voorraadmerk van de pagina zelf, voor producten zonder varianten.

    De JSON-LD is hier onbruikbaar: die meldt InStock ook als de pagina
    "Niet op voorraad" toont (nagemeten op vitamine-c-gebufferd-1000mg-capsules,
    31-08-2026). Daarom het merk uit de HTML en de dataLayer.
    """
    return 'class="stock unavailable"' in html or '"dimension10":"Niet op voorraad"' in html


def _handle(url):
    return url.rstrip("/").rsplit("/", 1)[-1]


GRAPHQL_QUERY = """
query($keys:[String]!){
  products(filter:{url_key:{in:$keys}}, pageSize:100){
    items{
      __typename sku name url_key
      price_range{minimum_price{regular_price{value} final_price{value}}}
      ... on ConfigurableProduct{
        variants{
          attributes{label}
          product{sku name
            price_range{minimum_price{regular_price{value} final_price{value}}}}
        }
      }
    }
  }
}
"""


def _prijzen(price_range):
    minimum = (price_range or {}).get("minimum_price") or {}
    advies = (minimum.get("regular_price") or {}).get("value")
    actie = (minimum.get("final_price") or {}).get("value")
    try:
        advies = float(advies)
    except (TypeError, ValueError):
        advies = 0.0
    try:
        actie = float(actie)
    except (TypeError, ValueError):
        actie = advies
    return advies, actie


def graphql_producten(url_keys, batch=60):
    """url_key -> {label: {sku, naam, advies, actie}} via het publieke endpoint."""
    uit = {}
    for i in range(0, len(url_keys), batch):
        deel = url_keys[i:i + batch]
        resp = SESSIE.post(
            f"{BASE_URL}/graphql",
            json={"query": GRAPHQL_QUERY, "variables": {"keys": deel}},
            headers={"Content-Type": "application/json"},
            timeout=60, verify=VERIFY_SSL,
        )
        resp.raise_for_status()
        lichaam = resp.json()
        if lichaam.get("errors"):
            print(f"    !  GraphQL-fout: {str(lichaam['errors'])[:200]}")
        for item in ((lichaam.get("data") or {}).get("products") or {}).get("items") or []:
            varianten = {}
            for variant in item.get("variants") or []:
                kind = variant.get("product") or {}
                label = " / ".join(
                    (a.get("label") or "") for a in variant.get("attributes") or []
                ).strip()
                advies, actie = _prijzen(kind.get("price_range"))
                varianten[label] = {
                    "sku": kind.get("sku") or "",
                    "naam": kind.get("name") or "",
                    "advies": advies,
                    "actie": actie,
                }
            if not varianten:  # SimpleProduct: een variant zonder optielabel
                advies, actie = _prijzen(item.get("price_range"))
                varianten[""] = {
                    "sku": item.get("sku") or "",
                    "naam": item.get("name") or "",
                    "advies": advies,
                    "actie": actie,
                }
            uit[item.get("url_key")] = varianten
        time.sleep(REQUEST_DELAY)
    return uit


def _pagina_stroom(urls):
    """Haalt de pagina's op met WORKERS tegelijk; levert (url, html, fout).

    Een productpagina van mattisson.nl is ~800 kB, dus een run van 446 pagina's
    sleept 370 MB binnen; daar gaat de tijd heen. Wat wel scheelt is de
    hergebruikte verbinding (SESSIE) en het wegvallen van de vaste wachttijd
    per pagina - samen ruim drie minuten per run. Meer tegelijk ophalen scheelt
    niets (zie WORKERS).
    """
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        taken = {pool.submit(_get, url): url for url in urls}
        for taak in cf.as_completed(taken):
            url = taken[taak]
            try:
                yield url, taak.result().text, None
            except Exception as e:
                yield url, None, e


def parse_pagina(url, html):
    """Productpagina -> tekst/afbeeldingen + per optielabel de EAN en voorraad."""
    ld = _ld_product(html)
    if not ld:
        return None

    aanbiedingen = ld.get("offers") or []
    if isinstance(aanbiedingen, dict):
        aanbiedingen = [aanbiedingen]

    config = _config_json(html)
    data = config.get("data") or {}
    titels = config.get("titles") or {}
    labels = _optie_labels(config)
    leverbaar = _leverbaar(config)
    uit_voorraad = _pagina_uit_voorraad(html)
    tabel_ean = EAN_TABEL_RE.search(html)

    per_label = {}
    for aanbod in aanbiedingen:
        kind = str(aanbod.get("sku") or "")
        ean = str((data.get(kind) or {}).get("EAN-code") or "").strip()
        if not ean and len(aanbiedingen) == 1 and tabel_ean:
            # Een-variant-product: EAN staat in de specificatietabel.
            ean = tabel_ean.group(1)
        if not EAN_RE.match(ean):
            continue
        label = labels.get(kind, "")
        per_label[label] = {
            "barcode": ean,
            "magento_id": kind,
            "titel": titels.get(kind) or ld.get("name") or "",
            # Niet de JSON-LD gebruiken: die staat altijd op InStock.
            "beschikbaar": (kind in leverbaar) if leverbaar is not None
                           else not uit_voorraad,
        }

    if not per_label:
        return None

    afbeelding = ld.get("image")
    if isinstance(afbeelding, list):
        afbeeldingen = [str(a) for a in afbeelding]
    else:
        afbeeldingen = [str(afbeelding)] if afbeelding else []

    return {
        "handle": _handle(url),
        "url": url,
        "titel": ld.get("name") or "",
        "omschrijving": _clean(ld.get("description")),
        "afbeeldingen": afbeeldingen,
        "per_label": per_label,
    }


def _koppel(per_label, gql_varianten):
    """Koppel pagina-varianten (EAN) aan GraphQL-varianten (artikelnr + prijs).

    Eerst op optielabel; lukt dat niet en is er aan beide kanten precies een
    variant, dan op volgorde. Wat niet koppelt, valt weg (met melding) - liever
    een variant minder dan een prijs op het verkeerde artikel.
    """
    gekoppeld, los = [], []
    labels_over = list(gql_varianten.keys())
    for label, pagina in per_label.items():
        gql = gql_varianten.get(label)
        if gql is None and len(per_label) == 1 and len(gql_varianten) == 1:
            gql = gql_varianten[labels_over[0]]
        if gql is None:
            los.append(label or "(zonder label)")
            continue
        gekoppeld.append({
            "barcode": pagina["barcode"],
            "sku": gql["sku"],
            "titel": gql["naam"] or pagina["titel"],
            "optie": label,
            "prijs": gql["advies"],
            "actieprijs": gql["actie"],
            "beschikbaar": pagina["beschikbaar"],
        })
    return gekoppeld, los


def fetch_products():
    """Alle producten met varianten. Print onderweg wat er wordt overgeslagen."""
    test_url = os.environ.get("TEST_URL")
    urls = [test_url] if test_url else product_urls()
    if not test_url:
        print(f"Te bezoeken: {len(urls)} productpagina's")
        if len(urls) < MIN_PRODUCTPAGINAS:
            raise SystemExit(
                f"STOP: slechts {len(urls)} productpagina's gevonden (ondergrens "
                f"{MIN_PRODUCTPAGINAS}). Geen feed weggeschreven - een halve feed "
                f"laat Stock Sync producten archiveren."
            )
    limiet = int(os.environ.get("MAX_PRODUCTEN") or 0)
    if limiet:
        urls = urls[:limiet]

    print("GraphQL: artikelnummers en prijzen ophalen...")
    gql = graphql_producten([_handle(u) for u in urls])
    print(f"GraphQL: {len(gql)} van de {len(urls)} url-sleutels gevonden")

    producten, overgeslagen, losse = [], [], []
    for i, (url, html, fout) in enumerate(_pagina_stroom(urls), 1):
        handle = _handle(url)
        if fout is not None:
            overgeslagen.append((handle, f"pagina onbereikbaar: {fout}"))
            continue
        pagina = parse_pagina(url, html)
        if pagina is None:
            overgeslagen.append((handle, "geen EAN of geen JSON-LD"))
        elif handle not in gql:
            overgeslagen.append((handle, "niet in GraphQL (geen prijs)"))
        else:
            varianten, los = _koppel(pagina["per_label"], gql[handle])
            if los:
                losse.append((handle, los))
            if not varianten:
                overgeslagen.append((handle, "geen variant gekoppeld aan een prijs"))
            else:
                pagina["varianten"] = varianten
                producten.append(pagina)
        if i % 50 == 0:
            print(f"    ...{i}/{len(urls)} pagina's, {len(producten)} producten")

    if overgeslagen:
        print(f"\nOvergeslagen: {len(overgeslagen)} pagina's")
        for handle, reden in overgeslagen[:20]:
            print(f"    - {handle}: {reden}")
        if len(overgeslagen) > 20:
            print(f"    ... en nog {len(overgeslagen) - 20}")
    if losse:
        print(f"\nNiet gekoppelde varianten bij {len(losse)} producten:")
        for handle, labels in losse[:10]:
            print(f"    - {handle}: {', '.join(labels)}")

    varianten = sum(len(p["varianten"]) for p in producten)
    print(f"\nKlaar: {len(producten)} producten, {varianten} varianten met EAN")
    return producten


def ontdubbel(producten):
    """Elke EAN maar een keer in de feed.

    Mattisson voert enkele artikelen onder twee url's (bv. bitterzout-epsom-zout
    en bitterzout-epsom-zout-1-kg): zelfde artikelnummer, zelfde EAN. Twee regels
    met dezelfde barcode laten Stock Sync twee keer hetzelfde product schrijven -
    en in de add-feed zou het twee producten aanmaken. De eerste wint; de rest
    wordt gemeld, niet stil weggelaten.
    """
    gezien, dubbel = {}, []
    schoon = []
    for p in producten:
        varianten = []
        for v in p["varianten"]:
            eerste = gezien.get(v["barcode"])
            if eerste is not None:
                dubbel.append((v["barcode"], eerste, p["handle"]))
                continue
            gezien[v["barcode"]] = p["handle"]
            varianten.append(v)
        if varianten:
            schoon.append({**p, "varianten": varianten})
    if dubbel:
        print(f"\nOntdubbeld: {len(dubbel)} regel(s) met een EAN die al voorkwam")
        for code, eerste, tweede in dubbel:
            print(f"    - {code}: {tweede} valt weg, {eerste} blijft")
    return schoon
