import { DecimalPipe } from '@angular/common';
import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router } from '@angular/router';
import { ApiService } from '../core/api.service';
import { AvvisiService } from '../core/avvisi.service';
import { EventiService } from '../core/eventi.service';
import { azionePrincipale, ETICHETTE_DOVE, filtraRighe } from '../core/catalogo-ia';
import { CatalogoIA, RigaCatalogoIA, VarianteIA } from '../core/modelli';

export interface DatiSceltaIA {
  /** perché si è aperta (es. «Per ricavare i tratti serve l'IA locale. Ollama non è installato…») */
  motivo?: string;
}

@Component({
  selector: 'app-scelta-ia',
  imports: [FormsModule, DecimalPipe, MatDialogModule, MatButtonModule, MatButtonToggleModule, MatFormFieldModule,
    MatInputModule, MatIconModule, MatProgressBarModule, MatTooltipModule],
  templateUrl: './scelta-ia.html',
  styleUrl: './scelta-ia.scss',
})
export class SceltaIAComponent implements OnInit {
  protected dati = inject<DatiSceltaIA>(MAT_DIALOG_DATA);
  private ref = inject<MatDialogRef<SceltaIAComponent, boolean>>(MatDialogRef);
  private api = inject(ApiService);
  private avvisi = inject(AvvisiService);
  private router = inject(Router);
  protected eventi = inject(EventiService);
  protected readonly etichette = ETICHETTE_DOVE;

  protected catalogo = signal<CatalogoIA | null>(null);
  protected caricamento = signal(true);
  protected tutti = signal(false);
  protected cerca = signal('');
  protected scelta = signal<string | null>(null);
  protected idLavoro = signal<string | null>(null);
  protected errore = signal('');
  protected eliminando = signal(false);

  protected stato = computed(() => this.catalogo()?.stato ?? null);
  protected righe = computed(() => filtraRighe(this.catalogo()?.modelli ?? [], this.tutti(), this.cerca()));
  protected nascosti = computed(() => (this.catalogo()?.modelli.length ?? 0)
    - filtraRighe(this.catalogo()?.modelli ?? [], false, this.cerca()).length);
  protected lavoro = computed(() => {
    const id = this.idLavoro();
    return id ? (this.eventi.lavori()[id] ?? null) : null;
  });
  protected inCorso = computed(() => {
    const l = this.lavoro();
    return !!l && (l.stato === 'in_coda' || l.stato === 'in_corso');
  });
  /** un download o un'installazione (l'aggiornamento dell'elenco non blocca la scelta) */
  protected scaricando = computed(() => this.inCorso() && this.lavoro()?.tipo !== 'ia_catalogo');
  /** cosa succede scegliendo un modello, in base allo stato dell'IA */
  protected spiegazione = computed(() => {
    const s = this.stato();
    if (!s || s.pronta) return '';
    if (s.tipo === 'nessuna') return 'L’IA è disattivata: scegliendo un modello la riattivo con Ollama.';
    if (s.tipo === 'openai') return '';
    if (!s.raggiungibile && !s.eseguibile) {
      return 'Scegli un modello qui sotto: Comic Studio installa Ollama (1-2 GB, una volta sola) e scarica il modello.';
    }
    if (!s.raggiungibile) return 'Ollama è installato ma è spento: scegliendo un modello lo avvio.';
    return 'Scegli il modello da usare: se non è ancora sul computer lo scarico.';
  });
  protected variante = computed<VarianteIA | null>(() => {
    const n = this.scelta();
    for (const r of this.catalogo()?.modelli ?? []) {
      const v = r.varianti.find((x) => x.nome === n);
      if (v) return v;
    }
    return null;
  });
  protected rigaScelta = computed(() =>
    this.catalogo()?.modelli.find((r) => r.varianti.some((v) => v.nome === this.scelta())) ?? null);
  protected testoAzione = computed(() => azionePrincipale(this.variante(), this.catalogo()));
  /** un nome cercato che non è nell'elenco: si possono chiedere a Ollama le sue versioni */
  protected daCercare = computed(() => {
    const q = this.cerca().trim().toLowerCase().split(':')[0];
    if (!/^[a-z0-9][a-z0-9._-]{1,60}$/.test(q)) return '';
    return (this.catalogo()?.famiglie ?? []).includes(q) ? '' : q;
  });
  protected titolo = computed(() => {
    const s = this.stato();
    if (!s) return 'IA locale';
    if (s.pronta) return `IA pronta · ${s.modello}`;
    if (s.tipo === 'nessuna') return 'L’IA locale è disattivata';
    if (s.tipo === 'ollama' && !s.raggiungibile && !s.eseguibile) return 'Ollama non è installato';
    if (!s.raggiungibile) return 'L’IA non risponde';
    return `Il modello ${s.modello} non è ancora scaricato`;
  });

