import { Component, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialog, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ApiService } from '../core/api.service';
import { ConfrontoGrafi, RigaConfrontoGrafi } from '../core/modelli';
import { GrafoComponent } from './grafo';

export interface DatiConfrontoGrafi { progetto: string; personaggio: string; file: string; nome: string }

export function apriConfrontoGrafi(dialog: MatDialog, dati: DatiConfrontoGrafi) {
  return dialog.open(ConfrontoGrafiDialog, { data: dati, width: '98vw', maxWidth: '98vw', height: '94vh', panelClass: 'finestra-grafo' });
}

/**
 * Il grafo della proposta da cui è nato il personaggio accanto a quello di un'immagine del dataset, con l'elenco delle
 * differenze nodo per nodo (i prompt tag per tag). Nei grafi: bordo arancione = valori diversi, tratteggiato = nodo
 * che c'è solo lì.
 */
@Component({
  selector: 'app-confronto-grafi',
  imports: [GrafoComponent, MatButtonModule, MatDialogModule, MatIconModule, MatTooltipModule],
  template: `
    <div class="testa">
      <mat-icon>compare</mat-icon>
      <h2>Proposta di riferimento e immagine {{ dati.file.replace('.png', '') }} del dataset di {{ dati.nome }}</h2>
      <span class="spazio"></span>
      <button mat-icon-button (click)="ref.close()" aria-label="Chiudi"><mat-icon>close</mat-icon></button>
    </div>
    @if (errore()) {
      <p class="errore">{{ errore() }}</p>
    } @else if (k(); as k) {
      <section class="differenze" [class.chiuse]="!aperte()">
        <button type="button" class="d-testa" (click)="aperte.set(!aperte())" [attr.aria-expanded]="aperte()">
          @if (k.uguali) { <mat-icon class="ok">check_circle</mat-icon> Stesso workflow, stessi valori (seme a parte) }
          @else {
            <mat-icon>difference</mat-icon> {{ sintesi() }}
          }
          <span class="spazio"></span>
          <mat-icon>{{ aperte() ? 'expand_less' : 'expand_more' }}</mat-icon>
        </button>
        @if (aperte()) {
          <ul>
            @for (r of k.righe; track $index) {
              <li [class]="r.tipo">
                <span class="etichetta">{{ etichette[r.tipo] }}</span>
                @if (r.campo === 'text' || r.solo_a || r.solo_b) {
                  <span><strong>{{ r.titolo }}</strong> · {{ r.campo }} ·
                    {{ ruoloTesto(r) }}</span>
                  <div class="tag">
                    @for (t of r.solo_a ?? []; track $index) { <span class="t meno" matTooltip="solo nella proposta">{{ t }}</span> }
                    @for (t of r.solo_b ?? []; track $index) { <span class="t piu" matTooltip="solo nel dataset">{{ t }}</span> }
                    @if (!(r.solo_a?.length) && !(r.solo_b?.length)) { <span class="nota">stessi tag, ordine diverso</span> }
                  </div>
                } @else {
                  <span>{{ r.testo }}</span>
                }
              </li>
            }
          </ul>
          <p class="nota">
            In rosso i tag che ci sono solo nella proposta, in verde quelli solo nel dataset: sono la parte variabile
            (inquadratura, angolazione, espressione, posa, sfondo). Seme e nomi dei file cambiano sempre e non si contano.
          </p>
        }
      </section>
      <div class="grafi">
        <div class="lato">
          <div class="etichetta-lato">Proposta (creazione del personaggio)</div>
          <app-grafo [url]="api.urlGrafoProposta(dati.progetto, dati.personaggio, k.file_proposta)" [evidenzia]="k.evidenzia_a" />
        </div>
        <div class="lato">
          <div class="etichetta-lato">Dataset (immagine {{ dati.file.replace('.png', '') }})</div>
          <app-grafo [url]="api.urlGrafoImmagine(dati.progetto, dati.personaggio, dati.file)" [evidenzia]="k.evidenzia_b" />
        </div>
      </div>
    } @else {
      <p class="nota attesa">Carico i due workflow…</p>
    }
  `,
  styles: `
    :host { display: flex; flex-direction: column; height: 100%; min-height: 0; background: #1b1b1b; color: #ddd; }
    .testa { display: flex; align-items: center; gap: 8px; padding: 4px 8px 4px 16px; border-bottom: 1px solid #2c2c2c; }
    h2 { margin: 0; font-size: 15px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .spazio { flex: 1; }
    .errore { padding: 16px; color: #ff8a80; }
    .attesa { padding: 16px; }
    .nota { color: #8a8a8a; font-size: 12px; margin: 6px 16px 8px; }
    .differenze { border-bottom: 1px solid #2c2c2c; max-height: 38%; overflow: auto; flex: 0 0 auto; }
    .d-testa { display: flex; align-items: center; gap: 8px; width: 100%; padding: 8px 16px; background: none; border: 0;
      color: inherit; font: inherit; font-size: 13px; cursor: pointer; text-align: left; position: sticky; top: 0; background: #1b1b1b; }
    .d-testa .ok { color: #81c784; }
    ul { list-style: none; margin: 0; padding: 0 16px; display: flex; flex-direction: column; gap: 4px; font-size: 12.5px; }
    li { display: grid; grid-template-columns: 120px 1fr; gap: 2px 10px; align-items: start; padding: 4px 0;
      border-top: 1px solid #2a2a2a; }
    li .tag { grid-column: 2; display: flex; flex-wrap: wrap; gap: 4px; }
    .etichetta { font-size: 11px; padding: 1px 6px; border-radius: 6px; background: #2c2c2c; color: #aaa; justify-self: start; }
    li.solo_b .etichetta { background: #1f3a37; color: #80cbc4; }
    li.solo_a .etichetta { background: #3a2a1f; color: #ffcc80; }
    li.valore .etichetta, li.collegamento .etichetta { background: #3d2620; color: #ff9e80; }
    .t { font: 11.5px 'JetBrains Mono', Consolas, monospace; padding: 1px 6px; border-radius: 5px; }
    .t.meno { background: #4a2020; color: #ffab91; text-decoration: line-through; }
    .t.piu { background: #1e3d24; color: #a5d6a7; }
    .grafi { flex: 1; min-height: 0; display: grid; grid-template-columns: 1fr 1fr; gap: 2px; background: #111; }
    @media (max-width: 900px) { .grafi { grid-template-columns: 1fr; grid-template-rows: 1fr 1fr; } }
    .lato { display: flex; flex-direction: column; min-height: 0; min-width: 0; }
    .etichetta-lato { padding: 4px 12px; font-size: 12px; font-weight: 600; background: #262626; color: #cfcfcf; }
    app-grafo { flex: 1; min-height: 0; }
  `,
})
export class ConfrontoGrafiDialog {
  protected dati = inject<DatiConfrontoGrafi>(MAT_DIALOG_DATA);
  protected ref = inject(MatDialogRef);
  protected api = inject(ApiService);
  protected k = signal<ConfrontoGrafi | null>(null);
  protected errore = signal('');
  protected aperte = signal(true);
  protected readonly etichette: Record<RigaConfrontoGrafi['tipo'], string> = {
    solo_a: 'solo proposta', solo_b: 'solo dataset', collegamento: 'collegamento', passa_per: 'passa per', valore: 'valore',
  };
  protected conta = computed(() => {
    const c = { solo_a: 0, solo_b: 0, collegamento: 0, passa_per: 0, valore: 0 };
    for (const r of this.k()?.righe ?? []) c[r.tipo]++;
    return c;
  });

  protected sintesi = computed(() => {
    const c = this.conta();
    const parti = [
      c.solo_b ? `${c.solo_b} nodi solo nel dataset` : '',
      c.solo_a ? `${c.solo_a} nodi solo nella proposta` : '',
      c.collegamento ? `${c.collegamento} collegamenti diversi` : '',
      c.valore ? `${c.valore} ${c.valore === 1 ? 'valore diverso' : 'valori diversi'}` : '',
    ].filter(Boolean);
    return parti.join(' · ') || 'stessi nodi, stessi valori';
  });

  constructor() {
    this.api.confrontoGrafi(this.dati.progetto, this.dati.personaggio, this.dati.file)
      .then((k) => this.k.set(k))
      .catch((e) => this.errore.set(e instanceof Error ? e.message : String(e)));
  }

  /** prompt positivo o negativo: si capisce da dove entra nel campionatore */
  protected ruoloTesto(r: RigaConfrontoGrafi) {
    const n = r.nodo_a ? this.k()?.proposta.grafo.collegamenti.find((c) => c.da === r.nodo_a) : null;
    return n?.ingresso === 'negative' ? 'prompt negativo' : n?.ingresso === 'positive' ? 'prompt positivo' : 'testo';
  }
}
