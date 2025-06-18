#!/bin/bash

if [ "$#" -ne 2 ]; then
    echo "Must specificy a catalog image and tag to pull (i.e. acm-dev-catalog latest-2.14)"
    exit 0
fi

img=$1
tag=$2

acm_header="quay.io/acm-d"

# get catalog image from quay.io
mkdir -p ./tmp/$img/$tag
podman pull -q "$acm_header/$img:$tag"
podman save -q $acm_header/$img:$tag -o tmp/$img/$tag.tar 2>/dev/null
tar -xf tmp/$img/$tag.tar -C tmp/$img/$tag

# try to extract the bundles.yaml file. I just run it twice since the bundle will only actually have one of them
find tmp/$img/$tag -type f -name "*.tar" | xargs -I {} tar --transform="s/configs\/advanced-cluster-management\/bundles.yaml/.\/tmp\/$img-$tag-bundles.yaml/" -xf {} configs/advanced-cluster-management/bundles.yaml 2>/dev/null
find tmp/$img/$tag -type f -name "*.tar" | xargs -I {} tar --transform="s/configs\/multicluster-engine\/bundles.yaml/.\/tmp\/$img-$tag-bundles.yaml/" -xf {} configs/multicluster-engine/bundles.yaml 2>/dev/null

# similar to above, try to grab ACM, then MCE and just write to the same file. Only one will actually work
cat ./tmp/$img-$tag-bundles.yaml | yq 'select(.name=="advanced-cluster-management.v2.14*") | .relatedImages | .[] | .name' | sed 's/_/-/g' | sed 's/^$/multiclusterhub-operator/' > ./tmp/$img-$tag-repos.txt
cat ./tmp/$img-$tag-bundles.yaml | yq 'select(.name=="multicluster-engine.v2.9*") | .relatedImages | .[] | .name' | sed 's/_/-/g' | sed 's/^$/multiclusterhub-operator/' >> ./tmp/$img-$tag-repos.txt

# grab the related images
images=$(cat ./tmp/$img-$tag-bundles.yaml | yq 'select(.name=="advanced-cluster-management.v2.14*") | .relatedImages | .[] | .image' | xargs)
images=${images:-"$(cat ./tmp/$img-$tag-bundles.yaml | yq 'select(.name=="multicluster-engine.v2.9*") | .relatedImages | .[] | .image' | xargs)"}

# parse the image for image@sha256:digest and create a file of just image and digest
rm ./tmp/$img-$tag-summary.txt
for image in $images
do
    base=$(basename $image | tr "@:" " ")
    echo $base | awk '{printf ("%s %s\n", $1, $3)}' >> tmp/$img-$tag-summary.txt
done