#!/usr/bin/env bash
# Read-only checks on the deployed demo stack, from the AWS side.
#
#   AWS_PROFILE=... deploy/aws/smoke.sh
#
# Checks: the ECS service is running its desired task, the load balancer target is healthy,
# the load balancer refuses requests that don't come through CloudFront, model calls in the last
# hour were real (not the offline engine) and succeeded, and no errors were logged in that hour.
# Optional: STACK (default docintel-demo), AWS_REGION (default us-east-1), WINDOW_MINUTES (60).
set -euo pipefail

STACK="${STACK:-docintel-demo}"
export AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
WINDOW_MINUTES="${WINDOW_MINUTES:-60}"

failures=0
pass() { printf '  \033[32mPASS\033[0m %s\n' "$*"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; failures=$((failures + 1)); }
warn() { printf '  \033[33mWARN\033[0m %s\n' "$*"; }

output() {
  aws cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}
resource() {
  aws cloudformation describe-stack-resource --stack-name "$STACK" --logical-resource-id "$1" \
    --query StackResourceDetail.PhysicalResourceId --output text
}

echo "AWS checks for stack $STACK in $AWS_REGION"

read -r running desired < <(aws ecs describe-services --cluster "$(output ClusterName)" \
  --services "$(output ServiceName)" --query "services[0].[runningCount,desiredCount]" --output text)
if [[ "$desired" -ge 1 && "$running" == "$desired" ]]; then
  pass "ECS service running $running of $desired task(s)"
else
  fail "ECS service running $running of $desired task(s)"
fi

health=$(aws elbv2 describe-target-health --target-group-arn "$(resource TargetGroup)" \
  --query "TargetHealthDescriptions[].TargetHealth.State" --output text)
if [[ -n "$health" && "$health" =~ ^(healthy[[:space:]]*)+$ ]]; then
  pass "load balancer target(s): $health"
else
  fail "load balancer target(s): ${health:-none registered}"
fi

alb_dns=$(aws elbv2 describe-load-balancers --load-balancer-arns "$(resource LoadBalancer)" \
  --query "LoadBalancers[0].DNSName" --output text)
direct=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "http://$alb_dns/health" || true)
if [[ "$direct" == "200" ]]; then
  fail "load balancer answered a direct request (HTTP 200); it should only accept CloudFront"
else
  pass "load balancer refuses direct requests (HTTP ${direct:-000})"
fi

log_group=$(output LogGroupName)
start_ms=$(( ($(date +%s) - WINDOW_MINUTES * 60) * 1000 ))

calls=$(aws logs filter-log-events --log-group-name "$log_group" --start-time "$start_ms" \
  --filter-pattern '{ $.event = "model_invocation" }' --query "events[].message" --output json)
read -r total mock failed < <(python3 -c '
import json, sys
events = [json.loads(m) for m in json.load(sys.stdin)]
print(len(events), sum(bool(e.get("is_mock")) for e in events), sum(not e.get("success") for e in events))
' <<<"$calls")
if [[ "$total" -eq 0 ]]; then
  warn "no model calls in the last $WINDOW_MINUTES minutes (run the live tour first)"
elif [[ "$mock" -gt 0 ]]; then
  fail "$mock of $total model calls used the offline engine (daily budget reached or misconfigured)"
elif [[ "$failed" -gt 0 ]]; then
  fail "$failed of $total model calls failed"
else
  pass "$total model calls in the last $WINDOW_MINUTES minutes, all live and successful"
fi

count_events() {
  aws logs filter-log-events --log-group-name "$log_group" --start-time "$start_ms" \
    --filter-pattern "$1" --query "events[].eventId" --output text | wc -w | tr -d ' '
}
errors=$(( $(count_events '{ $.level = "ERROR" }') + $(count_events '?Traceback ?"ERROR:"') ))
if [[ "$errors" == "0" ]]; then
  pass "no errors logged in the last $WINDOW_MINUTES minutes"
else
  fail "$errors error line(s) logged in the last $WINDOW_MINUTES minutes (see log group $log_group)"
fi

if [[ "$failures" -gt 0 ]]; then
  echo "$failures check(s) failed"
  exit 1
fi
echo "All AWS checks passed"
