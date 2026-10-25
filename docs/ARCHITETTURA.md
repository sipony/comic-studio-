# Architettura

```
Browser (Angular)  ──HTTP /api/*──▶  Backend FastAPI (Python)  ──HTTP + WebSocket──▶  ComfyUI
        ▲                                   │                                         (stesso PC)
        └────────── WebSocket /api/eventi ◀─┘──▶ kohya sd-scripts (PR 4), file dei progetti
```

Il backend è l'unico processo da avviare: serve l'interfaccia compilata (`frontend/dist/comic-studio/browser`),
espone le API e comanda ComfyUI. Tutto ciò che dura più di un attimo è un **lavoro** in background.

## Cartelle

```
avvio.py, avvia.*         avvio multipiattaforma
backend/app/
  __main__.py             python -m app [--porta] [--host] [--no-browser]
  main.py                 rotte REST, WebSocket, interfaccia statica
  state.py                stato condiviso: impostazioni, connessione, ricerca, controllo del sistema
  settings.py             impostazioni JSON nella cartella dati
  projects.py             progetti e personaggi su disco
  jobs.py                 lavori in background, bus degli eventi
  diagnostica.py          controllo di hardware, componenti, aggiornamenti, consigli
  modelinfo.py            famiglia e precisione dei modelli dall'intestazione dei file
  workflows.py            conversione UI→API, analisi dei ruoli, applicazione dei valori, workflow integrato
  dataset.py              Step 1: libreria dei workflow, configurazione, varianti, immagini
  somiglianza.py          CLIP in ONNX (o metodo semplice) e scelta delle immagini
  rotte_dataset.py        API e lavori dello Step 1
  didascalie.py           Step 2: tagger WD14, composizione delle didascalie, esportazione
  rotte_didascalie.py     API e lavori dello Step 2
  addestramento.py        Step 3: kohya (installazione, comando, lettura dell'uscita), parametri, epoche
  rotte_addestramento.py  API e lavori dello Step 3
  fumetto.py              Step 4: pagine e vignette, workflow delle scene, balloon, tavole, PDF, storia da testo
  rotte_fumetto.py        API e lavori dello Step 4
  comfy/discovery.py      ricerca delle installazioni di ComfyUI
  comfy/avvio.py          avvio e arresto di ComfyUI (comando per tipo di installazione, registro, PID)
  comfy/client.py         client asincrono per l'API di ComfyUI
backend/tests/            pytest; finto_comfy.py simula ComfyUI (HTTP + WebSocket)
frontend/src/app/
  core/                   servizi: api, eventi (WebSocket), progetto, avvisi; tipi condivisi
  shell/console.*         console in basso con avanzamento
  pagine/                 sistema, progetti, progetto (contenitore), personaggi, dataset, in-arrivo
  pagine/dataset/         sezione-workflow, sezione-prompt, sezione-genera, galleria
  pagine/didascalie/      Step 2
  shell/scelta-personaggio  selettore del personaggio comune agli step
  pagine/addestramento/   Step 3 e grafico della loss
  pagine/fumetto/         Step 4
docs/                     questa documentazione
```

## Dati su disco

```
~/ComicStudio/                       (COMIC_STUDIO_HOME)
  impostazioni.json                  comfy_url, comfy_dir, cartella_progetti, ultimo_progetto,
                                     avvio_automatico, argomenti_comfy, comando_comfy, attesa_avvio
  comfyui.log                        uscita del ComfyUI avviato da Comic Studio
  comfyui.pid                        PID (e ora di creazione) del ComfyUI avviato da Comic Studio
  strumenti/sd-scripts/              kohya sd-scripts con il suo venv
  progetti/
    <id-progetto>/
      progetto.json                  nome, descrizione, personaggi[]
      workflows/<id>.json            libreria dei workflow (formato API + ruoli)
      personaggi/<id>/riferimento.png
      personaggi/<id>/dataset/
        config.json                  workflow, ruoli, prompt, varianti, parametri dei nodi, quantità
        immagini.json                variante, prompt, seme, stato (tenuta/scartata), punteggio
        generate/0001.png …          immagini generate
        anteprime/0001.jpg …         miniature
      personaggi/<id>/didascalie/
        config.json                  fonte dei tag, soglia, tag tolti/aggiunti/sostituiti, massimo
        tag.json                     tag del tagger con probabilità, per immagine
        manuali.json                 didascalie scritte a mano
      personaggi/<id>/addestramento/
        config.json  stato.json      parametri / LoRA scelto, esito, test delle epoche
        loss.json                    punti [passo, loss]
        dataset/  dataset.toml       immagini + .txt esportati per kohya
        uscita/                      epoche: <trigger>-000001.safetensors … <trigger>.safetensors
        test/                        immagini di prova delle epoche
        comando.txt                  il comando di kohya usato
      fumetto/
        fumetto.json                 impostazioni, pagine, vignette, dialoghi
        immagini.json                versioni generate di ogni vignetta e quella scelta
        vignette/*.png               immagini generate
  modelli/                           CLIP per la somiglianza e tagger WD14 (scaricati al primo uso)
    .cestino/                        progetti e personaggi eliminati
```

