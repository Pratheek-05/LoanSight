# ── Providers ──────────────────────────────────────────────────────────────────
terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.50"
    }
  }

  # Uncomment after creating S3 bucket + DynamoDB table for remote state
  # backend "s3" {
  #   bucket         = "loansight-tfstate-ap-south-2"
  #   key            = "loansight/terraform.tfstate"
  #   region         = "ap-south-2"
  #   dynamodb_table = "loansight-tfstate-lock"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.region
}

# ── Data sources ───────────────────────────────────────────────────────────────
# Use default VPC — no NAT Gateway cost
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "public" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# ── ECR Repositories ───────────────────────────────────────────────────────────
resource "aws_ecr_repository" "api" {
  name                 = "${var.project}-api"
  image_tag_mutability = "MUTABLE"    # allow :latest tag overwrite

  image_scanning_configuration {
    scan_on_push = true               # free security scan on every push
  }

  lifecycle {
    prevent_destroy = false
  }

  tags = local.common_tags
}

resource "aws_ecr_repository" "ui" {
  name                 = "${var.project}-ui"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = local.common_tags
}

# ECR lifecycle policy — keep only last 5 images to save storage costs
resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 5 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 5
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_ecr_lifecycle_policy" "ui" {
  repository = aws_ecr_repository.ui.name
  policy     = aws_ecr_lifecycle_policy.api.policy
}

# ── IAM — ECS Task Execution Role ──────────────────────────────────────────────
# Allows ECS to pull images from ECR and write logs to CloudWatch
resource "aws_iam_role" "ecs_task_execution" {
  name = "${var.project}-ecs-task-execution-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ── IAM — Task Role (app permissions) ─────────────────────────────────────────
# Allows the running container to write CloudWatch metrics
resource "aws_iam_role" "ecs_task" {
  name = "${var.project}-ecs-task-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy" "ecs_task_cloudwatch" {
  name = "cloudwatch-metrics"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "cloudwatch:PutMetricData",
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ]
      Resource = "*"
    }]
  })
}

# ── Security Group — allow inbound on API and UI ports ─────────────────────────
resource "aws_security_group" "ecs_tasks" {
  name        = "${var.project}-ecs-sg-${var.environment}"
  description = "Allow inbound traffic to LoanSight containers"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "FastAPI"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Streamlit"
    from_port   = 8501
    to_port     = 8501
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = local.common_tags
}

# ── CloudWatch Log Groups ──────────────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.project}-api-${var.environment}"
  retention_in_days = 7    # keep costs low on free tier

  tags = local.common_tags
}

resource "aws_cloudwatch_log_group" "ui" {
  name              = "/ecs/${var.project}-ui-${var.environment}"
  retention_in_days = 7

  tags = local.common_tags
}

# ── ECS Cluster ────────────────────────────────────────────────────────────────
resource "aws_ecs_cluster" "main" {
  name = "${var.project}-cluster-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "disabled"    # saves CloudWatch costs on free tier
  }

  tags = local.common_tags
}

# ── ECS Task Definition — FastAPI ──────────────────────────────────────────────
resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project}-api-${var.environment}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512     # 0.5 vCPU
  memory                   = 1024    # 1 GB
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "loan-api"
    image     = "${aws_ecr_repository.api.repository_url}:latest"
    essential = true

    portMappings = [{
      containerPort = 8000
      protocol      = "tcp"
    }]

    environment = [
      { name = "ENVIRONMENT", value = var.environment },
      { name = "DRIFT_CHECK_INTERVAL", value = "120" }
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "ecs"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\""]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 15
    }
  }])

  tags = local.common_tags
}

# ── ECS Task Definition — Streamlit ───────────────────────────────────────────
resource "aws_ecs_task_definition" "ui" {
  family                   = "${var.project}-ui-${var.environment}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256     # 0.25 vCPU
  memory                   = 512     # 0.5 GB
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([{
    name      = "loan-ui"
    image     = "${aws_ecr_repository.ui.repository_url}:latest"
    essential = true

    portMappings = [{
      containerPort = 8501
      protocol      = "tcp"
    }]

    environment = [
      { name = "ENVIRONMENT", value = var.environment }
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.ui.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "ecs"
      }
    }

    healthCheck = {
      command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')\""]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 20
    }
  }])

  tags = local.common_tags
}

# ── ECS Service — FastAPI ──────────────────────────────────────────────────────
resource "aws_ecs_service" "api" {
  name            = "${var.project}-api-${var.environment}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  # Set to false so Terraform doesn't wait forever on first deploy
  # (image must be pushed to ECR before running terraform apply)
  force_new_deployment = true

  network_configuration {
    subnets          = data.aws_subnets.public.ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true    # no NAT Gateway needed — saves ~$32/month
  }

  # Allow rolling deployments without downtime
  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200

  depends_on = [aws_iam_role_policy_attachment.ecs_task_execution]

  tags = local.common_tags
}

# ── ECS Service — Streamlit ────────────────────────────────────────────────────
resource "aws_ecs_service" "ui" {
  name            = "${var.project}-ui-${var.environment}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.ui.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  force_new_deployment = true

  network_configuration {
    subnets          = data.aws_subnets.public.ids
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = true
  }

  deployment_minimum_healthy_percent = 50
  deployment_maximum_percent         = 200

  depends_on = [aws_iam_role_policy_attachment.ecs_task_execution]

  tags = local.common_tags
}

# ── SNS Topic for alerts ───────────────────────────────────────────────────────
resource "aws_sns_topic" "alerts" {
  name = "${var.project}-alerts-${var.environment}"
  tags = local.common_tags
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ── CloudWatch Alarm — API task stopped ───────────────────────────────────────
resource "aws_cloudwatch_metric_alarm" "api_task_count" {
  alarm_name          = "${var.project}-api-task-stopped-${var.environment}"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "RunningTaskCount"
  namespace           = "ECS/ContainerInsights"
  period              = 60
  statistic           = "Average"
  threshold           = 1
  alarm_description   = "API Fargate task has stopped"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.api.name
  }

  tags = local.common_tags
}
