/** Indirizzi cliccabili nei messaggi della console (es. «Connesso a ComfyUI su http://127.0.0.1:8188»). */

export interface Parte {
  testo: string;
  href?: string;
}

// http(s)://…, oppure ip:porta e localhost:porta senza schema
const INDIRIZZO =
  /\bhttps?:\/\/[^\s'"<>`]+|\b(?:\d{1,3}\.){3}\d{1,3}:\d{2,5}(?:\/[^\s'"<>`]*)?|\blocalhost:\d{2,5}(?:\/[^\s'"<>`]*)?/gi;
const FINALE = /[.,;:!?)\]}»]+$/;
const LOCALI = new Set(['127.0.0.1', 'localhost', '[::1]', '0.0.0.0', '[::]']);

/**
 * L'indirizzo da aprire nel browser: «0.0.0.0» (ComfyUI in ascolto su tutte le interfacce) diventa 127.0.0.1;
 * se Comic Studio è aperto da un altro computer della rete, gli indirizzi locali puntano al suo host.
 */
export function apribile(url: string, hostPagina = typeof location !== 'undefined' ? location.hostname : 'localhost'): string {
  let u: URL;
  try {
    u = new URL(/^https?:\/\//i.test(url) ? url : `http://${url}`);
  } catch {
    return url;
  }
  if (LOCALI.has(u.hostname)) {
    const remoto = hostPagina && !LOCALI.has(hostPagina) && hostPagina !== '::1';
    u.hostname = remoto ? hostPagina : '127.0.0.1';
  }
  return u.toString();
}

/** Divide il messaggio in testo e collegamenti (senza HTML: niente da iniettare). */
export function spezzaLink(msg: string, hostPagina?: string): Parte[] {
  const parti: Parte[] = [];
  let ultimo = 0;
  for (const m of msg.matchAll(INDIRIZZO)) {
    let trovato = m[0];
    const coda = trovato.match(FINALE)?.[0] ?? '';
    if (coda) trovato = trovato.slice(0, -coda.length);
    const inizio = m.index ?? 0;
    if (inizio > ultimo) parti.push({ testo: msg.slice(ultimo, inizio) });
    parti.push({ testo: trovato, href: apribile(trovato, hostPagina) });
    ultimo = inizio + trovato.length;
  }
  if (ultimo < msg.length) parti.push({ testo: msg.slice(ultimo) });
  return parti.length ? parti : [{ testo: msg }];
}

/** Stessa macchina e porta: il collegamento porta a ComfyUI. */
export function eComfy(href: string, comfy: string | null | undefined): boolean {
  if (!comfy) return false;
  try {
    const a = new URL(href);
    const b = new URL(apribile(comfy));
    return a.port === b.port && a.hostname === b.hostname;
  } catch {
    return false;
  }
}