## API REST

| Metodo | Percorso | Cosa fa |
| --- | --- | --- |
| GET | `/api/sistema` | versione, impostazioni, stato ComfyUI, installazioni trovate, ultimo controllo |
| POST | `/api/comfy/cerca` | avvia la ricerca di ComfyUI (lavoro) |
| POST | `/api/comfy/usa` | `{url, cartella}` imposta l'installazione da usare |
| GET | `/api/comfy/stato` | ricontrolla la connessione (con `in_avvio`, `avviato_da_noi`, `pid`) |
| POST | `/api/comfy/avvia` | si aggancia se è attivo, altrimenti avvia ComfyUI e aspetta che sia pronto (lavoro) |
| POST | `/api/comfy/riavvia` | ferma e riavvia il ComfyUI avviato da Comic Studio (lavoro) |
| POST | `/api/comfy/ferma` | ferma il ComfyUI avviato da Comic Studio (lavoro; 409 se l'ha aperto l'utente) |
| POST | `/api/comfy/avvio` | `{avvio_automatico, argomenti_comfy, comando_comfy, attesa_avvio}` |
| GET | `/api/comfy/modelli` | checkpoint, LoRA, VAE, ControlNet, CLIP Vision, IPAdapter, upscaler |
| GET / POST | `/api/diagnostica` | ultimo controllo del sistema / avvia un controllo (`?rete=false` senza aggiornamenti) |
| GET / POST | `/api/progetti` | elenco / crea `{nome, descrizione}` |
| GET / PATCH / DELETE | `/api/progetti/{id}` | leggi / modifica / sposta nel cestino |
| POST | `/api/progetti/{id}/personaggi` | `{nome, trigger?, genere, descrizione}` |
| PATCH / DELETE | `/api/progetti/{id}/personaggi/{pid}` | modifica / elimina |
| PUT / GET | `/api/progetti/{id}/personaggi/{pid}/riferimento` | carica (multipart `file`) / scarica l'immagine |
| GET | `/api/trigger/suggerisci?nome=&progetto=` | trigger word inventata e libera |
| GET / POST | `/api/progetti/{id}/workflows` | libreria / carica un workflow (multipart `file`, `nome`) |
| POST | `/api/progetti/{id}/workflows/integrato` | crea il workflow integrato SDXL + IPAdapter |
| GET / PATCH / DELETE | `/api/progetti/{id}/workflows/{wid}` | dettaglio con analisi / nome e ruoli / elimina |
| GET | `/api/progetti/{id}/workflows/{wid}/scarica` | il workflow in formato API |
| GET | `/api/progetti/{id}/personaggi/{pid}/dataset` | configurazione e riepilogo |
| PUT | `…/dataset/config` | salva la configurazione |
| POST | `…/dataset/esempi` | esempi dei prompt che verranno generati |
| POST | `…/dataset/genera` | `{quantita, sostituisci}` avvia la generazione (lavoro GPU) |
| GET | `…/dataset/immagini` | elenco con metadati e stato |
| GET / PATCH | `…/dataset/immagini/{file}` | immagine (`?anteprima=true` per la miniatura) / `{stato}` |
| POST | `…/dataset/seleziona` | `{quante}` selezione automatica (lavoro) |
| POST | `…/dataset/elimina` | `{file: [...]}` o `{scartate: true}` nel cestino |
| GET | `…/didascalie` | configurazione, didascalie di ogni immagine, frequenze dei tag |
| PUT | `…/didascalie/config` | salva la configurazione e restituisce le didascalie ricalcolate |
| POST | `…/didascalie/analizza` | `{tutte}` tag automatici con WD14 (lavoro) |
| PUT / DELETE | `…/didascalie/immagini/{file}` | `{testo}` didascalia a mano / torna a quella automatica |
| GET | `…/didascalie/zip` | dataset con immagini e `.txt` |
| GET / POST | `/api/kohya` / `/api/kohya/installa` | stato del trainer / installa o aggiorna (`{reinstalla}`) |
| GET / PUT | `…/addestramento` / `…/addestramento/config` | parametri, epoche, loss, stato / salva i parametri |
| POST | `…/addestramento/preset` | `{preset}` applica un preset |
| POST | `…/addestramento/avvia` | avvia l'addestramento (lavoro GPU) |
| PUT | `…/addestramento/prompt-test` | prompt di prova delle epoche |
| POST | `…/addestramento/prova` | `{epoche}` prova le epoche con ComfyUI (lavoro GPU) |
| GET | `…/addestramento/test/{file}` | immagine di prova |
| POST | `…/addestramento/scegli` / `…/addestramento/esistente` | `{epoca}` LoRA finale / `{lora}` LoRA già esistente |
| GET / PUT | `/api/progetti/{id}/fumetto` | fumetto, versioni delle immagini, LoRA dei personaggi / salva il fumetto |
| POST | `…/fumetto/importa` | `{testo, sostituisci}` storia da testo |
| POST | `…/fumetto/genera` | `{vignette, stesso_seme}` genera (tutte le mancanti se `vignette` è nullo) |
| PUT | `…/fumetto/vignette/{vid}/scelta` | `{indice}` versione da usare |
| GET | `…/fumetto/immagini/{file}` | immagine di una vignetta |
| GET | `…/fumetto/pagine/{n}/anteprima?larghezza=` | tavola con i balloon (JPEG) |
| GET | `…/fumetto/esporta?formato=pdf\|zip` | tutte le tavole in PDF o PNG |
| GET | `/api/comfy/nodi?classi=A,B` | definizioni dei nodi (per l'editor dei parametri) |
| GET | `/api/lavori` | lavori recenti |
| POST | `/api/lavori/{id}/annulla` | annulla un lavoro |
| GET | `/api/log?n=500` | ultime righe della console |

Gli errori hanno sempre la forma `{"detail": "messaggio leggibile"}`.

## Eventi (WebSocket `/api/eventi`)

| `tipo` | Contenuto |
| --- | --- |
| `benvenuto` | stato di ComfyUI e lavori attivi, alla connessione |
| `log` | `livello` (debug, info, ok, avviso, errore), `msg`, `lavoro` |
| `lavoro` | `dati`: il lavoro intero quando cambia stato |
| `avanzamento` | `lavoro`, `progresso` (0-1), `testo` |
| `comfy` | stato della connessione (ogni 5 s) |
| `installazioni` | installazioni di ComfyUI trovate |
| `diagnostica` | nuovo rapporto del controllo del sistema |
| `dataset` | `progetto`, `personaggio`, `azione` (nuova, stato, elenco), `immagine` |
| `didascalie` | `progetto`, `personaggio`: tag analizzati, da ricaricare |
| `addestramento` | `punto` [passo, loss], `passo`, `totale`, `epoca`, `velocita`, `rimanente`; `epoche_cambiate`, `test` |
| `kohya` | trainer installato o aggiornato |
| `fumetto` | `progetto`, `vignetta`: nuova immagine generata |

## Lavori

`Gestore.avvia(tipo, titolo, funzione, esclusivo=False)` esegue `async def funzione(lavoro)`. Dentro:
`lavoro.log(msg, livello)`, `lavoro.avanza(0..1, testo)`, `lavoro.controlla()` nei cicli lunghi per
rispettare l'annullamento. Si può chiamare `log` e `avanza` anche da un thread. I lavori con `esclusivo=True`
(generazione, addestramento) usano la GPU uno alla volta.
