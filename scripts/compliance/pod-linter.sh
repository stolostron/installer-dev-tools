#!/bin/bash
#
# Copyright (c) 2023 Red Hat, Inc.
#
# A WORK IN PROGRESS.
#
# A "linter" for check conformance to ACM/MCE pod configuraiton "standards".
#
# This script scans an OCP cluster that has ACM and/or MCE installed, and
# analyzes the configuraiton of each pod found in a non-Openshift namespace,
# assessing against of series of checks representing the conventions we are
# driving towards for all pods.   It emits info on each non-conformance found.
#
# The checks are encoded in a series of check_* functions.

# Assumes:
# - oc cluster authentication is available (via oc login, KUBECONFIG, service account, etc.)
#
# Needs:
# - oc
# - jq
# - yq
# - Std utils: cat, cp, mkdir, mktemp, sort

me=$(basename $0)
my_dir=$(dirname $(readlink -f $0))

# Create temp dir, make sure it gets cleaned up on any exit.

function cleanup {
	if [[ -n "$tmp_dir" ]]; then
		rm -rr "$tmp_dir"
	fi
}
trap cleanup EXIT
tmp_dir=$(mktemp -d -t "$me.XXXXXXXX")

# Message emitting...

pod_id=""
pod_namespace=""
pod_id_blurted=0
pod_non_conformances_found=0

blurt_pod_complaint=0
blurt_pod_ok_msgs=0
blurt_ns_progress_msgs=1

output_yaml="lint.yaml"

function blurt_ns_progress_msg() {
	if [[ $blurt_ns_progress_msgs -ne 0 ]]; then
		echo "$@"
	fi
}

# output conformity in a yaml file
# namespace pod container context desired_state actual_state
function append_yaml() {
	if [[ ! -z $output_yaml ]]; then
		if [[ -z $(cat $output_yaml 2>/dev/null) ]]; then touch $output_yaml; fi
		yq -i ".$1.$2.$3.$4.desired=\"$5\" | .$1.$2.$3.$4.actual=\"$6\"" $output_yaml
	fi
}

function set_pod_id() {
	pod_id="$1"
	pod_id_blurted=0
	pod_non_conformances_found=0
}

function set_pod_namespace() {
	pod_namespace="$1"
}

function blurt_pod_header() {
	if [[ $pod_id_blurted -eq 0 ]]; then
		echo ""
		echo "Analyzing pod $pod_id/$pod_namespace..."
		pod_id_blurted=1
	fi
}

function register_complaint() {
	pod_non_conformances_found=1
	if [[ $blurt_pod_complaint -ne 0 ]]; then
		blurt_pod_header
		echo "   Non-Conformance: $@"
	fi
}

function blurt_pod_ok() {
	if [[ $blurt_pod_ok_msgs -eq 0 ]]; then
		return
	fi
	blurt_pod_header
	echo "   Ok: $@"
}

# These varaibles are q auick hack to control what is checked for.  We probably
# need a mechanism by which each check is given some name and they can be turned on
# or off by name uinsg invocation args.

do_check_for_restricted_scc=1                 # Check if pod qualifies for restricted-v2 SCC
do_check_security_context=1                   # Check security context settings
do_check_security_context_read_only_root_fs=1 # Check for running with read-only filesystem
do_check_for_pod_anti_affinity=0              # Check pod anti-affinity specifications...
do_check_for_hard_anti_affinity=0             # ...if checking, look for hard antiaffinity.
do_check_for_hard_anti_affinity_only=0        # ...if checking, check for that only (special use case).

# TEMP config checks that we want on:
do_check_security_context=1

function check_for_restricted_scc() {

	# Check  that the pod qualifies for the restricted-v2 SCC.

	if [[ $do_check_for_restricted_scc -eq 0 ]]; then
		return 0
	fi

	local pod_metadata_json="$1"

	local pod_scc=$(jq -r '.annotations["openshift.io/scc"]' <<<"$pod_metadata_json")
	if [[ "$pod_scc" != "restricted-v2" ]]; then
		register_complaint "Pod is running with the $pod_scc SCC."
		return 1
	else
		blurt_pod_ok "Pod is running with the restricted-v2 SCC."
		return 0
	fi
}

