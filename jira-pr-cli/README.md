# jira-pr-summary

A CLI tool for automatically generating and posting progress summaries to Jira from merged pull requests.

**Author:** Disaiah Bennett
**Issues:** Report bugs or feature requests at [stolostron/installer-dev-tools](https://github.com/stolostron/installer-dev-tools/issues)

## Features

### Core Features
- 🤖 **AI-powered summaries** using local Ollama (completely free and private, configurable as default)
- 📝 **Direct issue updates** for work without PRs (interactive selector with configurable filters)
- 🔄 **Status transitions** (New → In Progress, Merged → Review)
- 🎯 **Interactive selectors** using arrow keys for PRs and issues (powered by questionary)
- 🧪 **QE test case generation** with smart detection of QE-NotApplicable label
- 🌍 **Global CLI** - works from any directory with auto-repo detection
- 👤 **User filtering** - only process issues assigned to you
- 🏷️ **Component filtering** - filter by single or multiple components
- 📦 **Bulk operations** - backfill old PRs, process multiple PRs at once
- ✍️ **Commit messages** - optionally include in summaries
- 🔗 **Related PRs** - automatically shows other PRs for the same issue

### Smart Features
- 💡 **PR type auto-detection** - automatically suggests templates based on PR content (bugfix, feature, refactor, etc.)
- 📋 **Summary templates** - 6 built-in templates with smart variable filling
- 🎯 **Multi-issue wizard** - post to multiple issues, select specific ones, or customize per issue
- 🔀 **Smart backport detection** - identifies main branch vs backports using version parsing
- 🚫 **Resolved issue filtering** - automatically skips posting to closed/resolved/done issues
- 🔐 **Token expiry alerts** - warns when Jira token is expiring (14-day window)

### Performance & Configuration
- ⚡ **Smart caching** - 3-tier cache (PR cache, Jira metadata with 5-min TTL, repo detection)
- 📁 **Config profiles** - switch between projects/teams with different settings
- 🔧 **Easy configuration** with first-run setup wizard (reconfigurable anytime)
- 📊 **Work reports** - generate summaries from cache history (text, JSON, CSV, Markdown)
- 🔍 **Verbose mode** - debug API calls, filtering decisions, and detection logic

## Installation

Install locally on your machine:

```bash
cd hack/jira-pr-cli
pip install -e .
```

The `-e` flag installs in "editable" mode, so changes to the code are immediately available.

**Note**: This is a local installation. To share with others, they need to clone your repo and run the same command.

## First Time Setup

After installation, run the setup wizard:

```bash
jira-pr-summary --setup
```

You'll be prompted to configure:
1. **Jira Personal Access Token** - Get from your Jira instance (Profile → Personal Access Tokens)
2. **Jira Base URL** - e.g., https://issues.redhat.com or https://yourcompany.atlassian.net
3. **Issue Pattern** - Regex for your issue keys (e.g., `\b(PROJ-\d+)\b` for single project or `\b(PROJ|TEAM)-\d+)\b` for multiple)
4. **Default Repository** (optional) - Falls back to auto-detection from git (e.g., myorg/my-project)
5. **Jira Username** (optional) - Filters issues assigned to you in Jira (e.g., jdoe or john.doe@company.com)
6. **GitHub Username** (optional) - Filters PRs authored by you on GitHub (e.g., jdoe)
7. **Component(s)** (optional) - Filter by single or multiple components (e.g., "Backend" or "Backend, Frontend, API")
8. **AI Default** (optional) - Use AI by default for summaries (yes/no)
9. **Cache Expiry** (optional) - Days to keep cache entries (0 = keep forever, default 90)
10. **Issue Filter for --update** (optional) - Which issues to show: Active sprint only, All open issues, In Progress + Review, or Custom statuses

Configuration is saved to `~/.jira-pr-summary/config.json`

**Reconfigure anytime**: Run `--setup` again and press Enter to keep existing values, or enter new values to update.

## Usage

### Basic Commands

```bash
# Process a specific PR
jira-pr-summary --pr 3369

# Process multiple PRs at once
jira-pr-summary --pr 3369 3370 3371

# Process all PRs for an issue
jira-pr-summary --issue PROJ-12345

# Process all PRs for multiple issues
jira-pr-summary --issue PROJ-12345 PROJ-67890

# List recent merged PRs (last 7 days)
jira-pr-summary --list-only

# Process recent PRs interactively (with PR selector)
jira-pr-summary

# Update issues directly - interactive selector (shows filtered issues)
jira-pr-summary --update

# Update specific issues directly (no PR required)
jira-pr-summary --update PROJ-12345 PROJ-67890
```

**Understanding the modes:**
- **Default mode** (`jira-pr-summary`): Finds merged PRs automatically, generates summaries from PR data
- **--pr**: Process specific PR number(s) from GitHub
- **--issue**: Find all PRs that mention specific Jira issue(s)
- **--update**: Update Jira issues directly without any PR (for investigation work, planning, etc.)

### AI-Powered Summaries

```bash
# Install Ollama (one-time)
# macOS:
brew install ollama && brew services start ollama && ollama pull llama3.2:3b

# Linux:
curl -fsSL https://ollama.com/install.sh | sh && ollama pull llama3.2:3b

# Windows:
# Download installer from https://ollama.com/download/windows
# Then run: ollama pull llama3.2:3b

# Use AI for summaries (one-off)
jira-pr-summary --pr 3369 --ai

# Set AI as default during setup
jira-pr-summary --setup
# Step 7: Use AI by default? (yes/no) [no]: yes

# Disable AI for one run (if AI is your default)
jira-pr-summary --pr 3369 --no-ai
```

### Summary Templates

Built-in templates help structure your summaries consistently:

```bash
# Process PR - automatically detects type and suggests template
jira-pr-summary --pr 3369

# Output shows:
# 🔍 This looks like a bugfix
# Would you like to see available templates? (y/N): y

# Interactive template selector appears:
# ? Use a summary template?
#   > Bugfix - Fix issue with solution (Suggested)
#     Feature - Add new capability
#     Refactor - Improve code structure
#     ...
```

**Available templates:**
- **Bugfix** - Fix issue with solution (auto-detects: "fix", "bug", "patch")
- **Feature** - Add new capability (auto-detects: "feat", "add", "new")
- **Refactor** - Improve code structure (auto-detects: "refactor", "cleanup")
- **Dependency** - Update dependency version (auto-detects: "bump", "upgrade", dependency files)
- **Docs** - Documentation update (auto-detects: `.md` files, "doc")
- **Test** - Add/update tests (auto-detects: test files, "test", "spec")

**Smart variable filling:**
- Auto-detects values from PR title, description, files, and AI summary
- Shows auto-detected value with option to override
- Press Enter to keep suggested value

### Multi-Issue Handling

When a PR references multiple Jira issues:

```bash
# PR mentions ACM-123, ACM-456, ACM-789
jira-pr-summary --pr 3369

# Wizard appears:
# ? This PR references 3 issues. What would you like to do?
#   > Post to all 3 issues (same summary)
#     Select specific issues
#     Customize summary for each issue
#     Post to first issue only (current behavior)
```

**Modes:**
- **Post to all** - Same summary posted to all issues (fastest)
- **Select specific** - Checkbox selector to pick which issues
- **Customize** - Full workflow for each issue separately
- **First only** - Old behavior, posts to first issue only

### Config Profiles

Switch between different projects/teams easily:

```bash
# Create a new profile
jira-pr-summary --create-profile acm-installer
# Profile wizard walks you through:
#   - Issue pattern: \b(ACM-\d+)\b
#   - Default repo: stolostron/backplane-operator
#   - Component: Installer
#   - etc.

# List all profiles
jira-pr-summary --list-profiles
# Available profiles:
#   - default (active)
#   - acm-installer
#   - mce-team

# Switch active profile (persists)
jira-pr-summary --switch-profile acm-installer

# Use profile for one command only
jira-pr-summary --profile mce-team --pr 456

# Delete a profile
jira-pr-summary --delete-profile old-project
```

**Profile settings (per-profile):**
- Jira base URL, issue pattern
- Default repository
- Jira username, GitHub username
- Component filter
- AI preference, issue filter

**Global settings (shared across profiles):**
- Jira token, cache expiry

### Configuration Management

```bash
# Show current configuration
jira-pr-summary --show-config

# Re-run setup wizard (press Enter to keep values)
jira-pr-summary --setup

# Reset configuration
jira-pr-summary --reset-config
```

### Cache Management

```bash
# View cache contents (shows expiry info)
jira-pr-summary --show-cache

# Clear entire cache (with confirmation)
jira-pr-summary --clear-cache

# Clear specific issues from cache
jira-pr-summary --clear-cache PROJ-12345 PROJ-67890

# Generate work summary report (default: text format)
jira-pr-summary --generate-report

# Generate report for specific issues
jira-pr-summary --generate-report PROJ-12345 PROJ-67890

# Export to different formats
jira-pr-summary --generate-report --format json
jira-pr-summary --generate-report --format csv
jira-pr-summary --generate-report --format markdown

# Save to file
jira-pr-summary --generate-report --format csv > report.csv
jira-pr-summary --generate-report --format markdown > report.md
```

### Advanced Usage

```bash
# Bulk backfill - post summaries for old unposted PRs
jira-pr-summary --backfill --days 90

# Include commit messages in summaries
jira-pr-summary --pr 3369 --include-commits

# Filter PRs by author (GitHub username)
jira-pr-summary --author jdoe --days 30

# Dry run - preview without posting
jira-pr-summary --pr 3369 --dry-run

# Auto-approve all prompts (skip confirmations)
jira-pr-summary --yes

# Verbose mode - show debug info (API calls, JQL queries, filtering)
jira-pr-summary --verbose

# Force re-posting even if already posted
jira-pr-summary --pr 3369 --force

# Specify repository manually
jira-pr-summary --pr 3369 --repo owner/repository-name

# Process last 14 days (default is 7)
jira-pr-summary --days 14
```

### Filtering

The tool automatically filters PRs based on your configuration:

```bash
# User filtering (configured in setup)
# Only shows PRs for issues assigned to you
jira-pr-summary

# Component filtering (configured in setup)
# Only shows PRs for issues in your components
jira-pr-summary

# Author filtering (command-line)
# Only shows PRs authored by specific user
jira-pr-summary --author jdoe

# Combine filters
jira-pr-summary --author jdoe --days 30
```

### Smart Features Explained

**Backport Detection:**
- Automatically identifies main branch vs backports using version parsing
- Highest version number = main branch (e.g., `release-2.16` > `release-2.15`)
- Groups backports in summary with clear labels

```
*Backport Summary:*
Main PR #1610 merged and backported to: backplane-2.11 (PR #1612), backplane-2.8 (PR #1611)
```

**Resolved Issue Filtering:**
- Automatically skips posting to issues in resolved states
- Resolved statuses: Done, Closed, Resolved, Completed, Verified, Released
- Use `--force` to override and post anyway

```bash
# Automatically skips resolved issues
jira-pr-summary --pr 3369
# Output: ⏭️  Issue is already Done - skipping

# Force posting to resolved issue
jira-pr-summary --pr 3369 --force
```

**Token Expiry Alerts:**
- Checks if Jira token is expiring within 14 days
- Shows warning at startup with days remaining
- Provides link to renew token

```bash
# During setup, you're asked for token expiry date
jira-pr-summary --setup
# Enter expiry date (YYYY-MM-DD) or leave blank: 2026-02-15

# Warning shown if expiring soon:
# ⚠️  JIRA TOKEN EXPIRING SOON
# Your Jira token will expire in 7 days (on 2026-02-15)
```

## How It Works

1. **Auto-detects repository** from current git directory or uses configured default
2. **Finds merged PRs** with Jira issue keys in title/description
3. **Filters PRs** by user assignment, component, and/or author (if configured)
4. **Skips resolved issues** automatically (Done, Closed, Resolved, etc.)
5. **Shows related PRs** for each issue automatically
6. **Checks smart cache** (PR cache + Jira metadata with 5-min TTL) to avoid duplicates
7. **Detects PR type** and suggests matching template (bugfix, feature, etc.)
8. **Identifies backports** using version parsing (highest version = main branch)
9. **Multi-issue wizard** if PR references multiple issues
10. **Offers status transitions** based on issue state
11. **Generates summaries** using AI (if configured) or basic PR metadata
12. **Template support** with smart variable auto-filling
13. **Prompts for context** so you can add details
14. **Generates QE test cases** (AI mode only, respects QE-NotApplicable label)
15. **Posts to Jira** with your approval (or auto-approve with --yes)

## Interactive Selectors

The tool uses interactive menus (powered by questionary) for better UX:

### PR Selector
When running `jira-pr-summary` without specific flags:
- Shows all merged PRs from the last N days
- **Navigate with arrow keys**
- **Space to select/deselect** individual PRs
- **'a' to toggle all** PRs
- **Enter to confirm** and process selected PRs

All PRs start **unselected** - you choose which ones to process.

### Issue Selector
When running `jira-pr-summary --update`:
- Shows issues based on your configured filter
- **Navigate with arrow keys**
- **Space to select/deselect** issues
- **'a' to toggle all**
- **Enter to confirm**

**Issue Filter Options** (configured in setup Step 10):
1. **Active sprint only** - Issues in your current sprint
2. **All open issues** - Any issue not Done/Closed/Resolved
3. **In Progress + Review** - Only issues actively being worked on
4. **Custom statuses** - Specify your own status list

## Repository Detection

The tool smartly detects which repository to use:

1. **In a git repo?** Uses `upstream` remote (or prompts if both upstream/origin exist)
2. **Default mode (`jira-pr-summary`)?** Shows interactive repo selector if not in git directory
3. **Using `--pr` or `--issue`?** **Requires `--repo` flag** when not in a git directory (for safety)
4. **Using `--update`?** **No repository needed** (only talks to Jira)
5. **Need to override?** Use `--repo owner/repo` flag

**Why `--repo` is required for `--pr` and `--issue`:**
PR numbers are per-repository (PR #123 in repo-A ≠ PR #123 in repo-B). To avoid ambiguity and posting to the wrong issue, you must explicitly specify the repository when not in a git directory.

**Examples:**
```bash
# In git directory - auto-detects repo
cd ~/my-project
jira-pr-summary --pr 123  ✅

# Outside git directory - requires --repo flag
cd ~
jira-pr-summary --pr 123  ❌ Error: --repo flag required
jira-pr-summary --pr 123 --repo owner/my-project  ✅

# Update mode - no repo needed
cd ~
jira-pr-summary --update  ✅ Shows issue selector
```

## Cache & Expiration

Posts are tracked in `~/.jira-pr-summary/cache.json` to prevent duplicates:

- 💾 **Tracks posted PRs** with timestamps and URLs
- ⏰ **Auto-expires old entries** based on configured days (default: 90 days, 0 = never expire)
- ✅ **Prevents duplicates** - prompts before re-posting
- 🔄 **Force override** - use `--force` to skip the check
- 📊 **Generate reports** - create work summaries from cache history
- 🗑️ **Manual management** - view, clear all, or clear specific issues

**Cache expiration behavior:**
- Configured during setup (Step 8)
- Entries older than X days are automatically removed on load
- Set to 0 to keep cache forever
- View expired entries with `--show-cache` before they're removed

## Configuration Files

- **Config**: `~/.jira-pr-summary/config.json` - Jira token, base URL, issue pattern
- **Cache**: `~/.jira-pr-summary/cache.json` - Tracks posted PRs with timestamps

## Work Summary Reports

Generate reports of your posted work from cache history:

```bash
# Full work summary
jira-pr-summary --generate-report
```

**Report shows:**
- Work grouped by date (most recent first)
- **Issue summaries** fetched from Jira
- **Current issue status** from Jira (e.g., In Progress, Done, Review)
- **PR titles** fetched from GitHub
- Timestamps for each post
- Total summary (X issues, Y PRs)

**Example output:**
```
Fetching issue details from Jira...
Fetching PR details from GitHub...

======================================================================
WORK SUMMARY REPORT
======================================================================
Generated: 2026-01-25 14:30

📅 2026-01-25
----------------------------------------------------------------------

  PROJ-12345: Fix authentication timeout in production [Done]
    • PR #3369: Add JWT token validation and refresh logic at 14:15
      https://github.com/myorg/my-project/pull/3369

  PROJ-67890: Implement new dashboard widgets [In Progress]
    • PR #3370: Add sales metrics widget at 10:30
      https://github.com/myorg/my-project/pull/3370

======================================================================
Summary: 2 issue(s), 2 PR(s) posted
======================================================================
```

**Export formats:**
The report can be exported in multiple formats using the `--format` flag:
- **text** (default) - Human-readable terminal output
- **json** - Machine-readable JSON format
- **csv** - Spreadsheet-compatible CSV format (headers: Date, Issue Key, Issue Summary, Issue Status, PR Number, PR Title, PR URL, Posted At)
- **markdown** - Formatted Markdown for documentation

**Examples:**
```bash
# JSON format for programmatic processing
jira-pr-summary --generate-report --format json | jq '.total_prs'

# CSV for Excel/Google Sheets
jira-pr-summary --generate-report --format csv > sprint_report.csv

# Markdown for documentation
jira-pr-summary --generate-report --format markdown > SPRINT_SUMMARY.md
```

**Future enhancements:**
- Filter by date range (--from, --to)
- Group by issue status or component

## Requirements

- **Python 3.6+**
- **Git**
- **GitHub CLI (`gh`)** - Required for PR operations
  - macOS: `brew install gh`
  - Linux: See [installation guide](https://github.com/cli/cli/blob/trunk/docs/install_linux.md)
  - Windows: `winget install --id GitHub.cli` or download from [cli.github.com](https://cli.github.com/)
- **questionary** - Interactive prompts (installed automatically with pip)
- **Optional: Ollama** for AI summaries (see AI-Powered Summaries section above)

## Uninstall

```bash
# Uninstall the tool
pip uninstall jira-pr-summary

# Optionally remove config and cache
# Unix/Linux/macOS:
rm -rf ~/.jira-pr-summary

# Windows (PowerShell):
# Remove-Item -Recurse -Force $env:USERPROFILE\.jira-pr-summary

# Windows (Command Prompt):
# rmdir /s /q %USERPROFILE%\.jira-pr-summary
```

## Example Workflows

### Daily Workflow
```bash
# After merging a PR (AI configured as default)
cd ~/my-project
jira-pr-summary --pr 3369

# Process multiple PRs from today
jira-pr-summary --pr 3369 3370 3371

# Update issues for non-PR work (investigation, planning, etc.)
jira-pr-summary --update
# Interactive selector shows issues based on your configured filter
```

### Weekly Review
```bash
# Review all your work from last week
jira-pr-summary --days 7

# Generate work summary report
jira-pr-summary --generate-report

# Backfill any missed PRs
jira-pr-summary --backfill --days 7
```

### Team Lead / Manager Workflow
```bash
# Check team member's work
jira-pr-summary --author teamember --days 14

# Filter by component
# (configure component during setup, or re-run --setup)
jira-pr-summary --days 30

# Generate sprint report
jira-pr-summary --generate-report
```

### Debugging
```bash
# Verbose mode to see what's happening
jira-pr-summary --verbose

# Dry run to preview without posting
jira-pr-summary --pr 3369 --dry-run

# View cache to see what's been posted
jira-pr-summary --show-cache
```
