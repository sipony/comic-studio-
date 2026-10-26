import { DecimalPipe, PercentPipe } from '@angular/common';
import { Component, computed, effect, inject, input, model, signal, untracked } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSliderModule } from '@angular/material/slider';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ApiService } from '../../core/api.service';
import { AvvisiService } from '../../core/avvisi.service';
import { EventiService } from '../../core/eventi.service';
import { ConfigDataset, ControlnetDataset, Lavoro, Personaggio, Posa, PoseGuidate, StatoComponenti } from '../../core/modelli';

export const POSE_PREDEFINITE: PoseGuidate = { attive: false, controlnet: null, pose: [], specchiate: true, forza: 0.8, fine: 0.8 };

/**
 * Pose guidate: a ogni immagine uno scheletro OpenPose della libreria di Comic Studio passa per un ControlNet. Il
 * personaggio resta quello del workflow (IPAdapter sul riferimento, LoRA, prompt delle proposte); cambia solo la posa.
 */
@Component({
  selector: 'app-sezione-pose',
  imports: [DecimalPipe, PercentPipe, MatButtonModule, MatCheckboxModule, MatIconModule, MatProgressBarModule, MatSliderModule,
    MatSlideToggleModule, MatTooltipModule],
  template: `
    @if (config(); as cfg) {
      <p class="nota">
        Comic Studio disegna lo scheletro di ogni posa (come lo estrarrebbe OpenPose da una foto) e lo passa a un
        ControlNet: il personaggio prende la posa dello scheletro, mentre aspetto e stile restano quelli del workflow e
        dell'immagine di riferimento. Il prompt prende da solo la posa e l'angolazione dello scheletro.
      </p>

      @if (stato(); as s) {
        @if (s.errore) {
          <p class="problema"><mat-icon>error</mat-icon> {{ s.errore }}</p>
        } @else if (!controlnet().length) {
          <div class="manca">
            <mat-icon>download</mat-icon>
            <div>
              <strong>Manca il ControlNet OpenPose {{ cn()?.serve === 'sd15' ? 'SD 1.5' : 'SDXL' }}</strong>
              @if (incompatibili().length) {
                <span class="errore">Quelli che hai ({{ incompatibili().join(', ') }}) sono per un'altra architettura
                  (di solito SD 1.5): con questo checkpoint farebbero fallire il KSampler.</span>
              }
              <span>{{ s.mancanti[0].nome }}, {{ gb(s.totale) }} GB in {{ s.mancanti[0].cartella }}. Va bene per Pony,
                Illustrious e gli altri SDXL.
                @if (s.spazio.length) { Liberi sul disco: {{ gb(s.spazio[0].libero) }} GB. }</span>
              @if (s.messaggio_spazio) { <span class="errore">{{ s.messaggio_spazio }}</span> }
            </div>
            @if (!s.mancanti.length) {
              <span class="nota">Mettilo in ComfyUI/models/controlnet (per esempio controlnet-openpose-sdxl-1.0 di xinsir).</span>
            } @else if (installazione(); as l) {
              <div class="avanzamento">
                <span>{{ l.testo || 'in coda' }}</span>
                <mat-progress-bar [mode]="l.progresso >= 0 ? 'determinate' : 'indeterminate'" [value]="l.progresso * 100" />
              </div>
            } @else {
              <button mat-flat-button (click)="installa()" [disabled]="!s.basta_spazio || occupato()">
                <mat-icon>download</mat-icon> Installa</button>
            }
          </div>
        }
      }

      <mat-slide-toggle [checked]="p().attive" (change)="imposta({ attive: $event.checked })">
        Usa le pose guidate in ogni generazione del dataset
      </mat-slide-toggle>

      <div class="riga-campi">
        <label class="campo">
          <span>ControlNet</span>
          <select [value]="p().controlnet ?? ''" (change)="imposta({ controlnet: $any($event.target).value || null })"
            aria-label="ControlNet delle pose">
            <option value="">Automatico{{ automatico() ? ' (' + automatico() + ')' : '' }}</option>
            @for (m of controlnet(); track m) { <option [value]="m">{{ m }}</option> }
            @for (m of incompatibili(); track m) { <option [value]="m" disabled>{{ m }} (altra architettura)</option> }
          </select>
        </label>
      </div>
      <div class="cursori">
        <div class="cursore">
          <span>Forza della posa <strong>{{ p().forza | number: '1.2-2' }}</strong></span>
          <mat-slider min="0.3" max="1.5" step="0.05" discrete>
            <input matSliderThumb [value]="p().forza" (valueChange)="imposta({ forza: $event })" />
          </mat-slider>
          <small>0,7-0,9: la posa si segue bene senza irrigidire il disegno.</small>
        </div>
        <div class="cursore">
          <span>Fino al <strong>{{ p().fine | percent }}</strong> dei passi</span>
          <mat-slider min="0.3" max="1" step="0.05" discrete>
            <input matSliderThumb [value]="p().fine" (valueChange)="imposta({ fine: $event })" />
          </mat-slider>
          <small>Negli ultimi passi lo scheletro si lascia: mani e dettagli vengono più naturali.</small>
        </div>
      </div>

      <div class="testa-pose">
        <strong>Pose ({{ scelte().length }} di {{ base().length }}{{ p().specchiate ? ', con le specchiate ' + scelte().length * 2 : '' }})</strong>
        <span class="spazio"></span>
        <mat-checkbox [checked]="p().specchiate" (change)="imposta({ specchiate: $event.checked })">Anche specchiate</mat-checkbox>
        <button mat-button (click)="imposta({ pose: [] })" [disabled]="!p().pose.length">Tutte</button>
      </div>
      <div class="pose" role="group" aria-label="Pose da usare">
        @for (x of base(); track x.id) {
          <button type="button" class="posa" [class.scelta]="sceltaSet().has(x.id)" (click)="alterna(x.id)"
            [attr.aria-pressed]="sceltaSet().has(x.id)" [matTooltip]="x.tag + ' · ' + x.vista">
            <img [src]="api.urlScheletro(x.id)" [alt]="'Scheletro: ' + x.nome" loading="lazy" />
            <span>{{ x.nome }}</span>
            @if (sceltaSet().has(x.id)) { <mat-icon class="spunta">check_circle</mat-icon> }
          </button>
        }
      </div>

      @for (m of problemi(); track m) { <p class="problema"><mat-icon>error</mat-icon> {{ m }}</p> }
      <div class="pulsanti">
        <button mat-flat-button (click)="unaPerPosa()" [disabled]="!!problemi().length || occupato() || !!lavoro()">
          <mat-icon>accessibility_new</mat-icon> Una immagine per posa ({{ quante() }})
        </button>
      </div>
      <p class="nota">
        Genera subito {{ quante() }} immagini di {{ personaggio().nome }} a figura intera, una per posa, e le mette nella
        galleria del dataset. Con l'interruttore acceso anche «Genera» usa le pose, a turno, tagliate per ogni
        inquadratura (nei primi piani resta testa e spalle).
      </p>
    }
  `,
  styles: `
    :host { display: flex; flex-direction: column; gap: 12px; }
    .nota { margin: 0; font-size: 12.5px; color: var(--mat-sys-on-surface-variant); }
    .problema { display: flex; gap: 6px; margin: 0; font-size: 13px; color: var(--cs-errore-testo); }
    .problema mat-icon { font-size: 18px; width: 18px; height: 18px; flex: 0 0 auto; }
    .manca { display: grid; grid-template-columns: auto 1fr; gap: 6px 10px; align-items: start; padding: 10px 12px;
      border-radius: 10px; background: color-mix(in srgb, var(--mat-sys-tertiary) 12%, transparent); font-size: 13px; }
    .manca > div { display: flex; flex-direction: column; gap: 2px; }
    .manca span { color: var(--mat-sys-on-surface-variant); }
    .manca .errore { color: var(--cs-errore-testo); }
    .manca .nota { grid-column: 1 / -1; }
    .manca > button, .manca .avanzamento { grid-column: 1 / -1; justify-self: start; }
    .manca .avanzamento { justify-self: stretch; display: flex; flex-direction: column; gap: 4px; }
    .riga-campi { display: flex; gap: 8px; }
    .campo { display: flex; flex-direction: column; gap: 4px; font-size: 12.5px; color: var(--mat-sys-on-surface-variant); flex: 1; min-width: 0; }
    .campo select { font: inherit; font-size: 13.5px; padding: 8px; border-radius: 8px; color: var(--mat-sys-on-surface);
      background: var(--mat-sys-surface-container-high); border: 1px solid var(--mat-sys-outline-variant); max-width: 100%; }
    .cursori { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    @media (max-width: 560px) { .cursori { grid-template-columns: 1fr; } }
    .cursore { display: flex; flex-direction: column; font-size: 13px; }
    .cursore mat-slider { margin: 0 4px; }
    .cursore small { color: var(--mat-sys-on-surface-variant); font-size: 11.5px; }
    .testa-pose { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 13.5px; }
    .spazio { flex: 1; }
    .pose { display: grid; grid-template-columns: repeat(auto-fill, minmax(84px, 1fr)); gap: 8px; }
    .posa { position: relative; display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 4px 4px 6px;
      border-radius: 10px; border: 2px solid transparent; background: #000; color: var(--mat-sys-on-surface-variant);
      font: inherit; font-size: 11.5px; line-height: 1.2; cursor: pointer; opacity: 0.45; transition: opacity 0.12s, border-color 0.12s; }
    .posa img { width: 100%; aspect-ratio: 208 / 304; object-fit: contain; display: block; }
    .posa span { text-align: center; }
    .posa.scelta { opacity: 1; border-color: var(--mat-sys-primary); color: #fff; }
    .posa:hover { opacity: 0.85; }
    .posa:focus-visible { outline: 2px solid var(--mat-sys-primary); outline-offset: 2px; }
    .spunta { position: absolute; top: 4px; right: 4px; font-size: 18px; width: 18px; height: 18px; color: var(--mat-sys-primary); }
    .pulsanti { display: flex; gap: 8px; flex-wrap: wrap; }
  `,
})
export class SezionePose {
  readonly progetto = input.required<string>();
  readonly personaggio = input.required<Personaggio>();
  readonly config = model.required<ConfigDataset | null>();
  readonly lavoro = input<Lavoro | null>(null);
  readonly prima = input<() => Promise<boolean>>(async () => true);

