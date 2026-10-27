import { DecimalPipe, PercentPipe } from '@angular/common';
import { Component, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ApiService } from '../../core/api.service';
import { AvvisiService } from '../../core/avvisi.service';
import { EventiService } from '../../core/eventi.service';
import { AnteprimaTrasformazione, DefinizioneTrasformazione, Personaggio, Trasformazione } from '../../core/modelli';
import { AnteprimaLavoro } from '../../shell/anteprima-lavoro';
import { GrafoDialog } from '../../shell/grafo';

const NUOVA: DefinizioneTrasformazione = {
  nome: '', tag_b: '', togli: '', negativo_b: '', lora: null, forza_lora: 0.8, passi: 5, inizio: 0.3, fine: 0.85,
};

/**
 * Trasformazioni del personaggio: dallo stato A (com'è, il riferimento) a uno stato B descritto con tag e, se serve,
 * una LoRA. Si genera la sequenza A → B (stesso seme, stessa inquadratura), si scarica come GIF, e un fotogramma
 * può diventare un personaggio a sé per lo stato B. Cosa c'è nello stato B lo decidono solo i tag e la LoRA scelti.
 */
@Component({
  selector: 'app-trasformazioni',
  imports: [AnteprimaLavoro, DecimalPipe, PercentPipe, FormsModule, MatButtonModule, MatFormFieldModule, MatIconModule,
    MatInputModule, MatProgressBarModule, MatSelectModule, MatTooltipModule],
  template: `
    <div class="testa">
      <h3><mat-icon>auto_fix_high</mat-icon> Trasformazioni</h3>
      <span class="nota">da {{ personaggio().nome }} a un altro stato (es. il mostro), in più passi</span>
      <span class="spazio"></span>
      @if (!bozza()) {
        <button mat-stroked-button (click)="nuova()" [disabled]="!personaggio().riferimento"
          [matTooltip]="personaggio().riferimento ? '' : 'Serve l\\'immagine di riferimento: è lo stato A'">
          <mat-icon>add</mat-icon> Nuova trasformazione</button>
      }
    </div>

    @if (bozza(); as b) {
      <div class="editor">
        <div class="riga">
          <mat-form-field class="corto">
            <mat-label>Nome dello stato B</mat-label>
            <input matInput [ngModel]="b.nome" (ngModelChange)="cambia({ nome: $event })" maxlength="60" placeholder="Il mostro" />
          </mat-form-field>
          <mat-form-field class="ck">
            <mat-label>LoRA della trasformazione (facoltativa)</mat-label>
            <mat-select [value]="b.lora" (valueChange)="cambia({ lora: $event })">
              <mat-option [value]="null">— nessuna —</mat-option>
              @for (m of lora(); track m) { <mat-option [value]="m">{{ m }}</mat-option> }
            </mat-select>
            <mat-hint>Sale da 0 alla sua forza lungo la sequenza</mat-hint>
          </mat-form-field>
          @if (b.lora) {
            <mat-form-field class="numero">
              <mat-label>Forza</mat-label>
              <input matInput type="number" min="0" max="2" step="0.05" [ngModel]="b.forza_lora" (ngModelChange)="cambia({ forza_lora: num($event, 0, 2, 0.8) })" />
            </mat-form-field>
          }
        </div>
        <mat-form-field class="pieno">
          <mat-label>Come diventa: tag dello stato B (in inglese)</mat-label>
          <textarea matInput rows="3" [ngModel]="b.tag_b" (ngModelChange)="cambia({ tag_b: $event })" maxlength="3000"
            placeholder="monster, transformation, grey skin, glowing eyes, claws, torn cassock"></textarea>
          <mat-hint>Li decidi tu: valgono solo per la trasformazione, non per il dataset né per le altre immagini</mat-hint>
        </mat-form-field>
        <div class="riga">
          <mat-form-field class="meta">
            <mat-label>Tag di A che nello stato B non valgono più</mat-label>
            <input matInput [ngModel]="b.togli" (ngModelChange)="cambia({ togli: $event })" placeholder="handsome, neutral expression" />
          </mat-form-field>
          <mat-form-field class="meta">
            <mat-label>Negativo in più per lo stato B</mat-label>
            <input matInput [ngModel]="b.negativo_b" (ngModelChange)="cambia({ negativo_b: $event })" placeholder="cute" />
          </mat-form-field>
        </div>
        <div class="riga">
          <mat-form-field class="numero">
            <mat-label>Passi</mat-label>
            <mat-select [value]="b.passi" (valueChange)="cambia({ passi: $event })">
              @for (n of [3, 4, 5, 6, 8, 10, 12]; track n) { <mat-option [value]="n">{{ n }}</mat-option> }
            </mat-select>
          </mat-form-field>
          <mat-form-field class="numero">
            <mat-label>Cambio iniziale</mat-label>
            <input matInput type="number" min="0.05" max="1" step="0.05" [ngModel]="b.inizio" (ngModelChange)="cambia({ inizio: num($event, 0.05, 1, 0.3) })" />
          </mat-form-field>
          <mat-form-field class="numero">
            <mat-label>Cambio finale</mat-label>
            <input matInput type="number" min="0.05" max="1" step="0.05" [ngModel]="b.fine" (ngModelChange)="cambia({ fine: num($event, 0.05, 1, 0.85) })" />
          </mat-form-field>
          <span class="nota spiega">Quanto ogni fotogramma si allontana dal riferimento (denoise): poco all'inizio, tanto alla
            fine. Più alto il finale, più lo stato B può essere diverso (forma del corpo, posa).</span>
        </div>
        @if (anteprima(); as a) {
          @if (a.errore) {
            <div class="riga">
              <span class="avviso">{{ a.errore }}</span>
              <mat-form-field class="ck">
                <mat-label>Checkpoint</mat-label>
                <mat-select [value]="checkpoint()" (valueChange)="checkpoint.set($event); aggiornaAnteprima()">
                  @for (m of checkpointElenco(); track m) { <mat-option [value]="m">{{ m }}</mat-option> }
                </mat-select>
              </mat-form-field>
            </div>
          } @else {
            <div class="prompt">
              <div><strong>A</strong> <code>{{ a.prompt_a }}</code></div>
              <div><strong>B</strong> <code>{{ a.prompt_b }}</code></div>
              <div class="nota">Negativo B: {{ a.negativo_b }}</div>
              <div class="passi">
                @for (f of a.fotogrammi; track $index) {
                  <span class="chip">{{ f.t | percent }} B · denoise {{ f.denoise | number: '1.2-2' }}</span>
                }
              </div>
            </div>
          }
        }
        <div class="azioni">
          <button mat-flat-button (click)="salva()" [disabled]="!b.nome.trim() || !b.tag_b.trim() || b.fine < b.inizio || occupato()">
            <mat-icon>save</mat-icon> Salva</button>
          <button mat-button (click)="bozza.set(null); idBozza.set(null)">Annulla</button>
          @if (b.fine < b.inizio) { <span class="avviso">Il cambio finale deve essere almeno quello iniziale.</span> }
        </div>
      </div>
    }

    @for (x of elenco(); track x.id) {
      <div class="trasformazione">
        <div class="t-testa">
          <strong>{{ personaggio().nome }} → {{ x.nome }}</strong>
          <span class="nota">{{ x.passi }} passi{{ x.lora ? ' · ' + x.lora + ' ' + x.forza_lora : '' }}{{ x.seme !== null ? ' · seme ' + x.seme : '' }}</span>
          <span class="spazio"></span>
          <button mat-icon-button (click)="modifica(x)" matTooltip="Modifica" aria-label="Modifica"><mat-icon>edit</mat-icon></button>
          <button mat-icon-button (click)="elimina(x)" matTooltip="Sposta nel cestino" aria-label="Elimina"><mat-icon>delete</mat-icon></button>
        </div>
        <div class="tag-b nota">{{ x.tag_b }}</div>
        @if (lavoroDi(x); as l) {
          <div class="in-corso">
            <span>{{ l.testo || 'in coda' }}</span>
            <mat-progress-bar [mode]="l.stato === 'in_coda' ? 'query' : 'determinate'" [value]="l.progresso * 100" />
            <app-anteprima-lavoro [lavoro]="l" />
          </div>
        }
        @if (x.fotogrammi.length) {
          <div class="striscia">
            @for (f of x.fotogrammi; track f.file) {
              <figure>
                <img [src]="api.urlFotogramma(progetto(), personaggio().id, x.id, f.file, versione())" [alt]="x.nome + ' ' + (f.t | percent)" loading="lazy" (click)="apri.set({ x, f: f.file })" />
                <figcaption>
                  <span>{{ f.t | percent }}</span>
                  <button mat-icon-button (click)="grafo(x, f.file)" matTooltip="Workflow di questo fotogramma" aria-label="Grafo"><mat-icon>account_tree</mat-icon></button>
                  <button mat-icon-button (click)="statoB(x, f.file)" [disabled]="occupato()" matTooltip="Crea un personaggio a sé da questo fotogramma (riferimento dello stato B, con il suo dataset)" aria-label="Crea personaggio"><mat-icon>person_add</mat-icon></button>
                </figcaption>
              </figure>
            }
          </div>
        }
        <div class="azioni">
          <button mat-flat-button (click)="genera(x, false)" [disabled]="!!lavoroDi(x) || !eventi.comfy()?.connesso || occupato()">
            <mat-icon>play_arrow</mat-icon> {{ x.fotogrammi.length ? 'Rigenera (stesso seme)' : 'Genera la sequenza' }}</button>
          @if (x.fotogrammi.length) {
            <button mat-button (click)="genera(x, true)" [disabled]="!!lavoroDi(x) || !eventi.comfy()?.connesso || occupato()">
              <mat-icon>casino</mat-icon> Nuovo seme</button>
            <a mat-button [href]="api.urlGif(progetto(), personaggio().id, x.id)" download><mat-icon>gif</mat-icon> Scarica GIF</a>
          }
        </div>
      </div>
    } @empty {
      @if (!bozza()) {
        <p class="nota">Nessuna trasformazione. Esempio: un prete che diventa un mostro. Lo stato A è {{ personaggio().nome }}
          com'è; lo stato B lo descrivi tu, con i tag e (se vuoi) una LoRA.</p>
      }
    }

    @if (apri(); as a) {
      <div class="lightbox" (click)="apri.set(null)" role="dialog" aria-modal="true">
        <img [src]="api.urlFotogramma(progetto(), personaggio().id, a.x.id, a.f, versione())" alt="Fotogramma" />
      </div>
    }
  `,
  styles: `
    :host { display: flex; flex-direction: column; gap: 10px; grid-column: 1 / -1; padding-top: 14px;
      border-top: 1px solid var(--mat-sys-outline-variant); }
    .testa { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    h3 { display: flex; align-items: center; gap: 6px; margin: 0; font-size: 15px; }
    .nota { font-size: 12.5px; color: var(--mat-sys-on-surface-variant); }
    .spazio { flex: 1; }
    .avviso { color: var(--cs-errore-testo); font-size: 12.5px; }
    .editor { display: flex; flex-direction: column; gap: 4px; padding: 12px; border-radius: 10px;
      background: var(--mat-sys-surface-container-high); }
    .riga { display: flex; gap: 8px 12px; flex-wrap: wrap; align-items: center; }
    .ck { flex: 1 1 260px; }
    .corto { flex: 0 1 220px; }
    .meta { flex: 1 1 240px; }
    .numero { flex: 0 0 120px; }
    .pieno { width: 100%; }
    .spiega { flex: 1 1 240px; }
    .prompt { display: flex; flex-direction: column; gap: 4px; font-size: 12.5px; }
    .prompt code { font-size: 12px; }
    .passi { display: flex; gap: 6px; flex-wrap: wrap; }
    .chip { font-size: 11.5px; padding: 2px 8px; border-radius: 10px; background: var(--mat-sys-surface-container-highest); }
    .azioni { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .trasformazione { display: flex; flex-direction: column; gap: 8px; padding: 12px; border-radius: 10px;
      border: 1px solid var(--mat-sys-outline-variant); }
    .t-testa { display: flex; align-items: center; gap: 10px; }
    .tag-b { font-family: 'JetBrains Mono', Consolas, monospace; font-size: 11.5px; }
    .in-corso { display: flex; flex-direction: column; gap: 6px; font-size: 12.5px; }
    .striscia { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(110px, 1fr); gap: 8px; overflow-x: auto;
      padding-bottom: 4px; }
    figure { margin: 0; display: flex; flex-direction: column; gap: 2px; }
    figure img { width: 100%; aspect-ratio: 832 / 1216; object-fit: cover; border-radius: 8px; cursor: zoom-in;
      background: var(--mat-sys-surface-container-highest); }
    figcaption { display: flex; align-items: center; font-size: 12px; color: var(--mat-sys-on-surface-variant); }
    figcaption span { flex: 1; }
    .lightbox { position: fixed; inset: 0; z-index: 1000; background: rgba(0, 0, 0, 0.85); display: flex;
      align-items: center; justify-content: center; cursor: zoom-out; }
    .lightbox img { max-width: 94vw; max-height: 94vh; border-radius: 8px; }
  `,
})
export class TrasformazioniComponent {
  readonly progetto = input.required<string>();
  readonly personaggio = input.required<Personaggio>();
  /** creato un personaggio dallo stato B */
  readonly nuovoPersonaggio = output<Personaggio>();

