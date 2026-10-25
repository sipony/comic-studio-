import { Injectable, inject } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { messaggioErrore } from './api.service';

/** Messaggi brevi in basso a destra. */
@Injectable({ providedIn: 'root' })
export class AvvisiService {
  private snack = inject(MatSnackBar);

  ok(msg: string) {
    this.snack.open(msg, 'OK', { duration: 3000, panelClass: 'avviso-ok' });
  }

  errore(e: unknown) {
    this.snack.open(messaggioErrore(e), 'Chiudi', { duration: 8000, panelClass: 'avviso-errore' });
  }
}
