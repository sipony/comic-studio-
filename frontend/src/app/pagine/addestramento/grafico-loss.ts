import { DecimalPipe } from '@angular/common';
import { Component, computed, input, signal } from '@angular/core';

const L = 760;      // larghezza del disegno (viewBox)
const A = 220;      // altezza
const M = { su: 12, destra: 16, giu: 28, sinistra: 52 };

/** Andamento della loss nei passi dell'addestramento: una linea, griglia discreta, valore al passaggio del mouse. */
@Component({
  selector: 'app-grafico-loss',
  imports: [DecimalPipe],
  template: `
    <figure>
      <figcaption>Loss media durante l'addestramento</figcaption>
      @if (punti().length < 2) {
        <div class="vuoto">Il grafico compare dopo i primi passi dell'addestramento.</div>
      } @else {
        <div class="contenitore" (pointermove)="muovi($event)" (pointerleave)="sopra.set(null)">
          <svg [attr.viewBox]="'0 0 ' + L + ' ' + A" role="img"
            [attr.aria-label]="'Loss da ' + (primo()[1] | number: '1.4-4') + ' a ' + (ultimo()[1] | number: '1.4-4')">
            @for (t of tacche().y; track t.v) {
              <line class="griglia" [attr.x1]="M.sinistra" [attr.x2]="L - M.destra" [attr.y1]="t.y" [attr.y2]="t.y" />
              <text class="asse" [attr.x]="M.sinistra - 8" [attr.y]="t.y + 4" text-anchor="end">{{ t.v | number: '1.3-3' }}</text>
            }
            @for (t of tacche().x; track t.v) {
              <text class="asse" [attr.x]="t.x" [attr.y]="A - 8" text-anchor="middle">{{ t.v }}</text>
            }
            <line class="base" [attr.x1]="M.sinistra" [attr.x2]="L - M.destra" [attr.y1]="A - M.giu" [attr.y2]="A - M.giu" />
            <path class="linea" [attr.d]="percorso()" />
            @if (puntoSopra(); as p) {
              <line class="mirino" [attr.x1]="p.x" [attr.x2]="p.x" [attr.y1]="M.su" [attr.y2]="A - M.giu" />
              <circle class="punto" [attr.cx]="p.x" [attr.cy]="p.y" r="5" />
            }
          </svg>
          @if (puntoSopra(); as p) {
            <div class="suggerimento" [style.left.%]="(p.x / L) * 100" [style.top.%]="(p.y / A) * 100">
              <span>passo {{ p.passo }}</span><strong>{{ p.loss | number: '1.4-4' }}</strong>
            </div>
          }
        </div>
        <p class="nota">
          Scende in fretta e poi si appiattisce: è normale. Più che il numero conta come vengono le epoche nella prova.
        </p>
      }
    </figure>
  `,
  styles: `
    figure { margin: 0; }
    figcaption { font-size: 13px; font-weight: 600; margin-bottom: 6px; }
    .contenitore { position: relative; touch-action: none; }
    svg { width: 100%; height: auto; display: block; overflow: visible; }
    .griglia { stroke: var(--mat-sys-outline-variant); stroke-width: 1; opacity: .5; }
    .base { stroke: var(--mat-sys-outline); stroke-width: 1; }
    .asse { fill: var(--mat-sys-on-surface-variant); font-size: 11px; font-variant-numeric: tabular-nums; }
    .linea { fill: none; stroke: var(--mat-sys-primary); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
    .mirino { stroke: var(--mat-sys-on-surface-variant); stroke-width: 1; stroke-dasharray: 3 3; }
    .punto { fill: var(--mat-sys-primary); stroke: var(--mat-sys-surface-container); stroke-width: 2; }
    .suggerimento { position: absolute; transform: translate(-50%, calc(-100% - 12px)); pointer-events: none;
      display: flex; flex-direction: column; align-items: center; padding: 4px 8px; border-radius: 6px; white-space: nowrap;
      background: var(--mat-sys-inverse-surface); color: var(--mat-sys-inverse-on-surface); font-size: 11.5px; }
    .suggerimento strong { font-variant-numeric: tabular-nums; }
    .vuoto { padding: 32px 8px; text-align: center; font-size: 13px; color: var(--mat-sys-on-surface-variant);
      border: 1px dashed var(--mat-sys-outline-variant); border-radius: 10px; }
    .nota { margin: 6px 0 0; font-size: 12px; color: var(--mat-sys-on-surface-variant); }
  `,
})
export class GraficoLoss {
  readonly punti = input<[number, number][]>([]);
  readonly totale = input(0);
  protected L = L;
  protected A = A;
  protected M = M;
  protected sopra = signal<number | null>(null);

  protected primo = computed(() => this.punti()[0]);
  protected ultimo = computed(() => this.punti()[this.punti().length - 1]);

  private scale = computed(() => {
    const p = this.punti();
    const maxX = Math.max(this.totale(), p.length ? p[p.length - 1][0] : 1, 1);
    const valori = p.map((x) => x[1]);
    let min = Math.min(...valori);
    let max = Math.max(...valori);
    if (max - min < 1e-6) { min -= 0.01; max += 0.01; }
    const margine = (max - min) * 0.08;
    min = Math.max(0, min - margine);
    max += margine;
    const x = (v: number) => M.sinistra + (v / maxX) * (L - M.sinistra - M.destra);
    const y = (v: number) => M.su + (1 - (v - min) / (max - min)) * (A - M.su - M.giu);
    return { x, y, min, max, maxX };
  });

  protected percorso = computed(() => {
    const { x, y } = this.scale();
    return this.punti().map((p, i) => `${i ? 'L' : 'M'}${x(p[0]).toFixed(1)} ${y(p[1]).toFixed(1)}`).join('');
  });

  protected tacche = computed(() => {
    const { x, y, min, max, maxX } = this.scale();
    const passoY = bella((max - min) / 4);
    const ys = [];
    for (let v = Math.ceil(min / passoY) * passoY; v <= max + 1e-9; v += passoY) ys.push({ v: +v.toFixed(6), y: y(v) });
    const passoX = bella(maxX / 5);
    const xs = [];
    for (let v = 0; v <= maxX + 1e-9; v += passoX) xs.push({ v: Math.round(v), x: x(v) });
    return { y: ys, x: xs };
  });

  protected puntoSopra = computed(() => {
    const i = this.sopra();
    const p = i === null ? null : this.punti()[i];
    if (!p) return null;
    const { x, y } = this.scale();
    return { x: x(p[0]), y: y(p[1]), passo: p[0], loss: p[1] };
  });

  protected muovi(ev: PointerEvent) {
    const r = (ev.currentTarget as HTMLElement).getBoundingClientRect();
    const xv = ((ev.clientX - r.left) / r.width) * L;
    const { x } = this.scale();
    const p = this.punti();
    let migliore = 0;
    for (let i = 1; i < p.length; i++) if (Math.abs(x(p[i][0]) - xv) < Math.abs(x(p[migliore][0]) - xv)) migliore = i;
    this.sopra.set(migliore);
  }
}

/** Un passo "rotondo" (1, 2, 5 × 10^n) per le tacche degli assi. */
function bella(grezzo: number): number {
  if (!(grezzo > 0)) return 1;
  const e = Math.pow(10, Math.floor(Math.log10(grezzo)));
  const f = grezzo / e;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * e;
}
