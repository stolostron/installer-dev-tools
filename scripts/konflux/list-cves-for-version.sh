#!/usr/bin/env bash

# Show help if no arguments or -h/--help flag
if [[ $# -eq 0 || "$1" == "-h" || "$1" == "--help" ]]; then
    echo "Usage: $0 \"<application> <version>\""
    echo ""
    echo "Examples:"
    echo "  $0 \"acm 2.14.2\""
    echo "  $0 \"mce 2.8.4\""
    exit 0
fi


version="$1"

xy="$(echo "$version" | awk -F'[ .]' '{print $2"."$3}')"
application="${version%% *}"
bundle="$application-operator-bundle"
case "$application" in
    "acm")
        branch="release-$xy"
        ;;
    "mce")
        branch="backplane-$xy"
        ;;
esac
config="$application-manifest-gen-config.json"
suffix="$application-${xy//./}"

echo "Version: $version"
echo "X.Y: $xy"
echo "Application: $application"
echo "Bundle: $bundle"
echo "Branch: $branch"
echo "Config: $config"
echo "Suffix: $suffix"

case "$application" in
    "acm")
        imagerepo="rhacm2"
        ;;
    "mce")
        imagerepo="multicluster-engine"
        ;;
    *)
        echo "Unknown Repo"
        exit 1
        ;;
esac

echo "Image Repo: $imagerepo"

issues=$(jira issue list -q "project = 'Red Hat Advanced Cluster Management' AND issuetype in ('Weakness', 'Vulnerability') AND fixVersion = '$version' and status in (closed)" --raw)
echo "$issues" | jq -s --slurpfile config <(curl -s https://raw.githubusercontent.com/stolostron/$bundle/refs/heads/$branch/config/$config) '.[0] as $jira | $config[0] as $mceconfig |($mceconfig."product-images"."image-list" | map({(.["publish-name"]): .["konflux-component-name"]}) | add) as $lookup | $jira | map({key: (.fields.summary | capture("(?<cve>CVE-[0-9]+-[0-9]+)").cve),component: (.fields.summary | capture("'"$imagerepo"'/(?<img>[^-]+(-[^-]+)*)-rhel[89]").img)}) | map(.component = ($lookup[.component] // $lookup[.component + "-rhel9"] // .component) + "-'"$suffix"'") | unique' | yq -p=json