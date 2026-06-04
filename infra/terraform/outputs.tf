# ── Locals ─────────────────────────────────────────────────────────────────────
locals {
  common_tags = {
    project     = var.project
    environment = var.environment
    managed_by  = "terraform"
    owner       = "loansight-team"
  }
}

# ── Outputs ────────────────────────────────────────────────────────────────────
output "resource_group_name" {
  description = "Resource group containing all LoanSight resources"
  value       = azurerm_resource_group.main.name
}

output "acr_login_server" {
  description = "ACR login server — use this in docker push commands"
  value       = azurerm_container_registry.main.login_server
}

output "acr_admin_username" {
  description = "ACR admin username"
  value       = azurerm_container_registry.main.admin_username
  sensitive   = true
}

output "api_url" {
  description = "Public URL for the FastAPI prediction API"
  value       = "https://${azurerm_container_app.api.ingress[0].fqdn}"
}

output "streamlit_url" {
  description = "Public URL for the Streamlit UI"
  value       = "https://${azurerm_container_app.streamlit.ingress[0].fqdn}"
}

output "log_analytics_workspace_id" {
  description = "Log Analytics workspace ID for querying logs"
  value       = azurerm_log_analytics_workspace.main.workspace_id
}
