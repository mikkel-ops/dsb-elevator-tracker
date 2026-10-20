resource "aws_s3_bucket" "raw" {
  bucket = "${var.name}-raw-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket" "site" {
  bucket = "${var.name}-site-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "all" {
  for_each                = { raw = aws_s3_bucket.raw.id, site = aws_s3_bucket.site.id }
  bucket                  = each.value
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "site" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.site.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site.arn]
    }
  }
}

data "aws_iam_policy_document" "raw" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.raw.arn}/raw/*", "${aws_s3_bucket.raw.arn}/screenshots/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "raw" {
  bucket = aws_s3_bucket.raw.id
  policy = data.aws_iam_policy_document.raw.json
}

resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id
  policy = data.aws_iam_policy_document.site.json
}

# Static site files, uploaded by Terraform so `terraform apply` is the whole deploy.
locals {
  site_dir = "${path.module}/../site"
  mime = {
    html = "text/html; charset=utf-8"
    js   = "application/javascript; charset=utf-8"
    css  = "text/css; charset=utf-8"
    json = "application/json; charset=utf-8"
    svg  = "image/svg+xml"
    png  = "image/png"
    ico  = "image/x-icon"
  }
}

resource "aws_s3_object" "site" {
  for_each      = fileset(local.site_dir, "**")
  bucket        = aws_s3_bucket.site.id
  key           = each.value
  source        = "${local.site_dir}/${each.value}"
  etag          = filemd5("${local.site_dir}/${each.value}")
  content_type  = lookup(local.mime, reverse(split(".", each.value))[0], "application/octet-stream")
  cache_control = endswith(each.value, ".html") ? "public, max-age=60" : "public, max-age=3600"
}
