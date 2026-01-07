#!/bin/bash

RELEASE="$1"

if  [ -z "$RELEASE" ]; then
	echo "Usage: get-catalogs-from-release.sh <releaseName>"
	exit 1
fi

oc get release "$RELEASE" -o yaml | yq '.status.artifacts.components' | jq -r '.[] | .ocp_version +": "+ .index_image'

