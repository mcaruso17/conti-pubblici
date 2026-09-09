#!/usr/bin/env python3
"""
Scraper della documentazione di bilancio pubblicata dalla Ragioneria Generale
dello Stato (www.rgs.mef.gov.it).

Obiettivo: raccogliere in locale rendiconti (conti consuntivi), leggi di bilancio,
assestamenti e circolari dal 2020 al 2026, per poter poi ricostruire il trattamento
dei residui passivi (perenzione, economie, reiscrizione).

Il crawler e' *discovery-based*: non costruisce URL per tentativi, ma parte dalle
pagine indice elencate in config/seeds.yaml, segue i link HTML che restano dentro i
prefissi consentiti e scarica i documenti binari che incontra.

Uso tipico:
    python3 scripts/scrape_rgs.py --dry-run           # mostra cosa scaricherebbe
    python3 scripts/scrape_rgs.py                     # scarica tutto
    python3 scripts/scrape_rgs.py --years 2022 2023   # solo alcuni anni
    python3 scripts/scrape_rgs.py --only rendiconto   # solo le categorie che matchano

Il manifest (data/manifest/manifest.jsonl) rende l'esecuzione idempotente: un file
gia' scaricato e con lo stesso ETag/Last-Modified non viene riscaricato.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
import yaml

# Su Windows la console usa spesso cp1252 e i nomi file RGS contengono accenti:
# senza questo, un semplice print del percorso fa esplodere lo script.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

SCRIPT_DIR = Path(__file__).resolve().parent


def _detect_root() -> Path:
    """Individua la cartella di lavoro del progetto.

    Funziona in tre situazioni:
      1. script dentro il repo, in scripts/  -> root = repo
      2. script alla radice del repo         -> root = repo
      3. script copiato da solo (es. Downloads) -> root = cartella dello script,
         e la configurazione viene presa da quella incorporata piu' sotto.
    """
    for candidate in (SCRIPT_DIR.parent, SCRIPT_DIR):
        if (candidate / "config" / "seeds.yaml").is_file():
            return candidate
    return SCRIPT_DIR


ROOT = _detect_root()
DEFAULT_CONFIG = ROOT / "config" / "seeds.yaml"
DEFAULT_OUT = ROOT / "data" / "raw"
DEFAULT_MANIFEST = ROOT / "data" / "manifest" / "manifest.jsonl"

# Copia incorporata di config/seeds.yaml, usata quando il file non e' presente
# (script eseguito fuori dal repository). scripts/test_scraper_offline.py
# verifica che le due versioni non divergano.
EMBEDDED_SEEDS_YAML = """\
# Seed di partenza per lo scraping del sito RGS (Ragioneria Generale dello Stato).
#
# Ogni seed definisce:
#   category       : categoria di ripiego, usata solo se nessuna regola di
#                    category_rules corrisponde all'URL del documento
#   url            : pagina indice da cui partire
#   depth          : profondita' massima di crawling HTML a partire dal seed
#   allow_prefixes : (opzionale) restringe il crawling di QUESTO seed a certi path,
#                    invece di usare i prefissi globali
#   note           : perche' questo seed serve all'analisi residui/economie
#
# Il crawler NON indovina URL: parte da queste pagine, segue i link HTML che restano
# dentro i prefissi consentiti e scarica i documenti binari trovati.

host: www.rgs.mef.gov.it
scheme: https

# Solo i link il cui path inizia con uno di questi prefissi vengono seguiti/scaricati.
# Il confronto e' case-insensitive (il sito usa sia /circolari/ sia /CIRCOLARI/).
allow_prefixes:
  - /VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/
  - /VERSIONE-I/circolari/
  - /VERSIONE-I/bilancio_aperto/
  - /VERSIONE-I/archivio/
  - /_Documenti/VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/
  - /_Documenti/VERSIONE-I/Attivit--i/
  - /_Documenti/VERSIONE-I/CIRCOLARI/

# Estensioni considerate "documento" e quindi scaricate.
doc_extensions: [pdf, xls, xlsx, xlsm, csv, zip, doc, docx, ods, txt, xml]

years: [2020, 2021, 2022, 2023, 2024, 2025, 2026]