  protected api = inject(ApiService);
  private avvisi = inject(AvvisiService);
  private eventi = inject(EventiService);

  protected tutte = signal<Posa[]>([]);
  protected stato = signal<StatoComponenti | null>(null);
  protected cn = signal<ControlnetDataset | null>(null);
  /** i ControlNet che vanno bene con il checkpoint del workflow (o di cui non si sa) */
  protected controlnet = computed(() => (this.cn()?.elenco ?? []).filter((x) => x.compatibile !== false).map((x) => x.nome));
  protected incompatibili = computed(() => (this.cn()?.elenco ?? []).filter((x) => x.compatibile === false).map((x) => x.nome));
  protected occupato = signal(false);
  private idInstallazione = signal<string | null>(null);

  protected p = computed(() => ({ ...POSE_PREDEFINITE, ...(this.config()?.pose ?? {}) }));
  /** le pose della libreria, senza le specchiate (si aggiungono con «Anche specchiate») */
  protected base = computed(() => this.tutte().filter((x) => !x.specchiata));
  protected scelte = computed(() => (this.p().pose.length ? this.base().filter((x) => this.p().pose.includes(x.id)) : this.base()));
  protected sceltaSet = computed(() => new Set(this.scelte().map((x) => x.id)));
  protected quante = computed(() => this.scelte().length * (this.p().specchiate ? 2 : 1));
  protected automatico = computed(() => this.cn()?.automatico ?? null);
  protected installazione = computed(() => {
    const id = this.idInstallazione();
    const l = id ? this.eventi.lavori()[id] : this.eventi.attivi().find((x) => x.tipo === 'componenti');
    return l && (l.stato === 'in_coda' || l.stato === 'in_corso') ? l : null;
  });

