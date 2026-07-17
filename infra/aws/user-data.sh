#!/bin/bash
# EC2 cloud-init bootstrap: Docker + a swap file.
#
# Passed via `aws ec2 run-instances --user-data file://infra/aws/user-data.sh`.
# t3.micro/t3.small only have 1-2GB RAM; the scraper's geopandas/pandas step
# and the Docker build (g++, libgdal-dev) need more headroom than that alone.
set -euo pipefail

# --- Docker (official repo, includes the compose plugin) ---
apt-get update
apt-get install -y ca-certificates curl git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker ubuntu

# --- 2G swap ---
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab

# Marker the deploy runbook polls for over SSH to know bootstrap is done.
touch /var/lib/cloud/instance/bootstrap-done
