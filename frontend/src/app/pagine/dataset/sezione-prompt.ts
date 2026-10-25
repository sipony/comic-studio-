import { Component, ElementRef, computed, effect, inject, input, model, signal, untracked, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ApiService } from '../../core/api.service';
import { ConfigDataset, EsempioPrompt, Inquadratura, Personaggio, Varianti } from '../../core/modelli';

type ListaTesto = 'angolazioni' | 'espressioni' | 'pose' | 'sfondi';

export const DIMENSIONI_SDXL = ['1024x1024', '832x1216', '1216x832', '896x1152', '1152x896', '768x1344', '1344x768'];

@Component({
  selector: 'app-sezione-prompt',
  imports: [FormsModule, MatButtonModule, MatFormFieldModule, MatIconModule, MatInputModule, MatSlideToggleModule, MatTooltipModule],
  templateUrl: './sezione-prompt.html',
  styleUrl: './sezione-prompt.scss',
})
export class SezionePrompt {
  readonly progetto = input.required<string>();
  readonly personaggio = input.required<Personaggio>();
  readonly config = model.required<ConfigDataset | null>();
  private api = inject(ApiService);
  private positivo = viewChild<ElementRef<HTMLTextAreaElement>>('positivo');

  protected dimensioni = DIMENSIONI_SDXL;
  protected segnaposto = [
    { t: '{qualita}', d: 'tag di qualità adatti al checkpoint (es. masterpiece… o score_9…)' },
    { t: '{genere}', d: '1girl / 1boy' },
    { t: '{descrizione}', d: 'i tratti fissi del personaggio' },
    { t: '{variante}', d: 'inquadratura, angolazione, espressione, posa e sfondo' },
    { t: '{inquadratura}', d: 'solo l’inquadratura' },
    { t: '{espressione}', d: 'solo l’espressione' },
    { t: '{posa}', d: 'solo la posa' },
    { t: '{sfondo}', d: 'solo lo sfondo' },
    { t: '{nome}', d: 'il nome del personaggio' },
  ];
  protected liste: { chiave: ListaTesto; etichetta: string }[] = [
    { chiave: 'angolazioni', etichetta: 'Angolazioni' },
    { chiave: 'espressioni', etichetta: 'Espressioni' },
    { chiave: 'pose', etichetta: 'Pose' },
    { chiave: 'sfondi', etichetta: 'Sfondi' },
  ];

  protected esempi = signal<EsempioPrompt[]>([]);
  protected c = computed(() => this.config()!);
  protected sommaQuote = computed(() => this.c().varianti.inquadrature.reduce((s, i) => s + i.quota, 0) || 1);
  private timer?: ReturnType<typeof setTimeout>;

  constructor() {
    effect(() => {
      const cfg = this.config();
      const pers = this.personaggio();
      if (!cfg) return;
      untracked(() => {
        clearTimeout(this.timer);
        this.timer = setTimeout(async () => {
          try {
            this.esempi.set(await this.api.esempi(this.progetto(), pers.id, cfg, 3));
          } catch {
            this.esempi.set([]);
          }
        }, 500);
      });
    });
  }

  protected imposta<K extends keyof ConfigDataset>(k: K, v: ConfigDataset[K]) {
    this.config.update((c) => (c ? { ...c, [k]: v } : c));
  }

  private varianti(f: (v: Varianti) => Varianti) {
    this.config.update((c) => (c ? { ...c, varianti: f(structuredClone(c.varianti)) } : c));
  }

  protected testoLista(k: ListaTesto): string {
    return this.c().varianti[k].join('\n');
  }

  protected impostaLista(k: ListaTesto, testo: string) {
    const voci = testo.split('\n').map((x) => x.trim()).filter(Boolean);
    this.varianti((v) => ({ ...v, [k]: voci }));
  }

  protected impostaInquadratura<K extends keyof Inquadratura>(i: number, k: K, valore: Inquadratura[K]) {
    this.varianti((v) => {
      v.inquadrature[i] = { ...v.inquadrature[i], [k]: valore };
      return v;
    });
  }

  protected impostaDimensioni(i: number, d: string) {
    const [w, h] = d.split('x').map(Number);
    this.varianti((v) => {
      v.inquadrature[i] = { ...v.inquadrature[i], larghezza: w, altezza: h };
      return v;
    });
  }

  protected aggiungiInquadratura() {
    this.varianti((v) => ({
      ...v,
      inquadrature: [...v.inquadrature, { nome: 'nuova', testo: 'upper body', larghezza: 1024, altezza: 1024, quota: 0.2, con_posa: true }],
    }));
  }

  protected rimuoviInquadratura(i: number) {
    this.varianti((v) => ({ ...v, inquadrature: v.inquadrature.filter((_, j) => j !== i) }));
  }

  protected inserisci(t: string) {
    const el = this.positivo()?.nativeElement;
    const attuale = this.c().prompt_positivo;
    if (!el) return this.imposta('prompt_positivo', `${attuale}, ${t}`);
    const [a, b] = [el.selectionStart ?? attuale.length, el.selectionEnd ?? attuale.length];
    this.imposta('prompt_positivo', attuale.slice(0, a) + t + attuale.slice(b));
    queueMicrotask(() => {
      el.focus();
      el.setSelectionRange(a + t.length, a + t.length);
    });
  }

  protected percentuale(q: number) {
    return Math.round((q / this.sommaQuote()) * 100);
  }
}
