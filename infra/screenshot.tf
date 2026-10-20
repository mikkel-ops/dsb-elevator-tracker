# Screenshot Lambda: container image (Playwright + Chromium) built locally
# with Docker and pushed to ECR by `terraform apply`.

resource "aws_ecr_repository" "screenshot" {
  name                 = "${var.name}-screenshot"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true
}

resource "aws_ecr_lifecycle_policy" "screenshot" {
  repository = aws_ecr_repository.screenshot.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep only the two newest images (ECR storage is billed)"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 2 }
      action       = { type = "expire" }
    }]
  })
}

locals {
  screenshot_src = ["${path.module}/../screenshot/Dockerfile", "${path.module}/../screenshot/handler.py"]
  screenshot_tag = substr(sha1(join("", [for f in local.screenshot_src : filesha1(f)])), 0, 12)
  screenshot_uri = "${aws_ecr_repository.screenshot.repository_url}:${local.screenshot_tag}"
}

resource "terraform_data" "screenshot_image" {
  triggers_replace = [local.screenshot_uri]

  provisioner "local-exec" {
    working_dir = "${path.module}/../screenshot"
    command     = <<-EOT
      set -e
      aws ecr get-login-password --region ${var.region} \
        | docker login --username AWS --password-stdin ${split("/", aws_ecr_repository.screenshot.repository_url)[0]}
      # --provenance=false: Lambda rejects multi-manifest (attestation) images.
      docker build --platform linux/arm64 --provenance=false -t ${local.screenshot_uri} .
      docker push ${local.screenshot_uri}
    EOT
  }
}

resource "aws_iam_role" "screenshot" {
  name               = "${var.name}-screenshot"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "screenshot" {
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.raw.arn}/screenshots/*"]
  }
  statement {
    actions   = ["dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.main.arn]
  }
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.screenshot.arn}:*"]
  }
}

resource "aws_iam_role_policy" "screenshot" {
  role   = aws_iam_role.screenshot.id
  policy = data.aws_iam_policy_document.screenshot.json
}

resource "aws_cloudwatch_log_group" "screenshot" {
  name              = "/aws/lambda/${var.name}-screenshot"
  retention_in_days = 30
}

resource "aws_lambda_function" "screenshot" {
  function_name = "${var.name}-screenshot"
  role          = aws_iam_role.screenshot.arn
  package_type  = "Image"
  image_uri     = local.screenshot_uri
  architectures = ["arm64"]
  memory_size   = 1024
  timeout       = 120

  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.main.name
      RAW_BUCKET = aws_s3_bucket.raw.id
    }
  }

  depends_on = [terraform_data.screenshot_image, aws_cloudwatch_log_group.screenshot]
}

# Async invocations: don't retry a failed screenshot twice (the next change
# or the daily run will take a new one), but alert on failure.
resource "aws_lambda_function_event_invoke_config" "screenshot" {
  function_name          = aws_lambda_function.screenshot.function_name
  maximum_retry_attempts = 1
  destination_config {
    on_failure {
      destination = aws_sns_topic.alerts.arn
    }
  }
}

data "aws_iam_policy_document" "screenshot_sns" {
  statement {
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }
}

resource "aws_iam_role_policy" "screenshot_sns" {
  role   = aws_iam_role.screenshot.id
  policy = data.aws_iam_policy_document.screenshot_sns.json
}
