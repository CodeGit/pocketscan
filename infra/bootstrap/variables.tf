variable "project_id" {
  description = "GCP project ID"
  type        = string
  default     = "pocketscan-510907"
}

variable "region" {
  description = "Default region"
  type        = string
  default     = "europe-west2"
}

variable "billing_account" {
  description = "Billing account ID for the project"
  type        = string
  default     = "015DF0-EAA37D-C6C842"
}