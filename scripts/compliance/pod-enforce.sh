#!/bin/bash

# Enforce the compliance specififed by SCC V2 upon the pods to see which ones break

#    securityContext:
#      allowPrivilegeEscalation: false
#      readOnlyRootFilesystem: true
#      capabilities:
#        drop:             # Check that capabilities.drop has the single entry ALL
#        - ALL
#      privileged: false

output_yaml="enforce.yaml"

function join_by {
	local IFS="$1"
	shift
	echo "$*"
}

# try searching for a deployment first, then stateful set
function try_find_deployment {
	local namespace=$1
	local pod=$2

	# split the podname by '-' and pop the last two tokens off
	IFS='-' read -ra tokens <<<"$pod"
	unset tokens[-1]
	unset tokens[-1]

	# re-join the remaining tokens into the proposed deployment name and search
	local deployment=$(join_by "-" ${tokens[@]})
	local notfound=$(oc get deployment $deployment -n $namespace 2>&1 | grep "NotFound")
	if [[ -z $notfound ]]; then
		echo "Deployment found: $deployment"
		yq -i ".$namespace.\"deployments\"+=[\"$deployment\"]" $output_yaml
	else
		echo "No Deployment found for: $deployment"
		try_find_statefulset $namespace $pod
	fi
}

# search for stateful set
function try_find_statefulset {
	local namespace=$1
	local pod=$2

	# split the podname by '-' and pop the last token off
	IFS='-' read -ra tokens <<<"$pod"
	unset tokens[-1]

	local statefulset=$(join_by "-" ${tokens[@]})
	local notfound=$(oc get statefulset $statefulset -n $namespace 2>&1 | grep "NotFound")
	if [[ -z $notfound ]]; then
		echo "StatefulSet found: $statefulset"
		yq -i ".$namespace.\"statefulsets\"+=[\"$statefulset\"]" $output_yaml
	else
		echo "No StatefulSet found for: $statefulset"
		try_find_job $namespace $pod
	fi
}

function try_find_job {
	local namespace=$1
	local pod=$2

	# split the podname by '-' and pop the last token off
	IFS='-' read -ra tokens <<<"$pod"
	unset tokens[-1]

	local job=$(join_by "-" ${tokens[@]})
	local notfound=$(oc get job $job -n $namespace 2>&1 | grep "NotFound")
	if [[ -z $notfound ]]; then
		echo "Job found: $job"
		yq -i ".$namespace.\"jobs\"+=[\"$job\"]" $output_yaml
	else
		echo "No Jobs found for: $job"
		yq -i ".$namespace.\"unknown\"+=[\"$job\"]" $output_yaml
	fi
}

function try_find_owners {
	# Look for Deployments and StatefulSets
	# get list of namespaces
	local namespaces=$(yq "keys | .[]" -oy <lint.yaml)

	for name in $namespaces; do
		pods=$(yq ".$name | keys | .[]" <lint.yaml)
		echo -e "--------------------"
		echo "Namespace: $name"
		echo
		echo "Non-compliant pods:"
		echo "$pods"

		for pod in $pods; do
			try_find_deployment $name $pod
		done
	done
}

function try_add_security_context {
	local namespace=$1
	local deployment=$2
	local container=$3
	local type=$4
	local security_context=$(oc get $type -n $namespace $deployment -o jsonpath="{.spec.template.spec.containers}" | yq ".[$container] | .securityContext")
	if [[ $security_context == "null" ]]; then
		oc patch $type -n $namespace $deployment --type='json' -p="[{\"op\": \"add\", \"path\": \"/spec/template/spec/containers/$container/securityContext\", \"value\":{}}]"
	fi
}

function patch_owner {
	local namespace=$1
	local deployment=$2
	local type=$3
	echo "--------------------"
	local num_containers=$(oc get $type -n $namespace $deployment -o jsonpath="{.spec.template.spec.containers}" | yq 'length')

	for ((ind = 0; ind < $num_containers; ind++)); do
		echo "Patching $namespace : $deployment : [$ind]"
		try_add_security_context $namespace $deployment $ind $type
		# patch privileged:false
		echo "privileged:false"
		oc patch $type -n $namespace $deployment --type='json' -p="[{\"op\": \"add\", \"path\": \"/spec/template/spec/containers/$ind/securityContext/privileged\", \"value\":false}]"

		# patch readOnlyRootFilesystem:true
		echo "readOnlyRootFilesystem:true"
		oc patch $type -n $namespace $deployment --type='json' -p="[{\"op\": \"add\", \"path\": \"/spec/template/spec/containers/$ind/securityContext/readOnlyRootFilesystem\", \"value\":true}]"
	done
}

function patch_owners {
	local namespaces=$(yq "keys | .[]" -oy <enforce.yaml)
	for namespace in $namespaces; do
		local deployments=$(yq ".$namespace.deployments | .[]" -oy <enforce.yaml)
		for deployment in $deployments; do
			patch_owner $namespace $deployment "deployment"
		done

		local statefulsets=$(yq ".$namespace.statefulsets | .[]" -oy <enforce.yaml)
		for ss in $statefulsets; do
			patch_owner $namespace $ss "statefulset"
		done

		local jobs=$(yq ".$namespace.jobs | .[]" -oy <enforce.yaml)
		for job in $jobs; do
			patch_owner $namespace $ss "job"
		done
	done
}

function pause_mch {
	echo "Pausing MCH"
	oc annotate mch multiclusterhub -n open-cluster-management mch-pause=true
}

function unpause_mch {
	echo "Unpausing MCH"
	oc annotate mch multiclusterhub -n open-cluster-management mch-pause-
}

function enforce {
	echo "" >$output_yaml
	try_find_owners

	pause_mch
	patch_owners
}

enforce
