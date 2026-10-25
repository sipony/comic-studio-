import { DecimalPipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatTabsModule } from '@angular/material/tabs';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ApiService } from '../../core/api.service';
import { AvvisiService } from '../../core/avvisi.service';
import { EventiService } from '../../core/eventi.service';
import { Esito, Installazione, VoceControllo, gb } from '../../core/modelli';

const ORDINE_CATEGORIE = ['Hardware', 'Software', 'Custom node', 'Modelli di supporto', 'Aggiornamenti'];
const PESO: Record<Esito, number> = { errore: 0, avviso: 1, info: 2, ok: 3 };

@Component({
  selector: 'app-sistema',
  imports: [DecimalPipe, FormsModule, MatButtonModule, MatFormFieldModule, MatIconModule, MatInputModule,
    MatProgressBarModule, MatSlideToggleModule, MatTabsModule, MatTooltipModule],
  templateUrl: './sistema.html',
  styleUrl: './sistema.scss',
})
export class SistemaPage {
  protected eventi = inject(EventiService);
  private api = inject(ApiService);
  private avvisi = inject(AvvisiService);
  protected gb = gb;

  protected url = signal('');
  protected cartella = signal('');
  protected salvando = signal(false);

  // avvio di ComfyUI
  protected avvioAutomatico = signal(true);
  protected argomenti = signal('');
  protected comando = signal('');
  protected attesa = signal(300);
  protected mostraAvanzate = signal(false);

  protected rapporto = this.eventi.rapporto;
  protected inControllo = computed(() =>
    this.eventi.attivi().find((l) => l.tipo === 'diagnostica' || l.tipo === 'ricerca_comfy') ?? null);
  protected lavoroComfy = computed(() =>
    this.eventi.attivi().find((l) => l.tipo === 'avvio_comfy' || l.tipo === 'arresto_comfy') ?? null);
  protected inCorso = computed(() => this.lavoroComfy() ?? this.inControllo());

  protected categorie = computed(() => {
    const r = this.rapporto();
    if (!r) return [];
    const gruppi = new Map<string, VoceControllo[]>();
    for (const v of r.voci) gruppi.set(v.categoria, [...(gruppi.get(v.categoria) ?? []), v]);
    return [...gruppi.entries()]
      .sort((a, b) => ORDINE_CATEGORIE.indexOf(a[0]) - ORDINE_CATEGORIE.indexOf(b[0]))
      .map(([nome, voci]) => ({
        nome,
        voci: [...voci].sort((a, b) => PESO[a.esito] - PESO[b.esito]),
        peggiore: voci.reduce<Esito>((p, v) => (PESO[v.esito] < PESO[p] ? v.esito : p), 'ok'),
      }));
  });

  protected gpu = computed(() => this.rapporto()?.hardware.gpu?.[0] ?? null);

  constructor() {
    const imp = this.eventi.sistema()?.impostazioni;
    this.url.set(imp?.comfy_url ?? this.eventi.comfy()?.url ?? 'http://127.0.0.1:8188');
    this.cartella.set(imp?.comfy_dir ?? this.eventi.comfy()?.cartella ?? '');
    this.avvioAutomatico.set(imp?.avvio_automatico ?? true);
    this.argomenti.set(imp?.argomenti_comfy ?? '');
    this.comando.set(imp?.comando_comfy ?? '');
    this.attesa.set(imp?.attesa_avvio ?? 300);
    this.mostraAvanzate.set(!!imp?.comando_comfy);
  }

  protected async avviaComfy() {
    try {
      const fine = await this.eventi.attendi((await this.api.avviaComfy()).id);
      if (fine.stato === 'completato') this.avvisi.ok('ComfyUI è pronto');
      else if (fine.errore) this.avvisi.errore(fine.errore);
      const c = this.eventi.comfy();
      if (c?.url) this.url.set(c.url);
      if (c?.cartella) this.cartella.set(c.cartella);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async riavviaComfy() {
    try {
      const fine = await this.eventi.attendi((await this.api.riavviaComfy()).id);
      if (fine.stato === 'completato') this.avvisi.ok('ComfyUI riavviato');
      else if (fine.errore) this.avvisi.errore(fine.errore);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async fermaComfy() {
    try {
      const fine = await this.eventi.attendi((await this.api.fermaComfy()).id);
      if (fine.stato === 'completato') this.avvisi.ok('ComfyUI fermato');
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async salvaAvvio(campi?: { avvio_automatico: boolean }) {
    try {
      const r = await this.api.impostaAvvio(campi ?? {
        argomenti_comfy: this.argomenti().trim(),
        comando_comfy: this.comando().trim(),
        attesa_avvio: Number(this.attesa()) || 300,
      });
      this.avvioAutomatico.set(r.impostazioni.avvio_automatico);
      this.argomenti.set(r.impostazioni.argomenti_comfy);
      this.comando.set(r.impostazioni.comando_comfy ?? '');
      this.attesa.set(r.impostazioni.attesa_avvio);
      this.avvisi.ok(campi ? (campi.avvio_automatico ? 'ComfyUI partirà da solo all\'apertura'
        : 'Avvio automatico disattivato') : 'Impostazioni di avvio salvate: valgono dal prossimo avvio');
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async controlla(rete = true) {
    try {
      await this.api.avviaControllo(rete);
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async cerca() {
    try {
      const l = await this.api.cercaComfy();
      const fine = await this.eventi.attendi(l.id);
      if (fine.stato === 'completato') {
        const c = this.eventi.comfy();
        if (c?.url) this.url.set(c.url);
        if (c?.cartella) this.cartella.set(c.cartella);
      }
    } catch (e) {
      this.avvisi.errore(e);
    }
  }

  protected async usa(i?: Installazione) {
    const url = i?.url ?? (this.url().trim() || null);
    const cartella = i?.cartella ?? (this.cartella().trim() || null);
    this.salvando.set(true);
    try {
      const s = await this.api.usaComfy(url, cartella);
      this.url.set(s.url ?? '');
      this.cartella.set(s.cartella ?? '');
      this.avvisi.ok(s.connesso ? 'Connesso a ComfyUI' : 'Impostazioni salvate (ComfyUI non risponde ancora)');
      void this.controlla(false);
    } catch (e) {
      this.avvisi.errore(e);
    } finally {
      this.salvando.set(false);
    }
  }

  protected inUso(i: Installazione): boolean {
    return i.cartella === this.eventi.comfy()?.cartella;
  }

  protected icona(e: Esito): string {
    return { ok: 'check_circle', avviso: 'warning', errore: 'error', info: 'info' }[e];
  }

  protected percentuale(libero: number, totale: number): number {
    return totale ? 100 - (libero / totale) * 100 : 0;
  }
}
