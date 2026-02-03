#!/usr/bin/env bash

# Show help if no arguments or -h/--help flag
if [[ $# -eq 0 || "$1" == "-h" || "$1" == "--help" ]]; then
    echo "Usage: $0 [-oyaml] \"<application> <version>\""
    echo ""
    echo "Options:"
    echo "  -oyaml    Output only YAML, suppressing debug information"
    echo ""
    echo "Examples:"
    echo "  $0 \"acm 2.14.2\""
    echo "  $0 \"mce 2.8.4\""
    echo "  $0 -oyaml \"acm 2.14.2\""
    exit 0
fi

# Parse flags
yaml_only=false
args=()
for arg in "$@"; do
    if [[ "$arg" == "-oyaml" ]]; then
        yaml_only=true
    else
        args+=("$arg")
    fi
done

version="${args[0]}"

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

if [[ "$yaml_only" == false ]]; then
    echo "Version: $version"
    echo "X.Y: $xy"
    echo "Application: $application"
    echo "Bundle: $bundle"
    echo "Branch: $branch"
    echo "Config: $config"
    echo "Suffix: $suffix"
    echo "Image Repo: $imagerepo"
fi

issues=$(jira issue list -q "project = 'Red Hat Advanced Cluster Management' AND issuetype in ('Weakness', 'Vulnerability') AND fixVersion = '$version' and status in (closed)" --raw)
echo "$issues" | jq -s \
    --slurpfile config <(curl -s "https://raw.githubusercontent.com/stolostron/$bundle/refs/heads/$branch/config/$config") \
    '
    # Store JIRA issues data
    .[0] as $jira |

    # Store manifest config data
    $config[0] as $configdata |

    # Build a lookup table mapping publish-name to konflux-component-name
    # from the product-images.image-list in the config
    ($configdata."product-images"."image-list" |
        map({(.["publish-name"]): .["konflux-component-name"]}) |
        add
    ) as $lookup |

    # Process each JIRA issue
    $jira |
    map({
        # Extract CVE number from summary (e.g., "CVE-2024-1234")
        key: (.fields.summary | capture("(?<cve>CVE-[0-9]+-[0-9]+)").cve),

        # Extract image component name from summary (e.g., "multicluster-engine/some-component-rhel8")
        component: (.fields.summary | capture("'"$imagerepo"'/(?<img>[^-]+(-[^-]+)*)-rhel[89]").img)
    }) |

    # Map component names using lookup table, try with "-rhel9" suffix if not found,
    # then append the version suffix (e.g., "-mce-28" or "-acm-214")
    map(.component = ($lookup[.component] // $lookup[.component + "-rhel9"] // .component) + "-'"$suffix"'") |

    # Remove duplicates
    unique
    ' | yq -p=json