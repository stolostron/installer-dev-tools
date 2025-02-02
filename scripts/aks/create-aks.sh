#!/bin/bash

helpFunction()
{
   echo ""
   echo "Usage: $0 -a REGION -b CLUSTER_NAME -c RESOURCE_GROUP"
   echo -e "\t-r Azure region"
   echo -e "\t-n Desired name of cluster"
   echo -e "\t-g Azure resource group where the cluster will be placed"
   exit 1 # Exit script after printing help
}

while getopts "r:n:g:" opt
do
   case "$opt" in
      r ) REGION="$OPTARG" ;;
      n ) CLUSTER_NAME="$OPTARG" ;;
      g ) RESOURCE_GROUP="$OPTARG" ;;
      ? ) helpFunction ;; # Print helpFunction in case parameter is non-existent
   esac
done

# Print helpFunction in case parameters are empty
if [ -z "$REGION" ] || [ -z "$CLUSTER_NAME" ] || [ -z "$RESOURCE_GROUP" ]
then
   echo "Some or all of the parameters are empty";
   helpFunction
fi

az login
az group create --name $RESOURCE_GROUP --location $REGION
az aks create --resource-group "${RESOURCE_GROUP}" --name "${CLUSTER_NAME}" --enable-oidc-issuer --generate-ssh-keys
az aks get-credentials --resource-group "${RESOURCE_GROUP}" --name "${CLUSTER_NAME}"
operator-sdk olm install