function check_for_pod_anti_affinity() {

	# Check that the pod has "soft" pod anti-affinity terms that repel other replicas
	# based  on the topology.kubernetes.io/zone and kubernetes.io/hostname topology keys.

	if [[ $do_check_for_pod_anti_affinity -eq 0 ]]; then
		return 0
	fi

	local pod_spec_json="$1"
	local has_non_conformances=0

	local pod_affinity=$(jq -c '.affinity.podAntiAffinity' <<<"$pod_spec_json")

	if [[ $do_check_for_hard_anti_affinity -ne 0 ]]; then
		if [[ "$pod_affinity" != "null" ]]; then
			local hard_pod_aa_terms=$(jq -c '.requiredDuringSchedulingIgnoredDuringExecution' <<<"$pod_affinity")
			if [[ "$hard_pod_aa_terms" != "null" ]]; then
				register_complaint "Pod specifies \"hard\" pod anti-affinity."
				has_non_conformances=1
			fi
		fi
		if [[ $do_check_for_hard_anti_affinity_only -ne 0 ]]; then
			return $has_non_conformances
		fi
	fi

	if [[ "$pod_affinity" == "null" ]]; then
		register_complaint "Pod is missing a pod affinity specification."
		return 1
	fi

	local soft_pod_aa_terms=$(jq -c '.preferredDuringSchedulingIgnoredDuringExecution' <<<"$pod_affinity")
	if [[ "$soft_pod_aa_terms" == "null" ]]; then
		register_complaint "Pod is missing a \"soft\" pod anti-affinity specification."
		return 1
	fi

	# Look through the anti-affinity terms to see if it conforms.  We're expecting
	# something like this (edited down):
	#
	# - podAffinityTerm:
	#     labelSelector:                              # We look for a label selector
	#       matchExpressions:                         # ...with a match expression
	#       - key: ocm-antiaffinity-selector          # ... using this exact key
	#         operator: In                            # ... and an "In" compare
	#         values:                                 # ... against a single vvalue
	#         - console
	#     topologyKey: topology.kubernetes.io/zone    # Associated with this topo key
	#
	# - podAffinityTerm:
	#     labelSelector:
	#       matchExpressions:                         # And a match expression
	#       - key: ocm-antiaffinity-selector          # ...with the same exact key
	#         operator: In                            # ...and operator
	#         values:
	#         - console                               # ...and value
	#     topologyKey: kubernetes.io/hostname         # Associated with this other topo key too.

	local expected_label_selector_key="ocm-antiaffinity-selector"

	local aa_term_cnt=$(jq 'length' <<<"$soft_pod_aa_terms")

	local found_candidate_zone_term=0
	local found_candidate_hostname_term=0

	local found_ok_zone_term=0
	local found_ok_hostname_term=0

	local the_match_expression_value=""

	for term_i in $(seq 0 $((aa_term_cnt - 1))); do

		local this_term=$(jq -c ".[$term_i].podAffinityTerm" <<<"$soft_pod_aa_terms")
		local this_topo_key=$(jq -r ".topologyKey" <<<"$this_term")

		if [[ "$this_topo_key" == "topology.kubernetes.io/zone" ]]; then
			found_candidate_zone_term=1
		elif [[ "$this_topo_key" == "kubernetes.io/hostname" ]]; then
			found_candidate_hostname_term=1
		else
			continue
		fi

		# Not sure how particular we should be here.  For now, we'll be really parciular and check
		# for a label selector match expression for our preferred key ocm-antiaffinity-selector.

		local label_selector_match_expressions=$(jq -c ".labelSelector.matchExpressions" <<<"$this_term")
		if [[ "$label_selector_match_expressions" == "null" ]]; then
			register_complaint "Anti-affinity term for $this_topo_key doesn't specify a label match."
			continue
		fi

		local ls_me_cnt=$(jq 'length' <<<"$label_selector_match_expressions")
		local our_match_expression_found=0
		for me_i in $(seq 0 $((ls_me_cnt - 1))); do
			local ls_me=$(jq ".[$me_i]" <<<"$label_selector_match_expressions")
			local me_key=$(jq -r '.key' <<<"$ls_me")
			local me_operator=$(jq -r '.operator' <<<"$ls_me")
			local me_values=$(jq '.values' <<<"$ls_me")
			if [[ "$me_key" == "$expected_label_selector_key" ]]; then
				break
			fi
		done

		if [[ "$me_key" != "$expected_label_selector_key" ]]; then
			register_complaint "Anti-affinity term for $this_topo_key doesn't specify a label-match for label $expected_label_selector_key"
			continue
		fi
		if [[ "$me_operator" != "In" ]]; then
			register_complaint "Anti-affinity term for $this_topo_key has label-match for label $expected_label_selector_key but doesn't specify an \"In\" type operation"
			continue
		fi
		if [[ "$me_values" == "null" ]]; then
			register_complaint "Anti-affinity term for $this_topo_key has label-match for label $expected_label_selector_key has no match value"
			continue
		fi
		local val_cnt=$(jq 'length' <<<"$me_values")
		if [[ $val_cnt -gt 1 ]]; then
			register_complaint "Anti-affinity term for $this_topo_key has label-match for label $expected_label_selector_key has multiple match values"
			continue
		fi

		local me_val=$(jq '.[0]' <<<"$me_values")

		if [[ -z "$the_match_expression_value" ]]; then
			the_match_expression_value=$me_value
		else
			if [[ "$me_value" != "$the_match_expression_value" ]]; then
				register_complaint "Anti-affinity term for $this_topo_key has label-match for label $expected_label_selector_key specifies different value"
				continue
			fi
		fi

		# If here and still happy, record what we found.
		if [[ $found_issues_with_me -eq 0 ]]; then
			if [[ $found_candidate_zone_term -ne 0 ]]; then
				found_ok_zone_term=1
			fi
			if [[ $found_candidate_hostname_term -ne 0 ]]; then
				found_ok_hostname_term=1
			fi
		fi
	done

	if [[ $found_ok_zone_term -eq 0 ]]; then
		# Complain about missing term affinity term (if candidate was found but not ok, we compalied already above)
		if [[ $found_candidate_zone_term -eq 0 ]]; then
			register_complaint "Pod is missing  a soft anti-affinity term for topology key topology.kubernetes.io/zone"
		fi
		has_non_conformances=1
	fi
	if [[ $found_ok_hostname_term -eq 0 ]]; then
		if [[ $found_candidate_hostname_term -eq 0 ]]; then
			register_complaint "Pod is missing a soft anti-affinity term for topology key kubernetes.io/hostname"
		fi
		has_non_conformances=1
	fi

	return $has_non_conformances
}

