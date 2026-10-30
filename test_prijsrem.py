"""Tests voor de gedeelde prijsrem — `python test_prijsrem.py` of pytest. Geen netwerk."""
from __future__ import annotations

import os
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import prijsrem  # noqa: E402


def _xml(prijzen: dict) -> str:
    return '<?xml version="1.0"?><products>' + "".join(
        f"<product><sku>{s}</sku><price>{p:.2f}</price><available>true</available></product>"
        for s, p in prijzen.items()) + "</products>"


def _root(prijzen: dict) -> ET.Element:
    return ET.fromstring(_xml(prijzen))


def _prijzen(root: ET.Element) -> dict:
    return {el.findtext("sku"): float(el.findtext("price")) for el in root.iter("product")}


def _met_vorige(vorige: dict):
    d = tempfile.mkdtemp()
    pad = os.path.join(d, "feed.xml")
    with open(pad, "w", encoding="utf-8") as f:
        f.write(_xml(vorige))
    return pad


def test_btw_loze_feed_wordt_teruggerekend():
    vorige = {f"s{i}": 20.00 for i in range(10)}
    pad = _met_vorige(vorige)
    root = _root({f"s{i}": round(20.00 / 1.09, 2) for i in range(10)})      # 18.35: de bron toont excl. btw
    r = prijsrem.pas_toe(root, pad)
    assert r["btw_eraf"] == 10 and not r["vastgehouden"], r
    assert all(abs(p - 20.00) <= 0.01 for p in _prijzen(root).values()), _prijzen(root)
    assert "BTW-CORRECTIE: 10" in prijsrem.verslag(r)


def test_cosmetica_21_procent_ook():
    pad = _met_vorige({"c1": 39.95, "c2": 29.95, "s1": 20.00})
    root = _root({"c1": round(39.95 / 1.21, 2), "c2": round(29.95 / 1.21, 2), "s1": round(20.00 / 1.09, 2)})
    r = prijsrem.pas_toe(root, pad)
    assert r["btw_eraf"] == 3 and not r["vastgehouden"], r
    p = _prijzen(root)
    assert abs(p["c1"] - 39.95) <= 0.01 and abs(p["c2"] - 29.95) <= 0.01 and abs(p["s1"] - 20.00) <= 0.01


def test_bron_toont_weer_incl_na_een_btw_loze_feed():
    pad = _met_vorige({f"s{i}": 18.35 for i in range(10)})                  # de vorige feed was fout (excl.)
    root = _root({f"s{i}": 20.00 for i in range(10)})
    r = prijsrem.pas_toe(root, pad)
    assert r["btw_terug"] == 10 and not r["vastgehouden"] and not r["btw_eraf"], r
    assert all(p == 20.00 for p in _prijzen(root).values())


def test_kleine_wijziging_door_rare_prijs_vast_losse_btw_regel_vast():
    pad = _met_vorige({f"s{i}": 20.00 for i in range(10)})
    nieuw = {f"s{i}": 20.00 for i in range(10)}
    nieuw["s0"] = 20.40          # +2%: gewoon
    nieuw["s1"] = 12.00          # -40%: vasthouden
    nieuw["s2"] = 18.35          # ÷1,09 maar als enige: geen systeem, vasthouden
    nieuw["s9"] = 21.80          # ×1,09 als enige: mag altijd (de bron toont weer incl.)
    nieuw["nieuw1"] = 5.00       # nieuwe SKU: door
    root = _root(nieuw)
    r = prijsrem.pas_toe(root, pad)
    assert r["vergeleken"] == 10 and r["nieuw_zonder_vorige"] == 1 and r["ok"] == 7 and r["btw_terug"] == 1, r
    assert sorted(s for s, _, _ in r["vastgehouden"]) == ["s1", "s2"], r["vastgehouden"]
    p = _prijzen(root)
    assert p["s0"] == 20.40 and p["s1"] == 20.00 and p["s2"] == 20.00 and p["s9"] == 21.80 and p["nieuw1"] == 5.00
    assert "VASTGEHOUDEN: 2" in prijsrem.verslag(r)


def test_zonder_vorige_feed_of_met_force_gaat_alles_door():
    root = _root({"s1": 1.00})
    r = prijsrem.pas_toe(root, os.path.join(tempfile.mkdtemp(), "bestaat-niet.xml"))
    assert r["nieuw_zonder_vorige"] == 1 and r["vergeleken"] == 0 and _prijzen(root)["s1"] == 1.00
    pad = _met_vorige({"s1": 20.00})
    os.environ["FORCE_PRIJZEN"] = "1"
    try:
        root = _root({"s1": 12.00})
        r = prijsrem.pas_toe(root, pad)
    finally:
        os.environ.pop("FORCE_PRIJZEN")
    assert r["uit"] and _prijzen(root)["s1"] == 12.00 and "uit" in prijsrem.verslag(r)


def test_andere_tags_blijven_onaangeraakt():
    pad = _met_vorige({"s1": 20.00})
    root = _root({"s1": 12.00})
    root.find("product").find("available").text = "false"
    prijsrem.pas_toe(root, pad)
    assert root.find("product").findtext("available") == "false" and _prijzen(root)["s1"] == 20.00


if __name__ == "__main__":
    fouten = 0
    for naam, f in sorted(globals().items()):
        if naam.startswith("test_") and callable(f):
            try:
                f()
                print(f"  ok    {naam}")
            except AssertionError as e:
                fouten += 1
                print(f"  FOUT  {naam} {e}")
    sys.exit(1 if fouten else 0)
