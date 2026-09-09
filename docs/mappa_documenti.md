# Mappa dei documenti RGS utili alla domanda sui residui

Ordine di priorita' rispetto alla domanda "perche' per alcune amministrazioni i residui
finiscono in economia e per altre vengono reiscritti".

## 1. Rendiconto - Conto del bilancio (fonte primaria)

`/VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/rendiconto/conto_del_bilancio_e_conto_del_patrimonio/conto_del_bilancio/`

Documenti per anno, sotto `_Documenti/.../conto_del_bilancio/<anno>/`:

| Sottocartella | Contenuto | Perche' serve |
|---|---|---|
| `conti_consuntivi_per_unit_di_voto/` | `CON_<anno>_<amm>-<n>-<titolo>.pdf`, un file per amministrazione | E' **la tabella dei residui**: consistenza iniziale, pagati in conto residui, residui eliminati, residui finali, per unita' di voto |
| `conti_consuntivi_piani_gestionali/` | stesso dato al massimo dettaglio (capitolo / piano gestionale) | Permette di isolare i singoli capitoli su cui si concentrano economie o reiscrizioni |
| relazione illustrativa | `Relazione_illustrativa_completa_cdb_<anno>.pdf` | Testo RGS che commenta l'andamento dei residui e le eliminazioni dell'anno |
| allegati | allegati numerati al rendiconto | Contengono gli elenchi delle eliminazioni e delle riassegnazioni |

Il codice `<amm>` a tre cifre identifica il ministero (000 entrata, 020 MEF, ecc.):
e' la chiave di confronto tra amministrazioni.

**Cosa NON contengono**: la motivazione della singola scelta. Il conto consuntivo
mostra l'esito (importo andato in economia, importo reiscritto), non il perche'.

## 2. Legge di bilancio - stato di previsione del MEF

`/VERSIONE-I/attivita_istituzionali/formazione_e_gestione_del_bilancio/bilancio_di_previsione/bilancio_finanziario/`
(archivi per triennio: `BF_2024_2026/`, ecc.)

Il pezzo rilevante e' lo **stato di previsione del MEF**, dove sono iscritti i
**fondi speciali per la riassegnazione dei residui passivi perenti** (uno per la
spesa corrente, uno per il conto capitale). Lo stanziamento annuale di quei capitoli
e' il tetto materiale delle reiscrizioni possibili: se il fondo e' capiente si
reiscrive, se e' esaurito la richiesta slitta all'esercizio successivo.

Da leggere insieme al rendiconto: stanziamento del fondo (previsione) contro somme
effettivamente trasferite ai capitoli delle amministrazioni (consuntivo).

## 3. Assestamento e gestione dei residui

- `/VERSIONE-I/.../gestione_del_bilancio/assestamento_del_bilancio/` - in assestamento
  i **residui presunti** iscritti in bilancio a gennaio vengono sostituiti dai
  **residui accertati** dal rendiconto dell'anno precedente. Il delta per
  amministrazione e' un indicatore diretto di quanto viene rideterminato.
- `/VERSIONE-I/.../assestamento_del_bilancio/la_gestione_dei_residui/` - pagina RGS
  che descrive perenzione, economie e reiscrizione. E' lo snodo concettuale.

## 4. Circolari RGS (regole operative, per anno)

`/VERSIONE-I/circolari/<anno>/`

Tre famiglie contano:

1. **Chiusura dell'esercizio** (circolare di dicembre) - istruzioni agli Uffici
   centrali di bilancio su impegni, perenzione ed economie di fine anno.
2. **Formazione del rendiconto** (circolare di primavera) - come le amministrazioni
   devono classificare residui eliminati ed economie.
3. **Riaccertamento dei residui passivi** - la verifica annuale delle partite debitorie.

Sono il documento che spiega **le regole** con cui l'IGB decide. Se esiste una
discrezionalita' per amministrazione, e' qui che si vede il margine.

## 5. Fonti fuori RGS che servono comunque

Lo scraper non le copre. Vanno aggiunte se si vuole rispondere alla domanda sul
*perche'*, non solo sul *quanto*:

- **Corte dei conti, Giudizio di parificazione del rendiconto** (`corteconti.it`) -
  ogni anno dedica un capitolo ai residui, con analisi per ministero e rilievi espliciti
  sulle amministrazioni che accumulano perenzioni o economie anomale. E' la fonte che
  piu' si avvicina a una spiegazione delle differenze tra amministrazioni.
- **Decreti MEF di reiscrizione dei residui perenti** - registrati dalla Corte dei conti,
  pubblicati in modo frammentario. Sono l'atto puntuale che dispone la reiscrizione.
- **OpenBDAP / Bilancio Aperto** (`openbdap.rgs.mef.gov.it`, `bilancio-aperto`) - gli
  stessi dati in formato strutturato. **Se i dataset per capitolo con le colonne dei
  residui sono disponibili in CSV, vanno preferiti ai PDF**: il parsing dei conti
  consuntivi in PDF e' fragile e lungo, un CSV rende l'analisi immediata. Da verificare
  come primo passo dopo lo scraping.
