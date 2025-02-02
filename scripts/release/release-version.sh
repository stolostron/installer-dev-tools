#!/bin/bash

# Takes the component version and the annotation version and records
# the mismatches to a yaml object
record_version_match_status() {
    local component=$1
    local kind=$2
    local resource=$3
    local component_version=$4
    local annotation_version=$5

    echo "$1 $2 $3 $4 $5 $(version_matches $4 $5)" >> version-matches
}

clear_version_match_file() {
    echo "" > version-matches
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
    local kinds=("deployment" "clusterrole" "clusterrolebinding" \
    "serviceaccount" "policy" "operatorgroup" "subscription" "placementbinding" \
    "placementrule" "role" "rolebinding" "consoleplugin" "prometheusrule" "service" "servicemonitor" \
    "clustermanagementaddon" "configmap" "validatingwebhookconfiguration")

    local acm_version=$(oc get csv -n open-cluster-management -oyaml | yq '.items[0].spec.version')
    local mce_version=$(oc get csv -n multicluster-engine -oyaml | yq '.items[0].spec.version')

    for kind in ${kinds[@]}; do
        local acm_resources=$(oc get $kind -n open-cluster-management | awk 'NR>1 {print $1}')
        local mce_resources=$(oc get $kind -n multicluster-engine | awk 'NR>1 {print $1}')

        for resource in $mce_resources; do
            release_version=$(oc get $kind -n multicluster-engine $resource -oyaml | yq '.metadata.annotations["installer.multicluster.openshift.io/release-version"]')
            echo "--------------------"
            echo "Multicluster Engine"
            echo "$kind: $resource"
            if [[ "$release_version" == "$mce_version" ]]; then
                echo "Release verions match: $release_version"
            else
                echo "Release version mismatch. MCE: $mce_version, Annotation: $release_version"
            fi
            record_version_match_status "mce" "$kind" $resource $mce_version $release_version
        done

        for resource in $acm_resources; do
            release_version=$(oc get $kind -n open-cluster-management $resource -oyaml | yq '.metadata.annotations["installer.open-cluster-management.io/release-version"]')
            echo "--------------------"
            echo "Open Cluster Management"
            echo "$kind: $resource"
            if [[ "$release_version" == "$acm_version" ]]; then
                echo "Release versions match: $release_version"
            else
                echo "Release version mismatch. ACM: $acm_version, Annotation: $release_version"
            fi
            record_version_match_status "acm" "$kind" $resource $acm_version $release_version
        done
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

clear_version_match_file
scan_components
