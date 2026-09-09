# conti-pubblici

Raccolta e analisi della documentazione di bilancio dello Stato pubblicata dalla
**Ragioneria Generale dello Stato** (RGS, `www.rgs.mef.gov.it`), esercizi
**2020-2026**.

Domanda di ricerca: **come vengono trattati i residui passivi delle amministrazioni
centrali**, e in particolare perche' l'Ispettorato Generale del Bilancio (IGB) per
alcune amministrazioni li porti in **economia** e per altre li **reiscriva** in
esercizi successivi.

## Stato del repository

| Componente | Stato |
|---|---|
| `scripts/scrape_rgs.py` | scritto, testato offline, **mai eseguito contro il sito**; eseguibile anche fuori dal repo |
| `config/seeds.yaml` | 19 seed su URL verificati tramite ricerca web |
| `docs/` | mappa dei documenti e nota metodologica |
| `data/raw/` | **vuoto** |
| ricognizione | eseguita il 2026-09-09: 2625 documenti individuati, 0 errori |

> **Perche' `data/raw/` e' vuoto.** La sessione in cui questo codice e' stato scritto
> gira dietro un proxy di egress che nega ogni host esterno (`rgs.mef.gov.it` risponde
> `403` al CONNECT, come qualsiasi altro dominio). Nessun PDF e' stato scaricato.
> Lo scraper va eseguito da una macchina con rete aperta.

## Uso

### Opzione A - repository completo (consigliata)

```bash
git clone https://github.com/mcaruso17/conti-pubblici.git
cd conti-pubblici
pip install -r requirements.txt
```

### Opzione B - solo lo script

`scripts/scrape_rgs.py` funziona anche da solo, copiato in una cartella qualsiasi:
porta dentro di se' una copia di `config/seeds.yaml` e crea `data/raw/` e
`data/manifest/` accanto a se stesso.

```powershell
# Windows PowerShell
py -3.13 -m pip install requests pyyaml
py -3.13 .\scrape_rgs.py --dry-run
```

Su Windows lo script accorcia automaticamente i percorsi oltre i 260 caratteri
(il file prende un nome breve derivato dall'URL, e il manifest conserva il legame
con l'URL originale). Per evitare del tutto il problema conviene lavorare da una
cartella corta, per esempio `C:\rgs`, non da `Downloads`.

### Comandi

```bash
# 1. Ricognizione: elenca i documenti e scrive l'inventario in CSV, senza scaricare
python3 scripts/scrape_rgs.py --dry-run --quiet-dry-run --report ricognizione.csv

# 2. Raccolta completa 2020-2026 (attesa: alcune centinaia di MB, ~1-2 ore con delay 1s)
python3 scripts/scrape_rgs.py

# 3. Sottoinsiemi
python3 scripts/scrape_rgs.py --only rendiconto --years 2022 2023 2024
python3 scripts/scrape_rgs.py --only circolari

# 4. Test della logica, senza rete
python3 scripts/test_scraper_offline.py
python3 scripts/test_crawl_simulato.py
```

A fine esecuzione lo scraper stampa la ripartizione dei documenti **per categoria e
per anno**: e' il controllo piu' rapido per accorgersi che un ramo del sito e' rimasto
scoperto. `--report` scrive lo stesso inventario in CSV (una riga per documento, con
categoria, anno, codice amministrazione e destinazione), utile per validare la
copertura senza rifare il crawling.

### Ricognizione del 2026-09-09

Prima esecuzione reale del `--dry-run`: **475 pagine visitate, 2625 documenti
individuati, 0 errori**. I seed sono corretti. Sono emersi due difetti, ora risolti:

- i sette seed delle circolari si annullavano a vicenda (l'indice 2020 linka gli altri
  anni, li marcava come gia' visitati e consumava da solo il tetto di 400 pagine);
- la cartella di destinazione dipendeva dal seed che trovava il file, non dal file:
  lo stesso PDF finiva in cartelle diverse a seconda del percorso di scoperta.

La cartella di destinazione di ogni documento si decide dal **suo** path
(`category_rules` in `config/seeds.yaml`), non dal seed che lo ha trovato: lo stesso PDF
finisce sempre nella stessa cartella, che sia stato raggiunto da un hub o dalla pagina
specifica.

Dopo ogni modifica a `config/seeds.yaml` va rigenerata la copia incorporata nello
script con `python3 scripts/embed_config.py` (i test falliscono se le due divergono).

Lo scraper e' **idempotente**: `data/manifest/manifest.jsonl` registra ogni URL
scaricato con sha256, dimensione, ETag e data. Rilanciandolo scarica solo il nuovo.
A fine run genera anche `data/manifest/manifest.csv` per ispezione rapida.

E' **discovery-based**: non costruisce URL per tentativi, parte dalle pagine indice di
`config/seeds.yaml` e segue i link che restano dentro i prefissi consentiti. Se RGS
riorganizza il sito, il crawler non si rompe silenziosamente: segnala gli URL falliti
nel riepilogo finale.

## Struttura dell'output

```
data/raw/
  rendiconto/conto_del_bilancio/<anno>/conti_consuntivi_per_unit_di_voto/CON_<anno>_<amm>-*.pdf
  rendiconto/conto_del_bilancio/<anno>/conti_consuntivi_piani_gestionali/*.pdf
  rendiconto/conto_del_patrimonio/<anno>/*.pdf
  bilancio_previsione/bilancio_finanziario/<anno>/*.pdf|xls
  gestione_bilancio/assestamento/<anno>/*
  gestione_bilancio/gestione_residui/*
  circolari/<anno>/*
data/manifest/manifest.jsonl
data/manifest/manifest.csv
```

`<amm>` e' il codice a tre cifre dell'amministrazione (000 = entrata, 020 = MEF, ecc.),
estratto dal nome file e riportato nel manifest: e' la chiave per confrontare il
trattamento dei residui tra ministeri.

## Documentazione

- [`docs/mappa_documenti.md`](docs/mappa_documenti.md) - quale documento contiene cosa,
  e in quale tabella si leggono residui, economie e reiscrizioni.
- [`docs/nota_metodologica_residui.md`](docs/nota_metodologica_residui.md) - il meccanismo
  contabile (perenzione, economie, fondi speciali di riassegnazione) e i limiti di
  quello che le fonti RGS possono effettivamente dimostrare.

## Avvertenze

- I PDF scaricati **non sono versionati** (vedi `.gitignore`): sono centinaia di MB e
  sono riproducibili dal manifest. Il manifest invece e' versionato ed e' la prova di
  cosa e' stato raccolto e quando.
- I documenti sono atti pubblici del MEF. Lo scraper usa un delay di 1 secondo tra
  richieste e uno User-Agent identificabile. Non alzare la frequenza.
