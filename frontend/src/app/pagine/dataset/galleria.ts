import { DecimalPipe } from '@angular/common';
import { Component, HostListener, computed, inject, input, output, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatDividerModule } from '@angular/material/divider';
import { apriConfrontoGrafi } from '../../shell/confronto-grafi';
import { GrafoDialog } from '../../shell/grafo';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule } from '@angular/material/menu';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ApiService } from '../../core/api.service';
import { AvvisiService } from '../../core/avvisi.service';
import { EventiService } from '../../core/eventi.service';
import { ImmagineDataset, Lavoro, Personaggio, RiepilogoDataset, StatoImmagine } from '../../core/modelli';

type Filtro = 'tutte' | 'tenuta' | 'scartata' | 'da_decidere';
type Ordine = 'numero' | 'punteggio';

@Component({
  selector: 'app-galleria',
  imports: [DecimalPipe, MatButtonModule, MatIconModule, MatMenuModule, MatTooltipModule, MatDividerModule, MatProgressBarModule],
  templateUrl: './galleria.html',
  styleUrl: './galleria.scss',
})
export class Galleria {
  readonly progetto = input.required<string>();
  readonly personaggio = input.required<Personaggio>();
  readonly immagini = input.required<ImmagineDataset[]>();
  readonly riepilogo = input<RiepilogoDataset | null>(null);
  readonly daTenere = input(30);
  readonly lavoro = input<Lavoro | null>(null);
  readonly ricarica = output<void>();

  protected api = inject(ApiService);
  private avvisi = inject(AvvisiService);
  private eventi = inject(EventiService);
  private snack = inject(MatSnackBar);
  private dialog = inject(MatDialog);

  protected confrontaGrafi(file: string) {
    apriConfrontoGrafi(this.dialog, { progetto: this.progetto(), personaggio: this.personaggio().id, file, nome: this.personaggio().nome });
  }

  protected grafo(file: string) {
    this.dialog.open(GrafoDialog, { data: { url: this.api.urlGrafoImmagine(this.progetto(), this.personaggio().id, file) },
      width: '96vw', maxWidth: '96vw', height: '90vh', panelClass: 'finestra-grafo' });
  }
  private nomiPose = signal<Record<string, string>>({});

  constructor() {
    this.api.pose().then((r) => this.nomiPose.set(Object.fromEntries(r.pose.map((p) => [p.id, p.nome])))).catch(() => undefined);
  }

  protected nomePosa(id: string) {
    return this.nomiPose()[id] ?? id;
  }

  protected filtro = signal<Filtro>('tutte');
  protected ordine = signal<Ordine>('numero');
  protected grandi = signal(false);
  protected aperta = signal<string | null>(null);
  /** download o eliminazione in corso, con l'avanzamento (null = indefinito) */
  protected operazione = signal<{ testo: string; progresso: number | null } | null>(null);

  protected visibili = computed(() => {
    const f = this.filtro();
    let l = this.immagini().filter((i) => f === 'tutte' || (f === 'da_decidere' ? i.stato === null : i.stato === f));
    if (this.ordine() === 'punteggio') l = [...l].sort((a, b) => (b.punteggio ?? -1) - (a.punteggio ?? -1));
    else l = [...l].sort((a, b) => b.numero - a.numero);
    return l;
  });
  /** «tutte le 117 immagini», «le 30 tenute»…: su cosa agiscono Scarica ed Elimina (il filtro attuale) */
  protected etichetta = computed(() => etichettaGruppo(this.filtro(), this.visibili().length));
  protected spazio = computed(() => peso(this.riepilogo()?.byte ?? 0));
  protected cestino = computed(() => this.riepilogo()?.cestino ?? { immagini: 0, byte: 0 });
  protected pesoCestino = computed(() => peso(this.cestino().byte));
  protected corrente = computed(() => this.visibili().find((i) => i.file === this.aperta()) ?? null);
  protected haPunteggi = computed(() => this.immagini().some((i) => i.punteggio !== null));

  protected url(i: ImmagineDataset, anteprima = true) {
    return this.api.urlImmagine(this.progetto(), this.personaggio().id, i.file, anteprima) + `${anteprima ? '&' : '?'}v=${i.creato}`;
  }

