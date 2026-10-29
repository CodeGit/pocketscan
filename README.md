# pocketscan

A pocket-detection platform for protein structures, built as a focused
demonstration of a scientific data platform: web app, queue, pipeline,
Kubernetes and GitOps.

> **Status:** works end to end on a developer machine: submit a batch, run the
> pipeline, browse the ranked pockets and view them in 3D. The cloud side
> (Kubernetes, the queue, Argo) is not built yet. See [Progress](#progress).

## Progress

**API**

- [x] Data model and the initial Alembic migration
- [x] `POST /jobs`: idempotent, keyed on a server-computed `request_key`
- [x] `GET /jobs/{id}`: job status derived from its proteins
- [x] `GET /jobs/{id}/pockets`: sort, filter, paging, and a `total` count
- [x] `GET /jobs/{id}/structures/{accession}`: serves the model (local files; `gs://` returns 501)
- [x] Ingest module and CLI: the result cache on `analysis_run`
- [ ] Publish new jobs to Pub/Sub (with a transactional outbox)
- [ ] Serve `gs://` structures through short-lived signed URLs

**Pipeline** (Nextflow)

- [x] Fetch the AlphaFold model, run fpocket, add SASA and pLDDT, write to PostgreSQL
- [x] One protein failing is reported and does not fail the batch
- [ ] Skip fpocket when a succeeded run already exists
- [ ] Write output to Cloud Storage (`--outdir gs://...`)
- [ ] Nextflow and Java in an image, for the Argo Workflow step

**Web**

- [x] Submit form, job status polling, per-protein status and errors
- [x] Sortable, filterable, paged pockets table
- [x] Mol* viewer, coloured by the selected pocket

**Images and CI**

- [x] API image and pipeline image, pinned by digest
- [x] CI: `infra`, `api`, `pipeline` and `images` (builds both images, with layer caching)
- [ ] Web image (nginx serving the build and proxying `/api`)
- [ ] Push images to Artifact Registry

**Infrastructure**

- [x] GCP project, APIs and the £10 budget with alerts (`infra/bootstrap`)
- [x] Artifact Registry repo, bucket and Pub/Sub topic defined (`infra/bootstrap/platform.tf`)
- [ ] Apply `platform.tf`
- [ ] Automatic billing shutdown
- [ ] OpenTofu state in a remote backend
- [ ] GKE Autopilot cluster root (`infra/cluster`), destroyed after each session
- [ ] Kustomize `deploy/` (`base/`, `overlays/local/`, `overlays/gke/`)
- [ ] Argo CD, Argo Events and Argo Workflows

## What it does

Submit a batch of UniProt accessions. For each one, pocketscan:

1. fetches the AlphaFold model,
2. runs [fpocket](https://github.com/Discngine/fpocket) to find and rank surface cavities,
3. adds structural context: solvent accessibility (SASA) and pLDDT per pocket,
4. returns a ranked table and the structure coloured by pocket in [Mol*](https://molstar.org/).

## Architecture

```
Browser (Svelte + Mol*)
   │
   ▼
FastAPI ──► PostgreSQL        (numbers: jobs, proteins, runs, pockets)
   │
   ▼
Pub/Sub ──► Argo Events ──► Argo Workflow ──► Nextflow pipeline
                                                  │
                                                  ▼
                                        Cloud Storage  (structures, fpocket output)
```

Argo is the glue; Nextflow does the science.

## Repository layout

A monorepo, deliberately. In production these would be split so that
infrastructure changes can have different reviewers and a smaller blast radius.

| Directory   | Contents                                              |
| ----------- | ----------------------------------------------------- |
| `api/`      | FastAPI service, Pydantic, SQLAlchemy, Alembic        |
| `pipeline/` | Nextflow pipeline, its Python helpers and image (Argo template still to do) |
| `deploy/`   | Kustomize: `base/`, `overlays/local/`, `overlays/gke/` |
| `infra/`    | OpenTofu for GCP                                      |
| `web/`      | Vite + Svelte page with the Mol* viewer               |

## Data model

Six tables. A request is `job` and `job_protein`; the rest are facts that
outlive any request.

| Table          | Purpose                                                          |
| -------------- | ---------------------------------------------------------------- |
| `job`          | A batch, with a unique `request_key`                             |
| `job_protein`  | Link table, with per-protein status and error                    |
| `protein`      | Deduplicated by `seq_sha256`, not by accession                   |
| `structure`    | The AlphaFold model, with its GCS URI                            |
| `analysis_run` | A tool, tool version and parameter hash against a structure      |
| `pocket`       | Rank, score, volume, mean SASA, mean pLDDT, residue list         |

## Design decisions

- **Cache on `analysis_run`**, keyed on tool version and parameter hash, so a
  tool upgrade invalidates results rather than mixing two versions.
- **Status lives on `job_protein`.** One protein failing does not fail the
  batch; the job's status is derived.
- **Idempotent.** Pub/Sub delivers at least once. A repeated `request_key`
  returns the existing job, and inserting a run is conditional on none existing.
- **Files to Cloud Storage, numbers to PostgreSQL**, so pockets can be sorted
  and filtered without reading files.
- **Pluggable analysis.** A job names an analysis; a second tool is a new
  step, not a rewrite.
- **Container images are pinned by digest**, not by tag.
- **`request_key` is computed on the server**: a hash of the analysis name and
  the sorted, de-duplicated, validated accessions. It does not include the tool
  version, so a tool upgrade does not change what counts as the same request.
- **The pipeline writes straight to PostgreSQL**, through the same module the
  API uses (`pocketscan_api.ingest`), so the cache rule lives in one place.
  Workflow pods therefore need the database URL and network access to it.
- **A job's status is derived.** It is `succeeded` once every protein has
  finished and at least one succeeded, so a succeeded job can still contain
  failed proteins; the UI shows each protein's own status and error.
- **The `protein` row is created at ingest**, not at submission, because it is
  keyed on the sequence hash and the sequence is only known once the pipeline
  has fetched the model.
- **fpocket's volume is a Monte Carlo estimate** and varies slightly between
  runs of the same structure. Scores and residues are stable.

## Out of scope

Users, projects and authentication; Cloud SQL; a second analysis step. These
are deliberate omissions.

## Development

Conventions: Python 3.14 with type hints and ruff; metric units throughout;
every schema change is an Alembic migration; tests run against a real
PostgreSQL service container, not SQLite.

Local prerequisites (so far):

- fpocket, built from source (needs `build-essential`) if running on Ubuntu.
  Record the git commit alongside the version (`params.tool_version` in
  `pipeline/nextflow.config`), since the result cache depends on it. The
  pipeline image builds it for you.
- Java and [Nextflow](https://www.nextflow.io/), for running the pipeline locally.
- Node and `pnpm`, for `web/`.
- `kubectl`, within one minor version of the cluster.
- `gcloud` (Google Cloud CLI), plus `google-cloud-cli-gke-gcloud-auth-plugin`
  so `kubectl` can authenticate to GKE.
- OpenTofu (`tofu`), matching the `required_version` in `infra/`.
- Once per checkout of each OpenTofu root, run `tofu init` in that directory
  (for example `infra/bootstrap/`). It downloads the pinned providers from the
  OpenTofu registry (`registry.opentofu.org/hashicorp/google`) and writes
  `.terraform.lock.hcl`, which is committed so provider builds stay pinned.
  `.terraform/` is not committed.
- [`uv`](https://docs.astral.sh/uv/) for the Python environments and lock files
  (`api/uv.lock` and `pipeline/uv.lock`, committed). The Python version is
  pinned in each `.python-version` and in `requires-python`.
- [`pre-commit`](https://pre-commit.com/), to run ruff on commit. Install it
  once, then enable the hook once per clone:
  ```bash
  uv tool install pre-commit
  pre-commit install
  ```
  The hooks are defined in `.pre-commit-config.yaml` (ruff lint with `--fix`,
  and ruff format, on staged files under `api/`; `pipeline/` is linted by CI
  only). If a hook changes a file the
  commit is aborted: `git add` the changes and commit again. Hooks are local
  and can be skipped, so CI is the enforcement: it runs `ruff check` and
  `ruff format --check`.
- Podman, not Docker, for local containers. Tests read the database location
  from `TEST_DATABASE_URL`, so any reachable PostgreSQL works.

### Running it locally

From the repository root. Each numbered step is independent of the later ones.

1. **PostgreSQL** (Podman, port 5433). Safe to re-run; it creates the container
   and databases if missing and writes the password and database URL to the
   untracked `api/.env`:
   ```bash
   cd api
   uv sync
   uv run python scripts/init-and-run-local-postgresql.py
   ```
2. **Schema:**
   ```bash
   uv run alembic upgrade head
   ```
3. **Tests**, using the `export TEST_DATABASE_URL=...` line that step 1 printed:
   ```bash
   uv run pytest
   uv run ruff check && uv run ruff format --check
   ```
4. **API** at <http://localhost:8000> (interactive docs at `/docs`). To let the
   viewer load structures from a local pipeline run, add
   `POCKETSCAN_LOCAL_STRUCTURE_ROOT=<repo>/pipeline/results` to `api/.env`, and
   restart the API after any change to `.env`:
   ```bash
   uv run uvicorn pocketscan_api.main:app --reload
   ```
5. **Web** at <http://localhost:5173>. Vite proxies `/api` to the API, so there is
   no CORS to configure:
   ```bash
   cd web
   pnpm install
   pnpm dev
   pnpm check    # type-check
   ```
6. **Pipeline.** Submit accessions in the web UI (the job id is in the URL,
   `#job=N`), then run the pipeline for that job. `POCKETSCAN_DATABASE_URL` is
   the value in `api/.env`, and it must be exported in the shell that runs
   Nextflow; the pipeline refuses to start without it:
   ```bash
   cd pipeline
   uv sync
   export POCKETSCAN_DATABASE_URL=postgresql+psycopg://postgres:<password>@127.0.0.1:5433/pocketscan
   uv run nextflow run main.nf --job_id <id> --accessions P08100,P0DTC2
   uv run pytest
   ```
7. **Images.** Build from the repository root, because `pipeline/` depends on
   `../api` by path:
   ```bash
   podman build -f api/Dockerfile -t pocketscan-api .
   podman build -f pipeline/Dockerfile -t pocketscan-pipeline .
   ```
   The base images are pinned by digest in the Dockerfiles. `.dockerignore`
   keeps `.env` files out of the build context.

## Infrastructure and cost

All infrastructure is OpenTofu and all cluster state is Git; nothing is
changed by hand in the GCP console. The GCP project is separate, with a £10
budget and alerts (the automatic shutdown is planned, not built). The GKE cluster is created and
destroyed per session with `tofu destroy`; a node pool is never left running.

### GCP project prerequisites

Done once, by hand, before the first `tofu apply`. These are the only steps
that cannot be OpenTofu, because the provider needs them in place first.

1. Create a separate GCP project and note its **project ID** (not the display
   name or number); the ID is what `gcloud` and OpenTofu take.
2. Link a billing account to the project. A free-trial credit is enough; no
   deposit is needed, and it expires after a fixed period. Note the **billing
   account ID** (for example `015DF0-EAA37D-C6C842`); the budget in
   `infra/bootstrap/` takes it as the `billing_account` variable. Find it with:
   ```bash
   gcloud billing projects describe <project-id> --format='value(billingAccountName)'
   gcloud billing accounts list
   ```
   The ID is the part after `billingAccounts/`. If you have more than one
   billing account, use the one the project is linked to.
3. Make sure your account has Owner on the project and Billing Account
   Administrator on the billing account (project Owner does not cover the
   billing account).
4. Authenticate and point the tools at the project:
   ```bash
   gcloud auth login
   gcloud config set project <project-id>
   gcloud auth application-default login
   gcloud auth application-default set-quota-project <project-id>
   ```
   OpenTofu uses the application default credentials, not the `gcloud auth login`
   session. The quota project is needed because the Billing Budgets API
   rejects user-credential calls without one.
5. Enable the APIs the provider itself depends on:
   ```bash
   gcloud services enable serviceusage.googleapis.com cloudbilling.googleapis.com \
     billingbudgets.googleapis.com --project <project-id>
   ```
   All other APIs are enabled by OpenTofu.
6. The £10 budget with alerts, measured **before credits** so free credit does
   not hide real usage, is created by OpenTofu in the long-lived
   `infra/bootstrap/` root, which is never destroyed; only the cluster root is
   destroyed each session. Nothing to do by hand for this step.

Before any `tofu apply`, check `gcloud config get project` shows the
pocketscan project.

### Bootstrap root (`infra/bootstrap/`)

The long-lived layer, applied once and never destroyed. It currently enables
the project's APIs (`serviceusage`, `cloudresourcemanager`, `cloudbilling`,
`billingbudgets`, `iam`, `compute`, `container`, `pubsub`, `artifactregistry`,
`storage`) with `disable_on_destroy = false`. It also holds the £10 monthly
budget (`budget.tf`), measured before credits, with email alerts at 50% and
90% of actual spend and at 100% of actual and forecast spend. Alerts go to the
billing account's administrators by default. Budget data lags by up to a day,
so this is an alarm, not a hard cap. The automatic shutdown is not built yet.

`platform.tf` defines the pieces that must outlive the per-session cluster: the
Artifact Registry repository `pocketscan` (no cleanup policy, because manifests
pin images by digest), a private bucket `<project-id>-data` whose objects expire
after 30 days, and the Pub/Sub topic `pocketscan-jobs` with its subscription
(which never expires, unlike the default 31 days of inactivity).

```bash
cd infra/bootstrap
tofu init
tofu plan -out=tfplan
tofu apply tfplan
```

From the repository root, `tofu -chdir=infra/bootstrap <command>` does the same
(`-chdir` is a global option and goes before the subcommand).

- The three APIs enabled by hand in step 5 above are adopted into state by the
  first apply; enabling an API that is already on is a no-op.
- State is **local** (`terraform.tfstate` in this directory, not committed).
  Keep it: without it OpenTofu no longer knows what it manages. Moving to a
  remote backend is a later decision.
- Saved plan files (`tfplan`) can contain sensitive values and must not be
  committed.