  protected api = inject(ApiService);
  private avvisi = inject(AvvisiService);
  protected eventi = inject(EventiService);
  private dialog = inject(MatDialog);

  protected elenco = signal<Trasformazione[]>([]);
  protected bozza = signal<DefinizioneTrasformazione | null>(null);
  protected idBozza = signal<string | null>(null);
  protected anteprima = signal<AnteprimaTrasformazione | null>(null);
  protected lora = signal<string[]>([]);
  protected checkpointElenco = signal<string[]>([]);
  protected checkpoint = signal<string | null>(null);
  protected occupato = signal(false);
  protected versione = signal(0);
  protected apri = signal<{ x: Trasformazione; f: string } | null>(null);
  private timer: ReturnType<typeof setTimeout> | null = null;

  protected lavori = computed(() => this.eventi.attivi().filter((l) => l.tipo === 'trasformazione' && l.progetto === this.progetto()));

  constructor() {
    effect(() => {
      this.personaggio().id;
      untracked(() => void this.carica());
    });
    effect(() => {
      const e = this.eventi.trasformazioni();
      if (e && e.progetto === untracked(this.progetto) && e.personaggio === untracked(this.personaggio).id) {
        untracked(() => { this.versione.update((v) => v + 1); void this.carica(); });
      }
    });
  }