- **Documenti parlamentari** (`parlamento.it`, Servizio Bilancio) - dossier sui disegni
  di legge di rendiconto e assestamento, spesso con tabelle per ministero gia' pronte.


---

# Diagnosi del 2026-09-09: perche' mancano gli anni precedenti

`scripts/diagnose_page.py --preset` ha chiarito il comportamento del sito. Non e'
un problema di JavaScript: e' che **ogni sezione pubblica solo l'anno corrente e non
linka gli anni precedenti**.

| Pagina | Documenti esposti | Anno |
|---|---|---|
| `bilancio_finanziario/` | 47 | solo 2026-2028 |
| `note_integrative_al_bilancio_di_previsione/` | 17 | solo 2026-2028 |
| `conto_del_bilancio/` | 25 | solo 2025 |
| `conto_generale_del_patrimonio/` | 1 | solo 2025 |
| `assestamento_del_bilancio/` | 2 | solo 2026 |
| `la_gestione_dei_residui/` | 0 | pagina di solo testo |

Le "pagine seguibili" trovate su ciascuna sono tutte navigazione laterale del sito,
non archivi. Un crawler che segue i link non puo' arrivare agli anni vecchi: non
esiste un link da seguire. Gli archivi esistono (per esempio
`bilancio_finanziario/BF_2024_2026/index.html`) ma vanno indirizzati direttamente.

Da qui `scripts/probe_archivi.py`: prova una lista di schemi di URL plausibili anno
per anno e riporta quali rispondono 200. Lo schema verificato diventa un seed
esplicito in `config/seeds.yaml`. La regola resta quella di partenza: **il crawler
non tira a indovinare, la sonda verifica una volta sola e il risultato si scrive nella
configurazione.**

## Altre cose emerse dalla diagnostica

- `la_gestione_dei_residui` non ha allegati: 0 documenti non e' un difetto, il
  contenuto e' il testo. Ora il seed ha `save_html: true` e salva la pagina.
- Erano linkate ma nessun seed le raggiungeva, ora aggiunte:
  `decreti_di_variazione` (i decreti che dispongono le reiscrizioni dai fondi
  speciali: l'atto piu' vicino a una risposta sul "perche'"),
  `note_integrative_a_consuntivo` (dove ogni amministrazione commenta a parole la
  propria gestione), `il_patrimonio_dello_stato`.
- `/VERSIONE-I/archivio/index.html` esiste ed era scartato dai prefissi: ora e'
  consentito, e la sonda verifica se e' l'indice degli archivi.
- Fra i link scartati compaiono `openbdap.rgs.mef.gov.it` e
  `bdap-opendata.rgs.mef.gov.it`. Confermano che gli stessi dati esistono in forma
  strutturata. Vanno guardati prima di impegnarsi nel parsing di migliaia di PDF.


---

# Il sito risponde 200 a tutto (soft-404)

Scoperto il 2026-09-09 con la prima versione di `probe_archivi.py`, che sondava
~170 URL di archivio e ne dava **100% esistenti**, in ogni sezione e ogni anno.

Fra i "trovati" c'era
`.../conto_del_bilancio/2026/conti_consuntivi_per_unit_di_voto/CON_2026_020-6-Finanziario.pdf`,
cioe' il rendiconto dell'esercizio 2026, che sara' pubblicato nel 2027. Non puo'
esistere. La sonda era sbagliata: **su questo sito lo stato HTTP non dice nulla**,
perche' agli URL inesistenti viene servita una pagina di cortesia con codice 200
invece di un 404.

Due conseguenze, entrambe gia' applicate al codice.

**1. La sonda verifica il contenuto, non lo stato.** Due controlli indipendenti:

- *controllo cieco*: ogni schema viene provato anche con l'anno 1899. Se la pagina
  dell'anno vero ha lo stesso contenuto di quella del 1899, e' la stessa pagina di
  cortesia;
- *prova di utilita'*: un archivio del 2022 serve solo se linka documenti il cui
  path contiene 2022. Zero documenti dell'anno, archivio inutile comunque sia.

Per i documenti si guardano i byte iniziali (`%PDF`, `PK`, `\xd0\xcf`) e il
Content-Type: se arriva HTML, e' cortesia travestita.

**2. Lo scraper valida ogni file scaricato.** Senza questo controllo un link rotto
avrebbe salvato una pagina HTML dentro un file `.pdf`, e il difetto sarebbe emerso
mesi dopo, in fase di parsing, su un archivio ormai grande. Ora il file viene
scartato e l'URL finisce fra gli errori del riepilogo.

La lezione vale oltre questo progetto: quando una verifica dice che **tutto**
esiste, la verifica e' rotta, non il mondo.
