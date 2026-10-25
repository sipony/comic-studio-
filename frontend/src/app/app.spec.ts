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
