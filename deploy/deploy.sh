#!/usr/bin/env bash
#
# Deploy AETHER to AWS.
#
# ARCHITECTURE
#
#   CloudFront ──┬── default ──▶ S3 (private, OAC)      static frontend
#                └── /api/*  ──▶ Lambda Function URL     FastAPI via Mangum
#                                       │
#                                       └──▶ DynamoDB (table: catherine)
#
# Two deliberate choices, both about cost and exposure:
#
#   * **No API Gateway.** A Lambda Function URL behind CloudFront does the same
#     job here. API Gateway would add a per-request charge and a second thing to
#     configure for no capability this application uses.
#
#   * **One distribution, two origins.** Serving the API under /api/* on the same
#     CloudFront domain as the frontend means the browser makes same-origin
#     requests, so there is no CORS to configure and no preflight round trip. It
#     also lets the Function URL be locked to CloudFront rather than published to
#     the internet.
#
# WHAT THIS SCRIPT WILL NOT DO
#
#   It never deletes. Every resource is created if absent and updated if present,
#   so re-running is safe and an existing deployment is adopted rather than
#   replaced.
#
# USAGE
#
#   aws login                      # the session expires; this is a manual step
#   bash deploy/deploy.sh discover # report what already exists, change nothing
#   bash deploy/deploy.sh backend  # role + function + function URL
#   bash deploy/deploy.sh frontend # bucket + distribution + upload
#   bash deploy/deploy.sh all

set -euo pipefail

REGION="${AWS_REGION:-ap-south-1}"
STACK="aether"
FUNCTION="${STACK}-api"
ROLE="${STACK}-lambda-role"
TABLE="catherine"
RUNTIME="python3.13"
BUILD="/d/aether-build"
ZIP="${BUILD}/aether-lambda.zip"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() { printf '\n\033[36m▸ %s\033[0m\n' "$*"; }
ok()  { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn(){ printf '  \033[33m!\033[0m %s\n' "$*"; }

account() { aws sts get-caller-identity --query Account --output text; }

# ---------------------------------------------------------------- discover

discover() {
  say "Identity"
  aws sts get-caller-identity --output table

  say "Existing Lambda functions"
  aws lambda list-functions --region "$REGION" \
    --query 'Functions[].{Name:FunctionName,Runtime:Runtime,Size:CodeSize,Modified:LastModified}' \
    --output table 2>/dev/null || warn "none or no permission"

  say "Existing S3 buckets"
  aws s3api list-buckets --query 'Buckets[].Name' --output table 2>/dev/null || warn "none"

  say "Existing CloudFront distributions  (you mentioned one from last time)"
  aws cloudfront list-distributions \
    --query 'DistributionList.Items[].{Id:Id,Domain:DomainName,Comment:Comment,Status:Status,Enabled:Enabled}' \
    --output table 2>/dev/null || warn "none"

  say "DynamoDB tables"
  aws dynamodb list-tables --region "$REGION" --output table 2>/dev/null || warn "none"

  say "IAM roles matching ${STACK}"
  aws iam list-roles --query "Roles[?starts_with(RoleName,'${STACK}')].RoleName" \
    --output table 2>/dev/null || warn "none"
}

# ----------------------------------------------------------------- backend

ensure_role() {
  if aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
    ok "role $ROLE exists"
  else
    say "Creating execution role"
    aws iam create-role --role-name "$ROLE" \
      --assume-role-policy-document '{
        "Version":"2012-10-17",
        "Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]
      }' >/dev/null
    aws iam attach-role-policy --role-name "$ROLE" \
      --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
    ok "role created"
    sleep 10   # IAM is eventually consistent; Lambda rejects a role it cannot see yet
  fi

  # Least privilege: three actions, one table. No Scan, no Query — the store is
  # keyed by exact partition key, which is what keeps this policy this small.
  say "Attaching DynamoDB policy (3 actions, 1 table)"
  aws iam put-role-policy --role-name "$ROLE" --policy-name "${STACK}-dynamodb" \
    --policy-document "{
      \"Version\":\"2012-10-17\",
      \"Statement\":[{
        \"Effect\":\"Allow\",
        \"Action\":[\"dynamodb:GetItem\",\"dynamodb:PutItem\",\"dynamodb:DeleteItem\"],
        \"Resource\":\"arn:aws:dynamodb:${REGION}:$(account):table/${TABLE}\"
      }]
    }"
  ok "policy attached"
}

