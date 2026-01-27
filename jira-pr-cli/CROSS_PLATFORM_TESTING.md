# Cross-Platform Testing Guide for jira-pr-cli

This guide provides instructions for testing the jira-pr-summary tool across Windows, Linux, and macOS platforms.

## Table of Contents

- [Platform Compatibility Matrix](#platform-compatibility-matrix)
- [Prerequisites by Platform](#prerequisites-by-platform)
- [Installation Testing](#installation-testing)
- [Core Functionality Testing](#core-functionality-testing)
- [Platform-Specific Testing](#platform-specific-testing)
- [Known Platform Differences](#known-platform-differences)
- [Troubleshooting](#troubleshooting)

## Platform Compatibility Matrix

| Feature | macOS | Linux | Windows |
|---------|-------|-------|---------|
| Installation | ✅ | ✅ | ✅ |
| Git operations | ✅ | ✅ | ✅ |
| GitHub CLI integration | ✅ | ✅ | ✅ |
| Jira API operations | ✅ | ✅ | ✅ |
| Config management | ✅ | ✅ | ✅ |
| Cache management | ✅ | ✅ | ✅ |
| AI summaries (Ollama) | ✅ | ✅ | ✅ |
| Interactive prompts | ✅ | ✅ | ✅ |

## Prerequisites by Platform

### macOS

**Required:**
- Python 3.6+ (check: `python3 --version`)
- pip (check: `pip3 --version`)
- Git (check: `git --version`)
- GitHub CLI (install: `brew install gh`)

**Optional:**
- Ollama (install: `brew install ollama`)

**Setup:**
```bash
# Install GitHub CLI
brew install gh

# Authenticate with GitHub
gh auth login

# Optional: Install Ollama
brew install ollama
brew services start ollama
ollama pull llama3.2:3b
```

### Linux

**Required:**
- Python 3.6+ (check: `python3 --version`)
- pip (check: `pip3 --version`)
- Git (check: `git --version`)
- GitHub CLI (see [installation guide](https://github.com/cli/cli/blob/trunk/docs/install_linux.md))

**Optional:**
- Ollama (install: `curl -fsSL https://ollama.com/install.sh | sh`)

**Setup (Ubuntu/Debian):**
```bash
# Install GitHub CLI
type -p curl >/dev/null || sudo apt install curl -y
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
&& sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
&& echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
&& sudo apt update \
&& sudo apt install gh -y

# Authenticate with GitHub
gh auth login

# Optional: Install Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:3b
```

**Setup (Fedora/RHEL/CentOS):**
```bash
# Install GitHub CLI
sudo dnf install gh

# Authenticate with GitHub
gh auth login

# Optional: Install Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:3b
```

### Windows

**Required:**
- Python 3.6+ (download from [python.org](https://www.python.org/downloads/))
- pip (included with Python)
- Git (download from [git-scm.com](https://git-scm.com/download/win))
- GitHub CLI (install: `winget install --id GitHub.cli`)

**Optional:**
- Ollama (download from [ollama.com/download/windows](https://ollama.com/download/windows))

**Setup (PowerShell as Administrator):**
```powershell
# Install GitHub CLI
winget install --id GitHub.cli

# Restart PowerShell, then authenticate
gh auth login

# Optional: Install Ollama
# Download and run installer from https://ollama.com/download/windows
# Then in terminal:
ollama pull llama3.2:3b
```

## Installation Testing

### Test 1: Install from Source

**macOS/Linux:**
```bash
# Navigate to the jira-pr-cli directory
cd path/to/installer-dev-tools/jira-pr-cli

# Install in editable mode
pip install -e .

# Verify installation
jira-pr-summary --help
which jira-pr-summary
```

**Windows (PowerShell):**
```powershell
# Navigate to the jira-pr-cli directory
cd path\to\installer-dev-tools\jira-pr-cli

# Install in editable mode
pip install -e .

# Verify installation
jira-pr-summary --help
Get-Command jira-pr-summary
```

**Expected Result:**
- Installation completes without errors
- `--help` displays usage information
- Command is in system PATH

### Test 2: Configuration Directory Creation

**All Platforms:**
```bash
jira-pr-summary --setup
```

**Expected Result:**
- Config directory created at:
  - macOS/Linux: `~/.jira-pr-summary/`
  - Windows: `%USERPROFILE%\.jira-pr-summary\`
- Setup wizard prompts for configuration
- Files created: `config.json`

**Verify (macOS/Linux):**
```bash
ls -la ~/.jira-pr-summary/
cat ~/.jira-pr-summary/config.json
```

**Verify (Windows PowerShell):**
```powershell
Get-ChildItem $env:USERPROFILE\.jira-pr-summary
Get-Content $env:USERPROFILE\.jira-pr-summary\config.json
```

## Core Functionality Testing

### Test 3: Repository Detection

**All Platforms:**
```bash
# From within a git repository
cd path/to/your/git/repo
jira-pr-summary --verbose
```

**Expected Result:**
- Tool detects repository from git config
- Displays: `📍 Using repository: owner/repo-name`
- Works with both `upstream` and `origin` remotes

### Test 4: GitHub CLI Integration

**All Platforms:**
```bash
# List recent PRs (requires --repo if not in git directory)
jira-pr-summary --list-only --repo owner/repo-name --days 7
```

**Expected Result:**
- Tool successfully calls `gh` CLI
- Lists merged PRs from the last 7 days
- No errors about gh not found

### Test 5: Jira API Operations

**All Platforms:**
```bash
# Show current configuration
jira-pr-summary --show-config

# Test Jira connectivity by running update mode
jira-pr-summary --update
```

**Expected Result:**
- Configuration displays correctly
- Jira API authentication works
- Issues are fetched (if any match your filters)

### Test 6: Cache Operations

**All Platforms:**
```bash
# View cache
jira-pr-summary --show-cache

# Clear cache (with confirmation)
jira-pr-summary --clear-cache
```

**Expected Result:**
- Cache file location displayed
- Cache contents shown or "Cache is empty" message
- Clear operation works with confirmation prompt

## Platform-Specific Testing

### Test 7: Ollama Integration (Platform-Specific Install Instructions)

**macOS:**
```bash
# Verify Ollama installation message
jira-pr-summary --pr <PR_NUMBER> --ai
# If Ollama not installed, should show: "brew install ollama && ollama pull llama3.2:3b"
```

**Linux:**
```bash
# Verify Ollama installation message
jira-pr-summary --pr <PR_NUMBER> --ai
# If Ollama not installed, should show: "curl -fsSL https://ollama.com/install.sh | sh && ollama pull llama3.2:3b"
```

**Windows:**
```powershell
# Verify Ollama installation message
jira-pr-summary --pr <PR_NUMBER> --ai
# If Ollama not installed, should show Windows-specific instructions
```

**Expected Result:**
- Platform-appropriate installation instructions displayed
- If Ollama is installed and running, AI summary generation works

### Test 8: GitHub CLI Installation Messages

**All Platforms:**
```bash
# Temporarily rename gh to simulate missing dependency
# macOS/Linux:
sudo mv $(which gh) $(which gh).bak

# Windows (PowerShell as Admin):
# Rename-Item (Get-Command gh).Source gh.exe.bak

# Then run the tool
jira-pr-summary --pr 123 --repo owner/repo

# Restore gh
# macOS/Linux:
sudo mv $(which gh).bak $(which gh)

# Windows:
# Rename-Item gh.exe.bak gh.exe
```

**Expected Result:**
- Platform-appropriate gh installation instructions displayed
- macOS: Shows `brew install gh`
- Linux: Shows link to Linux installation guide
- Windows: Shows `winget install --id GitHub.cli`

### Test 9: Path Handling

**All Platforms:**
Test that paths work correctly with spaces and special characters.

**Create test directory:**
```bash
# macOS/Linux:
mkdir -p "/tmp/test path/jira-test"
cd "/tmp/test path/jira-test"

# Windows:
New-Item -ItemType Directory -Path "$env:TEMP\test path\jira-test"
cd "$env:TEMP\test path\jira-test"

# Initialize git repo
git init
git config user.name "Test User"
git config user.email "test@example.com"

# Run tool
jira-pr-summary --show-config
```

**Expected Result:**
- No errors related to path parsing
- Config directory created successfully
- Tool runs without issues

### Test 10: Line Endings

**Windows-Specific:**
Ensure the tool handles CRLF line endings correctly.

```powershell
# Check config file line endings
Get-Content $env:USERPROFILE\.jira-pr-summary\config.json -Raw | Format-Hex | Select-Object -First 20
```

**Expected Result:**
- JSON files are valid regardless of line endings
- Tool reads and writes config correctly

## Known Platform Differences

### File Paths

| Platform | Config Location | Path Separator |
|----------|-----------------|----------------|
| macOS/Linux | `~/.jira-pr-summary/` | `/` |
| Windows | `%USERPROFILE%\.jira-pr-summary\` | `\` |

**Note:** The tool uses Python's `pathlib.Path` which handles these differences automatically.

### Line Endings

- **Unix/Linux/macOS:** LF (`\n`)
- **Windows:** CRLF (`\r\n`)

**Impact:** None - Python handles line endings transparently.

### Shell Commands

Some shell-specific commands in documentation are platform-specific:
- `which` (Unix) vs `Get-Command` (PowerShell) vs `where` (Windows CMD)
- `rm -rf` (Unix) vs `Remove-Item -Recurse` (PowerShell) vs `rmdir /s` (Windows CMD)

### Process Management

Ollama status checking uses platform-specific commands:
- **macOS:** `brew services list | grep ollama`
- **Linux:** `systemctl status ollama` or `ps aux | grep ollama`
- **Windows:** Task Manager or visit `http://localhost:11434`

## Troubleshooting

### Common Issues

#### Issue: "gh: command not found"

**Solution:**
- macOS: `brew install gh`
- Linux: Follow [Linux installation guide](https://github.com/cli/cli/blob/trunk/docs/install_linux.md)
- Windows: `winget install --id GitHub.cli` or download from cli.github.com

#### Issue: "Permission denied" on Unix/Linux

**Solution:**
```bash
# Ensure script has execute permissions (shouldn't be needed with pip install)
chmod +x jira_pr_summary/cli.py
```

#### Issue: Python not in PATH (Windows)

**Solution:**
1. Reinstall Python with "Add Python to PATH" checked
2. Or manually add Python to PATH:
   - Right-click "This PC" → Properties → Advanced system settings
   - Environment Variables → System variables → PATH → Edit
   - Add: `C:\Users\<username>\AppData\Local\Programs\Python\Python3x\`

#### Issue: Ollama not responding

**macOS:**
```bash
brew services restart ollama
# Or check status:
brew services list | grep ollama
```

**Linux:**
```bash
sudo systemctl restart ollama
# Or check status:
systemctl status ollama
```

**Windows:**
- Open Task Manager
- End "Ollama" task if running
- Restart from Start menu or run: `ollama serve`

#### Issue: SSL Certificate errors (Corporate networks)

Some corporate networks use SSL inspection which can cause certificate errors.

**Solution:**
```bash
# Set SSL cert path (if your org provides one)
export REQUESTS_CA_BUNDLE=/path/to/company-ca-bundle.crt

# Or disable SSL verification (not recommended for production)
export PYTHONHTTPSVERIFY=0
```

## Testing Checklist

Use this checklist when testing on a new platform:

- [ ] Prerequisites installed (Python, pip, Git, gh)
- [ ] Tool installs without errors (`pip install -e .`)
- [ ] Command is in PATH (`jira-pr-summary --help`)
- [ ] Setup wizard runs successfully (`--setup`)
- [ ] Config directory created in correct location
- [ ] Repository detection works
- [ ] GitHub CLI integration works (`--list-only`)
- [ ] Jira API connectivity works (`--update`)
- [ ] Cache operations work (`--show-cache`, `--clear-cache`)
- [ ] Platform-specific messages display correctly
- [ ] Ollama integration works (if installed)
- [ ] Interactive prompts work correctly
- [ ] Uninstall process works cleanly

## Reporting Platform-Specific Issues

When reporting platform-specific issues, please include:

1. **Platform Information:**
   ```bash
   # macOS/Linux:
   uname -a
   python3 --version

   # Windows:
   systeminfo | findstr /B /C:"OS Name" /C:"OS Version"
   python --version
   ```

2. **Tool Version:**
   ```bash
   pip show jira-pr-summary
   ```

3. **Verbose Output:**
   ```bash
   jira-pr-summary --verbose [your command]
   ```

4. **Error Messages:**
   Include full error stack trace if available.

## Contributing Platform-Specific Fixes

When contributing platform-specific fixes:

1. Test on at least 2 of 3 platforms (macOS, Linux, Windows)
2. Use Python's cross-platform libraries:
   - `pathlib.Path` for file paths
   - `platform.system()` for OS detection
   - `subprocess` with `capture_output=True` for commands
3. Update this testing guide with new test cases
4. Add platform-specific tests to any test suite

## Resources

- [Python pathlib documentation](https://docs.python.org/3/library/pathlib.html)
- [Python platform documentation](https://docs.python.org/3/library/platform.html)
- [GitHub CLI installation](https://cli.github.com/)
- [Ollama installation](https://ollama.com)