  protected problemi = computed(() => {
    const out: string[] = [];
    if (!this.config()?.workflow) out.push('Scegli o crea un workflow nella sezione 1.');
    if (!this.personaggio().riferimento) out.push(`${this.personaggio().nome} non ha un'immagine di riferimento (pagina Personaggi).`);
    if (!this.eventi.comfy()?.connesso) out.push('ComfyUI non è connesso: avvialo (vedi pagina Sistema).');
    if (!this.automatico() && !this.controlnet().includes(this.p().controlnet ?? '')) out.push('Serve un ControlNet OpenPose adatto al checkpoint (qui sopra).');
    return out;
  });

  constructor() {
    this.carica();
    // a installazione finita (o quando ComfyUI si collega) si ricontrolla
    let prima: string | undefined;
    effect(() => {
      const id = this.idInstallazione();
      const st = id ? this.eventi.lavori()[id]?.stato : undefined;
      const connesso = this.eventi.comfy()?.connesso;
      const chiave = `${st}|${connesso}`;
      if (chiave !== prima) {
        const vecchia = prima;
        prima = chiave;
        if (vecchia !== undefined && st !== 'in_coda' && st !== 'in_corso') untracked(() => this.controlla());
      }
    });
    // cambiando workflow cambia il checkpoint, e con lui i ControlNet che vanno bene
    let wfPrima: string | null | undefined;
    effect(() => {
      const wf = this.config()?.workflow ?? null;
      if (wfPrima !== undefined && wf !== wfPrima) untracked(() => this.controlla());
      wfPrima = wf;
    });
  }

