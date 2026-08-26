# Deploying AETHER to Vercel

A second deployment target, alongside the AWS one in [README.md](README.md). Both
serve the same application from the same repository; neither is generated from the
other, so where they differ the difference is written down here.

> All data served by this deployment is **simulated**. The function runs
> `AETHER_MODE=replay`, makes no outbound network call, and executes no transaction.

---

## Shape

```
Vercel project (root directory = repository root)
   │
   ├── default  ─▶  static build of frontend/  ─▶  frontend/out
   │
   └── /api/*   ─▶  rewrite ─▶ api/index.py    ─▶  the unchanged FastAPI app
```

This mirrors the AWS shape deliberately. The frontend is built with
`NEXT_PUBLIC_API_BASE=""`, exactly as `deploy.sh` builds it, so the browser asks for
`/api/v1/...` on the frontend's own origin. Every request is same-origin: no CORS to
configure, no preflight round trip, and the CORS middleware's `allowed_origins` never
comes into play.

| | |
|---|---|
| URL | https://aether-derivatives.vercel.app |
| Config | `vercel.json` at the repository root |
| Function | `api/index.py` — ASGI, no adapter |
| Dependencies | `requirements.txt` at the repository root |
| Mode | `AETHER_MODE=replay`, set in `api/index.py` |
| Max duration | 60 s |

### Why there is no Mangum here

Vercel's Python runtime speaks ASGI and looks for a module-level `app`. Lambda does
not, which is why `deploy/lambda_handler.py` wraps the same application in Mangum.
The application itself is untouched by either.

### Why the rewrite preserves the path

`vercel.json` rewrites `/api/(.*)` to `/api/index`. A Vercel rewrite changes which
function serves the request, not the URL the function observes — the app still sees
`/api/v1/health`, which is what its routes are declared as. Nothing re-prefixes or
strips a path anywhere.

### Why `includeFiles` covers both `backend` and `fixtures`

Vercel bundles a function from the entrypoint plus the imports it can trace
statically. Neither half of this application is reachable that way:

- **`backend/**`** is imported only after `api/index.py` mutates `sys.path` at
  runtime. A static tracer cannot follow that, so without this glob the bundle
  ships no `aether` package at all and the function dies at import with
  `ModuleNotFoundError`, surfacing as an opaque `FUNCTION_INVOCATION_FAILED` on
  every route including `/api/v1/health`.
- **`fixtures/**`** is data. Nothing imports it, so nothing can trace it.

The bundle also has to keep the repository shape, because
`aether.config.REPO_ROOT` is `__file__`'s grandparent and `fixtures/` resolves
against it: `backend/aether/config.py` two levels under the root, `fixtures/`
beside `backend/`. Flattening the tree breaks fixture loading silently — the
import succeeds and the first data read fails.

The two failures look nothing alike. A missing `backend` fails every route at
import; a missing `fixtures` leaves `/api/v1/health` returning 200 and breaks the
first route that reads data. `health` is therefore not a sufficient check on its
own — run a scenario.

---

## First deploy

The project is imported through the GitHub integration, so every push to the
production branch redeploys.

1. Vercel → **Add New… → Project** → import `catherinearulanand/Aether-Derivatives`.
2. Leave **Root Directory** as the repository root. `vercel.json` drives the rest —
   do not set the root to `frontend/`, or the API function disappears from the build.
3. Framework preset: **Other**. Build and output settings come from `vercel.json`;
   leave the dashboard overrides switched off.
4. No environment variables are required. `AETHER_MODE` and `AETHER_USE_TRUSTSTORE`
   are set in `api/index.py` with `setdefault`, so a dashboard variable still wins if
   one is ever added.
5. **Clear every environment variable Vercel offers to create.** The import flow
   reads `.env.example` and pre-creates each key it declares, blank. See below —
   this cost several deployments.
6. Deploy.

---

## Verifying a deployment

```bash
curl -s https://<deployment>/api/v1/health
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
     https://<deployment>/api/v1/scenarios/stress/run
```

Health alone is not sufficient — it touches no fixture and solves no LP. The scenario
run exercises the whole path and returns roughly 60 KB.

