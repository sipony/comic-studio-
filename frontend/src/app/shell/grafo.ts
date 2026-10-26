import { Component, ElementRef, computed, effect, inject, input, output, signal, untracked, viewChild } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ApiService } from '../core/api.service';
import { EventiService } from '../core/eventi.service';
import { NodoGrafo, WorkflowLavoro } from '../core/modelli';

/** Colori dei collegamenti per tipo, come nel tema scuro di ComfyUI. */
const COLORI: Record<string, string> = {
  MODEL: '#B39DDB', CLIP: '#FFD500', VAE: '#FF6E6E', CONDITIONING: '#FFA931', LATENT: '#FF9CF9', IMAGE: '#64B5F6',
  MASK: '#81C784', CLIP_VISION: '#A8DADC', CLIP_VISION_OUTPUT: '#AD7452', CONTROL_NET: '#6EE7B7', STYLE_MODEL: '#C2FFAE',
  NOISE: '#B0B0B0', GUIDER: '#66FFFF', SAMPLER: '#ECB4B4', SIGMAS: '#CDFFCD', IPADAPTER: '#7FB3A6', UPSCALE_MODEL: '#C9A0DC',
};
export function coloreTipo(tipo: string): string {
  if (COLORI[tipo]) return COLORI[tipo];
  let h = 0;
  for (const c of tipo) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${h} 45% 65%)`;
}

const TITOLO = 30;          // altezza della barra del titolo
const RIGA = 22;            // altezza di una riga di slot
const WIDGET = 24;          // altezza di un widget
const LARGO_MIN = 210;
const LARGO_MAX = 360;
const CAR = 6.6;            // larghezza media di un carattere a 12 px
const SPAZIO_X = 90;
const SPAZIO_Y = 36;

interface NodoDisegnato extends NodoGrafo {
  x: number;
  y: number;
  w: number;
  h: number;
  righe: number;            // righe di slot (max tra ingressi e uscite)
}

function testoValore(v: unknown): string {
  if (typeof v === 'string') return v;
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : String(Math.round(v * 1000) / 1000);
  return JSON.stringify(v);
}

function taglia(t: string, max: number): string {
  const s = t.replace(/\s+/g, ' ');
  return s.length > max ? s.slice(0, Math.max(1, max - 1)) + '…' : s;
}

/** Disposizione a colonne: ogni nodo dopo quelli da cui riceve, ordinati per ridurre gli incroci. */
function disponi(nodi: NodoGrafo[]): Map<string, NodoDisegnato> {
  const perId = new Map(nodi.map((n) => [n.id, n]));
  const livello = new Map<string, number>();
  const calcola = (id: string, pila: Set<string>): number => {
    if (livello.has(id)) return livello.get(id)!;
    if (pila.has(id)) return 0;
    pila.add(id);
    const n = perId.get(id);
    const l = n && n.ingressi.length ? 1 + Math.max(...n.ingressi.map((i) => (perId.has(i.da) ? calcola(i.da, pila) : -1))) : 0;
    pila.delete(id);
    livello.set(id, l);
    return l;
  };
  nodi.forEach((n) => calcola(n.id, new Set()));
  const colonne: NodoGrafo[][] = [];
  for (const n of nodi) (colonne[livello.get(n.id)!] ??= []).push(n);
  const out = new Map<string, NodoDisegnato>();
  // dimensioni
  for (const n of nodi) {
    const righe = Math.max(n.ingressi.length, n.uscite.length);
    let w = Math.max(LARGO_MIN, n.titolo.length * 7.4 + 48);
    for (let i = 0; i < righe; i++) {
      const a = n.ingressi[i]?.nome.length ?? 0;
      const b = n.uscite[i]?.nome.length ?? 0;
      w = Math.max(w, (a + b) * CAR + 70);
    }
    for (const x of n.widget) w = Math.max(w, Math.min(LARGO_MAX, (x.nome.length + testoValore(x.valore).length) * CAR + 50));
    w = Math.min(LARGO_MAX, Math.round(w));
    const h = TITOLO + righe * RIGA + n.widget.length * WIDGET + (n.widget.length ? 8 : 0) + 8;
    out.set(n.id, { ...n, x: 0, y: 0, w, h, righe });
  }
  // ordine nelle colonne: baricentro di chi manda il segnale (qualche passata)
  const ordine = new Map<string, number>();
  colonne.forEach((c) => c.forEach((n, i) => ordine.set(n.id, i)));
  for (let passata = 0; passata < 4; passata++) {
    for (const c of colonne.slice(1)) {
      const peso = (n: NodoGrafo) => {
        const p = n.ingressi.filter((i) => ordine.has(i.da)).map((i) => ordine.get(i.da)! + i.uscita * 0.01);
        return p.length ? p.reduce((a, b) => a + b, 0) / p.length : ordine.get(n.id)!;
      };
      c.sort((a, b) => peso(a) - peso(b));
      c.forEach((n, i) => ordine.set(n.id, i));
    }
  }
  // posizioni
  let x = 0;
  const altezze = colonne.map((c) => c.reduce((s, n) => s + out.get(n.id)!.h + SPAZIO_Y, -SPAZIO_Y));
  const alta = Math.max(0, ...altezze);
  colonne.forEach((c, i) => {
    let y = (alta - altezze[i]) / 2;
    const largo = Math.max(...c.map((n) => out.get(n.id)!.w));
    for (const n of c) {
      const d = out.get(n.id)!;
      d.x = x;
      d.y = y;
      y += d.h + SPAZIO_Y;
    }
    x += largo + SPAZIO_X;
  });
  return out;
}

/**
 * Il grafo del workflow che un lavoro ha mandato a ComfyUI, disegnato come in ComfyUI: nodi con titolo, ingressi e
 * uscite colorati per tipo, widget con i valori, collegamenti curvi. Trascina lo sfondo per spostarti, la rotella per
 * lo zoom, i titoli per spostare i nodi; clic su un nodo per vederne tutti i valori.
 */
@Component({
  selector: 'app-grafo',
  imports: [MatButtonModule, MatIconModule, MatTooltipModule],
  template: `
    <div class="barra">
      @if (dati(); as d) {
        <span class="info" [matTooltip]="d.riassunto">
          <strong>{{ d.lavoro.titolo }}</strong> · {{ d.grafo.nodi.length }} nodi
          @if (d.n > 1) { · inviato {{ d.n }} volte (cambiano prompt e seme: qui c'è l'ultimo) }
          @if (!d.grafo.da_comfy) { · <span class="nota">tipi dai nodi conosciuti (ComfyUI spento)</span> }
        </span>
      } @else if (errore()) {
        <span class="info nota">{{ errore() }}</span>
      } @else {
        <span class="info nota">Nessun workflow: compare qui quando un lavoro manda qualcosa a ComfyUI.</span>
      }
      <span class="spazio"></span>
      @if (dati()) {
        <button mat-icon-button (click)="adatta()" matTooltip="Adatta alla finestra"><mat-icon>fit_screen</mat-icon></button>
        <a mat-icon-button [href]="urlJson()" download matTooltip="Scarica il workflow (formato API): trascinalo in ComfyUI per aprirlo lì">
          <mat-icon>download</mat-icon></a>
        @if (eventi.comfy()?.connesso && eventi.comfy()?.url) {
          <a mat-icon-button [href]="eventi.comfy()!.url!" target="_blank" rel="noopener noreferrer"
            matTooltip="Apri ComfyUI (poi trascina lì il file scaricato)"><mat-icon>open_in_new</mat-icon></a>
        }
        @if (ingrandibile()) {
          <button mat-icon-button (click)="ingrandisci.emit()" matTooltip="A tutto schermo"><mat-icon>open_in_full</mat-icon></button>
        }
      }
      @if (chiudibile()) {
        <button mat-icon-button (click)="chiudi.emit()" aria-label="Chiudi" matTooltip="Chiudi"><mat-icon>close</mat-icon></button>
      }
    </div>
    <div class="tela" #tela (wheel)="rotella($event)" (pointerdown)="inizioSfondo($event)">
      <svg [attr.width]="'100%'" [attr.height]="'100%'">
        <defs>
          <pattern id="punti" [attr.width]="20 * k()" [attr.height]="20 * k()" patternUnits="userSpaceOnUse"
            [attr.x]="tx()" [attr.y]="ty()">
            <circle [attr.cx]="1" [attr.cy]="1" r="1" fill="#3a3a3a" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#punti)" />
        <g [attr.transform]="'translate(' + tx() + ',' + ty() + ') scale(' + k() + ')'">
          @for (c of linee(); track c.chiave) {
            <path [attr.d]="c.d" [attr.stroke]="c.colore" class="link" [class.acceso]="c.acceso" />
          }
          @for (n of nodi(); track n.id) {
            <g [attr.transform]="'translate(' + n.x + ',' + n.y + ')'" class="nodo" [class.scelto]="scelto()?.id === n.id"
              (pointerdown)="inizioNodo($event, n)">
              <rect [attr.width]="n.w" [attr.height]="n.h" rx="8" class="corpo" />
              <path [attr.d]="'M0,8 a8,8 0 0 1 8,-8 h' + (n.w - 16) + ' a8,8 0 0 1 8,8 v' + (titolo - 8) + ' h-' + n.w + 'z'" class="testa" />
              <circle cx="14" [attr.cy]="titolo / 2" r="4.5" class="pallino" />
              <text x="26" [attr.y]="titolo / 2 + 4" class="titolo">{{ taglia(n.titolo, (n.w - 70) / 7.2) }}</text>
              <text [attr.x]="n.w - 10" [attr.y]="titolo / 2 + 4" class="id">#{{ n.id }}</text>
              @for (i of n.ingressi; track i.nome; let r = $index) {
                <circle cx="0" [attr.cy]="titolo + r * riga + riga / 2" r="5" [attr.fill]="colore(i.tipo)" class="slot" />
                <text x="12" [attr.y]="titolo + r * riga + riga / 2 + 4" class="slot-nome">{{ i.nome }}</text>
              }
              @for (u of n.uscite; track $index; let r = $index) {
                <circle [attr.cx]="n.w" [attr.cy]="titolo + r * riga + riga / 2" r="5" [attr.fill]="colore(u.tipo)" class="slot" />
                <text [attr.x]="n.w - 12" [attr.y]="titolo + r * riga + riga / 2 + 4" class="slot-nome destra">{{ u.nome }}</text>
              }
              @for (wg of n.widget; track wg.nome; let r = $index) {
                <g [attr.transform]="'translate(10,' + (titolo + n.righe * riga + 4 + r * alto) + ')'">
                  <rect [attr.width]="n.w - 20" [attr.height]="alto - 4" rx="9" class="widget" />
                  <text x="10" [attr.y]="(alto - 4) / 2 + 4" class="w-nome">{{ taglia(wg.nome, 16) }}</text>
                  <text [attr.x]="n.w - 30" [attr.y]="(alto - 4) / 2 + 4" class="w-valore">{{ taglia(valore(wg.valore), (n.w - 40) / 6.6 - wg.nome.length - 2) }}</text>
                </g>
              }
            </g>
          }
        </g>
      </svg>
      @if (scelto(); as n) {
        <aside class="dettaglio" (pointerdown)="$event.stopPropagation()" (wheel)="$event.stopPropagation()">
          <div class="d-testa">
            <strong>#{{ n.id }} {{ n.titolo }}</strong>
            <button mat-icon-button (click)="scelto.set(null)" aria-label="Chiudi"><mat-icon>close</mat-icon></button>
          </div>
          <div class="nota">{{ n.classe }}</div>
          @for (i of n.ingressi; track i.nome) {
            <div class="d-riga"><span class="d-nome"><i [style.background]="colore(i.tipo)"></i>{{ i.nome }}</span>
              <span>← #{{ i.da }} {{ titoloDi(i.da) }} ({{ uscitaDi(i.da, i.uscita) }})</span></div>
          }
          @for (wg of n.widget; track wg.nome) {
            <div class="d-riga"><span class="d-nome">{{ wg.nome }}</span><pre>{{ valore(wg.valore) }}</pre></div>
          }
        </aside>
      }
    </div>
  `,
  styles: `
    :host { display: flex; flex-direction: column; min-height: 0; height: 100%; background: #202020; color: #ddd; }
    .barra { display: flex; align-items: center; gap: 4px; padding: 0 8px; min-height: 36px; font-size: 12.5px;
      border-bottom: 1px solid #2c2c2c; }
    .info { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .nota { color: #8a8a8a; }
    .spazio { flex: 1; }
    .tela { position: relative; flex: 1; min-height: 0; overflow: hidden; cursor: grab; touch-action: none;
      &:active { cursor: grabbing; } }
    svg { display: block; user-select: none; }
    .link { fill: none; stroke-width: 3; opacity: 0.75; &.acceso { stroke-width: 4.5; opacity: 1; } }
    .corpo { fill: #353535; stroke: #111; stroke-width: 1; }
    .testa { fill: #262626; }
    .nodo { cursor: pointer; filter: drop-shadow(0 2px 4px rgba(0, 0, 0, 0.5)); }
    .nodo.scelto .corpo { stroke: #fff; stroke-width: 1.5; }
    .pallino { fill: #5e5e5e; }
    .titolo { fill: #cfcfcf; font: 600 13px Inter, system-ui, sans-serif; }
    .id { fill: #777; font: 11px Inter, system-ui, sans-serif; text-anchor: end; }
    .slot { stroke: #1a1a1a; stroke-width: 1.5; }
    .slot-nome { fill: #a8a8a8; font: 12px Inter, system-ui, sans-serif; &.destra { text-anchor: end; } }
    .widget { fill: #222; stroke: #4a4a4a; }
    .w-nome { fill: #9a9a9a; font: 11.5px Inter, system-ui, sans-serif; }
    .w-valore { fill: #e6e6e6; font: 11.5px Inter, system-ui, sans-serif; text-anchor: end; }
    .dettaglio { position: absolute; top: 8px; right: 8px; bottom: 8px; width: min(360px, 60%); overflow: auto;
      background: #2a2a2a; border: 1px solid #444; border-radius: 10px; padding: 8px 12px; cursor: auto; font-size: 12.5px; }
    .d-testa { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
    .d-riga { display: grid; gap: 2px; padding: 6px 0; border-top: 1px solid #3a3a3a; }
    .d-nome { color: #9a9a9a; display: flex; align-items: center; gap: 6px;
      i { display: inline-block; width: 9px; height: 9px; border-radius: 50%; } }
    pre { margin: 0; white-space: pre-wrap; word-break: break-word; font: 12px 'JetBrains Mono', Consolas, monospace; color: #eee; }
  `,
})
export class GrafoComponent {
  readonly lavoro = input<string | null>(null);
  /** quante volte il lavoro ha mandato un workflow: quando cambia si ricarica */
  readonly n = input(0);
  readonly ingrandibile = input(false);
  readonly ingrandisci = output<void>();
  readonly chiudibile = input(false);
  readonly chiudi = output<void>();

  private api = inject(ApiService);
  protected eventi = inject(EventiService);
  private tela = viewChild<ElementRef<HTMLElement>>('tela');

  protected readonly titolo = TITOLO;
  protected readonly riga = RIGA;
  protected readonly alto = WIDGET;
  protected dati = signal<WorkflowLavoro | null>(null);
  protected errore = signal('');
  protected posizioni = signal(new Map<string, NodoDisegnato>());
  protected scelto = signal<NodoDisegnato | null>(null);
  protected tx = signal(20);
  protected ty = signal(20);
  protected k = signal(1);
  private caricato: string | null = null;

  protected nodi = computed(() => [...this.posizioni().values()]);
  protected linee = computed(() => {
    const pos = this.posizioni();
    const sel = this.scelto()?.id;
    return (this.dati()?.grafo.collegamenti ?? []).flatMap((c) => {
      const a = pos.get(c.da);
      const b = pos.get(c.a);
      if (!a || !b) return [];
      const r = b.ingressi.findIndex((i) => i.nome === c.ingresso);
      const x1 = a.x + a.w;
      const y1 = a.y + TITOLO + c.uscita * RIGA + RIGA / 2;
      const x2 = b.x;
      const y2 = b.y + TITOLO + Math.max(0, r) * RIGA + RIGA / 2;
      const dx = Math.max(60, Math.abs(x2 - x1) * 0.5);
      return [{ chiave: `${c.da}:${c.uscita}>${c.a}:${c.ingresso}`, colore: coloreTipo(c.tipo), acceso: sel === c.da || sel === c.a,
        d: `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}` }];
    });
  });
  protected urlJson = computed(() => this.api.urlWorkflowJson(this.dati()?.lavoro.id ?? ''));

  constructor() {
    effect(() => {
      const id = this.lavoro();
      const n = this.n();
      untracked(() => void this.carica(id, n));
    });
  }

  private async carica(id: string | null, _n: number) {
    if (!id) {
      this.dati.set(null);
      this.posizioni.set(new Map());
      return;
    }
    try {
      const d = await this.api.workflowLavoro(id);
      if (this.lavoro() !== id) return;
      const nuovo = this.caricato !== id;
      const vecchie = this.posizioni();
      const pos = disponi(d.grafo.nodi);
      // ricaricando lo stesso lavoro i nodi restano dove l'utente li ha messi
      if (!nuovo) for (const [k, v] of pos) { const o = vecchie.get(k); if (o) { v.x = o.x; v.y = o.y; } }
      this.errore.set('');
      this.dati.set(d);
      this.posizioni.set(pos);
      const s = this.scelto();
      this.scelto.set(s ? pos.get(s.id) ?? null : null);
      this.caricato = id;
      if (nuovo) queueMicrotask(() => this.adatta());
    } catch (e) {
      this.dati.set(null);
      this.errore.set(e instanceof Error ? e.message : String(e));
    }
  }

  protected adatta() {
    const el = this.tela()?.nativeElement;
    const nodi = this.nodi();
    if (!el || !nodi.length) return;
    const minX = Math.min(...nodi.map((n) => n.x));
    const minY = Math.min(...nodi.map((n) => n.y));
    const maxX = Math.max(...nodi.map((n) => n.x + n.w));
    const maxY = Math.max(...nodi.map((n) => n.y + n.h));
    const W = el.clientWidth || 800;
    const H = el.clientHeight || 300;
    const k = Math.min(1.2, Math.max(0.15, Math.min((W - 40) / (maxX - minX), (H - 40) / (maxY - minY))));
    this.k.set(k);
    this.tx.set((W - (maxX - minX) * k) / 2 - minX * k);
    this.ty.set((H - (maxY - minY) * k) / 2 - minY * k);
  }

  protected rotella(ev: WheelEvent) {
    ev.preventDefault();
    const r = (ev.currentTarget as HTMLElement).getBoundingClientRect();
    const mx = ev.clientX - r.left;
    const my = ev.clientY - r.top;
    const k0 = this.k();
    const k1 = Math.min(3, Math.max(0.1, k0 * Math.exp(-ev.deltaY * 0.0015)));
    this.tx.set(mx - ((mx - this.tx()) * k1) / k0);
    this.ty.set(my - ((my - this.ty()) * k1) / k0);
    this.k.set(k1);
  }

  protected inizioSfondo(ev: PointerEvent) {
    if (ev.button !== 0) return;
    const x0 = ev.clientX - this.tx();
    const y0 = ev.clientY - this.ty();
    let mosso = false;
    this.trascina(ev, (m) => {
      mosso = true;
      this.tx.set(m.clientX - x0);
      this.ty.set(m.clientY - y0);
    }, () => { if (!mosso) this.scelto.set(null); });
  }

  protected inizioNodo(ev: PointerEvent, n: NodoDisegnato) {
    if (ev.button !== 0) return;
    ev.stopPropagation();
    const x0 = ev.clientX;
    const y0 = ev.clientY;
    const nx = n.x;
    const ny = n.y;
    let mosso = false;
    this.trascina(ev, (m) => {
      const dx = (m.clientX - x0) / this.k();
      const dy = (m.clientY - y0) / this.k();
      if (!mosso && Math.hypot(dx, dy) < 3) return;
      mosso = true;
      const pos = new Map(this.posizioni());
      pos.set(n.id, { ...pos.get(n.id)!, x: nx + dx, y: ny + dy });
      this.posizioni.set(pos);
    }, () => { if (!mosso) this.scelto.set(this.posizioni().get(n.id) ?? null); });
  }

  private trascina(ev: PointerEvent, muovi: (m: PointerEvent) => void, fine: () => void) {
    const el = ev.currentTarget as Element;
    el.setPointerCapture?.(ev.pointerId);
    const su = () => {
      el.removeEventListener('pointermove', muovi as EventListener);
      el.removeEventListener('pointerup', su);
      el.removeEventListener('pointercancel', su);
      fine();
    };
    el.addEventListener('pointermove', muovi as EventListener);
    el.addEventListener('pointerup', su);
    el.addEventListener('pointercancel', su);
  }

  protected colore = coloreTipo;
  protected taglia(t: string, max: number) { return taglia(t, Math.floor(max)); }
  protected valore = testoValore;
  protected titoloDi(id: string) { return this.posizioni().get(id)?.titolo ?? ''; }
  protected uscitaDi(id: string, i: number) { return this.posizioni().get(id)?.uscite[i]?.nome ?? `uscita ${i}`; }
}

/** Il grafo a tutto schermo (da «Ingrandisci» nella console). */
@Component({
  selector: 'app-grafo-dialog',
  imports: [GrafoComponent, MatDialogModule],
  template: `<app-grafo [lavoro]="dati.lavoro" [n]="n()" [chiudibile]="true" (chiudi)="ref.close()" />`,
  styles: `:host { display: block; width: 100%; height: 100%; } app-grafo { height: 100%; }`,
})
export class GrafoDialog {
  protected dati = inject<{ lavoro: string }>(MAT_DIALOG_DATA);
  protected ref = inject(MatDialogRef);
  private eventi = inject(EventiService);
  protected n = computed(() => this.eventi.lavori()[this.dati.lavoro]?.workflow ?? 0);
}
