# Additional Improvements - Not Yet Merged

This document tracks additional improvements that were developed but not included in the initial `fix-version-comparison` branch. These changes are preserved on the `fix-version-comparison-temp` branch for future consideration.

## Branch History

- **Main branch:** `fix-version-comparison` - Contains core fixes (merged)
- **Experimental branch:** `fix-version-comparison-temp` - Contains additional improvements (preserved)

## Additional Changes Overview

### 1. CRD Namespace Templating

**Branch:** `fix-version-comparison-temp`
**Commits:**
- `2bba3fc` - Add CRD namespace templating for webhook services
- `a0360f8` - Use string-based replacement for CRD namespace templating

**What it does:**
Templates namespace references in CustomResourceDefinition (CRD) files:
- Webhook conversion service namespaces
- cert-manager.io/inject-ca-from annotations

**Example transformation:**

```yaml
# Before
metadata:
  annotations:
    cert-manager.io/inject-ca-from: multicluster-engine/capm3-serving-cert
spec:
  conversion:
    webhook:
      clientConfig:
        service:
          namespace: multicluster-engine

# After
metadata:
  annotations:
    cert-manager.io/inject-ca-from: '{{ default "multicluster-engine" .Values.global.namespace }}/capm3-serving-cert'
spec:
  conversion:
    webhook:
      clientConfig:
        service:
          namespace: '{{ default "multicluster-engine" .Values.global.namespace }}'
```

**Why it matters:**
Allows backplane-operator CRDs to be installed in custom namespaces, not just `multicluster-engine`.

**Why not merged:**
Decided to focus on core fixes first. CRD namespace customization can be added in a future PR when there's a specific requirement.

**Implementation details:**

Added `process_crd_namespaces()` function in `generate-charts.py`:

```python
def process_crd_namespaces(crd_data, crd_name):
    """
    Process CRD to template namespace references in webhook service configs and annotations.

    Uses string-based regex replacement to preserve original YAML formatting.
    """
```

Modified `addCRDs()` function to:
1. Read CRD file as text (not YAML object)
2. Use regex to find and replace namespace values
3. Write back as text (preserves formatting perfectly)

**Testing:**

```bash
cd /Users/disaiahbennett/dislbenn/backplane-operator
make regenerate-charts BRANCH=fix-version-comparison-temp

# Verify CRD namespaces are templated
grep "namespace:" pkg/templates/crds/cluster-api-provider-metal3-k8s/*.yaml
```

---

### 2. YAML Formatting Improvements

**Branch:** `fix-version-comparison-temp`
**Commits:**
- `a0360f8` - Use string-based replacement for CRD namespace templating (perfect preservation)
- `4e3c8d6` - Improve yaml.dump() formatting for regular resources

**What it does:**

#### For CRDs:
Uses string-based replacement instead of `yaml.dump()` to preserve original formatting:
- No extra blank lines added
- Original block scalar styles (`|-`) maintained
- Comments preserved
- Indentation unchanged

#### For Regular Resources:
Improved `yaml.dump()` parameters:

```python
yaml.dump(resource_data, f,
         width=float("inf"),
         default_flow_style=False,
         allow_unicode=True,
         sort_keys=False,          # NEW: Preserve field order
         explicit_start=False,      # NEW: No document markers
         explicit_end=False,        # NEW: No document markers
         default_style=None)        # NEW: Preserve string styles
```

**Before and After:**

```yaml
# Before (yaml.dump with defaults)
description: 'APIVersion defines the versioned schema of this representation of an object.

  Servers should convert recognized schemas to the latest internal value, and

  may reject unrecognized values.

  More info: https://git.k8s.io/...'

# After (string-based replacement for CRDs)
description: |-
  APIVersion defines the versioned schema of this representation of an object.
  Servers should convert recognized schemas to the latest internal value, and
  may reject unrecognized values.
  More info: https://git.k8s.io/...
```

**Why it matters:**
- Cleaner diffs in git (only actual changes shown)
- Easier to review changes
- Professional formatting matches upstream sources

**Why not merged:**
The improved `yaml.dump()` parameters are good but PyYAML still reformats. For perfect preservation, we'd need to switch to `ruamel.yaml` library, which requires:
- Adding new dependency
- Testing across all resource types
- Updating both `generate-charts.py` and `bundles-to-charts.py`

This is a larger change better suited for a dedicated refactoring PR.

**Future improvement path:**

```python
# Replace PyYAML with ruamel.yaml for better formatting
from ruamel.yaml import YAML
yaml = YAML()
yaml.preserve_quotes = True
yaml.default_flow_style = False
yaml.width = float("inf")
yaml.dump(data, f)
```

---

### 3. Shared Library Refactoring (Proof of Concept)

**Branch:** `fix-version-comparison-temp`
**Files Created:**
```
scripts/bundle-generation/
├── lib/
│   ├── __init__.py
│   ├── version_utils.py           # Version checking
│   ├── image_processing.py        # Image reference handling
│   ├── namespace_templating.py    # Namespace templating
│   └── helm_utils.py               # Common utilities
└── generate-charts-refactored-demo.py
```

**What it does:**
Creates a shared library to eliminate ~50% code duplication between:
- `generate-charts.py` - Helm charts → customized charts
- `bundles-to-charts.py` - OLM bundles → Helm charts

