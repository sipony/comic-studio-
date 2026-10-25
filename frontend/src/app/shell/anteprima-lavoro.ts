import { Component, HostListener, input, signal } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';
import { Lavoro } from '../core/modelli';

/** L'immagine che il lavoro sta generando (anteprima del campionamento) o l'ultima finita; clic per ingrandirla. */
@Component({
  selector: 'app-anteprima-lavoro',
  imports: [MatIconModule],
  template: `
    @if (lavoro(); as l) {
      @if (l.anteprima) {
        <button type="button" class="anteprima" [class.piccola]="piccola()" (click)="grande.set(true)"
          [attr.aria-label]="'Ingrandisci l\\'anteprima di ' + l.titolo" [title]="'Anteprima · clic per ingrandire'">
          <img [src]="url(l)" alt="" />
          @if (!piccola()) {
            <span class="etichetta"><mat-icon>visibility</mat-icon> anteprima dal vivo</span>
          }
        </button>
        @if (grande()) {
          <div class="sovrapposto" role="dialog" aria-label="Anteprima" (click)="grande.set(false)">
            <img [src]="url(l)" alt="Anteprima della generazione" />
            <span class="didascalia">{{ l.titolo }} · {{ l.testo }} · clic o Esc per chiudere</span>
          </div>
        }
      }
    }
  `,
  styles: `
    :host { display: contents; }
    .anteprima { position: relative; display: block; padding: 0; border: 1px solid var(--mat-sys-outline-variant);
      border-radius: 10px; overflow: hidden; background: var(--mat-sys-surface-container-highest); cursor: zoom-in;
      width: 100%; max-width: 360px; }
    .anteprima img { display: block; width: 100%; height: 320px; object-fit: contain; }
    .anteprima.piccola { width: 34px; height: 34px; border-radius: 6px; flex: 0 0 auto; }
    .anteprima.piccola img { width: 34px; height: 34px; object-fit: cover; }
    .etichetta { position: absolute; left: 6px; top: 6px; display: flex; align-items: center; gap: 4px;
      padding: 2px 8px; border-radius: 10px; font-size: 11.5px; background: rgb(0 0 0 / 60%); color: #fff; }
    .etichetta mat-icon { font-size: 14px; width: 14px; height: 14px; }
    .sovrapposto { position: fixed; inset: 0; z-index: 1100; display: flex; flex-direction: column; gap: 10px;
      align-items: center; justify-content: center; padding: 16px; background: rgb(0 0 0 / 82%); cursor: zoom-out; }
    .sovrapposto img { height: min(calc(100vh - 80px), 1216px); max-width: 100%; width: auto; object-fit: contain;
      border-radius: 8px; background: #111; }
    .didascalia { color: #ddd; font-size: 13px; text-align: center; }
  `,
})
export class AnteprimaLavoro {
  readonly lavoro = input<Lavoro | null>(null);
  readonly piccola = input(false);
  protected grande = signal(false);

  @HostListener('document:keydown.escape')
  protected chiudi() {
    this.grande.set(false);
  }

  protected url(l: Lavoro) {
    return `/api/lavori/${l.id}/anteprima?n=${l.anteprima}`;
  }
}
