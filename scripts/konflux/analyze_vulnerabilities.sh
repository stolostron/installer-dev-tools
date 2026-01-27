#!/bin/bash

if [ -z "$1" ]; then
	echo "Usage: analyze_vulnerabilities.sh <csv-filename>"
	exit 1
fi

FILENAME="$1"
if [ ! -f "$FILENAME" ]; then
	echo "The csv file containing vulnerability data does not exist"
	exit 1
fi

awk -F',' 'NR>1 && ($5=="high" || $5=="critical") {print $1}' "$FILENAME" | sort | uniq -c | sort -rn
