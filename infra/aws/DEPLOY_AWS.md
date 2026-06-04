# LoanSight AI — AWS Deployment Guide (Hyderabad / ap-south-2)

## Prerequisites
- AWS CLI: `winget install Amazon.AWSCLI`
- Terraform: `winget install Hashicorp.Terraform`
- Docker Desktop running
- AWS account with free tier / $100 credits

---

## Step 1 — Configure AWS CLI

```bash
aws configure
# AWS Access Key ID:     <from IAM console>
# AWS Secret Access Key: <from IAM console>
# Default region:        ap-south-2
# Default output format: json
```

Get your credentials from: AWS Console → IAM → Users → Your User → Security credentials → Create access key

---

## Step 2 — Fill in variables

Open `infra/aws/terraform/dev.tfvars`:
```
alert_email = "your-email@example.com"
```

---

## Step 3 — Run Terraform

```bash
cd infra/aws/terraform

terraform init
terraform plan  -var-file="dev.tfvars"
terraform apply -var-file="dev.tfvars"
```

Type `yes` when prompted. Takes ~2 minutes.

Note the outputs — you'll need the ECR URLs:
```
ecr_api_url = "123456789.dkr.ecr.ap-south-2.amazonaws.com/loansight-api"
ecr_ui_url  = "123456789.dkr.ecr.ap-south-2.amazonaws.com/loansight-ui"
```

---

## Step 4 — Push Docker images to ECR

```bash
# Authenticate Docker with ECR
aws ecr get-login-password --region ap-south-2 | \
  docker login --username AWS --password-stdin \
  123456789.dkr.ecr.ap-south-2.amazonaws.com

# Build and push API
docker build -f Dockerfile.api \
  -t 123456789.dkr.ecr.ap-south-2.amazonaws.com/loansight-api:latest .
docker push 123456789.dkr.ecr.ap-south-2.amazonaws.com/loansight-api:latest

# Build and push UI
docker build -f Dockerfile.streamlit \
  -t 123456789.dkr.ecr.ap-south-2.amazonaws.com/loansight-ui:latest .
docker push 123456789.dkr.ecr.ap-south-2.amazonaws.com/loansight-ui:latest
```

---

## Step 5 — Get your running task's public IP

Fargate assigns a public IP to each task. Get it with:

```bash
# Get API task IP
TASK=$(aws ecs list-tasks \
  --cluster loansight-cluster-dev \
  --service-name loansight-api-dev \
  --query 'taskArns[0]' --output text)

ENI=$(aws ecs describe-tasks \
  --cluster loansight-cluster-dev --tasks $TASK \
  --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' \
  --output text)

aws ec2 describe-network-interfaces \
  --network-interface-ids $ENI \
  --query 'NetworkInterfaces[0].Association.PublicIp' --output text
```

Then open:
- API docs:    `http://<IP>:8000/docs`
- Streamlit:   `http://<IP>:8501`
- Drift status:`http://<IP>:8000/drift/status`

---

## Step 6 — GitHub Actions secrets

In GitHub repo → Settings → Secrets → Actions → New secret:

| Secret name             | Value                        |
|------------------------|------------------------------|
| `AWS_ACCESS_KEY_ID`    | Your IAM access key          |
| `AWS_SECRET_ACCESS_KEY`| Your IAM secret key          |

Create a least-privilege IAM policy for GitHub Actions:
```bash
aws iam create-policy \
  --policy-name loansight-github-actions \
  --policy-document file://infra/aws/iam-github-policy.json
```

---

## Cost estimate (ap-south-2)

| Resource            | Cost/month (running 8hrs/day) |
|--------------------|-------------------------------|
| Fargate API (0.5 vCPU, 1GB) | ~$4–6 |
| Fargate UI (0.25 vCPU, 0.5GB) | ~$2–3 |
| ECR storage         | ~$0 (under 500MB free) |
| CloudWatch Logs     | ~$0 (under 5GB free) |
| **Total**           | **~$6–9/month** |

## Stop everything when not using (save credits)

```bash
# Scale services to 0 (stops billing for Fargate)
aws ecs update-service --cluster loansight-cluster-dev \
  --service loansight-api-dev --desired-count 0
aws ecs update-service --cluster loansight-cluster-dev \
  --service loansight-ui-dev --desired-count 0

# Scale back up when needed
aws ecs update-service --cluster loansight-cluster-dev \
  --service loansight-api-dev --desired-count 1
aws ecs update-service --cluster loansight-cluster-dev \
  --service loansight-ui-dev --desired-count 1
```

## Tear down completely

```bash
cd infra/aws/terraform
terraform destroy -var-file="dev.tfvars"
```
