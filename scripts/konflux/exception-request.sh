#!/bin/bash

SNAPSHOT="$1"
if [ -z "$SNAPSHOT" ]; then
	echo "Error: snapshot not provided"
	echo "Usage: exception-request.sh <snapshot-yaml-file>"
	exit 1
fi

if [ ! -f "$SNAPSHOT" ]; then
	echo "Error: snapshot file does not exist"
	echo "Usage: exception-request.sh <snapshot-yaml-file>"
	exit 1
fi

app=`cat "$SNAPSHOT" | yq -r .metadata.name | awk -F- '{print $2 "-" $3}'`
if [ -z "$app" ]; then
	echo "Error: could not determine the snapshot type from the name, mce or acm"
	echo "Usage: exception-request.sh <snapshot-yaml-file>"
	exit 1
fi
	

for entry in `cat "$SNAPSHOT" | yq -r .spec.components[].containerImage`; do
       echo "- value: 'schedule.weekday_restriction'"
       listdigest=`echo "$entry" | sed "s/.*${app}.//"`
       echo "  imageRef: $listdigest"
       for digest in `skopeo inspect --raw --no-tags docker://$entry | jq -r '.manifests[].digest'`; do
		echo "- value: 'schedule.weekday_restriction'"
		echo "  imageRef: $digest"
	done
done
