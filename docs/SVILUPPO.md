# Sviluppo di Comic Studio

Diario e roadmap del progetto. Si aggiorna a ogni PR: cosa è stato fatto, cosa manca, perché si è scelto così.

## Obiettivo

Un programma con interfaccia grafica, per Windows, macOS e Linux, che porta da alcune immagini di riferimento
a un fumetto con personaggi coerenti, comandando ComfyUI e un trainer di LoRA. Il flusso è a step, con
la massima libertà su workflow, modelli e parametri, una console con tutti i log e barre di avanzamento.

## Roadmap

| PR | Contenuto | Stato |
| --- | --- | --- |
| 1 | Base: backend, interfaccia, progetti e personaggi, ricerca automatica di ComfyUI, controllo del sistema, console e avanzamento, avvio multipiattaforma, CI | ✅ unita |
| 2 | Step 1 Dataset: caricamento e analisi dei workflow (formato UI e API), associazione dei nodi, varianti, generazione con avanzamento, galleria, selezione automatica per somiglianza | ✅ unita |
| 3 | Step 2 Didascalie: tagger WD14, trigger word, tabella delle frequenze dei tag, modifica per immagine | ✅ unita |
| 4 | Step 3 Addestramento: installazione di kohya sd-scripts, preset per VRAM, parametri avanzati, log e grafico della loss, test delle epoche, scelta del LoRA | ✅ unita |
| 5 | Step 4 Fumetto: storia per pagine e vignette, scene con più personaggi (LoRA per zona), balloon, tavole, PDF | ✅ unita |
| 6 | Avvio di ComfyUI da Comic Studio: aggancio se è già attivo, altrimenti avvio automatico (portable, Desktop, manuale o comando a mano), uscita nella console, Avvia / Riavvia / Ferma | ✅ unita |
| 7 | Installer per Windows, macOS e Linux: doppio clic, senza terminale, con Python e interfaccia già dentro; chiusura dall'interfaccia | ✅ unita |
| 8 | Dal testo al prompt: IA locale (Ollama) che legge descrizioni lunghe di personaggi, vignette e storie intere e ne ricava prompt fedeli per il checkpoint; controllo di aderenza con il tagger | ✅ unita |
| 9 | Personaggio dal nulla: senza immagine, Comic Studio genera dalla descrizione alcune proposte di riferimento, l'utente sceglie (o chiede varianti) e la scelta diventa l'immagine di riferimento | ✅ unita |
| 10 | Indirizzi cliccabili nella console (ComfyUI si apre nel browser) e pulsanti «Apri ComfyUI» | ✅ unita |
| 11 | Annullamento in qualsiasi momento con le risorse liberate (coda di ComfyUI, VRAM, processi, IA) e anteprime dal vivo delle immagini in generazione | ✅ unita |
| 12 | Scelta del modello dell'IA: finestra che si apre quando manca Ollama o il modello, elenco dal registro di Ollama con le quantizzazioni, ordinato per la VRAM e la RAM del computer | ✅ unita |
| 13 | Dataset: pose e inquadrature diverse anche con i workflow img2img; Scarica (ZIP), Scarica e cancella, Elimina e Svuota il cestino per liberare spazio | ✅ unita |
| 14 | Staccare i nodi del workflow dall'interfaccia: Comic Studio ricollega il resto da solo, stacca a cascata i nodi che non possono più funzionare e spiega quando non si può | ✅ unita |
| 15 | IA locale: eliminare dall'interfaccia i modelli scaricati con Ollama; gestione del processo di Ollama (avvio all'apertura, riavvio se si chiude o si blocca, Avvia / Riavvia / Ferma) | ✅ unita |
| 16 | Personaggio dal nulla con più scelte (LoRA di stile, negativo, campionamento, anteprima del prompt) che passano da sole al dataset: stesso checkpoint, LoRA e stile, così il personaggio resta lo stesso | ✅ unita |
| 17 | IPAdapter Plus proposto all'apertura se manca (nodo e modelli), con il controllo dello spazio su disco, e installato da Comic Studio | ✅ questa PR |
| 18 | Pose guidate (ControlNet OpenPose) nelle scene di gruppo e costruttore di workflow: scelta di checkpoint (riconoscimento Pony / Illustrious / SDXL / Flux), LoRA, IPAdapter, ControlNet e di ogni parametro di ogni nodo | da fare |
| 19 | Aggiornamenti con un clic (ComfyUI, custom node, librerie) con conferma esplicita | da fare |

## Decisioni

**Perché un LoRA per personaggio e non solo IPAdapter.** Le prove fatte prima del programma (workflow ComfyUI
con IPAdapter, maschere regionali, style transfer) hanno mostrato che IPAdapter regge un personaggio alla
volta, ma con due personaggi e più IPAdapter impilati i tratti si mescolano (età, corporatura, colori) e lo
stile si appiattisce. Con un LoRA per personaggio il personaggio diventa una parola (trigger word) che il
modello conosce: volto, corporatura, vestiti e stile restano stabili in ogni vignetta.

**Dataset con un solo personaggio per immagine.** Per addestrare il LoRA ogni immagine del dataset deve
contenere solo quel personaggio, altrimenti il LoRA impara due persone mescolate. Le scene con più
personaggi si fanno nello Step 4, caricando i LoRA di tutti i presenti, ognuno applicato alla sua zona.

**Angular + FastAPI.** L'interfaccia è in Angular (scelta dell'utente: interfaccia ricca, usabile anche da un
altro computer della rete). Il lavoro vero è in Python, lo stesso linguaggio di ComfyUI e kohya. Il backend
serve l'interfaccia compilata, quindi per *usare* il programma basta Python; Node.js serve solo per compilarla.

**kohya sd-scripts come trainer.** Si comanda bene da programma (riga di comando, configurazione TOML), a
differenza di OneTrainer che è pensato per la sua interfaccia.

**Aggiornamenti: si segnalano, non si installano da soli.** Un aggiornamento di ComfyUI o di un custom node può
rompere i workflow: il programma li rileva e li mostra, l'installazione arriverà (PR 7) solo con conferma.

**Somiglianza con CLIP in ONNX, senza PyTorch.** Per scegliere le immagini più somiglianti al riferimento serve
un modello visivo. PyTorch peserebbe più di 2 GB solo per questo: si usa invece il modello visivo di CLIP ViT-B/32
quantizzato (circa 90 MB) con onnxruntime, scaricato la prima volta. Se non si può scaricare (offline) si usa un
metodo semplice su colori e forma, meno preciso, e lo si dice nella console. Lo stesso runtime servirà al tagger
WD14 dello Step 2.

**Il programma gestisce prompt, seme, dimensioni e riferimento; il resto del workflow resta tuo.** Ogni workflow
viene analizzato per trovare i nodi con questi ruoli (si possono correggere a mano). Tutti gli altri valori di
ogni nodo si possono cambiare per singolo personaggio senza toccare il file originale.

**Didascalie da due fonti.** Le immagini del dataset sono generate da noi, quindi conosciamo già il prompt di
ognuna: è una fonte di tag sempre disponibile e senza download. Il tagger WD14 aggiunge ciò che il modello ha
davvero disegnato (che non sempre coincide con il prompt). Per default si usano entrambe; i tag del tagger si
salvano con la loro probabilità, così cambiare la soglia non richiede di rianalizzare.

**I tratti fissi si tolgono dalle didascalie.** Ciò che non compare nella didascalia ma è sempre presente
nell'immagine viene assorbito dalla trigger word: per questo i tratti della descrizione del personaggio
(capelli, divisa…) vengono tolti in automatico e quelli dell'aspetto presenti in quasi tutte le immagini
vengono segnalati come «fisso?».

**kohya con un ambiente Python suo.** kohya vuole versioni precise di PyTorch e delle sue librerie (Python
3.10 consigliato, `torch==2.6.0` con CUDA 12.4): vive in `<cartella dati>/strumenti/sd-scripts` con il suo
`venv`, separato da quello del programma e da quello di ComfyUI, così nessuno rompe l'altro. Si lancia
`sdxl_train_network.py` direttamente (niente `accelerate config`), leggendo l'uscita riga per riga.

