#!/usr/bin/env python3
"""Test offline della logica dello scraper (nessuna rete).

Verifica parsing config, filtri di scope, deduzione anno/amministrazione e
costruzione dei percorsi di destinazione su URL reali osservati sul sito RGS.
Eseguire con: python3 scripts/test_scraper_offline.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scrape_rgs import (  # noqa: E402
    EMBEDDED_SEEDS_YAML, Config, Manifest, Scraper, guess_year, safe_name,
)

ROOT = Path(__file__).resolve().parent.parent
cfg = Config.load(ROOT / "config" / "seeds.yaml")

fails = []


def check(label, got, want):
    if got != want:
        fails.append(f"{label}: atteso {want!r}, ottenuto {got!r}")


# --- config -----------------------------------------------------------------
check("host", cfg.host, "www.rgs.mef.gov.it")

# La copia incorporata nello script (per l'esecuzione fuori dal repo) non deve
# divergere da config/seeds.yaml.
check("config incorporata allineata",
      EMBEDDED_SEEDS_YAML, (ROOT / "config" / "seeds.yaml").read_text(encoding="utf-8"))

# Config.load senza file deve ricadere sulla copia incorporata.
cfg_embedded = Config.load(ROOT / "config" / "non_esiste.yaml")
check("fallback incorporato", len(cfg_embedded.seeds), len(cfg.seeds))
check("fallback senza argomenti", Config.load().host, cfg.host)
check("n_seeds", len(cfg.seeds) > 10, True)
check("pdf riconosciuto", "pdf" in cfg.doc_extensions, True)

# --- scope ------------------------------------------------------------------
IN = [
    "https://www.rgs.mef.gov.it/VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/rendiconto/",
    "https://www.rgs.mef.gov.it/_Documenti/VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/conto_del_bilancio/2022/conti_consuntivi_per_unit_di_voto/CON_2022_000-3-Entrata.pdf",
    "https://www.rgs.mef.gov.it/_Documenti/VERSIONE-I/CIRCOLARI/2025/27/Allegato-alla-Circolare-del-31-dicembre-2025-n-27.pdf",
    "https://www.rgs.mef.gov.it/_Documenti/VERSIONE-I/Attivit--i/Rendiconto/Conto_del_bilancio_e_Conto_del_patrimonio/2013/Conto-del-bilancio/ri/Relazione_illustrativa_completa_cdb_2013.pdf",
]
OUT = [
    "https://www.mef.gov.it/qualcosa.pdf",                      # altro host
    "https://www.rgs.mef.gov.it/VERSIONE-I/news/2026/x.html",   # fuori prefissi
    "mailto:info@rgs.it",
]
for u in IN:
    check(f"in_scope {u[-40:]}", cfg.in_scope(u), True)
for u in OUT:
    check(f"out_scope {u[-40:]}", cfg.in_scope(u), False)

# --- riconoscimento documenti ----------------------------------------------
check("is_document pdf", cfg.is_document(IN[1]), True)
check("is_document html", cfg.is_document(IN[0]), False)
check("is_document index.html",
      cfg.is_document("https://www.rgs.mef.gov.it/a/index.html"), False)

# --- deduzione anno ---------------------------------------------------------
check("anno da CON_", guess_year(IN[1]), "2022")
check("anno da segmento", guess_year(IN[3]), "2013")
check("anno circolare", guess_year(IN[2]), "2025")
check("anno da BF_", guess_year(
    "https://www.rgs.mef.gov.it/VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/bilancio_di_previsione/bilancio_finanziario/BF_2024_2026/index.html"),
    "2024")
check("anno assente", guess_year("https://www.rgs.mef.gov.it/a/b.pdf"), "senza_anno")

# --- nomi sicuri ------------------------------------------------------------
check("safe_name", safe_name("CON_2022_000-3-Entrata.pdf"), "CON_2022_000-3-Entrata.pdf")
check("safe_name spazi", safe_name("Conto del bilancio (2022).pdf"),
      "Conto del bilancio _2022_.pdf")

# --- destinazioni -----------------------------------------------------------
sc = Scraper(cfg, ROOT / "data" / "raw", Manifest(ROOT / "data" / "manifest" / ".test.jsonl"),
             delay=0, dry_run=True, years={2022}, max_pages=10, timeout=10)
d = sc.dest_path(IN[1], "rendiconto/conto_del_bilancio")
check("dest conti consuntivi", str(d.relative_to(ROOT)),
      "data/raw/rendiconto/conto_del_bilancio/2022/conti_consuntivi_per_unit_di_voto/CON_2022_000-3-Entrata.pdf")
check("amministrazione", sc.amministrazione_of(IN[1]), "000")
check("filtro anno ok", sc.year_allowed(IN[1]), True)
check("filtro anno ko", sc.year_allowed(IN[3]), False)

(ROOT / "data" / "manifest" / ".test.jsonl").unlink(missing_ok=True)

if fails:
    print("FALLITI:")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print(f"OK: tutti i controlli offline superati ({len(cfg.seeds)} seed caricati)")
