#!/usr/bin/env bash
# D4: wire the event to the fleet — deploy dispatcher, point a push
# subscription at it, then fire one real end-to-end run through intake.
# Usage: bash infra/wire_dispatch.sh <FLEET_ENGINE_ID>
set -uo pipefail
ENGINE_ID="${1:?usage: bash infra/wire_dispatch.sh <FLEET_ENGINE_ID>}"
P=$(gcloud config get-value project)
REGION=us-central1
TOPIC=vendor-docs-received

echo "--- deploy dispatcher (buildpack; ~2-4 min) ---"
gcloud run deploy gatehouse-dispatch \
  --source services/dispatcher \
  --region $REGION \
  --allow-unauthenticated \
  --timeout 600 \
  --set-env-vars GOOGLE_CLOUD_PROJECT=$P,ENGINE_ID=$ENGINE_ID,ENGINE_LOCATION=$REGION

DURL=$(gcloud run services describe gatehouse-dispatch --region $REGION --format="value(status.url)")
echo "dispatcher URL: $DURL"

echo "--- push subscription -> dispatcher (600s ack for the fleet's runtime) ---"
gcloud pubsub subscriptions create ${TOPIC}-dispatch \
  --topic=$TOPIC --push-endpoint="$DURL/push" --ack-deadline=600 2>/dev/null \
  || gcloud pubsub subscriptions update ${TOPIC}-dispatch --push-endpoint="$DURL/push" --ack-deadline=600

echo "--- end to end: one clean doc through the front door ---"
IURL=$(gcloud run services describe gatehouse-intake --region $REGION --format="value(status.url)")
curl -sS -X POST "$IURL/intake" -H "Content-Type: application/json" -d '{
  "vendor_id": "acme-saas-inc",
  "doc_id": "e2e-kickoff",
  "text": "Acme SOC 2 update: attestation renewed; MFA rollout to the legacy tier is scheduled."
}'; echo
echo
echo "The fleet is now running asynchronously (2-3 min). Watch it:"
echo "  gcloud run services logs read gatehouse-dispatch --region $REGION --limit 30"
echo "Success = a 'dispatch: Review vendor acme-saas-inc' line followed later by 'fleet done: events=N'."