**La scelta dell'epoca si fa guardando, aiutati dal punteggio.** Il programma prova alcune epoche con gli stessi
prompt e semi e calcola la somiglianza al riferimento; consiglia la prima epoca quasi buona quanto la migliore,
perché le ultime tendono a «cuocere» il LoRA. La decisione finale resta a te.

**Scene di gruppo: composizione + ripasso.** Con più LoRA attivi insieme sull'intera immagine i personaggi si
mescolano. Ogni vignetta di gruppo si fa quindi in un solo workflow con due passaggi: prima la scena con tutti
i LoRA a forza ridotta e un prompt per zona (il primo personaggio a sinistra, poi gli altri), poi ogni zona
viene ridisegnata (inpainting, denoise ≈ 0,5) con il solo LoRA del suo personaggio e incollata con bordi sfumati.
Le pose guidate con ControlNet arriveranno nella PR 6.

**Immagini e testo separati.** La struttura del fumetto (pagine, vignette, dialoghi) e le immagini generate sono
salvate in file diversi: si può continuare a scrivere mentre il programma genera, senza sovrascriversi. Ogni
vignetta tiene tutte le versioni generate; la tavola usa quella scelta.

**Eliminazioni nel cestino.** Progetti e personaggi eliminati vengono spostati in `progetti/.cestino`.

## PR 1 — Base del programma

Fatto:

- **Backend FastAPI** (`backend/app`)
  - impostazioni in `~/ComicStudio/impostazioni.json` (`COMIC_STUDIO_HOME` per cambiarla)
  - progetti e personaggi su disco, con validazione della trigger word (3-24 caratteri, unica nel progetto,
    no parole che il modello conosce già) e suggerimento automatico; immagine di riferimento convertita in PNG
  - **ricerca di ComfyUI**: porte note (8188, 8000, …) con il percorso letto da `/system_stats`, processi
    attivi, configurazione di ComfyUI Desktop, cartelle tipiche di Windows / macOS / Linux; riconosce portable,
    Desktop e installazioni manuali; si avvia da sola al primo avvio e sceglie l'installazione migliore
  - **client ComfyUI** asincrono: stato, elenco modelli, caricamento immagini, esecuzione di un workflow con
    avanzamento via WebSocket e messaggi d'errore leggibili (pronto per lo Step 1)
  - **gestore dei lavori**: log, avanzamento, annullamento, lavori GPU uno alla volta; eventi a tutti i client
    via WebSocket `/api/eventi`
  - **controllo del sistema**: GPU/VRAM, RAM, disco; Python, Git, ComfyUI, custom node necessari (anche se
    presenti ma non caricati), modelli di supporto (IPAdapter, CLIP Vision, ControlNet); analisi dei
    checkpoint (famiglia Pony / Illustrious / NoobAI / SDXL / Flux e precisione letti dall'intestazione
    safetensors, GGUF); aggiornamenti disponibili (git di ComfyUI, dei custom node e del programma, ultima
    release di ComfyUI, librerie); consigli in base all'hardware (fp8 e impostazioni con 8 GB, GGUF per Flux,
    fp16 al posto di fp32, avvisi su RAM, disco, GPU di portatili, Mac)
- **Interfaccia Angular 22 + Material** (`frontend/`), tema scuro
  - barra in alto con lo stato di ComfyUI e della GPU; menu degli step
  - pagina **Sistema**: controllo completo e connessione (installazioni trovate, impostazioni manuali)
  - pagine **Progetti** e **Personaggi** (immagine di riferimento trascinabile, trigger word, tratti fissi)
  - **console** sempre visibile: filtri (normale / problemi / dettagli), ricerca, copia, ridimensionabile,
    con il lavoro in corso, la sua barra di avanzamento e il pulsante per annullarlo
  - segnaposto degli step 1-4 con la descrizione di cosa faranno
- **Avvio** `avvia.bat` / `avvia.command` / `avvia.sh` → `avvio.py`: crea l'ambiente Python, installa e
  aggiorna le librerie (una volta al giorno), compila l'interfaccia se manca o è cambiata, avvia e apre il browser
- **CI GitHub Actions**: test del backend su Windows, macOS e Linux, build e test dell'interfaccia, pacchetto
  `comic-studio-pronto` già compilato a ogni push su `main`
- **Sicurezza**: il server ascolta solo su questo computer e accetta solo richieste indirizzate a `localhost`
  (protezione dal DNS rebinding); `--host 0.0.0.0` lo apre alla rete, con un avviso
- **Test**: 30 test backend (ricerca, progetti, lavori, client ComfyUI contro un ComfyUI simulato, API,
  WebSocket, controllo del sistema, aggiornamenti git, host non consentiti), 4 test dell'interfaccia; collaudo dell'interfaccia
  con Playwright su desktop e telefono

Non ancora verificato: il programma non è stato provato su una GPU vera né con un ComfyUI reale, solo con
un ComfyUI simulato che risponde come l'API vera.

## PR 2 — Step 1 Dataset

Fatto:

