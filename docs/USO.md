# Guida d'uso

## 1. Primo avvio

1. Installa Comic Studio con l'installer del tuo sistema (vedi il README) e aprilo dall'icona;
   dai sorgenti: `avvia.bat`, `avvia.command` o `./avvia.sh`. Si apre il browser.
2. Il programma cerca ComfyUI da solo: se è già aperto ci si aggancia, altrimenti **lo avvia lui** e aspetta
   che sia pronto (la prima volta può volerci qualche minuto; in console vedi cosa scrive ComfyUI).
3. Poi controlla il sistema. In alto a destra vedi lo stato: pallino giallo = in avvio, verde = connesso,
   con il nome della GPU e la VRAM.

In **Sistema → Connessione a ComfyUI** trovi i pulsanti **Avvia**, **Riavvia** (utile dopo aver installato custom
node o modelli) e **Ferma**, l'interruttore dell'avvio automatico e gli **argomenti in più** (es. `--lowvram`).
ComfyUI resta acceso anche se chiudi Comic Studio. Se usi un tuo file di avvio (es. `run_nvidia_gpu.bat`),
scrivilo in **Opzioni avanzate → Comando di avvio personalizzato**.

Se ComfyUI non viene trovato: pagina **Sistema → Connessione a ComfyUI**, inserisci l'indirizzo
(di solito `http://127.0.0.1:8188`, oppure `:8000` per l'app Desktop) e la cartella che contiene
`models`, `input` e `output`, poi **Salva e prova**.

## 2. Controllo del sistema

Pagina **Sistema → Controllo**. Le voci sono divise per categoria, con un'icona:

- ✅ a posto · ⚠️ da tenere d'occhio · ❗ da sistemare prima di proseguire · ℹ️ informazione

Per ogni problema c'è scritto cosa fare e, quando serve, il link da cui scaricare il componente.
Nel riquadro **Consigli** trovi le impostazioni più adatte alla tua scheda video (per esempio fp8 con 8 GB di VRAM).
**Ricontrolla tutto** cerca anche gli aggiornamenti (serve internet); **Controllo rapido** solo i controlli locali.

## 3. Progetto e personaggi

1. **Progetti → Nuovo progetto**: dai un nome alla storia.
2. Nella pagina **Personaggi** aggiungi ogni personaggio:
   - **Nome** e **tipo** (donna, uomo, altro)
   - **Trigger word**: una parola inventata (ne viene proposta una, il dado ne genera un'altra).
     Non usare parole vere come "police" o "girl": il modello le conosce già e si confonderebbe.
   - **Descrizione libera**: scrivi il personaggio come vuoi, anche a lungo e in italiano, poi premi
     **Ricava i tratti con l'IA**: l'IA locale ne tira fuori i tratti fissi in inglese (e il tipo). Controllali e
     premi **Salva**. La personalità e la storia restano nella descrizione, non finiscono nel prompt.
   - **Tratti fissi**, in inglese: ciò che non cambia mai, come capelli, corporatura e vestiti
     (es. `old man, fat, white hair, white mustache, blue police uniform`). Puoi anche scriverli a mano.
   - **Immagine di riferimento**: trascinala nel riquadro. Meglio un'immagine pulita, a figura intera o
     mezzo busto, su sfondo semplice.
   - **Non hai un'immagine?** Scrivi la descrizione libera e premi **Crea dal testo**: scegli checkpoint (Pony,
     Illustrious, NoobAI…: i tag di qualità giusti li mette Comic Studio), **LoRA di stile** con la sua forza,
     stile, tag in più, inquadratura e quante proposte; in **Negativo e campionamento** il prompt negativo, passi,
     CFG, sampler e scheduler. Sotto vedi il prompt positivo e negativo esatto che verrà usato. Poi **Genera**. Se
     mancano i tratti fissi li ricava prima l'IA. Sulla proposta giusta premi **Usa questa** (diventa l'immagine di
     riferimento) oppure **Varianti** per averne altre simili; ⟲ riprende le scelte con cui è stata fatta quella
     proposta; **Togli le non scelte** sposta le altre nel cestino del progetto.
   - **Hai già il prompt?** Accendi **Ho già il prompt** e scrivi positivo e negativo: le proposte li usano parola per
     parola (pesi compresi) e non servono descrizione né tratti. Le LoRA non si scrivono nel prompt (`<lora:…>` in
     ComfyUI non fa niente): si scelgono in «LoRA di stile». Nel dataset i tag di inquadratura, posa, angolazione,
     espressione e sfondo del tuo prompt diventano le varianti, il resto resta identico.
   - **Trasformazioni** (in fondo alla scheda, quando c'è il riferimento): per un personaggio che cambia stato (il prete
     che diventa mostro) premi **Nuova trasformazione**, scrivi il nome dello stato B, i suoi tag (li decidi tu: valgono
     solo qui), i tag di A da togliere, se vuoi una LoRA, e quanti passi. **Genera la sequenza** crea i fotogrammi da A a
     B nella stessa inquadratura; **Rigenera** con lo stesso seme o **Nuovo seme**, **Scarica GIF**. Sotto un
     fotogramma, 👤+ crea il personaggio dello stato B, con il suo dataset già pronto.
   - **Il dataset è identico alle proposte.** Con «Usa questa» Comic Studio prepara anche il dataset del personaggio:
     lo stesso workflow delle proposte con in più solo l'immagine di riferimento (IPAdapter, se è installato), lo
     stesso prompt salvo la parte che cambia a ogni immagine, lo stesso negativo. Così il dataset, e quindi il LoRA,
     ritrae lo stesso personaggio delle proposte. Se il dataset aveva già un workflow scelto da te non lo cambia: nel
     dataset il riquadro di confronto propone **Rendi il dataset identico alle proposte**.

