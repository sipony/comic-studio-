import { Injectable, effect, inject, untracked } from '@angular/core';
import { MatDialog, MatDialogRef } from '@angular/material/dialog';
import { ComponentiComponent } from '../shell/componenti';
import { EventiService } from './eventi.service';

/**
 * All'apertura, se manca IPAdapter Plus (nodo e modelli) e l'utente non ha detto «non chiedere più», propone di
 * installarlo; una volta per sessione. Si apre anche da Sistema → Controllo (`apri()`).
 */
@Injectable({ providedIn: 'root' })
export class ComponentiService {
  private dialog = inject(MatDialog);
  private eventi = inject(EventiService);
  private proposto = false;
  private aperta: MatDialogRef<ComponentiComponent> | null = null;

  constructor() {
    effect(() => {
      const s = this.eventi.componenti();
      if (!s || this.proposto || !s.chiedi || s.errore || !s.mancanti.length) return;
      this.proposto = true;
      untracked(() => this.apri());
    });
  }

  apri() {
    if (this.aperta) return;
    this.aperta = this.dialog.open(ComponentiComponent, { width: 'min(620px, 96vw)', maxWidth: '96vw', autoFocus: 'dialog' });
    this.aperta.afterClosed().subscribe(() => (this.aperta = null));
  }
}