deploy_backend() {
  [[ -f "$ZIP" ]] || { echo "Missing $ZIP — run deploy/build_lambda.sh first." >&2; exit 1; }
  ensure_role
  local role_arn
  role_arn="arn:aws:iam::$(account):role/${ROLE}"

  # AETHER_USE_TRUSTSTORE is off: it exists only for the TLS interception on the
  # development machine, and on Lambda it is a pointless import.
  local env="Variables={AETHER_MODE=replay,AETHER_USE_TRUSTSTORE=false,AETHER_ENGINE_VERSION=0.1.0,AETHER_DYNAMO_TABLE=${TABLE},AETHER_CORS_ORIGINS=*}"

  if aws lambda get-function --function-name "$FUNCTION" --region "$REGION" >/dev/null 2>&1; then
    say "Updating existing function"
    aws lambda update-function-code --function-name "$FUNCTION" --region "$REGION" \
      --zip-file "fileb://${ZIP}" --output text --query LastModified
    aws lambda wait function-updated --function-name "$FUNCTION" --region "$REGION"
    aws lambda update-function-configuration --function-name "$FUNCTION" --region "$REGION" \
      --timeout 30 --memory-size 1024 --environment "$env" --output text --query LastModified
  else
    say "Creating function"
    aws lambda create-function --function-name "$FUNCTION" --region "$REGION" \
      --runtime "$RUNTIME" --role "$role_arn" --handler lambda_handler.handler \
      --zip-file "fileb://${ZIP}" --timeout 30 --memory-size 1024 \
      --environment "$env" --output text --query FunctionArn
  fi
  aws lambda wait function-updated --function-name "$FUNCTION" --region "$REGION"

  # AWS_IAM, not NONE. The distribution signs requests with OAC; a Function URL
  # left open is a public, unauthenticated API, and this application has no
  # authentication of its own to fall back on.
  if ! aws lambda get-function-url-config --function-name "$FUNCTION" --region "$REGION" >/dev/null 2>&1; then
    aws lambda create-function-url-config --function-name "$FUNCTION" --region "$REGION" \
      --auth-type AWS_IAM >/dev/null
  fi
  local url
  url=$(aws lambda get-function-url-config --function-name "$FUNCTION" --region "$REGION" \
    --query FunctionUrl --output text)
  ok "function URL: $url"
  echo "$url" > "${BUILD}/function-url.txt"
}

# ---------------------------------------------------------------- frontend

deploy_frontend() {
  local bucket="${STACK}-web-$(account)"

  if aws s3api head-bucket --bucket "$bucket" 2>/dev/null; then
    ok "bucket $bucket exists"
  else
    say "Creating private bucket"
    aws s3api create-bucket --bucket "$bucket" --region "$REGION" \
      --create-bucket-configuration "LocationConstraint=${REGION}" >/dev/null
    aws s3api put-public-access-block --bucket "$bucket" \
      --public-access-block-configuration \
      "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
    ok "bucket created, public access blocked"
  fi

  # The frontend calls ${API_BASE}/api/v1/... — an empty base makes that a
  # same-origin path, which CloudFront routes to the Lambda origin.
  say "Rebuilding frontend for same-origin API"
  ( cd "${ROOT}/frontend" && NEXT_PUBLIC_API_BASE="" npx next build >/dev/null )
  ok "built $(find "${ROOT}/frontend/out" -type f | wc -l) files"

  say "Uploading"
  aws s3 sync "${ROOT}/frontend/out" "s3://${bucket}" --delete \
    --cache-control "public,max-age=300" >/dev/null
  ok "uploaded to s3://${bucket}"

  warn "CloudFront distribution is created interactively — see deploy/README.md."
  warn "Two origins are needed (S3 default, Lambda under /api/*) plus OAC on both."
}

case "${1:-discover}" in
  discover) discover ;;
  backend)  deploy_backend ;;
  frontend) deploy_frontend ;;
  all)      deploy_backend && deploy_frontend ;;
  *) echo "usage: $0 {discover|backend|frontend|all}" >&2; exit 1 ;;
esac
