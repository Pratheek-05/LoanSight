variable "region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "ap-south-2"    # Hyderabad
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

variable "alert_email" {
  description = "Email address for CloudWatch alerts via SNS"
  type        = string
  sensitive   = true
}
