#!/bin/bash

CATALOGS="acm-redhat-operators
mce-redhat-operators"

if [ -n "$1" ]; then
	CATALOGS="$1"
fi

cd /tmp
rm -rf /tmp/acm-mce-operator-catalogs
git clone https://github.com/stolostron/acm-mce-operator-catalogs.git
cd acm-mce-operator-catalogs

update=`date`
for branch in $CATALOGS; do
	git checkout $branch
	git pull
	catalog=`echo "$branch" | awk -F- '{print $1}'`
	newbranch="${catalog}-refresh-$$"
	git checkout -b "$newbranch"
	cat <<< $(yq -y ".\"request-time\" = \"$update\"" catalog-request.yaml) > catalog-request.yaml
	git commit -a -m "Refresh the catalog build for $catalog"
	echo "Run: git push origin $newbranch"
	git push origin "$newbranch"
done

cd /tmp
rm -rf /tmp/acm-mce-operator-catalogs
