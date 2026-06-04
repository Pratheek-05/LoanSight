# LoanSight AI — Azure Deployment Guide

## Prerequisites
- Azure CLI installed: `winget install Microsoft.AzureCLI`
- Terraform installed: `winget install Hashicorp.Terraform`
- Docker Desktop running

---

## Step 1 — Login to Azure

```bash
az login
az account show   # confirm your subscription is active
```

Copy your Subscription ID from the output.

---

## Step 2 — Fill in your variables

Open `infra/terraform/dev.tfvars` and replace:
- `YOUR-AZURE-SUBSCRIPTION-ID` → your actual subscription ID
- `your-email@example.com` → your email for alerts

---

## Step 3 — Run Terraform

```bash
cd infra/terraform

terraform init
terraform plan -var-file="dev.tfvars"
terraform apply -var-file="dev.tfvars"
```

Type `yes` when prompted. Takes ~3-5 minutes.

After apply, note the outputs:
```
acr_login_server  = "acrloansightdev.azurecr.io"
api_url           = "https://ca-loansight-api-dev.xxx.eastus.azurecontainerapps.io"
streamlit_url     = "https://ca-loansight-ui-dev.xxx.eastus.azurecontainerapps.io"
```

---

## Step 4 — Push Docker images to ACR

```bash
# Login to ACR
az acr login --name acrloansightdev

# Build and push API image
docker build -f Dockerfile.api -t acrloansightdev.azurecr.io/loan-api:latest .
docker push acrloansightdev.azurecr.io/loan-api:latest

# Build and push Streamlit image
docker build -f Dockerfile.streamlit -t acrloansightdev.azurecr.io/loan-ui:latest .
docker push acrloansightdev.azurecr.io/loan-ui:latest
```

---

## Step 5 — Verify deployment

```bash
# Check API health
curl https://<your-api-url>/health

# Check API docs
open https://<your-api-url>/docs
```

---

## Step 6 — Set up GitHub Actions CI/CD

In your GitHub repo → Settings → Secrets → Add:

| Secret name          | Value                                      |
|---------------------|--------------------------------------------|
| `AZURE_CREDENTIALS` | Output of the command below               |
| `ACR_LOGIN_SERVER`  | `acrloansightdev.azurecr.io`              |
| `ACR_NAME`          | `acrloansightdev`                         |

Generate Azure credentials:
```bash
az ad sp create-for-rbac \
  --name "sp-loansight-github" \
  --role contributor \
  --scopes /subscriptions/YOUR-SUBSCRIPTION-ID \
  --sdk-auth
```

Paste the entire JSON output as the `AZURE_CREDENTIALS` secret.

Now every push to `main` automatically builds, pushes, and deploys.

---

## Tear down (to save free credits)

```bash
cd infra/terraform
terraform destroy -var-file="dev.tfvars"
```

Or just stop the Container Apps when not presenting:
```bash
az containerapp revision deactivate --name ca-loansight-api-dev --resource-group rg-loansight-dev --revision <revision-name>
```
