#!/bin/bash

# Get the directory where the script is located
SCRIPT_DIR=$(dirname "$0")
VERSION_MATCH_FILE="${SCRIPT_DIR}/version-matches.csv"

INSTALLER_ACM_ANNOTATION="installer.open-cluster-management.io/release-version"
INSTALLER_MCE_ANNOTATION="installer.multicluster.openshift.io/release-version"

# Takes the component version and the annotation version and records
# the mismatches to a csv object
record_version_match_status() {
    local component=$1
    local kind=$2
    local resource=$3
    local component_version=$4
    local annotation_version=$5

    echo "$1,$2,$3,$4,$5,$(version_matches $4 $5)" >> $VERSION_MATCH_FILE
}

clear_version_match_file() {
    # Check if the file exists before attempting to remove it
    if [[ -f "$VERSION_MATCH_FILE" ]]; then
        echo -e "Removing version match file: '$VERSION_MATCH_FILE'" 
        rm $VERSION_MATCH_FILE
    fi
}

version_matches() {
    local component_version=$1
    local annotation_version=$2
    if [[ "$component_version" == "$annotation_version" ]]; then
        echo "MATCH"
    else
        echo "MISMATCH"
    fi
}

scan_components() {
    local kinds=(
    "addondeploymentconfig" "addontemplate" "apiservice" "clusterrole" 
    "clusterrolebinding" "clustermanagementaddon" "configmap" "consoleclidownload"
    "consoleplugin" "consolequickstart" "consoledownload" "customresourcedefinition"
    "deployment" "managedclustersetbinding" "managedproxyconfiguration" "managedproxyserviceresolver"
    "mutatingwebhookconfiguration" "networkpolicy" "placement" "placementbinding"
    "placementrule" "policy" "policyset" "prometheusrule" "resourcequota"
    "role" "rolebinding" "route" "secret" "service"
    "serviceaccount" "servicemonitor" "statefulset" "subscription"
    "validatingwebhookconfiguration" "verticalpodautoscaler"
)

    # Fetch ACM and MCE versions and namespaces in parallel
    local acm_version mce_version acm_namespace mce_namespace
    acm_version=$(oc get csv -n open-cluster-management -oyaml | yq '.items[0].spec.version')
    mce_version=$(oc get csv -n multicluster-engine -oyaml | yq '.items[0].spec.version')
    acm_namespace=$(oc get mch -A -o json | jq -r '.items[0].metadata.namespace')
    mce_namespace=$(oc get mce -o json | jq -r '.items[0].spec.targetNamespace')

    echo "======================================="
    echo "ACM and MCE Version Information"
    echo "======================================="
    printf "ACM Version:            %s\n" "$acm_version"
    printf "ACM Namespace:          %s\n\n" "$acm_namespace"
    printf "MCE Version:            %s\n" "$mce_version"
    printf "MCE Target Namespace:   %s\n" "$mce_namespace"
    echo "======================================="

    # Check if the namespaces are set
    if [[ -z "$acm_namespace" || -z "$mce_namespace" ]]; then
        echo "Error: ACM or MCE namespace is missing. Exiting."
        exit 1
    fi

    # Run resource fetch and version check in parallel for ACM and MCE
    for kind in ${kinds[@]}; do
        {
            # Fetch ACM resources for this kind and filter by annotation
            acm_resources=$(oc get $kind -n $acm_namespace -o json | jq -r --arg annotation "$INSTALLER_ACM_ANNOTATION" '.items[] | select(.metadata.annotations[$annotation] != null) | .metadata.name')

            # Fetch MCE resources for this kind and filter by annotation
            mce_resources=$(oc get $kind -n $mce_namespace -o json | jq -r --arg annotation "$INSTALLER_MCE_ANNOTATION" '.items[] | select(.metadata.annotations[$annotation] != null) | .metadata.name')
            
            # Check and compare resources for MCE
            for resource in $mce_resources; do
                release_version=$(oc get $kind -n $mce_namespace $resource -o yaml | yq eval ".metadata.annotations[\"$INSTALLER_MCE_ANNOTATION\"]" -)
                echo "--------------------"
                echo "Multicluster Engine (MCE)"
                echo "$kind: $resource"
                if [[ "$release_version" == "$mce_version" ]]; then
                    echo "Release versions match: $release_version"
                else
                    echo "Release version mismatch. MCE: $mce_version, Annotation: $release_version"
                fi
                record_version_match_status "mce" "$kind" $resource $mce_version $release_version
            done

            # Check and compare resources for ACM
            for resource in $acm_resources; do
                release_version=$(oc get $kind -n $mce_namespace $resource -o yaml | yq eval ".metadata.annotations[\"$INSTALLER_ACM_ANNOTATION\"]" -)
                echo "--------------------"
                echo "Advanced Cluster Management (ACM)"
                echo "$kind: $resource"
                if [[ "$release_version" == "$acm_version" ]]; then
                    echo "Release versions match: $release_version"
                else
                    echo "Release version mismatch. ACM: $acm_version, Annotation: $release_version"
                fi
                record_version_match_status "acm" "$kind" $resource $acm_version $release_version
            done
        }
    done
}

compare_versions() {
    local operator_version=$1
    local component_version=$2
    if [[ "$component_version" == "$operator_version" ]]; then
        true
    else
        false
    fi
}

# Start time tracking
START_TIME=$(date +%s)

clear_version_match_file
scan_components

# End time tracking
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

# Display how long the script took to run
echo "======================================="
echo "Script ran in $DURATION seconds."
echo "======================================="
