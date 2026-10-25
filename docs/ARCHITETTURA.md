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
  comfy/discovery.py      ricerca delle installazioni di ComfyUI
  comfy/client.py         client asincrono per l'API di ComfyUI
backend/tests/            pytest; finto_comfy.py simula ComfyUI (HTTP + WebSocket)
frontend/src/app/
  core/                   servizi: api, eventi (WebSocket), progetto, avvisi; tipi condivisi
  shell/console.*         console in basso con avanzamento
  pagine/                 sistema, progetti, progetto (contenitore), personaggi, in-arrivo
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
      personaggi/<id>/riferimento.png
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

## Lavori

`Gestore.avvia(tipo, titolo, funzione, esclusivo=False)` esegue `async def funzione(lavoro)`. Dentro:
`lavoro.log(msg, livello)`, `lavoro.avanza(0..1, testo)`, `lavoro.controlla()` nei cicli lunghi per
rispettare l'annullamento. Si può chiamare `log` e `avanza` anche da un thread. I lavori con `esclusivo=True`
(generazione, addestramento) usano la GPU uno alla volta.
