# M2 infrastructure: the tiering target. Deliberately minimal — a resource
# group, one storage account, one container. M3 extends this with ACR + AKS.
# Everything here must survive `terraform destroy` + `terraform apply` cleanly
# (docs/azure-cost-guardrails.md: the cloud env is ephemeral by design).

terraform {
  required_version = ">= 1.5"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {}
  # Auth comes from `az login`; subscription from the CLI default.
}

variable "location" {
  type    = string
  default = "eastus2"
}

resource "azurerm_resource_group" "minifiles" {
  name     = "minifiles-rg"
  location = var.location
}

# Storage account names are globally unique, lowercase alphanumeric, <=24 chars.
resource "random_string" "sa_suffix" {
  length  = 8
  upper   = false
  special = false
}

resource "azurerm_storage_account" "tiering" {
  name                     = "minifiles${random_string.sa_suffix.result}"
  resource_group_name      = azurerm_resource_group.minifiles.name
  location                 = azurerm_resource_group.minifiles.location
  account_tier             = "Standard"
  account_replication_type = "LRS" # cheapest; tiered data is reproducible from source volumes
  min_tls_version          = "TLS1_2"

  blob_properties {
    delete_retention_policy {
      days = 7 # cheap safety net against accidental blob deletion
    }
  }
}

resource "azurerm_storage_container" "tiered" {
  name                  = "tiered"
  storage_account_id    = azurerm_storage_account.tiering.id
  container_access_type = "private"
}

output "storage_account_name" {
  value = azurerm_storage_account.tiering.name
}

output "container_name" {
  value = azurerm_storage_container.tiered.name
}

output "connection_string" {
  value     = azurerm_storage_account.tiering.primary_connection_string
  sensitive = true
}
