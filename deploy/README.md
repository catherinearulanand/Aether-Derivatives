# Deploying AETHER

A record of what is deployed, how to rebuild it, and which parts are wired by hand.
Written against the running deployment rather than against intent — where the scripts
and the cloud disagree, the disagreement is named below rather than smoothed over.

> All data served by this deployment is **simulated**. The function runs
> `AETHER_MODE=replay`, makes no outbound network call, and executes no transaction.

---

## What is deployed

```
CloudFront  E2XYCWF9L9C796   d3gzusuqrty02w.cloudfront.net
   │
   ├── default  ─▶  S3  aether-site-<account>            static frontend, private, OAC
   │                    CachePolicy  CachingOptimized
   │
   └── /api/*   ─▶  API Gateway  gwrvbykv32 (HTTP API)   ─▶  Lambda  aether-api
                        CachePolicy         CachingDisabled
                        OriginRequestPolicy AllViewerExceptHostHeader
```

| | |
|---|---|
| Region | `ap-south-1` |
| Function | `aether-api` · python3.13 · 2048 MB · 30 s timeout |
| Handler | `lambda_handler.handler` — Mangum over the unchanged FastAPI app |
| Mode | `AETHER_MODE=replay` |
| Reserved concurrency | 20 |

Serving the API under `/api/*` on the frontend's own domain makes every browser
request same-origin. There is no CORS to configure and no preflight round trip.

---

## Rebuild and deploy

```bash
bash deploy/build_lambda.sh     # produces /d/aether-build/aether-lambda.zip
bash deploy/deploy.sh backend   # role, function, concurrency, function URL
bash deploy/deploy.sh frontend  # bucket, static export, upload
```

`deploy/deploy.sh discover` reports what exists and changes nothing. The script never
deletes: resources are created if absent and updated if present.

### The package

`build_lambda.sh` installs a **runtime** dependency set, not the development set. Five
packages in `pyproject.toml` are deliberately excluded, each verified against the source
first — the reasons are written at the top of that script. The two that matter:

- **`sqlmodel` is declared and imported nowhere.** It pulls in SQLAlchemy, the single
  largest avoidable weight in the archive.
- **`anthropic` is imported lazily** inside `legal_clause.extract_terms` and
  `agents.guide`, and reached only in live mode.

**Consequence, stated plainly: this package cannot serve `AETHER_MODE=live`.** Setting
that variable on the deployed function raises `ModuleNotFoundError` at the first
extraction. Replay is the demo path and the only mode this artifact supports.

Two builds of the same inputs produce a **byte-identical** archive — entries are written
in sorted order with a pinned timestamp, and pip's generated console-script launchers,
which differ on every install, are stripped. `package-manifest.txt` records the commit,
whether the tree was clean, every resolved version, and the archive's SHA-256. That is
what lets a deployed function be tied back to a tested one.

Current size: **229 MB → 153 MB unzipped, 48 MB zipped**, against limits of 250 MB and
50 MB. The headroom on the zipped figure is thin; a dependency bump can breach it, and
`--zip-file fileb://` then fails. Staging through
`s3://aether-deploy-<account>-ap-south-1` is the documented way out, and is not yet
automated.

---

## CloudFront is wired by hand

`deploy.sh` does not create the distribution. Recreating it from nothing means:

1. **Origin 1 — S3.** `aether-site-<account>`, public access fully blocked, reached
   through an Origin Access Control. Add the generated bucket policy to the bucket.
2. **Origin 2 — the API.** The HTTP API Gateway endpoint. Behaviour `/api/*`, all seven
   methods allowed, cache policy `CachingDisabled`, origin request policy
   `AllViewerExceptHostHeader` — the last matters, because forwarding the viewer `Host`
   makes API Gateway reject the request.
3. **Default root object** `index.html`. The frontend static-exports with
   `trailingSlash: true`, so `/review/` resolves and `/review` may not.

---

## Verifying a deployment

```bash
curl -s https://d3gzusuqrty02w.cloudfront.net/api/v1/health
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
     https://d3gzusuqrty02w.cloudfront.net/api/v1/scenarios/stress/run
```

Health alone is not sufficient — it touches no fixture and solves no LP. The scenario run
exercises the whole path and returns roughly 60 KB.

**Test concurrency, not just correctness.** The dashboard opens by firing the run, the
comparison and the workflow simultaneously. A sequential check passes against a
deployment that fails in a browser:

```bash
for i in 1 2 3 4 5 6 7 8; do
  ( curl -s -o /dev/null -w '%{http_code} ' -X POST \
      https://d3gzusuqrty02w.cloudfront.net/api/v1/scenarios/stress/run ) &
done; wait; echo
```

---

## Operations

**Reserved concurrency was the cause of a live outage.** The function sat at a
reservation of 1. Every parallel request beyond the first was throttled, and the browser
showed `Request failed with status 503` on a dashboard whose API was, individually,
perfectly healthy. In one 15-minute window: 31 invocations, 27 throttles.

A throttled invocation is invisible in the function's logs — it never reaches the
application, so there is no log line to find. The only evidence is the `Throttles`
metric:

```bash
aws cloudwatch get-metric-statistics --namespace AWS/Lambda \
  --metric-name Throttles --dimensions Name=FunctionName,Value=aether-api \
  --start-time <iso8601> --end-time <iso8601> --period 900 --statistics Sum \
  --region ap-south-1
```

Reserved concurrency is a ceiling, not a meter. It costs nothing on its own; you pay per
invocation either way. `deploy.sh` now sets it on every backend deploy.

**Logs.** `/aws/lambda/aether-api`. Cold start is around 3 s and peak memory around
170 MB of the 2048 MB provisioned — the memory is bought for CPU share, not for headroom.

---

## Known divergences

`deploy.sh` was written before the deployment settled into its current shape, and the
following still differ. None is load-bearing today; all would take effect on the next
`deploy.sh backend` run.

| Script says | Deployment is | Effect if the script runs |
|---|---|---|
| Lambda Function URL as the `/api/*` origin | API Gateway HTTP API `gwrvbykv32` | None — the Function URL exists and is left in place, unused by the distribution |
| `--memory-size 1024` | 2048 MB | Halves CPU share; roughly doubles cold start |
| `AETHER_CORS_ORIGINS=*` | the distribution's own domain | Widens CORS. Harmless while every request is same-origin, but it is a real loosening |
| `AETHER_DYNAMO_TABLE=catherine` | not set | None |

**DynamoDB is not used at all.** No `boto3` import, no client, no reference anywhere
under `backend/aether/`. The table, the IAM policy granting three actions on it, and the
environment variable are all vestigial. They are described here so the policy is not
mistaken for evidence of a persistence layer — the review workflow's state lives in
process memory, and says so in `api/main.py`.
