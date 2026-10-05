# Public demo on AWS: runbook

This deploys the guided demo site and API as **one container on ECS Fargate** behind an
Application Load Balancer and CloudFront. The container calls Claude on Amazon Bedrock using an
IAM task role, so no AWS keys are stored anywhere in the deployment.

> Status: the template passes `cfn-lint`, the image is built and tested in CI, and the deploy script
> is written for the AWS CLI. Run the first deploy yourself with an admin profile and check the
> result. Nothing here has been deployed automatically.

## What gets created

| Resource | Purpose |
| --- | --- |
| VPC, two public subnets, internet gateway | Networking without a NAT gateway (the task has a public IP for outbound calls; inbound is locked down by security groups) |
| ECR repository | Container images; scan on push, immutable tags, keeps the last 10 |
| ECS cluster, task definition, service | One ARM64 task, 0.5 vCPU / 1 GB |
| Application Load Balancer | Accepts traffic only from CloudFront's address ranges, and only with CloudFront's secret header |
| CloudFront distribution | HTTPS for visitors, HSTS, caches `/assets/*`, passes everything else through |
| IAM task role | `bedrock:InvokeModel` on the one configured model, nothing else |
| IAM execution role | Pull the image, write logs, read the session secret from SSM |
| CloudWatch log group | `/ecs/<stack>`, 14-day retention |
| AWS Budgets budget | Emails at 80% of the monthly amount (actual) and 100% (forecast) |
| SSM parameters (created by the script) | `/docintel/demo/session-secret` (SecureString) signs visitor cookies; `/docintel/demo/origin-verify` is the CloudFront-to-ALB header value |

## Before the first deploy

1. **Bedrock model access.** In the Bedrock console for your region, make sure Claude Haiku 4.5
   is enabled (Model access). The default model id is the US cross-region inference profile
   `us.anthropic.claude-haiku-4-5-20251001-v1:0`.
2. **Tools.** AWS CLI v2, Docker (with buildx, which Docker Desktop includes), git, openssl.
3. **Credentials.** An admin profile for the first deploy, e.g. `export AWS_PROFILE=admin`. The
   `docintel` IAM user used for local development has only Bedrock permissions and can't create
   this stack.

## Deploy

```bash
ALERT_EMAIL=you@example.com make deploy
# same as: ALERT_EMAIL=you@example.com deploy/aws/deploy.sh
```

The script:

1. creates the two SSM parameters with random values if they don't exist (values are never printed);
2. looks up CloudFront's origin-facing prefix list for the region;
3. on the first run, creates the stack with zero tasks so the ECR repository exists;
4. builds a `linux/arm64` image tagged with the git commit (plus `-dirty-<time>` if the working tree
   has uncommitted changes), pushes it unless that tag already exists, and
5. updates the stack to run one task with that image. CloudFormation waits until the task passes
   its health check, and rolls back automatically if it doesn't.

It prints the public URL at the end (`https://<id>.cloudfront.net`). A new distribution takes a
few minutes to start serving. AWS sends a confirmation email for the budget alerts the first time.

Optional settings: `STACK` (default `docintel-demo`), `AWS_REGION` (default `us-east-1`),
`MONTHLY_BUDGET_USD` (default 30), `DAILY_LIVE_BUDGET_USD` (default 2.0).

## Check it

```bash
URL=$(aws cloudformation describe-stacks --stack-name docintel-demo \
  --query "Stacks[0].Outputs[?OutputKey=='SiteUrl'].OutputValue" --output text)
curl -s "$URL/health"          # {"status":"ok",...}
curl -s "$URL/demo/status"     # "ai_mode": "live" while under the daily budget
```

Then run the smoke tests (needs `make web` once for the Node dependencies and Playwright's
Chromium):

```bash
AWS_PROFILE=<profile> make smoke-live   # LIVE_URL=... to point at another deployment
```

They take about 30 seconds and cost about $0.02 of model usage.

- **Browser and API tests** (`web/e2e-live/`):
  - Every page loads, unknown addresses get proper 404s, and the CSP, HSTS and caching headers
    are set.
  - `/health` reports Bedrock rather than the offline engine.
  - Accessibility scans pass, there are no console or CSP errors, and the phone layout doesn't
    scroll sideways.
  - One visitor can't read another visitor's document, a forged session cookie is rejected, and
    operator endpoints refuse visitors.
  - The full eight-step tour runs on live AI.