**Current situation:**
Both scripts contain duplicate functions:
- `is_version_compatible()` - 90 lines duplicated
- `parse_image_ref()` - 45 lines duplicated
- `find_templates_of_type()` - 25 lines duplicated
- `fixImageReferences()` - 75 lines duplicated
- `fixEnvVarImageReferences()` - 70 lines duplicated
- `ensure_webhook_namespace()` - 50 lines duplicated
- `update_helm_resources()` - 200+ lines duplicated
- Many more...

**Total duplication:** ~1,000+ lines of code

**Proposed structure:**

```python
# Before (duplicated in both scripts)
def is_version_compatible(branch, min_release, min_backplane, min_ocm):
    # 90 lines of code
    ...

# After (shared library)
from lib.version_utils import is_version_compatible
```

**Benefits:**

✅ **Single source of truth** - Bug fixes apply everywhere
✅ **Easier testing** - Unit test library functions independently
✅ **Better maintainability** - Changes in one place
✅ **Consistent behavior** - Both scripts use exact same logic
✅ **Easier to extend** - New scripts can use the library

**Example - Version comparison bug:**

The version comparison bug we just fixed existed in BOTH scripts. With a shared library:
- Fix once in `lib/version_utils.py`
- Both `generate-charts.py` and `bundles-to-charts.py` automatically benefit
- Future scripts automatically get the fix

**Why not merged:**
This is a significant refactoring that should be:
1. Done as a dedicated PR
2. Thoroughly tested
3. Reviewed by the team
4. Potentially done in phases

**Migration plan (for future):**

**Phase 1:** Create shared library
- [x] Extract common functions to `lib/` (DONE - on temp branch)
- [ ] Add unit tests for library functions
- [ ] Document library API

**Phase 2:** Refactor generate-charts.py
- [ ] Import shared functions
- [ ] Remove duplicate code
- [ ] Test with all chart types

**Phase 3:** Refactor bundles-to-charts.py
- [ ] Import shared functions
- [ ] Remove duplicate code
- [ ] Test with all bundle types

**Phase 4:** Add to requirements
- [ ] Document library usage
- [ ] Update README

**Testing the refactored demo:**

```bash
cd /Users/disaiahbennett/stolostron/installer-dev-tools/scripts/bundle-generation
python3 generate-charts-refactored-demo.py
```

Output shows how the library works:
```
✅ Version is compatible
📦 Parsed image: {'registry_and_ns': 'quay.io/stolostron', 'repository': 'backplane-operator', ...}
Processing Helm Chart: my-chart
```

---

## Summary of Preserved Work

| Feature | Status | Branch | Commits | Recommendation |
|---------|--------|--------|---------|----------------|
| **Version comparison fix** | ✅ Merged | `fix-version-comparison` | e8100c8 | In production |
| **Certificate namespace fix** | ✅ Merged | `fix-version-comparison` | b76f9fc | In production |
| **Double-wrapping fix** | ✅ Merged | `fix-version-comparison` | 6001339, 52afb26 | In production |
| **CRD namespace templating** | 📦 Preserved | `fix-version-comparison-temp` | 2bba3fc, a0360f8 | Future PR when needed |
| **YAML formatting** | 📦 Preserved | `fix-version-comparison-temp` | 4e3c8d6 | Future PR with ruamel.yaml |
| **Shared library** | 📦 Preserved | `fix-version-comparison-temp` | lib/* files | Future refactoring PR |

---

## How to Apply These Changes Later

### To add CRD namespace templating:

```bash
git checkout -b add-crd-namespace-templating
git cherry-pick 2bba3fc a0360f8
# Test thoroughly
git push -u origin add-crd-namespace-templating
# Create PR
```

### To improve YAML formatting:

```bash
# Option 1: Use improved yaml.dump() (partial improvement)
git checkout -b improve-yaml-formatting
git cherry-pick 4e3c8d6

# Option 2: Switch to ruamel.yaml (complete solution)
# 1. Add ruamel.yaml to requirements.txt
# 2. Replace yaml.dump() calls with ruamel.yaml
# 3. Test all resource types
```

### To refactor with shared library:

```bash
git checkout -b refactor-shared-library
# Copy lib/ directory from fix-version-comparison-temp
git checkout fix-version-comparison-temp -- scripts/bundle-generation/lib/
# Refactor generate-charts.py to use library
# Refactor bundles-to-charts.py to use library
# Add unit tests
# Create PR
```

---

## Testing Commands

### Test main fixes (merged):
```bash
cd /Users/disaiahbennett/dislbenn/backplane-operator
make regenerate-charts BRANCH=fix-version-comparison
```

### Test with CRD templating (preserved):
```bash
make regenerate-charts BRANCH=fix-version-comparison-temp
```

### Compare outputs:
```bash
diff -r pkg/templates/crds/ /tmp/crds-backup/
```

---

## References

- **Main PR branch:** `fix-version-comparison`
- **Experimental branch:** `fix-version-comparison-temp`
- **Related issues:**
  - Repeating error messages about ACM/MCE version
  - Hard-coded namespaces in generated charts
  - Certificate/Issuer namespace templating
  - YAML formatting inconsistencies

---

## Conclusion

All additional work has been preserved on the `fix-version-comparison-temp` branch and documented here. This allows us to:

1. ✅ Merge core fixes quickly (`fix-version-comparison` branch)
2. 📦 Preserve advanced features for future PRs
3. 📚 Maintain institutional knowledge
4. 🔄 Apply improvements incrementally as needed

The experimental branch will remain available for future reference and can be cherry-picked from as requirements evolve.

---

**Document version:** 1.0
**Last updated:** 2026-01-07
**Author:** Generated with Claude Code
**Maintained by:** stolostron/installer-dev-tools team
