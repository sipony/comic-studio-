import { Injectable, effect, inject } from '@angular/core';
import { MatDialog, MatDialogRef } from '@angular/material/dialog';
import { firstValueFrom } from 'rxjs';
import { SceltaIAComponent, DatiSceltaIA } from '../shell/scelta-ia';
import { ApiService } from './api.service';
import { EventiService } from './eventi.service';

/**
 * Finestra per scegliere e installare l'IA locale. Si apre:
 * - prima di un'azione che usa l'IA, se l'IA non è pronta (`pronta()`): quando l'IA è pronta l'azione riparte
 * - quando un lavoro finisce con l'errore `ia_non_pronta` (Ollama o il modello mancano)
 * - dal pulsante in Sistema → IA locale (`apri()`)
 */
@Injectable({ providedIn: 'root' })
export class SceltaIAService {
  private dialog = inject(MatDialog);
  private api = inject(ApiService);
  private eventi = inject(EventiService);
  private aperta: MatDialogRef<SceltaIAComponent, boolean> | null = null;
  private visti = new Set<string>();
  private readonly avvio = Date.now() / 1000;

  constructor() {
    effect(() => {
      for (const l of Object.values(this.eventi.lavori())) {
        if (l.codice !== 'ia_non_pronta' || this.visti.has(l.id)) continue;
        this.visti.add(l.id);
        if ((l.finito ?? 0) >= this.avvio - 2) void this.apri(l.errore ?? undefined);
      }
    });
  }

  /** true se l'IA è pronta, altrimenti apre la finestra e restituisce se l'utente l'ha resa pronta. */
  async pronta(motivo?: string): Promise<boolean> {
    try {
      const s = await this.api.statoIA();
      if (s.pronta) return true;
      return await this.apri(motivo);
    } catch {
      return this.apri(motivo);
    }
  }

  /** Apre la finestra (una sola alla volta); true quando si chiude con l'IA pronta. */
  async apri(motivo?: string): Promise<boolean> {
    if (this.aperta) return firstValueFrom(this.aperta.afterClosed()).then((x) => !!x);
    const dati: DatiSceltaIA = { motivo };
    this.aperta = this.dialog.open(SceltaIAComponent, {
      data: dati, width: 'min(960px, 96vw)', maxWidth: '96vw', maxHeight: '92vh', autoFocus: 'dialog',
      panelClass: 'finestra-ia',
    });
    const fatto = await firstValueFrom(this.aperta.afterClosed());
    this.aperta = null;
    return !!fatto;
  }
}
