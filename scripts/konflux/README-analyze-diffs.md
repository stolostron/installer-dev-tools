# Konflux Diff Analyzer

## Overview

`analyze-diffs.sh` is a script that analyzes git diffs created by `konflux-snapshot-difftool.sh` to identify commits that violate development phase policies. It helps enforce code freeze policies during different phases of the release cycle.

## Usage

```bash
./analyze-diffs.sh [OPTIONS]
```

### Options

- `-m, --mode MODE` - Development phase mode (default: `feature-complete`)
  - `feature-complete`: Allow bug fixes, tests, docs, deps, and build changes. Reject feature work.
  - `code-lockdown`: Only allow dependencies, tests, build files, and documentation changes. Reject all product code changes.

- `-v, --verbose` - Show detailed analysis of each file change

- `-a, --show-allowed` - Show allowed changes in addition to violations and warnings

- `-f, --format FORMAT` - Output format: `text`, `json`, `csv` (default: `text`)

- `-d, --diffs-dir DIR` - Directory containing diff files (default: `./diffs`)

- `-h, --help` - Show help message

### Examples

```bash
# Analyze diffs in feature-complete mode (default)
./analyze-diffs.sh --mode feature-complete

# Analyze diffs in code-lockdown mode with verbose output
./analyze-diffs.sh --mode code-lockdown --verbose

# Generate JSON report
./analyze-diffs.sh --mode code-lockdown --format json > report.json

# Show all changes including allowed ones
./analyze-diffs.sh --show-allowed

# Generate CSV for tracking
./analyze-diffs.sh --mode code-lockdown --format csv > status.csv
```

## Workflow

1. **Generate diffs** using `konflux-snapshot-difftool.sh`:
   ```bash
   ./konflux-snapshot-difftool.sh -v acm-2.15.0 \
     -s release-acm-215-abc123 \
     -s release-acm-215-def456
   ```

2. **Analyze the diffs** to check for policy violations:
   ```bash
   ./analyze-diffs.sh --mode code-lockdown
   ```

3. **Review violations** and take action:
   - Violations require immediate attention
   - Warnings should be manually reviewed
   - Clean components are good to go

## Development Phases

### Feature Complete Mode

**Allowed:**
- Bug fixes
- Refactoring
- Test changes
- Documentation updates
- Dependency updates
- Build/CI changes

**Rejected:**
- New features
- Significant code additions

**Warnings:**
- Changes that can't be automatically classified

### Code Lockdown Mode

**Allowed:**
- Test changes
- Documentation updates
- Dependency updates
- Build/CI changes

**Rejected:**
- ALL product code changes
- Bug fixes to product code

**Use Case:** Final hardening phase before release where only test/doc/dep updates are permitted.

## File Classification

The script automatically classifies files into categories:

### Dependency Files
- `package.json`, `package-lock.json`
- `go.mod`, `go.sum`
- `Gemfile`, `Gemfile.lock`
- `requirements.txt`, `Pipfile.lock`
- `pom.xml`, `build.gradle`, `Cargo.toml`
- `*/vendor/*`, `*/node_modules/*`

### Test Files
- `*_test.go`, `*.test.js`, `*.spec.ts`
- `*Test.java`, `test_*.py`
- `*/test/*`, `*/tests/*`, `*/__tests__/*`
- `*/e2e/*`, `*/integration/*`
- `.github/workflows/*` (CI workflows)

### Build Files
- `Makefile`, `Dockerfile`, `*.dockerignore`
- `.github/workflows/*`, `.tekton/*`, `.konflux/*`
- `build/*`, `ci/*`, `.ci/*`
- `Jenkinsfile`, `*.mk`, `CMakeLists.txt`

### Documentation Files
- `*.md`, `*.rst`, `*.txt`
- `README*`, `CHANGELOG*`, `LICENSE*`
- `doc/*`, `docs/*`
- `.vscode/*`, `.idea/*` (editor configs)

### Product Code
- Everything else (source code that ships in the product)

## Output Formats

### Text Format (Default)

Human-readable colored output showing:
- Component name and status (CLEAN/WARNING/VIOLATION)
- Repository URL and diff link
- File counts and line changes
- List of violating files (if any)
- List of allowed changes (with `--show-allowed`)

### JSON Format

Machine-readable JSON with full details:
```json
{
  "mode": "code-lockdown",
  "components": [
    {
      "component": "cert-policy-controller-acm-215",
      "status": "CLEAN",
      "commits": 3,
      "files_changed": 3,
      "product_files": 0,
      ...
    }
  ],
  "summary": {
    "total": 15,
    "violations": 2,
    "warnings": 5,
    "clean": 8
  }
}
```

### CSV Format

Spreadsheet-compatible format:
```csv
component,repository,diff_url,status,commits,files_changed,product_files,additions,deletions,violations,warnings,allowed
cert-policy-controller-acm-215,https://github.com/...,https://github.com/.../compare/...,CLEAN,3,3,0,47,48,0,0,3
```

## Exit Codes

- `0` - All checks passed (no violations)
- `1` - Policy violations detected

Warnings do NOT cause a non-zero exit code.

## Integration with CI/CD

### GitLab CI Example

```yaml
check-code-freeze:
  stage: validate
  script:
    - ./konflux-snapshot-difftool.sh -v acm-2.15.0 -s $CI_COMMIT_SHA -s $BASELINE_SNAPSHOT
    - ./analyze-diffs.sh --mode code-lockdown --format json > report.json
  artifacts:
    reports:
      junit: report.json
    paths:
      - report.json
  only:
    - /^release-.*$/
```

### GitHub Actions Example

```yaml
name: Code Freeze Check
on:
  pull_request:
    branches:
      - 'release-*'

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Analyze Diffs
        run: |
          ./analyze-diffs.sh --mode code-lockdown --format text
```

## Limitations

- **Commit Message Analysis**: The script currently classifies changes primarily based on file paths, not commit messages, since commit messages aren't included in the diff files
- **Context-Aware Classification**: Cannot detect if a "fix" actually introduces new features
- **Manual Review**: Warnings always require manual inspection

## Future Enhancements

Potential improvements:
1. Fetch commit messages from GitHub API for better classification
2. Configurable file classification rules via config file
3. Integration with Jira to validate bug IDs in commits
4. Support for allowlist/blocklist of specific files or patterns
5. Diff size thresholds (flag large changes even if categorized as fixes)
6. Team-specific rules (different policies for different components)

## See Also

- `konflux-snapshot-difftool.sh` - Generates the diffs analyzed by this script
- `compliance.sh` - Checks Konflux component compliance
- `batch-compliance.sh` - Runs compliance checks in parallel
