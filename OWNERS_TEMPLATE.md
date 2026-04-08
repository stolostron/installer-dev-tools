# Component OWNERS File Guide

## Overview

Component teams can now add OWNERS files to their chart directories in their upstream repositories. These OWNERS files will be automatically synced to operator repositories (multiclusterhub-operator, backplane-operator) during chart regeneration, allowing component teams to independently approve changes to their charts.

## How It Works

1. **Component teams** add an OWNERS file to their chart/bundle directory in their upstream repo
2. **Automation** syncs the OWNERS file during `make regenerate-charts` / `make regenerate-charts-from-bundles`
3. **Prow** uses the OWNERS file for PR approvals in the operator repository
4. **Fallback**: Charts without upstream OWNERS files use the root OWNERS (Installer team)

**Important:** Upstream is the single source of truth for automated charts:
- **If upstream HAS OWNERS** → copied to operator repository (multiclusterhub-operator, backplane-operator)
- **If upstream NO OWNERS** → any existing downstream OWNERS removed, fallback to root OWNERS (Installer team)

**Do not manually add OWNERS to automated charts** in operator repositories - they will be removed on the next regeneration if they don't exist upstream.

**Exception:** Charts manually maintained in operator repositories (not in automation config) can have manual OWNERS files - the automation won't touch them.

## Where to Add OWNERS File

### For Helm-based Components

Add the OWNERS file to your chart directory in your component repository:

```
your-component-repo/
└── deploy/
    └── chart/                    # or wherever your chart lives
        ├── Chart.yaml
        ├── values.yaml
        ├── templates/
        └── OWNERS                # <-- Add this file
```

### For Bundle-based Components (OLM Operators)

Add the OWNERS file to the root of your bundle repository:

```
your-operator-bundle-repo/
├── bundle/
│   └── manifests/
│       └── your-operator.clusterserviceversion.yaml
└── OWNERS                        # <-- Add this file
```

This will be copied to the operator repository (e.g., multiclusterhub-operator):
```
<operator-repo>/
└── pkg/
    └── templates/
        └── charts/
            └── toggle/
                └── your-component/
                    ├── Chart.yaml
                    ├── values.yaml
                    ├── templates/
                    └── OWNERS    # <-- Auto-copied here
```

## OWNERS File Format

Create an OWNERS file in YAML format:

```yaml
approvers:
- github-username-1
- github-username-2
- github-username-3
reviewers:
- github-username-1
- github-username-2
- github-username-3
- github-username-4
```

### Example: Component Team OWNERS

```yaml
approvers:
- team-lead-1
- team-lead-2
- team-member-1
reviewers:
- team-lead-1
- team-lead-2
- team-member-1
- team-member-2
```

## Approval Behavior

### With Component OWNERS File

**Scenario 1**: PR only touches your component's chart files
- ✅ Your team can `/approve` and merge independently
- ✅ Installer team can still approve if needed (Prow inheritance)

**Scenario 2**: PR touches your component AND other files
- ⚠️ Requires approvals from both:
  - Your team member (for your component files)
  - Root OWNERS or other component OWNERS (for other files)

### Without Component OWNERS File

- All PRs require approval from root OWNERS (Installer team)
- This is the fallback behavior

## Benefits

- **Faster approvals**: Component teams don't need to wait for Installer team
- **Better ownership**: Clear responsibility for component charts
- **Flexibility**: Installer team can still approve when needed
- **No duplication**: OWNERS maintained in component repos, auto-synced

## FAQ

**Q: Do we need to use `no_parent_owners: true`?**
A: No. We use partial delegation, which allows both component teams AND the Installer team to approve.

**Q: What if our upstream chart doesn't have an OWNERS file?**
A: The chart will fallback to the root OWNERS file (Installer team) automatically.

**Q: Can we update OWNERS without regenerating charts?**
A: No. OWNERS files are synced during chart regeneration. Changes to OWNERS upstream will be picked up on the next regeneration.

**Q: What about CRD OWNERS files?**
A: Same pattern applies! Add OWNERS to your CRD directory and it will be copied to `pkg/templates/crds/your-component/OWNERS`.

## Rollout Plan

1. **Phase 1**: Merge this PR to installer-dev-tools
2. **Phase 2**: Component teams add OWNERS files to their repos
3. **Phase 3**: Next chart regeneration picks up OWNERS files
4. **Phase 4**: Component teams can start approving their own PRs

## Questions?

Contact the Installer team (@cameronmwall, @dislbenn, @ngraham20) if you have questions about OWNERS files.