**IPAdapter Plus.** Se all'apertura Comic Studio non trova il nodo ComfyUI_IPAdapter_plus, il modello
ip-adapter-plus_sdxl_vit-h o CLIP Vision ViT-H, ti chiede se installarli: vedi cosa manca, quanto pesa (circa 3,3 GB in
tutto) e quanto spazio c'è sul disco di ComfyUI. Se non basta te lo dice e non scarica niente. Dopo il nodo serve
riavviare ComfyUI (se l'ha avviato Comic Studio lo fa da solo). «Non chiedere più» toglie la domanda: puoi installarlo
quando vuoi da Sistema → Controllo.

**Il workflow che usa Comic Studio.** Ogni volta che un lavoro (proposte, dataset, prova del LoRA, fumetto) manda
un workflow a ComfyUI, nella console compare una riga «Workflow inviato a ComfyUI» con i nodi e i valori principali e
il pulsante **grafo**. La scheda **Grafo** della console disegna i nodi collegati come in ComfyUI: rotella per lo
zoom, trascina lo sfondo o i nodi, clic su un nodo per vedere tutti i suoi valori (anche il prompt intero). Da lì puoi
scaricare il workflow e trascinarlo in ComfyUI per aprirlo identico, o vederlo a tutto schermo.

Nel pannello del nodo puoi **cambiare le impostazioni** (checkpoint, LoRA, passi, CFG, sampler, pesi…), con i limiti
di ComfyUI controllati mentre scrivi, e premere **Salva**: valgono dalla prossima generazione di quel personaggio.
Per il dataset finiscono nelle sue impostazioni (le ritrovi in Dataset → Nodi e parametri), per le proposte nelle
scelte del pannello «Crea dal testo». Le impostazioni con il lucchetto le scrive Comic Studio (prompt, seme,
dimensioni…): il pannello dice perché e dove si cambiano.

## 4. Step 1 · Dataset

Per ogni personaggio (scegli in alto quale):

- se il riferimento è una proposta, il riquadro in alto verifica che il dataset usi **lo stesso workflow** della
  proposta con in più solo l'immagine di riferimento (IPAdapter), **lo stesso prompt** salvo la parte che cambia a
  ogni immagine (inquadratura, sguardo, espressione, posa, sfondo) e **lo stesso negativo**: mostra prompt e negativo
  tag per tag e le differenze del workflow nodo per nodo. **Rendi il dataset identico alle proposte** sistema tutto.
  Per i personaggi creati con le versioni vecchie indica prima il checkpoint con cui hai fatto la proposta

1. **Workflow** — scegline uno dalla libreria del progetto, **caricane uno** tuo (il file salvato da ComfyUI va
   bene, con ComfyUI avviato) oppure **crea quello integrato** (SDXL + IPAdapter) scegliendo checkpoint, LoRA di
   stile e modelli dagli elenchi. Il programma riconosce da solo i nodi del riferimento, dei prompt, del seme,
   delle dimensioni e dell'immagine finale: controlla in «Nodi riconosciuti» e correggi solo se serve.
   In «Parametri dei nodi» puoi cambiare qualunque valore (passi, CFG, forza dell'IPAdapter…) solo per questo personaggio.
   Se il workflow è **img2img** (il KSampler parte dall'immagine di riferimento) compare il riquadro **pose e
   inquadrature**: con **Pose dalle varianti** (predefinito) ogni immagine parte da zero con la posa, l'angolazione e
   le dimensioni della sua variante, e l'aspetto del personaggio viene dai LoRA / IPAdapter del workflow e dal
   prompt; con **Come il riferimento** tutte le immagini hanno la posa del riferimento.
   In **Nodi e parametri** puoi anche **staccare** un nodo con il pulsante ⏻ (per esempio un LoRA, un IPAdapter,
   un ControlNet, un upscale): Comic Studio collega direttamente quello che c'era prima e quello che c'era dopo, e
   stacca da solo i nodi che senza di lui non funzionerebbero (es. staccando il riferimento, l'IPAdapter che lo usava).
   Il riquadro sopra l'elenco mostra i collegamenti rifatti; se il workflow non può funzionare (es. checkpoint
   staccato) lo dice e la generazione non parte. Il file del workflow non cambia: il pulsante ⏻ riattacca il nodo.
2. **Prompt e varianti** — il prompt è un modello: `{descrizione}` diventa i tratti fissi del personaggio,
   `{variante}` cambia a ogni immagine (inquadratura, angolazione, espressione, posa, sfondo), `{qualita}` mette i
   tag giusti per il checkpoint. Sotto vedi esempi dei prompt che verranno usati.
   **Aspetto dal riferimento** (`{aspetto}`): vestiti, capelli e accessori dell'immagine di riferimento, subito dopo
   i tratti in ogni prompt (lo riempie «Massima somiglianza al riferimento»).
3. **Pose guidate** — Comic Studio disegna lo scheletro OpenPose di ogni posa (in piedi, tre quarti, profilo, di
   spalle, mani sui fianchi, braccia conserte, saluto, corsa, seduta, in ginocchio…, anche specchiate) e lo passa a
   un **ControlNet OpenPose SDXL**: il personaggio prende la posa dello scheletro, aspetto e stile restano quelli del
   workflow e del riferimento. Se il ControlNet manca, **Installa** lo scarica (2,5 GB, con il controllo dello
   spazio). Scegli le pose cliccando sulle miniature, la **forza** (0,7-0,9) e fino a che punto dei passi vale.
   **Una immagine per posa** genera subito una figura intera per ogni posa scelta; con l'interruttore acceso anche
   «Genera» usa le pose, a turno, tagliate per ogni inquadratura. Il prompt prende da solo posa e angolazione.
4. **Generazione** — scegli quante immagini (80-120) e quante tenerne (20-40), poi **Genera**. Segui
   l'avanzamento qui e nella console; puoi fermarla quando vuoi.

   **Stessa persona, come le proposte** (nel riquadro in alto e qui) fa nascere le immagini del dataset come le
   proposte, che sembrano sempre la stessa persona: stesso workflow (senza IPAdapter), stesso prompt nello stesso
   ordine, stesse dimensioni, sfondo bianco e sguardo in camera; cambiano solo posa, angolazione, espressione e quanto
   si vede della figura. In più il tagger legge vestiti e accessori del riferimento e li mette nel prompt, così la
   divisa resta quella scelta. Poi **Tieni le N migliori** sceglie le più somiglianti; con 20-30 buone addestra il
   LoRA: con quello il personaggio resta uguale in qualunque posa e scena.

   **Grafi**: nella proposta (pagina Personaggi) il pulsante 🌳 mostra il workflow con cui è stata fatta; aprendo
   un'immagine del dataset, **Grafo** mostra il suo e **Confronta con la proposta** mette i due grafi fianco a fianco
   con le differenze nodo per nodo e i prompt tag per tag (in rosso solo nella proposta, in verde solo nel dataset).
   Lo stesso dal riquadro in alto, **Confronta i grafi** (ultima immagine).
5. **Galleria** — **Tieni le N migliori** sceglie da sola le più somiglianti al riferimento, varie e senza doppioni.
   Poi rifinisci a mano: passa sopra un'immagine e premi ✓ o ✕, oppure aprila e usa **T** (tieni), **S** (scarta)
   e le frecce. Le tue scelte manuali non vengono più toccate dalla selezione automatica.
6. **Scarica ed Elimina** — agiscono sulle immagini del filtro scelto (Tutte, Tenute, Da decidere, Scartate):
   - **Scarica → ZIP**: le immagini con il prompt di ognuna in un `.txt`
   - **Scarica → … e cancellale dal computer**: dopo il download completo le immagini vengono cancellate dal disco
     (non passano dal cestino), così non occupano più spazio
   - **Elimina**: le sposta nel cestino; dal messaggio, o da **Elimina → Svuota il cestino**, le cancelli davvero
     e liberi lo spazio. In alto vedi quanto occupano.

## 5. Step 2 · Didascalie

1. Scegli il personaggio. Vengono usate le immagini che hai tenuto nello Step 1.
2. **Analizza** fa guardare le immagini al tagger WD14 (la prima volta lo scarica, circa 400 MB). Se sei offline
   scegli **Solo prompt**: i tag vengono dal prompt con cui ogni immagine è stata generata.
3. Ogni didascalia inizia con la trigger word. Escono da soli i **tratti fissi** della descrizione (anche detti con
   meno parole: «blonde hair» per «long straight blonde hair»), l'aspetto del riferimento usato nel dataset e, con
   **Togli anche l'aspetto che ricorre** (acceso), capelli, occhi e vestiti presenti in quasi tutte le immagini: così
   li impara la trigger word, e basta lei a richiamare il personaggio. Nella tabella **Tag del dataset** fai clic su un
   tag per toglierlo o rimetterlo.
4. Se una didascalia non va, correggila a mano nel suo riquadro (torna a quella automatica con **Automatica**).
5. **Scarica il dataset** ti dà uno zip con immagini e `.txt`, utile per addestrare anche altrove.

## 6. Step 3 · Addestramento

1. **Trainer**: la prima volta premi **Installa**. Scarica kohya, PyTorch e le librerie (circa 3 GB, 10-20 minuti);
   servono Python 3.10, 3.11 o 3.12 (meglio il 3.10) e preferibilmente Git.
2. Scegli il personaggio e il **checkpoint di base**: lo stesso che userai per il fumetto.
3. Scegli il **preset**: quello «consigliato» va bene per la tua scheda (con 8 GB: «8 GB sicuro»). Nei
   **parametri avanzati** puoi cambiare tutto; il conto ti dice quanti passi farà.
4. **Addestra**: segui passi, epoche, tempo rimanente e il grafico della loss. Con 8 GB conta 1-3 ore. ComfyUI può
   restare aperto.
5. **Prova le epoche**: un'epoca è un giro completo su tutte le immagini; dopo ogni giro Comic Studio salva il LoRA
   com'è in quel momento. Le prime epoche hanno imparato poco, le ultime rischiano di copiare le immagini del dataset
   (stesse pose, disegno rigido): la prova le mette a confronto con lo stesso seme. Scegli quali (di solito sono già
   selezionate 4), scrivi i **prompt di prova in inglese a tag** (`{trigger}, {genere}, solo, sitting, smile, upper
   body`) e premi **Prova**. Confronta le immagini affiancate e premi **Usa questa** sull'epoca migliore: quella
   «consigliata» è la più somigliante al riferimento.
6. Hai già un LoRA addestrato altrove? Sceglilo in **Oppure usa un LoRA già addestrato**.

## 7. Step 4 · Fumetto

1. **Impostazioni**: scegli il checkpoint (lo stesso dei LoRA) ed eventualmente un LoRA di stile.
2. Scrivi le pagine: **Storia da testo → Racconto libero** per incollare tutta la storia così com'è (l'IA la divide
   in pagine e vignette, sceglie i personaggi e copia i dialoghi), **Una vignetta per riga** per il formato
   a righe, oppure aggiungi le vignette a mano a sinistra.
3. Per ogni vignetta: **formato**, **personaggi** in scena (clic per aggiungerli; il primo sta a sinistra, le
   frecce cambiano l'ordine; se non ne scegli, li trova l'IA nel testo), la **descrizione della scena** in
   linguaggio naturale, lunga quanto vuoi, ed eventuali **tag in più** in inglese, poi le **battute** con chi parla
   e dove mettere il balloon. **Trasforma in prompt** mostra cosa ha capito l'IA: la scena, cosa fa ciascun
   personaggio nella sua zona, cosa evitare e cosa non si può disegnare (suoni, odori, pensieri). Si fa comunque
   da solo quando generi, e si rifà solo se cambi il testo.
4. **Genera le mancanti** fa tutte le vignette senza immagine; sulla singola vignetta **Nuova versione** ne prova
   un'altra, **Stesso seme** rifà la stessa composizione con le modifiche al testo. Le versioni restano: clic su
   una miniatura per usarla.
   Sotto l'immagine c'è l'**aderenza**: quali elementi chiave della descrizione il tagger vede davvero
   (✓) e quali mancano (✗). **Rafforza i mancanti e rigenera** li fa pesare di più e rifà la vignetta con lo
   stesso seme.
5. A destra vedi la **tavola** con i balloon. **Esporta** ti dà il PDF o le pagine in PNG.

## 8. L'IA locale

Non serve prepararla prima: la prima volta che usi l'IA (per esempio **Ricava i tratti con l'IA**) e manca
Ollama o il modello, si apre la finestra **Scegli l'IA locale**:

- in alto vedi la tua scheda video, la VRAM e la RAM
- l'elenco mostra i modelli ordinati per il tuo computer: in cima **il migliore per te** e due **consigliati**;
  ogni modello ha le sue quantizzazioni (Q4_K_M, Q8_0, FP16…) con la dimensione e un pallino: verde = tutto sulla
  GPU, giallo = in parte sulla CPU (più lento), arancione = solo processore, rosso = non entra in memoria
- **Adatti al mio computer** / **Tutti** e il campo **Cerca**; un nome che non è nell'elenco (es. `deepseek-r1`)
  si cerca su Ollama con un clic
- **Aggiorna da Ollama** legge dal registro tutte le versioni e le dimensioni vere (senza rete le dimensioni
  sono stimate, con il segno ~)
- **Installa Ollama e scarica** / **Scarica e usa** / **Usa questo**: finito il download la finestra si chiude
  e l'azione che avevi chiesto riparte da sola

La stessa finestra si apre da **Sistema → IA locale → Scegli il modello adatto al tuo computer**. Ollama e i
modelli finiscono nella cartella `ComicStudio/strumenti/ollama`. Tutto gira sul tuo computer. Se hai già Ollama o LM Studio, Comic Studio usa quelli. Puoi provare l'IA con una scena di esempio e
cambiare modello (più leggero o più preciso). Prima di ogni domanda all'IA la memoria della scheda video viene
liberata, così ComfyUI e l'IA non se la contendono.

**Ollama acceso e spento.** In **Sistema → IA locale → Ollama** vedi se è acceso, chi l'ha avviato (Comic Studio,
il servizio di sistema o l'app di Ollama) e hai **Avvia**, **Riavvia** e **Ferma**. Con l'interruttore «Avvia Ollama
all'apertura…» (acceso di serie) Ollama parte insieme a Comic Studio e, se si chiude o smette di rispondere, viene
riavviato da solo entro una ventina di secondi; se non riparte dopo tre tentativi, la console spiega perché (per
esempio la porta occupata da un altro Ollama). Quello avviato da Comic Studio si chiude quando chiudi Comic Studio.
Su Linux, un Ollama installato come servizio di sistema non si può fermare da qui: la pagina dice il comando da usare
(`sudo systemctl restart ollama`).

Se in **Tipo** c'è «Server compatibile OpenAI» ma il modello è di Ollama (succede scegliendo il tipo sbagliato), in
alto compare **Usa Ollama**: un clic e Comic Studio passa a Ollama e lo avvia. Anche scegliere un modello dalla
finestra dell'elenco passa a Ollama, perché quei modelli sono di Ollama.

Per liberare spazio: in **Sistema → IA locale → Modelli scaricati** ogni modello ha il suo peso e il pulsante 🗑,
e nella finestra di scelta, selezionando un modello già scaricato, compare **Elimina dal computer**. I modelli
eliminati non vanno nel cestino: per riaverli si scaricano di nuovo. Se elimini quello in uso, l'IA non è pronta
finché non ne scegli un altro.

Contenuti: il testo viene tradotto in modo fedele, horror, violenza e sangue compresi. C'è un solo blocco fisso,
che non si può disattivare: niente contenuti sessuali con minorenni o personaggi dall'aspetto infantile.

## 9. La console

Per **chiudere** Comic Studio usa il pulsante ⏻ in alto a destra: puoi lasciare acceso ComfyUI o chiudere anche
quello. Riaprendo l'icona la pagina si riattiva da sola. Se qualcosa va storto all'avvio, il registro è in
`ComicStudio/comicstudio.log`.

In basso c'è sempre la console: tutti i messaggi del programma, di ComfyUI e, in futuro, dell'addestramento.

- gli **indirizzi** nei messaggi sono cliccabili: quello di ComfyUI (es. `http://127.0.0.1:8188`) apre ComfyUI
  nel browser; c'è anche il pulsante ↗ accanto allo stato di ComfyUI in alto
- **Normale / Problemi / Dettagli** filtra i messaggi (Dettagli mostra anche i dati tecnici degli errori)
- la barra mostra il lavoro in corso con la percentuale e la **miniatura** dell'immagine che si sta generando
  (clic per vederla grande); il pulsante ⏹ lo annulla in qualsiasi momento: ComfyUI si ferma, i lavori in coda
  vengono tolti e la memoria della scheda video viene liberata; con più lavori c'è anche «annulla tutti»
- trascina il bordo superiore per ingrandirla, fai clic su *Console* per chiuderla
- il pulsante copia mette le righe visibili negli appunti: utile per chiedere aiuto

## Prossimi step

Pose guidate nelle scene di gruppo, costruttore di workflow e aggiornamenti con un clic: vedi [SVILUPPO.md](SVILUPPO.md).
