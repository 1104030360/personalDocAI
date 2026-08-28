# PersonalDocAI

> A personal visual filing cabinet: snap it, drop it in, ask for it back in one sentence.

Upload a photo (or a PDF) and the system reads it with a vision model (VLM), turning it into
a text description plus four metadata fields, then stores it in PostgreSQL + pgvector as an
embedding. Afterwards you can ask in plain language — "上個月在 Target 買了什麼" or
"show me my receipts" — and LangGraph decides whether to run a filtered lookup or a semantic
search, with an LLM writing the final answer **in whatever language you asked in**.

**A single-user, fully local, genuinely demo-able side project.** No accounts, no cloud
storage — the photos and the database live on your own machine (only AI inference can be
switched between local Ollama and Ollama Cloud).

| | |
|---|---|
| Stack | Python 3.12 / FastAPI / PostgreSQL 17 + pgvector / LangChain / LangGraph / Celery + Redis / Ollama |
| Deployment | Docker Compose, four services (`db` `redis` `app` `worker`), starts on boot |
| Size | 5,716 lines of product Python + 4,026 lines of frontend (zero frameworks); 11,352 lines of tests |
| Tests | **543 passed, 0 skipped** (includes pytest-bdd running the `.feature` specs directly) |
| API | **22 endpoints**, zero DELETE in `openapi.json` (having no delete is a settled spec decision) |

> **Note on language.** This README and [`LAUNCH.md`](LAUNCH.md) are in English. Everything
> else — the web UI, the specs under `docs/`, `CLAUDE.md`, code comments, and the seed data —
> is in Traditional Chinese, which is the project's working language. Where this document
> shows a real UI string or database value, it keeps the Chinese original and glosses it in
> English rather than inventing a translation that isn't in the code.

---

## Contents

