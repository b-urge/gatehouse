#!/usr/bin/env bash
# Reproducible API enablement for gatehouse-hackathon (D1).
set -euo pipefail
gcloud services enable \
  aiplatform.googleapis.com \
  run.googleapis.com \
  firestore.googleapis.com \
  pubsub.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com
# GEAP audit item — Model Armor (log result in GEAP-AUDIT.md):
gcloud services enable modelarmor.googleapis.com || echo "Model Armor enable failed -> log as GATED/UNKNOWN"
# One-time, region is permanent:
gcloud firestore databases create --location=us-central1 || echo "Firestore db already exists"
