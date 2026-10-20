resource "aws_sns_topic" "alerts" {
  name = "${var.name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# Catches what the handler can't report itself: timeouts, OOM, init errors.
resource "aws_cloudwatch_metric_alarm" "scraper_errors" {
  alarm_name          = "${var.name}-scraper-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.scraper.function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 3
  threshold           = 3
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
