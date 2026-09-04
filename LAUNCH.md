# LAUNCH.md — daily operations

Start / stop, URLs, tests, backups, optional cloud worker.
Product intro: [`README.md`](README.md).

Four Docker services: `db` `redis` `app` `worker`. **HTTPS only.** Ollama stays on the
Mac — after Quit it does not come back; the site still loads and upload still returns
202, but analysis fails and `/ask` is 500.

## 1. Quick start

Bookmark (survives Wi-Fi / IP changes):

```
https://$(scutil --get LocalHostName).local:8000/
```

```bash
docker compose -f compose.yaml up -d          # four Up; db + redis healthy
open -a Ollama
curl -s http://127.0.0.1:11434/api/version    # JSON = up
```

After `docker compose stop`, a reboot will **not** restart them — `up -d` again.

## 2. URLs

Always `https`. `http://` never connects (uvicorn starts with `--ssl-*`).

| | |
|---|---|
| Pages | `https://<host>.local:8000/ui/{upload,pending,browse,ask}.html` |
| Camera desktop | `https://<host>.local:8000/ui/camera-desk.html` |
| API | `https://<host>.local:8000/docs` |
| Local fallback | `https://localhost:8000/` (not for camera) |

Open camera-desk on **`.local`**, not `localhost` — otherwise the QR host is a Docker
`172.x` the phone cannot reach. QR host must equal `ipconfig getifaddr en0` exactly.
Phone: scan the QR; never type a URL.

## 3. Start, stop, restart

```bash
cd /Users/linjunting/personalDocAI
docker compose -f compose.yaml up -d
docker compose stop                           # keeps volumes
docker compose logs -f app worker             # Ctrl+C leaves containers up
docker compose ps --no-trunc                  # --no-trunc required to see --reload
```

**Dev overlay** — `compose.dev.yaml` **second** (`--reload` + bind-mount `./app`):

```bash
# always-on → dev
docker compose -f compose.yaml stop app worker
docker compose -f compose.yaml -f compose.dev.yaml up -d
# dev → always-on
docker compose -f compose.yaml -f compose.dev.yaml stop
docker compose -f compose.yaml up -d
```

Wait until the worker is idle before restarting it (`/ingest-jobs` has no `analyzing` /
`retrying`). A mid-job restart is **not** redelivered — the row stays analyzing forever.

| Changed | Do this |
|---|---|
| `.py` HTTP in **dev** | Nothing (app `--reload`) |
| `.py` analysis | `restart worker` (same `-f` you started with). Silent if you skip. |
| `.py` **always-on** | `up -d --build` |
| `.env` | `restart app worker` |
| `requirements.txt` | `build app` then `up -d` |
| `certs/` | `restart app` |
| Camera pairing | New QR (reload clears the token) |

`DATABASE_URL` / `OLLAMA_BASE_URL` / `CELERY_BROKER_URL` in the container come from
compose `environment` and ignore `.env`. Do camera tests in always-on mode.

## 4. Network / certs

`.local` URL: do nothing when the IP changes. Re-sign only if you renamed the Mac or
mDNS is blocked:

```bash
ipconfig getifaddr en0
openssl x509 -in certs/cert.pem -noout -text | grep -A2 "Subject Alternative Name"
mkcert -cert-file certs/cert.pem -key-file certs/key.pem \
  $(scutil --get LocalHostName).local $(ipconfig getifaddr en0) localhost 127.0.0.1
docker compose restart app
```

## 5. Tests and database

`db` must be healthy. **Never run two pytest sessions** (they TRUNCATE the same test DB).

```bash
source .venv/bin/activate
pytest -q
AWS_ENDPOINT_URL=http://127.0.0.1:9 CELERY_BROKER_URL=redis://127.0.0.1:9/0 \
  OLLAMA_BASE_URL=http://127.0.0.1:9 pytest -q    # same count = no external deps
ruff format --check app tests scripts && ruff check app tests scripts
```

`~/.zshrc`: `PGPORT=5433` `PGUSER=postgres` `PGHOST=127.0.0.1`.

