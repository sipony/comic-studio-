# Comic Studio — note per lo sviluppo

- Lingua: interfaccia, messaggi, documentazione e nomi nel codice in **italiano**.
- Backend: FastAPI in `backend/app`, test con `cd backend && ../.venv/bin/python -m pytest`.
  I test non devono toccare le cartelle reali dell'utente: usare la fixture `casa` e `finto_comfy`.
- Interfaccia: Angular 22 standalone, zoneless, signal; Angular Material con tema scuro (`--mat-sys-*`).
  Build: `cd frontend && npx ng build`; test: `npx ng test --watch=false`.
- Tutto ciò che dura più di un attimo è un lavoro (`app.gestore.avvia`) con log e avanzamento.
- Le eliminazioni spostano nel cestino; gli aggiornamenti di ComfyUI non partono mai senza conferma.
- A ogni PR aggiornare `docs/SVILUPPO.md` (roadmap + sezione della PR) e, se cambia, `docs/ARCHITETTURA.md`.
