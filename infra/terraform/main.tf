# ============================================================
# Automatic Fraud Detection — infrastructure de production (AWS, eu-north-1)
#
#   RDS PostgreSQL 16      : bases airflow (métadonnées), mlflow (tracking/registry), fraud (warehouse)
#   S3                     : dataset d'entraînement, artefacts MLflow, exports CSV du rapport quotidien
#   EC2 (m7i-flex.large)   : Airflow 3 + MLflow + Streamlit via docker compose (docker/prod/)
#   IAM                    : rôle d'instance (accès au bucket), aucune clé dans le code
#
#   bash infra/terraform/tf.sh init && bash infra/terraform/tf.sh apply
#   bash infra/terraform/tf.sh destroy      ← après la soutenance (≈ 3 $/jour sinon)
# ============================================================

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.70" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
    tls    = { source = "hashicorp/tls", version = "~> 4.0" }
    http   = { source = "hashicorp/http", version = "~> 3.4" }
    local  = { source = "hashicorp/local", version = "~> 2.5" }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "automatic-fraud-detection", ManagedBy = "terraform" }
  }
}

data "aws_caller_identity" "me" {}

# ───────────────────────── Réseau : VPC par défaut ─────────────────────────

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# IP publique de l'opérateur : seul accès autorisé aux UIs, à SSH et à psql
data "http" "my_ip" {
  url = "https://checkip.amazonaws.com"
}

locals {
  my_cidr = var.operator_cidr != "" ? var.operator_cidr : "${chomp(data.http.my_ip.response_body)}/32"
  name    = "fraud-detection"
  ui_ports = {
    airflow   = 8080
    mlflow    = 5000
    dashboard = 8501
  }
}

resource "aws_security_group" "ec2" {
  name        = "${local.name}-ec2"
  description = "Airflow + MLflow + dashboard host"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "SSH operateur"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [local.my_cidr]
  }

  dynamic "ingress" {
    for_each = local.ui_ports
    content {
      description = "${ingress.key} UI operateur"
      from_port   = ingress.value
      to_port     = ingress.value
      protocol    = "tcp"
      cidr_blocks = [local.my_cidr]
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "rds" {
  name        = "${local.name}-rds"
  description = "PostgreSQL airflow / mlflow / fraud"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "PostgreSQL depuis l'EC2"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ec2.id]
  }
  ingress {
    description = "PostgreSQL operateur (psql depuis le poste)"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [local.my_cidr]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ───────────────────────── S3 : dataset, artefacts MLflow, rapports ─────────────────────────

resource "random_id" "bucket" {
  byte_length = 3
}

resource "aws_s3_bucket" "data" {
  bucket        = "${local.name}-${data.aws_caller_identity.me.account_id}-${random_id.bucket.hex}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration { status = "Enabled" }
}

# Dataset d'entraînement (144 Mo, non versionné dans git) : l'instance le télécharge au boot
resource "aws_s3_object" "dataset" {
  bucket = aws_s3_bucket.data.id
  key    = "data/fraudTest.csv"
  source = var.dataset_path
  etag   = filemd5(var.dataset_path)
}

# ───────────────────────── RDS PostgreSQL 16 ─────────────────────────

resource "random_password" "rds_master" {
  length  = 24
  special = false
}

resource "random_password" "db_airflow" {
  length  = 24
  special = false
}

resource "random_password" "db_mlflow" {
  length  = 24
  special = false
}

resource "random_password" "db_fraud" {
  length  = 24
  special = false
}

resource "aws_db_subnet_group" "rds" {
  name       = "${local.name}-rds"
  subnet_ids = data.aws_subnets.default.ids
}

resource "aws_db_instance" "postgres" {
  identifier              = "${local.name}-postgres"
  engine                  = "postgres"
  engine_version          = "16"
  instance_class          = var.rds_instance_class
  allocated_storage       = 20
  storage_type            = "gp3"
  storage_encrypted       = true
  db_name                 = "postgres"
  username                = "fraud_admin"
  password                = random_password.rds_master.result
  db_subnet_group_name    = aws_db_subnet_group.rds.name
  vpc_security_group_ids  = [aws_security_group.rds.id]
  publicly_accessible     = true # restreint à l'IP opérateur + SG EC2
  multi_az                = false
  backup_retention_period = 1
  skip_final_snapshot     = true
  deletion_protection     = false
  apply_immediately       = true
}

# ───────────────────────── IAM : rôle d'instance (S3 uniquement) ─────────────────────────

resource "aws_iam_role" "ec2" {
  name = "${local.name}-ec2"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "ec2_s3" {
  name = "s3-data-bucket"
  role = aws_iam_role.ec2.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:ListBucket", "s3:GetBucketLocation"], Resource = aws_s3_bucket.data.arn },
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], Resource = "${aws_s3_bucket.data.arn}/*" }
    ]
  })
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${local.name}-ec2"
  role = aws_iam_role.ec2.name
}

# ───────────────────────── EC2 : Airflow + MLflow + dashboard ─────────────────────────

resource "tls_private_key" "ssh" {
  algorithm = "ED25519"
}

resource "aws_key_pair" "ssh" {
  key_name   = "${local.name}-key"
  public_key = tls_private_key.ssh.public_key_openssh
}

resource "local_sensitive_file" "ssh_key" {
  content         = tls_private_key.ssh.private_key_openssh
  filename        = "${path.module}/keys/${local.name}.pem"
  file_permission = "0600"
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
}

resource "random_password" "airflow_admin" {
  length  = 16
  special = false
}

resource "random_password" "airflow_jwt" {
  length  = 48
  special = false
}

# Clé Fernet : 32 octets en base64 url-safe
resource "random_bytes" "fernet" {
  length = 32
}

locals {
  fernet_key = replace(replace(random_bytes.fernet.base64, "+", "-"), "/", "_")
}

resource "aws_instance" "airflow" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.ec2_instance_type
  key_name               = aws_key_pair.ssh.key_name
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.ec2.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
    encrypted   = true
  }

  # IMDSv2 accessible depuis les conteneurs Docker (2 sauts réseau)
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  user_data = templatefile("${path.module}/user_data.sh", {
    repo_url            = var.repo_url
    repo_ref            = var.repo_ref
    aws_region          = var.region
    s3_bucket           = aws_s3_bucket.data.bucket
    dataset_key         = aws_s3_object.dataset.key
    rds_host            = aws_db_instance.postgres.address
    rds_master_user     = aws_db_instance.postgres.username
    rds_master_password = random_password.rds_master.result
    db_airflow_password = random_password.db_airflow.result
    db_mlflow_password  = random_password.db_mlflow.result
    db_fraud_password   = random_password.db_fraud.result
    airflow_fernet_key  = local.fernet_key
    airflow_jwt_secret  = random_password.airflow_jwt.result
    airflow_admin_user  = "airflow"
    airflow_admin_pass  = random_password.airflow_admin.result
    discord_webhook_url = var.discord_webhook_url
    fraud_threshold     = var.fraud_threshold
    report_timezone     = var.report_timezone
  })
  user_data_replace_on_change = true

  tags = { Name = "${local.name}-airflow" }

  depends_on = [aws_db_instance.postgres, aws_s3_object.dataset]
}
