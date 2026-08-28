#!/usr/bin/env bash
# Phase 2 wiring: vendor-approved topic -> dispatcher /approved -> enablement engine.
# Redeploys the dispatcher with approval + enablement config, then fires one
# end-to-end lifecycle doc through the front door.
# Usage: bash infra/wire_approved.sh <ENABLEMENT_ENGINE_ID>
set -uo pipefail
EN_ID="${1:?usage: bash infra/wire_approved.sh <ENABLEMENT_ENGINE_ID>}"
P=$(gcloud config get-value project)
REGION=us-central1
FLEET_ID=$(gcloud run services describe gatehouse-dispatch --region $REGION \
  --format="value(spec.template.spec.containers[0].env)" | tr ';' '\n' | grep -A0 "ENGINE_ID" \
  | head -1 | sed "s/.*'value': '\([0-9]*\)'.*/\1/")
FLEET_ID=${FLEET_ID:-3060061256623849472}
TOPIC=vendor-approved

echo "--- topic + debug sub (idempotent) ---"
gcloud pubsub topics create $TOPIC 2>/dev/null || echo "topic exists"
gcloud pubsub subscriptions create ${TOPIC}-debug --topic=$TOPIC 2>/dev/null || echo "sub exists"

echo "--- redeploy dispatcher with approval + enablement config (~2-4 min) ---"
gcloud run deploy gatehouse-dispatch \
  --source services/dispatcher \
  --region $REGION \
  --allow-unauthenticated \
  --timeout 600 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$P,ENGINE_ID=$FLEET_ID,ENGINE_LOCATION=$REGION,ENABLEMENT_ENGINE_ID=$EN_ID,APPROVED_TOPIC=$TOPIC,APPROVAL_THRESHOLD=0.7"

DURL=$(gcloud run services describe gatehouse-dispatch --region $REGION --format="value(status.url)")
echo "--- approved push subscription -> dispatcher /approved (600s ack) ---"
gcloud pubsub subscriptions create ${TOPIC}-enable \
  --topic=$TOPIC --push-endpoint="$DURL/approved" --ack-deadline=600 2>/dev/null \
  || gcloud pubsub subscriptions update ${TOPIC}-enable --push-endpoint="$DURL/approved" --ack-deadline=600

echo "--- LIFECYCLE E2E: one clean doc through the front door ---"
IURL=$(gcloud run services describe gatehouse-intake --region $REGION --format="value(status.url)")
curl -sS -X POST "$IURL/intake" -H "Content-Type: application/json" -d '{
  "vendor_id": "acme-saas-inc",
  "doc_id": "lifecycle-e2e",
  "text": "Acme SOC 2 update: attestation renewed; MFA rollout to the legacy tier is scheduled."
}'; echo
echo
echo "Now running: intake -> review fleet -> approval -> vendor-approved -> enablement."
echo "Full lifecycle takes ~4-6 min. Watch:"
echo "  gcloud run services logs read gatehouse-dispatch --region $REGION --limit 40"
echo "Success reads, in order: 'fleet done' -> 'approval: APPROVED ... published' ->"
echo "'enable: Vendor acme-saas-inc approved' -> 'enablement done: events=N'."
echo "Receipts land in Firestore: provisioning_tickets, training_modules, comms_drafts."