1. [What it does](#1-what-it-does)
2. [Five-minute start](#2-five-minute-start)
3. [Architecture](#3-architecture)
4. [The two main flows](#4-the-two-main-flows)
5. [Web interface](#5-web-interface)
6. [Data model](#6-data-model)
7. [API overview](#7-api-overview)
8. [Configuration (`.env`)](#8-configuration-env)
9. [Development and testing](#9-development-and-testing)
10. [Documentation map](#10-documentation-map)
11. [Easy mistakes](#11-easy-mistakes)
12. [Explicitly out of scope](#12-explicitly-out-of-scope)

---

## 1. What it does

| Feature | Notes |
|---|---|
| **Upload photos / PDFs** | JPEG, PNG, PDF; several files at once. A PDF is stored one photo per page |
| **Wireless camera** | The desktop page shows a QR code; scan it and your phone becomes a wireless camera (WebRTC preview, shutter uploads straight into the queue) |
| **Vision understanding** | Produces a text description plus four metadata fields: `category` / `location` / `items` / `content_time` |
| **Folders (drawers)** | A photo lives in exactly one. The VLM suggests, **a human confirms, and the decision is irreversible** |
| **Entities (pins)** | A photo can carry many, e.g. "my MacBook". Stored in a link table, never in the vector |
| **Tasks** | The VLM also judges whether something is actionable, but **nothing is written until a human confirms** (it never touches Gmail or a calendar) |
| **Natural-language questions** | Chinese and English; the answer follows the language of the question, and photo content is never translated |
| **AI backend switch** | One toggle in the header flips between local Ollama and Ollama Cloud, effective immediately (embeddings always stay local) |
| **Background queue** | Upload returns 202 immediately; the vision work happens in a worker, with a progress panel visible on every page |

---

## 2. Five-minute start

### Prerequisites

- Docker Desktop
- [Ollama](https://ollama.com) running **on the Mac, not in Docker**, with two models pulled
- Python 3.12 (only needed to run the tests; the services themselves live in containers)
- `mkcert` — for HTTPS certificates, because mobile browsers only grant camera access on a secure origin

```bash
# 1. Models
ollama pull gemma4          # vision + text (VLM_MODEL / LLM_MODEL)
ollama pull bge-m3          # embeddings, 1024 dimensions, bilingual

# 2. Config file (.env is not in version control; create it by hand, see section 8)
touch .env && $EDITOR .env

# 3. HTTPS certificate (once per machine)
brew install mkcert && mkcert -install
mkdir -p certs
mkcert -cert-file certs/cert.pem -key-file certs/key.pem \
  $(ipconfig getifaddr en0) localhost 127.0.0.1

# 4. Start the services (brings up db / redis / app / worker together)
docker compose -f compose.yaml up -d
```

Open **`https://localhost:8000/`** — note the **`https`**. Plain `http://` will not connect at
all, because the container's start command always carries the certificate and one process
cannot listen for HTTP and HTTPS at the same time.

> **Create `.env` first.** `compose.yaml` has a `./.env:/app/.env` bind mount. When the source
> file is missing, Docker **does not error — it silently creates a directory named `.env`**,
> and the container then reads no configuration at all.

### First database run

The `db` container creates both `PersonalDocAI` and `PersonalDocAI_test` on first start.
Load the schema into each one:

```bash
psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI      -f db/schema.sql
psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI_test -f db/schema.sql
```

> **`schema.sql` begins with `DROP TABLE IF EXISTS`** — it wipes and rebuilds. Once you have
> real photos, all structural changes go through the re-runnable migration scripts instead
> (`db/migrate_folders.sql` → `migrate_design3.sql` → `migrate_design5.sql`).

The full day-to-day manual — starting, stopping, dev mode, backups, monitoring,
troubleshooting — is in **[`LAUNCH.md`](LAUNCH.md)**.

---

## 3. Architecture

```
+---------------------------- Your Mac ---------------------------------+
|                                                                       |
|   Browser                                       +---------------+     |
|   iPhone   ---- HTTPS :8000 ----------------->  |     app       |     |
|  (scans QR)                                     |  FastAPI      |     |
|                                                 |  accepts the  |     |
|                                                 |  file only    |     |
|                                                 +-------+-------+     |
|                                    (2) job_id only      |             |
|   (1) the file lands first                              v             |
|   data/staging/{job_id}.jpg  ---+               +---------------+     |
|   (image bytes never enter      |               |    redis      |     |
|    the queue)                   |               | queue+progress|     |
|                                 |               +-------+-------+     |
|                                 |     (3) pick up work  |             |
|                                 |                       v             |
|                                 |               +---------------+     |
|                                 +---- read ---->|    worker     |     |
|                                                 |  Celery x2    |     |
|                                                 +---+-------+---+     |
|                                (4) vision/embed     |       | (5) write|
|                                                     v       v         |
|                    +--------------+        +----------------------+   |
|                    |   Ollama     |<-------|         db           |   |
|                    | (host:11434) |        | PostgreSQL 17        |   |
|                    | gemma4       |        | + pgvector (HNSW)    |   |
|                    | bge-m3       |        +----------------------+   |
|                    +--------------+                                   |
|                          ^                originals/thumbs -> data/   |
|                          |  when the switch is flipped to "cloud",    |
|                          +-- gemma4 calls go to https://ollama.com    |
|                              (embeddings always stay local)           |
+-----------------------------------------------------------------------+
```

**Layering rule** (enforced by tests that scan the code):

```
api/routers/  -- HTTP, status codes, error messages
      |
      v
services/     -- vision, embeddings, storage, the queue task body
                 (knows nothing about HTTP)
      |
      v
repositories/ -- the only place in the system that writes SQL
                 (photo_repository.py)
```

Four AI injection points in `app/dependencies.py` — `get_vlm`, `get_router`, `get_answerer`
and `get_entity_suggester` — follow the backend switch; `get_embeddings` and `get_now` do not.
pytest replaces all six with fakes, so **the tests never call a real model**.

---

## 4. The two main flows

### 4.1 Upload is asynchronous (202, not 201)

```
POST /photos     (or POST /camera/{token}/photos from the wireless camera)
   |
   +- wrong format ---------------------------------> 415, nothing stored
   |
   +- (1) write data/staging/{job_id}.jpg
   +- (2) create the job (status=queued)
   +- (3) push onto the Celery queue
   |          ^ strict order: if any step fails, everything is cleaned up
   |
   +-> 202 Accepted {job_id, filename, content_type}
        ^
        +-- at this moment the photo table is unchanged
            and the pending wall is still empty

  worker (background: 64-88 s per photo locally, about 2 s on cloud)
   |
   +- vision -- fail -> retry -- fail -> retry   (3 attempts, first one included)
   |                                     |
   |                                     +- all three fail -> delete staging
   |                                                          job = failed
   |                                                          zero rows in photo
   +- embed (bge-m3, always local)
   +- INSERT into the inbox folder (the three VLM hints are stored alongside)
   +- write the original and the thumbnail into data/
   +- delete the job   <- the job disappearing IS success
                          (JobStore has no "success" state)
```

A job has exactly four states: `queued` -> `analyzing` -> `retrying` -> `failed`.
The frontend polls `GET /ingest-jobs` every two seconds to draw the panel in the bottom-right
corner; a failed row is dismissed with its `x` button
(`POST /ingest-jobs/{job_id}/dismiss`, which **only accepts `failed`**).

A PDF is **one job per file, retried per page**: three attempts per page, a failing page is
skipped, and only zero successful pages makes the whole job fail. Redelivery after a crash is
made idempotent by `photo_ids` and `pages_done`.

### 4.2 Asking is a four-way LangGraph

```
POST /ask {"question": "What did I buy at Target last month?"}
   |
   v
 route -- one structured LLM call: pick the search mode and extract filters
   |      (bilingual few-shot examples)
   |
   +- metadata -> filtered lookup with ILIKE (category / location / items)
   +- vector   -> pgvector `<=>` cosine distance, top 5
   |                ^ any routing failure falls back to this one
   +- entity   -> every photo pinned to that entity
   |              (prefixed with one line stating the pin as a fact)
   +- task     -> tasks ordered by due_date ("this week" = +7 days)
   |
   |   The two photo paths share one time filter:
   |   COALESCE(content_time, uploaded_at::date) >= today - 30 days
   v
 generate -- three hard rules: answer only from the retrieved photos,
             never invent anything when nothing is found, and reply in the
             language of the question (photo content is never translated)
   |
   v
 200 {answer, search_mode, retrieved_photo_ids}
        ^
        +-- search_mode and ids are read straight off the graph state,
            never from the AI
```

---

## 5. Web interface

Zero frameworks, zero bundlers, zero npm — five plain HTML files served from `/ui`, sharing
one `style.css`.

```
+----------------------------------------------------------------+
| PersonalDocAI   上傳照片 | 待決定(3) | 瀏覽資料夾 | 問問題      |
|                                          AI 模型 [本機|雲端]    |
+----------------------------------------------------------------+
   ^ the real header. Left to right: Upload / Pending(3) / Browse
     folders / Ask; the toggle on the right is local vs cloud.
```

| Page | URL | Purpose |
|---|---|---|
| Upload | `/ui/upload.html` | Multi-select of images and PDFs, sent one request per file |
| Pending | `/ui/pending.html` | Inbox photos, driven through the full three-step modal chain |
| Browse | `/ui/browse.html` | Two tabs: folders and tasks |
| Ask | `/ui/ask.html` | One input box; the answer plus the photos it cited |
| Wireless camera | `/ui/camera-desk.html` | Generates the QR code, remote preview, shutter |
| API docs | `/docs` | Swagger UI generated by FastAPI |

**The three-step modal chain** is the only way to file a photo. It forces a decision — there
is no `x` and no Esc escape hatch:

```
  +-- Drawer -------+   +-- Entity -------+   +-- Task ---------+
  | 1. take hint    |   | 1. take hint    |   | title (prefilled)|
  | 2. pick existing|-->| 2. pick existing|-->| due   (prefilled)|
  | 3. create new   |   | 3. create one   |   | [Create] [Skip]  |
  | 4. decide later |   | 4. skip, go on  |   +------------------+
  +-----------------+   +-----------------+    Opens only when a
   exactly one folder    many pins allowed     task hint exists;
   irreversible          (= pushpins)          never for an empty one
```

All three steps read hints that were stored at ingest time, so **the image is never looked at
a second time**. Every piece of dynamic content goes through `textContent` / `esc()`, and
`alert` / `confirm` / `prompt` are **banned across the whole frontend** (a test scans for
them); errors are written into a red area inside the modal instead.

---

## 6. Data model

```
                     +------------------+
                     |      folder      |  six seed rows (id 1-6):
                     |  name (UNIQUE)   |  inbox + Receipts / Food /
                     |  is_inbox        |  Scenery / Documents / Other
                     +--------+---------+  a partial unique index guarantees
                              | 1          at most one inbox system-wide
                              |
                              | many
                     +--------+-------------------------+
                     |             photo                |
                     |  text            VLM description |
                     |  category        = folder.name   |
                     |  location/items/content_time     |  <- the four fixed
                     |  embedding       vector(1024)    |  <- HNSW + cosine
                     |  original_path/thumbnail_path    |  <- DB stores only
                     |                                  |     relative paths
                     |  suggested_category              |  \  three hint
                     |  suggested_entity                |   | columns, stored
                     |  suggested_task_title/_due       |  /  at ingest; only
                     |                                  |     a human confirms
                     +---+--------------------------+---+
             1:at most 1 |                          | many
                         v                          v
                  +-------------+          +------------------+     +----------+
                  |    task     |          |   photo_entity   |many-1|  entity  |
                  | photo_id UQ |          | PK(photo,entity) |     | name  UQ |
                  | title       |          +------------------+     +----------+
                  | due_date    |            photo <-> entity        a pushpin;
                  +-------------+            many-to-many            the list only
                                                                     grows when a
                                                                     user creates one

  +--------------------+
  | folder_correction  |  Every time the user rejects a hint and picks something
  | suggested / chosen |  else, one row is recorded. These are injected into the
  | photo_text         |  VLM prompt as few-shot examples (N=5) so the model
  +--------------------+  learns this particular person's filing habits.
```

The seed folder names are stored in Chinese: `未分類` (unsorted, the inbox), `收據`
(receipts), `飲食` (food), `風景` (scenery), `文件` (documents), `其他` (other). Insertion
order is the id order, 1 through 6.

Originals and thumbnails live on the filesystem and are **not in version control**:

```
data/
├── photos/   {id}.jpg|png     the original (the master copy; only one exists anywhere)
├── thumbs/   {id}.jpg|png     thumbnail (longest edge <= 512)
└── staging/  {job_id}.jpg|…   accepted but not yet analysed
                               Deleted on success or final failure, so it should
                               normally be close to empty. Orphans older than 24 h
                               are swept away when app and worker start.
```

---

## 7. API overview

22 endpoints. Full interactive documentation at `https://localhost:8000/docs`.

### Photos

| Method | Path | Notes |
|---|---|---|
| `POST` | `/photos` | Upload. **202** means accepted and queued — *not* "stored" |
| `GET` | `/photos/{id}` | Photo detail (read-only; there is no button to change the folder) |
| `GET` | `/photos/{id}/thumbnail` | Thumbnail; 404 if the row, the path, or the file is missing |
| `GET` | `/photos/{id}/image` | Original |
| `PATCH` | `/photos/{id}/folder` | File the photo. Only accepts photos still in the inbox (409 if already filed, 422 if the target is the inbox) |

### Folders, entities, tasks

| Method | Path | Notes |
|---|---|---|
| `GET` | `/folders` | Folder list with photo counts (empty folders still appear) |
| `GET` | `/folders/{id}` | Photo summaries for that folder (eight keys, newest first) |
| `GET` | `/entities` | Entity list |
| `POST` | `/photos/{id}/entities` | Pin an existing entity, or create one on the spot (same transaction) |
| `POST` | `/photos/{id}/entity-suggestion` | "Suggest another"; returns `null` when there is nothing left — that is not an error |
| `POST` | `/photos/{id}/task` | Create a task (at most one per photo; a second one gets 409) |
| `GET` | `/tasks` | Task list, `due_date ASC NULLS LAST` |

### Asking

| Method | Path | Notes |
|---|---|---|
| `POST` | `/ask` | `{question}` → `{answer, search_mode, retrieved_photo_ids}` |

### Ingest jobs (the only data source for the progress panel)

| Method | Path | Notes |
|---|---|---|
| `GET` | `/ingest-jobs` | In-flight and failed jobs, plus `pending_count` (inbox size) |
| `POST` | `/ingest-jobs/{job_id}/dismiss` | Dismiss a failed row. **Only `failed` is allowed.** It is a POST so that `openapi.json` stays free of DELETE |

### Wireless camera

| Method | Path | Notes |
|---|---|---|
| `POST` | `/camera/session` | Issues a pairing token and QR code (SVG rendered locally, no third-party service); TTL 600 s |
| `POST` | `/camera/{token}/photos` | Phone shutter; goes through the same ingest queue → 202 |
| `GET` | `/camera/{token}/latest` | Behaviour has been narrowed: always 204 |
| `WS` | `/camera/{token}/signal` | Pure WebRTC signalling relay (not in `openapi.json`; no STUN or TURN) |

### Everything else

| Method | Path | Notes |
|---|---|---|
| `GET` / `PUT` | `/settings/ai-backend` | Local/cloud switch. State is in memory only, so **a restart always returns to local**; switching to cloud without an API key gives 422 |
| `GET` | `/health` | `{"status": "ok"}` |
| `GET` | `/` | Redirects to `/ui/upload.html` |

---

## 8. Configuration (`.env`)

`.env` is not in version control. The minimum you need:

```bash
# Database (used by pytest and psql on the host; the container's value is
# overridden by compose.yaml)
DATABASE_URL=postgresql://postgres@127.0.0.1:5433/PersonalDocAI

# Local Ollama (also overridden to host.docker.internal by compose.yaml)
OLLAMA_BASE_URL=http://localhost:11434

# Model names: changing models means changing only these
VLM_MODEL=gemma4
LLM_MODEL=gemma4
EMBEDDING_MODEL=bge-m3

# Ollama Cloud (may stay empty = local only; the cloud switch needs this filled in)
OLLAMA_API_KEY=
OLLAMA_CLOUD_VLM_MODEL=gemma4
OLLAMA_CLOUD_LLM_MODEL=gemma4
```

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql://localhost:5433/PersonalDocAI` | Overridden to `db:5432` inside the container |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Overridden to `host.docker.internal` inside the container |
| `CELERY_BROKER_URL` | `redis://redis:6379/0` | The in-container form; pytest never touches it |
| `OLLAMA_API_KEY` | empty | Without it the switch cannot reach cloud (422) |
| `DATA_DIR` | `data` | A pytest fixture redirects this to a temporary directory |

**`DATABASE_URL`, `OLLAMA_BASE_URL` and `CELERY_BROKER_URL` are deliberately overridden**
by the `environment` block in `compose.yaml`. Editing those three lines in `.env` inside the
container has no effect no matter how often you restart. Changing any *other* value does
require `restart app worker`.

---

## 9. Development and testing

### Dev mode (hot reload)

```bash
# Two files layered; compose.dev.yaml must come second
docker compose -f compose.yaml -f compose.dev.yaml up -d
docker compose -f compose.yaml -f compose.dev.yaml logs -f app worker
```

**`--reload` only rescues `app`.** Celery has no hot reload, so after editing a `.py` file the
worker is still running the old code — and the symptom is that *HTTP behaviour is already new
while photo analysis behaves as before, with no error at all*. Editing worker-side code
requires `restart worker`.

### Running the tests

```bash
source .venv/bin/activate
uv pip install -r requirements.txt
pytest -q            # 543 passed, 0 skipped
                     # (tests run on the host against the test DB inside Docker)
```

Running only the spec binders (pytest-bdd executing the `.feature` files directly):

```bash
pytest tests/integration/test_upload_feature.py \
       tests/integration/test_ask_feature.py \
       tests/integration/test_camera_feature.py -v
```

**Four autouse safety nets** in `tests/conftest.py` — the foundation of this project's tests:

```
reset_tables           TRUNCATEs the test DB per test and replays the six
                       folder seed rows          -> never touches the real DB
wire_fake_ai           swaps all six injection
                       points for fakes          -> never calls the real Ollama
isolated_data_dir      points DATA_DIR at tmp_path -> never writes the project data/
wire_memory_job_store  in-memory JobStore, an
                       accounting fake dispatcher -> never reaches Redis or Celery
```

Zero external dependencies is **demonstrated, not merely intended**: point both
`OLLAMA_BASE_URL` and `CELERY_BROKER_URL` at a dead port, run the full suite, and the count
is unchanged.

> **Never run two pytest sessions at once.** `reset_tables` TRUNCATEs the same test database
> in every test, so two runs wipe each other's data. The symptom is a large number of
> apparently random 404s and `NoneType` errors, with a different failure count each time.

### Code style

ruff replaces black, flake8 and isort in one tool; configuration lives in `pyproject.toml`
(`line-length = 100`, rules `E` / `F` / `I`, with `E501` deliberately disabled because ruff
counts CJK characters as double width).

```bash
ruff format --check app tests scripts && ruff check app tests scripts   # check only
ruff format app tests scripts && ruff check app tests scripts --fix     # fix
```

A pre-commit hook runs the same two tools over staged `.py` files. It is not installed
automatically — run it once per clone:

```bash
pre-commit install
```

CI (`.github/workflows/test.yml`) runs the check-only form plus the full test suite on every
push and pull request, against a throwaway pgvector container.

### Project layout

```
app/
├── main.py              FastAPI assembly: eight routers + /ui static files + staging sweeper
├── celery_app.py        Celery task (a thin wrapper: fetch job -> build parts -> run_ingest_job)
├── dependencies.py      Six injection points (4 AI + embeddings + clock) + JobStore + dispatcher
├── core/config.py       The only place in the project that reads environment variables
├── api/routers/         ask camera entities folders ingest_jobs photos settings tasks
├── schemas/             Pydantic contracts for the outside world
├── services/
│   ├── vlm_service.py           vision (local/cloud) + prompt assembly + clamping
│   ├── indexing_service.py      merges fields in a fixed order -> embedding
│   ├── ask_workflow.py          LangGraph: route -> four retrieval paths -> generate
│   ├── retrieval_service.py     custom @chain retriever (deliberately not PGVector store)
│   ├── ingest_job.py            the ingest task body (knows nothing of HTTP or Celery)
│   ├── ingest_job_store.py      JobStore, Redis and in-memory implementations
│   ├── storage_service.py       writes the original and the thumbnail
│   ├── staging_service.py       the staging area and its 24-hour sweeper
│   ├── pdf_service.py           the only place that touches pypdfium2
│   ├── camera_session_service.py pairing tokens (memory only, never persisted)
│   ├── ollama_cloud.py          the only place that builds a cloud client
│   └── ai_timing.py             timing logs for the five call kinds
├── repositories/photo_repository.py   * the only place that writes SQL
└── static/              five HTML pages + four modal scripts + progress panel + one style.css

db/       schema.sql (rebuild) + three re-runnable migration scripts
docs/     spec / design (six canonical designs) / plan (plans and reports)
tests/    unit (13) + integration (36, including three .feature binders)
scripts/  check_embedding_dim.py (manual real-model smoke test, never in CI)

compose.yaml      production-style, always on (db / redis / app / worker, no --reload)
compose.dev.yaml  dev overlay (app hot reload + source bind mounts)
Dockerfile        one image shared by app and worker
pyproject.toml    ruff + pytest configuration (not a distributable package, so no [project])
.pre-commit-config.yaml   ruff on staged .py files at commit time
.github/workflows/test.yml CI: format check -> lint -> schema -> pytest
```

---

## 10. Documentation map

This project is **spec-driven**: spec → design → per-phase plan → TDD implementation → report.

| Location | What it is | When to read it |
|---|---|---|
| [`LAUNCH.md`](LAUNCH.md) | Startup and daily operations (start/stop, backup, monitoring, troubleshooting) | **Every day** |
| [`CLAUDE.md`](CLAUDE.md) | Full project context and settled decisions, written for AI collaborators | Before taking over or changing code |
| `docs/spec/features/*.feature` | Seven Gherkin acceptance specs (**read-only**; changes need the product owner's approval) | To learn how it is *supposed* to behave |
| `docs/spec/erm.dbml` | The spec-level data model | Same |
| `docs/spec/.clarify/resolved/` | 18 settled clarifications (**including the rejected options, which may not be reopened**) | Before changing any design |
| `docs/design/design.md` … `design5.md` | Six canonical designs; each later one states what it overrides | To learn *why* it is built this way |
| `docs/plan/finish/` | 77 completed phase plans (Phase 01–72) | Archaeology |
| `docs/plan/report/` | Execution reports for each stage | Archaeology |

**Precedence when sources conflict:** `.clarify/resolved/` → `erm.dbml` + `.feature` → design
drafts. Among the six designs, a later one overrides an earlier one **but only for the items
it explicitly lists**.

---

## 11. Easy mistakes

| Symptom | What is actually going on |
|---|---|
| "I uploaded and the photo isn't on the pending page" | **Expected.** 202 only means accepted; it is done when the progress panel clears and the header count goes up by one |
| "Every photo fails to analyse and the red text means nothing to me" | The worker is reporting `Errno 101 Network is unreachable`, which means **Ollama on the Mac is not running**. `open -a Ollama` fixes it with no container restart (switching to cloud does not help — embeddings are always local) |
| "`http://localhost:8000` won't connect at all" | The URL is missing its **s**. The container only ever speaks HTTPS |
| "I edited a `.py`, the API changed but the analysis didn't" | Celery has no hot reload; `restart worker` |
| "My phone scans the QR but can't connect" | Open the desktop page on a LAN IP or the `.local` name, never `localhost` — otherwise the QR points at a Docker-internal subnet. The test: the QR's host must match `ipconfig getifaddr en0` character for character |
| "The iPhone scans the QR and Safari blocks it" | The mkcert root certificate is not trusted, or the "Certificate Trust Settings" step was skipped |
| Large numbers of random 404s in pytest | Two pytest sessions running at once, TRUNCATE-ing the same test database |

### Operations that destroy data

```
docker compose down -v            <- -v deletes the volumes too. Always stop with `stop`
docker system prune --volumes     <- removes any volume no container currently references
docker volume rm personaldocai_pgdata
changing pg17 to pg18 in compose  <- PGDATA moves, so the mount is no longer the data dir
```

The two volumes are not remotely equivalent:

```
personaldocai_pgdata     <- the real database (photo rows, folders, entities,
                            tasks, vectors). Losing it is a disaster
personaldocai_redisdata  <- progress rows and unfinished jobs. Losing it only
                            costs you the photos that had not finished analysing
```

**Backing up the database alone is not enough** — the originals under `data/` are not in
version control, so exactly one copy exists anywhere:

```bash
pg_dump -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI --no-owner --no-acl -Fc \
  -f ~/PersonalDocAI-backup-$(date +%F).dump
tar -czf ~/PersonalDocAI-data-$(date +%F).tar.gz data/
```

---

## 12. Explicitly out of scope

These are settled spec decisions, not unfinished work. Most are enforced by tests that scan
the code, so quietly adding one back turns the suite red:

- No multi-user support or accounts (photos have no owner; there is no `user` column)
- No deleting photos (`openapi.json` contains zero DELETE)
- No changing a folder after it is decided (the backend answers 409; there is no undo)
- No conversational memory (every question stands alone)
- No cloud storage (photos never leave your machine; only AI inference can go to the cloud)
- No frontend framework or bundler (plain HTML and vanilla JS)
- No `alert` / `confirm` / `prompt`
- No automatic capture, no second model, no tool calling, no writing to Gmail or a calendar
- No STUN or TURN, no third-party QR service (everything stays on the machine or the LAN)
- No fifth metadata field (`category`, `location`, `items` and `content_time` are fixed)
