#!/usr/bin/env python3
"""Sonda quali archivi per anno esistono davvero sul sito RGS.

ATTENZIONE, lezione della prima versione: il sito risponde **HTTP 200 anche agli
URL inesistenti** (soft-404: serve una pagina di cortesia invece di un 404). La
prima sonda controllava solo lo stato e concluse che esisteva tutto, compreso
CON_2026_020-6-Finanziario.pdf, cioe' il rendiconto di un esercizio non ancora
chiuso. Verificare lo stato HTTP su questo sito non prova nulla.

Questa versione verifica il CONTENUTO, con due controlli indipendenti:

1. Controllo cieco. Ogni schema viene provato anche con un anno impossibile
   (1899). Se la pagina dell'anno vero ha lo stesso contenuto di quella
   dell'anno impossibile, e' la stessa pagina di cortesia: soft-404.
2. Prova di utilita'. Una pagina di archivio del 2022 e' utile solo se linka
   documenti il cui path contiene 2022. Se ne linka zero, non serve comunque.

Per i documenti si controllano i byte iniziali: un PDF inizia con %PDF, uno
xlsx/zip con PK. Se arriva HTML, e' la pagina di cortesia travestita.

    python3 scripts/probe_archivi.py
    python3 scripts/probe_archivi.py --anni 2020 2021 2022 --csv sonda.csv
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scrape_rgs as s  # noqa: E402

BASE = "https://www.rgs.mef.gov.it"
AI = "/VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio"
DOC = "/_Documenti/VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio"

ANNO_IMPOSSIBILE = 1899

# (sezione, tipo, schema). tipo: "pagina" oppure "documento".
SCHEMI = [
    ("conto_del_bilancio", "pagina", AI + "/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/conto_del_bilancio/{Y}/index.html"),
    ("conto_del_bilancio", "pagina", AI + "/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/conto_del_bilancio/CDB_{Y}/index.html"),
    ("conto_del_bilancio", "documento", DOC + "/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/conto_del_bilancio/{Y}/conti_consuntivi_per_unit_di_voto/CON_{Y}_020-6-Finanziario.pdf"),
    ("conto_del_bilancio", "documento", DOC + "/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/conto_del_bilancio/{Y}/conti_consuntivi_piani_gestionali/CON_{Y}_020-6-Finanziario.pdf"),

    ("conto_patrimonio", "pagina", AI + "/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/conto_generale_del_patrimonio/{Y}/index.html"),
    ("conto_patrimonio", "documento", DOC + "/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/conto_generale_del_patrimonio/{Y}/Conto-patrimonio-{Y}.pdf"),

    ("rendiconto_economico", "pagina", AI + "/rendiconto/rendiconto_economico/{Y}/index.html"),
    ("rendiconto_in_breve", "pagina", AI + "/rendiconto/rendiconto_in_breve/{Y}/index.html"),
    ("note_integrative_consuntivo", "pagina", AI + "/rendiconto/note_integrative_a_consuntivo/{Y}/index.html"),

    ("bilancio_finanziario", "pagina", AI + "/bilancio_di_previsione/bilancio_finanziario/BF_{Y}_{Y2}/index.html"),
    ("bilancio_finanziario", "pagina", AI + "/bilancio_di_previsione/bilancio_finanziario/{Y}-{Y2}/index.html"),
    ("note_integrative_previsione", "pagina", AI + "/bilancio_di_previsione/note_integrative/note_integrative_al_bilancio_di_previsione/{Y}-{Y2}/index.html"),
    ("bilancio_in_breve", "pagina", AI + "/bilancio_di_previsione/bilancio_in_breve/{Y}-{Y2}/index.html"),

    ("assestamento", "pagina", AI + "/gestione_del_bilancio/assestamento_del_bilancio/{Y}/index.html"),
    ("decreti_di_variazione", "pagina", AI + "/gestione_del_bilancio/decreti_di_variazione/{Y}/index.html"),
]

MAGIC = {"pdf": b"%PDF", "xlsx": b"PK", "xls": b"\xd0\xcf", "zip": b"PK", "docx": b"PK"}


def link_documenti(cfg: s.Config, url: str, html: str) -> set[str]:
    out = set()
    for raw in s.HREF_RE.findall(html):
        raw = raw.strip()
        if not raw or raw.lower().startswith(("mailto:", "javascript:", "tel:")):
            continue
        link = urljoin(url, raw).split("#")[0]
        if cfg.is_document(link) and cfg.in_scope(link):
            out.add(link)
    return out


def scarica_pagina(session, url, timeout) -> tuple[int, str]:
    try:
        r = session.get(url, timeout=timeout, allow_redirects=True)
        return r.status_code, (r.text if "html" in r.headers.get("Content-Type", "") else "")
    except requests.RequestException as exc:
        return 0, f"__errore__{exc.__class__.__name__}"


def testa_documento(session, url, timeout) -> tuple[str, str]:
    """Ritorna (verdetto, dettaglio) guardando i byte iniziali."""
    try:
        r = session.get(url, timeout=timeout, stream=True, allow_redirects=True)
        if r.status_code != 200:
            r.close()
            return "NON ESISTE", f"HTTP {r.status_code}"
        testa = next(r.iter_content(chunk_size=512), b"")
        ctype = r.headers.get("Content-Type", "").split(";")[0]
        lung = r.headers.get("Content-Length", "?")
        r.close()
    except requests.RequestException as exc:
        return "ERRORE", exc.__class__.__name__

    ext = Path(urlparse(url).path).suffix.lower().lstrip(".")
    atteso = MAGIC.get(ext)
    if atteso and testa.startswith(atteso):
        return "ESISTE", f"{ctype}, {lung} byte"
    if "html" in ctype.lower() or testa[:15].lower().startswith((b"<!doctype", b"<html")):
        return "SOFT-404", f"il server ha restituito {ctype or 'HTML'} al posto del file"
    return "SOSPETTO", f"{ctype}, inizio {testa[:8]!r}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--anni", type=int, nargs="*",
                    default=[2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026])
    ap.add_argument("--delay", type=float, default=0.4)
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--csv", type=Path, default=Path("sonda_archivi.csv"))
    args = ap.parse_args()

    cfg = s.Config.load(s.DEFAULT_CONFIG)
    session = requests.Session()
    session.headers.update({"User-Agent": s.USER_AGENT, "Accept-Language": "it-IT,it;q=0.9"})

    print(f"Sondo {len(SCHEMI)} schemi su {len(args.anni)} anni, piu' un controllo "
          f"cieco per schema.\n")

    # --- controllo cieco: stesso schema con un anno impossibile ----------------
    controlli: dict[str, set[str] | None] = {}
    print("-- controllo cieco (anno 1899, deve risultare inesistente) --")
    for sez, tipo, schema in SCHEMI:
        url = BASE + schema.format(Y=ANNO_IMPOSSIBILE, Y2=ANNO_IMPOSSIBILE + 2)
        if tipo == "documento":
            verdetto, _ = testa_documento(session, url, args.timeout)
            controlli[schema] = None
            print(f"   {verdetto:9s} documento {sez}")
            if verdetto == "ESISTE":
                print("   ANOMALIA: esiste un documento per il 1899, la sonda non "
                      "puo' distinguere nulla su questo schema")
        else:
            stato, html = scarica_pagina(session, url, args.timeout)
            controlli[schema] = link_documenti(cfg, url, html) if html else set()
            print(f"   HTTP {stato}, {len(controlli[schema] or [])} documenti  pagina {sez}")
        time.sleep(args.delay)

    # --- prove vere ------------------------------------------------------------
    print("\n-- verifica anno per anno --")
    righe = []
    for anno in args.anni:
        for sez, tipo, schema in SCHEMI:
            url = BASE + schema.format(Y=anno, Y2=anno + 2)
            if tipo == "documento":
                verdetto, dettaglio = testa_documento(session, url, args.timeout)
                n_anno = ""
            else:
                stato, html = scarica_pagina(session, url, args.timeout)
                if stato != 200 or not html:
                    verdetto, dettaglio, n_anno = "NON ESISTE", f"HTTP {stato}", 0
                else:
                    docs = link_documenti(cfg, url, html)
                    ctrl = controlli.get(schema) or set()
                    del_anno = {d for d in docs if str(anno) in urlparse(d).path}
                    n_anno = len(del_anno)
                    if docs and docs == ctrl:
                        verdetto = "SOFT-404"
                        dettaglio = "contenuto identico alla pagina del 1899"
                    elif n_anno == 0:
                        verdetto = "INUTILE"
                        dettaglio = f"{len(docs)} documenti, nessuno del {anno}"
                    else:
                        verdetto = "ESISTE"
                        dettaglio = f"{n_anno} documenti del {anno} su {len(docs)}"
            righe.append({"sezione": sez, "anno": anno, "tipo": tipo,
                          "verdetto": verdetto, "documenti_anno": n_anno,
                          "dettaglio": dettaglio, "url": url})
            if verdetto == "ESISTE":
                print(f"   {anno}  {sez:30s} {dettaglio}")
                print(f"          {url[len(BASE):]}")
            time.sleep(args.delay)

    import csv as _csv
    with args.csv.open("w", encoding="utf-8-sig", newline="") as fh:
        w = _csv.DictWriter(fh, fieldnames=["sezione", "anno", "tipo", "verdetto",
                                            "documenti_anno", "dettaglio", "url"])
        w.writeheader()
        w.writerows(righe)

    print(f"\n---- riepilogo ({args.csv}) ----")
    sezioni = sorted({r["sezione"] for r in righe})
    verdetti = ["ESISTE", "INUTILE", "SOFT-404", "NON ESISTE", "SOSPETTO", "ERRORE"]
    print(f"  {'sezione':30s} " + " ".join(f"{v:>10s}" for v in verdetti))
    for sez in sezioni:
        conta = {v: sum(1 for r in righe if r["sezione"] == sez and r["verdetto"] == v)
                 for v in verdetti}
        print(f"  {sez:30s} " + " ".join(f"{conta[v]:10d}" for v in verdetti))

    esistono = [r for r in righe if r["verdetto"] == "ESISTE"]
    print(f"\n  archivi realmente utilizzabili: {len(esistono)} su {len(righe)} provati")
    if not esistono:
        print("  Nessuno schema funziona: gli archivi hanno un'altra forma e "
              "vanno cercati a mano sul sito.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
