#!/usr/bin/env bash
# GEAP audit: Agent Runtime control plane — create + list a bare engine.
# Full code deploy (adk deploy agent_engine) is exercised on D4; this proves access.
set -uo pipefail
P=$(gcloud config get-value project)
LOC=us-central1
B="https://$LOC-aiplatform.googleapis.com/v1/projects/$P/locations/$LOC/reasoningEngines"

echo "--- create bare engine ---"
curl -sS -X POST "$B" \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -H "Content-Type: application/json" \
  -d '{"displayName": "gatehouse-audit-engine"}'
echo; echo "--- waiting 20s for the operation ---"; sleep 20

echo "--- list engines ---"
curl -sS "$B" -H "Authorization: Bearer $(gcloud auth print-access-token)"
echo; echo "ENGINE_ID = the number at the end of the 'name' field above"