  async ngOnInit() {
    await this.carica();
    const c = this.catalogo();
    if (c?.da_aggiornare) void this.aggiorna();
  }

  private async carica() {
    try {
      const c = await this.api.catalogoIA();
      this.catalogo.set(c);
      if (!this.variante()) {
        const attuale = c.modelli.flatMap((r) => r.varianti).find((v) => v.attuale && v.installato && c.stato.pronta);
        this.scelta.set(attuale?.nome ?? c.modelli[0]?.migliore ?? null);
      }
    } catch (e) {
      this.avvisi.errore(e);
    } finally {
      this.caricamento.set(false);
    }
  }

  /** Chiede a Ollama l'elenco aggiornato (tag, quantizzazioni e dimensioni vere). */
  protected async aggiorna(famiglia?: string) {
    try {
      const l = await this.api.aggiornaCatalogoIA(famiglia);
      this.idLavoro.set(l.id);
      const fine = await this.eventi.attendi(l.id);
      if (fine.stato === 'errore' && famiglia) this.errore.set(fine.errore ?? '');
      await this.carica();
      if (famiglia && fine.stato === 'completato') {
        this.tutti.set(true);
        const r = this.catalogo()?.modelli.find((x) => x.famiglia === famiglia);
        if (r) this.scelta.set(r.migliore);
      }
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected scegliRiga(r: RigaCatalogoIA) {
    if (!r.varianti.some((v) => v.nome === this.scelta())) this.scelta.set(r.migliore);
  }

  protected async conferma() {
    const v = this.variante();
    if (!v) return;
    this.errore.set('');
    try {
      const r = await this.api.scegliModelloIA(v.nome);
      if (r.lavoro) {
        this.idLavoro.set(r.lavoro.id);
        const fine = await this.eventi.attendi(r.lavoro.id);
        if (fine.stato !== 'completato') {
          if (fine.stato === 'errore') this.errore.set(fine.errore ?? 'Download non riuscito');
          await this.carica();
          return;
        }
      }
      await this.carica();
      const s = this.stato();
      if (s?.pronta) {
        this.avvisi.ok(`IA pronta: ${s.modello}`);
        this.ref.close(true);
      } else {
        this.errore.set(s?.errore ?? 'L’IA non è ancora pronta.');
      }
    } catch (e) {
      this.errore.set(e instanceof Error ? e.message : String(e));
    }
  }

  /** Cancella dal computer il modello scelto, se è scaricato (non va nel cestino). */
  protected async elimina() {
    const v = this.variante();
    if (!v?.installato) return;
    const inUso = v.attuale && !!this.stato()?.pronta;
    if (!confirm(`Eliminare il modello ${v.nome} dal computer e liberare circa ${v.gb.toFixed(1)} GB?\n\n` +
      (inUso ? 'È il modello in uso: finché non ne scegli un altro, l’IA locale non sarà pronta.\n' : '') +
      'Non va nel cestino: per riaverlo dovrai scaricarlo di nuovo.')) return;
    this.errore.set('');
    this.eliminando.set(true);
    try {
      const r = await this.api.eliminaModelloIA(v.nome);
      this.avvisi.ok(r.eliminato ? `Modello ${v.nome} eliminato` : `Il modello ${v.nome} non c’era già più`);
      await this.carica();
    } catch (e) {
      this.errore.set(e instanceof Error ? e.message : String(e));
    } finally {
      this.eliminando.set(false);
    }
  }

  protected async usaOllama() {
    try {
      await this.api.impostaIA({ tipo: 'ollama' });
      await this.carica();
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async ferma() {
    const id = this.idLavoro();
    if (id) await this.api.annulla(id).catch(() => undefined);
  }

  protected avanzate() {
    this.ref.close(false);
    void this.router.navigate(['/sistema'], { queryParams: { scheda: 'ia' } });
  }

  protected chiudi() {
    this.ref.close(!!this.stato()?.pronta);
  }

  protected aggiornato(): string {
    const t = this.catalogo()?.aggiornato;
    if (!t) return 'dimensioni stimate';
    return `elenco di Ollama del ${new Date(t * 1000).toLocaleDateString('it-IT')}`;
  }
}
