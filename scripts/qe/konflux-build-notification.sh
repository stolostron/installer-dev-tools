#!/bin/bash

# get the most recent two tags
acm_tags=$(podman search quay.io/acm-d/acm-dev-catalog --list-tags --limit=100 --format="{{.Tag}}" | grep -F 2.14 | tail -2)
mce_tags=$(podman search quay.io/acm-d/mce-dev-catalog --list-tags --limit=100 --format="{{.Tag}}" | grep -F 2.9 | tail -2)

# split the tags to get recent and second recent
previous_acm=$(echo "$acm_tags" | head -1)
previous_mce=$(echo "$mce_tags" | head -1)

current_acm=$(echo "$acm_tags" | tail -1)
current_mce=$(echo "$mce_tags" | tail -1)

recorded_acm=$(cat latest-acm.txt)
recorded_mce=$(cat latest-mce.txt)

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
if [[ "$recorded_acm" != "$current_acm" ]]; then echo "🟩 NEW ACM BUILD: $current_acm"; fi
if [[ "$recorded_mce" != "$current_mce" ]]; then echo "🟩 NEW MCE BUILD: $current_mce"; fi

echo "$current_acm" > latest-acm.txt
echo "$current_mce" > latest-mce.txt

echo "-----"
# pull the bundles and scrape for information
./konflux-build-status.sh acm-dev-catalog $previous_acm
./konflux-build-status.sh mce-dev-catalog $previous_mce


./konflux-build-status.sh acm-dev-catalog $current_acm
./konflux-build-status.sh mce-dev-catalog $current_mce

# gather the diffs of the summaries
echo "$previous_acm > $current_acm" > ACM-diff.txt
echo "$previous_mce > $current_mce" > MCE-diff.txt
diff ./tmp/acm-dev-catalog-$previous_acm-summary.txt ./tmp/acm-dev-catalog-$current_acm-summary.txt --unchanged-line-format= --old-line-format= --new-line-format='%L' >> diff-acm.txt
diff ./tmp/mce-dev-catalog-$previous_mce-summary.txt ./tmp/mce-dev-catalog-$current_mce-summary.txt --unchanged-line-format= --old-line-format= --new-line-format='%L' >> diff-mce.txt