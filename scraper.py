"""
Mattisson UPDATE-feed
=====================
Lichte feed om BESTAANDE producten bij te werken: prijs + beschikbaarheid.
Matcht in Stock Sync op **barcode (EAN)** - de Mattisson-varianten in de winkel
hebben geen SKU.

  price       = adviesprijs van Mattisson (incl. BTW)
  actieprijs  = wat mattisson.nl vandaag vraagt (kan een tijdelijke korting zijn)
  quantity    = 0, altijd. Wij houden geen Mattisson-voorraad aan; de aantallen
                die tot 31-08-2026 in de winkel stonden (224.918 stuks!) waren de
                magazijnstanden van Mattisson zelf, uit hun oude feed.
  available   = kan Mattisson leveren, ja/nee. Dit hoort in Stock Sync op het
                VOORRAADBELEID gemapt te worden (ja = doorgaan met verkopen,
                nee = stoppen), niet op een aantal - anders staat er weer een
                getal in de winkel dat niets betekent.
  sku         = artikelnummer van Mattisson (MT2336) - om lege SKU's te vullen

Bewust GEEN description: dat beschermt de eigen teksten in de winkel.

Bron: mattisson.nl (publiek). Zie mattisson_common.py.
Lokaal: INSECURE_SSL=1, MAX_PRODUCTEN=10.
"""

import time
import xml.etree.ElementTree as ET
from xml.dom import minidom

import mattisson_common as mc

OUTPUT_FILE = "mattisson_feed.xml"

# Anti-archiveerslot: onder dit aantal varianten schrijven we geen feed weg.
# Stock Sync archiveert wat niet in de feed staat. Peiling 31-08-2026: 505 varianten.
MIN_VARIANTEN = 400


def build_xml(producten):
    root = ET.Element("products")
    for p in producten:
        for v in p["varianten"]:
            item = ET.SubElement(root, "product")

            def add(tag, value):
                el = ET.SubElement(item, tag)
                el.text = "" if value is None else str(value)

            add("sku", v["sku"])
            add("barcode", v["barcode"])
            add("title", v["titel"])
            add("vendor", mc.BRAND)
            add("price", f"{v['prijs']:.2f}")
            add("actieprijs", f"{v['actieprijs']:.2f}")
            add("quantity", "0")   # wij houden geen eigen Mattisson-voorraad aan
            add("available", "true" if v["beschikbaar"] else "false")
            add("handle", p["handle"])
            add("option1", v["optie"])
    return root


def save_xml(root, filepath):
    xml_str = ET.tostring(root, encoding="unicode")
    pretty = minidom.parseString(xml_str).toprettyxml(indent="  ")
    lines = pretty.split("\n")
    if lines[0].startswith("<?xml"):
        lines[0] = '<?xml version="1.0" encoding="UTF-8"?>'
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\nXML opgeslagen: {filepath}")


def main():
    print("Mattisson UPDATE-feed gestart\n")
    start = time.time()
    producten = mc.ontdubbel(mc.fetch_products())
    varianten = sum(len(p["varianten"]) for p in producten)
    if varianten < MIN_VARIANTEN:
        raise SystemExit(
            f"STOP: slechts {varianten} varianten (ondergrens {MIN_VARIANTEN}). "
            f"Geen feed weggeschreven - een halve feed laat Stock Sync producten "
            f"archiveren."
        )
    save_xml(build_xml(producten), OUTPUT_FILE)
    zonder_voorraad = sum(
        1 for p in producten for v in p["varianten"] if not v["beschikbaar"]
    )
    print(
        f"Klaar in {time.time() - start:.0f}s - {len(producten)} producten, "
        f"{varianten} varianten, waarvan {zonder_voorraad} uit voorraad"
    )
    print("\nFeed-URL voor Stock Sync (Update):")
    print("https://raw.githubusercontent.com/Maximillian-creator/mattisson-feed/main/mattisson_feed.xml")


if __name__ == "__main__":
    main()
