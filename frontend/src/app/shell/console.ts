import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, ElementRef, computed, effect, inject, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ApiService } from '../core/api.service';
import { AvvisiService } from '../core/avvisi.service';
import { EventiService } from '../core/eventi.service';
import { eComfy, Parte, spezzaLink } from '../core/link';
import { Livello } from '../core/modelli';
import { AnteprimaLavoro } from './anteprima-lavoro';
import { GrafoComponent, GrafoDialog } from './grafo';
import { MatDialog } from '@angular/material/dialog';

type Filtro = 'normale' | 'problemi' | 'tutto';
type Vista = 'messaggi' | 'grafo';

function leggi(chiave: string, predefinito: string): string {
  try {
    return localStorage.getItem(chiave) ?? predefinito;
  } catch {
    return predefinito;
  }
}
function scrivi(chiave: string, valore: string) {
  try {
    localStorage.setItem(chiave, valore);
  } catch {
    /* archiviazione non disponibile */
  }
}

@Component({
  selector: 'app-console',
  imports: [AnteprimaLavoro, GrafoComponent, DatePipe, DecimalPipe, FormsModule, MatButtonModule, MatIconModule, MatProgressBarModule,
    MatTooltipModule],
  templateUrl: './console.html',
  styleUrl: './console.scss',
  host: { '[class.aperta]': 'aperta()', '[style.--altezza.px]': 'altezza()' },
})
export class ConsoleComponent {
  protected eventi = inject(EventiService);
  private api = inject(ApiService);
  private avvisi = inject(AvvisiService);
  private corpo = viewChild<ElementRef<HTMLElement>>('corpo');

  protected aperta = signal(leggi('console.aperta', '1') === '1');
  protected altezza = signal(Number(leggi('console.altezza', '240')) || 240);
  protected filtro = signal<Filtro>((leggi('console.filtro', 'normale') as Filtro));
  protected cerca = signal('');
  protected segui = signal(true);
  private dialog = inject(MatDialog);

  // scheda «Grafo»: il workflow che un lavoro ha mandato a ComfyUI
  protected vista = signal<Vista>((leggi('console.vista', 'messaggi') as Vista));
  /** lavoro scelto a mano; null = segui l'ultimo che ha mandato un workflow */
  protected sceltoGrafo = signal<string | null>(null);
  protected conWorkflow = computed(() =>
    Object.values(this.eventi.lavori()).filter((l) => (l.workflow ?? 0) > 0).sort((a, b) => b.creato - a.creato));
  protected lavoroGrafo = computed(() => this.sceltoGrafo() ?? this.conWorkflow()[0]?.id ?? null);
  protected nGrafo = computed(() => this.eventi.lavori()[this.lavoroGrafo() ?? '']?.workflow ?? 0);

  protected impostaVista(v: Vista) {
    this.vista.set(v);
    scrivi('console.vista', v);
    // il grafo ha bisogno di spazio
    if (v === 'grafo' && this.altezza() < 420) this.altezza.set(Math.min(420, Math.round(window.innerHeight * 0.6)));
    if (v === 'messaggi') queueMicrotask(() => this.scorriInFondo());
  }

  /** Dalla riga del log «Workflow inviato…» al suo grafo. */
  protected vediGrafo(lavoro: string | null) {
    if (!lavoro) return;
    this.sceltoGrafo.set(lavoro);
    if (!this.aperta()) this.interruttore();
    this.impostaVista('grafo');
  }

  protected ingrandisciGrafo() {
    const id = this.lavoroGrafo();
    if (!id) return;
    this.dialog.open(GrafoDialog, { data: { lavoro: id }, width: '96vw', maxWidth: '96vw', height: '90vh',
      panelClass: 'finestra-grafo' });
  }

  private cacheLink = new Map<string, Parte[]>();

  /** Il messaggio diviso in testo e indirizzi cliccabili (in memoria: le righe non cambiano). */
  protected parti(msg: string): Parte[] {
    let p = this.cacheLink.get(msg);
    if (!p) {
      if (this.cacheLink.size > 3000) this.cacheLink.clear();
      p = spezzaLink(msg);
      this.cacheLink.set(msg, p);
    }
    return p;
  }

  protected eComfy(href: string): boolean {
    return eComfy(href, this.eventi.comfy()?.url);
  }

  protected lavoro = computed(() => this.eventi.attivi()[0] ?? null);
  protected altriAttivi = computed(() => Math.max(0, this.eventi.attivi().length - 1));

  protected righe = computed(() => {
    const f = this.filtro();
    const q = this.cerca().trim().toLowerCase();
    const ammessi: Livello[] =
      f === 'problemi' ? ['avviso', 'errore'] : f === 'tutto' ? ['debug', 'info', 'ok', 'avviso', 'errore'] : ['info', 'ok', 'avviso', 'errore'];
    const out = this.eventi.log().filter((r) => ammessi.includes(r.livello) && (!q || r.msg.toLowerCase().includes(q)));
    return out.slice(-1500);
  });

  constructor() {
    effect(() => {
      this.righe();
      if (this.segui() && this.aperta()) queueMicrotask(() => this.scorriInFondo());
    });
  }

  protected interruttore() {
    this.aperta.update((v) => !v);
    scrivi('console.aperta', this.aperta() ? '1' : '0');
  }

  protected impostaFiltro(f: Filtro) {
    this.filtro.set(f);
    scrivi('console.filtro', f);
  }

  protected scorriInFondo() {
    const el = this.corpo()?.nativeElement;
    if (el) el.scrollTop = el.scrollHeight;
  }

  protected allaRotella() {
    const el = this.corpo()?.nativeElement;
    if (!el) return;
    const inFondo = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    if (inFondo !== this.segui()) this.segui.set(inFondo);
  }

  protected async copia() {
    const testo = this.righe()
      .map((r) => `${new Date(r.ts * 1000).toLocaleTimeString()} [${r.livello}] ${r.msg}`)
      .join('\n');
    try {
      await navigator.clipboard.writeText(testo);
      this.avvisi.ok(`${this.righe().length} righe copiate`);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async annullaTutti() {
    if (!confirm(`Annullare tutti i ${this.eventi.attivi().length} lavori in corso e in coda?`)) return;
    try {
      await this.api.annullaTutti();
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async annulla(id: string) {
    try {
      await this.api.annulla(id);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected iniziaRidimensiona(ev: PointerEvent) {
    ev.preventDefault();
    const inizioY = ev.clientY;
    const inizioH = this.altezza();
    const muovi = (m: PointerEvent) => {
      const h = Math.min(window.innerHeight * 0.75, Math.max(120, inizioH + (inizioY - m.clientY)));
      this.altezza.set(Math.round(h));
    };
    const fine = () => {
      window.removeEventListener('pointermove', muovi);
      window.removeEventListener('pointerup', fine);
      scrivi('console.altezza', String(this.altezza()));
    };
    window.addEventListener('pointermove', muovi);
    window.addEventListener('pointerup', fine);
  }

  protected icona(l: Livello): string {
    return { debug: 'bug_report', info: 'info', ok: 'check_circle', avviso: 'warning', errore: 'error' }[l];
  }
}
