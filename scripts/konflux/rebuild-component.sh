#!/bin/bash

comps="$1"

for comp in $comps; do
    oc annotate "components/$comp" build.appstudio.openshift.io/request=trigger-pac-build
done