function check_security_context() {

	# Check that pod security context meets expections.

	if [[ $do_check_security_context -eq 0 ]]; then
		return 0
	fi

	local pod_spec_json="$1"
	local has_non_conformances=0

	# Check that container-level security context for all containts specifies:
	#
	#    securityContext:
	#      allowPrivilegeEscalation: false
	#      capabilities:
	#        drop:             # Check that capabilities.drop has the single entry ALL
	#        - ALL
	#      privileged: false
	#
	# Note: Check for readOnlyRootFilesystem is done in check_read_only_root_filesystem
	# so it can be separately enabled/disabled.

	local containers=$(jq -c '.containers' <<<"$pod_spec_json")
	local container_cnt=$(jq 'length' <<<"$containers")

	for container_i in $(seq 0 $((container_cnt - 1))); do
		local this_container=$(jq -c ".[$container_i]" <<<"$containers")
		local container_name=$(jq -r '.name' <<<"$this_container")

		# Don't assume default values are what we want them to be
		# The security context should be present
		local container_sec_ctx=$(jq -r '.securityContext' <<<"$this_container")
		if [[ "$container_sec_ctx" == "null" ]]; then
			append_yaml $pod_namespace $pod_id $container_name "securityContext" "notnull" "notnull"
			register_complaint "Container $container_name does not have a security context."
			has_non_conformances=1
			continue
		fi

		# allowPrivilegeEscalation should be FALSE
		local ape=$(jq -r '.allowPrivilegeEscalation' <<<"$container_sec_ctx")
		if [[ "$ape" != "false" ]]; then
			register_complaint "Container $container_name allows privilege escalation."
			append_yaml $pod_namespace $pod_id $container_name "allowPrivilegeEscalation" "false" $ape
			has_non_conformances=1
		fi

		# privileged sould be FALSE
		local priv=$(jq -r '.privileged' <<<"$container_sec_ctx")
		if [[ "$priv" != "false" ]]; then
			register_complaint "Container $container_name is running as privileged."
			append_yaml $pod_namespace $pod_id $container_name "privileged" "false" $priv
			has_non_conformances=1
		fi

		# NET_BIND_SERVICE should drop ALL
		local drops_all_capabilities=0
		local cap_drop=$(jq -c '.capabilities.drop' <<<"$container_sec_ctx")
		if [[ "$cap_drop" != "null" ]]; then
			local drop_cnt=$(jq 'length' <<<"$cap_drop")
			if [[ $drop_cnt -eq 1 ]]; then
				local drop_entry_0=$(jq -r '.[0]' <<<"$cap_drop")
				if [[ "$drop_entry_0" == "ALL" ]]; then
					drops_all_capabilities=1
				fi
			fi
		fi
		if [[ $drops_all_capabilities -eq 0 ]]; then
			register_complaint "Container $container_name does not drop all capabilities."
			append_yaml $pod_namespace $pod_id $container_name "capabilities.drop" "[\"ALL\"]" $cap_drop
			has_non_conformances=1
		fi

		# readOnlyRootFilesystem should be TRUE
		if [[ $do_check_security_context_read_only_root_fs -ne 0 ]]; then
			local rorfs=$(jq -r '.readOnlyRootFilesystem' <<<"$container_sec_ctx")
			if [[ "$rorfs" != "true" ]]; then
				register_complaint "Container $container_name is not using a read-only root filesystem."
				append_yaml $pod_namespace $pod_id $container_name "readOnlyRootFilesystem" "true" $rorfs
				has_non_conformances=1
			fi
		fi
	done

	# And check that pod-level security context specifies:
	#
	#    securityContext:
	#      runAsNonRoot: true
	#      seccompProfile:
	#        type: RuntimeDefault

	local pod_sec_ctx=$(jq -r '.securityContext' <<<"$pod_spec_jsonr")

	if [[ "$pod_sec_ctx" == "null" ]]; then
		register_complaint "Pod does not have a pod-level security context."
		has_non_conformances=1
	else
		local ranr=$(jq -r '.runAsNonRoot' <<<"$pod_sec_ctx")
		if [[ "$anr" != "true" ]]; then
			register_complaint "Pod is not running as non-root user."
			has_non_conformances=1
		fi
		local scpt=$(jq -r '.seccompProfile.type' <<<"$pod_sec_ctx")
		if [[ "$scpt" != "RuntimeDefault" ]]; then
			register_complaint "Pod is not configured with secCompProfile.type as RuntimeDefault."
			has_non_conformances=1
		fi
	fi

	return $has_non_conformances
}
function check_read_only_root_filesystem() {

	# Check that all containers in pod are runninng with a read-only root filessytem.
	# (This is a specific security context check that is broken out as a separate check.)

	if [[ $do_check_read_only_root_fs -eq 0 ]]; then
		return 0
	fi

	local pod_spec_json="$1"
	local has_non_conformances=0

	# Check that container-level security context for all containts specifies:
	#
	#    securityContext:
	#      readOnlyRootFilesystem: true

	local containers=$(jq -c '.containers' <<<"$pod_spec_json")
	local container_cnt=$(jq 'length' <<<"$containers")

	for container_i in $(seq 0 $((container_cnt - 1))); do
		local this_container=$(jq -c ".[$container_i]" <<<"$containers")
		local container_name=$(jq -r '.name' <<<"$this_container")
		local container_sec_ctx=$(jq -r '.securityContext' <<<"$this_container")
		if [[ "$container_sec_ctx" == "null" ]]; then
			register_complaint "Container $container_name does not have a security context."
			has_non_conformances=1
			continue
		fi

		local rorfs=$(jq -r '.readOnlyRootFilesystem' <<<"$container_sec_ctx")
		if [[ "$rorfs" != "true" ]]; then
			register_complaint "Container $container_name is not using a read-only root filesystem."
			has_non_conformances=1
		fi
	done

	return $has_non_conformances
}

