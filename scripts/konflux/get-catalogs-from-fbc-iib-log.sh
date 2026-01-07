#!/bin/bash

logfile="$1"

if [ -z "$logfile" ]; then
	echo "Error: command <logfile>"
	exit 1
fi

#grep -A1 "Updated fromIndex for next batch:" managed-p6tz9-add-fbc-contribution-to-index-image-mce27.log |grep -v '^-' |  awk 'NR % 2 == 0 { print $NF ": " val } { val = $6 }'

# TODO Display a header

grep -A1 "Updated fromIndex for next batch:" "$logfile" | grep -v '^-' | awk 'NR % 2 == 0 { print $NF ": " val } { val = $6 }'


