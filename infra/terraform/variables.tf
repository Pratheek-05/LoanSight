variable "subscription_id" {
  description = "Azure Subscription ID"
  type        = string
  sensitive   = true
}

variable "project" {
  description = "Project short name — used in all resource names"
  type        = string
  default     = "loansight"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod."
  }
}

variable "location" {
  description = "Azure region to deploy into"
  type        = string
  default     = "East US"             # cheapest & most available for free tier
}

variable "alert_email" {
  description = "Email address for Azure Monitor alerts"
  type        = string
  sensitive   = true
}
