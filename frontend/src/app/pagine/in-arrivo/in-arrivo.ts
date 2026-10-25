import { Component, computed, input } from '@angular/core';
import { MatIconModule } from '@angular/material/icon';

const PASSI: Record<string, { numero: number; titolo: string; icona: string; pr: number; cosa: string[] }> = {
  dataset: {
    numero: 1, titolo: 'Dataset', icona: 'photo_library', pr: 2,
    cosa: [
      'Carichi un workflow di ComfyUI per ogni personaggio (formato normale o API) e il programma ne riconosce i nodi.',
      'Scegli quante immagini generare e le varianti: inquadrature, angolazioni, espressioni, pose, sfondi.',
      'Segui la generazione con avanzamento e log; vedi le anteprime e tieni o scarti con un clic.',
      'Selezione automatica delle immagini più somiglianti al riferimento e senza doppioni.',
    ],
  },
  didascalie: {
    numero: 2, titolo: 'Didascalie', icona: 'sell', pr: 3,
    cosa: [
      'Tag automatici con WD14 e trigger word in testa a ogni didascalia.',
      'Tabella delle frequenze: togli con un clic i tratti fissi (capelli, divisa…) da tutte le immagini.',
      'Modifica a mano di ogni didascalia accanto alla sua immagine.',
    ],
  },
  addestramento: {
    numero: 3, titolo: 'Addestramento', icona: 'model_training', pr: 4,
    cosa: [
      'Installazione automatica di kohya sd-scripts.',
      'Parametri principali con preset per la tua VRAM e sezione avanzata con tutto il resto.',
      'Log in diretta, avanzamento, tempo rimanente e grafico della loss.',
      'Griglia di test delle epoche e scelta del LoRA migliore con un clic.',
    ],
  },
  fumetto: {
    numero: 4, titolo: 'Fumetto', icona: 'auto_stories', pr: 5,
    cosa: [
      'Storia scritta per pagine e vignette, con i personaggi presenti in ogni scena.',
      'Scene con più personaggi: ognuno con il suo LoRA nella sua zona della vignetta, pose guidate.',
      'Balloon, didascalie, impaginazione delle tavole e rigenerazione di una singola vignetta.',
    ],
  },
};

@Component({
  selector: 'app-in-arrivo',
  imports: [MatIconModule],
  template: `
    <div class="pagina">
      @if (info(); as i) {
        <div class="intestazione">
          <div>
            <h1>Step {{ i.numero }} · {{ i.titolo }}</h1>
            <p class="sotto">Questo step arriva con la PR {{ i.pr }}. Ecco cosa farà:</p>
          </div>
        </div>
        <ul class="elenco">
          @for (c of i.cosa; track $index) {
            <li><mat-icon>check</mat-icon><span>{{ c }}</span></li>
          }
        </ul>
      } @else {
        <h1>Pagina inesistente</h1>
      }
    </div>
  `,
  styles: `
    .elenco { list-style: none; padding: 0; margin: 24px 0; display: flex; flex-direction: column; gap: 12px; max-width: 760px; }
    .elenco li { display: flex; gap: 12px; padding: 14px 16px; border-radius: 12px;
      background: var(--mat-sys-surface-container); border: 1px solid var(--mat-sys-outline-variant); }
    .elenco mat-icon { color: var(--mat-sys-primary); flex: 0 0 auto; }
  `,
})
export class InArrivoPage {
  readonly passo = input<string>('');
  protected info = computed(() => PASSI[this.passo()] ?? null);
}
