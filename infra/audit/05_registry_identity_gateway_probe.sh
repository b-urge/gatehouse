#!/usr/bin/env bash
# GEAP audit probes: Registry, Identity, Gateway CLI surfaces + Observability pointer.
set -uo pipefail
LOC=us-central1
echo "===== gcloud agent-registry ====="
gcloud agent-registry --help 2>&1 | sed -n '1,45p'
echo; echo "===== gcloud agent-identity ====="
gcloud agent-identity --help 2>&1 | sed -n '1,45p'
echo; echo "===== gcloud network-services agent-gateways ====="
gcloud network-services agent-gateways --help 2>&1 | sed -n '1,45p'
echo; echo "===== gateway list (safe read) ====="
gcloud network-services agent-gateways list --location=$LOC 2>&1 | head -6
echo; echo "Observability manual check - open:"
echo "  https://console.cloud.google.com/traces/list?project=$(gcloud config get-value project 2>/dev/null)"
echo "Empty traces != GATED: it likely means the [otel] exporter isn't wired yet (D2 work)."
