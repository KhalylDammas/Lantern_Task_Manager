#!/usr/bin/env bash
# Grant Microsoft Graph User.Read.All (Application) to the bot's user-assigned MSI.
#
# Azure ARM deploy creates a *separate* Entra app for the managed identity (CLIENT_ID
# app setting). Permissions granted on the local Toolkit bot app (F5 / aadApp/create)
# do NOT apply to that MSI app.
#
# Usage:
#   ./scripts/grant_msi_graph_permissions.sh              # uses $CLIENT_ID from env
#   ./scripts/grant_msi_graph_permissions.sh <client-id>  # explicit MSI client id
#
# Requires: az CLI, signed in as a tenant admin (Application Administrator +
# Privileged Role Administrator, or Global Administrator).

set -euo pipefail

CLIENT_ID="${1:-${CLIENT_ID:-}}"
GRAPH_APP_ID="00000003-0000-0000-c000-000000000000"
USER_READ_ALL_ROLE="df021288-bdef-4463-88db-98f22de91432"

if [[ -z "$CLIENT_ID" ]]; then
  echo "Usage: $0 <msi-client-id>" >&2
  echo "  or set CLIENT_ID to the App Service BOT_TYPE=UserAssignedMsi client id." >&2
  exit 1
fi

echo "Target Entra app (client id): $CLIENT_ID"
echo "Looking up managed identity service principal..."

MSI_SP_ID="$(az ad sp show --id "$CLIENT_ID" --query id -o tsv)"
GRAPH_SP_ID="$(az ad sp show --id "$GRAPH_APP_ID" --query id -o tsv)"

echo "MSI service principal object id:    $MSI_SP_ID"
echo "Microsoft Graph SP object id:       $GRAPH_SP_ID"

echo "Adding User.Read.All application permission to app registration..."
az ad app permission add \
  --id "$CLIENT_ID" \
  --api "$GRAPH_APP_ID" \
  --api-permissions "${USER_READ_ALL_ROLE}=Role" \
  2>/dev/null || echo "(permission may already be configured on app registration)"

echo "Assigning User.Read.All app role to MSI service principal..."
az rest --method POST \
  --uri "https://graph.microsoft.com/v1.0/servicePrincipals/${GRAPH_SP_ID}/appRoleAssignedTo" \
  --headers "Content-Type=application/json" \
  --body "{\"principalId\":\"${MSI_SP_ID}\",\"resourceId\":\"${GRAPH_SP_ID}\",\"appRoleId\":\"${USER_READ_ALL_ROLE}\"}" \
  2>/dev/null || echo "(app role assignment may already exist)"

echo "Admin consent for app registration..."
az ad app permission admin-consent --id "$CLIENT_ID"

echo ""
echo "Done. Verify with:"
echo "  CLIENT_ID=$CLIENT_ID BOT_TYPE=UserAssignedMsi python scripts/verify_graph_access.py"
echo "  or restart the App Service and check /health and startup logs."
