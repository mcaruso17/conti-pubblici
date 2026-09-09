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
