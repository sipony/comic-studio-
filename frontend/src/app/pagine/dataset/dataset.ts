import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink } from '@angular/router';
import { ApiService } from '../../core/api.service';
import { AvvisiService } from '../../core/avvisi.service';
import { EventiService } from '../../core/eventi.service';
import { ConfigDataset, ConfrontoDataset, ImmagineDataset, NOMI_FAMIGLIA, RiassuntoWorkflow, RicettaProposta, RiepilogoDataset } from '../../core/modelli';
import { ProgettoService } from '../../core/progetto.service';
import { SceltaPersonaggio } from '../../shell/scelta-personaggio';
import { Galleria } from './galleria';
import { SezioneGenera } from './sezione-genera';
import { SezionePrompt } from './sezione-prompt';
import { SezioneWorkflow } from './sezione-workflow';

type StatoSalvataggio = 'salvato' | 'modificato' | 'salvataggio' | 'errore';

@Component({
  selector: 'app-dataset',
  imports: [MatButtonModule, MatExpansionModule, MatIconModule, MatProgressBarModule, MatTooltipModule, RouterLink,
    SceltaPersonaggio, SezioneWorkflow, SezionePrompt, SezioneGenera, Galleria],
  templateUrl: './dataset.html',
  styleUrl: './dataset.scss',
})
export class DatasetPage {
  protected progetti = inject(ProgettoService);
  private api = inject(ApiService);
  private avvisi = inject(AvvisiService);
  private eventi = inject(EventiService);

  protected progetto = computed(() => this.progetti.corrente()!);
  protected personaggi = computed(() => this.progetto().personaggi);
  protected sceltoId = signal<string | null>(null);
  protected personaggio = computed(() => this.personaggi().find((p) => p.id === this.sceltoId()) ?? null);

  protected config = signal<ConfigDataset | null>(null);
  protected riepilogo = signal<RiepilogoDataset | null>(null);
  protected immagini = signal<ImmagineDataset[]>([]);
  protected libreria = signal<RiassuntoWorkflow[]>([]);
  protected salvataggio = signal<StatoSalvataggio>('salvato');
  protected workflowScelto = computed(() => this.libreria().find((w) => w.id === this.config()?.workflow) ?? null);
  /** le scelte delle proposte da cui viene il riferimento (se il personaggio è nato in Comic Studio) */
  protected ricetta = signal<RicettaProposta | null>(null);
  protected preparando = signal(false);
  /** il workflow del dataset usa lo stesso checkpoint (e la stessa LoRA di stile) delle proposte? */
  protected coerente = computed(() => {
    const r = this.ricetta();
    const w = this.workflowScelto();
    if (!r || !w) return false;
    return w.checkpoint === r.checkpoint && (!r.lora_stile || w.lora.includes(r.lora_stile));
  });
  protected descrizioneRicetta = computed(() => {
    const r = this.ricetta();
    if (!r) return '';
    const parti = [r.checkpoint.replace(/\.(safetensors|ckpt)$/, '')];
    if (r.lora_stile) parti.push(`LoRA ${r.lora_stile.replace(/\.safetensors$/, '')} ${r.forza_lora}`);
    const stile = [r.stile, r.extra].filter(Boolean).join(', ');
    if (stile) parti.push(`stile «${stile}»`);
    return parti.join(' · ');
  });
  protected readonly nomiFamiglia = NOMI_FAMIGLIA;
  /** confronto con la proposta scelta come riferimento (aggiornato mentre si cambia la configurazione) */
  protected confronto = signal<ConfrontoDataset | null>(null);
  protected confrontoAperto = signal(false);
  private timerConfronto?: ReturnType<typeof setTimeout>;
  protected urlProposta = (file: string) => this.api.urlProposta(this.progetto().id, this.sceltoId() ?? '', file);

  /** Aggiunge allo stile del dataset i tag di stile delle proposte che mancano. */
  protected aggiungiStile() {
    const c = this.config();
    const m = this.confronto()?.mancanti ?? [];
    if (!c || !m.length) return;
    this.config.set({ ...c, stile: [c.stile ?? '', ...m].map((x) => x.trim()).filter(Boolean).join(', ') });
    this.avvisi.ok(`Aggiunti allo stile: ${m.join(', ')}`);
  }

  /** Lavoro del dataset in corso per questo personaggio (generazione o selezione). */
  protected lavoro = computed(() => {
    const p = this.personaggio();
    if (!p) return null;
    return this.eventi.attivi().find((l) => l.progetto === this.progetto().id && l.tipo.startsWith('dataset_') &&
      l.titolo.includes(p.nome)) ?? null;
  });

  private ultimoSalvato = '';
  private timer?: ReturnType<typeof setTimeout>;

