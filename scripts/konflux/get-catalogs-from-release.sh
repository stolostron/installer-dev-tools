#!/bin/bash

RELEASE="$1"

if  [ -z "$RELEASE" ]; then
	echo "Usage: get-catalogs-from-release.sh <releaseName> ..."
	exit 1
fi

set -o pipefail
status=0
for rel in "$@"; do
   oc get release "$rel" -o yaml | yq '.status.artifacts.components | .[] | .ocp_version +": "+ .index_image' || status=1
done
exit "$status"
