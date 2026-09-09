#!/usr/bin/env python3
"""Simulazione del crawling con un sito finto (nessuna rete).

Riproduce il difetto osservato nella prima esecuzione reale: l'indice delle
circolari 2020 linka tutti gli altri anni, quindi il primo seed li marcava come
gia' visitati e i sei seed successivi non leggevano nemmeno la propria pagina di
partenza. Il test fallisce se quel comportamento torna.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scrape_rgs as s  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HOST = "https://www.rgs.mef.gov.it"
ANNI = [2020, 2021, 2022, 2023, 2024, 2025, 2026]

# Sito finto: ogni indice annuale linka tutti gli altri anni piu' un proprio PDF.
PAGES = {}
for a in ANNI:
    altri = "".join(f'<a href="{HOST}/VERSIONE-I/circolari/{b}/">{b}</a>' for b in ANNI)
    PAGES[f"{HOST}/VERSIONE-I/circolari/{a}/"] = (
        f'{altri}<a href="{HOST}/_Documenti/VERSIONE-I/CIRCOLARI/{a}/1/circ_{a}.pdf">c</a>'
    )


class FakeResponse:
    def __init__(self, text=""):
        self.text = text
        self.headers = {"Content-Type": "text/html; charset=utf-8"}
        self.status_code = 200


fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"{label}: atteso {want!r}, ottenuto {got!r}")


cfg = s.Config.load(ROOT / "config" / "seeds.yaml")
manifest = s.Manifest(ROOT / "data" / "manifest" / ".test_sim.jsonl")
sc = s.Scraper(cfg, ROOT / "data" / "raw", manifest, delay=0, dry_run=True,
               years=set(ANNI), max_pages=50, timeout=5, quiet=True)

richieste = []


def fake_get(url, stream=False):
    richieste.append(url)
    return FakeResponse(PAGES.get(url, ""))


sc._get = fake_get
seeds = [x for x in cfg.seeds if x.url.startswith("/VERSIONE-I/circolari/")]

# I seed vanno eseguiti uno per uno registrando le richieste di ciascuno:
# controllare solo il totale non basterebbe, perche' con il difetto il primo seed
# da solo raggiungeva tutti gli indici e il conteggio complessivo tornava lo stesso.
per_seed = []
for seed in seeds:
    prima = len(richieste)
    sc.crawl_seed(seed)
    per_seed.append((seed.url, richieste[prima:]))

# 1. OGNI seed deve aver letto la propria pagina di partenza, di persona
for (url, reqs), a in zip(per_seed, ANNI):
    proprio = f"{HOST}/VERSIONE-I/circolari/{a}/"
    check(f"seed {a} legge il proprio indice", proprio in reqs, True)
    check(f"seed {a} non resta a secco", len(reqs) > 0, True)
    # e non deve andare a curiosare negli altri anni
    altrui = [r for r in reqs if f"/{a}/" not in r]
    check(f"seed {a} non sconfina", altrui, [])

# 2. ogni anno deve aver prodotto il proprio documento
trovati = {d["anno"] for d in sc.discovered}
check("un documento per anno", trovati, {str(a) for a in ANNI})
check("sette documenti in tutto", len(sc.discovered), 7)

# 3. tutti classificati come circolari, non con la categoria del seed sbagliato
check("categoria circolari", {d["category"] for d in sc.discovered}, {"circolari"})

# 4. nessun seed deve aver sconfinato negli anni altrui: 7 indici letti, non 49
check("nessuno sconfinamento", len(richieste), 7)

(ROOT / "data" / "manifest" / ".test_sim.jsonl").unlink(missing_ok=True)

if fails:
    print("FALLITI:")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("OK: crawling simulato corretto, nessun seed rimasto a secco")
