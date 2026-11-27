# AWS deployment

One CloudFormation stack (`deploy/aws/cloudformation.yaml`) creates everything the portal needs in your existing VPC. The recommended region is `ap-south-1` (Mumbai).

```
            Route 53 / DNS: hr.kairoz.com
                        │
                 ┌──────▼──────┐  HTTPS (ACM certificate), HTTP → HTTPS redirect
                 │     ALB     │  public subnets
                 └──────┬──────┘
                        │ :8000, health check /health
        ┌───────────────▼───────────────┐
        │  ECS Fargate service (ARM64)  │  private subnets, 2–4 tasks, CPU autoscaling, ECS Exec enabled
        │  hr-management container      │  logs → CloudWatch /ecs/kairoz-hrm
        └───┬───────────┬───────────┬───┘
            │           │           │
   ┌────────▼───┐ ┌─────▼─────┐ ┌───▼────┐   Secrets Manager: app secret key, RDS-managed DB password,
   │ RDS Postgres│ │ S3 bucket │ │  SES   │   optional LLM key — injected as env vars, never in the image
   │ 16, encrypted│ │ private,  │ │ email  │
   │ backups 7d  │ │ encrypted │ └────────┘
   └────────────┘ └───────────┘
```

## What the stack creates

| Resource | Notes |
|---|---|
| RDS PostgreSQL 16 | Encrypted, private, deletion protection, 7-day backups, Performance Insights. The password is managed by RDS in Secrets Manager. Multi-AZ is optional (`DbMultiAz=true` for production) |
| S3 bucket | Resumes, receipts and generated documents. Private, SSE-S3, versioned, TLS-only bucket policy. Retained if the stack is deleted |
| Secrets Manager | `kairoz-hrm/secret-key`, generated automatically |
| ECS cluster + Fargate service | ARM64 (cheaper), rolling deploys with circuit-breaker rollback, CPU target-tracking autoscaling |
| Application Load Balancer | TLS 1.3 policy, 120-second idle timeout, HTTP → HTTPS redirect |
| IAM | The execution role can read only these secrets. The task role can use this bucket's `hrm/` prefix, send SES email and use ECS Exec |
| CloudWatch | Log group (30 days), alarms for unhealthy targets and 5xx responses |

## Before the first deploy

1. **AWS CLI v2 and Docker with buildx** on the machine that deploys, logged into the target account.
2. **VPC**: two public subnets (for the load balancer) and two private subnets with a NAT gateway (for the app and the database), each pair in different availability zones.
   - With no NAT gateway, pass public subnets as `PRIVATE_SUBNET_IDS` and set `ASSIGN_PUBLIC_IP=ENABLED`.
3. **Certificate**: request an ACM certificate for `hr.kairoz.com` in the same region and validate it through DNS.
4. **SES**:
   - Verify the domain `kairoz.com` (or the sender address).
   - Request production access to leave the sandbox. In the sandbox you can only email verified addresses, so candidates would not receive emails.
5. **Parameters**: `cp deploy/aws/params.example.env deploy/aws/params.env` and fill it in. The file is git-ignored.

## Deploy

```bash
deploy/aws/deploy.sh
```

The script:
1. creates the ECR repository if needed;
2. builds the image for `linux/arm64` and pushes it with a timestamp tag;
3. runs `aws cloudformation deploy`.

The first run takes about 15 minutes, most of it for RDS. Later runs only roll out the new image, with zero downtime.

When it finishes, point DNS at the `LoadBalancerDnsName` output. In Route 53, use an alias A record.

## Create the first HR administrator

In production no password is ever invented and logged, so create the admin with ECS Exec:

```bash
TASK=$(aws ecs list-tasks --cluster kairoz-hrm-cluster --service-name kairoz-hrm-web --query 'taskArns[0]' --output text)
aws ecs execute-command --cluster kairoz-hrm-cluster --task "$TASK" --container web --interactive \
  --command "python -m hr_management create-hr --email hr.admin@kairoz.com --name 'HR Admin'"
```

The command prints a `KZH` user ID and a temporary password, which must be changed at first sign-in. That admin can then add HR colleagues from **Access & accounts**.

## Operations

| Task | How |
|---|---|
| Logs | CloudWatch → `/ecs/kairoz-hrm`, or `aws logs tail /ecs/kairoz-hrm --follow` |
| Scale | Change `DESIRED_COUNT`/`MAX_COUNT` and redeploy. Autoscaling targets 60% CPU |
| Roll back | Redeploy with `IMAGE_TAG=<previous tag> deploy/aws/deploy.sh`. A failed deploy is rolled back automatically by the circuit breaker |
| Database backups | Automated (7 days) plus a final snapshot when the database is deleted. Restore by point-in-time to a new instance |
| Rotate the app secret | Rotate `kairoz-hrm/secret-key` in Secrets Manager, then force a new deployment. Everyone is signed out |
| Rotate the DB password | Built into RDS-managed secrets. Force a new ECS deployment afterwards so tasks pick it up |
| Enable the AI layer | Store the key as a plain-text secret, set `LLM_API_KEY_SECRET_ARN`, redeploy |
| Schema upgrades | Automatic and additive on container start. No migration step is needed |

## Cost guide (ap-south-1, approximate)

| Item | Monthly cost |
|---|---|
| Fargate, 2 × (1 vCPU, 2 GB) ARM | about $60 |
| RDS `db.t4g.small`, single-AZ, 20 GB | about $35 (Multi-AZ doubles this) |
| ALB | about $20 |
| NAT gateway | about $35 plus data |
| S3, SES, CloudWatch | a few dollars |

For a pilot, `DESIRED_COUNT=1` and `db.t4g.micro` roughly halves the total.

## Security checklist

- [ ] `HRM_ENVIRONMENT=production` (set by the template)
- [ ] SES out of the sandbox, sender domain verified, DKIM and SPF set up
- [ ] DNS points to the ALB; the site is only reachable over HTTPS
- [ ] First HR admin created with ECS Exec and the password changed
- [ ] `DbMultiAz=true` for production availability
- [ ] Optional: put AWS WAF (managed rule groups) in front of the ALB
- [ ] Optional: KMS customer-managed keys for RDS and S3 if your compliance requires it
