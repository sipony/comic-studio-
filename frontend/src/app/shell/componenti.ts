import { DecimalPipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { ApiService } from '../core/api.service';
import { AvvisiService } from '../core/avvisi.service';
import { EventiService } from '../core/eventi.service';

const GB = 1024 ** 3;

/** Finestra che propone di installare IPAdapter Plus (nodo e modelli), con lo spazio che serve. */
@Component({
  selector: 'app-componenti',
  imports: [DecimalPipe, MatButtonModule, MatDialogModule, MatIconModule, MatProgressBarModule],
  template: `
    <h2 mat-dialog-title><mat-icon>face_retouching_natural</mat-icon> Installare IPAdapter Plus?</h2>
    <mat-dialog-content>
      @if (stato(); as s) {
        @if (fatto()) {
          <p class="esito ok"><mat-icon>check_circle</mat-icon> IPAdapter Plus è installato.</p>
          @if (riavvio() === 'a_mano') {
            <p class="avviso"><mat-icon>restart_alt</mat-icon>
              Riavvia ComfyUI per caricare il nodo: {{ s.comfy_avviato_da_noi ? 'quando finiscono gli altri lavori, da Sistema → Connessione → Riavvia.' : 'è aperto fuori da Comic Studio, chiudilo e riaprilo.' }}</p>
          } @else if (riavvio() === 'fatto') {
            <p class="nota">ComfyUI è stato riavviato e ha caricato il nodo.</p>
          }
        } @else {
          <p>
            Senza IPAdapter il dataset nasce solo dal testo e i volti cambiano da un'immagine all'altra. Con IPAdapter
            Comic Studio usa l'immagine di riferimento e il personaggio somiglia molto di più. Mancano:
          </p>
          <ul class="elenco">
            @for (c of s.mancanti; track c.id) {
              <li>
                <mat-icon>{{ c.tipo === 'nodo' ? 'extension' : 'deployed_code' }}</mat-icon>
                <div><strong>{{ c.nome }}</strong> <span class="peso">{{ peso(c.byte) }}</span>
                  <div class="nota">{{ c.descrizione }} · in {{ c.cartella }}</div></div>
              </li>
            }
          </ul>
          @for (d of s.spazio; track d.cartella) {
            <p class="spazio" [class.poco]="!d.basta">
              <mat-icon>{{ d.basta ? 'hard_drive' : 'error' }}</mat-icon>
              <span>Servono {{ d.serve / gb | number: '1.1-1' }} GB (compreso 1 GB di margine), liberi
                {{ d.libero / gb | number: '1.1-1' }} GB su <code>{{ d.cartella }}</code></span>
            </p>
          }
          @if (!s.basta_spazio) {
            <p class="avviso errore"><mat-icon>warning</mat-icon>
              <span>Non c'è abbastanza spazio: libera almeno {{ mancaSpazio() / gb | number: '1.1-1' }} GB e riprova. Puoi
              eliminare i modelli dell'IA che non usi (Sistema → IA locale) o svuotare il cestino dei dataset.</span></p>
          }
          @if (s.mancanti.some(nodo)) {
            <p class="nota">
              Il nodo si carica riavviando ComfyUI:
              {{ s.comfy_avviato_da_noi ? 'Comic Studio lo riavvia da solo alla fine (se non ci sono altri lavori in corso).' :
                (s.comfy_connesso ? 'ComfyUI è aperto fuori da Comic Studio, dovrai riavviarlo tu.' : 'lo farà alla prossima apertura.') }}
            </p>
          }
          @if (lavoro(); as l) {
            <div class="avanzamento">
              <span>{{ l.testo || 'in coda' }}</span>
              <mat-progress-bar [mode]="l.progresso > 0 ? 'determinate' : 'indeterminate'" [value]="l.progresso * 100" />
            </div>
          }
          @if (errore()) { <p class="avviso errore"><mat-icon>error</mat-icon> {{ errore() }}</p> }
        }
      }
    </mat-dialog-content>
    <mat-dialog-actions>
      @if (fatto()) {
        <button mat-flat-button (click)="ref.close()">Chiudi</button>
      } @else if (inCorso()) {
        <button mat-stroked-button (click)="ferma()"><mat-icon>stop</mat-icon> Ferma</button>
      } @else {
        <button mat-button (click)="nonChiedere()">Non chiedere più</button>
        <button mat-button (click)="ref.close()">Non ora</button>
        <button mat-flat-button (click)="installa()" [disabled]="!stato()?.basta_spazio || !!stato()?.errore">
          <mat-icon>download</mat-icon> Installa ({{ peso(stato()?.totale ?? 0) }})
        </button>
      }
    </mat-dialog-actions>
  `,
  styles: `
    h2 { display: flex; align-items: center; gap: 8px; }
    .elenco { list-style: none; padding: 0; margin: 8px 0 12px; display: grid; gap: 8px;
      li { display: flex; gap: 10px; align-items: flex-start; } }
    .peso { color: var(--mat-sys-on-surface-variant); font-size: 13px; margin-left: 6px; }
    .nota { color: var(--mat-sys-on-surface-variant); font-size: 13px; }
    .spazio, .avviso, .esito { display: flex; gap: 8px; align-items: flex-start; font-size: 13.5px;
      code { overflow-wrap: anywhere; font-size: 12px; } mat-icon { flex: none; } }
    .spazio.poco, .errore { color: var(--mat-sys-error); }
    .esito.ok mat-icon { color: var(--cs-ok); }
    .avanzamento { display: grid; gap: 6px; margin-top: 8px; font-size: 13px; }
  `,
})
export class ComponentiComponent {
  protected ref = inject<MatDialogRef<ComponentiComponent>>(MatDialogRef);
  private api = inject(ApiService);
  private avvisi = inject(AvvisiService);
  private eventi = inject(EventiService);
  protected readonly gb = GB;

  protected stato = this.eventi.componenti;
  protected idLavoro = signal<string | null>(this.eventi.componenti()?.lavoro ?? null);
  protected errore = signal('');
  protected riavvio = signal<string | null>(null);
  protected lavoro = computed(() => {
    const id = this.idLavoro();
    return id ? (this.eventi.lavori()[id] ?? null) : null;
  });
  protected inCorso = computed(() => ['in_coda', 'in_corso'].includes(this.lavoro()?.stato ?? ''));
  protected fatto = computed(() => !!this.stato() && !this.stato()!.mancanti.length && !this.inCorso());

  protected nodo = (c: { tipo: string }) => c.tipo === 'nodo';
  protected mancaSpazio = computed(() =>
    (this.stato()?.spazio ?? []).reduce((s, d) => s + Math.max(0, d.serve - d.libero), 0));

  protected peso(byte: number): string {
    return byte >= GB ? `${(byte / GB).toFixed(1).replace('.', ',')} GB` : `${Math.max(1, Math.round(byte / 1024 ** 2))} MB`;
  }

  protected async installa() {
    this.errore.set('');
    try {
      const l = await this.api.installaComponenti();
      this.idLavoro.set(l.id);
      const fine = await this.eventi.attendi(l.id);
      if (fine.stato === 'completato') {
        const r = await this.api.lavoro<{ riavvio: string | null }>(l.id);
        this.riavvio.set(r.risultato?.riavvio ?? null);
        this.avvisi.ok('IPAdapter Plus installato');
      } else if (fine.stato === 'errore') {
        this.errore.set(fine.errore ?? 'Installazione non riuscita');
      }
      this.eventi.componenti.set(await this.api.componenti());
    } catch (e) {
      this.errore.set(e instanceof Error ? e.message : String(e));
    }
  }

  protected async ferma() {
    const id = this.idLavoro();
    if (id) await this.api.annulla(id).catch(() => undefined);
  }

  protected async nonChiedere() {
    try {
      await this.api.chiediComponenti(false);
      this.avvisi.ok('Non te lo chiedo più: puoi installarlo da Sistema → Controllo');
    } catch (e) {
      this.avvisi.errore(e);
    }
    this.ref.close();
  }
}