  protected async stato(i: ImmagineDataset, s: StatoImmagine, ev?: Event) {
    ev?.stopPropagation();
    const nuovo = i.stato === s ? null : s;
    try {
      await this.api.statoImmagine(this.progetto(), this.personaggio().id, i.file, nuovo);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async selezioneAutomatica() {
    try {
      await this.api.selezionaAuto(this.progetto(), this.personaggio().id, this.daTenere());
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async eliminaScartate() {
    const n = this.riepilogo()?.scartate ?? 0;
    if (!n || !confirm(`Spostare nel cestino le ${n} immagini scartate?`)) return;
    try {
      await this.api.eliminaImmagini(this.progetto(), this.personaggio().id, { scartate: true });
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  /** ZIP delle immagini mostrate; con `libera` le cancella dal disco quando il download è arrivato tutto. */
  protected async scarica(libera: boolean) {
    const lista = this.visibili().map((i) => i.file);
    if (!lista.length) return;
    if (libera && !confirm(`Scaricare ${this.etichetta()} in uno ZIP e poi cancellarle dal computer?\n\n` +
      'Vengono cancellate solo quando il download è finito, e non passano dal cestino: tienile nello ZIP.')) return;
    const pers = this.personaggio().id;
    this.operazione.set({ testo: `Preparo lo ZIP con ${this.etichetta()}…`, progresso: null });
    try {
      const l = await this.api.esportaDataset(this.progetto(), pers, lista);
      const fine = await this.eventi.attendi(l.id);
      if (fine.stato !== 'completato') throw new Error(fine.errore ?? 'ZIP non preparato');
      const r = (await this.api.lavoro<Esportazione>(l.id)).risultato;
      if (!r) throw new Error('ZIP non preparato');
      const blob = await this.api.scaricaEsportazione(this.progetto(), pers, r.nome, (fatto, totale) =>
        this.operazione.set({ testo: `Scarico lo ZIP: ${peso(fatto)} di ${peso(totale || r.byte)}`, progresso: fatto / (totale || r.byte) }));
      if (blob.size < r.byte) throw new Error('Il download si è interrotto: le immagini non sono state cancellate.');
      salvaFile(blob, r.nome);
      if (libera) {
        this.operazione.set({ testo: 'Cancello le immagini scaricate…', progresso: null });
        const d = await this.api.eliminaImmagini(this.progetto(), pers, { file: r.file, definitivo: true });
        this.avvisi.ok(`${d.eliminate} immagini scaricate e cancellate: liberati ${peso(d.liberati)}`);
      } else {
        this.avvisi.ok(`ZIP scaricato: ${r.immagini} immagini, ${peso(r.byte)}`);
      }
    } catch (e) {
      this.avvisi.errore(e);
    } finally {
      this.operazione.set(null);
    }
  }

  /** Sposta nel cestino le immagini mostrate; dal messaggio si può liberare subito lo spazio. */
  protected async elimina() {
    const lista = this.visibili().map((i) => i.file);
    if (!lista.length || !confirm(`Spostare nel cestino ${this.etichetta()}?\n\nPer liberare lo spazio svuota poi il cestino del dataset.`)) return;
    try {
      const d = await this.api.eliminaImmagini(this.progetto(), this.personaggio().id, { file: lista });
      this.snack.open(`${d.eliminate} immagini nel cestino`, 'Libera lo spazio', { duration: 10000, panelClass: 'avviso-ok' })
        .onAction().subscribe(() => void this.svuota(true));
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  /** Cancella dal disco le immagini di questo dataset che sono nel cestino. */
  protected async svuota(giaChiesto = false) {
    if (!giaChiesto) {
      const c = this.cestino();
      if (!c.immagini || !confirm(`Cancellare definitivamente le ${c.immagini} immagini nel cestino di questo dataset ` +
        `(${peso(c.byte)})? Non si potranno recuperare.`)) return;
    }
    try {
      const r = await this.api.svuotaCestinoDataset(this.progetto(), this.personaggio().id);
      this.avvisi.ok(`Cestino svuotato: liberati ${peso(r.byte)}`);
      this.ricarica.emit();
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected sposta(delta: number) {
    const l = this.visibili();
    const i = l.findIndex((x) => x.file === this.aperta());
    const j = i + delta;
    if (i >= 0 && j >= 0 && j < l.length) this.aperta.set(l[j].file);
  }

  @HostListener('document:keydown', ['$event'])
  protected tasto(ev: KeyboardEvent) {
    const c = this.corrente();
    if (!c || (ev.target as HTMLElement)?.closest('input, textarea, select')) return;
    const azioni: Record<string, () => void> = {
      Escape: () => this.aperta.set(null),
      ArrowRight: () => this.sposta(1),
      ArrowLeft: () => this.sposta(-1),
      t: () => void this.stato(c, 'tenuta').then(() => this.sposta(1)),
      s: () => void this.stato(c, 'scartata').then(() => this.sposta(1)),
    };
    const a = azioni[ev.key];
    if (a) {
      ev.preventDefault();
      a();
    }
  }
}

interface Esportazione {
  nome: string;
  byte: number;
  immagini: number;
  file: string[];
}

/** Su cosa agiscono Scarica ed Elimina, secondo il filtro della galleria. */
export function etichettaGruppo(filtro: string, n: number): string {
  if (filtro === 'tenuta') return n === 1 ? 'l’immagine tenuta' : `le ${n} tenute`;
  if (filtro === 'scartata') return n === 1 ? 'l’immagine scartata' : `le ${n} scartate`;
  if (filtro === 'da_decidere') return n === 1 ? 'l’immagine da decidere' : `le ${n} da decidere`;
  return n === 1 ? 'l’unica immagine' : `tutte le ${n} immagini`;
}

/** 1.234.567 byte → «1 MB», 2,5e9 → «2,5 GB». */
export function peso(byte: number): string {
  if (byte >= 1e9) return `${(byte / 1e9).toLocaleString('it-IT', { maximumFractionDigits: 1 })} GB`;
  return `${Math.max(Math.round(byte / 1e6), byte > 0 ? 1 : 0)} MB`;
}

function salvaFile(blob: Blob, nome: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = nome;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