```bash
psql -d PersonalDocAI
psql -d PersonalDocAI_test
```

Never `schema.sql` on `PersonalDocAI` (`DROP TABLE`). Never touch `postgresql@14` on 5432.

## 6. Backups

```bash
pg_dump -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI --no-owner --no-acl -Fc \
  -f ~/PersonalDocAI-backup-$(date +%F).dump
tar -czf ~/PersonalDocAI-data-$(date +%F).tar.gz data/    # originals; not in git
```

`personaldocai_pgdata` = real DB. `personaldocai_redisdata` = unfinished jobs only.
`down -v` deletes both.

## 7. Monitoring and troubleshooting

```bash
docker compose ps
curl -s http://127.0.0.1:11434/api/version
curl -sk https://127.0.0.1:8000/ingest-jobs | python3 -m json.tool
docker compose logs worker | grep -E "route=|fallback="
```

`202` = queued. Success deletes the job. `route=local verdict=SENSITIVE|UNCERTAIN` stayed
here. `route=cloud` went to S3. `fallback=local reason=…` tried cloud and came home.

| Symptom | Fix |
|---|---|
| Site will not load | Use `https://` |
| Models / keys empty after clone | `./.env` became a **directory** — `stop`, `rmdir .env`, `cp .env.example .env`, `up -d` |
| Cert warning on LAN IP | Re-sign + `restart app` |
| `.env` edited, no change | `restart app worker` (same `-f`) |
| 202 but no photo | Worker or Ollama down, or still analysing (60–90 s local) |
| QR is `172.x` | Open camera-desk on `.local` |
| Safari “offline” on phone | Install mkcert root + enable full trust |
| All jobs fail, `ConnectError` | `open -a Ollama` |
| Random pytest 404 | Another pytest is running |
| Job stuck `analyzing` | Worker restarted mid-job — clear Redis key, re-upload |

AWS CLI: `set -a; . ./.env; set +a; unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY`
(CLI must stay on `~/.aws` admin). Idle mailbox: `documents/` empty, both queues 0.

## 8. Never

`docker compose stop` only. Do not: `down -v`, volume prune, `volume rm personaldocai_pgdata`,
`schema.sql` on the real DB, `pg17`→`pg18`, NAT / Elastic IP / inbound SSH,
Terminate a CPU box you still need, expose Ollama on `0.0.0.0`.

## 9. Cloud worker (Mac)

Not the Celery `worker`. Day to day it should be off.

`CLOUD_ROUTE`: `off` (default) / `assume` (this section) / `ec2` (next). Restart Celery
worker after every change. Empty `WORKER_VLM_BACKEND` = `cloud`.

```bash
# terminal A — do not source .env here
python -m app.workers.cloud_worker
# expect: cloud_worker 啟動 version=dev … vlm=cloud model=…

# terminal B
# .env: CLOUD_ROUTE=assume   (optional: CLOUD_RESULT_TIMEOUT_SECONDS=30)
docker compose -f compose.yaml -f compose.dev.yaml restart worker
```

Upload a non-sensitive image (receipt, not an ID). Expect `route=cloud` then
`雲端結果已入庫`. **Done:** `CLOUD_ROUTE=off`, timeout `300`, `restart worker`.
Leave `assume` on with no process → every non-sensitive upload waits the full timeout.

## 10. Cloud worker (EC2)

Optional. Normally **stopped**. Running ≈ $0.22/h; disk while stopped ≈ $3/month.
On this Mac: `CLOUD_ROUTE=ec2` + `restart worker`. Stopped instance →
`fallback=local reason=remote_unavailable` (probe cached 60 s).

```bash
set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
aws ec2 start-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
aws ec2 wait instance-running --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
# every session ends with Stop, not Terminate:
aws ec2 stop-instances --instance-ids "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"
```

No SSH. `aws ssm start-session --target "$EC2_WORKER_INSTANCE_ID" --region "$AWS_REGION"`
then `sudo docker logs cloud-worker --tail 50` — first line `version=<git sha>`.
`WORKER_VLM_BACKEND` is on the instance (`/opt/personaldocai/worker.env`), not this Mac `.env`.
