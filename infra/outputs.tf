output "site_url" {
  value = "https://${aws_cloudfront_distribution.site.domain_name}"
}

output "table_name" {
  value = aws_dynamodb_table.main.name
}

output "raw_bucket" {
  value = aws_s3_bucket.raw.id
}

output "scraper_function" {
  value = aws_lambda_function.scraper.function_name
}

output "distribution_id" {
  value = aws_cloudfront_distribution.site.id
}
