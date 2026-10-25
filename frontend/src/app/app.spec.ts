import { HttpErrorResponse } from '@angular/common/http';
import { describe, expect, it } from 'vitest';
import { messaggioErrore } from './core/api.service';
import { gb } from './core/modelli';

describe('messaggioErrore', () => {
  it('usa il dettaglio del backend', () => {
    const e = new HttpErrorResponse({ status: 400, error: { detail: 'Trigger già usata' } });
    expect(messaggioErrore(e)).toBe('Trigger già usata');
  });

  it('unisce gli errori di validazione', () => {
    const e = new HttpErrorResponse({ status: 422, error: { detail: [{ msg: 'campo mancante' }, { msg: 'troppo lungo' }] } });
    expect(messaggioErrore(e)).toBe('campo mancante; troppo lungo');
  });

  it('spiega quando il programma non risponde', () => {
    expect(messaggioErrore(new HttpErrorResponse({ status: 0 }))).toContain('non risponde');
  });
});

describe('gb', () => {
  it('formatta i byte in GB', () => {
    expect(gb(8 * 1024 ** 3)).toBe('8 GB');
    expect(gb(null)).toBe('—');
  });
});

import { apribile, eComfy, spezzaLink } from './core/link';

describe('indirizzi cliccabili nella console', () => {
  it('trova gli indirizzi di ComfyUI nei messaggi', () => {
    const p = spezzaLink('Connesso a ComfyUI 0.9.9 su http://127.0.0.1:8188 — GPU RTX 4070', 'localhost');
    expect(p.map((x) => x.testo)).toEqual(['Connesso a ComfyUI 0.9.9 su ', 'http://127.0.0.1:8188', ' — GPU RTX 4070']);
    expect(p[1].href).toBe('http://127.0.0.1:8188/');
  });

  it('accetta ip:porta senza schema e toglie la punteggiatura finale', () => {
    const p = spezzaLink('ComfyUI › To see the GUI go to: 0.0.0.0:8188.', 'localhost');
    expect(p[1]).toEqual({ testo: '0.0.0.0:8188', href: 'http://127.0.0.1:8188/' });
    expect(p[2].testo).toBe('.');
  });

  it('lascia stare il testo senza indirizzi', () => {
    expect(spezzaLink('Nessun indirizzo qui, solo 12:30')).toEqual([{ testo: 'Nessun indirizzo qui, solo 12:30' }]);
  });

  it('da un altro computer della rete punta all\'host di Comic Studio', () => {
    expect(apribile('http://127.0.0.1:8188', '192.168.1.20')).toBe('http://192.168.1.20:8188/');
  });

  it('riconosce ComfyUI', () => {
    expect(eComfy('http://127.0.0.1:8188/', 'http://127.0.0.1:8188')).toBe(true);
    expect(eComfy('http://127.0.0.1:8765/', 'http://127.0.0.1:8188')).toBe(false);
  });
});
