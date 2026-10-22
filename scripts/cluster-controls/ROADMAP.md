# Roadmap

Future improvements and considerations for this project.

## Module Namespacing (Future Consideration)

Currently, the justfile uses `import` to include recipes from `cluster.just` and `acm.just`, which places all recipes in the same namespace.

### Current Setup (using `import`)

```just
kubeconfig := env_var_or_default("KUBECONFIG", justfile_directory() + "/kubeconfig")

import 'cluster.just'
import 'acm.just'
```

**Usage:**
- `just login`
- `just install-acm`
- `just apply-pull-secret`

All recipes appear in a flat namespace.

### Alternative: Module Namespacing (using `mod`)

We could switch to using `mod` instead, which provides namespaced commands:

```just
kubeconfig := env_var_or_default("KUBECONFIG", justfile_directory() + "/kubeconfig")

mod cluster
mod acm
```

**Benefits:**
- Clear grouping: `just cluster::login`, `just acm::install-acm`
- `just -l` shows all recipes with module prefixes
- `just -l acm::` shows only ACM-related recipes
- `just -l cluster::` shows only cluster-related recipes
- Better organization for larger projects

**Drawbacks:**
- Longer command names
- More typing for common commands
- May be overkill for smaller projects

**Usage examples:**
- `just cluster::login https://api.cluster.example.com:6443 --token=...`
- `just cluster::kubectx my-dev-cluster=.`
- `just acm::install-acm`
- `just acm::apply-pull-secret`

### Conversion Steps

If we decide to switch to modules:

1. Update the main `justfile`:
   ```just
   kubeconfig := env_var_or_default("KUBECONFIG", justfile_directory() + "/kubeconfig")

   mod cluster
   mod acm
   ```

2. No changes needed to `cluster.just` or `acm.just` files

3. Update the README.md to reflect the new namespaced command structure

4. Users would need to update any scripts or muscle memory to use the new `module::command` syntax

## Other Potential Improvements

- Add more recipes for common cluster operations
- Add recipes for cleanup/uninstall operations
- Add validation recipes to check cluster state before operations
- Add recipes for troubleshooting common issues
- Support for additional registries beyond quay.io
- Configuration presets for different environments (dev, staging, prod)


## Hotswap Image in CSV
- Add a recipe to edit the current cluster's MCH CSV to hot-swap the image reference
