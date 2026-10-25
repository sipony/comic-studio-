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
  comfy/discovery.py      ricerca delle installazioni di ComfyUI
  comfy/client.py         client asincrono per l'API di ComfyUI
backend/tests/            pytest; finto_comfy.py simula ComfyUI (HTTP + WebSocket)
frontend/src/app/
  core/                   servizi: api, eventi (WebSocket), progetto, avvisi; tipi condivisi
  shell/console.*         console in basso con avanzamento
  pagine/                 sistema, progetti, progetto (contenitore), personaggi, dataset, in-arrivo
  pagine/dataset/         sezione-workflow, sezione-prompt, sezione-genera, galleria
docs/                     questa documentazione
```

## Dati su disco

```
~/ComicStudio/                       (COMIC_STUDIO_HOME)
  impostazioni.json                  comfy_url, comfy_dir, cartella_progetti, ultimo_progetto
  strumenti/sd-scripts/              kohya (PR 4)
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
  modelli/                           modello CLIP per la somiglianza (scaricato al primo uso)
    .cestino/                        progetti e personaggi eliminati
```

## API REST

| Metodo | Percorso | Cosa fa |
| --- | --- | --- |
| GET | `/api/sistema` | versione, impostazioni, stato ComfyUI, installazioni trovate, ultimo controllo |
| POST | `/api/comfy/cerca` | avvia la ricerca di ComfyUI (lavoro) |
| POST | `/api/comfy/usa` | `{url, cartella}` imposta l'installazione da usare |
| GET | `/api/comfy/stato` | ricontrolla la connessione |
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

## Lavori

`Gestore.avvia(tipo, titolo, funzione, esclusivo=False)` esegue `async def funzione(lavoro)`. Dentro:
`lavoro.log(msg, livello)`, `lavoro.avanza(0..1, testo)`, `lavoro.controlla()` nei cicli lunghi per
rispettare l'annullamento. Si può chiamare `log` e `avanza` anche da un thread. I lavori con `esclusivo=True`
(generazione, addestramento) usano la GPU uno alla volta.
