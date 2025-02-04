#!/bin/bash

helpFunction() {
	echo ""
	echo "Usage: $0 -a REGION -b CLUSTER_NAME -c RESOURCE_GROUP"
	echo -e "\t-n Name of cluster to be deleted"
	echo -e "\t-g Azure resource group where the cluster is located"
	exit 1 # Exit script after printing help
}

while getopts "n:g:" opt; do
	case "$opt" in
	n) CLUSTER_NAME="$OPTARG" ;;
	g) RESOURCE_GROUP="$OPTARG" ;;
	?) helpFunction ;; # Print helpFunction in case parameter is non-existent
	esac
done

# Print helpFunction in case parameters are empty
if [ -z "$CLUSTER_NAME" ] || [ -z "$RESOURCE_GROUP" ]; then
	echo "Some or all of the parameters are empty"
	helpFunction
fi

az login
az aks delete --name "${CLUSTER_NAME}" --resource-group "${RESOURCE_GROUP}"