- **Libreria dei workflow del progetto** (`backend/app/workflows.py`, `dataset.py`)
  - si carica il file salvato normalmente da ComfyUI (convertito nel formato API usando le definizioni dei
    nodi di ComfyUI: widget, `control_after_generate`, Reroute, nodi Primitive, nodi in bypass o disattivati,
    note) oppure quello esportato con «Export (API)»; nodi mancanti e subgraph sono segnalati con un messaggio chiaro
  - **workflow integrato** SDXL + IPAdapter, creato da un modulo con i modelli presenti in ComfyUI
  - **analisi automatica dei ruoli**: immagine di riferimento (il LoadImage che va all'IPAdapter), prompt
    positivo e negativo (risalendo dal sampler), seme, dimensioni, nodo finale; correggibili a mano
- **Configurazione per personaggio**, salvata da sola mentre la modifichi
  - modello di prompt con segnaposto (`{qualita}`, `{genere}`, `{descrizione}`, `{variante}`, …) e tag di
    qualità automatici in base al checkpoint (Pony `score_9…`, Illustrious `masterpiece…`, …)
  - **varianti**: inquadrature con dimensioni e quota, angolazioni, espressioni, pose, sfondi; esempi dei
    prompt che verranno generati
  - **parametri dei nodi**: qualunque valore di qualunque nodo, modificabile solo per quel personaggio
- **Generazione** come lavoro GPU: carica il riferimento in ComfyUI, crea ogni immagine con la sua variante e
  un seme nuovo, avanzamento per passo del sampler e per immagine, tempo rimanente, si ferma quando vuoi
  (interrompendo anche ComfyUI); «Genera altre» continua la numerazione, «Rifai da capo» sposta tutto nel cestino
- **Galleria** in tempo reale: filtri (tenute, da decidere, scartate), ordine per somiglianza, anteprime,
  ingrandimento con prompt e seme, tasti T / S per tenere o scartare e frecce per scorrere
- **Selezione automatica** (`somiglianza.py`): punteggio di somiglianza al riferimento con CLIP, quote per
  inquadratura, esclusione dei quasi-doppioni; le scelte fatte a mano restano
- **Test**: 47 test backend (conversione UI→API con link nei due formati, analisi su un workflow reale a 4
  vignette, applicazione dei valori, varianti e quote, selezione, valutatore ONNX con un modello di prova, flusso
  completo via API contro il ComfyUI simulato); collaudo dell'interfaccia con Playwright

Non ancora verificato: la qualità della selezione con il modello CLIP vero (qui non si può scaricare) e la
generazione su un ComfyUI reale.

## PR 3 — Step 2 Didascalie

Fatto:

- **Tagger WD14** in ONNX (`backend/app/didascalie.py`): `wd-vit-tagger-v3` scaricato al primo uso, stessa
  preparazione dell'immagine dell'originale (quadrato bianco, 448 px, BGR); salva i tag con probabilità ≥ 0,2
- **Didascalie automatiche**: `trigger, 1girl/1boy, solo, [tag sempre presenti], tag dell'immagine, [tag di stile]`
  - fonti: tagger, prompt di generazione o entrambe; soglia di sicurezza regolabile
  - tolti in automatico i tratti fissi della descrizione; tag da togliere, sostituzioni, numero massimo di tag
  - usa le immagini tenute nello Step 1 (se non ne hai scelta nessuna, tutte tranne le scartate, con avviso)
- **Tabella dei tag del dataset**: quante immagini hanno ogni tag, clic per toglierlo o rimetterlo in tutte,
  sostituzione, filtro «suggeriti» (tratti dell'aspetto presenti in almeno il 70% delle immagini) e
  «Togli i suggeriti» con un clic
- **Modifica a mano** di ogni didascalia accanto alla sua immagine, con ritorno a quella automatica
- **Scarica il dataset**: zip con immagini e `.txt`, utilizzabile con qualunque trainer (anche online);
  `esporta()` prepara la stessa cartella per lo Step 3
- Il selettore del personaggio è ora un componente comune (Dataset e Didascalie)
- **Test**: 54 test backend (tagger ONNX con un modello di prova, composizione, frequenze e suggerimenti,
  scritte a mano, esportazione e zip, flusso via API); collaudo dell'interfaccia con Playwright

Non ancora verificato: il tagger vero (da qui non si può scaricare).

## PR 4 — Step 3 Addestramento

Fatto:

- **Installazione di kohya sd-scripts con un clic** (`backend/app/addestramento.py`, `rotte_addestramento.py`):
  clona il repository (o scarica lo zip se Git manca), crea l'ambiente con un Python 3.10-3.12, installa
  PyTorch 2.6 adatto alla macchina (CUDA 12.4 con NVIDIA, MPS su Mac, CPU altrimenti) e le librerie; verifica
  che PyTorch veda la GPU. Pulsanti per aggiornare e reinstallare
- **Parametri** con preset scelto in base alla VRAM: «8 GB sicuro» (fp8, rank 16, Adafactor, solo UNet, cache del
  text encoder), «Equilibrato», «Qualità»; tutti i parametri avanzati (alpha, learning rate, ottimizzatore,
  scheduler, warmup, risoluzione, batch, ripetizioni, min SNR, noise offset, text encoder, mescola tag, argomenti
  extra); conto dei passi immagini × ripetizioni × epoche
- **Addestramento** come lavoro GPU: esporta il dataset con le didascalie, fa liberare la memoria a ComfyUI, lancia
  kohya e legge in diretta passo, epoca, velocità, tempo rimanente e loss (anche le righe di tqdm con `\r`);
  grafico della loss; si ferma terminando anche i processi figli; errori spiegati (memoria esaurita, librerie
  mancanti, GPU non vista, checkpoint rovinato); le epoche precedenti vanno nel cestino
- **Prova delle epoche** con ComfyUI: copia le epoche scelte in `models/loras/comic_studio`, genera i prompt di prova
  (modificabili) con gli stessi semi, punteggio di somiglianza e epoca consigliata; confronto affiancato
- **Scelta del LoRA finale**: copiato come `comic_studio/<trigger>.safetensors`, pronto per lo Step 4; oppure
  si usa un LoRA già esistente (per esempio addestrato online con lo zip dello Step 2)
- **Test**: 62 test backend (comando di kohya e preset, lettura dell'uscita reale di kohya, epoche, comandi di
  installazione, lettura dei processi anche nel modo di riserva per Windows, flusso completo con un kohya simulato: addestramento, errore di memoria, prova e scelta);
  collaudo dell'interfaccia con Playwright

Non ancora verificato: l'installazione e l'addestramento veri su Windows con la GPU dell'utente.

## PR 5 — Step 4 Fumetto

Fatto:

- **Pagine e vignette** (`backend/app/fumetto.py`, `rotte_fumetto.py`): formato larga / alta / quadrata, fino a 3
  personaggi per vignetta (ordinati da sinistra a destra), cosa succede, dialoghi e didascalie con posizione
  (automatica o in uno dei 4 angoli), seme fisso facoltativo; aggiunta, spostamento ed eliminazione di vignette e pagine
- **Storia da testo**: una vignetta per riga `formato | personaggi | azione | chi: battuta`, `---` per una nuova
  pagina; i personaggi per nome, id o trigger; errori riga per riga
- **Generazione** come lavoro GPU: una vignetta, «stesso seme» per correggere senza cambiare composizione, oppure
  tutte le mancanti; con il LoRA basta la trigger word, senza LoRA si usa la descrizione (con avviso);
  scene di gruppo con composizione regionale e ripasso per personaggio; tutte le versioni restano e si sceglie quale usare
- **Impostazioni del fumetto**: checkpoint, LoRA di stile, forza dei personaggi, ripasso, stile e negativo comuni
  con tag di qualità automatici, campionatore, font dei balloon, larghezza della tavola e margini
- **Tavole**: impaginazione automatica (due vignette alte di fila affiancate), balloon con coda verso chi parla,
  didascalie gialle del narratore, anteprima della tavola sempre aggiornata; **esportazione** in PDF e PNG (zip)
- **Test**: 67 test backend (workflow con 0, 1 e 3 personaggi, importazione della storia, impaginazione e balloon,
  PDF, flusso completo via API con versioni, stesso seme, anteprima ed esportazione); collaudo con Playwright

Non ancora verificato: la resa delle scene di gruppo su un ComfyUI vero (dipende dal checkpoint e dai LoRA).

Prossimo passo: PR 6, avvio di ComfyUI da Comic Studio.

## PR 6 — Avvio di ComfyUI

Richiesta: «voglio che sia il mio programma ad avviare ComfyUI, e se è già attivo che vi si agganci».

Fatto:

- **All'apertura** (`App.avvio` in `backend/app/state.py`): trova ComfyUI come prima; se risponde ci si aggancia,
  altrimenti, con l'avvio automatico attivo (predefinito), lo avvia e aspetta che sia pronto, poi fa il controllo
  del sistema. Se è aperto su un'altra porta lo riconosce dalla cartella (argv di `/system_stats`) e si aggancia lì
- **Comando giusto per ogni installazione** (`backend/app/comfy/avvio.py`):
  - portable: `python_embeded/python.exe -s ComfyUI/main.py --windows-standalone-build --port N`
  - manuale: il Python del suo `venv`/`.venv` (o quello di sistema) con `main.py --port N`
  - Desktop: l'app ComfyUI (Windows `%LOCALAPPDATA%\Programs\@comfyorgcomfyui-electron\ComfyUI.exe`, macOS `open -a ComfyUI`)
  - oppure un comando scritto a mano (es. il proprio `run_nvidia_gpu.bat`), più argomenti extra (`--lowvram`, …)
- **Processo staccato**: chiudere Comic Studio non chiude ComfyUI; il PID (con l'ora di creazione, contro il riuso
  dei PID) è salvato in `comfyui.pid`, così alla riapertura Comic Studio lo riconosce come suo e può ancora fermarlo
- **Uscita di ComfyUI nella console**: va in `~/ComicStudio/comfyui.log` e compare con il prefisso `ComfyUI ›`;
  avvisi e traceback colorati, il resto nei «Dettagli»
- **Errori spiegati**: se ComfyUI si chiude durante l'avvio, il messaggio dice perché (pacchetto mancante, porta
  occupata, PyTorch senza CUDA, memoria esaurita) leggendo le ultime righe; attesa massima regolabile (300 s)
- **Interfaccia**: Sistema → Connessione ha Avvia / Riavvia / Ferma, l'interruttore dell'avvio automatico,
  gli argomenti in più e, nelle opzioni avanzate, il comando personalizzato; il chip in alto mostra «in avvio…».
  Si può fermare solo un ComfyUI avviato da Comic Studio (quello aperto a mano si chiude dalla sua finestra)
- **API**: `POST /api/comfy/avvia`, `/ferma`, `/riavvia` (lavori), `POST /api/comfy/avvio` (impostazioni)
- **Test**: 77 test backend; un finto `main.py` vero e proprio (server HTTP) viene avviato, seguito nel registro,
  riavviato e fermato; aggancio a un ComfyUI già attivo; avvio automatico all'apertura e con l'opzione spenta;
  errore chiaro se ComfyUI si chiude subito; comandi per portable, manuale, Desktop e personalizzato

Non ancora verificato: l'avvio della portable e dell'app Desktop su un Windows vero.

Prossimo passo: PR 7, installer per Windows, macOS e Linux.


## PR 7 — Installer

Richiesta: «un installer su tutte le versioni così da non dover usare il terminale, né da Linux, né da Mac, né da
Windows 11».

Fatto:

- **`installer/costruisci.py`** costruisce tutto da Linux (anche per Windows e macOS, niente compilazione):
  - Python 3.12 completo da [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
    (versione e checksum fissati nello script), senza test, IDLE e Tk
  - librerie installate per la piattaforma di destinazione con `uv pip install --python-platform …`
    (i marcatori come `sys_platform` sono valutati per il sistema giusto, non per Linux)
  - su Windows anche le DLL del runtime Visual C++ (`msvc-runtime`), che servono a onnxruntime e non tutti i PC hanno
  - interfaccia già compilata, `.pyc` già pronti (avvio più rapido, nessuna scrittura nella cartella dell'app)
  - icona generata dal `favicon.svg` (PNG, ICO, ICNS)
- **Pacchetti** in `installer/dist/`:
  - Windows: `…-Windows-Setup.exe` (NSIS, in italiano, senza permessi di amministratore, in
    `%LOCALAPPDATA%\Programs\ComicStudio`); icone nel menu Start e sul desktop, voce in «App installate»
    con disinstallazione; chiude Comic Studio se è aperto prima di aggiornare o disinstallare
  - macOS: `Comic Studio.app` in uno zip, uno per Apple Silicon e uno per Intel (macOS 13+); zip che conserva
    permessi e collegamenti simbolici
  - Linux: AppImage (al primo avvio si aggiunge da solo al menu delle applicazioni) e `.deb` in `/opt/comic-studio`
  - `SHA256SUMS.txt`
- **Avvio senza terminale** (`backend/app/installato.py`): uscita in `ComicStudio/comicstudio.log`, errori
  all'avvio in una finestra del sistema, su Windows nessuna finestra nera per i comandi lanciati (git, pip, kohya),
  se è già aperto apre solo il browser, se la porta 8765 è occupata da un altro programma usa la successiva
- **Chiusura dall'interfaccia**: pulsante ⏻ in alto (`POST /api/esci`), con la scelta di chiudere anche ComfyUI;
  la pagina mostra «Comic Studio è chiuso» e si riattiva da sola alla riapertura
- **kohya** usa il Python incluso (3.12) per creare il suo ambiente: non serve installare Python neanche per
  l'addestramento; git resta facoltativo
- **Workflow `installer.yml`**: con un tag `v*` costruisce gli installer e li pubblica nella release
- Versione 0.7.0
- **Test**: 84 test backend (chiusura, avvio da installato con porta occupata, già aperto, errore all'avvio,
  integrazione AppImage nel menu, zip per macOS con permessi e collegamenti). Collaudo vero dei pacchetti:
  - AppImage e `.deb` installati e avviati su Ubuntu 24.04: interfaccia servita, chiusura con ⏻,
    disinstallazione pulita
  - installer Windows provato con Wine: installazione silenziosa, collegamenti, avvio con `pythonw.exe`
    (nessuna console), server e interfaccia funzionanti, kohya trova il `python.exe` incluso, disinstallazione
    che chiude l'app e rimuove i file lasciando i progetti

Non ancora verificato: l'app per macOS su un Mac vero (gli eseguibili arm64 risultano firmati dal linker, come
richiesto da macOS), e l'installer su un Windows 11 vero. Con Wine, numpy 2.5 si ferma su una funzione di
`ucrtbase` che Wine non ha (`crealf`); su Windows vero c'è.

Limiti: app non firmate (servono certificati a pagamento), quindi la prima apertura chiede conferma; le istruzioni
sono in `installer/NOTE_RILASCIO.md`.

Prossimo passo: PR 8, dal testo al prompt.

## PR 8 — Dal testo al prompt

Richiesta: «leggere una descrizione anche molto lunga per la scena e per la generazione iniziale dei personaggi,
e creare automaticamente dal linguaggio naturale un prompt attendibile e fedele».

Decisioni:

- **IA locale, non un servizio esterno**: Ollama gira sul computer dell'utente, gratis e senza mandare i testi in
  rete. Modello predefinito Qwen3 8B (circa 5 GB, buon italiano, contesto lungo); in alternativa Qwen3 4B o
  Gemma 3 12B, o qualsiasi server compatibile OpenAI (LM Studio, llama.cpp)
- **L'IA analizza, Comic Studio compone**: l'IA restituisce un JSON con schema fisso (soggetti con posizione,
  azione, posa, espressione, vestiti; interazione, inquadratura, ambiente, luce, atmosfera, oggetti, effetti,
  elementi chiave, negativo, frase in inglese, cose non disegnabili). Il prompt lo compone il codice, in modo
  prevedibile e nello stile del checkpoint: tag Danbooru per Pony / Illustrious / NoobAI / SD 1.5, frasi per
  Flux / SD3, tag + frase per SDXL. Gli elementi chiave pesano 1.15, quelli da rafforzare 1.3
- **I tratti dei personaggi con LoRA non si ripetono**: il LoRA li conosce; l'IA descrive solo cosa cambia nella
  scena, e ciascun personaggio riceve la sua parte nella sua zona (composizione regionale e ripasso)
- **GPU condivisa**: `keep_alive: 0` (Ollama scarica il modello appena risponde) e, prima di ogni domanda, ComfyUI
  libera la VRAM. Le analisi si fanno tutte prima di generare
- **Fedeltà**: l'istruzione dice di non ammorbidire violenza, sangue, gore e horror descritti e di non aggiungere
  nulla. Blocco fisso e non disattivabile: niente contenuto sessuale con minori o personaggi dall'aspetto infantile
  (parole nel testo + `adulto`/`sessuale` dell'analisi + `adulto` del personaggio); il testo esplicito non
  arriva nemmeno all'IA

Fatto:

- `backend/app/llm.py`: client Ollama / OpenAI con risposta JSON, download dei modelli in streaming, Ollama
  portatile (zip / tgz / tar.zst dalla release di GitHub, in `strumenti/ollama`, avviato con `ollama serve`)
- `backend/app/ia.py`: stato, installazione (dopo conferma), avvio, download del modello, domande con lock
- `backend/app/testo_prompt.py`: schemi e istruzioni, composizione per famiglia, blocco, aderenza, storia a pezzi
- `backend/app/rotte_testo.py`: `/api/ia` (stato, impostazioni, installa, modello, prova), tratti del personaggio,
  analisi della vignetta (rifatta solo se testo, personaggi o modello cambiano), prompt, storia → pagine
- Fumetto: `Vignetta.descrizione` / `analisi` / `rafforza`, `Versione.aderenza`; la generazione analizza prima,
  poi genera e controlla l'aderenza con il tagger WD14 (solo gli elementi che il tagger conosce)
- Personaggi: `storia` (descrizione libera, fino a 20 000 caratteri) e `adulto`; tratti fino a 1500 caratteri
- `GET /api/lavori/{id}` con il risultato del lavoro
- Interfaccia: scheda **IA locale** in Sistema, **Ricava i tratti** nei personaggi, descrizione della scena con
  prompt ricavato, aderenza e **Rafforza i mancanti** nel fumetto, **Racconto libero** nella storia da testo
- Versione 0.8.0; `zstandard` tra le librerie (archivio di Ollama per Linux)
- **Test**: 95 test backend; un Ollama finto (versione, modelli, pull in streaming, chat) per: stato e download
  del modello, tratti dal testo (con `keep_alive: 0` e schema), analisi della vignetta con personaggi trovati
  dall'IA e cache, generazione con prompt della scena e aderenza, storia intera, blocco (anche prima di chiedere
  all'IA), composizione per Illustrious / Flux / SDXL, archivi di Ollama per ogni sistema

Non ancora verificato: la qualità delle analisi con Qwen3 8B vero sui testi lunghi in italiano, e quanto spesso
il tagger riconosce gli elementi chiave.

Prossimo passo: PR 9, personaggio dal nulla.

## PR 9 — Personaggio dal nulla

Richiesta: «se non ho già un'immagine e voglio creare un personaggio dal nulla con un testo in linguaggio
naturale, come facciamo?».

Prima il dataset (Step 1) partiva sempre da un'immagine di riferimento caricata dall'utente. Ora la si può creare:

- **Crea dal testo** sotto l'immagine del personaggio apre il pannello delle proposte: checkpoint (preferito
  Illustrious / NoobAI / Pony / XL, come nel dataset), inquadratura (mezzo busto, figura intera, primo piano),
  quante (2-8), stile facoltativo
- se il personaggio ha solo la descrizione libera, il lavoro chiede prima all'IA i tratti fissi e li salva nel
  personaggio (tipo e «adulto» compresi), poi genera
- prompt: tag di qualità del checkpoint, tipo, `solo, looking at viewer, neutral expression, simple background,
  white background`, tratti, inquadratura, stile; negativo contro più persone, testo, mani sbagliate
- ogni proposta ha il suo seme; **Usa questa** la copia come `riferimento.png`; **Varianti** rifà img2img
  partendo da quella (denoise 0.55); **Togli le non scelte** le sposta nel cestino del progetto
- lavoro GPU esclusivo con avanzamento; il blocco fisso (minori e contenuti sessuali) vale anche qui
- `backend/app/proposte.py` (configurazione, prompt, workflow txt2img / img2img, archivio in
  `personaggi/<id>/proposte/`), `backend/app/rotte_proposte.py`; la lettura dei tratti è in comune con
  «Ricava i tratti» (`tratti_dal_testo`)
- Versione 0.9.0
- **Test**: 97 test backend; dal solo testo a 2 proposte (tratti ricavati e salvati, prompt, workflow), scelta del
  riferimento, varianti img2img, scarto nel cestino, errori senza descrizione e blocco

Prossimo passo: PR 10, indirizzi cliccabili.

## PR 10 — Indirizzi cliccabili

Richiesta: «dalla console, quando nei log c'è l'indirizzo IP dell'istanza, cliccandolo voglio che mi rimandi su
ComfyUI nel browser».

- `frontend/src/app/core/link.ts`: trova negli messaggi gli indirizzi `http(s)://…`, `ip:porta` e
  `localhost:porta` (togliendo la punteggiatura finale) e li divide dal testo, senza HTML; `0.0.0.0` diventa
  `127.0.0.1`; se Comic Studio è aperto da un altro computer della rete, gli indirizzi locali puntano all'host
  di Comic Studio
- console: gli indirizzi sono collegamenti che si aprono in una nuova scheda; quello di ComfyUI è in grassetto
  con il suggerimento «Apri ComfyUI nel browser» (vale anche per le righe `ComfyUI › To see the GUI go to: …`)
- pulsante «Apri ComfyUI» accanto al chip in alto e in Sistema → Connessione, quando è connesso
- Versione 0.10.0
- **Test**: 9 test dell'interfaccia (indirizzi nel testo, ip:porta senza schema, punteggiatura, 0.0.0.0,
  accesso da un altro computer, riconoscimento di ComfyUI); collaudo con Playwright: clic sull'indirizzo nella
  console → si apre ComfyUI

Prossimo passo: PR 11, annullamento e anteprime.

## PR 11 — Annullamento sicuro e anteprime dal vivo

Richieste: «prevedi l'annullamento in qualsiasi momento delle generazioni e che liberi correttamente le risorse
hardware» e «rendi visibili come anteprima le immagini generate».

Annullamento:

- `ComfyClient.esegui`: se il lavoro viene annullato (in attesa del WebSocket, durante l'invio, in qualsiasi
  punto) toglie dalla coda di ComfyUI i prompt di questo client, interrompe quello in corso solo se è suo
  (gli altri programmi che usano ComfyUI non vengono toccati) e chiama `/free` per scaricare i modelli dalla VRAM.
  La pulizia è protetta da un secondo annullamento (`asyncio.shield`). Prima ogni pagina chiamava `/interrupt`
  per conto suo, senza togliere i prompt in coda né liberare la memoria
- `Gestore`: un lavoro annullato mentre aspetta la GPU passa subito ad «annullato» (prima restava «in coda» per
  sempre); il secondo clic su «annulla» non interrompe la pulizia; `POST /api/lavori/annulla` annulla tutto;
  il lavoro dice `annullando` finché la pulizia non è finita, poi il registro conferma «memoria della GPU liberata»
- kohya: il processo e tutti i figli vengono chiusi e si aspetta che siano usciti (solo allora la VRAM è libera),
  senza bloccare il server
- IA: annullando una domanda il modello viene tolto subito dalla memoria (`keep_alive: 0`)
- un'esecuzione interrotta dall'interfaccia di ComfyUI ha ora un messaggio chiaro

Anteprime:

- ComfyUI manda anteprime binarie durante il campionamento (formati 1 e 4 del WebSocket): `leggi_anteprima` le
  legge e il lavoro tiene l'ultima (`GET /api/lavori/{id}/anteprima`, evento `anteprima` al massimo 3 volte al
  secondo); le immagini finite diventano anteprima anche senza anteprime di ComfyUI
