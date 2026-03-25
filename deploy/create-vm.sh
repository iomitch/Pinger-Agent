#!/bin/bash
#
# Deploy a Pinger Agent VM to Azure
#
# Usage:
#   ./create-vm.sh <location> <agent-name> <api-key> [server-url]
#
# Examples:
#   ./create-vm.sh eastus pinger-vm-eastus pk_abc123
#   ./create-vm.sh westeurope pinger-vm-westeurope pk_def456 https://pinger.ionsoft.io
#

set -euo pipefail

LOCATION="${1:?Usage: $0 <location> <agent-name> <api-key> [server-url]}"
AGENT_NAME="${2:?Usage: $0 <location> <agent-name> <api-key> [server-url]}"
API_KEY="${3:?Usage: $0 <location> <agent-name> <api-key> [server-url]}"
SERVER_URL="${4:-https://pinger.ionsoft.io}"
RESOURCE_GROUP="${RESOURCE_GROUP:-TOOLS-RG}"
VM_SIZE="${VM_SIZE:-Standard_B1s}"
ADMIN_USER="pinger"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLOUD_INIT="$SCRIPT_DIR/cloud-init.yml"

if [ ! -f "$CLOUD_INIT" ]; then
  echo "Error: cloud-init.yml not found at $CLOUD_INIT"
  exit 1
fi

# Generate customized cloud-init with actual values
TEMP_INIT=$(mktemp)
sed -e "s|__SERVER_URL__|${SERVER_URL}|g" \
    -e "s|__API_KEY__|${API_KEY}|g" \
    "$CLOUD_INIT" > "$TEMP_INIT"

echo "Creating VM '$AGENT_NAME' in $LOCATION ($VM_SIZE)..."

az vm create \
  --name "$AGENT_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --image Debian:debian-12:12:latest \
  --size "$VM_SIZE" \
  --admin-username "$ADMIN_USER" \
  --generate-ssh-keys \
  --public-ip-sku Standard \
  --custom-data "$TEMP_INIT" \
  --output table

rm -f "$TEMP_INIT"

echo ""
echo "VM created. The agent will be ready in ~3-5 minutes (installing Docker + building image)."
echo ""
echo "To check status:"
echo "  ssh $ADMIN_USER@\$(az vm show -g $RESOURCE_GROUP -n $AGENT_NAME --show-details --query publicIps -o tsv)"
echo "  sudo docker logs -f pinger-agent"
echo ""
echo "Auto-update: checks for repo changes every 5 minutes via cron."
echo "Update log:  /var/log/pinger-agent-update.log"
