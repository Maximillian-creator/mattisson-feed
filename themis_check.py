"""
Themis-controle over de ADD-feed
================================
De teksten in de add-feed zijn LETTERLIJK die van mattisson.nl. Wat daar
mag staan, mag bij Good For You niet automatisch ook: wij zijn zelf
verantwoordelijk voor elke claim op onze eigen pagina's (EFSA/NVWA/KOAG-KAG).

Dit script haalt elke beschrijving door `gfy-themis` en schrijft een rapport:

    python themis_check.py

Het draait alleen lokaal, in de map "Claude Code Projecten" waar gfy-themis
naast deze repo staat. In GitHub Actions is Themis er niet; dan stopt het
script netjes met een uitleg in plaats van een foutmelding. Daarom staat
`published` in de add-feed ook hard op false: bouwen mag, publiceren verdien je.
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HIER = Path(__file__).parent
ADD = HIER / "mattisson_add_feed.xml"
RAPPORT = HIER / "mattisson_themis.md"

# gfy-themis staat twee mappen omhoog: leveranciers-feeds/<deze repo>/..
THEMIS_PAD = HIER.parent.parent / "gfy-themis"


def laad_themis():
    if not THEMIS_PAD.exists():
        print("gfy-themis niet gevonden naast deze repo "
              f"({THEMIS_PAD}) - controle overgeslagen.")
        print("Draai dit script lokaal in 'Claude Code Projecten'.")
        return None
    sys.path.insert(0, str(THEMIS_PAD))
    import themis
    return themis


def plat(html):
    import re
    from html import unescape
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html or ""))).strip()


def main():
    themis = laad_themis()
    if themis is None:
        return 0
    if not ADD.exists():
        print("mattisson_add_feed.xml ontbreekt - draai eerst add_scraper.py")
        return 1

    root = ET.parse(ADD).getroot()
    regels, tellen = [], {"ok": 0, "let-op": 0, "afkeuren": 0}
    gezien = set()   # de feed is plat per variant: elke tekst een keer toetsen
    for p in root.findall("product"):
        titel = (p.findtext("title") or "").strip()
        sku = (p.findtext("barcode") or "").strip()
        handle = (p.findtext("handle") or "").strip()
        tekst = plat(p.findtext("description") or "")
        if not tekst or handle in gezien:
            continue
        gezien.add(handle)
        rapport = themis.toets(tekst)
        tellen[rapport.oordeel] = tellen.get(rapport.oordeel, 0) + 1
        if rapport.oordeel == "ok":
            continue
        regels.append(f"### {titel} (`{sku}`)\n")
        regels.append(f"**Oordeel: {rapport.oordeel}**\n")
        for pr in rapport.problemen:
            regels.append(f"- `{pr['term']}` — {pr['categorie']} "
                          f"({pr['bron']}): {pr['toelichting']}")
        for s in rapport.suggesties:
            regels.append(f"- in plaats van \"{s['niet']}\": {s['wel']}")
        for a in rapport.art14_signalen:
            regels.append(f"- artikel-14-doelgroep: {a}")
        regels.append("")

    kop = [
        "# Themis over de Mattisson add-feed",
        "",
        "De teksten hieronder komen letterlijk van mattisson.nl. Alles wat",
        "hier staat moet aangepast zijn *voordat* een product in Shopify op",
        "'published' gaat.",
        "",
        f"- ok: **{tellen.get('ok', 0)}**",
        f"- let op: **{tellen.get('let-op', 0)}**",
        f"- afkeuren: **{tellen.get('afkeuren', 0)}**",
        "",
    ]
    RAPPORT.write_text("\n".join(kop + regels), encoding="utf-8")
    print(f"Rapport geschreven: {RAPPORT.name}")
    print(f"  ok {tellen.get('ok', 0)} | let op {tellen.get('let-op', 0)} "
          f"| afkeuren {tellen.get('afkeuren', 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