  private async carica() {
    try {
      this.elenco.set(await this.api.trasformazioni(this.progetto(), this.personaggio().id));
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  private async caricaModelli() {
    try {
      const m = await this.api.modelli();
      this.lora.set(m['loras'] ?? []);
      this.checkpointElenco.set(m['checkpoints'] ?? []);
    } catch {
      /* ComfyUI spento: elenchi vuoti */
    }
  }

  protected lavoroDi(x: Trasformazione) {
    return this.lavori().find((l) => l.titolo.includes(`«${x.nome}»`) && l.titolo.endsWith(this.personaggio().nome)) ?? null;
  }

  protected num(v: string, min: number, max: number, ripiego: number) {
    const n = Number(String(v).replace(',', '.'));
    return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : ripiego;
  }

  protected nuova() {
    this.idBozza.set(null);
    this.bozza.set({ ...NUOVA });
    void this.caricaModelli();
    this.aggiornaAnteprima();
  }

  protected modifica(x: Trasformazione) {
    const { nome, tag_b, togli, negativo_b, lora, forza_lora, passi, inizio, fine } = x;
    this.idBozza.set(x.id);
    this.bozza.set({ nome, tag_b, togli, negativo_b, lora, forza_lora, passi, inizio, fine });
    void this.caricaModelli();
    this.aggiornaAnteprima();
  }

  protected cambia(v: Partial<DefinizioneTrasformazione>) {
    this.bozza.update((b) => (b ? { ...b, ...v } : b));
    this.aggiornaAnteprima();
  }

  protected aggiornaAnteprima() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      const b = this.bozza();
      if (!b) return;
      const d = { ...b, nome: b.nome || 'B', tag_b: b.tag_b || '…', fine: Math.max(b.fine, b.inizio) };
      this.api.anteprimaTrasformazione(this.progetto(), this.personaggio().id, d, this.checkpoint())
        .then((a) => this.anteprima.set(a)).catch(() => this.anteprima.set(null));
    }, 350);
  }

  protected async salva() {
    const b = this.bozza();
    if (!b) return;
    this.occupato.set(true);
    try {
      const id = this.idBozza();
      if (id) await this.api.modificaTrasformazione(this.progetto(), this.personaggio().id, id, b);
      else await this.api.creaTrasformazione(this.progetto(), this.personaggio().id, b);
      this.bozza.set(null);
      this.idBozza.set(null);
      await this.carica();
    } catch (e) {
      this.avvisi.errore(e);
    } finally {
      this.occupato.set(false);
    }
  }

  protected async elimina(x: Trasformazione) {
    if (!confirm(`Spostare nel cestino la trasformazione «${x.nome}» e i suoi fotogrammi?`)) return;
    try {
      await this.api.eliminaTrasformazione(this.progetto(), this.personaggio().id, x.id);
      await this.carica();
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async genera(x: Trasformazione, nuovoSeme: boolean) {
    this.occupato.set(true);
    try {
      await this.api.generaTrasformazione(this.progetto(), this.personaggio().id, x.id,
        { nuovo_seme: nuovoSeme, checkpoint: this.checkpoint() });
    } catch (e) {
      this.avvisi.errore(e);
    } finally {
      this.occupato.set(false);
    }
  }

  protected grafo(x: Trasformazione, file: string) {
    this.dialog.open(GrafoDialog, { data: { url: this.api.urlGrafoFotogramma(this.progetto(), this.personaggio().id, x.id, file) },
      width: '96vw', maxWidth: '96vw', height: '90vh', panelClass: 'finestra-grafo' });
  }

  protected async statoB(x: Trasformazione, file: string) {
    if (!confirm(`Creare il personaggio «${this.personaggio().nome} (${x.nome})» con questo fotogramma come riferimento?`)) return;
    this.occupato.set(true);
    try {
      const r = await this.api.personaggioDaStatoB(this.progetto(), this.personaggio().id, x.id, file);
      this.avvisi.ok(`Creato «${r.personaggio.nome}»: il suo dataset è già pronto come le sue «proposte»`);
      if (r.avviso) this.avvisi.errore(r.avviso);
      this.nuovoPersonaggio.emit(r.personaggio);
    } catch (e) {
      this.avvisi.errore(e);
    } finally {
      this.occupato.set(false);
    }
  }
}
