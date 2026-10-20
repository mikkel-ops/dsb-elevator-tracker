# One-time bootstrap: creates the S3 bucket that holds Terraform remote state
# for infra/, and writes ../backend.hcl for `make init`.
#
# Chicken-and-egg: the very first run must use local state - comment out the
# backend block, `init && apply`, then restore it and migrate:
#   terraform init -backend-config=../backend.hcl \
#     -backend-config=key=bootstrap/terraform.tfstate -migrate-state

terraform {
  required_version = ">= 1.10" # S3-native state locking (use_lockfile)
  required_providers {
    aws   = { source = "hashicorp/aws", version = "~> 6.0" }
    local = { source = "hashicorp/local", version = "~> 2.5" }
  }
  backend "s3" {}
}

variable "region" {
  type    = string
  default = "eu-north-1"
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "dsb-elevator-tracker" }
  }
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "state" {
  bucket = "dsb-elevator-tracker-tfstate-${data.aws_caller_identity.current.account_id}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

resource "local_file" "backend" {
  filename = "${path.module}/../backend.hcl"
  content  = <<-EOT
    bucket       = "${aws_s3_bucket.state.id}"
    key          = "dsb-elevator-tracker/terraform.tfstate"
    region       = "${var.region}"
    encrypt      = true
    use_lockfile = true
  EOT
}

output "state_bucket" {
  value = aws_s3_bucket.state.id
}
