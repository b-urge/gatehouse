#!/usr/bin/env bash
# D4: deploy the review fleet to Agent Engine (Agent Runtime).
# The repo-root packages the fleet imports are staged via --extra_packages.
# First deploy builds an image: expect 5-10 minutes. Answer y to any prompts.
set -uo pipefail
P=$(gcloud config get-value project)
REGION=us-central1

adk deploy agent_engine \
  --project "$P" \
  --region "$REGION" \
  --display_name "gatehouse-review-fleet" \
  --otel_to_cloud \
  --extra_packages contracts \
  --extra_packages retrieval \
  --extra_packages actions \
  --extra_packages ledger \
  agents/review_fleet

echo
echo "Deploy finished. Find the new engine id (the fleet one, not the D1 audit engine):"
curl -sS "https://$REGION-aiplatform.googleapis.com/v1/projects/$P/locations/$REGION/reasoningEngines" \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  | python3 -c "import json,sys; [print(e['name'].split('/')[-1], '-', e.get('displayName','')) for e in json.load(sys.stdin).get('reasoningEngines',[])]"
echo
echo "Next: bash infra/wire_dispatch.sh <FLEET_ENGINE_ID>"