# La cartella di destinazione di un documento si decide dal SUO path, non dal seed
# che lo ha trovato: cosi' un PDF del conto del bilancio finisce sempre nella stessa
# cartella, che sia stato scoperto partendo dall'hub o dalla pagina specifica.
# Prima regola che corrisponde (sottostringa, case-insensitive) vince.
category_rules:
  - match: /conto_del_bilancio_e_conto_del_patrimonio/conto_del_bilancio/
    category: rendiconto/conto_del_bilancio
  - match: /conto_generale_del_patrimonio/
    category: rendiconto/conto_del_patrimonio
  - match: /conto-del-bilancio/
    category: rendiconto/conto_del_bilancio
  - match: /rendiconto/rendiconto_economico/
    category: rendiconto/rendiconto_economico
  - match: /rendiconto/rendiconto_in_breve/
    category: rendiconto/rendiconto_in_breve
  - match: /rendiconto/
    category: rendiconto/altro
  - match: /bilancio_di_previsione/bilancio_finanziario/
    category: bilancio_previsione/bilancio_finanziario
  - match: /bilancio_di_previsione/note_integrative/
    category: bilancio_previsione/note_integrative
  - match: /bilancio_di_previsione/bilancio_in_breve/
    category: bilancio_previsione/bilancio_in_breve
  - match: /bilancio_di_previsione/
    category: bilancio_previsione/altro
  - match: /la_gestione_dei_residui/
    category: gestione_bilancio/gestione_residui
  - match: /assestamento_del_bilancio/
    category: gestione_bilancio/assestamento
  - match: /gestione_del_bilancio/
    category: gestione_bilancio/altro
  - match: /decreti_di_variazione/
    category: gestione_bilancio/decreti_di_variazione
  - match: /note_integrative_a_consuntivo/
    category: rendiconto/note_integrative_a_consuntivo
  - match: /il_patrimonio_dello_stato/
    category: rendiconto/patrimonio_dello_stato
  - match: /circolari/
    category: circolari
  - match: /bilancio_aperto/
    category: bilancio_aperto

