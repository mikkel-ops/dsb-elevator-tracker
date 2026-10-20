resource "aws_cloudfront_origin_access_control" "s3" {
  name                              = "${var.name}-s3"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_origin_access_control" "lambda" {
  name                              = "${var.name}-lambda"
  origin_access_control_origin_type = "lambda"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# API responses: honour the Lambda's Cache-Control (5 min), cache per query string.
resource "aws_cloudfront_cache_policy" "api" {
  name        = "${var.name}-api"
  min_ttl     = 0
  default_ttl = 300
  max_ttl     = 3600

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "all"
    }
  }
}

data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

# Archived DSB HTML is third-party markup: render it inert on our domain.
resource "aws_cloudfront_response_headers_policy" "evidence" {
  name = "${var.name}-evidence"
  security_headers_config {
    content_security_policy {
      content_security_policy = "sandbox; default-src 'none'; img-src * data:; style-src * 'unsafe-inline'"
      override                = true
    }
    content_type_options {
      override = true
    }
  }
}

locals {
  api_origin_id      = "api"
  site_origin_id     = "site"
  evidence_origin_id = "evidence"
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  comment             = var.name
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  http_version        = "http2and3"

  origin {
    origin_id                = local.site_origin_id
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.s3.id
  }

  origin {
    origin_id                = local.api_origin_id
    domain_name              = regex("https://([^/]+)/", aws_lambda_function_url.api.function_url)[0]
    origin_access_control_id = aws_cloudfront_origin_access_control.lambda.id
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  origin {
    origin_id                = local.evidence_origin_id
    domain_name              = aws_s3_bucket.raw.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.s3.id
  }

  # Evidence: raw HTML snapshots and screenshots, immutable once written.
  dynamic "ordered_cache_behavior" {
    for_each = ["/raw/*", "/screenshots/*"]
    content {
      path_pattern               = ordered_cache_behavior.value
      target_origin_id           = local.evidence_origin_id
      viewer_protocol_policy     = "redirect-to-https"
      allowed_methods            = ["GET", "HEAD"]
      cached_methods             = ["GET", "HEAD"]
      cache_policy_id            = data.aws_cloudfront_cache_policy.optimized.id
      response_headers_policy_id = aws_cloudfront_response_headers_policy.evidence.id
      compress                   = false
    }
  }

  default_cache_behavior {
    target_origin_id       = local.site_origin_id
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.optimized.id
    compress               = true
  }

  ordered_cache_behavior {
    path_pattern           = "/api/*"
    target_origin_id       = local.api_origin_id
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = aws_cloudfront_cache_policy.api.id
    compress               = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
