#!/bin/bash

previous_acm=$(cat latest-acm.txt)
previous_mce=$(cat latest-mce.txt)

current_acm=$(podman search quay.io/acm-d/acm-dev-catalog --list-tags --limit=100 --format="{{.Tag}}" | grep -F 2.14 | tail -1)
current_mce=$(podman search quay.io/acm-d/mce-dev-catalog --list-tags --limit=100 --format="{{.Tag}}" | grep -F 2.9 | tail -1)


./konflux-build-status.sh acm-dev-catalog $current_acm
./konflux-build-status.sh mce-dev-catalog $current_mce

if [[ "$previous_acm" != "$current_acm" ]]; then
    echo "New latest ACM: $current_acm"
    echo "$current_acm" > latest-acm.txt
    diff ./tmp/acm-dev-catalog-$previous_acm-summary.txt ./tmp/acm-dev-catalog-$current_acm-summary.txt --unchanged-line-format= --old-line-format= --new-line-format='%L' > ACM-diff.txt

fi

if [[ "$previous_mce" != "$current_mce" ]]; then
    echo "New latest MCE: $current_mce"
    echo "$current_mce" > latest-mce.txt
    diff ./tmp/mce-dev-catalog-$previous_mce-summary.txt ./tmp/mce-dev-catalog-$current_mce-summary.txt --unchanged-line-format= --old-line-format= --new-line-format='%L' > MCE-diff.txt
fi
