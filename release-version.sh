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

version_matches() {
    local component_version=$1
    local annotation_version=$2
    if [[ "$component_version" == "$annotation_version" ]]; then
        echo "MATCH"
    else
        echo "MISMATCH"
    fi
}

acm_version=$(oc get csv -n open-cluster-management -oyaml | yq '.items[0].spec.version')
mce_version=$(oc get csv -n multicluster-engine -oyaml | yq '.items[0].spec.version')
echo "" > version-matches

acm_deployments=$(oc get deployments -n open-cluster-management | awk 'NR>1 {print $1}')
mce_deployments=$(oc get deployments -n multicluster-engine | awk 'NR>1 {print $1}')

for deployment in $mce_deployments; do
    release_version=$(oc get deployment -n multicluster-engine $deployment -oyaml | yq '.metadata.annotations["installer.multicluster.openshift.io/release-version"]')
    echo "--------------------"
    echo "Multicluster Engine"
    echo "Deployment: $deployment"
    if [[ "$release_version" == "$mce_version" ]]; then
        echo "Release verions match: $release_version"
    else
        echo "Release version mismatch. MCE: $mce_version, Annotation: $release_version"
    fi
    record_version_match_status "mce" "deployment" $deployment $mce_version $release_version
done

for deployment in $acm_deployments; do
    release_version=$(oc get deployment -n open-cluster-management $deployment -oyaml | yq '.metadata.annotations["installer.open-cluster-management.io/release-version"]')
    echo "--------------------"
    echo "Open Cluster Management"
    echo "Deployment: $deployment"
    if [[ "$release_version" == "$acm_version" ]]; then
        echo "Release versions match: $release_version"
    else
        echo "Release version mismatch. MCE: $mce_version, Annotation: $release_version"
    fi
    record_version_match_status "acm" "deployment" $deployment $mce_version $release_version
done
