## Pod Linter
The pod linter will scan all pods that are installed by the ACM Installer, filtering out pods in the following namespaces:

```
openshift-*
openshift
kube-public
kube-system
kube-node-lease
default
```

The following hard-coded flags are used to enable/disable any checks:

```
do_check_for_restricted_scc
do_check_security_context
do_check_security_context_read_only_root_fs
do_check_for_pod_anti_affinity
do_check_for_hard_anti_affinity
do_check_for_hard_anti_affinity_only
do_check_security_context
```

All results are printed to the console for human-readable output, controlled by the "blurt" flags.

The results are written to 'lint.yaml' in the format `namespace.pod.container.context:{desired: <state>, actual: <state>}`

## Pod Enforcer
The pod enforcer's job is currently hard-coded to solve the specific problem of patching **deployments**, **statefulsets**, and **jobs** with `privileged: false` and `readOnlyRootFilesystem: true`. It assumes that the pods follow the naming convention `pod_name_xxxxxxxxx_xxxx`, and that the last two `_` separated values are unique identifiers, leaving `pod_name` to also be the name of the deployment in the same namespace. For the purposes of the work this script was designed for, this sufficed. Stateful Sets and Jobs followed similar, but not exact conventions.

The enforcer reads in `lint.yaml` and creates its own `enforce.yaml` to keep track of namespaces, deployments, statefulsets, and jobs that it successfully finds, then it uses those to apply the patch to each one.