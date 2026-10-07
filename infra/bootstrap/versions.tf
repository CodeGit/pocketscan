terraform {
  # ~> permits patching but not major revisions
  required_version = "~> 1.13.1"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.6"
    }
  }
}