seeds:

  # I seed specifici vengono prima degli hub: l'ordine non cambia piu' la cartella
  # di destinazione (ci pensano le category_rules) ma tiene i log leggibili.

  # ---------------------------------------------------------------- RENDICONTO
  - category: rendiconto/conto_del_bilancio
    url: /VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/conto_del_bilancio/
    depth: 3
    note: >
      FONTE PRINCIPALE. Conti consuntivi per unita' di voto e per piano gestionale
      (file CON_<anno>_<codice amministrazione>-*.pdf) con le colonne dei residui:
      consistenza iniziale, pagamenti, economie/eliminazioni, residui finali.

  - category: rendiconto/conto_del_patrimonio
    url: /VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/conto_generale_del_patrimonio/
    depth: 3
    note: Conto generale del patrimonio, dove i residui perenti figurano come debiti.

  - category: rendiconto/rendiconto_economico
    url: /VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/rendiconto/rendiconto_economico/
    depth: 3
    note: Contabilita' economica analitica per centro di costo.

  - category: rendiconto/rendiconto_in_breve
    url: /VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/rendiconto/rendiconto_in_breve/
    depth: 2
    note: Sintesi divulgativa, utile per i totali aggregati di residui ed economie.

  - category: rendiconto/altro
    url: /VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/
    depth: 3
    note: Hub che espone gli archivi per anno di Conto del bilancio e Conto del patrimonio.

  - category: rendiconto/altro
    url: /VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/rendiconto/
    depth: 2
    note: Pagina madre del Rendiconto generale dello Stato.

  # ------------------------------------------------------- BILANCIO DI PREVISIONE
  - category: bilancio_previsione/bilancio_finanziario
    url: /VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/bilancio_di_previsione/bilancio_finanziario/
    depth: 3
    note: >
      Legge di bilancio: stati di previsione per ministero, allegati tecnici, tabelle.
      Nello stato di previsione del MEF stanno i fondi speciali per la riassegnazione
      dei residui passivi perenti. Archivi per triennio: BF_<anno>_<anno+2>/.

  - category: bilancio_previsione/note_integrative
    url: /VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/bilancio_di_previsione/note_integrative/note_integrative_al_bilancio_di_previsione/
    depth: 3
    note: Note integrative al bilancio di previsione, per capitolo/azione.

  - category: bilancio_previsione/bilancio_in_breve
    url: /VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/bilancio_di_previsione/bilancio_in_breve/
    depth: 2
    note: Sintesi della legge di bilancio.

  # ------------------------------------------------------- GESTIONE E ASSESTAMENTO
  - category: gestione_bilancio/gestione_residui
    url: /VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/gestione_del_bilancio/assestamento_del_bilancio/la_gestione_dei_residui/
    depth: 0
    save_html: true
    note: >
      Questa pagina non ha allegati: il contenuto e' il testo stesso, quindi va
      salvata come HTML (save_html) invece di cercarvi documenti.
      SNODO CONCETTUALE. Pagina RGS su perenzione, economie e reiscrizione dei
      residui passivi perenti tramite i fondi speciali.

  - category: gestione_bilancio/assestamento
    url: /VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/gestione_del_bilancio/assestamento_del_bilancio/
    depth: 3
    note: >
      In assestamento i residui presunti iscritti a gennaio vengono sostituiti dai
      residui accertati del rendiconto precedente. Il delta per amministrazione e'
      un indicatore diretto di quanto viene rideterminato.

  - category: gestione_bilancio/altro
    url: /VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/gestione_del_bilancio/
    depth: 2
    note: Hub gestione del bilancio (variazioni, flessibilita', decreti).

  # Scoperti dalla diagnostica: erano linkati dalle pagine gia' visitate ma
  # nessun seed li raggiungeva.
  - category: gestione_bilancio/decreti_di_variazione
    url: /VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/gestione_del_bilancio/decreti_di_variazione/
    depth: 3
    note: >
      RILEVANTE. I decreti di variazione includono i prelevamenti dai fondi
      speciali per la reiscrizione dei residui perenti: e' l'atto che dispone
      la singola reiscrizione, il piu' vicino a una risposta sul "perche'".

  - category: rendiconto/note_integrative_a_consuntivo
    url: /VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/rendiconto/note_integrative_a_consuntivo/
    depth: 3
    note: >
      Ogni amministrazione commenta a consuntivo la propria gestione. E' il posto
      dove un ministero puo' spiegare a parole perche' non ha speso.

  - category: rendiconto/patrimonio_dello_stato
    url: /VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/il_patrimonio_dello_stato/
    depth: 2
    note: Relazione sul patrimonio dello Stato.

  # ------------------------------------------------------------------- CIRCOLARI
  # Le circolari annuali di chiusura esercizio e di formazione del rendiconto
  # dettano le regole operative su perenzione, economie e reiscrizioni.
  #
  # Ogni anno ha allow_prefixes propri: l'indice di un anno linka gli altri anni,
  # e senza questo vincolo il primo seed consumava da solo il budget di pagine e
  # lasciava a secco tutti gli anni successivi.
  - category: circolari
    url: /VERSIONE-I/circolari/2020/
    depth: 2
    allow_prefixes: [/VERSIONE-I/circolari/2020/, /_Documenti/VERSIONE-I/CIRCOLARI/2020/]
  - category: circolari
    url: /VERSIONE-I/circolari/2021/
    depth: 2
    allow_prefixes: [/VERSIONE-I/circolari/2021/, /_Documenti/VERSIONE-I/CIRCOLARI/2021/]
  - category: circolari
    url: /VERSIONE-I/circolari/2022/
    depth: 2
    allow_prefixes: [/VERSIONE-I/circolari/2022/, /_Documenti/VERSIONE-I/CIRCOLARI/2022/]
  - category: circolari
    url: /VERSIONE-I/circolari/2023/
    depth: 2
    allow_prefixes: [/VERSIONE-I/circolari/2023/, /_Documenti/VERSIONE-I/CIRCOLARI/2023/]
  - category: circolari
    url: /VERSIONE-I/circolari/2024/
    depth: 2
    allow_prefixes: [/VERSIONE-I/circolari/2024/, /_Documenti/VERSIONE-I/CIRCOLARI/2024/]
  - category: circolari
    url: /VERSIONE-I/circolari/2025/
    depth: 2
    allow_prefixes: [/VERSIONE-I/circolari/2025/, /_Documenti/VERSIONE-I/CIRCOLARI/2025/]
  - category: circolari
    url: /VERSIONE-I/circolari/2026/
    depth: 2
    allow_prefixes: [/VERSIONE-I/circolari/2026/, /_Documenti/VERSIONE-I/CIRCOLARI/2026/]
"""

USER_AGENT = (
    "conti-pubblici-research/1.0 (raccolta documenti pubblici RGS; "
    "contatto: vedi README del repository)"
)

HREF_RE = re.compile(r"""href\s*=\s*["']([^"'#>]+)["']""", re.IGNORECASE)
YEAR_RE = re.compile(r"(?<!\d)(20[0-3]\d)(?!\d)")
# Nome file dei conti consuntivi: CON_<anno>_<codice amministrazione>-<n>-<titolo>.pdf
CON_RE = re.compile(r"CON_(20\d{2})_(\d{3})", re.IGNORECASE)

# Limite prudenziale di lunghezza del percorso (Windows si ferma a 260 senza
# la chiave di registro LongPathsEnabled).
MAX_PATH_LEN = 240 if os.name == "nt" else 4000


# --------------------------------------------------------------------------- util

_LOG_FILE = None


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    if _LOG_FILE is not None:
        _LOG_FILE.write(line + "\n")
        _LOG_FILE.flush()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_name(value: str, maxlen: int = 120) -> str:
    """Nome di file/cartella sicuro, preservando leggibilita'."""
    value = unquote(value)
    value = re.sub(r"[^\w\-. ]+", "_", value, flags=re.UNICODE).strip(" ._")
    value = re.sub(r"_{2,}", "_", value)
    if len(value) > maxlen:
        stem, dot, ext = value.rpartition(".")
        if dot and len(ext) <= 5:
            value = stem[: maxlen - len(ext) - 1] + "." + ext
        else:
            value = value[:maxlen]
    return value or "documento"


def guess_year(url: str, fallback: int | None = None) -> str:
    """Deduce l'anno di riferimento dal path dell'URL.

    Preferisce l'anno che compare in un segmento di path dedicato (es. /2022/) o
    nel nome file dei conti consuntivi, perche' e' il piu' affidabile.
    """
    path = urlparse(url).path
    m = CON_RE.search(path)
    if m:
        return m.group(1)
    segments = [s for s in path.split("/") if s]
    for seg in reversed(segments):
        if re.fullmatch(r"20[0-3]\d", seg):
            return seg
    # triennio del bilancio finanziario: BF_2024_2026 -> 2024
    m = re.search(r"BF_(20\d{2})_20\d{2}", path)
    if m:
        return m.group(1)
    years = YEAR_RE.findall(path)
    if years:
        return years[-1]
    return str(fallback) if fallback else "senza_anno"


# ------------------------------------------------------------------------ config

@dataclass
class Seed:
    category: str
    url: str
    depth: int = 2
    note: str = ""
    # Se valorizzato, restringe il crawling di questo seed a questi path,
    # ignorando i prefissi globali. Serve per gli indici che linkano ad altri
    # anni: senza vincolo il primo seed consuma il budget di pagine di tutti.
    allow_prefixes: list[str] = field(default_factory=list)
    # Alcune pagine RGS non hanno allegati: il contenuto e' il testo stesso.
    # Con save_html la pagina viene salvata come documento.
    save_html: bool = False


@dataclass
class Config:
    host: str
    scheme: str
    allow_prefixes: list[str]
    doc_extensions: set[str]
    years: list[int]
    category_rules: list[tuple[str, str]] = field(default_factory=list)
    seeds: list[Seed] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        if path is not None and path.is_file():
            raw = path.read_text(encoding="utf-8")
        else:
            if path is not None:
                log(f"config non trovata in {path}: uso la configurazione incorporata")
            raw = EMBEDDED_SEEDS_YAML
        data = yaml.safe_load(raw)
        seeds = [
            Seed(
                category=s["category"],
                url=s["url"],
                depth=int(s.get("depth", 2)),
                note=(s.get("note") or "").strip(),
                allow_prefixes=list(s.get("allow_prefixes") or []),
                save_html=bool(s.get("save_html", False)),
            )
            for s in data["seeds"]
        ]
        rules = [
            (r["match"].lower(), r["category"])
            for r in (data.get("category_rules") or [])
        ]
        return cls(
            host=data["host"],
            scheme=data.get("scheme", "https"),
            allow_prefixes=list(data["allow_prefixes"]),
            doc_extensions={e.lower().lstrip(".") for e in data["doc_extensions"]},
            years=[int(y) for y in data.get("years", [])],
            category_rules=rules,
            seeds=seeds,
        )

    def absolute(self, url: str) -> str:
        return urljoin(f"{self.scheme}://{self.host}/", url)

    def in_scope(self, url: str, prefixes: list[str] | None = None) -> bool:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False
        if p.netloc.lower() != self.host.lower():
            return False
        # Case-insensitive: il sito usa sia /circolari/ sia /CIRCOLARI/.
        path = p.path.lower()
        for prefix in (prefixes or self.allow_prefixes):
            if path.startswith(prefix.lower()):
                return True
        return False

    def category_for(self, url: str, fallback: str) -> str:
        """Categoria di destinazione dedotta dal path del documento.

        Il seed che ha trovato il file non deve determinare dove finisce: lo stesso
        PDF raggiunto da un hub o dalla pagina specifica deve stare nella stessa
        cartella.
        """
        path = urlparse(url).path.lower()
        for needle, category in self.category_rules:
            if needle in path:
                return category
        return fallback

    def extension_of(self, url: str) -> str:
        return Path(urlparse(url).path).suffix.lower().lstrip(".")

    def is_document(self, url: str) -> bool:
        return self.extension_of(url) in self.doc_extensions


# ---------------------------------------------------------------------- manifest

class Manifest:
    """Registro append-only dei download, chiave = URL."""

    def __init__(self, path: Path):
        self.path = path
        self.entries: dict[str, dict] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self.entries[rec["url"]] = rec
        path.parent.mkdir(parents=True, exist_ok=True)

    def get(self, url: str) -> dict | None:
        return self.entries.get(url)

    def add(self, rec: dict) -> None:
        self.entries[rec["url"]] = rec
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def rewrite_csv(self, csv_path: Path) -> None:
        import csv as _csv

        cols = [
            "url", "category", "anno", "amministrazione", "path", "content_type",
            "bytes", "sha256", "etag", "last_modified", "scaricato_il",
        ]
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        rows = sorted(
            self.entries.values(),
            key=lambda r: (r.get("category", ""), r.get("anno", ""), r.get("path", "")),
        )
        with csv_path.open("w", encoding="utf-8", newline="") as fh:
            w = _csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)


