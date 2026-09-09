#!/usr/bin/env python3
"""Diagnostica una singola pagina RGS: cosa ci trova il crawler e cosa scarta.

Serve a capire perche' un ramo del sito resta scoperto. Scarica UNA pagina e
classifica ogni link: documento scaricabile, pagina che il crawler seguirebbe,
oppure link scartato (e per quale motivo).

    python3 scripts/diagnose_page.py <url> [<url> ...]
    python3 scripts/diagnose_page.py --preset            # le pagine sospette

Con --dump-html salva l'HTML grezzo, utile se la pagina costruisce i link in
JavaScript e quindi il crawler non puo' vederli.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scrape_rgs as s  # noqa: E402

PRESET = [
    # Categorie che nella ricognizione del 2026-09-09 hanno prodotto quasi nulla.
    "/VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/bilancio_di_previsione/bilancio_finanziario/",
    "/VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/conto_generale_del_patrimonio/",
    "/VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/gestione_del_bilancio/assestamento_del_bilancio/la_gestione_dei_residui/",
    "/VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/gestione_del_bilancio/assestamento_del_bilancio/",
    "/VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/bilancio_di_previsione/note_integrative/note_integrative_al_bilancio_di_previsione/",
    # Riferimento: questa invece ha funzionato, serve per confronto.
    "/VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/conto_del_bilancio/",
]


def diagnose(cfg: s.Config, sc: s.Scraper, url: str, dump: Path | None) -> None:
    print("=" * 100)
    print(url)
    r = sc._get(url)
    if r is None:
        print("  IRRAGGIUNGIBILE")
        return

    html = r.text
    print(f"  HTTP 200 | {r.headers.get('Content-Type','?')} | {len(html)} caratteri")

    if dump:
        out = dump / (s.safe_name(urlparse(url).path.strip("/").replace("/", "__")) + ".html")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8", errors="replace")
        print(f"  HTML salvato in {out}")

    raw = [h.strip() for h in s.HREF_RE.findall(html)]
    links = [urljoin(url, h).split("#")[0] for h in raw
             if h and not h.lower().startswith(("mailto:", "javascript:", "tel:"))]

    docs, pagine, scartati = [], [], []
    for l in links:
        if cfg.is_document(l):
            (docs if cfg.in_scope(l) else scartati).append((l, "documento fuori prefissi"))
        elif cfg.in_scope(l):
            pagine.append(l)
        else:
            p = urlparse(l)
            motivo = ("altro host: " + p.netloc) if p.netloc.lower() != cfg.host.lower() \
                else "path fuori allow_prefixes"
            scartati.append((l, motivo))

    docs = [d[0] if isinstance(d, tuple) else d for d in docs]
    print(f"  link totali: {len(links)} | documenti in scope: {len(docs)} | "
          f"pagine seguibili: {len(set(pagine))} | scartati: {len(scartati)}")

    if len(links) < 15:
        print("  SOSPETTO: pochissimi link. La pagina potrebbe costruire la "
              "navigazione in JavaScript, invisibile al crawler.")
    if "<select" in html.lower():
        print("  SOSPETTO: la pagina contiene un <select>. Gli archivi per anno "
              "potrebbero stare in un menu a tendina, non in link <a href>.")
    if "iframe" in html.lower():
        print("  SOSPETTO: la pagina contiene un <iframe>: il contenuto reale "
              "potrebbe stare su un altro URL.")

    if docs:
        print("  -- documenti (primi 10) --")
        for d in sorted(set(docs))[:10]:
            print("     ", d)
    if pagine:
        print("  -- pagine seguibili (prime 15) --")
        for p_ in sorted(set(pagine))[:15]:
            print("     ", p_)
    if scartati:
        print("  -- scartati, per motivo --")
        for motivo, n in Counter(m for _, m in scartati).most_common():
            print(f"      {n:4d}  {motivo}")
        print("  -- esempi di scartati interni al sito (primi 15) --")
        interni = [l for l, m in scartati if m == "path fuori allow_prefixes"]
        for l in sorted(set(interni))[:15]:
            print("     ", urlparse(l).path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--preset", action="store_true",
                    help="diagnostica le pagine risultate scoperte nella ricognizione")
    ap.add_argument("--dump-html", type=Path, default=None,
                    help="cartella in cui salvare l'HTML grezzo delle pagine")
    args = ap.parse_args()

    cfg = s.Config.load(s.DEFAULT_CONFIG)
    sc = s.Scraper(cfg, s.DEFAULT_OUT, s.Manifest(s.DEFAULT_MANIFEST),
                   delay=1.0, dry_run=True, years=None, max_pages=1,
                   timeout=120, quiet=True)

    urls = list(args.urls)
    if args.preset or not urls:
        urls += [cfg.absolute(u) for u in PRESET]
    urls = [u if u.startswith("http") else cfg.absolute(u) for u in urls]

    for u in urls:
        diagnose(cfg, sc, u, args.dump_html)
    print("=" * 100)
    return 0


if __name__ == "__main__":
    sys.exit(main())
