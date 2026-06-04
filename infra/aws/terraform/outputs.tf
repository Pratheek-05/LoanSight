# ── Locals ─────────────────────────────────────────────────────────────────────
locals {
  common_tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
    Owner       = "pratheek"
  }
}

# ── Outputs ────────────────────────────────────────────────────────────────────
output "ecr_api_url" {
  description = "ECR repository URL for the API image — use in docker push"
  value       = aws_ecr_repository.api.repository_url
}

output "ecr_ui_url" {
  description = "ECR repository URL for the UI image — use in docker push"
  value       = aws_ecr_repository.ui.repository_url
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.main.name
}

output "api_service_name" {
  description = "ECS service name for the API"
  value       = aws_ecs_service.api.name
}

output "ui_service_name" {
  description = "ECS service name for the UI"
  value       = aws_ecs_service.ui.name
}

output "sns_topic_arn" {
  description = "SNS topic ARN for alerts"
  value       = aws_sns_topic.alerts.arn
}

output "get_api_public_ip" {
  description = "Command to get the running API task public IP"
  value       = "aws ecs list-tasks --cluster ${aws_ecs_cluster.main.name} --service-name ${aws_ecs_service.api.name} --query 'taskArns[0]' --output text | xargs -I{} aws ecs describe-tasks --cluster ${aws_ecs_cluster.main.name} --tasks {} --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' --output text | xargs aws ec2 describe-network-interfaces --network-interface-ids --query 'NetworkInterfaces[0].Association.PublicIp' --output text"
}
