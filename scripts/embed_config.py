#!/usr/bin/env python3
"""Rigenera la copia di config/seeds.yaml incorporata in scripts/scrape_rgs.py.

Lo scraper deve poter girare anche copiato da solo, fuori dal repository: per
questo porta dentro di se' una copia della configurazione. Dopo ogni modifica a
config/seeds.yaml eseguire:

    python3 scripts/embed_config.py

scripts/test_scraper_offline.py fallisce se le due versioni divergono.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "scrape_rgs.py"
CONFIG = ROOT / "config" / "seeds.yaml"

seeds = CONFIG.read_text(encoding="utf-8")
if '"""' in seeds or "\\" in seeds:
    sys.exit("config/seeds.yaml contiene caratteri che romperebbero l'incorporamento")

text = SCRIPT.read_text(encoding="utf-8")
pattern = re.compile(r'EMBEDDED_SEEDS_YAML = """\\\n.*?"""', re.DOTALL)
if not pattern.search(text):
    sys.exit("blocco EMBEDDED_SEEDS_YAML non trovato in scrape_rgs.py")

new_block = 'EMBEDDED_SEEDS_YAML = """\\\n' + seeds + '"""'
SCRIPT.write_text(pattern.sub(lambda _: new_block, text, count=1), encoding="utf-8")
print(f"incorporata config/seeds.yaml ({len(seeds)} caratteri) in {SCRIPT.name}")
