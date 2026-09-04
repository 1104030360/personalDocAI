# PersonalDocAI

A personal visual filing cabinet: snap it, drop it in, ask for it back.
**Single-user, local-first.** Photos stay on this machine by default.

Upload a photo or PDF → VLM writes text + four metadata fields → embedding in
PostgreSQL + pgvector. Ask in Chinese or English; the answer follows the question
language. Daily operations: [`LAUNCH.md`](LAUNCH.md).

This README and `LAUNCH.md` are English. The UI, specs, and `CLAUDE.md` are Traditional Chinese.

| | |
|---|---|
| Stack | Python 3.12, FastAPI, PostgreSQL 17 + pgvector, LangChain, LangGraph, Celery + Redis, Ollama |
| Services | `db` `redis` `app` `worker` (Docker Compose) |
| Tests | 716 passed, 0 skipped |
| API | 22 endpoints, zero DELETE |

## Start

Docker Desktop, [Ollama](https://ollama.com) on the Mac, Python 3.12 for tests, `mkcert` for HTTPS.

```bash
ollama pull gemma4 && ollama pull bge-m3
cp .env.example .env && $EDITOR .env
brew install mkcert && mkcert -install
mkdir -p certs
mkcert -cert-file certs/cert.pem -key-file certs/key.pem \
  $(ipconfig getifaddr en0) localhost 127.0.0.1
docker compose -f compose.yaml up -d
```

Open **`https://localhost:8000/`**. `http://` will not connect.

**Create `.env` first.** Compose bind-mounts `./.env`. If the file is missing, Docker
silently creates a **directory** named `.env` and the container reads nothing.

First boot only — empty DBs, then:

```bash
psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI      -f db/schema.sql
psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI_test -f db/schema.sql
```

`schema.sql` starts with `DROP TABLE`. After real photos, use `db/migrate_*.sql` only.

## How it runs

```
Browser -- HTTPS :8000 --> app (accept file only)
                             file -> data/staging/{job_id}.*
                             job_id -> redis -> Celery worker
                             privacy gate -> local Ollama, or optional S3/EC2 if
                             NON_SENSITIVE and remote is running
                             embed always local (bge-m3) -> db + data/
```

**202 is not 201.** Upload means queued, not stored. Success = the job disappears
and pending **N** increments. PDF = one job, retry per page.

Header toggle `本機` / `雲端` = local Ollama vs Ollama Cloud (embeddings stay local).
That is a different door from `CLOUD_ROUTE` (optional mailbox). Default `CLOUD_ROUTE=off`.
How to run the cloud path: [`LAUNCH.md` §9–10](LAUNCH.md#9-cloud-worker-mac).

SQL lives only in `photo_repository.py`. pytest fakes every AI call — the suite never
hits a real model.

| Page | URL |
|---|---|
| Upload / pending / browse / ask | `/ui/{upload,pending,browse,ask}.html` |
| Wireless camera | `/ui/camera-desk.html` |
| API | `/docs` |

Filing is irreversible. The VLM suggests; a human confirms. Full list: `/docs`.

| First endpoints | |
|---|---|
| `POST /photos` | **202** — queued |
| `GET /ingest-jobs` | Progress panel |
| `PATCH /photos/{id}/folder` | File from inbox |
| `POST /ask` | Question → answer + photo ids |
| `GET` / `PUT /settings/ai-backend` | Local / cloud inference |

## Tests and CI/CD

```bash
source .venv/bin/activate && uv pip install -r requirements.txt
pytest -q          # db must be Up (healthy). Never run two pytest sessions at once.
```

CI (`test.yml`): ruff → `schema.sql` → pytest on a throwaway pgvector. No Redis / Ollama / `.env`.

CD (`deploy.yml`): after `test` succeeds on `main`, push `cloud-worker` to ECR
(`<sha>` + `latest`). Restarts EC2 only if that instance is **running**. Stopped =
still green. No long-lived AWS keys (OIDC).

## Docs and dangers

| File | Role |
|---|---|
| [`LAUNCH.md`](LAUNCH.md) | Start/stop, URLs, backups, cloud worker |
| `docs/design/` | Canonical designs; a later file overrides only what it lists |
| `docs/spec/` | Features + `erm.dbml` (read-only unless the product owner approves) |

Out of scope (enforced): no multi-user, no DELETE, no undo after filing, no chat memory,
no cloud file store, no frontend framework, no STUN/TURN. S3 is a short-lived mailbox
for non-sensitive photos only. Metadata is four fields: `category`, `location`, `items`,
`content_time`.

Stop with `docker compose stop`. Do **not** `down -v`, volume prune, `volume rm personaldocai_pgdata`,
`schema.sql` on the real DB, or change `pg17` → `pg18`. Backups: [`LAUNCH.md` §6](LAUNCH.md#6-backups).
