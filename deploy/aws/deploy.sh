#!/usr/bin/env bash
# Build the image for ARM64 Fargate, push it to ECR and create/update the CloudFormation stack.
#
# Usage:  deploy/aws/deploy.sh            (reads deploy/aws/params.env)
# First run creates everything (≈15 min, RDS is the slow part); later runs roll out a new image.
set -euo pipefail
cd "$(dirname "$0")/../.."

PARAMS_FILE="deploy/aws/params.env"
[[ -f "$PARAMS_FILE" ]] || { echo "Copy deploy/aws/params.example.env to $PARAMS_FILE and fill it in."; exit 1; }
# shellcheck disable=SC1090
source "$PARAMS_FILE"

: "${AWS_REGION:?}" "${STACK_NAME:?}" "${APP_NAME:?}" "${VPC_ID:?}" "${PUBLIC_SUBNET_IDS:?}" "${PRIVATE_SUBNET_IDS:?}"
: "${CERTIFICATE_ARN:?}" "${PUBLIC_BASE_URL:?}" "${EMAIL_FROM:?}"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REPO="${APP_NAME}"
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
TAG="${IMAGE_TAG:-$(date +%Y%m%d-%H%M%S)-$(git rev-parse --short HEAD 2>/dev/null || echo local)}"
IMAGE_URI="${REGISTRY}/${REPO}:${TAG}"

echo "▶ ECR repository ${REPO}"
aws ecr describe-repositories --repository-names "$REPO" --region "$AWS_REGION" >/dev/null 2>&1 || \
  aws ecr create-repository --repository-name "$REPO" --region "$AWS_REGION" \
    --image-scanning-configuration scanOnPush=true --encryption-configuration encryptionType=AES256 >/dev/null

echo "▶ Build and push ${IMAGE_URI}"
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$REGISTRY"
docker buildx build --platform linux/arm64 -t "$IMAGE_URI" --push .

echo "▶ Deploy stack ${STACK_NAME}"
aws cloudformation deploy \
  --region "$AWS_REGION" \
  --stack-name "$STACK_NAME" \
  --template-file deploy/aws/cloudformation.yaml \
  --capabilities CAPABILITY_IAM \
  --no-fail-on-empty-changeset \
  --parameter-overrides \
    AppName="$APP_NAME" VpcId="$VPC_ID" PublicSubnetIds="$PUBLIC_SUBNET_IDS" PrivateSubnetIds="$PRIVATE_SUBNET_IDS" \
    AssignPublicIp="${ASSIGN_PUBLIC_IP:-DISABLED}" CertificateArn="$CERTIFICATE_ARN" PublicBaseUrl="$PUBLIC_BASE_URL" \
    ImageUri="$IMAGE_URI" EmailFrom="$EMAIL_FROM" BootstrapHrEmail="${BOOTSTRAP_HR_EMAIL:-}" \
    DesiredCount="${DESIRED_COUNT:-2}" MaxCount="${MAX_COUNT:-4}" DbInstanceClass="${DB_INSTANCE_CLASS:-db.t4g.small}" \
    DbMultiAz="${DB_MULTI_AZ:-false}" LlmApiKeySecretArn="${LLM_API_KEY_SECRET_ARN:-}"

aws cloudformation describe-stacks --region "$AWS_REGION" --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[].[OutputKey,OutputValue]" --output table
echo "✔ Deployed ${IMAGE_URI}"
