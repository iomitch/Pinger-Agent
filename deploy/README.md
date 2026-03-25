# Deploying Pinger Agent VMs

## Prerequisites

1. Azure CLI (`az`) authenticated
2. The Pinger-Agent repo must be **public** (or add a deploy key)
3. Register the agent in Pinger Admin → Ping Hosts → Add, copy the API key

## Deploy a new VM

```bash
# Register agent in admin panel first, then:
./create-vm.sh <location> <vm-name> <api-key>

# Examples:
./create-vm.sh eastus    pinger-vm-eastus    pk_your_key_here
./create-vm.sh westeurope pinger-vm-westeu   pk_your_key_here
./create-vm.sh southeastasia pinger-vm-sea   pk_your_key_here
```

## What it creates

- Debian 12 B1s VM (~$3.80/mo)
- Docker installed and running
- Pinger Agent container with ICMP ping + traceroute
- Auto-update cron job every 5 minutes

## Managing

```bash
# SSH into the VM
ssh pinger@<vm-ip>

# Check agent logs
sudo docker logs -f pinger-agent

# Check auto-update log
sudo tail -f /var/log/pinger-agent-update.log

# Force update now
sudo /opt/pinger-agent/update.sh
```

## Tear down

```bash
az vm delete --name pinger-vm-eastus --resource-group TOOLS-RG --yes
az network public-ip delete --name pinger-vm-eastusPublicIP --resource-group TOOLS-RG
```
