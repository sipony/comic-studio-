import { DecimalPipe } from '@angular/common';
import { Component, computed, inject, input, model, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { ApiService } from '../../core/api.service';
import { AvvisiService } from '../../core/avvisi.service';
import { EventiService } from '../../core/eventi.service';
import { ConfigDataset, Lavoro, Personaggio, RiepilogoDataset } from '../../core/modelli';

@Component({
  selector: 'app-sezione-genera',
  imports: [DecimalPipe, FormsModule, MatButtonModule, MatFormFieldModule, MatIconModule, MatInputModule, MatProgressBarModule],
  template: `
    @if (config(); as cfg) {
      <div class="due">
        <mat-form-field>
          <mat-label>Immagini da generare</mat-label>
          <input matInput type="number" min="1" max="2000" [ngModel]="cfg.quantita" (ngModelChange)="imposta('quantita', +$event)" />
          <mat-hint>Consigliate 80-120: poi tieni le migliori</mat-hint>
        </mat-form-field>
        <mat-form-field>
          <mat-label>Da tenere nel dataset</mat-label>
          <input matInput type="number" min="1" max="500" [ngModel]="cfg.da_tenere" (ngModelChange)="imposta('da_tenere', +$event)" />
          <mat-hint>20-40 bastano per un LoRA</mat-hint>
        </mat-form-field>
      </div>

      @for (p of problemi(); track p) {
        <p class="problema"><mat-icon>error</mat-icon> {{ p }}</p>
      }

      @if (lavoro(); as l) {
        <div class="in-corso">
          <div class="testo"><strong>{{ l.titolo }}</strong><span>{{ l.testo || 'in coda' }}</span></div>
          <mat-progress-bar [mode]="l.stato === 'in_coda' ? 'query' : 'determinate'" [value]="l.progresso * 100" />
          <div class="riga">
            <span>{{ l.progresso * 100 | number: '1.0-0' }}%</span>
            <button mat-stroked-button (click)="annulla(l.id)"><mat-icon>stop</mat-icon> Ferma</button>
          </div>
        </div>
      } @else {
        <div class="pulsanti">
          <button mat-flat-button (click)="genera(false)" [disabled]="!!problemi().length || avvio()">
            <mat-icon>play_arrow</mat-icon>
            {{ (riepilogo()?.totale ?? 0) > 0 ? 'Genera altre ' + cfg.quantita : 'Genera ' + cfg.quantita + ' immagini' }}
          </button>
          @if ((riepilogo()?.totale ?? 0) > 0) {
            <button mat-button (click)="genera(true)" [disabled]="!!problemi().length || avvio()">
              <mat-icon>restart_alt</mat-icon> Rifai da capo
            </button>
          }
        </div>
        <p class="nota">Puoi fermarla quando vuoi: le immagini già fatte restano. Su una GPU da 8 GB conta circa 15-30 secondi a immagine.</p>
      }
    }
  `,
  styles: `
    :host { display: flex; flex-direction: column; gap: 12px; }
    .due { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    .pulsanti { display: flex; gap: 8px; flex-wrap: wrap; }
    .nota { margin: 0; font-size: 12.5px; color: var(--mat-sys-on-surface-variant); }
    .problema { display: flex; gap: 6px; margin: 0; font-size: 13px; color: var(--cs-errore-testo); }
    .problema mat-icon { font-size: 18px; width: 18px; height: 18px; flex: 0 0 auto; }
    .in-corso { display: flex; flex-direction: column; gap: 8px; padding: 12px; border-radius: 10px;
      background: color-mix(in srgb, var(--mat-sys-primary) 8%, transparent); }
    .in-corso .testo { display: flex; flex-direction: column; font-size: 13px; gap: 2px; }
    .in-corso .testo span { color: var(--mat-sys-on-surface-variant); }
    .riga { display: flex; justify-content: space-between; align-items: center; font-variant-numeric: tabular-nums; }
  `,
})
export class SezioneGenera {
  readonly progetto = input.required<string>();
  readonly personaggio = input.required<Personaggio>();
  readonly config = model.required<ConfigDataset | null>();
  readonly riepilogo = input<RiepilogoDataset | null>(null);
  readonly lavoro = input<Lavoro | null>(null);
  readonly prima = input<() => Promise<boolean>>(async () => true);

  private api = inject(ApiService);
  private avvisi = inject(AvvisiService);
  private eventi = inject(EventiService);
  protected avvio = signal(false);

  protected problemi = computed(() => {
    const out: string[] = [];
    if (!this.config()?.workflow) out.push('Scegli o crea un workflow nella sezione 1.');
    if (!this.personaggio().riferimento) out.push(`${this.personaggio().nome} non ha un'immagine di riferimento (pagina Personaggi).`);
    if (!this.eventi.comfy()?.connesso) out.push('ComfyUI non è connesso: avvialo (vedi pagina Sistema).');
    return out;
  });

  protected imposta<K extends keyof ConfigDataset>(k: K, v: ConfigDataset[K]) {
    if (typeof v === 'number' && (!Number.isFinite(v) || v < 1)) return;
    this.config.update((c) => (c ? { ...c, [k]: v } : c));
  }

  protected async genera(sostituisci: boolean) {
    const cfg = this.config();
    if (!cfg) return;
    if (sostituisci && !confirm('Spostare nel cestino tutte le immagini di questo personaggio e rigenerarle?')) return;
    this.avvio.set(true);
    try {
      if (!(await this.prima()())) return;
      await this.api.genera(this.progetto(), this.personaggio().id, cfg.quantita, sostituisci);
    } catch (e) {
      this.avvisi.errore(e);
    } finally {
      this.avvio.set(false);
    }
  }

  protected async annulla(id: string) {
    try {
      await this.api.annulla(id);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }
}