# ----------------------------------------------------------------------- crawler

class Scraper:
    def __init__(self, cfg: Config, out_dir: Path, manifest: Manifest,
                 delay: float, dry_run: bool, years: set[int] | None,
                 max_pages: int, timeout: int, quiet: bool = False):
        self.cfg = cfg
        self.out_dir = out_dir
        self.manifest = manifest
        self.delay = delay
        self.dry_run = dry_run
        self.years = years
        self.max_pages = max_pages
        self.timeout = timeout
        self.quiet = quiet
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "it-IT,it;q=0.9",
        })
        self.visited_pages: set[str] = set()
        self.seen_docs: set[str] = set()
        self.stats = {"pagine": 0, "documenti_nuovi": 0, "documenti_saltati": 0,
                      "errori": 0, "bytes": 0}
        self.errors: list[tuple[str, str]] = []
        # Ogni documento incontrato, anche in dry-run: serve a ispezionare la
        # copertura (per categoria, anno, amministrazione) senza scaricare nulla.
        self.discovered: list[dict] = []

    # -- rete -------------------------------------------------------------

    def _get(self, url: str, stream: bool = False) -> requests.Response | None:
        backoff = 2.0
        for attempt in range(1, 5):
            try:
                r = self.session.get(url, timeout=self.timeout, stream=stream,
                                     allow_redirects=True)
                if r.status_code == 200:
                    return r
                if r.status_code in (429, 500, 502, 503, 504):
                    log(f"  HTTP {r.status_code} su {url} - retry {attempt}/4")
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                log(f"  HTTP {r.status_code} su {url} - salto")
                self.errors.append((url, f"HTTP {r.status_code}"))
                return None
            except requests.RequestException as exc:
                log(f"  errore rete su {url}: {exc.__class__.__name__} - retry {attempt}/4")
                time.sleep(backoff)
                backoff *= 2
        self.errors.append((url, "rete: 4 tentativi falliti"))
        self.stats["errori"] += 1
        return None

    # -- destinazione ------------------------------------------------------

    def dest_path(self, url: str, category: str) -> Path:
        anno = guess_year(url)
        parsed = urlparse(url)
        filename = safe_name(Path(parsed.path).name or "documento")
        # Evita collisioni tra file omonimi in sottocartelle diverse.
        parent = safe_name(Path(parsed.path).parent.name or "")
        target = self.out_dir / category / anno
        if parent and parent.lower() not in (anno, "", "documenti"):
            target = target / parent
        return target / filename

    def amministrazione_of(self, url: str) -> str:
        m = CON_RE.search(urlparse(url).path)
        return m.group(2) if m else ""

    def year_allowed(self, url: str) -> bool:
        if not self.years:
            return True
        anno = guess_year(url)
        if anno == "senza_anno":
            return True  # in dubbio si scarica: meglio un file in piu' che uno in meno
        try:
            return int(anno) in self.years
        except ValueError:
            return True

    # -- download ----------------------------------------------------------

    def save_page(self, url: str, html: str, category: str) -> None:
        """Salva una pagina HTML come documento."""
        if url in self.seen_docs:
            return
        self.seen_docs.add(url)
        cat = self.cfg.category_for(url, category)
        anno = guess_year(url)
        nome = safe_name(urlparse(url).path.strip("/").replace("/", "__")) + ".html"
        dest = self.out_dir / cat / anno / nome
        self.discovered.append({"url": url, "category": cat, "anno": anno,
                                "amministrazione": "", "path": str(dest)})
        if self.dry_run:
            if not self.quiet:
                log(f"  [dry-run] pagina {url}")
            self.stats["documenti_nuovi"] += 1
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(html, encoding="utf-8", errors="replace")
        rec = {
            "url": url, "category": cat, "anno": anno, "amministrazione": "",
            "path": str(dest.relative_to(ROOT)) if ROOT in dest.parents else str(dest),
            "content_type": "text/html", "bytes": len(html.encode("utf-8")),
            "sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
            "etag": "", "last_modified": "",
            "scaricato_il": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.manifest.add(rec)
        self.stats["documenti_nuovi"] += 1
        log(f"  OK pagina    {nome}")

    def _short_dest(self, url: str, dest: Path) -> Path:
        """Nome file corto e stabile, derivato dall'URL."""
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
        suffix = Path(urlparse(url).path).suffix.lower()
        return dest.parent / f"{digest}{suffix}"

    def _stream_to(self, dest: Path, r: requests.Response) -> int:
        tmp = dest.with_suffix(dest.suffix + ".part")
        size = 0
        with tmp.open("wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if chunk:
                    fh.write(chunk)
                    size += len(chunk)
        tmp.replace(dest)
        return size

    def download(self, url: str, seed_category: str) -> None:
        if url in self.seen_docs:
            return
        self.seen_docs.add(url)

        if not self.year_allowed(url):
            return

        category = self.cfg.category_for(url, seed_category)
        dest = self.dest_path(url, category)
        self.discovered.append({
            "url": url,
            "category": category,
            "anno": guess_year(url),
            "amministrazione": self.amministrazione_of(url),
            "path": str(dest),
        })
        prev = self.manifest.get(url)
        if prev and Path(prev["path"]).is_absolute():
            prev_path = Path(prev["path"])
        elif prev:
            prev_path = ROOT / prev["path"]
        else:
            prev_path = None

        if prev and prev_path and prev_path.exists():
            self.stats["documenti_saltati"] += 1
            return

        if self.dry_run:
            if not self.quiet:
                log(f"  [dry-run] {url}")
            self.stats["documenti_nuovi"] += 1
            return

        r = self._get(url, stream=True)
        if r is None:
            return

        dest.parent.mkdir(parents=True, exist_ok=True)

        # Windows senza long paths abilitati si ferma a 260 caratteri: accorcia
        # in anticipo, con un nome corto deterministico tracciato nel manifest.
        if len(str(dest)) > MAX_PATH_LEN:
            dest = self._short_dest(url, dest)
            log(f"  percorso troppo lungo, uso {dest.name}")

        try:
            size = self._stream_to(dest, r)
        except OSError as exc:
            r.close()
            short = self._short_dest(url, dest)
            log(f"  scrittura fallita ({exc.__class__.__name__}), riprovo come {short.name}")
            r2 = self._get(url, stream=True)
            if r2 is None:
                return
            try:
                size = self._stream_to(short, r2)
            except OSError as exc2:
                log(f"  scrittura fallita di nuovo: {exc2}")
                self.errors.append((url, f"scrittura: {exc2}"))
                self.stats["errori"] += 1
                return
            dest = short

        rec = {
            "url": url,
            "category": category,
            "anno": guess_year(url),
            "amministrazione": self.amministrazione_of(url),
            "path": str(dest.relative_to(ROOT)),
            "content_type": r.headers.get("Content-Type", ""),
            "bytes": size,
            "sha256": sha256_file(dest),
            "etag": r.headers.get("ETag", ""),
            "last_modified": r.headers.get("Last-Modified", ""),
            "scaricato_il": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.manifest.add(rec)
        self.stats["documenti_nuovi"] += 1
        self.stats["bytes"] += size
        log(f"  OK {size/1024:8.0f} KB  {dest.relative_to(ROOT)}")
        time.sleep(self.delay)

    # -- crawling ----------------------------------------------------------

    def crawl_seed(self, seed: Seed) -> None:
        start = self.cfg.absolute(seed.url)
        prefixes = seed.allow_prefixes or None
        log(f"== SEED [{seed.category}] {start}")
        # La pagina di partenza va sempre letta, anche se un seed precedente
        # l'aveva gia' incrociata: altrimenti il seed diventa un no-op silenzioso.
        self.visited_pages.discard(start)
        queue: deque[tuple[str, int]] = deque([(start, 0)])
        pages_here = 0
        docs_before = len(self.seen_docs)

        while queue:
            url, depth = queue.popleft()
            url = url.split("#")[0]
            if url in self.visited_pages:
                continue
            self.visited_pages.add(url)

            if pages_here >= self.max_pages:
                log(f"  limite di {self.max_pages} pagine raggiunto per questo seed")
                break

            r = self._get(url)
            if r is None:
                continue
            pages_here += 1
            self.stats["pagine"] += 1

            ctype = r.headers.get("Content-Type", "")
            if "html" not in ctype.lower():
                continue

            html = r.text
            if seed.save_html:
                self.save_page(url, html, seed.category)

            links: list[str] = []
            for raw in HREF_RE.findall(html):
                raw = raw.strip()
                if not raw or raw.lower().startswith(("mailto:", "javascript:", "tel:")):
                    continue
                links.append(urljoin(url, raw))

            docs = [l for l in links
                    if self.cfg.is_document(l) and self.cfg.in_scope(l, prefixes)]
            for d in docs:
                self.download(d.split("#")[0], seed.category)

            if depth < seed.depth:
                for l in links:
                    l = l.split("#")[0]
                    if l in self.visited_pages or self.cfg.is_document(l):
                        continue
                    if not self.cfg.in_scope(l, prefixes):
                        continue
                    queue.append((l, depth + 1))

            time.sleep(self.delay)

        nuovi = len(self.seen_docs) - docs_before
        log(f"   seed concluso: {pages_here} pagine, {nuovi} documenti")
        if pages_here == 0:
            log("   ATTENZIONE: nessuna pagina letta, controlla URL e allow_prefixes")

    def run(self, seeds: list[Seed]) -> None:
        for seed in seeds:
            self.crawl_seed(seed)


# --------------------------------------------------------------------------- cli

def write_report(rows: list[dict], path: Path) -> None:
    import csv as _csv

    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["category", "anno", "amministrazione", "url", "path"]
    rows = sorted(rows, key=lambda r: (r["category"], r["anno"], r["url"]))
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = _csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument("--years", type=int, nargs="*", default=None,
                    help="filtra i documenti per anno (default: tutti quelli in seeds.yaml)")
    ap.add_argument("--only", nargs="*", default=None,
                    help="esegue solo i seed la cui categoria contiene una di queste stringhe")
    ap.add_argument("--delay", type=float, default=1.0,
                    help="pausa in secondi tra richieste (default 1.0, sii gentile)")
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--max-pages", type=int, default=400,
                    help="tetto di pagine HTML visitate per singolo seed")
    ap.add_argument("--dry-run", action="store_true",
                    help="elenca i documenti senza scaricarli")
    ap.add_argument("--report", type=Path, default=None,
                    help="scrive in CSV tutti i documenti individuati (url, categoria, "
                         "anno, amministrazione, destinazione). Funziona anche con --dry-run: "
                         "serve a validare la copertura senza rifare il crawling.")
    ap.add_argument("--quiet-dry-run", action="store_true",
                    help="in dry-run non stampa una riga per documento (usa --report)")
    ap.add_argument("--log-file", type=Path, default=None,
                    help="copia l'intero log su file, comodo per condividere la "
                         "sequenza dei seed senza dipendere dal buffer del terminale")
    args = ap.parse_args()

    if args.log_file:
        global _LOG_FILE
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        _LOG_FILE = args.log_file.open("w", encoding="utf-8")

    cfg = Config.load(args.config)
    years = set(args.years) if args.years else set(cfg.years)

    seeds = cfg.seeds
    if args.only:
        needles = [n.lower() for n in args.only]
        seeds = [s for s in seeds if any(n in s.category.lower() for n in needles)]
        if not seeds:
            log("Nessun seed corrisponde al filtro --only")
            return 1

    manifest = Manifest(args.manifest)
    scraper = Scraper(cfg, args.out, manifest, args.delay, args.dry_run,
                      years, args.max_pages, args.timeout, args.quiet_dry_run)

    log(f"Host: {cfg.host} | seed: {len(seeds)} | anni: {sorted(years)} | "
        f"dry-run: {args.dry_run}")
    t0 = time.time()
    try:
        scraper.run(seeds)
    except KeyboardInterrupt:
        log("interrotto dall'utente")

    if not args.dry_run:
        manifest.rewrite_csv(args.manifest.with_suffix(".csv"))

    if args.report:
        write_report(scraper.discovered, args.report)
        log(f"report scritto in {args.report} ({len(scraper.discovered)} documenti)")

    # Ripartizione per categoria e anno: e' il controllo piu' rapido per capire se
    # un ramo del sito e' rimasto scoperto.
    if scraper.discovered:
        log("---- documenti per categoria ----")
        by_cat: dict[str, int] = {}
        for d in scraper.discovered:
            by_cat[d["category"]] = by_cat.get(d["category"], 0) + 1
        for cat in sorted(by_cat):
            log(f"  {cat:44s} {by_cat[cat]:5d}")
        log("---- documenti per anno ----")
        by_year: dict[str, int] = {}
        for d in scraper.discovered:
            by_year[d["anno"]] = by_year.get(d["anno"], 0) + 1
        for year in sorted(by_year):
            log(f"  {year:44s} {by_year[year]:5d}")

    s = scraper.stats
    log("---- riepilogo ----")
    log(f"pagine visitate    : {s['pagine']}")
    log(f"documenti nuovi    : {s['documenti_nuovi']}")
    log(f"gia' presenti      : {s['documenti_saltati']}")
    log(f"errori             : {s['errori']}")
    log(f"scaricati          : {s['bytes']/1e6:.1f} MB")
    log(f"tempo              : {time.time()-t0:.0f}s")
    if scraper.errors:
        log(f"URL falliti ({len(scraper.errors)}):")
        for url, why in scraper.errors[:30]:
            log(f"  {why}  {url}")
    if _LOG_FILE is not None:
        _LOG_FILE.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
