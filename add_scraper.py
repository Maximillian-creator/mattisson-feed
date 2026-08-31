"""
Mattisson ADD-feed
==================
Zware feed om NIEUWE producten aan te maken: alle productinfo die Mattisson
publiek toont. Plat per variant, gegroepeerd via `handle` - zo verwacht Stock
Sync het (Variantgroep = handle, Variant Optie 1 = option1).

`published` staat hard op **false**: concept-only. De teksten komen letterlijk
van mattisson.nl en zijn nog niet langs Themis geweest; publiceren verdien je.
Draai daarom na deze feed `python themis_check.py` en werk het rapport af.

Bron: mattisson.nl (publiek). Zie mattisson_common.py.
Lokaal: INSECURE_SSL=1, MAX_PRODUCTEN=10.
"""

import csv
import time
import xml.etree.ElementTree as ET
from xml.dom import minidom

import mattisson_common as mc

OUTPUT_FILE = "mattisson_add_feed.xml"
BRON_FILE = "mattisson_tekstbron.csv"

MIN_VARIANTEN = 400


def add(parent, tag, value):
    el = ET.SubElement(parent, tag)
    el.text = "" if value is None else str(value)
    return el


def build_xml(producten):
    root = ET.Element("products")
    for p in producten:
        afbeeldingen = p["afbeeldingen"]
        for v in p["varianten"]:
            item = ET.SubElement(root, "product")
            add(item, "handle", p["handle"])
            add(item, "title", p["titel"])
            add(item, "vendor", mc.BRAND)
            add(item, "brand", mc.BRAND)
            add(item, "published", "false")   # concept-only: publiceren verdien je
            add(item, "description", p["omschrijving"])
            add(item, "body_html", p["omschrijving"])
            add(item, "bron_url", p["url"])
            add(item, "option1_name", "Inhoud")
            add(item, "option1", v["optie"] or "Standaard")
            add(item, "sku", v["sku"])
            add(item, "barcode", v["barcode"])
            add(item, "price", f"{v['prijs']:.2f}")
            add(item, "actieprijs", f"{v['actieprijs']:.2f}")
            add(item, "quantity", "0")   # geen eigen voorraad; zie scraper.py
            add(item, "available", "true" if v["beschikbaar"] else "false")
            add(item, "variant_title", v["titel"])
            add(item, "image", afbeeldingen[0] if afbeeldingen else "")
            add(item, "image_links", ",".join(afbeeldingen))
            beelden = ET.SubElement(item, "images")
            for src in afbeeldingen:
                add(ET.SubElement(beelden, "image"), "src", src)
    return root


def schrijf_tekstbron(producten, pad=BRON_FILE):
    """Per variant: waar de tekst vandaan komt en hoeveel het er is.

    Zonder dit bestand is "412 producten met beschrijving" een getal dat je moet
    geloven; hiermee kun je het regel voor regel nakijken.
    """
    with open(pad, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["barcode", "sku", "titel", "optie", "woorden", "afbeeldingen",
                    "adviesprijs", "actieprijs", "op_voorraad", "bron_url"])
        for p in producten:
            woorden = len(p["omschrijving"].split())
            for v in p["varianten"]:
                w.writerow([v["barcode"], v["sku"], v["titel"], v["optie"], woorden,
                            len(p["afbeeldingen"]), f"{v['prijs']:.2f}",
                            f"{v['actieprijs']:.2f}",
                            "ja" if v["beschikbaar"] else "nee", p["url"]])
    print(f"Tekstbron geschreven: {pad}")


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
    print("Mattisson ADD-feed gestart\n")
    start = time.time()
    producten = mc.ontdubbel(mc.fetch_products())
    varianten = sum(len(p["varianten"]) for p in producten)
    if varianten < MIN_VARIANTEN:
        raise SystemExit(
            f"STOP: slechts {varianten} varianten (ondergrens {MIN_VARIANTEN}). "
            f"Geen feed weggeschreven."
        )
    save_xml(build_xml(producten), OUTPUT_FILE)
    schrijf_tekstbron(producten)
    zonder_tekst = sum(1 for p in producten if len(p["omschrijving"].split()) < 30)
    print(f"Klaar in {time.time() - start:.0f}s - {len(producten)} producten, "
          f"{varianten} varianten, {zonder_tekst} met een dunne beschrijving")
    print("\nFeed-URL voor Stock Sync (Add):")
    print("https://raw.githubusercontent.com/Maximillian-creator/mattisson-feed/main/mattisson_add_feed.xml")
    print("\nLet op: draai nu 'python themis_check.py' voordat je iets publiceert.")


if __name__ == "__main__":
    main()
