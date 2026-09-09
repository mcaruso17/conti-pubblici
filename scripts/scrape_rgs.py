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

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "seeds.yaml"
DEFAULT_OUT = ROOT / "data" / "raw"
DEFAULT_MANIFEST = ROOT / "data" / "manifest" / "manifest.jsonl"

USER_AGENT = (
    "conti-pubblici-research/1.0 (raccolta documenti pubblici RGS; "
    "contatto: vedi README del repository)"
)

HREF_RE = re.compile(r"""href\s*=\s*["']([^"'#>]+)["']""", re.IGNORECASE)
YEAR_RE = re.compile(r"(?<!\d)(20[0-3]\d)(?!\d)")
# Nome file dei conti consuntivi: CON_<anno>_<codice amministrazione>-<n>-<titolo>.pdf
CON_RE = re.compile(r"CON_(20\d{2})_(\d{3})", re.IGNORECASE)


# --------------------------------------------------------------------------- util

def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


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


@dataclass
class Config:
    host: str
    scheme: str
    allow_prefixes: list[str]
    doc_extensions: set[str]
    years: list[int]
    seeds: list[Seed] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "Config":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        seeds = [
            Seed(
                category=s["category"],
                url=s["url"],
                depth=int(s.get("depth", 2)),
                note=(s.get("note") or "").strip(),
            )
            for s in data["seeds"]
        ]
        return cls(
            host=data["host"],
            scheme=data.get("scheme", "https"),
            allow_prefixes=list(data["allow_prefixes"]),
            doc_extensions={e.lower().lstrip(".") for e in data["doc_extensions"]},
            years=[int(y) for y in data.get("years", [])],
            seeds=seeds,
        )

    def absolute(self, url: str) -> str:
        return urljoin(f"{self.scheme}://{self.host}/", url)

    def in_scope(self, url: str) -> bool:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False
        if p.netloc.lower() != self.host.lower():
            return False
        return any(p.path.startswith(prefix) for prefix in self.allow_prefixes)

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
                 max_pages: int, timeout: int):
        self.cfg = cfg
        self.out_dir = out_dir
        self.manifest = manifest
        self.delay = delay
        self.dry_run = dry_run
        self.years = years
        self.max_pages = max_pages
        self.timeout = timeout
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

    def download(self, url: str, category: str) -> None:
        if url in self.seen_docs:
            return
        self.seen_docs.add(url)

        if not self.year_allowed(url):
            return

        dest = self.dest_path(url, category)
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
            log(f"  [dry-run] {url}\n            -> {dest.relative_to(ROOT)}")
            self.stats["documenti_nuovi"] += 1
            return

        r = self._get(url, stream=True)
        if r is None:
            return

        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        size = 0
        with tmp.open("wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 16):
                if chunk:
                    fh.write(chunk)
                    size += len(chunk)
        tmp.replace(dest)

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
        log(f"== SEED [{seed.category}] {start}")
        queue: deque[tuple[str, int]] = deque([(start, 0)])
        pages_here = 0

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
            links: list[str] = []
            for raw in HREF_RE.findall(html):
                raw = raw.strip()
                if not raw or raw.lower().startswith(("mailto:", "javascript:", "tel:")):
                    continue
                links.append(urljoin(url, raw))

            docs = [l for l in links if self.cfg.is_document(l) and self.cfg.in_scope(l)]
            for d in docs:
                self.download(d.split("#")[0], seed.category)

            if depth < seed.depth:
                for l in links:
                    l = l.split("#")[0]
                    if l in self.visited_pages or self.cfg.is_document(l):
                        continue
                    if not self.cfg.in_scope(l):
                        continue
                    queue.append((l, depth + 1))

            time.sleep(self.delay)

    def run(self, seeds: list[Seed]) -> None:
        for seed in seeds:
            self.crawl_seed(seed)


# --------------------------------------------------------------------------- cli

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
    args = ap.parse_args()

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
                      years, args.max_pages, args.timeout)

    log(f"Host: {cfg.host} | seed: {len(seeds)} | anni: {sorted(years)} | "
        f"dry-run: {args.dry_run}")
    t0 = time.time()
    try:
        scraper.run(seeds)
    except KeyboardInterrupt:
        log("interrotto dall'utente")

    if not args.dry_run:
        manifest.rewrite_csv(args.manifest.with_suffix(".csv"))

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
    return 0


if __name__ == "__main__":
    sys.exit(main())
