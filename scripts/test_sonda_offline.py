#!/usr/bin/env python3
"""Test della sonda archivi su un sito finto che imita il comportamento RGS.

Il sito simulato risponde HTTP 200 a tutto: agli URL veri con il contenuto vero,
a quelli inesistenti con una pagina di cortesia. E' esattamente il caso che ha
ingannato la prima versione della sonda.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe_archivi as pa  # noqa: E402
import scrape_rgs as s  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DOC = pa.DOC
CORTESIA = "<html><body>Pagina non disponibile. <a href='/VERSIONE-I/'>Home</a></body></html>"

# Anni realmente pubblicati nel sito finto.
VERI = {2020, 2021, 2022}


def pagina_archivio(anno: int) -> str:
    base = f"{pa.BASE}{DOC}/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/conto_del_bilancio/{anno}"
    voci = "".join(
        f"<a href='{base}/conti_consuntivi_per_unit_di_voto/CON_{anno}_{amm:03d}-6-Finanziario.pdf'>x</a>"
        for amm in (20, 30, 40))
    return f"<html><body>Conto del bilancio {anno}{voci}</body></html>"


class FakeResp:
    def __init__(self, text="", ctype="text/html;charset=UTF-8", body=b""):
        self.status_code = 200
        self.text = text
        self.headers = {"Content-Type": ctype, "Content-Length": str(len(body) or len(text))}
        self._body = body

    def iter_content(self, chunk_size=512):
        yield self._body[:chunk_size]

    def close(self):
        pass


class FakeSession:
    headers = {}

    def get(self, url, timeout=None, stream=False, allow_redirects=True):
        if url.endswith(".pdf"):
            anno = next((a for a in VERI if f"/{a}/" in url and f"CON_{a}_" in url), None)
            if anno:
                return FakeResp(ctype="application/pdf", body=b"%PDF-1.7 contenuto")
            return FakeResp(text=CORTESIA, body=CORTESIA.encode())  # soft-404 travestito da HTML
        for a in VERI:
            if f"/conto_del_bilancio/{a}/index.html" in url:
                return FakeResp(text=pagina_archivio(a))
        return FakeResp(text=CORTESIA)


fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"{label}: atteso {want!r}, ottenuto {got!r}")


cfg = s.Config.load(ROOT / "config" / "seeds.yaml")
ses = FakeSession()

# --- documenti --------------------------------------------------------------
url_vero = f"{pa.BASE}{DOC}/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/conto_del_bilancio/2022/conti_consuntivi_per_unit_di_voto/CON_2022_020-6-Finanziario.pdf"
url_falso = url_vero.replace("2022", "2026")
check("documento vero", pa.testa_documento(ses, url_vero, 5)[0], "ESISTE")
check("documento inesistente riconosciuto",
      pa.testa_documento(ses, url_falso, 5)[0], "SOFT-404")

# --- pagine: controllo cieco ------------------------------------------------
schema = pa.AI + "/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/conto_del_bilancio/{Y}/index.html"
url_ctrl = pa.BASE + schema.format(Y=1899, Y2=1901)
_, html_ctrl = pa.scarica_pagina(ses, url_ctrl, 5)
ctrl = pa.link_documenti(cfg, url_ctrl, html_ctrl)
check("controllo cieco senza documenti", len(ctrl), 0)

for anno in (2020, 2021, 2022):
    url = pa.BASE + schema.format(Y=anno, Y2=anno + 2)
    _, html = pa.scarica_pagina(ses, url, 5)
    docs = pa.link_documenti(cfg, url, html)
    del_anno = {d for d in docs if str(anno) in d}
    check(f"archivio {anno} trovato", len(del_anno), 3)

for anno in (2019, 2025, 2026):
    url = pa.BASE + schema.format(Y=anno, Y2=anno + 2)
    _, html = pa.scarica_pagina(ses, url, 5)
    docs = pa.link_documenti(cfg, url, html)
    # stessa pagina di cortesia del controllo cieco: va riconosciuta
    check(f"anno {anno} riconosciuto come cortesia", docs == ctrl, True)

if fails:
    print("FALLITI:")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("OK: la sonda distingue archivi veri, soft-404 su pagina e soft-404 su documento")