declare -A owners_already_seen

function replica_was_already_seen() {

	# See if we're already seen a replica of the current pod by checking
	# for an onwerReference of a kind we understand and with matching uid.
	#
	# Returns 0 for already seen, 1 if not (or can't tell).

	local pod_metadata_json="$1"

	local owner_refs=$(jq -r '.ownerReferences' <<<"$pod_metadata_json")
	if [[ "$owner_refs" == "null" ]]; then
		return 1
	fi
	local owner_ref_cnt=$(jq 'length' <<<"$owner_refs")
	local owner_uid=""
	for owner_ref_i in $(seq 0 $((owner_ref_cnt - 1))); do
		local this_ref=$(jq -c ".[$owner_ref_i]" <<<"$owner_refs")
		local ref_kind=$(jq -r '.kind' <<<"$this_ref")
		if [[ $ref_kind == "ReplicaSet" ]] || [[ $ref_kind == "StatefulSet" ]]; then
			local ref_uid=$(jq -r '.uid' <<<"$this_ref")
			if [[ "$ref_uid" != "null" ]]; then
				owner_uid="$ref_uid"
				break
			fi
		fi
	done

	if [[ -z "$owner_uid" ]]; then
		return 1
	fi

	local pod_ns=$(jq -r '.namespace' <<<"$pod_metadata")
	local pod_name=$(jq -r '.name' <<<"$pod_metadata")

	if [[ -n "${owners_already_seen[$owner_uid]}" ]]; then
		# echo "Replica of pod $pod_ns/$pod_name already scanned."
		return 0
	fi
	owners_already_seen[$owner_uid]=1
	return 1

}

