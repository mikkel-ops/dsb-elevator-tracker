variable "region" {
  type    = string
  default = "eu-north-1"
}

variable "name" {
  type    = string
  default = "dsb-elevator-tracker"
}

variable "alert_email" {
  description = "Receives SNS alerts when the scraper fails. Set in terraform.tfvars (git-ignored)."
  type        = string
}

variable "scrape_schedule" {
  type    = string
  default = "rate(1 hour)"
}

variable "api_reserved_concurrency" {
  description = "Hard cap on concurrent API Lambdas. Set to -1 if the account's concurrency limit is too low to reserve."
  type        = number
  default     = 5
}

variable "build_dir" {
  description = "Where scripts/build.sh puts the Lambda zips."
  type        = string
  default     = "../build"
}
