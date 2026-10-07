# pocketscan

A pocket-detection platform for protein structures, built as a focused
demonstration of a scientific data platform: web app, queue, pipeline,
Kubernetes and GitOps.

> **Status:** early design. The architecture and data model are settled

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
| `pipeline/` | Nextflow pipeline and the Argo Workflow template      |
| `deploy/`   | Kustomize: `base/`, `overlays/local/`, `overlays/gke/` |
| `infra/`    | OpenTofu for GCP                                      |
| `web/`      | Svelte page with the Mol* viewer                      |

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

## Out of scope

Users, projects and authentication; Cloud SQL; a second analysis step. These
are deliberate omissions.

## Development

Conventions: Python 3.12 with type hints and ruff; metric units throughout;
every schema change is an Alembic migration; tests run against a real
PostgreSQL service container, not SQLite.

Local prerequisites (so far):

- fpocket, built from source (needs `build-essential` and `libnetcdf-dev`) if running on Ubuntu.
  Record the git commit alongside the version, since the result cache depends
  on it.
- `kubectl`, within one minor version of the cluster.
- `gcloud` (Google Cloud CLI), plus `google-cloud-cli-gke-gcloud-auth-plugin`
  so `kubectl` can authenticate to GKE.
- OpenTofu (`tofu`), matching the `required_version` in `infra/`.
- Once per checkout of each OpenTofu root, run `tofu init` in that directory
  (for example `infra/bootstrap/`). It downloads the pinned providers from the
  OpenTofu registry (`registry.opentofu.org/hashicorp/google`) and writes
  `.terraform.lock.hcl`, which is committed so provider builds stay pinned.
  `.terraform/` is not committed.

Build, run and test instructions will be added as each component lands.

## Infrastructure and cost

All infrastructure is OpenTofu and all cluster state is Git; nothing is
changed by hand in the GCP console. The GCP project is separate, with a £10
budget, alerts and automatic shutdown. The GKE cluster is created and
destroyed per session with `tofu destroy`; a node pool is never left running.

### GCP project prerequisites

Done once, by hand, before the first `tofu apply`. These are the only steps
that cannot be OpenTofu, because the provider needs them in place first.

1. Create a separate GCP project and note its **project ID** (not the display
   name or number); the ID is what `gcloud` and OpenTofu take.
2. Link a billing account to the project. A free-trial credit is enough; no
   deposit is needed, and it expires after a fixed period.
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
6. Create the £10 budget with alerts, measured **before credits** so free
   credit does not hide real usage. The budget and shutdown belong in the
   long-lived `infra/bootstrap/` root, which is never destroyed; only the
   cluster root is destroyed each session.

Before any `tofu apply`, check `gcloud config get project` shows the
pocketscan project.

### Bootstrap root (`infra/bootstrap/`)

The long-lived layer, applied once and never destroyed. It currently enables
the project's APIs (`serviceusage`, `cloudresourcemanager`, `cloudbilling`,
`billingbudgets`, `iam`, `compute`, `container`, `pubsub`, `artifactregistry`,
`storage`) with `disable_on_destroy = false`. The budget and shutdown are not
in it yet.

```bash
cd infra/bootstrap
tofu init
tofu plan -out=tfplan
tofu apply tfplan
```

- The three APIs enabled by hand in step 5 above are adopted into state by the
  first apply; enabling an API that is already on is a no-op.
- State is **local** (`terraform.tfstate` in this directory, not committed).
  Keep it: without it OpenTofu no longer knows what it manages. Moving to a
  remote backend is a later decision.
- Saved plan files (`tfplan`) can contain sensitive values and must not be
  committed.