- **AWS checks** (`deploy/aws/smoke.sh`, read-only): the task is running and its target is
  healthy, the load balancer refuses direct requests, model calls in the last hour were live and
  succeeded, and no errors were logged.

The live site allows 5 new visitor sessions per IP address per hour, and each run uses 2, so run
it at most about once an hour from the same network. If the limit is hit, the run fails with a
429 and says how long to wait. Going straight to the load balancer's DNS name times out, because
its security group only admits CloudFront.

Logs: `aws logs tail /ecs/docintel-demo --follow`.

## Day-to-day

- **Redeploy after a code change:** commit, then `make deploy` again.
- **Live budget:** the app estimates the cost of each model call and switches to the offline engine
  for the rest of the UTC day once `DAILY_LIVE_BUDGET_USD` is reached. The header badge and every
  result say which engine produced them.
- **Force offline mode:** redeploy with `DAILY_LIVE_BUDGET_USD=0`.
- **Rotate the session secret:** `aws ssm put-parameter --name /docintel/demo/session-secret
  --type SecureString --overwrite --value "$(openssl rand -hex 32)"`, then force a new deployment
  (`aws ecs update-service --cluster <cluster> --service <service> --force-new-deployment`).
  Existing visitor sessions stop working, and their browsers get a new session automatically.
- **Rotate the origin header:** overwrite `/docintel/demo/origin-verify` (type String) and run
  `make deploy`.
- **Stop all spend except storage:** `aws ecs update-service --cluster <cluster> --service <service>
  --desired-count 0`. The ALB still costs money while the stack exists.

## Tear down

```bash
aws ecr delete-repository --repository-name <repository name> --force   # images block stack deletion
aws cloudformation delete-stack --stack-name docintel-demo
aws ssm delete-parameter --name /docintel/demo/session-secret
aws ssm delete-parameter --name /docintel/demo/origin-verify
```

## Rough monthly cost (us-east-1, light traffic)

| Item | Approx. |
| --- | --- |
| Fargate ARM64, 0.5 vCPU / 1 GB, always on | ~$14 |
| Application Load Balancer | ~$16 to $18 |
| Public IPv4 addresses (one for the task, two for the ALB) | ~$11 |
| CloudFront, CloudWatch Logs, ECR | under $1 at demo traffic |
| Bedrock | capped by `DAILY_LIVE_BUDGET_USD` (a soft cap, see below) |

These are estimates from public list prices, not a quote. The ALB is the biggest fixed cost. The AWS Budgets
alert defaults to $30 a month: it **emails you**, it does not stop anything.

## Known limitations (read before sharing the link)

- **State lives on the task's local disk.** SQLite, the vector index, uploads and the audit trail
  are lost whenever the task is replaced (each deploy, or if it crashes). That is acceptable for a
  demo where visitor data is deleted after 24 hours anyway. A production deployment would use
  Postgres (RDS), S3 for files, and a durable, write-once store for the audit log.
- **The daily live budget is a soft cap.** Spend is summed from the app's own cost estimates
  (cached for a few seconds), and the total resets if the task restarts. AWS Budgets is the backstop.
- **One task only.** Rate limits and sessions are held in memory; running two tasks would split them.
- **Rate limits are per task and in memory.** They slow down casual abuse; they are not a WAF.
  Add AWS WAF with a rate-based rule in front of CloudFront if the link is shared widely.
- **CloudFront to ALB is plain HTTP inside AWS.** Visitors always use HTTPS to CloudFront. To
  encrypt the second leg, add a custom domain with an ACM certificate on the ALB and switch the
  origin protocol to `https-only`.
- **Data residency:** the US cross-region inference profile may process requests in any of its
  US regions. Use a single-region model id if that matters.
- **No custom domain** is configured; the site uses the `cloudfront.net` address.
- **The task's root filesystem is writable.** The docker compose setup runs read-only with a
  `/data` volume and a tmpfs `/tmp`; the Fargate task definition doesn't yet (the container still
  runs as a non-root user). Adding ephemeral volumes for `/data` and `/tmp` and setting
  `ReadonlyRootFilesystem: true` is a follow-up that needs a test deploy.