- quando Comic Studio avvia ComfyUI aggiunge `--preview-method auto` (se l'utente non ha scelto altro)
- interfaccia: miniatura accanto alla barra della console, anteprima grande nella generazione del dataset, nel
  fumetto e nelle proposte del personaggio; clic per vederla a schermo intero (Esc per chiudere); pulsante
  «annulla tutti» quando i lavori sono più di uno
- Versione 0.11.0
- **Test**: 104 test backend; il finto ComfyUI ha ora una coda vera, `/interrupt`, `DELETE` dalla coda e
  anteprime: annullare un prompt in coda lo toglie senza toccare quello di un altro client, annullare quello in
  corso lo interrompe, la VRAM viene liberata; lavoro annullato in attesa della GPU; annulla tutti; kohya con
  un processo figlio; annullamento dall'API con anteprima e nuova generazione subito dopo; IA scaricata
  all'annullamento

Prossimo passo: PR 12, scelta del modello dell'IA.

## PR 12 — Scelta del modello dell'IA

Richiesta: «quando gli do la descrizione libera mi dice che non può generare i tag perché manca Ollama: devi aprire
un pop-up, fare una chiamata API su quali modelli sono disponibili, soprattutto quantizzati, e mostrare come
migliori quelli più adatti al sistema; poi li fai vedere tutti comunque».

Prima l'errore arrivava solo come messaggio e bisognava andare in Sistema → IA locale, dove c'erano tre modelli fissi.

Backend:

- `catalogo_ia.py`: elenco di partenza di famiglie adatte all'italiano e al JSON (Qwen3, Gemma 3, Mistral Small
  3.2, Qwen2.5, Llama 3.1 / 3.2, Mistral Nemo, Phi-4) con dimensioni e quantizzazioni; **Aggiorna da Ollama**
  (lavoro `ia_catalogo`) chiede al registro `registry.ollama.ai/v2/library/<famiglia>/tags/list` tutti i tag (se
  non risponde legge la pagina dei tag di ollama.com) e dal manifest di ognuno la dimensione vera; i tag corti
  (`qwen3:8b`) diventano alias della variante con lo stesso file; esclusi modelli base, `cloud` e `latest`.
  Il risultato resta in `strumenti/catalogo_ia.json` e va rinfrescato dopo una settimana. Si può aggiungere
  qualsiasi famiglia di Ollama per nome