**Test concurrency, not just correctness.** The dashboard opens by firing the run, the
comparison and the workflow simultaneously.

```bash
for i in 1 2 3 4 5 6 7 8; do
  ( curl -s -o /dev/null -w '%{http_code} ' -X POST \
      https://<deployment>/api/v1/scenarios/stress/run ) &
done; wait; echo
```

---

## Blank environment variables killed this deployment

Recorded because the failure was expensive to find and gives no clue on its own.

Vercel creates project environment variables from `.env.example` during import,
**blank** when they are not filled in. Every `AETHER_*` key therefore arrived
*present and empty*, and `Settings()` rejected `''` for the mode enum and the
truststore boolean. That happens at module import, before any handler exists, so
the platform could only answer `FUNCTION_INVOCATION_FAILED` — no module name, no
traceback, and nothing in the response to distinguish it from a missing package
or a broken bundle.

Two properties made it hard:

- **`os.environ.setdefault` does not help.** It fills an *absent* key. These keys
  were present and empty, so the entrypoint's defaults never applied.
- **The string-typed settings did not fail.** They accepted `''` silently. Had
  only `mode` and `use_truststore` been fixed, `engine_version` would have
  shipped empty — and it is part of the reproducibility block on every response
  carrying a computed number.

`Settings` now sets `env_ignore_empty`, so an empty variable means unset for
every field. `backend/tests/unit/test_config.py` covers the exact shape the
platform created and fails without the fix.

**What to do about the variables themselves:** delete them in Settings →
Environment Variables. The code no longer needs them gone, but leaving blanks
misrepresents the deployment's configuration to anyone reading it.

### Diagnosing this class of failure again

`FUNCTION_INVOCATION_FAILED` means the function died before serving anything.
`api/index.py` therefore guards its import and, on failure, serves a 500 whose
body carries the traceback and a report of what the bundle contains — which is
how this cause was finally identified. Two constraints on that guard:

- **`app` must be a top-level assignment.** Vercel finds the entrypoint by
  statically scanning the file's top level for the name; it does not execute the
  module. An earlier revision put the import inside `try`/`except` with the
  fallback defined in the handler, leaving no top-level `app`, and the build
  failed in two seconds with "No FastAPI entrypoint found" — while production
  stayed silently pinned to the previous deployment, so the same stale error kept
  being served.
- **A `Redeploy` re-runs the pinned source commit**, not the branch head. Fixing
  a build failure requires a new push.

---

## Verified on the live deployment

```
GET  /api/v1/health              200      128 B
GET  /api/v1/methodology         200    2,528 B
GET  /api/v1/scenarios           200      842 B
POST /api/v1/scenarios/base/run  200   31,633 B
POST /api/v1/scenarios/stress/run 200  60,611 B
POST /api/v1/scenarios/crash/run 200   35,997 B
GET  /api/v1/comparison/base/stress 200 8,969 B
8 concurrent stress runs         200 x 8
```

Two live stress runs are byte-identical apart from `timing.elapsed_ms`, which is
a wall-clock measurement — every computed figure and the whole audit chain
reproduce.

---

## Known limits

**The review workflow's state is per-instance.** `_extractions`, `_agreements` and
`_approvals` in `api/main.py` are process memory, and the module says so. Vercel scales
by starting instances, so a confirm-field call and the run that should observe it can
land on different ones — the reviewer's decision is then recorded and ignored. The AWS
deployment has the same design and hides it better, because a single warm function
tends to serve a whole session. Nothing in this deployment makes it worse; it makes it
**more likely to surface**, and it surfaces as a run that quietly uses the committed
fixture instead of the frozen agreement. Fixing it means moving that state out of the
process, which is not done in either deployment.

**Live mode is not served.** `requirements.txt` excludes `anthropic` for the same
reasons `build_lambda.sh` does, and both live paths fall back to replay without
raising. Check `live_available` on `/api/v1/health` rather than inferring live from a
200.

**Bundle size.** numpy and scipy account for most of the 250 MB unzipped function
limit. A dependency bump can breach it, and the failure appears at build time.

**Cold start** is a few seconds — scipy's import dominates.