  constructor() {
    effect(() => {
      const c = this.config();
      const id = this.sceltoId();
      if (this.timerConfronto) clearTimeout(this.timerConfronto);
      if (!c || !id) return;
      this.timerConfronto = setTimeout(() => {
        this.api.confrontoDataset(this.progetto().id, id, c)
          .then((r) => { if (this.sceltoId() === id) this.confronto.set(r); })
          .catch(() => this.confronto.set(null));
      }, 400);
    });
    effect(() => {
      const id = this.sceltoId();
      if (id) untracked(() => void this.carica(id));
    });

    // salvataggio automatico della configurazione
    effect(() => {
      const c = this.config();
      if (!c) return;
      const json = JSON.stringify(c);
      if (json === this.ultimoSalvato) return;
      untracked(() => {
        this.salvataggio.set('modificato');
        clearTimeout(this.timer);
        this.timer = setTimeout(() => void this.salva(), 700);
      });
    });

    // aggiornamenti in tempo reale della galleria
    effect(() => {
      const e = this.eventi.dataset();
      if (!e || e.progetto !== this.progetto().id || e.personaggio !== untracked(this.sceltoId)) return;
      untracked(() => {
        if (e.azione === 'elenco') {
          void this.ricaricaImmagini();
        } else if (e.immagine) {
          const img = e.immagine;
          this.immagini.update((l) => {
            const i = l.findIndex((x) => x.file === img.file);
            return i >= 0 ? l.map((x) => (x.file === img.file ? img : x)) : [...l, img];
          });
          this.aggiornaRiepilogo();
        }
      });
    });
  }

  protected scegli(id: string | null) {
    if (id === this.sceltoId()) return;
    if (this.sceltoId()) void this.salvaSubito();
    this.sceltoId.set(id);
  }

  private async carica(id: string) {
    const pid = this.progetto().id;
    try {
      const [stato, lib, imm] = await Promise.all([
        this.api.statoDataset(pid, id), this.api.workflow(pid), this.api.immaginiDataset(pid, id)]);
      if (this.sceltoId() !== id) return;
      this.ultimoSalvato = JSON.stringify(stato.config);
      this.config.set(stato.config);
      this.riepilogo.set(stato.riepilogo);
      this.ricetta.set(stato.origine?.ricetta ?? null);
      this.libreria.set(lib);
      this.immagini.set(imm);
      this.salvataggio.set('salvato');
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async ricaricaImmagini() {
    const id = this.sceltoId();
    if (!id) return;
    try {
      const [imm, stato] = await Promise.all([this.api.immaginiDataset(this.progetto().id, id),
        this.api.statoDataset(this.progetto().id, id)]);
      if (this.sceltoId() !== id) return;
      this.immagini.set(imm);
      this.riepilogo.set(stato.riepilogo);         // conteggi, spazio occupato e cestino
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  /** Workflow, stile e negativo del dataset come quelli delle proposte da cui è nato il personaggio. */
  protected async comeProposte() {
    const id = this.sceltoId();
    if (!id) return;
    this.preparando.set(true);
    try {
      const r = await this.api.comeProposte(this.progetto().id, id);
      this.libreria.set(await this.api.workflow(this.progetto().id));
      this.ultimoSalvato = JSON.stringify(r.config);
      this.config.set(r.config);
      this.salvataggio.set('salvato');
      this.avvisi.ok(`Dataset con le stesse scelte delle proposte: ${r.workflow.nome}`);
      for (const a of r.avvisi) this.avvisi.errore(a);
    } catch (e) {
      this.avvisi.errore(e);
    } finally {
      this.preparando.set(false);
    }
  }

  protected async ricaricaLibreria() {
    try {
      this.libreria.set(await this.api.workflow(this.progetto().id));
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  private aggiornaRiepilogo() {
    const l = this.immagini();
    this.riepilogo.set({
      ...this.riepilogo(),
      totale: l.length,
      tenute: l.filter((i) => i.stato === 'tenuta').length,
      scartate: l.filter((i) => i.stato === 'scartata').length,
      da_decidere: l.filter((i) => i.stato === null).length,
    });
  }

  private async salva() {
    const c = this.config();
    const id = this.sceltoId();
    if (!c || !id) return;
    const json = JSON.stringify(c);
    if (json === this.ultimoSalvato) return this.salvataggio.set('salvato');
    this.salvataggio.set('salvataggio');
    try {
      await this.api.salvaConfig(this.progetto().id, id, c);
      this.ultimoSalvato = json;
      this.salvataggio.set(JSON.stringify(this.config()) === json ? 'salvato' : 'modificato');
    } catch (e) {
      this.salvataggio.set('errore');
      this.avvisi.errore(e);
    }
  }

  protected primaDiGenerare = () => this.salvaSubito();

  /** Salva subito (prima di generare o di cambiare personaggio). */
  protected async salvaSubito(): Promise<boolean> {
    clearTimeout(this.timer);
    await this.salva();
    return this.salvataggio() !== 'errore';
  }
}
