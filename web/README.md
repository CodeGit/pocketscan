# pocketscan web

A Vite + Svelte 5 (TypeScript) single-page app: submit UniProt accessions, watch
job progress, browse a job's ranked pockets, and view the selected pocket in
[Mol*](https://molstar.org/).

```bash
pnpm install
pnpm dev      # http://localhost:5173; /api is proxied to the API on :8000
pnpm check    # svelte-check and tsc
pnpm build    # static files in dist/
```

- `src/lib/api.ts`: the typed client and the only place that knows API URLs
  and response shapes (keep it in step with `api/src/pocketscan_api/schemas.py`).
- `src/lib/PocketTable.svelte`: sorting, filtering and paging, driven by the
  API's `total`.
- `src/lib/JobForm.svelte`, `JobStatus.svelte`: submitting a job and polling it.
- `src/lib/StructureViewer.svelte`: the Mol* panel. Mol* is loaded lazily, as
  separate chunks, the first time a pocket is shown.
- The selected job is kept in the URL hash (`#job=N`), so a job is a link.

Setup, the full local workflow and the project overview are in the
[root README](../README.md).
