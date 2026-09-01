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

# --- M3: registry + cluster -------------------------------------------------

resource "azurerm_container_registry" "acr" {
  name                = "minifilesacr${random_string.sa_suffix.result}"
  resource_group_name = azurerm_resource_group.minifiles.name
  location            = azurerm_resource_group.minifiles.location
  sku                 = "Basic"
  admin_enabled       = false # AKS pulls via managed identity, CI via service principal
}

resource "azurerm_kubernetes_cluster" "aks" {
  name                = "minifiles-aks"
  resource_group_name = azurerm_resource_group.minifiles.name
  location            = azurerm_resource_group.minifiles.location
  dns_prefix          = "minifiles"

  default_node_pool {
    name       = "system"
    node_count = 1
    vm_size    = "Standard_D2as_v6" # 2 vCPU / 8 GiB: fits argo + monitoring + workloads (B-series not allowed in this subscription)
  }

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_role_assignment" "aks_pulls_acr" {
  principal_id                     = azurerm_kubernetes_cluster.aks.kubelet_identity[0].object_id
  role_definition_name             = "AcrPull"
  scope                            = azurerm_container_registry.acr.id
  skip_service_principal_aad_check = true
}

output "acr_login_server" {
  value = azurerm_container_registry.acr.login_server
}

output "acr_id" {
  value = azurerm_container_registry.acr.id
}

output "aks_name" {
  value = azurerm_kubernetes_cluster.aks.name
}

output "resource_group" {
  value = azurerm_resource_group.minifiles.name
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
