#!/usr/bin/env bash
# Phase 2: deploy the enablement agent to Agent Engine.
# First build ~5-10 min. Ends by listing engines: grab the gatehouse-enablement id.
set -uo pipefail
P=$(gcloud config get-value project)
REGION=us-central1

adk deploy agent_engine \
  --project "$P" \
  --region "$REGION" \
  --display_name "gatehouse-enablement" \
  --otel_to_cloud \
  --extra_packages contracts \
  --extra_packages retrieval \
  --extra_packages actions \
  --extra_packages ledger \
  --extra_packages memorybank \
  agents/enablement

echo; echo "Engines now:"
curl -sS "https://$REGION-aiplatform.googleapis.com/v1/projects/$P/locations/$REGION/reasoningEngines" \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  | python3 -c "import json,sys; [print(e['name'].split('/')[-1], '-', e.get('displayName','')) for e in json.load(sys.stdin).get('reasoningEngines',[])]"
echo; echo "Next: bash infra/wire_approved.sh <ENABLEMENT_ENGINE_ID>"