- modelli già scaricati: da `/api/tags` di Ollama, con dimensione, parametri e quantizzazione veri (anche quelli
  scaricati a mano che non sono nel catalogo)
- valutazione: memoria che serve = file + contesto da 12k token + margine, confrontata con la VRAM (meno 0,5 GB;
  ComfyUI viene scaricato prima di ogni domanda), con il 67% della memoria unificata sui Mac e con la RAM.
  Esito: `gpu` (veloce), `misto` (in parte sulla CPU), `cpu` (nessuna GPU), `troppo`. Punteggio: qualità della
  famiglia + dimensione (logaritmica; i MoE contano come un modello denso un po' più piccolo) + quantizzazione
  (Q2/Q3 penalizzate, Q8 un po' meglio di Q4) − la parte che resta sulla CPU (meno per i MoE) − il peso del file
  quando gira solo sul processore; +0,5 se è già scaricato. I primi tre sono consigliati
- `POST /api/ia/scegli`: imposta il modello (riattiva Ollama se l'IA era disattivata) e, se serve, installa Ollama
  o scarica il modello
- `ErroreIA(non_pronta=True)` quando mancano Ollama, il modello o il server, o l'IA è disattivata: il lavoro ha
  `codice: "ia_non_pronta"` (anche nelle risposte HTTP 503), così l'interfaccia sa che deve aprire la finestra

Interfaccia:

- `shell/scelta-ia.*`: hardware, filtri **Adatti al mio computer** / **Tutti**, ricerca (e «Cerca su Ollama» per
  un nome nuovo), una riga per famiglia e dimensione con le quantizzazioni come pulsanti (dimensione, pallino del
  colore dell'esito, segno di spunta se scaricata), «il migliore per te» e «consigliato», legenda; in fondo il
  modello scelto con quanto pesa e dove girerà, e **Installa Ollama e scarica** / **Scarica e usa** / **Usa
  questo** con l'avanzamento e **Ferma**
- `core/scelta-ia.service.ts`: `pronta(motivo)` prima di Ricava i tratti, proposte del personaggio solo dalla
  descrizione libera, Trasforma in prompt e Storia → vignette; quando l'IA diventa pronta l'azione riparte. Si
  apre da sola anche quando un lavoro finisce con `ia_non_pronta` (es. la generazione delle vignette)
- Sistema → IA locale: «Scegli il modello adatto al tuo computer» e «Scegli e installa» quando l'IA non è pronta;
  `/sistema?scheda=ia` apre direttamente la scheda
- Versione 0.12.0
- **Test**: 110 test backend (tag e quantizzazioni, valutazione per RTX 3060 / 4060 / solo CPU / Mac, ordine del
  catalogo, alias dei modelli scaricati, registro finto con lista dei tag, manifest e pagina del sito, ricerca
  di una famiglia nuova, scelta con download, riattivazione dall'IA disattivata, codice `ia_non_pronta`);
  12 test dell'interfaccia; collaudo con Chromium: da «Ricava i tratti» senza modello → finestra → Scarica e
  usa → la finestra si chiude e i tratti compaiono

Prossimo passo: PR 13, pose diverse nel dataset e spazio su disco.

## PR 13 — Dataset: pose diverse e spazio su disco

Richiesta: «devi mettere un tasto per cancellare tutte le immagini generate da un dataset, mettere uno "scarica
tutte" e che vengano eliminate dal sistema così non occupano spazio; e poi non ho visto la generazione dello stesso
personaggio in posizioni diverse: puoi verificare e correggere».

**Perché le pose erano tutte uguali.** Il workflow dell'utente («Cala_Maranello_img2img») è img2img: LoadImage del
riferimento → VAEEncode → KSampler con denoise 0.55. Comic Studio cambiava il prompt di ogni variante (inquadratura,
angolazione, posa) ma il campionamento partiva sempre dall'immagine di riferimento, quindi composizione, posa e
inquadratura restavano le sue; e le dimensioni delle inquadrature non venivano applicate perché non c'era un
EmptyLatentImage. Il prompt diverso cambiava solo dettagli e colori.

Correzione:

- `workflows.img2img()`: riconosce i workflow in cui un campionatore (KSampler, KSamplerAdvanced, SamplerCustom)
  parte, anche attraverso nodi come LatentUpscale, da un VAEEncode dell'immagine di riferimento (un secondo
  passaggio che ricodifica l'uscita del primo non conta); `guide_identita()` trova IPAdapter, PuLID, InstantID…
- `ConfigDataset.composizione`: `libera` (predefinita) o `riferimento`. Con `libera`, `applica()` aggiunge un
  latente vuoto (`EmptyLatentImage`, `EmptySD3LatentImage` per Flux / SD3) con le dimensioni dell'inquadratura,
  ci collega il campionatore e mette il denoise a 1 (KSamplerAdvanced: dal primo passo con il rumore; SamplerCustom:
  denoise dello scheduler). LoRA, IPAdapter e il resto del workflow restano com'erano; il file salvato non cambia
- nel registro della generazione: cosa succede e un avviso se il workflow non ha né LoRA né IPAdapter (senza il
  riferimento il personaggio potrebbe non somigliare)
- interfaccia: nella sezione Workflow il riquadro «Workflow img2img: pose e inquadrature» spiega il problema, mostra
  da dove viene l'aspetto (es. Maranello_ViperRSR) e permette di scegliere «Pose dalle varianti» / «Come il riferimento»;
  il ruolo «Dimensioni» vuoto non è più un problema

Spazio su disco:

- galleria: pulsanti **Scarica** ed **Elimina** sempre visibili, che agiscono sul filtro scelto («tutte le 117
  immagini», «le 30 tenute»…), e lo spazio occupato accanto ai conteggi
- **Scarica → ZIP**: un lavoro prepara lo ZIP (`ZIP_STORED`, le PNG sono già compresse) con le immagini, il prompt di
  ognuna in un `.txt` e `immagini.json`; il browser lo scarica con l'avanzamento e lo ZIP viene tolto dal disco
- **Scarica → … e cancellale dal computer**: le immagini vengono cancellate solo quando lo ZIP è arrivato tutto nel
  browser (dimensione controllata), e solo quelle finite nello ZIP. Qui si cancella davvero, senza cestino: è
  l'eccezione alla regola del cestino, perché l'utente ne ha appena scaricato la copia e chiede di liberare spazio
- **Elimina**: sposta nel cestino come prima; il messaggio ha «Libera lo spazio», e **Svuota il cestino** (con il
  numero e il peso) cancella dal disco solo le immagini del dataset di questo personaggio
- `riepilogo` del dataset con `byte` e `cestino`
- Versione 0.13.0
- **Test**: 113 test backend (riconoscimento img2img con KSampler, KSamplerAdvanced e un secondo passaggio, latente
  per Flux, workflow integrato non toccato; generazione via API con ogni immagine da un latente vuoto delle
  dimensioni della sua inquadratura e scelta «come il riferimento»; ZIP con prompt e metadati, nomi non validi,
  cancellazione definitiva, cestino di un altro personaggio non toccato); 14 test dell'interfaccia; collaudo con
  Chromium: riquadro img2img, menu, «Scarica e cancellale» con ZIP salvato e galleria vuota, 100 immagini generate
  nelle 4 inquadrature

Prossimo passo: PR 14, nodi staccati.

## PR 14 — Staccare i nodi del workflow

Richiesta: «poter staccare un nodo disattivandolo a video senza compromettere il workflow: il sistema dovrebbe
essere in grado, dove è possibile, di rimediare in autonomia all'esclusione di un nodo riorganizzando in automatico
e sensatamente il collegamento tra i nodi».

- `esclusione.py` — `escludi(wf, nodi, info, protetti)`, sulla copia del workflow pronta da inviare:
  - chi usava un'uscita del nodo staccato viene ricollegato all'ingresso dello **stesso tipo** del nodo staccato,
    come il bypass di ComfyUI: prima quello nella stessa posizione dell'uscita, poi quello con lo stesso nome, poi il
    primo del tipo (LoRA → MODEL e CLIP dal nodo prima; ControlNetApplyAdvanced → positive e negative ognuno al suo
    posto); le catene di nodi staccati si attraversano
  - un ingresso facoltativo che non si può ricollegare viene tolto
  - un nodo che perde un ingresso indispensabile viene **staccato anche lui** e si continua a valle (riferimento
    staccato → l'IPAdapter perde l'immagine e si stacca → il KSampler prende il modello che entrava nell'IPAdapter;
    un'anteprima del nodo staccato sparisce con lui), con il motivo per ognuno
  - i nodi riconosciuti (campionatore, prompt positivo, immagine finale) non si staccano mai da soli: se la catena
    arriva a loro, il risultato è un problema spiegato in italiano
  - tipi delle uscite e degli ingressi da `/object_info` di ComfyUI; senza ComfyUI, quelli dei nodi più comuni e il
    nome dell'ingresso (model → MODEL, clip → CLIP…)
- `ConfigDataset.disattivati`; `applica(..., disattivati, info)` stacca per ultimo, così un img2img con le pose dalle
  varianti ha già lasciato libero il VAEEncode del riferimento
- `POST …/dataset/esclusione`: anteprima con la configurazione ancora da salvare; la generazione non parte se ci
  sono problemi, scrive nel registro cosa è stato staccato e ricollegato, e non chiede il riferimento se è staccato
- interfaccia: «Nodi e parametri» mostra tutti i nodi, ognuno con ⏻ per staccarlo o riattaccarlo; i nodi staccati
  (da te o da Comic Studio, con il motivo) sono tratteggiati e barrati; sopra l'elenco il riquadro con i
  collegamenti rifatti, i nodi staccati in automatico o i problemi; «Riattacca tutti»
- Versione 0.14.0
- **Test**: 121 test backend (LoRA singolo e in catena, ControlNet con positive / negative, riferimento → IPAdapter e
  anteprima a cascata, checkpoint e nodi riconosciuti non staccabili, ingresso facoltativo tolto, nodo sconosciuto
  con e senza i tipi di ComfyUI, img2img con il riferimento staccato, API di anteprima e generazione); collaudo
  con Chromium: LoRA staccato → KSampler ricollegato al checkpoint; riferimento staccato → ImageScale e VAEEncode
  staccati da soli; checkpoint staccato → problemi spiegati

Prossimo passo: PR 15, eliminazione dei modelli dell'IA.

## PR 15 — IA locale: eliminare i modelli e gestire Ollama

### Eliminare i modelli

Richiesta: «modificare il programma per fare in modo di cancellare direttamente da lì i modelli AI locali».
I modelli di Ollama pesano da 1 a oltre 20 GB l'uno e finora si potevano solo scaricare.

- `ClientIA.elimina_modello(nome)`: toglie il modello dalla memoria (`keep_alive: 0`) e lo cancella con
  `DELETE /api/delete` di Ollama; un modello che non c'è già più non è un errore. I file condivisi con altri
  modelli scaricati li tiene Ollama finché servono
- `ServizioIA.elimina_modello`: solo con Ollama acceso; rifiuta mentre si scarica un modello o Ollama
  (`ia_modello`, `ia_installa`) e mentre l'IA sta rispondendo (il lucchetto delle domande), e tiene il lucchetto
  durante la cancellazione così nessuna domanda parte nel frattempo; scrive nella console cosa ha fatto
- `StatoIA.dimensioni`: i byte di ogni modello scaricato (da `/api/tags`)
- `POST /api/ia/modello/elimina` `{nome}` → `{eliminato, stato}`. È una richiesta e non un lavoro: Ollama
  cancella in un attimo
- **Eccezione alla regola del cestino**: i modelli si cancellano davvero, perché i loro file stanno nell'archivio
  di Ollama (condivisi tra modelli) e non si possono spostare; si riscaricano con un clic. La conferma lo dice,
  con lo spazio che si libera e un avviso se è il modello in uso (l'IA torna «non pronta» e la finestra di scelta
  si riapre alla prossima domanda)
- interfaccia: **Sistema → IA locale → Modelli scaricati** con il peso di ognuno, lo spazio totale, «Usa
  questo» e 🗑 (disattivato mentre l'IA lavora); nella finestra di scelta del modello **Elimina dal computer**
  quando la variante scelta è già scaricata
- Versione 0.15.0
- **Test**: test backend `test_elimina_modello` (dimensioni nello stato, modello tolto dalla memoria e cancellato,
  modello già assente, rifiuto mentre l'IA risponde, eliminazione di quello in uso → IA non pronta, solo con Ollama,
  nome vuoto); il finto Ollama ha `/api/delete`. 14 test dell'interfaccia; collaudo con Chromium: tre modelli,
  gemma3:4b eliminato da Sistema (2 rimasti, totale aggiornato), llama3.2:3b eliminato dalla finestra di scelta.
  Già prima di questa PR falliscono 3 test sul blocco dei contenuti (`test_blocco_minori_e_contenuto_sessuale`,
  `test_scena_vietata_bloccata`, `test_proposte_bloccate_e_senza_testo`), perché i controlli sono stati disattivati
  nei commit «Disable scene and content verification» e «fix»

### Gestione di Ollama

Richiesta: «ho cambiato modello ma mi dice che Ollama non risponde: è possibile aggiungere una gestione anche
dell'Ollama locale, riavviarlo se necessario e un minimo di gestione, perché magari l'app non lo avvia in locale
allo start».

**Cosa succedeva.** Due problemi insieme. (1) Nelle impostazioni il tipo era «Server compatibile OpenAI» (indirizzo
di LM Studio, :1234) con un modello di Ollama (`qwen3:4b-q8_0`): la finestra di scelta del modello cambiava solo il
nome del modello e lasciava il tipo, quindi Comic Studio continuava a chiedere a un LM Studio spento. (2) Ollama
non partiva mai all'apertura: si avviava solo alla prima domanda all'IA, così la pagina diceva «non risponde» anche
quando bastava avviarlo, e se si chiudeva nessuno se ne accorgeva.

- `processo_ollama.py`: i processi `ollama serve` (anche lanciati da un interprete), con utente e porta;
  `termina` con i figli (i modelli caricati) e chi non si può fermare; `come_fermarlo` (servizio di sistema su
  Linux → `sudo systemctl restart ollama`); livello e testo delle righe del registro (slog), senza le richieste
  HTTP `[GIN]`; `spiega_errore` (porta occupata, permessi, disco pieno, ultime righe)
- `ServizioIA`:
  - **all'apertura** (`all_avvio`, dentro `App.avvio`, prima di ComfyUI): riconosce l'Ollama avviato la volta
    prima (PID salvato in `strumenti/ollama/ollama.pid`, come per ComfyUI) e, se è spento, lo avvia
  - **sorveglianza** (ogni 10 s): spento → lo avvia al secondo controllo; acceso da Comic Studio ma bloccato →
    lo riavvia al terzo, ma non mentre sta rispondendo a una domanda; dopo 3 tentativi falliti di fila si ferma e
    lo scrive nella console (Avvia a mano ricomincia a contare); niente se l'utente l'ha fermato, se si sta
    installando o se l'avvio automatico è spento
  - **Avvia / Riavvia / Ferma** come lavori (`ia_avvio`, `ia_arresto`), uno alla volta; un Ollama aperto in un
    altro modo si usa così com'è, si ferma solo se è dello stesso utente (altrimenti si spiega come fare) e, se il
    sistema lo riaccende da solo, lo si dice
  - un avvio alla volta (`_lock_avvio`), anche tra sorveglianza, domande e pulsanti
  - il registro di Ollama va nella console come `Ollama › …` (errori e avvisi visibili, il resto in «Dettagli»);
    se si chiude da solo la console lo dice con il motivo; un avvio fallito spiega perché (es. porta occupata)
  - `StatoIA`: `in_avvio`, `avviato_da_noi`, `pid`, `esterno` (servizio di sistema, app o terminale), `fermato`,
    `avvio_automatico`, `suggerisci_ollama`; messaggi d'errore che dicono cosa sta succedendo
- impostazione `ia_avvio_automatico` (acceso di serie); passando a Ollama o riattivandolo, Ollama parte subito
- `POST /api/ia/scegli`: i modelli dell'elenco sono di Ollama, quindi sceglierne uno passa a Ollama anche dal tipo
  «compatibile OpenAI» (prima solo da «nessuna»)
- con il server compatibile OpenAI che non risponde e Ollama installato (o acceso su :11434), `suggerisci_ollama`
- interfaccia, Sistema → IA locale: sezione **Ollama** con lo stato (acceso da Comic Studio con il PID, da altri,
  si sta avviando, spento, fermo, non installato), Riavvia / Ferma / Avvia (conferma se l'ha aperto qualcun altro),
  interruttore dell'avvio automatico e percorso del programma; nel riquadro in alto **Usa Ollama** quando il server
  OpenAI non risponde ma Ollama c'è, **Avvia Ollama** quando è spento
- **Test**: `test_ollama_processo.py` con un `ollama` finto che è un processo vero (`finto_ollama_serve.py`: righe
  come quelle di Ollama, porta occupata, blocco a comando): avvio all'apertura, registro nella console senza le
  richieste HTTP, chiusura improvvisa → riavvio della sorveglianza, Ferma che resta fermo, Riavvia, riapertura di
  Comic Studio che riconosce il processo e lo chiude all'uscita, blocco → riavvio ma non durante una domanda, porta
  occupata spiegata e tentativi limitati, LM Studio che non risponde → «Usa Ollama» e scelta del modello che passa
  a Ollama, servizio di un altro utente. Collaudo con Chromium nel caso dell'utente (tipo OpenAI su :1234):
  «Usa Ollama» → IA pronta in meno di un secondo; processo ucciso → «Spento» subito, riacceso da solo in 16 s;
  Ferma → resta fermo; Avvia
  Collaudo anche con **Ollama 0.40.11 vero** (installato come fa Comic Studio, in `strumenti/ollama`): parte da solo
  all'apertura; ucciso con `kill -9` → riacceso dalla sorveglianza in 20 s; Riavvia, Ferma (resta fermo); Comic
  Studio chiuso di colpo → alla riapertura riconosce il suo Ollama dal PID. Un Ollama di prova lasciato acceso su
  :11434 è stato fermato e sostituito da Riavvia, come un Ollama aperto fuori da Comic Studio. Gli avvisi di Ollama
  sui servizi online di ollama.com (senza rete) vanno in «Dettagli», non tra gli avvisi

Prossimo passo: PR 16, dal personaggio dal nulla al dataset.

## PR 16 — Dal personaggio dal nulla al dataset, con le stesse scelte

Richiesta: «quando creo un personaggio da zero, il workflow che ha generato il programma me lo deve riproporre in
automatico quando genera il dataset, altrimenti per forza vengono fuori soggetti diversi»; e «posso scegliere se
generarlo con Pony o con Illustrious, dargli uno stile presente nei LoRA, o più in generale scegliere diverse
opzioni?».

**Cosa succedeva.** Le proposte (PR 9) si generavano con un workflow interno (checkpoint scelto, tag di stile,
campionamento fisso) di cui non restava traccia: la proposta salvava solo seme e prompt. Il dataset ripartiva da
zero, con il workflow scelto a mano dalla libreria (spesso con un altro checkpoint) e senza i tag di stile: il
personaggio del dataset, e quindi del LoRA, poteva essere un altro.

- `proposte.Ricetta`: checkpoint, LoRA di stile e forza, stile, tag in più, negativo (solo se cambiato), passi,
  CFG, sampler, scheduler, inquadratura; ogni `Proposta` ha la sua; le proposte più vecchie no (`None`)
- `ConfigProposte`: `lora_stile`, `forza_lora`; il workflow delle proposte mette il `LoraLoader` tra checkpoint,
  testi e campionatore
- `Personaggio.origine`: la ricetta della proposta scelta con «Usa questa»; un riferimento caricato a mano la
  toglie
- `ArchivioDataset.come_proposte`: workflow integrato con lo stesso checkpoint, LoRA di stile e campionamento;
  IPAdapter Plus e CLIP Vision ViT-H scelti da soli se installati, altrimenti txt2img con un avviso (la somiglianza
  la fa la selezione automatica); riusa il workflow se in libreria ce n'è già uno con gli stessi parametri;
  configurazione con `stile` (nuovo segnaposto `{stile}`, ora anche nel prompt predefinito) e negativo delle
  proposte. `integrato()` funziona anche senza IPAdapter
- «Usa questa» prepara il dataset così se non ha ancora un workflow; `GET …/dataset` dà `origine` con
  `coerente`; `POST …/dataset/come-proposte` per tornare alle scelte delle proposte
- `POST …/proposte/anteprima`: il prompt esatto (con i tag di qualità della famiglia del checkpoint) senza generare
- interfaccia, proposte: LoRA di stile (dalle LoRA di ComfyUI) con la forza, tag in più, «Negativo e
  campionamento» (negativo con ripristino, passi, CFG, sampler, scheduler), anteprima del prompt con la famiglia
  (Pony, Illustrious…) aggiornata mentre si scelgono le opzioni; il pannello riparte dalle scelte dell'ultima
  proposta; ⟲ su ogni proposta per riprenderne le scelte
- interfaccia, dataset: riquadro «Come le proposte da cui è nato …» oppure l'avviso quando il workflow usa un altro
  checkpoint o non ha la LoRA, con **Usa le scelte delle proposte**; campo **Stile** e segnaposto `{stile}`
- l'addestramento propone già il checkpoint del workflow del dataset, quindi anche il LoRA si addestra sullo stesso
- Versione 0.16.0
- **Test**: `test_dataset_come_le_proposte` (anteprima Pony, LoRA nel workflow delle proposte, ricetta salvata,
  «Usa questa» → dataset pronto con checkpoint, LoRA, sampler, stile e negativo; esempi dei prompt; un altro
  workflow → non coerente; «come le proposte» con IPAdapter installato → nodo di riferimento, senza doppioni;
  riferimento caricato a mano → nessuna origine). Collaudo con Chromium: Pony + LoRA Western_Ink_XL + stile →
  anteprima, 4 proposte, «Usa questa» → dataset «Come le proposte · ponyDiffusionV6XL + Western_Ink_XL»; scelto un
  workflow Illustrious → avviso; «Usa le scelte delle proposte» → di nuovo coerente, stile nel campo

Prossimo passo: PR 17, IPAdapter Plus installato da Comic Studio.

## PR 17 — IPAdapter Plus installato da Comic Studio

Richiesta: «fare in modo che il programma chieda di installarli all'avvio se non trova il nodo
ComfyUI_IPAdapter_plus, il modello ip-adapter-plus_sdxl_vit-h e CLIP Vision ViT-H; ovviamente se non hai spazio te
lo deve dire».

- `componenti.py`: i tre componenti con cartella, nome del file (CLIP Vision rinominato
  `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors`, come vuole il nodo), indirizzo (Hugging Face h94/IP-Adapter, GitHub
  cubiq/ComfyUI_IPAdapter_plus) e dimensione stimata
  - `controlla`: cosa manca guardando il disco di ComfyUI e, se ComfyUI è acceso, anche i suoi elenchi dei modelli
    (cartelle di extra_model_paths) e i nodi caricati; un file con un altro nome che corrisponde va bene; un nodo sul
    disco che ComfyUI non carica non si reinstalla (lo segnala già la diagnostica)
  - spazio per disco (`shutil.disk_usage` sulla cartella di ComfyUI): file + 1 GB di margine; se non basta, il
    messaggio dice quanto liberare
  - `scarica`: in `<file>.parziale`, con avanzamento e annullamento; diventa definitivo solo se la dimensione è
    giusta e, quando Hugging Face la dà (`x-linked-etag`), anche l'impronta SHA-256; nessun file a metà
  - `installa_nodo`: `git clone --depth 1` se c'è git (così ComfyUI-Manager lo aggiorna), altrimenti lo ZIP di GitHub
- `rotte_componenti.py`: `GET /api/componenti`, `POST /api/componenti/installa` (lavoro `componenti`, rifiutato con il
  messaggio se manca spazio), `POST /api/componenti/chiedi` («non chiedere più», impostazione `chiedi_componenti`).
  Dopo il nodo, se ComfyUI l'ha avviato Comic Studio e non ci sono altri lavori lo riavvia; altrimenti dice di farlo
- all'apertura (`App.avvio`, dopo ComfyUI e prima della diagnostica) il controllo va nella console e
  all'interfaccia (evento `componenti`, anche nel benvenuto del WebSocket, così non si perde se il browser arriva dopo)
- interfaccia: finestra «Installare IPAdapter Plus?» una volta per sessione, con i componenti mancanti e il loro peso,
  lo spazio che serve e quello libero, **Installa** (disattivato se manca spazio, con quanto liberare e dove),
  **Non ora**, **Non chiedere più**; avanzamento, Ferma, esito e avviso di riavvio. In Sistema → Controllo un riquadro
  con **Installa…** finché manca
- Versione 0.17.0
- **Test**: `test_componenti.py` con un finto Hugging Face (rimando con `x-linked-etag`) e GitHub (ZIP): cosa manca
  anche con altri nomi o in cartelle viste solo da ComfyUI, nodo non caricato, spazio insufficiente (409 e nessun
  download), installazione completa (nodo dallo ZIP, modelli con il nome giusto, nessun `.parziale`, elenco dei
  modelli aggiornato), download rovinato → nessun file e si riprende dai modelli. Collaudo con Chromium della sequenza
  di apertura vera: disco quasi pieno → finestra con «libera almeno 2,4 GB», Installa disattivato; disco libero →
  installazione (il nodo clonato con git da GitHub), «IPAdapter Plus è installato»

Prossimo passo: PR 18, pose guidate e costruttore di workflow.
