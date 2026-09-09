#!/usr/bin/env python3
"""Sonda quali pagine di archivio per anno esistono sul sito RGS.

La diagnostica del 2026-09-09 ha mostrato che ogni sezione pubblica SOLO l'anno
corrente e non linka gli anni precedenti: il crawler, che segue i link, non puo'
raggiungerli. Gli archivi esistono (la ricerca web ne mostra alcuni) ma vanno
indirizzati direttamente.

Questo script prova una lista di schemi di URL plausibili, anno per anno, e
riporta quali rispondono 200. Non scarica i corpi: legge solo lo stato HTTP.
Serve a scoprire lo schema vero, che poi finisce in config/seeds.yaml come seed
espliciti: non e' il crawler a tirare a indovinare, e' questo strumento a
verificare una volta sola.

    python3 scripts/probe_archivi.py
    python3 scripts/probe_archivi.py --anni 2019 2020 2021 --csv sonda.csv
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scrape_rgs as s  # noqa: E402

BASE = "https://www.rgs.mef.gov.it"
AI = "/VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio"
DOC = "/_Documenti/VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio"

# (sezione, schema). {Y} = anno, {Y2} = anno+2.
SCHEMI = [
    # --- rendiconto: conto del bilancio -------------------------------------
    ("conto_del_bilancio", AI + "/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/conto_del_bilancio/{Y}/index.html"),
    ("conto_del_bilancio", AI + "/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/conto_del_bilancio/{Y}/"),
    ("conto_del_bilancio", AI + "/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/conto_del_bilancio/CDB_{Y}/index.html"),
    # documento noto: se risponde, l'anno e' pubblicato e lo schema del path e' questo
    ("conto_del_bilancio_doc", DOC + "/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/conto_del_bilancio/{Y}/conti_consuntivi_per_unit_di_voto/CON_{Y}_020-6-Finanziario.pdf"),
    ("conto_del_bilancio_doc", DOC + "/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/conto_del_bilancio/{Y}/conti_consuntivi_piani_gestionali/CON_{Y}_020-6-Finanziario.pdf"),

    # --- rendiconto: conto del patrimonio -----------------------------------
    ("conto_patrimonio", AI + "/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/conto_generale_del_patrimonio/{Y}/index.html"),
    ("conto_patrimonio", AI + "/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/conto_generale_del_patrimonio/{Y}/"),
    ("conto_patrimonio_doc", DOC + "/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/conto_generale_del_patrimonio/{Y}/Conto-patrimonio-{Y}.pdf"),

    # --- rendiconto: altre sezioni ------------------------------------------
    ("rendiconto_economico", AI + "/rendiconto/rendiconto_economico/{Y}/index.html"),
    ("rendiconto_in_breve", AI + "/rendiconto/rendiconto_in_breve/{Y}/index.html"),
    ("note_integrative_consuntivo", AI + "/rendiconto/note_integrative_a_consuntivo/{Y}/index.html"),
    ("note_integrative_consuntivo", AI + "/rendiconto/note_integrative_a_consuntivo/{Y}/"),

    # --- bilancio di previsione ---------------------------------------------
    ("bilancio_finanziario", AI + "/bilancio_di_previsione/bilancio_finanziario/BF_{Y}_{Y2}/index.html"),
    ("bilancio_finanziario", AI + "/bilancio_di_previsione/bilancio_finanziario/{Y}-{Y2}/index.html"),
    ("note_integrative_previsione", AI + "/bilancio_di_previsione/note_integrative/note_integrative_al_bilancio_di_previsione/{Y}-{Y2}/index.html"),
    ("note_integrative_previsione", AI + "/bilancio_di_previsione/note_integrative/note_integrative_al_bilancio_di_previsione/NI_{Y}_{Y2}/index.html"),
    ("bilancio_in_breve", AI + "/bilancio_di_previsione/bilancio_in_breve/{Y}-{Y2}/index.html"),

    # --- gestione del bilancio ----------------------------------------------
    ("assestamento", AI + "/gestione_del_bilancio/assestamento_del_bilancio/{Y}/index.html"),
    ("assestamento", AI + "/gestione_del_bilancio/assestamento_del_bilancio/{Y}/"),
    ("decreti_di_variazione", AI + "/gestione_del_bilancio/decreti_di_variazione/{Y}/index.html"),
    ("decreti_di_variazione", AI + "/gestione_del_bilancio/decreti_di_variazione/{Y}/"),
]

# Pagine singole da verificare una sola volta (non dipendono dall'anno).
FISSE = [
    ("archivio_sito", "/VERSIONE-I/archivio/index.html"),
    ("decreti_di_variazione", AI + "/gestione_del_bilancio/decreti_di_variazione/"),
    ("note_integrative_consuntivo", AI + "/rendiconto/note_integrative_a_consuntivo/"),
    ("patrimonio_dello_stato", AI + "/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/il_patrimonio_dello_stato/"),
    ("ecorendiconto", AI + "/rendiconto/ecorendiconto/"),
    ("bilancio_aperto", "/VERSIONE-I/bilancio_aperto/index.html"),
]


def probe(session: requests.Session, url: str, timeout: int) -> tuple[int, str]:
    """Ritorna (stato, tipo). Legge le intestazioni, non il corpo."""
    try:
        r = session.get(url, timeout=timeout, stream=True, allow_redirects=True)
        stato, ctype = r.status_code, r.headers.get("Content-Type", "").split(";")[0]
        finale = r.url
        r.close()
        # Il sito risponde 200 anche su pagine "non trovata": segnalalo se e' stato
        # rediretto altrove.
        if finale.rstrip("/") != url.rstrip("/"):
            ctype += f" (redirect -> {finale})"
        return stato, ctype
    except requests.RequestException as exc:
        return 0, exc.__class__.__name__


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--anni", type=int, nargs="*",
                    default=[2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026])
    ap.add_argument("--delay", type=float, default=0.4)
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--csv", type=Path, default=Path("sonda_archivi.csv"))
    args = ap.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": s.USER_AGENT, "Accept-Language": "it-IT,it;q=0.9"})

    prove: list[tuple[str, str]] = [(sez, BASE + path) for sez, path in FISSE]
    for anno in args.anni:
        for sez, schema in SCHEMI:
            prove.append((sez, BASE + schema.format(Y=anno, Y2=anno + 2)))

    print(f"sondo {len(prove)} URL, ~{len(prove) * (args.delay + 0.3) / 60:.0f} minuti\n")
    righe = []
    trovati: dict[str, list[str]] = {}
    for i, (sez, url) in enumerate(prove, 1):
        stato, ctype = probe(session, url, args.timeout)
        righe.append({"sezione": sez, "stato": stato, "url": url, "tipo": ctype})
        if stato == 200:
            trovati.setdefault(sez, []).append(url)
            print(f"  200  {sez:30s} {url[len(BASE):]}")
        if i % 25 == 0:
            print(f"  ... {i}/{len(prove)}")
        time.sleep(args.delay)

    import csv as _csv
    with args.csv.open("w", encoding="utf-8-sig", newline="") as fh:
        w = _csv.DictWriter(fh, fieldnames=["sezione", "stato", "url", "tipo"])
        w.writeheader()
        w.writerows(righe)

    print(f"\n---- riepilogo ({args.csv}) ----")
    for sez in sorted({s_ for s_, _ in prove}):
        n = len(trovati.get(sez, []))
        stato = "OK" if n else "NESSUN ARCHIVIO TROVATO"
        print(f"  {sez:32s} {n:3d} pagine  {stato}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