function analyze_pod() {

	local this_pod_json="$1"

	local pod_metadata=$(jq -c '.metadata' <<<"$this_pod_json")

	local pod_ns=$(jq -r '.namespace' <<<"$pod_metadata")
	local pod_name=$(jq -r '.name' <<<"$pod_metadata")
	set_pod_id "$pod_name"
	set_pod_namespace "$pod_ns"

	if replica_was_already_seen "$pod_metadata"; then
		return 0
	fi

	check_for_restricted_scc "$pod_metadata"

	local pod_spec=$(jq -c '.spec' <<<"$this_pod_json")

	check_security_context "$pod_spec"
	check_read_only_root_filesystem "$pod_spec"
	check_for_pod_anti_affinity "$pod_spec"

	# TODO:
	# - Check for node selector and toleration for infra nodes
	# - Check for pass-thru of PROXY env vars (but only if proxy env...)
	# - xxx

	return $pod_non_conformances_found
}

# Main:

clean_namespaces=()
namespaces_with_non_conformances=()
echo "" >$output_yaml

# Ensure that we're configured/authenticated to an OCP cluster.
#
# If we're running sa a pod on the OCP cluster, we should be automatically configered
# and authenticated to run under the pod's service account.
#
# But if we're being run locally, or as a local container, then we'll need appropriate
# OCP config/login to be done by the user before launching us.

tmp_emsgs="$tmp_dir/error-msgs.txt"
oc status >/dev/null 2>"$tmp_emsgs"
if [[ $? -ne 0 ]]; then
	>&2 echo "Error: Cannot access target OCP cluster:"
	>&2 cat "$tmp_emsgs"
	exit 3
fi

# Get a list of all namespaces that aren't considered OCP's namespaces.

all_non_ocp_namespaces=$(
	oc get ns -o name |
		grep -v '^namespace/openshift-' |
		grep -v '^namespace/openshift' |
		grep -v '^namespace/kube-public' |
		grep -v '^namespace/kube-system' |
		grep -v '^namespace/kube-node-lease' |
		grep -v '^namespace/default' |
		cut -d'/' -f2 |
		sort
)

# Analyze pods in all of the non-OCP namespaces.

for ns in $all_non_ocp_namespaces; do
	blurt_ns_progress_msg "Analyzing pods in namespace $ns."
	all_pods_json="$tmp_dir/$ns-all-pods.json"
	oc -n "$ns" get pods -o json >"$all_pods_json"
	pod_cnt=$(jq '.items | length' "$all_pods_json")

	ns_had_non_conformances=0

	for i in $(seq 0 $((pod_cnt - 1))); do
		this_pod_json=$(jq -c ".items[$i]" "$all_pods_json")
		analyze_pod "$this_pod_json"
		rc=$?
		if [[ $rc -ne 0 ]]; then
			ns_had_non_conformances=1
		fi
	done

	if [[ $ns_had_non_conformances -eq 0 ]]; then
		clean_namespaces+=("$ns")
	else
		namespaces_with_non_conformances+=("$ns")
	fi
done

echo ""
echo "Namespaces that were clean (no non-conforming pods):"
for ns in ${clean_namespaces[@]}; do
	echo "   $ns"
done

echo ""
echo "Namespaces with non-conforming pods:"
for ns in ${namespaces_with_non_conformances[@]}; do
	echo "   $ns"
done

exit 0
