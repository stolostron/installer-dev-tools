#!/bin/bash

skopeo_args=""
if [[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]]; then
    echo "Detected MacOS ARM64. Adding skopeo platform override."
    skopeo_args="--override-arch amd64 --override-os linux"
fi

if command -v skopeo &> /dev/null; then
    acm_tags=$(skopeo $skopeo_args inspect docker://quay.io/acm-d/acm-dev-catalog:latest-2.14 | yq -r '.RepoTags | .[] | match("2.14.*-DOWNSTREAM.*") | .string' | tail -2)
    mce_tags=$(skopeo $skopeo_args inspect docker://quay.io/acm-d/mce-dev-catalog:latest-2.9 | yq -r '.RepoTags | .[] | match("2.9.*-DOWNSTREAM.*") | .string' | tail -2)
else
    echo "WARNING: using podman search is unreliable. Please install skopeo for a more reliable tag search"
    acm_tags=$(podman search quay.io/acm-d/acm-dev-catalog --list-tags --limit=100 --format="{{.Tag}}" | grep -F 2.14 | tail -2)
    mce_tags=$(podman search quay.io/acm-d/mce-dev-catalog --list-tags --limit=100 --format="{{.Tag}}" | grep -F 2.9 | tail -2)
fi
# get the most recent two tags

# split the tags to get recent and second recent
previous_acm=$(echo "$acm_tags" | head -1)
previous_mce=$(echo "$mce_tags" | head -1)

current_acm=$(echo "$acm_tags" | tail -1)
current_mce=$(echo "$mce_tags" | tail -1)

recorded_acm=$(cat latest-acm.txt 2>/dev/null)
recorded_mce=$(cat latest-mce.txt 2>/dev/null)

# script output details
echo "-----"
echo "Previous ACM: $previous_acm"
echo "Previous MCE: $previous_mce"
echo ""
echo "Current ACM: $current_acm"
echo "Current MCE: $current_mce"

echo "-----"
echo "Previous recorded ACM: $recorded_acm"
echo "Previous recorded MCE: $recorded_mce"

if [[ "$recorded_acm" != "$current_acm" ]]; then
    echo "🟩 NEW ACM BUILD: $current_acm"
    echo "$current_acm" > latest-acm.txt
fi

if [[ "$recorded_mce" != "$current_mce" ]]; then
    echo "🟩 NEW MCE BUILD: $current_mce"
    echo "$current_mce" > latest-mce.txt
fi

if [[ "$recorded_acm" == "$current_acm" && "$recorded_mce" == "$current_mce" ]]; then
    echo "🟪 No new builds. Exiting."
    exit 0
fi

echo "-----"
# pull the bundles and scrape for information
echo "Pulling $previous_acm"
./konflux-build-status.sh acm-dev-catalog $previous_acm

echo "Pulling $previous_mce"
./konflux-build-status.sh mce-dev-catalog $previous_mce

echo "Pulling $current_acm"
./konflux-build-status.sh acm-dev-catalog $current_acm

echo "Pulling $current_mce"
./konflux-build-status.sh mce-dev-catalog $current_mce

# gather the diffs of the summaries
echo "$previous_acm > $current_acm" > diff-acm.txt
echo "$previous_mce > $current_mce" > diff-mce.txt
diff ./tmp/acm-dev-catalog-$previous_acm-summary.txt ./tmp/acm-dev-catalog-$current_acm-summary.txt --unchanged-line-format= --old-line-format= --new-line-format='%L' | column -t -s' ' >> diff-acm.txt
diff ./tmp/mce-dev-catalog-$previous_mce-summary.txt ./tmp/mce-dev-catalog-$current_mce-summary.txt --unchanged-line-format= --old-line-format= --new-line-format='%L' | column -t -s' ' >> diff-mce.txt

echo ""
echo "---------------------------"
echo " Latest ACM Konflux Builds "
echo "---------------------------"
echo "quay.io/acm-d/acm-dev-catalog:$current_acm"
echo "quay.io/acm-d/mce-dev-catalog:$current_mce"

echo ""
echo "------------"
echo " ACM Images "
echo "------------"
cat ./tmp/acm-dev-catalog-$current_acm-summary.txt | column -t -s' '

echo ""
echo "------------"
echo " MCE Images "
echo "------------"
cat ./tmp/mce-dev-catalog-$current_mce-summary.txt | column -t -s' '

echo ""
echo "----------"
echo " ACM diff "
echo "----------"
cat diff-acm.txt
if [ $(cat diff-acm.txt | wc -l) -eq 1 ]; then echo "(No differences)"; fi

echo ""
echo "----------"
echo " MCE Diff "
echo "----------"
cat diff-mce.txt
if [ $(cat diff-mce.txt | wc -l) -eq 1 ]; then echo "(No differences)"; fi