# Installation Guide

## Prerequisites

Before installing, ensure you have:
- **Python 3.6+** installed
- **pip** (Python package installer)
- **Git** installed
- **GitHub CLI (gh)** installed:
  - macOS: `brew install gh`
  - Linux: See [Linux installation guide](https://github.com/cli/cli/blob/trunk/docs/install_linux.md)
  - Windows: `winget install --id GitHub.cli` or download from [cli.github.com](https://cli.github.com/)

## Quick Install (Local Only)

This installs the `jira-pr-summary` command on **your machine only**.

### Unix/Linux/macOS

```bash
# From the hack directory
cd hack/jira-pr-cli

# Install in editable mode (recommended for development)
pip install -e .

# Verify installation
jira-pr-summary --help
```

### Windows

```powershell
# From the hack directory (PowerShell)
cd hack\jira-pr-cli

# Install in editable mode (recommended for development)
pip install -e .

# Verify installation
jira-pr-summary --help
```

## First Time Setup

Run the setup wizard to configure Jira token and settings:

```bash
jira-pr-summary --setup
```

You'll be prompted for:
- Jira Personal Access Token
- Jira base URL (e.g., https://issues.redhat.com)
- Issue key pattern (e.g., `\b(ACM-\d+)\b`)
- Default repository (optional)

## Usage

```bash
# Process a specific PR
jira-pr-summary --pr 3369

# Use AI for summaries (requires Ollama - see below)
jira-pr-summary --pr 3369 --ai

# Show configuration
jira-pr-summary --show-config
```

## Optional: Install Ollama for AI Summaries

### macOS
```bash
brew install ollama
brew services start ollama
ollama pull llama3.2:3b
```

### Linux
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:3b
```

### Windows
1. Download installer from [https://ollama.com/download/windows](https://ollama.com/download/windows)
2. Run the installer
3. Open terminal and run: `ollama pull llama3.2:3b`

## Uninstall

### Unix/Linux/macOS

```bash
# Uninstall the tool
pip uninstall jira-pr-summary

# Remove config and cache
rm -rf ~/.jira-pr-summary
```

### Windows

```powershell
# Uninstall the tool
pip uninstall jira-pr-summary

# Remove config and cache (PowerShell)
Remove-Item -Recurse -Force $env:USERPROFILE\.jira-pr-summary

# Or in Command Prompt:
# rmdir /s /q %USERPROFILE%\.jira-pr-summary
```

## For Other Users

To share with teammates:

### Unix/Linux/macOS
1. They clone the repo
2. They run `cd hack/jira-pr-cli && pip install -e .`
3. They run `jira-pr-summary --setup` with their own Jira token

### Windows
1. They clone the repo
2. They run `cd hack\jira-pr-cli` and then `pip install -e .`
3. They run `jira-pr-summary --setup` with their own Jira token

Each user has their own local configuration at:
- Unix/Linux/macOS: `~/.jira-pr-summary/config.json`
- Windows: `%USERPROFILE%\.jira-pr-summary\config.json`
