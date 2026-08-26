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

### Why fixtures need `includeFiles`

`aether.config.REPO_ROOT` is `__file__`'s grandparent, and `fixtures/` resolves
against it. The bundle therefore has to keep the repository shape:
`backend/aether/config.py` two levels under the root, `fixtures/` beside `backend/`.
Fixtures are data and nothing imports them, so Vercel's dependency tracer cannot see
them — `functions["api/index.py"].includeFiles` puts them in. Flattening the tree or
dropping that key breaks fixture loading silently: the import succeeds and the first
data read fails.

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
5. Deploy.

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