  private async carica() {
    try {
      this.tutte.set((await this.api.pose()).pose);
    } catch (e) {
      this.avvisi.errore(e);
    }
    await this.controlla();
  }

  private async controlla() {
    try {
      const [s, cn] = await Promise.all([this.api.componenti('pose'), this.api.controlnetDataset(this.progetto(), this.personaggio().id)]);
      this.stato.set(s);
      this.cn.set(cn);
    } catch {
      /* ComfyUI spento o cartella sconosciuta: il riquadro lo dice quando c'è */
    }
  }

  protected gb(byte: number) {
    return (byte / 1024 ** 3).toFixed(1).replace('.', ',');
  }

  protected imposta(v: Partial<PoseGuidate>) {
    this.config.update((c) => (c ? { ...c, pose: { ...this.p(), ...v } } : c));
  }

  protected alterna(id: string) {
    const ora = this.scelte().map((x) => x.id);
    const nuove = ora.includes(id) ? ora.filter((x) => x !== id) : [...ora, id];
    if (!nuove.length) return;          // almeno una posa
    // tutte scelte = lista vuota (così le pose aggiunte nelle versioni nuove entrano da sole)
    this.imposta({ pose: nuove.length === this.base().length ? [] : this.base().map((x) => x.id).filter((x) => nuove.includes(x)) });
  }

  protected async installa() {
    this.occupato.set(true);
    try {
      const l = await this.api.installaComponenti('pose');
      this.idInstallazione.set(l.id);
    } catch (e) {
      this.avvisi.errore(e);
    } finally {
      this.occupato.set(false);
    }
  }

  protected async unaPerPosa() {
    const cfg = this.config();
    if (!cfg) return;
    this.occupato.set(true);
    try {
      if (!(await this.prima()())) return;
      await this.api.genera(this.progetto(), this.personaggio().id, 1, false, true);
    } catch (e) {
      this.avvisi.errore(e);
    } finally {
      this.occupato.set(false);
    }
  }
}
