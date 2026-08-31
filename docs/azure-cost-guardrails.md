# Azure cost guardrails

The free account gives ~$200 of credit for 30 days plus 12 months of limited
free services. Rules to make it last:

1. **Nothing long-lived until M3.** M0–M2 run entirely on kind; the only Azure
   resource M2 needs is a storage account (blob storage is pennies at this
   scale).
2. **Everything through Terraform/Bicep** so teardown is one command. Never
   click-create resources in the portal — orphaned resources are how credits
   die.
3. **AKS**: free control plane, one `Standard_B2s` or spot node pool. Stop the
   cluster (`az aks stop`) when not demoing; a stopped cluster bills only disks.
4. **Set a budget alert** on day one: Cost Management → budget at $50 with
   alerts at 50/80/100%. Do this before creating anything else.
5. **Azure NetApp Files itself is NOT part of this project's steady state.**
   Minimum capacity pool is 1 TiB (~$150–400/mo) but billed hourly — only ever
   provision it for short benchmark runs (the separate validation-harness
   project), a few hours at a time, destroyed the same day.
6. **ACR**: Basic tier. Clean old image tags monthly.
7. When the 30-day credit expires, the whole M3 environment must be
   reproducible from `terraform apply` — treat the cloud env as ephemeral,
   which is itself the operational skill worth demonstrating.
