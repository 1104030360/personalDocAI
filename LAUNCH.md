# LAUNCH.md — startup and daily operations

Since 2026-08-24 PersonalDocAI runs inside Docker. **It starts automatically at boot; normally
you do not need to type anything.**

---

## Contents

1. [Quick start](#1-quick-start)
2. [URLs](#2-urls)
3. [Starting and stopping](#3-starting-and-stopping)
4. [Dev mode (hot reload)](#4-dev-mode-hot-reload)
5. [When the network changes](#5-when-the-network-changes)
6. [Running the tests](#6-running-the-tests)
7. [Database](#7-database)
8. [Backups](#8-backups)
9. [Monitoring and logs](#9-monitoring-and-logs)
10. [Troubleshooting](#10-troubleshooting)
11. [Never do these](#11-never-do-these)
12. [Cloud worker on the Mac](#12-cloud-worker-on-the-mac)

---

## 1. Quick start

**There is nothing to do. Just open this URL:**

```
https://linjuntingdeMacBook-Pro-1071.local:8000/
```

This URL **never changes** — not when you switch Wi-Fi, not when the IP changes. Bookmark it.

If the services are not up:

```bash
docker compose -f compose.yaml up -d
```

One more thing has to be running: **Ollama on the Mac** (its icon should be in the menu bar).
It is a login item and comes up at boot, but once you quit it manually **it does not come
back on its own** — and while it is down the website still loads and photos are still accepted
(202). What breaks is that **every analysis fails and asking a question returns 500**. This
actually happened on 2026-08-27. To bring it back:

```bash
open -a Ollama    # ready in about 4 s
                  # verify: curl -s http://127.0.0.1:11434/api/version
```

---

## 2. URLs

`HOST` below stands for `linjuntingdeMacBook-Pro-1071.local`:

| Page | URL |
|---|---|
| Home (redirects to upload) | `https://HOST:8000/` |
| Upload | `https://HOST:8000/ui/upload.html` |
| Filing cabinet | `https://HOST:8000/ui/browse.html` |
| Ask | `https://HOST:8000/ui/ask.html` |
| Wireless camera (desktop) | `https://HOST:8000/ui/camera-desk.html` |
| API docs | `https://HOST:8000/docs` |

Rules:

- **It must be `https`** — plain `http://` will not connect at all.
- **Open the home page via the `.local` hostname**, not `localhost`. For the other pages
  `localhost` makes no difference, but if you navigate from the home page to the camera page,
  the QR code will point at a Docker-internal subnet (`172.x`) that your phone cannot reach.
- You never need to type a URL on the phone — just scan the QR code.

**Why `.local` instead of an IP:** `.local` is this Mac's Bonjour name and follows whatever IP
it currently has. Switching Wi-Fi or getting a new DHCP lease changes nothing, so **the URL
stays the same and the certificate does not need re-signing**. (The certificate covers the IP
as well, so the IP route still works as a fallback.)

---

## 3. Starting and stopping

```bash
cd /Users/linjunting/personalDocAI

# Start (always-on mode; brings up db, redis, app and worker together)
docker compose -f compose.yaml up -d

# Stop
docker compose stop

# Status (all four should be there; db and redis must be healthy)
docker compose ps

# Logs (app is the website and API, worker is the one analysing photos)
docker compose logs -f app worker   # Ctrl+C only exits the log; containers keep running
docker compose logs -f worker       # use this when you only care about analysis progress
```

**Restarting a single service** (the worker is misbehaving, or you edited `.env`):

```bash
docker compose -f compose.yaml restart worker        # background analysis only
docker compose -f compose.yaml restart app worker    # after editing .env, both need it
```

**Wait until the worker is idle before restarting it.** That means the progress panel in the
bottom-right corner has collapsed, or `curl -sk https://127.0.0.1:8000/ingest-jobs` shows no
`analyzing` or `retrying` in `jobs` (leftover `failed` rows are fine — they do not occupy the
worker). The reason: a restart grants only a 10-second grace period, while a single local
vision call takes 60–90 seconds. A job killed midway **is not redelivered** — the message has
already been acknowledged by Celery — so it stays stuck in "analyzing" forever (see
[section 10](#10-troubleshooting) for the rescue). If a job really is running and you really
must restart:

```bash
docker compose stop -t 300 worker      # give it up to 5 minutes to finish the current photo
docker compose -f compose.yaml up -d   # bring it back
```

**In always-on mode `restart` will not pick up code changes.** The code is baked into the
image, so after editing `app/` you must rebuild:
`docker compose -f compose.yaml up -d --build` (app and worker share one image, so both are
replaced at once). To iterate quickly, switch to dev mode ([section 4](#4-dev-mode-hot-reload)).

**After `docker compose stop`, a reboot will not bring the services back** — you have to run
`up -d` yourself.

**After editing `requirements.txt` you must pass `--build`**, otherwise the new packages never
enter the image: `docker compose -f compose.yaml up -d --build`

---

## 4. Dev mode (hot reload)

Saving a file under `app/` takes effect in **app** automatically; in **worker** it does not
(see the first row of the table below).

```bash
# Always-on -> dev
docker compose -f compose.yaml stop app worker
docker compose -f compose.yaml -f compose.dev.yaml up -d
docker compose -f compose.yaml -f compose.dev.yaml logs -f app worker

# Dev -> always-on
docker compose -f compose.yaml -f compose.dev.yaml stop
docker compose -f compose.yaml up -d

# Which mode am I in? (does app's COMMAND contain --reload?)
docker compose ps --no-trunc
```

`--no-trunc` is not optional: without it the COMMAND column is truncated and the trailing
`--reload` is invisible (same for the worker's `--concurrency=2`).

**`--reload` rescues app, never worker.** Celery does not watch files. After editing Python
under `app/`, the analysis path is still running the old code **and nothing reports an
error** — you see "HTTP behaviour is already new, photo analysis results are still old".
You must run:

```bash
docker compose -f compose.yaml -f compose.dev.yaml restart worker
```

**Five things that look like "saving had no effect":**

| What you changed | What to do |
|---|---|
| A `.py` under `app/`, but **analysis behaviour** did not change | `docker compose -f compose.yaml -f compose.dev.yaml restart worker` |
| `.env` | `docker compose -f compose.yaml -f compose.dev.yaml restart app worker` |
| `requirements.txt` | `docker compose build app`, then `up -d` (worker shares the image and updates too) |
| `certs/` | Same as `.env`: `restart app` (the worker does not use certificates) |
| You are pairing the camera right now | A reload clears the token; regenerate the QR and rescan |

Always do real-device camera testing in **always-on mode** — in dev mode every file save
invalidates the pairing.

---

## 5. When the network changes

**If you use the `.local` URL: do nothing.** The name follows the new IP automatically.

Only two situations need action:

**1. You renamed the computer** (System Settings → General → About → Name)

```bash
cd /Users/linjunting/personalDocAI
scutil --get LocalHostName          # the new name; update your bookmark to match
mkcert -cert-file certs/cert.pem -key-file certs/key.pem \
  $(scutil --get LocalHostName).local $(ipconfig getifaddr en0) localhost 127.0.0.1
docker compose restart app
```

**2. The network blocks mDNS, so `.local` does not resolve** (common on corporate and public
Wi-Fi)

Fall back to the IP — this is the case where the certificate must be re-signed:

```bash
ipconfig getifaddr en0              # the IP; use it in the URL
mkcert -cert-file certs/cert.pem -key-file certs/key.pem \
  $(scutil --get LocalHostName).local $(ipconfig getifaddr en0) localhost 127.0.0.1
docker compose restart app
```

Check which addresses the current certificate covers:

```bash
openssl x509 -in certs/cert.pem -noout -text | grep -A2 "Subject Alternative Name"
```

**Do not run `restart` in the middle of camera testing** — the pairing token lives in memory
and is lost on restart, so the QR code has to be regenerated.

---

## 6. Running the tests

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
pytest -q                                        # expect 543 passed
                                                 # (measured 2026-08-27; trust the current run)
OLLAMA_BASE_URL=http://localhost:9 pytest -q     # zero-external-dependency check;
                                                 # the count must be identical
```

Prerequisite: `db` must be `Up (healthy)` in `docker compose ps` — the test database lives
inside the container.

**Do not run two pytest sessions at once** (two terminals, or you running one while an agent
runs another). Every single test TRUNCATEs the same test database, so two runs wipe each
other's data. The symptom is a large number of apparently random 404s and `NoneType` errors.

### Formatting and lint

```bash
ruff format --check app tests scripts && ruff check app tests scripts   # check only
ruff format app tests scripts && ruff check app tests scripts --fix     # fix
```

A commit-time hook runs the same tools on staged `.py` files. It is not installed
automatically — **run this once per clone, and again after recreating `.venv`**:

```bash
pre-commit install
```

---

## 7. Database

`~/.zshrc` already sets `PGPORT=5433`, `PGUSER=postgres` and `PGHOST=127.0.0.1`, so:

```bash
psql -d PersonalDocAI        # the real database
psql -d PersonalDocAI_test   # the test database

# Explicit form (use this in scripts)
psql -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI
```

All three variables are required:

- Without `PGHOST` → `connection to server on socket "/tmp/.s.PGSQL.5433" failed`
- Without `PGUSER` → `role "linjunting" does not exist`

`postgresql@14` (port 5432) belongs to **other projects** (wanderlove, fse_chat_room). Never
stop it or modify it.

---

## 8. Backups

```bash
# Database
pg_dump -h 127.0.0.1 -p 5433 -U postgres -d PersonalDocAI --no-owner --no-acl -Fc \
  -f ~/PersonalDocAI-backup-$(date +%F).dump

# Photo originals
# (the line above does NOT include image files; data/ is not in version control,
#  so exactly one copy exists anywhere)
tar -czf ~/PersonalDocAI-data-$(date +%F).tar.gz data/
```

Restore:

```bash
pg_restore -h 127.0.0.1 -p 5433 -U postgres --no-owner --no-acl \
  --dbname=PersonalDocAI ~/PersonalDocAI-backup-YYYY-MM-DD.dump
```

---

## 9. Monitoring and logs

**One-minute health check — three layers, outside in, in this order:**

```bash
docker compose ps                                    # 1. all four up? db and redis healthy?
curl -s http://127.0.0.1:11434/api/version           # 2. is Ollama alive on the Mac?
                                                     #    no response -> row 1 of section 10
curl -sk https://127.0.0.1:8000/ingest-jobs | python3 -m json.tool
                                                     # 3. queue state: in-flight and failed
                                                     #    jobs, plus the inbox count
```

### Docker layer (are the services alive)

```bash
docker compose ps --no-trunc            # full start command; tells always-on from dev mode
                                        # (--no-trunc is not optional)
docker compose logs -f app worker       # follow both (Ctrl+C only exits the log)
docker compose logs worker --tail 50    # last 50 lines
docker compose logs worker --since 10m  # last 10 minutes (use this to find that failure)
```

### Celery / worker layer (what is happening to the photos)

```bash
docker compose logs -f worker                    # each job end to end: received -> attempt N
                                                 # -> stored / finally failed
docker compose logs worker | grep "kind=vlm"     # per-image duration, local or cloud
                                                 # (backend=local|cloud)
docker compose logs worker | grep "kind=embed"   # embedding (always backend=local)
docker compose logs worker | grep "job "         # job lifecycle events only

# Ask the worker directly (broadcast via Redis; a live worker answers.
# You want to see "1 node online")
docker compose exec worker celery -A app.celery_app.celery_app status
docker compose exec worker celery -A app.celery_app.celery_app inspect active
                                                 # currently running (empty = idle)
docker compose exec worker celery -A app.celery_app.celery_app inspect reserved
                                                 # claimed but not started yet
```

### Redis layer (the queue and progress data themselves)

```bash
docker compose exec redis redis-cli ping                          # must answer PONG
docker compose exec redis redis-cli llen celery                   # queued, not yet claimed
                                                                  # (normally 0)
docker compose exec redis redis-cli smembers ingest:open          # unfinished job_ids
                                                                  # (success deletes the whole
                                                                  #  record, so normally empty)
docker compose exec redis redis-cli get "ingest:<job_id>"         # one job as JSON
                                                                  # (status/attempt/error)
docker compose exec redis redis-cli --scan --pattern "ingest:*"   # every progress-related key
docker compose exec redis redis-cli info persistence | grep aof_enabled
                                                                  # AOF on = aof_enabled:1
```

The two key families do different jobs: `celery` (a list) is **Celery's queue**, while
`ingest:*` is **our own progress record** — the panel in the corner and `GET /ingest-jobs`
read that one. Reading them together: a non-zero `llen celery` means work is queued waiting
for the worker; something in `ingest:open` while `llen` is 0 means the worker is busy with it
(`inspect active` should show it — if it does not, the job is stuck; see section 10).

### S3 / SQS layer (the cloud route)

Only relevant when `CLOUD_ROUTE` is not `off`. With `off` (the default) nothing ever
reaches AWS: the S3 and queue commands below report an empty, idle mailbox. The last
command is the exception — the worker log still shows `route=local` for every photo, and
`fallback=local reason=remote_unavailable` whenever the gate cleared a file for the cloud
and found the route switched off. Both lines are normal on `off`, not a failure.

```bash
set -a; . ./.env; set +a                          # load $S3_BUCKET, $AWS_REGION and the two queue URLs
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY     # so the CLI uses ~/.aws, not the app's key
aws sts get-caller-identity --query Arn --output text
                                                  # expect: .../personaldocai-admin

# Anything in flight right now? (a finished job cleans up after itself, so normally empty)
aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix documents/ \
  --region "$AWS_REGION" --query 'Contents[].Key' --output text

# How many messages are waiting / in flight on each queue
for URL in "$SQS_JOBS_QUEUE_URL" "$SQS_RESULTS_QUEUE_URL"; do
  echo "-- ${URL##*/}"
  aws sqs get-queue-attributes --queue-url "$URL" --region "$AWS_REGION" \
    --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
    --query 'Attributes' --output json
done

# Which route did each photo take? The worker log is the only place this is visible.
docker compose logs worker | grep -E "route=|fallback="
```

How to read it:

- `documents/` empty and both queues at 0 = idle. That is the normal resting state.
- `route=local verdict=SENSITIVE` or `verdict=UNCERTAIN` — the privacy gate kept the file
  on this machine. Nothing was sent to AWS. The gate looks at the **image itself** (it is
  shown to a vision model, one short question), never at the filename, and anything it is
  not confident about stays here. That is the intended default.
- `route=cloud verdict=NON_SENSITIVE` — it went to S3 and onto the jobs queue.
- `fallback=local reason=...` — it tried the cloud route and came back. Four reasons:
  `remote_unavailable` (the instance is not running, or `CLOUD_ROUTE=off`),
  `submit_failed` (S3 or SQS refused),
  `result_timeout` (nobody answered within `CLOUD_RESULT_TIMEOUT_SECONDS`),
  `redelivered_without_result` (the task was retried but no result was on S3).
  In every case the photo still lands in the inbox exactly as it would have without AWS —
  that is the whole point of the design.
- Objects left under `documents/` for more than a few minutes mean a cleanup was missed.
  They are harmless: the bucket lifecycle rule expires everything under that prefix after
  two days.
- Messages piling up on `personaldocai-jobs` mean nobody is consuming them (no worker
  running). Clear them with
  `aws sqs purge-queue --queue-url "$SQS_JOBS_QUEUE_URL" --region "$AWS_REGION"`
  — once per 60 seconds at most, and it takes up to a minute to take effect.

`ApproximateNumberOfMessages` is approximate on purpose: SQS is distributed, so the
number lags a send or a delete by up to a minute. Wait before concluding anything.

### app layer (the ask flow and the camera)

```bash
docker compose logs app --tail 50
docker compose logs app | grep "kind="        # route/answer timings for questions
                                              # (ingest's kind=vlm lives in the worker)
docker compose logs app | grep "role=phone"   # wireless camera: did the phone connect at all
```

---

## 10. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| The site will not load at all | You used `http://` | Use `https://` |
| Certificate warning | Opened via a LAN IP the certificate does not cover | Re-sign the certificate ([section 5](#5-when-the-network-changes)) |
| **The QR code starts with `172.x`** | The desktop page was opened via `localhost` | Close the tab and reopen it on the `.local` URL |
| The `.local` URL will not load | This network blocks mDNS | Fall back to the IP: `ipconfig getifaddr en0`, and re-sign the certificate ([section 5](#5-when-the-network-changes)) |
| The QR renders fine but the phone cannot scan it | The URL is long, so the QR grid is too dense | `.cd-qr svg` in `style.css` needs `max-width` >= `20rem` (a test pins this). The longer the URL, the more cells, the finer each cell |
| The phone scans it but nothing opens | 1. the QR's IP is wrong 2. the iPhone does not trust the root certificate 3. the network blocks it | Check in that order. If the log shows no `role=phone`, the phone never reached the server at all |
| The desktop keeps saying the other side is offline | The phone never connected | Same as above |
| **Every photo fails to analyse**: the panel shows "AI 看不懂這張照片（已試 3 次）" for every single one | Almost certainly **Ollama is not running on the Mac**. If the worker log shows `ConnectError: [Errno 101] Network is unreachable`, that is it — a container hitting a host port with nothing listening reports it this way, so **it looks like broken Docker networking when Ollama is simply not running** (hit on 2026-08-27). Switching to cloud does not help: embeddings always use local bge-m3 | `open -a Ollama`, wait until `curl -s http://127.0.0.1:11434/api/version` responds. **No container needs restarting.** Dismiss the failed rows with `x` and re-upload the photos (failed = nothing was stored) |
| Asking a question returns 500 | Ollama is down. (Uploading does **not** 500 — it still accepts the file and returns 202, then lands in the row above) | Same: `open -a Ollama` |
| Uploads are slow (1–2 minutes) | That is simply how fast the local model is | Normal. Vision 60–90 s, routing 138 s, answering 92 s |
| Uploading and asking at the same time → 500 | The host was overwhelmed | **Do one thing at a time** |
| Lots of random pytest failures | Two pytest sessions running at once | Wait for the other one to finish |
| Upload returns 202 but the photo never appears | The worker is down or crashed | `docker compose ps` to see whether the worker is there; `docker compose logs worker --tail 50` for a traceback |
| Upload returns 500 immediately | redis is down or not healthy yet | Check redis in `docker compose ps`; `docker compose exec redis redis-cli ping` must answer PONG |
| Code changed but analysis behaviour did not | Celery has no `--reload` | `docker compose -f compose.yaml -f compose.dev.yaml restart worker` |
| The worker keeps restarting | The image was not rebuilt (celery package missing) | If `docker compose logs worker` shows `ModuleNotFoundError: No module named 'celery'` → `docker compose up -d --build` |
| A job is stuck in "analyzing" **forever** and `x` will not dismiss it | The worker was restarted or killed mid-job (the warning in [section 3](#3-starting-and-stopping) exists to prevent exactly this). The message was already acknowledged by Celery so it is never redelivered, and dismiss only accepts `failed` | First confirm nobody is working on it with `inspect active` ([section 9](#9-monitoring-and-logs)), then clear the record by hand: `docker compose exec redis redis-cli del "ingest:<job_id>"` and `docker compose exec redis redis-cli srem ingest:open "<job_id>"`, then re-upload the photo. The leftover staging file is removed by the 24-hour sweeper |

The log and queue commands for each layer are collected in
[section 9](#9-monitoring-and-logs).

---

## 11. Never do these

| Command | Consequence |
|---|---|
| `docker compose down -v` | **Destroys the real database** (`-v` deletes the volumes too) |
| `docker volume rm personaldocai_pgdata` | **Destroys the real database** |
| `docker system prune --volumes` | **Destroys the real database** (dangerous after any `down`) |
| Docker Desktop → Reset to factory defaults | **Destroys the real database** |
| Changing `pg17` to `pg18` in `compose.yaml` | PGDATA moves, so a new empty cluster is created and it looks like all the data vanished |
| Running `db/schema.sql` against the real database | It starts with `DROP TABLE` |
| `brew uninstall postgresql@17` | That is the first layer of undo (the data directory `/opt/homebrew/var/postgresql@17` is still there) |
| Stopping or modifying `postgresql@14` | Another project is using it |
| `docker volume rm personaldocai_redisdata` | Loses the progress and failure rows (**not** the real database; see below) |

Always stop services with `docker compose stop`.

**`pgdata` and `redisdata` are very different — do not confuse them:**

| Volume | Contents | If you lose it |
|---|---|---|
| `personaldocai_pgdata` | **The real database**: photo rows, folders, entities, tasks, vectors | A disaster. Every photo is gone and only a backup can restore it |
| `personaldocai_redisdata` | Progress rows, failure rows, unfinished jobs | You only lose the photos that had not finished analysing. Not a single stored photo is affected (the masters live in pgdata and `data/photos`). Re-upload those few; their leftover files in `data/staging` are removed by the 24-hour sweeper |

So `down -v` remains absolutely forbidden — it deletes **both**. But if you ever genuinely
need to clear only Redis, `docker volume rm personaldocai_redisdata` is an acceptable loss —
**provided no job is running at the time**.

---

## 12. Cloud worker on the Mac

The **cloud worker** is the process that looks at photos on the *other* side of the mailbox.
It is not the Celery worker container — that one stays on this Mac and writes to the database.
The cloud worker only looks at images and writes one `result.json` back into S3.

From increment six it can run in two places: on this Mac (this section) or on an EC2
instance (added later). Both run exactly the same code.

**You only need this when you want to exercise the cloud pipeline by hand.**
Day to day it should not be running, and `CLOUD_ROUTE` in `.env` should be `off`.

### What has to be in place

- `.env` has values for `S3_BUCKET`, `SQS_JOBS_QUEUE_URL`, `SQS_RESULTS_QUEUE_URL`,
  `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `OLLAMA_API_KEY` and
  `OLLAMA_CLOUD_VLM_MODEL` — and **no** `AWS_ENDPOINT_URL` (that one is only for pytest,
  where it points at a dead port so nothing can reach the internet).
- The bucket and both queues exist:

```bash
python scripts/aws_check.py s3 sqs      # both lines must print OK
```

### Run it (terminal A)

```bash
cd /Users/linjunting/personalDocAI && source .venv/bin/activate
python -m app.workers.cloud_worker
```

Do **not** source `.env` or `unset` anything in this terminal: the worker reads `.env` by
itself and needs the `personaldocai-mac` key that lives there. Sourcing `.env` and then
`unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY` is only for the shell where you type `aws`
commands — that shell should be on the `personaldocai-admin` profile from `~/.aws`.

The first line tells you which build, which region and which bucket it is talking to:

```text
INFO:     cloud_worker 啟動 version=dev region=ap-northeast-1 bucket=... vlm=cloud model=gemma4
```

`version=dev` is correct here — the real git sha is only baked in when the image is built.
`vlm=` and `model=` say which vision backend it picked; see the next subsection.

Use `python -m` (a module path), **not** `python app/workers/cloud_worker.py`: the second
form puts `app/workers/` on the import path and `from app.core import config` fails
immediately. It also has to be started **from the project root** — `app` is not installed
into the venv, so `python -m` only finds it because the current directory is on `sys.path`.
(`.env` is not the reason: `load_dotenv()` in `app/core/config.py` walks up from that file's
own directory, so the keys are found from anywhere.) If the worker starts but then repeats a
`NoCredentialsError` / `InvalidClientTokenId` traceback every 5 seconds, the AWS key in
`.env` is missing or wrong — the worker deliberately keeps retrying instead of dying; press
Ctrl+C, fix `.env`, start it again.

### Which vision backend the worker uses

`WORKER_VLM_BACKEND` decides which model the cloud worker itself talks to. It defaults to
`cloud`, which is what the hand-run smoke test above uses.

| value | talks to | reads |
|---|---|---|
| `cloud` (default — also what an empty value means) | ollama.com | `OLLAMA_API_KEY`, `OLLAMA_CLOUD_VLM_MODEL` |
| `local` | the Ollama on **the same machine as the worker** | `OLLAMA_BASE_URL`, `VLM_MODEL` (both required) |

`local` means the worker's *own* machine, not "this Mac" in general: on an EC2 instance it
is that instance's own `127.0.0.1:11434`. It does work here on the Mac, but the local gemma4
takes 64–88 s per photo, so this value really exists for a GPU instance (added 2026-09-03;
it replaces the earlier rule that the worker always used Ollama Cloud).
No EC2 worker is running yet. When one is set up it will be a **CPU box first** (`t3.xlarge`),
which keeps `cloud` here — the box just forwards the image to ollama.com — because that box
is only there to prove the AWS path end to end. A **GPU box** (`g4dn.xlarge`, `local`) comes
later and only if AWS grants the GPU quota; the machine type does not decide the backend,
this variable does. With `local` the worker
does not need `OLLAMA_API_KEY` at all, but it does need `VLM_MODEL` (an empty model name talks
to Ollama happily and fails on every single photo). Leaving the value empty, or leaving the line
out entirely, both mean `cloud`; a *typo* is fatal on purpose — the worker refuses to start
rather than quietly falling back to one of them.

This is **not** the header switch in the web UI. That one decides which model the *local* path
and the privacy gate use; it never reaches the cloud worker.

### Point the local side at it (terminal B)

```bash
# 1. In .env:   CLOUD_ROUTE=assume      ("assume the remote worker is up; do not probe")
#               CLOUD_RESULT_TIMEOUT_SECONDS=30    (optional, keeps mistakes short)
# 2. Only the worker container reads this setting. Pass the same -f files you started with;
#    in dev mode (the usual state on this machine) that is both of them:
docker compose -f compose.yaml -f compose.dev.yaml restart worker
docker compose -f compose.yaml -f compose.dev.yaml logs -f worker
```

Now upload a photo whose **content** is clearly not sensitive. The gate never looks at the
file name: it shrinks the image and asks the same vision model one short question about what
is in it. A picture of a shop receipt is the easy case; a picture of an ID card is not.

```bash
curl -k -s -w '\n%{http_code}\n' -F "file=@/tmp/smoke-receipt.png" \
  https://127.0.0.1:8000/photos          # 202
```

The gate runs on whichever backend the header switch is set to (`GET /settings/ai-backend`).
On `local` that one question costs 1–2 minutes per photo; on `cloud` it is under a second.
For a hand-run smoke test, flip it to cloud first:

```bash
curl -sk -X PUT https://127.0.0.1:8000/settings/ai-backend \
  -H 'Content-Type: application/json' -d '{"backend":"cloud"}'
```

That switch is a **separate door** from the privacy gate — it only decides which model the
gate (and the local path) talks to. The cloud worker is not affected by it at all: what it
talks to is `WORKER_VLM_BACKEND` (see above).

What you should see:

| Where | What |
|---|---|
| terminal A (cloud worker) | `kind=vlm backend=cloud`, about 1–3 s, then `result.json 已放好` |
| terminal B (worker container) | `route=cloud verdict=NON_SENSITIVE`, then `kind=embed backend=local`, then `雲端結果已入庫：photo_id=<n>` (the cloud path's own completion line; `grep 雲端結果已入庫`) — and the job disappears from `GET /ingest-jobs` |
| S3 | empty again once it is done (the local side deletes all three objects) |
| both queues | `ApproximateNumberOfMessages` back to `0` |
| the app | the photo is on the pending wall, exactly as with any other upload |

An image **whose content** is an ID card, a passport page or a payslip never reaches the
cloud worker at all: terminal A stays silent, terminal B logs `route=local verdict=SENSITIVE`
(or `verdict=UNCERTAIN`, which is treated the same way), and S3 gets nothing. Renaming a file
changes nothing in either direction — that is the whole point of the gate.

### Stop it

Press **Ctrl+C** in terminal A. It prints `收到停止訊號` and then finishes the message it is
holding before exiting, so it never leaves half a job behind. **This can take up to 20
seconds** — that is the SQS long poll finishing, not a hang. Press Ctrl+C again to cut it short.

### When you are done — this part is not optional

```bash
# In .env:   CLOUD_ROUTE=off
#            CLOUD_RESULT_TIMEOUT_SECONDS=300      (back to the default)
docker compose -f compose.yaml -f compose.dev.yaml restart worker
curl -sk -X PUT https://127.0.0.1:8000/settings/ai-backend \
  -H 'Content-Type: application/json' -d '{"backend":"local"}'   # if you flipped it
```

If you leave `CLOUD_ROUTE=assume` behind with no worker running, every non-sensitive upload
will be pushed to S3 and then sit there until `CLOUD_RESULT_TIMEOUT_SECONDS` expires before
falling back to local processing. Nothing is lost — the photo still lands in the inbox — but
every one of them is several minutes slower, and the only clue is a `fallback=local
reason=result_timeout` line in the worker log.

Leftover queue messages from a smoke test:

```bash
set -a; . ./.env; set +a
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY     # so the CLI uses ~/.aws, not the app's key
aws sqs get-queue-attributes --queue-url "$SQS_JOBS_QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages --region "$AWS_REGION"
aws sqs purge-queue --queue-url "$SQS_JOBS_QUEUE_URL" --region "$AWS_REGION"   # once per 60 s
```

---

## Appendix: current architecture

```
   Mac (host)
   |-- postgresql@14 (brew) :5432   <- another project. NEVER TOUCH
   |-- postgresql@17 (brew)  --     <- stopped; data directory kept as an undo (do not delete)
   |-- Ollama              :11434   <- stays on the Mac (MLX, GPU access), never in Docker
   |                                   Login item, but does NOT return after a manual
   |                                   Quit (see section 1)
   |-- data/  certs/  .env          <- files live here, bind-mounted into the containers
   |-- .venv/ + pytest              <- tests still run on the host, against 127.0.0.1:5433
   |
   +-- Docker Desktop (starts at boot)
        +------ Compose project "personaldocai" ------------------------------+
        |       (internal network: the service name IS the hostname)          |
        |                                                                     |
        |   [app]  uvicorn --ssl-*  (no --reload)                             |
        |     :8000 in the container --published--> 0.0.0.0:8000 on the Mac   |
        |                                           (reachable from the phone)|
        |     mounts: ./data ./certs ./.env                                   |
        |        |                     |                        |             |
        |        | TCP db:5432         | TCP redis:6379         | disk        |
        |        v                     v                        v             |
        |   [db] pgvector:pg17      [redis] redis:7-alpine   data/staging     |
        |     :5432 in container      :6379 in container         |            |
        |     --published-->          --published-->             |            |
        |       127.0.0.1:5433          127.0.0.1:6379           |            |
        |     volume: pgdata          volume: redisdata (AOF)    |            |
        |       ** REAL DB **           ** progress only **      |            |
        |        ^                     ^                         |            |
        |        | TCP db:5432         | TCP redis:6379          | disk       |
        |        |                     |                         v            |
        |   [worker] celery -A app.celery_app.celery_app worker                |
        |            --loglevel=info --concurrency=2                           |
        |     no ports (it listens on nothing; it pulls work from Redis)       |
        |     mounts: ./data ./.env   (** no certs: it does not serve HTTPS **)|
        |        |                                                             |
        +--------|-------------------------------------------------------------+
                 | TCP host.docker.internal:11434
                 v
              Ollama (on the Mac) -- local gemma4 vision 64-88 s
                                     bge-m3 embeddings
                 or
              https://ollama.com  -- cloud gemma4 vision, about 2 s
                                     (when the snapshot says cloud)

   Six TCP / HTTPS links
     browser or iPhone --HTTPS :8000--> app
     app    --db:5432--------> db     (queries, filing, creating folders, pinning
                                       entities and creating tasks are still written
                                       by app; only the photo INSERT moved to worker)
     app    --redis:6379-----> redis  (enqueue, read progress, dismiss)
     worker --redis:6379-----> redis  (take jobs, update status)
     worker --db:5432--------> db     (this is the photo INSERT)
     worker --host.docker.internal:11434--> Ollama (or straight out to ollama.com)

   Plus two links that are not TCP:
     app writes data/staging and worker reads it -- that goes over DISK
        (design5 section 4.1: image bytes NEVER enter Redis or a Celery argument)
     phone ==WebRTC direct== desktop browser -- the camera preview never touches
        the server (increment five left this alone)

   Dev mode (layering compose.dev.yaml) differs in exactly three ways:
     app's command gains --reload, app and worker both bind-mount ./app,
     and both have restart: "no".
     * The worker's command is IDENTICAL in both modes -- Celery has no --reload,
       so after editing Python you must `docker compose ... restart worker`.
```

Related documents: [`README.md`](README.md) (what this project is), `CLAUDE.md` (full project
context and development rules), `docs/design/` (design decisions), `docs/plan/`
(implementation record).
