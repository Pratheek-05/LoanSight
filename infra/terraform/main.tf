# ── Providers ─────────────────────────────────────────────────────────────────
terraform {
  required_version = ">= 1.6.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.100"
    }
    azapi = {
      source  = "azure/azapi"
      version = "~> 1.13"
    }
  }

  # Uncomment this block after creating your storage account for remote state
  # backend "azurerm" {
  #   resource_group_name  = "rg-loansight-tfstate"
  #   storage_account_name = "stloansighttfstate"
  #   container_name       = "tfstate"
  #   key                  = "loansight.terraform.tfstate"
  # }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

# ── Resource Group ─────────────────────────────────────────────────────────────
resource "azurerm_resource_group" "main" {
  name     = "rg-${var.project}-${var.environment}"
  location = var.location

  tags = local.common_tags
}

# ── Log Analytics Workspace ────────────────────────────────────────────────────
resource "azurerm_log_analytics_workspace" "main" {
  name                = "law-${var.project}-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "PerGB2018"
  retention_in_days   = 30          # free tier: 30 days max

  tags = local.common_tags
}

# ── Azure Container Registry ───────────────────────────────────────────────────
resource "azurerm_container_registry" "main" {
  name                = "acr${var.project}${var.environment}"   # must be globally unique, alphanumeric only
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"     # cheapest tier — fine for dev/demo
  admin_enabled       = true        # enables simple username/password auth for Container Apps

  tags = local.common_tags
}

# ── Container Apps Environment ─────────────────────────────────────────────────
resource "azurerm_container_app_environment" "main" {
  name                       = "cae-${var.project}-${var.environment}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  tags = local.common_tags
}

# ── Container App: FastAPI Prediction API ──────────────────────────────────────
resource "azurerm_container_app" "api" {
  name                         = "ca-loansight-api-${var.environment}"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"

  registry {
    server               = azurerm_container_registry.main.login_server
    username             = azurerm_container_registry.main.admin_username
    password_secret_name = "acr-password"
  }

  secret {
    name  = "acr-password"
    value = azurerm_container_registry.main.admin_password
  }

  template {
    min_replicas = 0    # scales to zero when idle — saves free credits
    max_replicas = 3

    # Scale out when CPU > 50% or HTTP requests > 10 concurrent
    custom_scale_rule {
      name             = "http-scaling"
      custom_rule_type = "http"
      metadata = {
        concurrentRequests = "10"
      }
    }

    container {
      name   = "loan-api"
      image  = "${azurerm_container_registry.main.login_server}/loan-api:latest"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }

      liveness_probe {
        path             = "/health"
        port             = 8000
        transport        = "HTTP"
        initial_delay    = 15
        interval_seconds = 30
        failure_count_threshold = 3
      }

      readiness_probe {
        path             = "/ready"
        port             = 8000
        transport        = "HTTP"
        initial_delay    = 10
        interval_seconds = 15
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  tags = local.common_tags
}

# ── Container App: Streamlit UI ────────────────────────────────────────────────
resource "azurerm_container_app" "streamlit" {
  name                         = "ca-loansight-ui-${var.environment}"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"

  registry {
    server               = azurerm_container_registry.main.login_server
    username             = azurerm_container_registry.main.admin_username
    password_secret_name = "acr-password"
  }

  secret {
    name  = "acr-password"
    value = azurerm_container_registry.main.admin_password
  }

  template {
    min_replicas = 0
    max_replicas = 2

    container {
      name   = "loan-ui"
      image  = "${azurerm_container_registry.main.login_server}/loan-ui:latest"
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        name  = "API_URL"
        value = "https://${azurerm_container_app.api.ingress[0].fqdn}"
      }

      liveness_probe {
        path             = "/_stcore/health"
        port             = 8501
        transport        = "HTTP"
        initial_delay    = 20
        interval_seconds = 30
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8501
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  tags = local.common_tags
}

# ── Azure Monitor: Alert on high error rate ────────────────────────────────────
resource "azurerm_monitor_action_group" "email_alert" {
  name                = "ag-loansight-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
  short_name          = "loansight"

  email_receiver {
    name                    = "admin"
    email_address           = var.alert_email
    use_common_alert_schema = true
  }
}

resource "azurerm_monitor_metric_alert" "api_errors" {
  name                = "alert-api-errors-${var.environment}"
  resource_group_name = azurerm_resource_group.main.name
  scopes              = [azurerm_container_app.api.id]
  description         = "Alert when API error rate exceeds threshold"
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT15M"

  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "Requests"
    aggregation      = "Count"
    operator         = "GreaterThan"
    threshold        = 100

    dimension {
      name     = "statusCodeCategory"
      operator = "Include"
      values   = ["5xx"]
    }
  }

  action {
    action_group_id = azurerm_monitor_action_group.email_alert.id
  }
}
