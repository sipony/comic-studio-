import { Component, computed, inject, OnInit } from '@angular/core';
import { MatIconRegistry, MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { EventiService } from './core/eventi.service';
import { gb } from './core/modelli';
import { ProgettoService } from './core/progetto.service';
import { ConsoleComponent } from './shell/console';

interface VoceMenu {
  percorso: string;
  icona: string;
  etichetta: string;
  passo?: number;
  pronto: boolean;
}

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, MatIconModule, MatButtonModule, MatTooltipModule, ConsoleComponent],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App implements OnInit {
  protected eventi = inject(EventiService);
  protected progetti = inject(ProgettoService);
  private router = inject(Router);

  constructor() {
    inject(MatIconRegistry).setDefaultFontSetClass('material-symbols-outlined');
  }

  protected passi = computed<VoceMenu[]>(() => {
    const id = this.progetti.id();
    if (!id) return [];
    const base = `/progetto/${id}`;
    return [
      { percorso: `${base}/personaggi`, icona: 'groups', etichetta: 'Personaggi', pronto: true },
      { percorso: `${base}/dataset`, icona: 'photo_library', etichetta: 'Dataset', passo: 1, pronto: true },
      { percorso: `${base}/didascalie`, icona: 'sell', etichetta: 'Didascalie', passo: 2, pronto: false },
      { percorso: `${base}/addestramento`, icona: 'model_training', etichetta: 'Addestramento', passo: 3, pronto: false },
      { percorso: `${base}/fumetto`, icona: 'auto_stories', etichetta: 'Fumetto', passo: 4, pronto: false },
    ];
  });

  protected chipComfy = computed(() => {
    const c = this.eventi.comfy();
    if (!this.eventi.collegato()) return { classe: 'errore', testo: 'Comic Studio non risponde', dettaglio: '' };
    if (!c) return { classe: 'attesa', testo: 'ComfyUI…', dettaglio: '' };
    if (!c.connesso) return { classe: 'errore', testo: 'ComfyUI non connesso', dettaglio: c.errore ?? '' };
    const gpu = c.gpu ? c.gpu.replace(/^cuda:\d+\s*/, '').replace(/ : .*$/, '').replace('NVIDIA GeForce ', '') : '';
    return {
      classe: 'ok',
      testo: `ComfyUI ${c.versione ?? ''}`.trim(),
      dettaglio: gpu ? `${gpu} · ${gb(c.vram_totale)}` : '',
    };
  });

  protected problemi = computed(() => {
    const r = this.eventi.rapporto();
    return r ? r.riepilogo.errore : 0;
  });

  async ngOnInit() {
    await this.eventi.avvia();
  }

  protected vaiAlSistema() {
    void this.router.navigateByUrl('/sistema');
  }
}
