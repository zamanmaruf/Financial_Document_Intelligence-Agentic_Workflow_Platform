#!/usr/bin/env bash
# Build the image, push it to the stack's ECR repository and deploy deploy/aws/demo-stack.yaml.
#
#   ALERT_EMAIL=you@example.com deploy/aws/deploy.sh
#
# Uses the standard AWS CLI credential chain (AWS_PROFILE etc.); run it with an admin profile
# for the first deploy. Optional: STACK (default docintel-demo), AWS_REGION (default us-east-1),
# MONTHLY_BUDGET_USD (30), DAILY_LIVE_BUDGET_USD (2.0), CFN_ROLE_ARN (CloudFormation service
# role from deploy/aws/github-oidc.yaml; GitHub Actions sets it). See deploy/aws/RUNBOOK.md.
set -euo pipefail

STACK="${STACK:-docintel-demo}"
export AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
ALERT_EMAIL="${ALERT_EMAIL:?set ALERT_EMAIL to receive budget alerts}"
MONTHLY_BUDGET_USD="${MONTHLY_BUDGET_USD:-30}"
DAILY_LIVE_BUDGET_USD="${DAILY_LIVE_BUDGET_USD:-2.0}"
CFN_ROLE_ARN="${CFN_ROLE_ARN:-}"
SESSION_SECRET_PARAM="/docintel/demo/session-secret"
ORIGIN_SECRET_PARAM="/docintel/demo/origin-verify"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEMPLATE="$ROOT/deploy/aws/demo-stack.yaml"

log() { printf '\033[1m==> %s\033[0m\n' "$*"; }

for tool in aws docker git openssl; do
  command -v "$tool" >/dev/null || { echo "missing required tool: $tool" >&2; exit 1; }
done

log "Account $(aws sts get-caller-identity --query Account --output text), region $AWS_REGION, stack $STACK"

# Secrets are generated here and stored in SSM; their values are never printed or passed as
# command-line arguments to CloudFormation.
ensure_parameter() {
  local name="$1" type="$2"
  if ! aws ssm get-parameter --name "$name" >/dev/null 2>&1; then
    log "Creating SSM parameter $name ($type)"
    aws ssm put-parameter --name "$name" --type "$type" \
      --value "$(openssl rand -hex 32)" >/dev/null
  fi
}
ensure_parameter "$SESSION_SECRET_PARAM" SecureString
ensure_parameter "$ORIGIN_SECRET_PARAM" String

PREFIX_LIST="$(aws ec2 describe-managed-prefix-lists \
  --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing \
  --query 'PrefixLists[0].PrefixListId' --output text)"
[[ "$PREFIX_LIST" == pl-* ]] || { echo "CloudFront prefix list not found in $AWS_REGION" >&2; exit 1; }

# Once a stack has a service role, CloudFormation keeps using it even when none is passed.
role_args=()
[[ -n "$CFN_ROLE_ARN" ]] && role_args=(--role-arn "$CFN_ROLE_ARN")

deploy_stack() {
  local count="$1" tag="$2"
  aws cloudformation deploy \
    --stack-name "$STACK" \
    --template-file "$TEMPLATE" \
    --capabilities CAPABILITY_IAM \
    --no-fail-on-empty-changeset \
    ${role_args[@]+"${role_args[@]}"} \
    --parameter-overrides \
      "ImageTag=$tag" \
      "DesiredCount=$count" \
      "AlertEmail=$ALERT_EMAIL" \
      "MonthlyBudgetUsd=$MONTHLY_BUDGET_USD" \
      "DailyLiveBudgetUsd=$DAILY_LIVE_BUDGET_USD" \
      "DemoSecretParameterName=$SESSION_SECRET_PARAM" \
      "OriginVerifySecret=$ORIGIN_SECRET_PARAM" \
      "CloudFrontPrefixListId=$PREFIX_LIST"
}

output() {
  aws cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

if ! aws cloudformation describe-stacks --stack-name "$STACK" >/dev/null 2>&1; then
  log "First deploy: creating the stack with no running task (the image repository is empty)"
  deploy_stack 0 bootstrap
fi

REPO_URI="$(output RepositoryUri)"
TAG="$(git -C "$ROOT" rev-parse --short=12 HEAD)"
if [[ -n "$(git -C "$ROOT" status --porcelain)" ]]; then
  TAG="$TAG-dirty-$(date -u +%Y%m%d%H%M%S)"
fi

if aws ecr describe-images --repository-name "${REPO_URI##*/}" --image-ids "imageTag=$TAG" >/dev/null 2>&1; then
  log "Image $TAG already in ECR; skipping build"
else
  log "Building linux/arm64 image $TAG"
  aws ecr get-login-password | docker login --username AWS --password-stdin "${REPO_URI%%/*}" >/dev/null
  docker build --platform linux/arm64 -t "$REPO_URI:$TAG" "$ROOT"
  docker push "$REPO_URI:$TAG"
fi

log "Deploying image $TAG (CloudFormation waits until the task is healthy)"
deploy_stack 1 "$TAG"

log "Done. Public demo: $(output SiteUrl)"
echo "A new CloudFront distribution can take a few minutes to start serving."
