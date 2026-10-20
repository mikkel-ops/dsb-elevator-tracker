data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# ---------- scraper ----------

resource "aws_iam_role" "scraper" {
  name               = "${var.name}-scraper"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "scraper" {
  statement {
    actions = [
      "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
      "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan",
    ]
    resources = [aws_dynamodb_table.main.arn, "${aws_dynamodb_table.main.arn}/index/*"]
  }
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.raw.arn}/raw/*"]
  }
  statement {
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.screenshot.arn]
  }
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.scraper.arn}:*"]
  }
}

resource "aws_iam_role_policy" "scraper" {
  role   = aws_iam_role.scraper.id
  policy = data.aws_iam_policy_document.scraper.json
}

resource "aws_cloudwatch_log_group" "scraper" {
  name              = "/aws/lambda/${var.name}-scraper"
  retention_in_days = 30
}

resource "aws_lambda_function" "scraper" {
  function_name    = "${var.name}-scraper"
  role             = aws_iam_role.scraper.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "scraper.handler.lambda_handler"
  filename         = "${var.build_dir}/scraper.zip"
  source_code_hash = filebase64sha256("${var.build_dir}/scraper.zip")
  memory_size      = 256
  timeout          = 120

  environment {
    variables = {
      TABLE_NAME          = aws_dynamodb_table.main.name
      RAW_BUCKET          = aws_s3_bucket.raw.id
      ALERT_TOPIC_ARN     = aws_sns_topic.alerts.arn
      SCREENSHOT_FUNCTION = aws_lambda_function.screenshot.function_name
    }
  }

  depends_on = [aws_cloudwatch_log_group.scraper]
}

resource "aws_cloudwatch_event_rule" "scrape" {
  name                = "${var.name}-scrape"
  schedule_expression = var.scrape_schedule
}

resource "aws_cloudwatch_event_target" "scrape" {
  rule = aws_cloudwatch_event_rule.scrape.name
  arn  = aws_lambda_function.scraper.arn
}

resource "aws_lambda_permission" "scrape" {
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scraper.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.scrape.arn
}

# ---------- API ----------

resource "aws_iam_role" "api" {
  name               = "${var.name}-api"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "api" {
  statement {
    actions   = ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan"]
    resources = [aws_dynamodb_table.main.arn, "${aws_dynamodb_table.main.arn}/index/*"]
  }
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.api.arn}:*"]
  }
}

resource "aws_iam_role_policy" "api" {
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api.json
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${var.name}-api"
  retention_in_days = 14
}

resource "aws_lambda_function" "api" {
  function_name                  = "${var.name}-api"
  role                           = aws_iam_role.api.arn
  runtime                        = "python3.12"
  architectures                  = ["arm64"]
  handler                        = "api.app.handler"
  filename                       = "${var.build_dir}/api.zip"
  source_code_hash               = filebase64sha256("${var.build_dir}/api.zip")
  memory_size                    = 512
  timeout                        = 15
  reserved_concurrent_executions = var.api_reserved_concurrency

  environment {
    variables = {
      TABLE_NAME = aws_dynamodb_table.main.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.api]
}

# IAM-authenticated: only CloudFront (via OAC) can call it.
resource "aws_lambda_function_url" "api" {
  function_name      = aws_lambda_function.api.function_name
  authorization_type = "AWS_IAM"
}

resource "aws_lambda_permission" "api_url" {
  statement_id  = "AllowCloudFrontInvokeUrl"
  action        = "lambda:InvokeFunctionUrl"
  function_name = aws_lambda_function.api.function_name
  principal     = "cloudfront.amazonaws.com"
  source_arn    = aws_cloudfront_distribution.site.arn
}

resource "aws_lambda_permission" "api_invoke" {
  statement_id  = "AllowCloudFrontInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "cloudfront.amazonaws.com"
  source_arn    = aws_cloudfront_distribution.site.arn
}
