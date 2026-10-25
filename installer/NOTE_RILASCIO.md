## Installa Comic Studio

Scarica il file per il tuo sistema, qui sotto in **Assets**. Python, le librerie e l'interfaccia sono già dentro:
non servono né Python, né Node, né il terminale.

| Sistema | File | Come si installa |
| --- | --- | --- |
| **Windows 10 / 11** | `ComicStudio-…-Windows-Setup.exe` | Doppio clic → Avanti → Installa. Crea le icone nel menu Start e sul desktop |
| **Mac con chip Apple (M1–M4)** | `ComicStudio-…-macOS-AppleSilicon.zip` | Doppio clic sullo zip → trascina **Comic Studio** in **Applicazioni** |
| **Mac Intel** | `ComicStudio-…-macOS-Intel.zip` | Come sopra |
| **Ubuntu, Debian, Mint** | `comic-studio_…_amd64.deb` | Doppio clic → **Installa** |
| **Altre distribuzioni Linux** | `ComicStudio-…-Linux-x86_64.AppImage` | Tasto destro → Proprietà → «Consenti l'esecuzione come programma», poi doppio clic |

Al primo avvio Comic Studio si apre nel browser, trova ComfyUI e lo avvia da solo. Per chiuderlo usa il pulsante
⏻ in alto a destra.

### Il primo avvio su Windows e macOS

L'app non è firmata con un certificato a pagamento, quindi la prima volta il sistema chiede conferma (una volta sola):

- **Windows**: «Windows ha protetto il PC» → **Ulteriori informazioni** → **Esegui comunque**.
  Se compare «Smart App Control ha bloccato…», Smart App Control non permette app non firmate: va disattivato in
  Sicurezza di Windows → Controllo app e browser.
- **macOS 15 o più recente**: apri l'app, chiudi l'avviso, poi vai in **Impostazioni di Sistema → Privacy e
  sicurezza**, scorri in fondo e premi **Apri comunque**.
- **macOS 13 e 14**: tasto destro (o Ctrl+clic) sull'app → **Apri** → **Apri**.

### Aggiornare e disinstallare

- **Aggiornare**: installa la versione nuova sopra la vecchia.
- **Disinstallare**:
  - Windows: Impostazioni → App → Comic Studio → Disinstalla;
  - macOS: trascina l'app nel Cestino;
  - Linux: rimuovi il pacchetto dal Centro software.

I progetti, i LoRA e le impostazioni sono nella cartella `ComicStudio` della tua cartella utente e restano anche se
disinstalli il programma.

Il file `SHA256SUMS.txt` contiene le impronte dei file, per chi vuole verificarli.
