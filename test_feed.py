"""
Tests bij de Mattisson-feed
===========================
Twee soorten:

1. **Voorraadlogica** op nagebouwde HTML - draait overal, ook in GitHub Actions.
   Dit is de test die het getal "x varianten uit voorraad" betekenis geeft: de
   JSON-LD van mattisson.nl meldt namelijk ALTIJD `InStock`, ook bij een
   uitverkocht product. Wie die zou geloven, drukt een voorraadgetal af dat niets
   zegt.
2. **Livecontrole** op drie echte pagina's - alleen met `LIVE=1`, want daarvoor
   is internet nodig en kan de voorraad bij Mattisson wisselen.

    python test_feed.py
    LIVE=1 INSECURE_SSL=1 python test_feed.py
"""

import os
import sys

import mattisson_common as mc

CONFIG_MET_VOORRAAD = (
    '<script>initConfigurableOptions("968", '
    '{"attributes":{"142":{"id":"142","code":"inhoud","label":"inhoud","options":'
    '[{"id":"339","label":"90 tabl","products":["444"]},'
    '{"id":"480","label":"180 tabl","products":["824"]}]}},'
    '"salable":{"142":{"339":["444"]}},'
    '"titles":{"444":"90 tabletten","824":"180 tabletten"},'
    '"data":{"444":{"EAN-code":"8717677965267"},"824":{"EAN-code":"8720959400677"}}'
    '});</script>'
)
LD_TWEE_VARIANTEN = (
    '<script type="application/ld+json">{"@context":"http://schema.org/",'
    '"@type":"Product","name":"Magnesium Bisglycinaat","description":"tekst",'
    '"image":"https://x/y.png","offers":['
    '{"@type":"Offer","sku":"444","price":"14.96","availability":"http://schema.org/InStock"},'
    '{"@type":"Offer","sku":"824","price":"26.21","availability":"http://schema.org/InStock"}]}'
    '</script>'
)
LD_EEN_VARIANT = (
    '<script type="application/ld+json">{"@context":"http://schema.org/",'
    '"@type":"Product","name":"Vitamine C Gebufferd","description":"tekst",'
    '"image":"https://x/y.png","offers":'
    '{"@type":"Offer","sku":"433","price":"14.96","availability":"http://schema.org/InStock"}}'
    '</script>'
)
TABEL_EAN = '<td class="col data" data-th="EAN-code">8717677962204</td>'


def test_salable_bepaalt_voorraad():
    """Kind 824 staat niet in `salable` -> uitverkocht, ondanks InStock in de LD."""
    html = LD_TWEE_VARIANTEN + CONFIG_MET_VOORRAAD
    p = mc.parse_pagina("https://www.mattisson.nl/test-product", html)
    assert p is not None, "product niet geparsed"
    assert p["per_label"]["90 tabl"]["beschikbaar"] is True
    assert p["per_label"]["180 tabl"]["beschikbaar"] is False
    assert p["per_label"]["90 tabl"]["barcode"] == "8717677965267"


def test_pagina_zonder_varianten_uit_voorraad():
    """Simpel product: het voorraadmerk op de pagina beslist, niet de LD."""
    uit = LD_EEN_VARIANT + TABEL_EAN + '<div class="stock unavailable">Niet op voorraad</div>'
    op = LD_EEN_VARIANT + TABEL_EAN + '<div class="stock available">Op voorraad</div>'
    assert mc.parse_pagina("https://x/y", uit)["per_label"][""]["beschikbaar"] is False
    assert mc.parse_pagina("https://x/y", op)["per_label"][""]["beschikbaar"] is True


def test_datalayer_merk_telt_ook():
    html = LD_EEN_VARIANT + TABEL_EAN + '"dimension10":"Niet op voorraad",'
    assert mc.parse_pagina("https://x/y", html)["per_label"][""]["beschikbaar"] is False


def test_zonder_ean_geen_regel():
    """Zonder EAN kan Stock Sync niets matchen -> die variant hoort niet in de feed."""
    assert mc.parse_pagina("https://x/y", LD_EEN_VARIANT) is None


def test_koppelen_valt_stil_bij_onbekend_label():
    """Een pagina-variant zonder prijs-tegenhanger valt weg mét melding."""
    per_label = {"90 tabl": {"barcode": "871", "magento_id": "444", "titel": "t",
                             "beschikbaar": True},
                 "180 tabl": {"barcode": "872", "magento_id": "824", "titel": "t",
                              "beschikbaar": True}}
    gql = {"90 tabl": {"sku": "MT1", "naam": "n", "advies": 19.95, "actie": 14.96}}
    gekoppeld, los = mc._koppel(per_label, gql)
    assert [v["barcode"] for v in gekoppeld] == ["871"]
    assert los == ["180 tabl"]
    assert gekoppeld[0]["prijs"] == 19.95 and gekoppeld[0]["actieprijs"] == 14.96


def test_ontdubbelen_houdt_een_regel_per_ean():
    """Twee url's met dezelfde EAN (bitterzout) leveren een feedregel op."""
    producten = [
        {"handle": "bitterzout-epsom-zout-1-kg", "varianten": [
            {"barcode": "8717677966134", "sku": "MT2222"}]},
        {"handle": "bitterzout-epsom-zout", "varianten": [
            {"barcode": "8717677966134", "sku": "MT2222"}]},
        {"handle": "iets-anders", "varianten": [{"barcode": "8717677960675", "sku": "MT1420"}]},
    ]
    schoon = mc.ontdubbel(producten)
    codes = [v["barcode"] for p in schoon for v in p["varianten"]]
    assert codes == ["8717677966134", "8717677960675"], codes
    assert [p["handle"] for p in schoon] == ["bitterzout-epsom-zout-1-kg", "iets-anders"]


def test_live():
    """Drie echte pagina's: EAN gevonden, prijs > 0, actieprijs nooit hoger."""
    for url in [
        "https://www.mattisson.nl/magnesium-bisglycinaat-tabletten-100-mg-elementair",
        "https://www.mattisson.nl/biologische-erythritol",
        "https://www.mattisson.nl/vitamine-c-gebufferd-1000mg-capsules",
    ]:
        os.environ["TEST_URL"] = url
        producten = mc.fetch_products()
        assert producten, f"niets geparsed voor {url}"
        for p in producten:
            for v in p["varianten"]:
                assert mc.EAN_RE.match(v["barcode"]), f"geen EAN: {v}"
                assert v["prijs"] > 0, f"geen prijs: {v}"
                assert v["actieprijs"] <= v["prijs"] + 0.005, f"actie boven advies: {v}"
                assert v["sku"], f"geen artikelnummer: {v}"
        print(f"  ok: {url.rsplit('/', 1)[-1]}")
    os.environ.pop("TEST_URL", None)


def main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and (k != "test_live" or os.environ.get("LIVE"))]
    mislukt = 0
    for t in tests:
        try:
            t()
            print(f"ok   {t.__name__}")
        except AssertionError as e:
            mislukt += 1
            print(f"FOUT {t.__name__}: {e}")
    print(f"\n{len(tests) - mislukt}/{len(tests)} geslaagd")
    if not os.environ.get("LIVE"):
        print("(livecontrole overgeslagen - draai met LIVE=1 INSECURE_SSL=1)")
    return 1 if mislukt else 0


if __name__ == "__main__":
    sys.exit(main())
