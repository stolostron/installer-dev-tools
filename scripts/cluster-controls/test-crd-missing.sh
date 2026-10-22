#!/bin/bash
set -e

MCE_NAME="multiclusterengine"
CRD_MANAGEDCLUSTERADDONS="managedclusteraddons.addon.open-cluster-management.io"
CRD_ADDONDEPLOYMENTCONFIGS="addondeploymentconfigs.addon.open-cluster-management.io"

echo "=== Step 1: Disabling hypershift and hypershift-local-hosting ==="
oc get mce "$MCE_NAME" -o json | \
  jq '.spec.overrides.components |= map(if .name == "hypershift" or .name == "hypershift-local-hosting" then .enabled = false else . end)' | \
  oc apply -f -

echo "=== Step 2: Waiting for MCE to become available again ==="
sleep 10

TIMEOUT=240
ELAPSED=0
while [ $ELAPSED -lt $TIMEOUT ]; do
  STATUS=$(oc get mce "$MCE_NAME" -o jsonpath='{.status.conditions[?(@.type=="Available")].status}' 2>/dev/null || echo "Unknown")
  if [ "$STATUS" == "True" ]; then
    echo "  MCE is available!"
    break
  fi
  echo "  MCE status: $STATUS (waiting... ${ELAPSED}s/${TIMEOUT}s)"
  sleep 5
  ELAPSED=$((ELAPSED + 5))
done

if [ "$STATUS" != "True" ]; then
  echo "  WARNING: MCE did not become available within ${TIMEOUT} seconds, proceeding anyway..."
fi

echo "=== Step 3: Deleting both CRDs (allowing finalizers to complete) ==="
for CRD_NAME in "$CRD_MANAGEDCLUSTERADDONS" "$CRD_ADDONDEPLOYMENTCONFIGS"; do
  echo "  Deleting $CRD_NAME..."
  oc delete crd "$CRD_NAME" 2>/dev/null || echo "  CRD $CRD_NAME already deleted or not found"
done

echo "=== Step 4: Verifying CRDs are gone ==="
for CRD_NAME in "$CRD_MANAGEDCLUSTERADDONS" "$CRD_ADDONDEPLOYMENTCONFIGS"; do
  for i in {1..10}; do
    if ! oc get crd "$CRD_NAME" &>/dev/null; then
      echo "  $CRD_NAME successfully deleted!"
      break
    fi
    echo "  Waiting for $CRD_NAME to be deleted... (attempt $i/10)"
    sleep 1
  done

  if oc get crd "$CRD_NAME" &>/dev/null; then
    echo "  ERROR: $CRD_NAME still exists after 10 seconds"
    exit 1
  fi
done

echo "=== Step 5: Re-enabling hypershift and hypershift-local-hosting ==="
oc get mce "$MCE_NAME" -o json | \
  jq '.spec.overrides.components |= map(if .name == "hypershift" or .name == "hypershift-local-hosting" then .enabled = true else . end)' | \
  oc apply -f -

echo "=== Done! Watch the MCE controller logs for errors ==="
echo "Run: oc logs -n multicluster-engine -l control-plane=backplane-operator -f"
