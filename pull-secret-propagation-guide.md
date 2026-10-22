# Pull Secret Propagation Guide for OpenShift

This document outlines the process and lessons learned for properly configuring pull secrets to access private registries like `quay.io/acm-d` in OpenShift clusters.

## Problem

When deploying catalog sources that reference images from private registries (e.g., `quay.io/acm-d`), pods may fail with `ImagePullBackOff` errors showing "unauthorized: access to the requested resource is not authorized" even when pull secrets are configured.

## Root Cause Analysis

The issue typically stems from:
1. **Registry URL mismatch**: Pull secrets configured for `quay.io:443` won't automatically work for images referenced as `quay.io/...`
2. **Pull secret propagation timing**: Updated pull secrets need time to propagate to all nodes
3. **Pod restart requirements**: Existing pods may need to be recreated to pick up new credentials

## Solution Steps

### 0. Getting quay.io:443 Pull Secret (from README.md)

Add the pull-secrets for the `quay.io:443` registry with access to the `quay.io/acm-d` repository in your OpenShift main pull-secret. (**Caution**: if you apply this on a pre-existing cluster, it will cause a rolling restart of all nodes).

```bash
# Replace <USER> and <PASSWORD> with your credentials
oc get secret/pull-secret -n openshift-config --template='{{index .data ".dockerconfigjson" | base64decode}}' >pull_secret.yaml
oc registry login --registry="quay.io:443" --auth-basic="<USER>:<PASSWORD>" --to=pull_secret.yaml
oc set data secret/pull-secret -n openshift-config --from-file=.dockerconfigjson=pull_secret.yaml
rm pull_secret.yaml
```

Your OpenShift main pull secret should contain an entry with `quay.io:443`:
```json
{
  "auths": {
    "cloud.openshift.com": {
      "auth": "ENCODED SECRET",
      "email": "email@address.com"
    },
    "quay.io:443": {
      "auth": "ENCODED SECRET",
      "email": ""
    }
  }
}
```

### 1. Update Cluster Pull Secret

Update the global pull secret in the `openshift-config` namespace:

```bash
# Update the cluster pull secret with your updated credentials file
oc set data secret/pull-secret -n openshift-config --from-file=.dockerconfigjson=updated_pull_secret.json
```

### 2. Registry URL Consistency

**Option A (Recommended): Update Image References**
Update catalog sources or deployments to use the explicit port:

```bash
# Update catalog source to use :443 port explicitly
oc patch catalogsource <catalog-name> -n openshift-marketplace --type='merge' \
  -p='{"spec":{"image":"quay.io:443/acm-d/your-image:tag"}}'
```

**Option B: Add Multiple Registry Entries**
Ensure your pull secret contains entries for both formats:

```json
{
  "auths": {
    "quay.io": {
      "auth": "your-acm-d-credentials",
      "email": ""
    },
    "quay.io:443": {
      "auth": "your-acm-d-credentials", 
      "email": ""
    }
  }
}
```

### 3. Verify Pull Secret Propagation

Check that the pull secret has been updated in the cluster:

```bash
# Verify the pull secret contains your new credentials
oc get secret -n openshift-config pull-secret -o jsonpath='{.data.\.dockerconfigjson}' | \
  base64 -d | jq '.auths."quay.io:443"'
```

Monitor machine config pool status for updates:

```bash
# Check if nodes are updated with new configuration
oc get mcp master -o yaml
```

Look for `status.conditions` showing `Updated: True`.

### 4. Force Pod Recreation

Delete failing pods to force recreation with updated credentials:

```bash
# Delete the failing catalog source pod
oc delete pod <failing-pod-name> -n openshift-marketplace
```

### 5. Optional: Restart Kubelet (if needed)

In some cases, you may need to restart the kubelet on nodes:

```bash
# Restart kubelet on a specific node (use with caution)
oc debug node/<node-name> -- chroot /host systemctl restart kubelet
```

## Verification

1. **Pod Status**: Ensure pods transition from `ImagePullBackOff` to `Running`
2. **Catalog Source**: Check that catalog sources show `READY` state
3. **Operator Hub**: Verify operators appear in the Operator Hub UI (may take 1-2 minutes)

```bash
# Check catalog source status
oc get catalogsource <catalog-name> -n openshift-marketplace -o yaml

# Verify pod is running
oc get pods -n openshift-marketplace | grep <catalog-name>
```

## Timeline Expectations

- **Pull secret update**: Immediate
- **Machine config propagation**: 2-5 minutes
- **Pod restart**: 30 seconds - 2 minutes
- **Operator Hub visibility**: 1-2 minutes after pod is running

## Key Lessons Learned

1. **Registry URL consistency is critical**: `quay.io` and `quay.io:443` are treated as different registries
2. **Machine config updates are automatic**: OpenShift will automatically update nodes when the global pull secret changes
3. **Pod recreation may be required**: Existing pods don't automatically pick up new credentials
4. **Patience is important**: Allow time for propagation and synchronization
5. **Explicit ports are clearer**: Using `quay.io:443` in image references removes ambiguity

## Troubleshooting Commands

```bash
# Check pod events for detailed error messages
oc describe pod <pod-name> -n <namespace>

# View machine config pool status
oc get mcp

# Check all catalog sources
oc get catalogsource -A

# Verify pull secret contents
oc get secret -n openshift-config pull-secret -o yaml
```

## Files in This Directory

- `pull_secret.yaml`: Original cluster pull secret
- `quay_auth.json`: ACM-D specific credentials
- `updated_pull_secret.json`: Combined pull secret with all registry credentials

---

*Generated: $(date)*
*Cluster: $(oc whoami --show-server)*