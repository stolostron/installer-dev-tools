#!/usr/bin/env python3
"""
Jira PR Summary - Generate and post progress summaries to Jira from merged PRs

This script:
1. Finds merged PRs with Jira issue keys in title/description (e.g., ACM-12345)
2. Checks if the issue is "In Progress"
3. Generates a summary of work done based on PR commits and changes
4. Posts the summary as a comment to Jira

Usage:
  # Check recently merged PRs and post summaries
  ./hack/jira-pr-summary.py

  # Process a specific PR by number
  ./hack/jira-pr-summary.py --pr 123

  # Process a specific issue (finds all merged PRs for that issue)
  ./hack/jira-pr-summary.py --issue ACM-12345

  # List recently merged PRs without posting
  ./hack/jira-pr-summary.py --list-only
"""

import argparse
import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from urllib.request import urlopen
from urllib.error import URLError

from .config import Config


class JiraPRSummary:
    # Built-in summary templates
    TEMPLATES = {
        "bugfix": {
            "name": "Bugfix - Fix issue with solution",
            "template": "Fixed {issue_description} by {approach}. The issue was caused by {root_cause}.",
            "variables": ["issue_description", "approach", "root_cause"],
            "ai_hints": {
                "issue_description": "What was broken or not working correctly",
                "approach": "How the issue was resolved",
                "root_cause": "Why the issue occurred"
            }
        },
        "feature": {
            "name": "Feature - Add new capability",
            "template": "Added {feature_name} that enables users to {benefit}. This includes {implementation_details}.",
            "variables": ["feature_name", "benefit", "implementation_details"],
            "ai_hints": {
                "feature_name": "Name of the new feature",
                "benefit": "What users can now do",
                "implementation_details": "Key technical changes"
            }
        },
        "refactor": {
            "name": "Refactor - Improve code quality",
            "template": "Refactored {component} to improve {improvement_type}. No functional changes.",
            "variables": ["component", "improvement_type"],
            "ai_hints": {
                "component": "What code was refactored",
                "improvement_type": "What was improved (readability, performance, maintainability)"
            }
        },
        "dependency": {
            "name": "Dependency Update",
            "template": "Updated {dependency} from {old_version} to {new_version}. {notes}",
            "variables": ["dependency", "old_version", "new_version", "notes"],
            "ai_hints": {
                "dependency": "Which dependency was updated",
                "old_version": "Previous version",
                "new_version": "New version",
                "notes": "Breaking changes or important notes (or 'No breaking changes')"
            }
        },
        "docs": {
            "name": "Documentation",
            "template": "Updated documentation for {topic}. {changes_summary}",
            "variables": ["topic", "changes_summary"],
            "ai_hints": {
                "topic": "What documentation is about",
                "changes_summary": "What changed in the docs"
            }
        },
        "test": {
            "name": "Test Addition",
            "template": "Added tests for {feature}. {coverage_info}",
            "variables": ["feature", "coverage_info"],
            "ai_hints": {
                "feature": "What is being tested",
                "coverage_info": "Test coverage details or scope"
            }
        }
    }

    @staticmethod
    def _get_ollama_install_instructions() -> str:
        """Get OS-specific instructions for installing Ollama"""
        system = platform.system()
        if system == "Darwin":  # macOS
            return "brew install ollama && ollama pull llama3.2:3b"
        elif system == "Linux":
            return "curl -fsSL https://ollama.com/install.sh | sh && ollama pull llama3.2:3b"
        elif system == "Windows":
            return "Download from https://ollama.com/download/windows and run installer, then: ollama pull llama3.2:3b"
        else:
            return "Visit https://ollama.com for installation instructions"

    @staticmethod
    def _get_gh_install_instructions() -> str:
        """Get OS-specific instructions for installing GitHub CLI"""
        system = platform.system()
        if system == "Darwin":  # macOS
            return "brew install gh"
        elif system == "Linux":
            return "See: https://github.com/cli/cli/blob/trunk/docs/install_linux.md"
        elif system == "Windows":
            return "winget install --id GitHub.cli OR download from https://cli.github.com/"
        else:
            return "Visit https://cli.github.com for installation instructions"

    @staticmethod
    def _get_ollama_check_instructions() -> str:
        """Get OS-specific instructions for checking Ollama status"""
        system = platform.system()
        if system == "Darwin":  # macOS
            return "brew services list | grep ollama"
        elif system == "Linux":
            return "systemctl status ollama OR ps aux | grep ollama"
        elif system == "Windows":
            return "Check Task Manager for ollama.exe OR visit http://localhost:11434"
        else:
            return "Visit http://localhost:11434 in your browser"

    def __init__(self, use_ai: bool = False, repo: Optional[str] = None, config: Optional[Config] = None, include_commits: bool = False, verbose: bool = False):
        # Use provided config or create new one
        self.config_manager = config or Config()
        self.verbose = verbose

        # Get settings from config
        self.token = self.config_manager.get('jira_token')
        if not self.token:
            print("❌ Error: Jira token not configured. Run setup first.")
            sys.exit(1)

        self.jira_base = self.config_manager.get('jira_base', 'https://issues.redhat.com')
        pattern_str = self.config_manager.get('issue_pattern', r'\b(ACM-\d+)\b')
        self.issue_pattern = re.compile(pattern_str, re.IGNORECASE)

        if self.verbose:
            print(f"🔍 [DEBUG] Using Jira base: {self.jira_base}")
            print(f"🔍 [DEBUG] Issue pattern: {pattern_str}")

        self.use_ai = use_ai
        self.ollama_available = False
        self.repo = repo
        self.include_commits = include_commits
        self.cache_file = str(self.config_manager.cache_file)
        self.cache = self._load_cache()

        # Auto-detect repo if not specified
        if not self.repo:
            # Try to detect from current directory
            self.repo = self._detect_repo()
            if not self.repo:
                # Fall back to default from config
                self.repo = self.config_manager.get('default_repo')

            if self.repo:
                print(f"📍 Using repository: {self.repo}")
            elif not repo:
                # Will require --repo flag for operations that need it
                # Or show interactive selector if in interactive mode
                pass

        # Track repo usage if we have a repo
        if self.repo:
            self._update_repo_history(self.repo)

        # Check for Ollama if AI is requested
        if self.use_ai:
            print("🤖 Checking for Ollama...")
            self.ollama_available = self._check_ollama_available()
            if self.ollama_available:
                print("   ✅ Ollama is available - AI summaries enabled")
            else:
                print("   ⚠️  Ollama not found - falling back to keyword-based summaries")
                print(f"   💡 Install Ollama: {self._get_ollama_install_instructions()}")
                self.use_ai = False

    def _detect_repo(self) -> Optional[str]:
        """Detect the repository from git config (cached per directory)"""
        # Get current working directory for cache key
        try:
            cwd = os.getcwd()
        except:
            cwd = None

        # Check cache first
        if cwd:
            if '_repo_detection' not in self.cache:
                self.cache['_repo_detection'] = {}

            cached_repo = self.cache['_repo_detection'].get(cwd)
            if cached_repo:
                if self.verbose:
                    print(f"🔍 [DEBUG] Using cached repo detection: {cached_repo}")
                return cached_repo

        # Not in cache - detect from git
        if self.verbose:
            print(f"🔍 [DEBUG] Detecting repository from git config...")

        try:
            remotes = {}

            # Check for upstream
            result = subprocess.run(
                ['git', 'config', '--get', 'remote.upstream.url'],
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode == 0:
                url = result.stdout.strip()
                repo = self._parse_github_repo(url)
                if repo:
                    remotes['upstream'] = repo

            # Check for origin
            result = subprocess.run(
                ['git', 'config', '--get', 'remote.origin.url'],
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode == 0:
                url = result.stdout.strip()
                repo = self._parse_github_repo(url)
                if repo:
                    remotes['origin'] = repo

            detected_repo = None

            # If both exist and are different, prompt user
            if 'upstream' in remotes and 'origin' in remotes and remotes['upstream'] != remotes['origin']:
                print("\n🔍 Found multiple git remotes:")
                print(f"  1. upstream: {remotes['upstream']}")
                print(f"  2. origin:   {remotes['origin']}")
                choice = input("\nWhich repository to use for PRs? (1/2) [1]: ").strip() or "1"

                if choice == "2":
                    detected_repo = remotes['origin']
                else:
                    detected_repo = remotes['upstream']
            # If only upstream exists, use it
            elif 'upstream' in remotes:
                detected_repo = remotes['upstream']
            # Otherwise use origin
            elif 'origin' in remotes:
                detected_repo = remotes['origin']

            # Cache the detected repo for this directory
            if detected_repo and cwd:
                if '_repo_detection' not in self.cache:
                    self.cache['_repo_detection'] = {}
                self.cache['_repo_detection'][cwd] = detected_repo
                if self.verbose:
                    print(f"🔍 [DEBUG] Cached repo detection for {cwd}: {detected_repo}")
                self._save_cache()

            return detected_repo

        except Exception:
            pass

        return None

    def _parse_github_repo(self, url: str) -> Optional[str]:
        """Parse owner/repo from GitHub URL"""
        # Handle both SSH and HTTPS URLs
        # SSH: git@github.com:owner/repo.git
        # HTTPS: https://github.com/owner/repo.git

        if 'github.com' not in url:
            return None

        if url.startswith('git@github.com:'):
            path = url.replace('git@github.com:', '').replace('.git', '')
            return path
        elif 'github.com/' in url:
            path = url.split('github.com/')[-1].replace('.git', '')
            return path

        return None

    def _run_command(self, cmd: List[str]) -> Optional[str]:
        """Run a shell command and return output"""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except FileNotFoundError:
            if cmd[0] == 'gh':
                print(f"❌ GitHub CLI (gh) not found")
                print(f"   Install it: {self._get_gh_install_instructions()}")
            else:
                print(f"❌ Command not found: {cmd[0]}")
            return None
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.strip() if e.stderr else ""

            # Better gh CLI error messages
            if cmd[0] == 'gh':
                if 'not logged' in stderr.lower() or 'authentication' in stderr.lower():
                    print(f"❌ GitHub CLI not authenticated")
                    print(f"   Run: gh auth login")
                elif 'not found' in stderr.lower() and '--repo' not in cmd:
                    print(f"❌ Could not find repository or PR")
                    print(f"   Make sure you're in a git repository or use --repo flag")
                else:
                    print(f"❌ GitHub CLI error: {stderr}")
            else:
                print(f"❌ Command failed: {' '.join(cmd)}")
                print(f"   Error: {stderr}")
            return None

    def _jira_request(self, endpoint: str, method: str = "GET", data: dict = None) -> dict:
        """Make a request to Jira API"""
        import urllib.request
        import urllib.error

        url = f"{self.jira_base}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        if self.verbose:
            print(f"🔍 [DEBUG] Jira API {method} {endpoint}")
            if data:
                print(f"🔍 [DEBUG] Request data: {json.dumps(data, indent=2)}")

        req_data = json.dumps(data).encode('utf-8') if data else None
        request = urllib.request.Request(url, data=req_data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(request) as response:
                response_body = response.read().decode('utf-8')
                # Handle empty responses (e.g., 204 No Content for transitions)
                if not response_body or response_body.strip() == '':
                    # Return a truthy value to indicate success
                    return {'success': True}
                return json.loads(response_body)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                print(f"❌ Jira authentication failed (401 Unauthorized)")
                print(f"   Your token may be expired or invalid")
                print(f"   Run: jira-pr-summary --setup")
            elif e.code == 403:
                print(f"❌ Jira access forbidden (403)")
                print(f"   You may not have permission to access this issue")
            elif e.code == 404:
                print(f"❌ Jira issue not found (404)")
                print(f"   URL: {url}")
            else:
                print(f"❌ Jira API error (HTTP {e.code}): {e.reason}")
            return {}
        except urllib.error.URLError as e:
            print(f"❌ Network error connecting to Jira")
            print(f"   {e.reason}")
            print(f"   Check your internet connection or Jira base URL")
            return {}
        except Exception as e:
            print(f"❌ Unexpected error making Jira request: {e}")
            return {}

    def _load_cache(self) -> Dict:
        """Load the cache file tracking posted PRs, filtering out expired entries"""
        # Use cache file from config manager for consistency
        cache_file = self.cache_file

        # Migrate from old cache location if needed
        old_cache_file = os.path.expanduser("~/.jira-pr-summary-cache.json")
        if not os.path.exists(cache_file) and os.path.exists(old_cache_file):
            try:
                # Copy old cache to new location
                import shutil
                os.makedirs(os.path.dirname(cache_file), exist_ok=True)
                shutil.copy2(old_cache_file, cache_file)
                if self.verbose:
                    print(f"🔍 [DEBUG] Migrated cache from {old_cache_file} to {cache_file}")
            except Exception as e:
                if self.verbose:
                    print(f"⚠️  Could not migrate old cache file: {e}")

        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    cache = json.load(f)

                # Get cache expiry setting (0 = never expire)
                expiry_days = self.config_manager.get('cache_expiry_days', 90)

                if self.verbose:
                    print(f"🔍 [DEBUG] Cache expiry: {expiry_days} days (0 = never)")

                if expiry_days == 0:
                    # Never expire - return full cache
                    if self.verbose:
                        total_entries = sum(len(prs) for key, prs in cache.items() if not key.startswith('_') and isinstance(prs, dict))
                        print(f"🔍 [DEBUG] Loaded {total_entries} cache entries (no expiration)")
                    return cache

                # Filter out expired entries
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=expiry_days)
                if self.verbose:
                    print(f"🔍 [DEBUG] Filtering cache entries older than {cutoff_date.strftime('%Y-%m-%d')}")
                filtered_cache = {}

                for issue_key, prs in cache.items():
                    # Skip special cache keys (like _repo_history)
                    if issue_key.startswith('_'):
                        filtered_cache[issue_key] = prs
                        continue

                    filtered_prs = {}
                    for pr_num, pr_info in prs.items():
                        timestamp = pr_info.get('timestamp')
                        if timestamp:
                            try:
                                pr_date = datetime.fromisoformat(timestamp)
                                if pr_date >= cutoff_date:
                                    filtered_prs[pr_num] = pr_info
                            except:
                                # Keep if we can't parse date
                                filtered_prs[pr_num] = pr_info
                        else:
                            # Keep if no timestamp
                            filtered_prs[pr_num] = pr_info

                    if filtered_prs:
                        filtered_cache[issue_key] = filtered_prs

                # Save filtered cache back to disk
                if filtered_cache != cache:
                    # Count only issue entries (not special keys like _repo_history)
                    original_count = sum(len(prs) for key, prs in cache.items() if not key.startswith('_') and isinstance(prs, dict))
                    filtered_count = sum(len(prs) for key, prs in filtered_cache.items() if not key.startswith('_') and isinstance(prs, dict))
                    removed_count = original_count - filtered_count

                    if self.verbose and removed_count > 0:
                        print(f"🔍 [DEBUG] Removed {removed_count} expired cache entries")

                    try:
                        with open(cache_file, 'w') as f:
                            json.dump(filtered_cache, f, indent=2)
                    except:
                        pass  # Continue even if save fails
                elif self.verbose:
                    total_entries = sum(len(prs) for key, prs in filtered_cache.items() if not key.startswith('_') and isinstance(prs, dict))
                    print(f"🔍 [DEBUG] Loaded {total_entries} cache entries (none expired)")

                return filtered_cache
            except:
                return {}
        return {}

    def _save_cache(self) -> None:
        """Save the cache file"""
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(self.cache, f, indent=2)
        except Exception as e:
            print(f"⚠️  Warning: Could not save cache file: {e}")

    def _is_pr_cached(self, issue_key: str, pr_number: int) -> bool:
        """Check if a PR has already been posted for this issue"""
        issue_key = issue_key.upper()
        return issue_key in self.cache and str(pr_number) in self.cache[issue_key]

    def _get_cached_info(self, issue_key: str, pr_number: int) -> Optional[Dict]:
        """Get cached information about a previously posted PR"""
        issue_key = issue_key.upper()
        if self._is_pr_cached(issue_key, pr_number):
            return self.cache[issue_key][str(pr_number)]
        return None

    def _update_cache(self, issue_key: str, pr_number: int, pr_url: str) -> None:
        """Update the cache with a newly posted PR"""
        issue_key = issue_key.upper()
        if issue_key not in self.cache:
            self.cache[issue_key] = {}

        self.cache[issue_key][str(pr_number)] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pr_url": pr_url
        }
        self._save_cache()

    def _get_repo_history(self) -> List[str]:
        """Get list of recently used repositories from cache"""
        if '_repo_history' not in self.cache:
            return []
        return self.cache.get('_repo_history', [])

    def _get_pr_cache_key(self, pr_number: int, repo: str = None) -> str:
        """Generate cache key for a PR"""
        repo = repo or self.repo
        if not repo:
            return None
        return f"{repo}#{pr_number}"

    def _get_cached_pr(self, pr_number: int, repo: str = None) -> Optional[Dict]:
        """Get cached PR details if available"""
        cache_key = self._get_pr_cache_key(pr_number, repo)
        if not cache_key:
            return None

        if '_pr_cache' not in self.cache:
            return None

        cached_pr = self.cache['_pr_cache'].get(cache_key)
        if cached_pr:
            if self.verbose:
                print(f"🔍 [DEBUG] Using cached PR #{pr_number} from {repo}")
            return cached_pr

        return None

    def _cache_pr(self, pr: Dict, repo: str = None) -> None:
        """Cache PR details (merged PRs don't change, so no TTL)"""
        if not pr or 'number' not in pr:
            return

        pr_number = pr['number']
        cache_key = self._get_pr_cache_key(pr_number, repo)
        if not cache_key:
            return

        if '_pr_cache' not in self.cache:
            self.cache['_pr_cache'] = {}

        # Store full PR details with timestamp
        self.cache['_pr_cache'][cache_key] = {
            **pr,
            'cached_at': datetime.now(timezone.utc).isoformat()
        }

        if self.verbose:
            print(f"🔍 [DEBUG] Cached PR #{pr_number} for {repo}")

        self._save_cache()

    def _get_cached_issue_metadata(self, issue_key: str, ttl_seconds: int = 300) -> Optional[Dict]:
        """Get cached Jira issue metadata if available and not expired (default TTL: 5 min)"""
        issue_key = issue_key.upper()

        if '_jira_cache' not in self.cache:
            return None

        cached_data = self.cache['_jira_cache'].get(issue_key)
        if not cached_data:
            return None

        # Check if expired
        cached_at = cached_data.get('cached_at')
        if not cached_at:
            return None

        try:
            cached_time = datetime.fromisoformat(cached_at)
            now = datetime.now(timezone.utc)
            age_seconds = (now - cached_time).total_seconds()

            if age_seconds > ttl_seconds:
                if self.verbose:
                    print(f"🔍 [DEBUG] Jira cache for {issue_key} expired ({int(age_seconds)}s old, TTL: {ttl_seconds}s)")
                return None

            if self.verbose:
                print(f"🔍 [DEBUG] Using cached Jira metadata for {issue_key} ({int(age_seconds)}s old)")

            return cached_data
        except:
            return None

    def _cache_issue_metadata(self, issue_key: str, status: str = None, labels: List[str] = None,
                              summary: str = None, assignee: str = None) -> None:
        """Cache Jira issue metadata with timestamp for TTL"""
        issue_key = issue_key.upper()

        if '_jira_cache' not in self.cache:
            self.cache['_jira_cache'] = {}

        # Get existing cache or create new
        cached_data = self.cache['_jira_cache'].get(issue_key, {})

        # Update only provided fields
        if status is not None:
            cached_data['status'] = status
        if labels is not None:
            cached_data['labels'] = labels
        if summary is not None:
            cached_data['summary'] = summary
        if assignee is not None:
            cached_data['assignee'] = assignee

        # Update timestamp
        cached_data['cached_at'] = datetime.now(timezone.utc).isoformat()

        self.cache['_jira_cache'][issue_key] = cached_data

        if self.verbose:
            print(f"🔍 [DEBUG] Cached Jira metadata for {issue_key}")

        self._save_cache()

    def _invalidate_issue_cache(self, issue_key: str) -> None:
        """Invalidate cached issue metadata (e.g., after status transition)"""
        issue_key = issue_key.upper()

        if '_jira_cache' in self.cache and issue_key in self.cache['_jira_cache']:
            del self.cache['_jira_cache'][issue_key]
            if self.verbose:
                print(f"🔍 [DEBUG] Invalidated cache for {issue_key}")
            self._save_cache()

    def _update_repo_history(self, repo: str) -> None:
        """Track repository usage in cache"""
        if not repo:
            return

        # Validate repo format (must be owner/repo)
        if '/' not in repo or repo.startswith('✕') or repo.startswith('➕'):
            return

        if '_repo_history' not in self.cache:
            self.cache['_repo_history'] = []

        history = self.cache['_repo_history']

        # Remove repo if already in list (we'll add it to the front)
        if repo in history:
            history.remove(repo)

        # Add to front of list
        history.insert(0, repo)

        # Keep only last 10 repos
        self.cache['_repo_history'] = history[:10]
        self._save_cache()

    def _select_repo_interactive(self) -> Optional[str]:
        """Show interactive menu to select from previously used repos or enter new one"""
        repo_history = self._get_repo_history()

        try:
            import questionary
            from questionary import Choice

            # If no history, directly prompt for custom repo
            if not repo_history:
                print("\nℹ️  No repository detected from current directory")
                print("   No repository history found (cache may be empty)")
                print()

                custom_repo = questionary.text(
                    "Enter repository (owner/repo):",
                    validate=lambda text: '/' in text or "Repository must be in format: owner/repo"
                ).ask()

                return custom_repo if custom_repo else None

            print()  # Add spacing
            choices = []

            # Add "all repos" option first
            choices.append(Choice(title="🌍 Show all my PRs (across all repos)", value="__all_repos__"))

            # Add repo history
            for repo in repo_history:
                choices.append(Choice(title=repo, value=repo))

            # Add custom option
            choices.append(Choice(title="➕ Enter custom repository", value="__custom__"))

            # Add cancel option
            choices.append(Choice(title="✕ Cancel", value=None))

            selected = questionary.select(
                "Select repository:",
                choices=choices,
                instruction="(Use arrow keys)",
                qmark="📦"
            ).ask()

            if selected is None:
                return None

            if selected == "__all_repos__":
                # Special marker to show PRs from all repos
                return "__all_repos__"

            if selected == "__custom__":
                # Custom repo
                custom_repo = questionary.text(
                    "Enter repository (owner/repo):",
                    validate=lambda text: '/' in text or "Repository must be in format: owner/repo"
                ).ask()
                return custom_repo if custom_repo else None

            return selected

        except ImportError:
            # Fallback to numbered menu if questionary not available
            # If no history, directly prompt for custom repo
            if not repo_history:
                print("\nℹ️  No repository detected from current directory")
                print("   No repository history found (cache may be empty)")
                print()
                custom_repo = input("Enter repository (owner/repo): ").strip()
                if custom_repo and '/' in custom_repo:
                    return custom_repo
                else:
                    print("❌ Invalid repository format. Use: owner/repo")
                    return None

            print("\n" + "=" * 70)
            print("SELECT REPOSITORY")
            print("=" * 70)
            print("\nRecently used repositories:")

            for i, repo in enumerate(repo_history, 1):
                print(f"  {i}. {repo}")

            print(f"  {len(repo_history) + 1}. Enter custom repository")
            print("  0. Cancel")

            print("\n" + "-" * 70)
            choice = input("Select repository (number): ").strip()

            if not choice or choice == "0":
                return None

            try:
                choice_num = int(choice)
                if 1 <= choice_num <= len(repo_history):
                    return repo_history[choice_num - 1]
                elif choice_num == len(repo_history) + 1:
                    # Custom repo
                    custom_repo = input("Enter repository (owner/repo): ").strip()
                    if custom_repo and '/' in custom_repo:
                        return custom_repo
                    else:
                        print("❌ Invalid repository format. Use: owner/repo")
                        return None
                else:
                    print("❌ Invalid selection")
                    return None
            except ValueError:
                print("❌ Invalid input")
                return None

    def get_issue_status(self, issue_key: str) -> Optional[str]:
        """Get the current status of a Jira issue (cached with 5-min TTL)"""
        # Check cache first
        cached = self._get_cached_issue_metadata(issue_key)
        if cached and 'status' in cached:
            return cached['status']

        # Not in cache - fetch from Jira
        if self.verbose:
            print(f"🔍 [DEBUG] Fetching issue status from Jira for {issue_key}...")

        data = self._jira_request(f"/rest/api/2/issue/{issue_key}?fields=status,summary,labels,assignee")
        if data and 'fields' in data:
            status = data['fields']['status']['name']
            summary = data['fields'].get('summary')
            labels = data['fields'].get('labels', [])
            assignee = data['fields'].get('assignee', {}).get('name') if data['fields'].get('assignee') else None

            # Cache all fetched metadata
            self._cache_issue_metadata(issue_key, status=status, labels=labels,
                                      summary=summary, assignee=assignee)
            return status
        return None

    def get_issue_labels(self, issue_key: str) -> List[str]:
        """Get labels for a Jira issue (cached with 5-min TTL)"""
        # Check cache first
        cached = self._get_cached_issue_metadata(issue_key)
        if cached and 'labels' in cached:
            return cached['labels']

        # Not in cache - fetch from Jira
        if self.verbose:
            print(f"🔍 [DEBUG] Fetching issue labels from Jira for {issue_key}...")

        data = self._jira_request(f"/rest/api/2/issue/{issue_key}?fields=labels,status,summary,assignee")
        if data and 'fields' in data:
            labels = data['fields'].get('labels', [])
            status = data['fields']['status']['name']
            summary = data['fields'].get('summary')
            assignee = data['fields'].get('assignee', {}).get('name') if data['fields'].get('assignee') else None

            # Cache all fetched metadata
            self._cache_issue_metadata(issue_key, status=status, labels=labels,
                                      summary=summary, assignee=assignee)
            return labels
        return []

    def get_issue_summary(self, issue_key: str) -> Optional[str]:
        """Get the summary/title of a Jira issue (cached with 5-min TTL)"""
        # Check cache first
        cached = self._get_cached_issue_metadata(issue_key)
        if cached and 'summary' in cached:
            return cached['summary']

        # Not in cache - fetch from Jira
        if self.verbose:
            print(f"🔍 [DEBUG] Fetching issue summary from Jira for {issue_key}...")

        data = self._jira_request(f"/rest/api/2/issue/{issue_key}?fields=summary,status,labels,assignee")
        if data and 'fields' in data:
            summary = data['fields'].get('summary')
            status = data['fields']['status']['name']
            labels = data['fields'].get('labels', [])
            assignee = data['fields'].get('assignee', {}).get('name') if data['fields'].get('assignee') else None

            # Cache all fetched metadata
            self._cache_issue_metadata(issue_key, status=status, labels=labels,
                                      summary=summary, assignee=assignee)
            return summary
        return None

    def get_available_transitions(self, issue_key: str) -> List[Dict]:
        """Get available status transitions for an issue"""
        data = self._jira_request(f"/rest/api/2/issue/{issue_key}/transitions")
        if data and 'transitions' in data:
            return data['transitions']
        return []

    def transition_issue(self, issue_key: str, transition_id: str) -> bool:
        """Transition an issue to a new status"""
        data = {"transition": {"id": transition_id}}
        result = self._jira_request(f"/rest/api/2/issue/{issue_key}/transitions", method="POST", data=data)

        # Invalidate cache after successful transition
        if result:
            self._invalidate_issue_cache(issue_key)

        return bool(result)

    def find_transition_by_name(self, issue_key: str, target_status: str) -> Optional[str]:
        """Find transition ID for a target status"""
        transitions = self.get_available_transitions(issue_key)
        for transition in transitions:
            if transition['to']['name'].lower() == target_status.lower():
                return transition['id']
        return None

    def offer_status_transition(self, issue_key: str, current_status: str, pr_merged: bool) -> None:
        """Offer to transition issue status based on current state"""
        # If in New or Backlog, offer to move to In Progress
        if current_status in ['New', 'Backlog', 'To Do', 'Open']:
            choice = input(f"\n💡 Issue is in '{current_status}'. Move to 'In Progress'? (y/N): ").strip().lower()
            if choice == 'y':
                transition_id = self.find_transition_by_name(issue_key, 'In Progress')
                if transition_id:
                    if self.transition_issue(issue_key, transition_id):
                        print(f"   ✅ Transitioned {issue_key} to 'In Progress'")
                    else:
                        print(f"   ❌ Failed to transition {issue_key}")
                else:
                    print(f"   ⚠️  'In Progress' transition not available")

        # If PR is merged, offer to move to Review
        if pr_merged and current_status in ['In Progress', 'New', 'Backlog', 'To Do', 'Open']:
            choice = input(f"\n💡 PR is merged. Move issue to 'Review'? (y/N): ").strip().lower()
            if choice == 'y':
                transition_id = self.find_transition_by_name(issue_key, 'Review')
                if transition_id:
                    if self.transition_issue(issue_key, transition_id):
                        print(f"   ✅ Transitioned {issue_key} to 'Review'")
                    else:
                        print(f"   ❌ Failed to transition {issue_key}")
                else:
                    print(f"   ⚠️  'Review' transition not available")

    def _generate_ai_closing_summary(self, issue_key: str) -> Optional[str]:
        """Generate AI-powered closing summary based on issue history and PRs"""
        try:
            print(f"   🤖 Generating AI closing summary...")

            # Get issue summary/description
            issue_data = self._jira_request(f"/rest/api/2/issue/{issue_key}")
            if not issue_data:
                return None

            issue_summary = issue_data.get('fields', {}).get('summary', '')
            issue_description = issue_data.get('fields', {}).get('description', '')

            # Get comments
            comments = []
            if 'fields' in issue_data and 'comment' in issue_data['fields']:
                for comment in issue_data['fields']['comment'].get('comments', [])[:5]:  # Last 5 comments
                    body = comment.get('body', '').strip()
                    if body and len(body) < 200:  # Only short comments
                        comments.append(body)

            # Find related PRs from cache
            cache = self._load_cache()
            prs_info = []
            if issue_key in cache:
                for pr_num, pr_data in cache[issue_key].items():
                    if pr_num != 'summary':
                        pr_url = pr_data.get('pr_url', '')
                        if pr_url:
                            # Extract PR number from URL
                            import re
                            match = re.search(r'/pull/(\d+)$', pr_url)
                            if match:
                                pr_number = int(match.group(1))
                                pr = self.get_pr_details(pr_number)
                                if pr:
                                    prs_info.append({
                                        'number': pr_number,
                                        'title': pr.get('title', ''),
                                        'body': pr.get('body', '')[:200] if pr.get('body') else ''
                                    })

            # Build context for AI
            context_parts = [f"Issue: {issue_key} - {issue_summary}"]

            if issue_description and len(issue_description) < 500:
                context_parts.append(f"\nDescription:\n{issue_description[:500]}")

            if prs_info:
                pr_list = '\n'.join([
                    f"- PR #{pr['number']}: {pr['title']}"
                    for pr in prs_info[:3]  # Max 3 PRs
                ])
                context_parts.append(f"\nMerged PRs:\n{pr_list}")

            if comments:
                comments_text = '\n'.join([f"- {c}" for c in comments[:3]])
                context_parts.append(f"\nRecent comments:\n{comments_text}")

            context = '\n'.join(context_parts)

            # Prompt for Ollama
            prompt = f"""Based on this Jira issue and its activity, write a concise 2-3 sentence closing summary that explains what was accomplished or the resolution.

{context}

Closing Summary:"""

            # Call Ollama API
            data = {
                "model": "llama3.2:3b",
                "prompt": prompt,
                "stream": False
            }

            import urllib.request
            req = urllib.request.Request(
                'http://localhost:11434/api/generate',
                data=json.dumps(data).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )

            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                ai_summary = result.get('response', '').strip()
                print(f"   ✅ AI summary generated")
                return ai_summary

        except Exception as e:
            print(f"   ⚠️  AI closing summary failed: {e}")
            print(f"   Falling back to manual summary")
            return None

    def close_issue(self, issue_key: str, closing_summary: str = None, use_ai: bool = False,
                   dry_run: bool = False) -> bool:
        """Close an issue with a required summary comment"""
        print(f"\n{'='*70}")
        print(f"Closing {issue_key}")
        print('='*70)

        # Get current status
        print(f"\n📋 Checking {issue_key}...")
        status = self.get_issue_status(issue_key)
        if not status:
            print(f"   ❌ Could not fetch status for {issue_key}")
            return False

        print(f"   Status: {status}")

        # Check if already closed
        if self._is_issue_resolved(status):
            print(f"   ⚠️  Issue is already {status}")
            choice = input(f"\nIssue is already closed. Continue anyway? (y/N): ").strip().lower()
            if choice != 'y':
                print(f"   ⏭️  Skipping {issue_key}")
                return False

        # Generate or prompt for closing summary if not provided
        if not closing_summary:
            if use_ai:
                # Try to generate AI summary
                ai_summary = self._generate_ai_closing_summary(issue_key)
                if ai_summary:
                    print(f"\n📝 AI-GENERATED CLOSING SUMMARY")
                    print("=" * 70)
                    print(ai_summary)
                    print("=" * 70)
                    print("\nYou can edit this summary before posting.")
                    print("Options:")
                    print("  1. Use as-is (press Enter)")
                    print("  2. Edit the summary")
                    print("  3. Write from scratch")
                    choice = input("\nYour choice (1-3) [1]: ").strip()

                    if choice == '2':
                        # Edit the AI summary
                        print("\nEdit the summary below. Press Enter twice when done.")
                        print("-" * 70)
                        print(ai_summary)
                        print("-" * 70)
                        print("\nEnter your edits (or press Enter twice to keep as-is):")

                        lines = []
                        empty_count = 0
                        while True:
                            line = input()
                            if not line:
                                empty_count += 1
                                if empty_count >= 2 or (empty_count >= 1 and lines):
                                    break
                            else:
                                empty_count = 0
                                lines.append(line)

                        edited_summary = '\n'.join(lines).strip()
                        closing_summary = edited_summary if edited_summary else ai_summary
                    elif choice == '3':
                        # Write from scratch
                        closing_summary = None  # Will fall through to manual prompt
                    else:
                        # Use AI summary as-is
                        closing_summary = ai_summary

            # Manual prompt if no AI or user chose to write from scratch
            if not closing_summary:
                print(f"\n📝 Enter closing summary (required):")
                print("(Type your summary, then press Enter twice to finish)")
                print("-" * 70)

                lines = []
                empty_count = 0
                while True:
                    line = input()
                    if not line:
                        empty_count += 1
                        if empty_count >= 2 or (empty_count >= 1 and lines):
                            break
                    else:
                        empty_count = 0
                        lines.append(line)

                closing_summary = '\n'.join(lines).strip()

                if not closing_summary:
                    print("❌ Closing summary is required.")
                    return False

        # Show the final closing summary
        print(f"\n📝 CLOSING SUMMARY")
        print("=" * 70)
        print(closing_summary)
        print("=" * 70)

        # Find available close transitions
        transitions = self.get_available_transitions(issue_key)
        close_transitions = []
        for transition in transitions:
            target = transition['to']['name']
            if target in ['Done', 'Closed', 'Resolved']:
                close_transitions.append({
                    'id': transition['id'],
                    'name': target
                })

        if not close_transitions:
            print(f"\n   ❌ No closing transitions available for {issue_key}")
            print(f"   Available transitions: {[t['to']['name'] for t in transitions]}")
            return False

        # Select which transition to use
        if len(close_transitions) == 1:
            selected_transition = close_transitions[0]
            print(f"\n💡 Will transition to: {selected_transition['name']}")
        else:
            print(f"\n💡 Multiple close transitions available:")
            for idx, trans in enumerate(close_transitions):
                print(f"   {idx + 1}. {trans['name']}")

            while True:
                choice = input(f"\nSelect transition (1-{len(close_transitions)}): ").strip()
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(close_transitions):
                        selected_transition = close_transitions[idx]
                        break
                    else:
                        print(f"   ⚠️  Please enter a number between 1 and {len(close_transitions)}")
                except ValueError:
                    print(f"   ⚠️  Please enter a valid number")

        if dry_run:
            print(f"\n🔍 DRY RUN - Would post the above summary and transition to {selected_transition['name']}")
            print(f"✅ Preview complete (not posted)")
            return True

        # Post the closing summary as a comment
        print(f"\n📤 Posting closing summary...")
        if not self.post_comment(issue_key, closing_summary):
            print(f"   ❌ Failed to post closing summary")
            return False

        print(f"   ✅ Posted closing summary to {issue_key}")

        # Transition to closed status
        print(f"\n🔄 Transitioning to {selected_transition['name']}...")
        if self.transition_issue(issue_key, selected_transition['id']):
            print(f"   ✅ Transitioned {issue_key} to {selected_transition['name']}")
            print(f"\n{'='*70}")
            print(f"✅ {issue_key} closed successfully")
            print('='*70)
            return True
        else:
            print(f"   ❌ Failed to transition {issue_key}")
            return False

    def search_issues_jql(self, jql: str, max_results: int = 50) -> List[Dict]:
        """Search Jira issues using JQL"""
        if self.verbose:
            print(f"🔍 [DEBUG] JQL Query: {jql}")

        params = {
            "jql": jql,
            "maxResults": max_results,
            "fields": "summary,status,assignee,components"
        }
        import urllib.parse
        query_string = urllib.parse.urlencode(params)
        data = self._jira_request(f"/rest/api/2/search?{query_string}")

        if data and 'issues' in data:
            if self.verbose:
                print(f"🔍 [DEBUG] JQL returned {len(data['issues'])} issue(s)")
            return data['issues']

        if self.verbose:
            print(f"🔍 [DEBUG] JQL returned no results")
        return []

    def _build_component_jql(self, jira_component: str) -> str:
        """Build JQL component filter for single or multiple components"""
        if not jira_component:
            return None

        # Split by comma and clean up
        components = [c.strip() for c in jira_component.split(',')]

        if len(components) == 1:
            return f"component = '{components[0]}'"
        else:
            # Multiple components - use IN operator
            component_list = ", ".join(f"'{c}'" for c in components)
            return f"component IN ({component_list})"

    def _quote_jql_value(self, value: str) -> str:
        """Properly quote a value for use in JQL queries"""
        # If value contains special characters like @, space, etc., wrap in quotes
        # Otherwise, return as-is for simple usernames
        if '@' in value or ' ' in value or '-' in value:
            return f'"{value}"'
        return value

    def get_my_active_sprint_issues(self) -> List[Dict]:
        """Get issues assigned to configured user in active sprints"""
        jira_user = self.config_manager.get('jira_user')
        jira_component = self.config_manager.get('jira_component')

        if not jira_user:
            return []

        # Build JQL query
        jql_parts = [
            f"assignee = {self._quote_jql_value(jira_user)}",
            "sprint in openSprints()",
            "status NOT IN (Done, Closed, Resolved)"
        ]

        component_jql = self._build_component_jql(jira_component)
        if component_jql:
            jql_parts.append(component_jql)

        jql = " AND ".join(jql_parts)
        return self.search_issues_jql(jql)

    def get_my_issues(self, status: Optional[str] = None) -> List[Dict]:
        """Get issues assigned to configured user"""
        jira_user = self.config_manager.get('jira_user')
        jira_component = self.config_manager.get('jira_component')

        if not jira_user:
            return []

        # Build JQL query
        jql_parts = [f"assignee = {self._quote_jql_value(jira_user)}"]

        if status:
            jql_parts.append(f"status = '{status}'")
        else:
            jql_parts.append("status NOT IN (Done, Closed, Resolved)")

        component_jql = self._build_component_jql(jira_component)
        if component_jql:
            jql_parts.append(component_jql)

        jql = " AND ".join(jql_parts) + " ORDER BY updated DESC"
        return self.search_issues_jql(jql)

    def get_my_issue_keys(self, issue_keys: List[str]) -> set:
        """Filter issue keys to only those assigned to configured user"""
        jira_user = self.config_manager.get('jira_user')
        jira_component = self.config_manager.get('jira_component')

        # If no user configured, return all issues
        if not jira_user:
            return set(issue_keys)

        if not issue_keys:
            return set()

        # Build JQL to check which issues are assigned to user
        # Using issue key IN list
        issue_list = ", ".join(issue_keys)
        jql_parts = [
            f"key IN ({issue_list})",
            f"assignee = {self._quote_jql_value(jira_user)}"
        ]

        component_jql = self._build_component_jql(jira_component)
        if component_jql:
            jql_parts.append(component_jql)

        jql = " AND ".join(jql_parts)
        my_issues = self.search_issues_jql(jql, max_results=len(issue_keys))

        # Return set of issue keys that match
        return {issue['key'] for issue in my_issues}

    def filter_prs_by_author(self, prs: List[Dict], author: str) -> List[Dict]:
        """Filter PRs by author username"""
        if not author:
            return prs

        if self.verbose:
            print(f"🔍 [DEBUG] Filtering {len(prs)} PRs by author: {author}")

        filtered_prs = []
        for pr in prs:
            pr_author = pr.get('author', {}).get('login', '')
            if pr_author.lower() == author.lower():
                filtered_prs.append(pr)

        if self.verbose:
            print(f"🔍 [DEBUG] Filtered to {len(filtered_prs)} PR(s) by {author}")

        return filtered_prs

    def filter_prs_by_user(self, prs: List[Dict]) -> List[Dict]:
        """Filter PRs to only include those with at least one issue assigned to configured user"""
        jira_user = self.config_manager.get('jira_user')

        # If no user configured, return all PRs
        if not jira_user:
            if self.verbose:
                print(f"🔍 [DEBUG] No user filter configured, keeping all {len(prs)} PRs")
            return prs

        if self.verbose:
            print(f"🔍 [DEBUG] Filtering {len(prs)} PRs by user: {jira_user}")

        # Collect all unique issue keys from all PRs
        all_issue_keys = set()
        for pr in prs:
            all_issue_keys.update(pr.get('issue_keys', []))

        if not all_issue_keys:
            if self.verbose:
                print(f"🔍 [DEBUG] No issue keys found in PRs")
            return []

        # Get issue keys assigned to configured user
        my_issue_keys = self.get_my_issue_keys(list(all_issue_keys))

        if self.verbose:
            print(f"🔍 [DEBUG] Found {len(my_issue_keys)} issue(s) assigned to {jira_user}: {', '.join(my_issue_keys)}")

        # Filter PRs that have at least one issue assigned to user
        filtered_prs = []
        for pr in prs:
            pr_issue_keys = set(pr.get('issue_keys', []))
            if pr_issue_keys & my_issue_keys:  # Intersection - at least one match
                filtered_prs.append(pr)

        if self.verbose:
            print(f"🔍 [DEBUG] Filtered to {len(filtered_prs)} PR(s) assigned to user")

        return filtered_prs

    def find_merged_prs_all_repos(self, days: int = 7) -> List[Dict]:
        """Find merged PRs across ALL repositories for the configured GitHub user"""
        github_user = self.config_manager.get('github_user')

        if not github_user:
            print("❌ GitHub username not configured")
            print("   Run 'jira-pr-summary --setup' and configure your GitHub username")
            return []

        print(f"\n🔍 Searching for PRs by {github_user} across all repos (last {days} days)...")

        # Calculate date threshold
        date_threshold = datetime.now(timezone.utc) - timedelta(days=days)
        date_str = date_threshold.strftime('%Y-%m-%d')

        # Use gh search to find PRs across all repos
        cmd = [
            'gh', 'search', 'prs',
            f'author:{github_user}',
            f'merged:>={date_str}',
            'is:merged',
            '--json', 'number,title,body,closedAt,url,author,repository',
            '--limit', '100'
        ]

        output = self._run_command(cmd)

        if not output:
            return []

        try:
            prs = json.loads(output)

            # Extract issue keys and add repo info
            result_prs = []
            for pr in prs:
                # Extract repository name from repository object
                repo_info = pr.get('repository', {})
                repo_name = repo_info.get('nameWithOwner', 'unknown/repo')

                # Extract issue keys from title and body
                issue_keys = self._extract_issue_keys(pr.get('title', ''), pr.get('body', ''))

                if issue_keys:
                    pr['issue_keys'] = issue_keys
                    pr['repo_name'] = repo_name
                    # Add mergedAt alias for compatibility (gh search uses closedAt)
                    pr['mergedAt'] = pr.get('closedAt')
                    result_prs.append(pr)

            if self.verbose:
                print(f"🔍 [DEBUG] Found {len(result_prs)} PRs across {len(set(pr['repo_name'] for pr in result_prs))} repositories")

            # Sort by closed date (most recent first)
            result_prs.sort(key=lambda x: x.get('closedAt', ''), reverse=True)

            return result_prs

        except json.JSONDecodeError:
            print("❌ Failed to parse GitHub response")
            return []

    def find_merged_prs(self, days: int = 7, issue_key: Optional[str] = None) -> List[Dict]:
        """Find recently merged PRs, optionally filtered by issue key"""
        # Get recently merged PRs - fetch more than needed since we'll filter by date
        limit = max(100, days * 10)  # Assume ~10 PRs per day max

        cmd = ['gh', 'pr', 'list', '--state', 'merged', '--limit', str(limit),
               '--json', 'number,title,body,mergedAt,url,author']

        if self.repo:
            cmd.extend(['-R', self.repo])

        output = self._run_command(cmd)

        if not output:
            return []

        try:
            prs = json.loads(output)

            # Calculate cutoff date
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

            # Filter by date and extract issue keys
            filtered_prs = []
            for pr in prs:
                # Parse merged date
                merged_at = pr.get('mergedAt')
                if not merged_at:
                    continue

                try:
                    merged_date = datetime.fromisoformat(merged_at.replace('Z', '+00:00'))
                    if merged_date < cutoff_date:
                        continue
                except:
                    continue

                # Extract issue keys
                pr['issue_keys'] = self._extract_issue_keys(pr['title'], pr.get('body', ''))

                # Add repository info
                pr['repository'] = self.repo

                # Filter by issue key if specified
                if issue_key:
                    if issue_key.upper() in pr['issue_keys']:
                        filtered_prs.append(pr)
                elif pr['issue_keys']:
                    # Only include PRs with issue keys
                    filtered_prs.append(pr)

            return filtered_prs
        except json.JSONDecodeError:
            print(f"❌ Failed to parse PR list")
            return []

    def get_pr_details(self, pr_number: int) -> Optional[Dict]:
        """Get detailed information about a specific PR (cached for performance)"""
        # Check cache first
        cached_pr = self._get_cached_pr(pr_number, self.repo)
        if cached_pr:
            # Remove cached_at before returning (internal metadata)
            pr_copy = cached_pr.copy()
            pr_copy.pop('cached_at', None)
            return pr_copy

        # Not in cache - fetch from GitHub
        if self.verbose:
            print(f"🔍 [DEBUG] Fetching PR #{pr_number} from GitHub...")

        cmd = ['gh', 'pr', 'view', str(pr_number), '--json',
               'number,title,body,mergedAt,url,author,commits,files']

        if self.repo:
            cmd.extend(['-R', self.repo])

        output = self._run_command(cmd)

        if not output:
            return None

        try:
            pr = json.loads(output)
            pr['issue_keys'] = self._extract_issue_keys(pr['title'], pr.get('body', ''))

            # Cache the PR details for future use
            self._cache_pr(pr, self.repo)

            return pr
        except json.JSONDecodeError:
            return None

    def _extract_issue_keys(self, title: str, body: str) -> List[str]:
        """Extract unique issue keys from PR title and body"""
        text = f"{title} {body}"
        matches = self.issue_pattern.findall(text)
        return list(set(m.upper() for m in matches))

    def _detect_pr_type(self, pr: Dict) -> Optional[str]:
        """
        Auto-detect PR type from title, labels, files, and commits.
        Returns template key (bugfix, feature, refactor, dependency, docs, test) or None
        """
        title = pr.get('title', '').lower()
        files = pr.get('files', [])
        commits = pr.get('commits', [])

        # Check title patterns first (most reliable)
        title_patterns = {
            'bugfix': ['fix', 'bug', 'issue', 'patch', 'resolve', 'correct'],
            'feature': ['feat', 'add', 'implement', 'new', 'introduce', 'support'],
            'refactor': ['refactor', 'restructure', 'reorganize', 'simplify', 'cleanup', 'clean up'],
            'dependency': ['bump', 'update.*dep', 'upgrade', 'dependency', 'dependencies'],
            'docs': ['doc', 'readme', 'documentation', 'comment'],
            'test': ['test', 'spec', 'coverage']
        }

        for pr_type, patterns in title_patterns.items():
            for pattern in patterns:
                if pattern in title:
                    if self.verbose:
                        print(f"🔍 [DEBUG] Detected PR type '{pr_type}' from title pattern '{pattern}'")
                    return pr_type

        # Check file patterns
        if files:
            file_paths = [f.get('path', '') for f in files]

            # Test files
            test_files = [f for f in file_paths if 'test' in f.lower() or 'spec' in f.lower()]
            if test_files and len(test_files) / len(file_paths) > 0.5:
                if self.verbose:
                    print(f"🔍 [DEBUG] Detected PR type 'test' from file patterns ({len(test_files)}/{len(file_paths)} test files)")
                return 'test'

            # Documentation files
            doc_files = [f for f in file_paths if any(x in f.lower() for x in ['readme', '.md', 'doc/', 'docs/'])]
            if doc_files and len(doc_files) / len(file_paths) > 0.5:
                if self.verbose:
                    print(f"🔍 [DEBUG] Detected PR type 'docs' from file patterns ({len(doc_files)}/{len(file_paths)} doc files)")
                return 'docs'

            # Dependency files
            dep_files = [f for f in file_paths if any(x in f.lower() for x in ['package.json', 'go.mod', 'requirements.txt', 'pom.xml', 'gradle'])]
            if dep_files:
                if self.verbose:
                    print(f"🔍 [DEBUG] Detected PR type 'dependency' from dependency files")
                return 'dependency'

        # Check commit messages as fallback
        if commits:
            commit_msgs = ' '.join([c.get('messageHeadline', '').lower() for c in commits[:5]])
            for pr_type, patterns in title_patterns.items():
                for pattern in patterns:
                    if pattern in commit_msgs:
                        if self.verbose:
                            print(f"🔍 [DEBUG] Detected PR type '{pr_type}' from commit messages")
                        return pr_type

        if self.verbose:
            print(f"🔍 [DEBUG] Could not auto-detect PR type")
        return None

    def _select_template_interactive(self, pr: Dict = None, suggested_template: str = None) -> Optional[Dict]:
        """Show interactive menu to select a summary template"""
        try:
            import questionary
            from questionary import Choice

            # Build choices with suggested template first
            choices = []

            if suggested_template and suggested_template in self.TEMPLATES:
                tmpl = self.TEMPLATES[suggested_template]
                choices.append(Choice(title=f"{tmpl['name']} (Suggested)", value=suggested_template))

            # Add other templates
            for k, t in self.TEMPLATES.items():
                if k != suggested_template:
                    choices.append(Choice(title=f"{t['name']}", value=k))

            choices.append(Choice(title="No template - write from scratch", value=None))

            template_key = questionary.select(
                "Use a summary template?",
                choices=choices,
                instruction="(Use arrow keys to select)"
            ).ask()

            if template_key is None:
                return None

            return {
                'key': template_key,
                **self.TEMPLATES[template_key]
            }

        except (ImportError, AttributeError):
            # Fallback without questionary
            print("\nAvailable templates:")
            template_list = list(self.TEMPLATES.items())

            # If suggested, show it first
            if suggested_template and suggested_template in self.TEMPLATES:
                print(f"  1. {self.TEMPLATES[suggested_template]['name']} (Suggested)")
                idx = 2
                for i, (key, tmpl) in enumerate(template_list, idx):
                    if key != suggested_template:
                        print(f"  {i}. {tmpl['name']}")
                        idx = i + 1
            else:
                for i, (key, tmpl) in enumerate(template_list, 1):
                    print(f"  {i}. {tmpl['name']}")
                idx = len(template_list) + 1

            print(f"  {idx}. No template - write from scratch")

            choice = input(f"\nSelect template (1-{idx}) [1]: ").strip() or "1"

            try:
                choice_num = int(choice)
                if choice_num == idx:
                    return None

                # Handle suggested template
                if suggested_template and suggested_template in self.TEMPLATES and choice_num == 1:
                    return {
                        'key': suggested_template,
                        **self.TEMPLATES[suggested_template]
                    }

                # Handle other templates
                if 1 <= choice_num <= len(template_list):
                    if suggested_template:
                        # Adjust index if suggestion was shown
                        adjusted_list = [k for k in template_list if k[0] != suggested_template]
                        if choice_num > 1:
                            key = adjusted_list[choice_num - 2][0]
                        else:
                            key = template_list[0][0]
                    else:
                        key = template_list[choice_num - 1][0]

                    return {
                        'key': key,
                        **self.TEMPLATES[key]
                    }
            except (ValueError, IndexError):
                pass

            return None

    def _auto_fill_template_variables(self, template: Dict, pr: Dict, ai_summary: str = None) -> Dict[str, str]:
        """Auto-fill template variables from PR data and AI summary"""
        filled_vars = {}

        # Extract data from PR
        title = pr.get('title', '')
        body = pr.get('body', '')
        files = pr.get('files', [])
        commits = pr.get('commits', [])

        # Try to smart-fill based on template type
        template_key = template.get('key', '')

        # Common variables
        if 'issue_description' in template['variables']:
            # Try to extract from title or AI summary
            if ai_summary:
                filled_vars['issue_description'] = ai_summary.split('.')[0].strip() if '.' in ai_summary else ai_summary[:100]
            else:
                filled_vars['issue_description'] = title

        if 'approach' in template['variables']:
            # Try to extract from AI summary or body
            if ai_summary:
                sentences = [s.strip() for s in ai_summary.split('.') if s.strip()]
                filled_vars['approach'] = sentences[1] if len(sentences) > 1 else "See PR description"
            else:
                filled_vars['approach'] = body.split('\n')[0][:100] if body else "See PR changes"

        if 'root_cause' in template['variables']:
            filled_vars['root_cause'] = "See PR description for details"

        if 'feature_name' in template['variables']:
            # Extract feature name from title
            filled_vars['feature_name'] = title.split(':')[-1].strip() if ':' in title else title

        if 'benefit' in template['variables']:
            filled_vars['benefit'] = "See PR description"

        if 'implementation_details' in template['variables']:
            if files:
                changed_files = ', '.join([f['path'].split('/')[-1] for f in files[:3]])
                filled_vars['implementation_details'] = f"Modified {changed_files}"
            else:
                filled_vars['implementation_details'] = f"{len(commits)} commit(s)"

        if 'old_implementation' in template['variables']:
            filled_vars['old_implementation'] = "Previous implementation"

        if 'new_implementation' in template['variables']:
            filled_vars['new_implementation'] = "Improved implementation"

        if 'improvements' in template['variables']:
            filled_vars['improvements'] = "Better code organization and maintainability"

        if 'dependency_name' in template['variables']:
            filled_vars['dependency_name'] = "dependency"

        if 'old_version' in template['variables']:
            filled_vars['old_version'] = "previous version"

        if 'new_version' in template['variables']:
            filled_vars['new_version'] = "latest version"

        if 'reason' in template['variables']:
            filled_vars['reason'] = "improved features and security"

        if 'what_changed' in template['variables']:
            if files:
                filled_vars['what_changed'] = f"Updated documentation in {len(files)} file(s)"
            else:
                filled_vars['what_changed'] = "Documentation updates"

        if 'test_description' in template['variables']:
            filled_vars['test_description'] = title

        if 'test_approach' in template['variables']:
            filled_vars['test_approach'] = f"{len(files)} file(s) changed"

        if 'coverage' in template['variables']:
            filled_vars['coverage'] = "test coverage"

        return filled_vars

    def _apply_template(self, template: Dict, pr: Dict, ai_summary: str = None) -> Optional[str]:
        """Apply template by filling variables and returning the result"""
        # Auto-fill what we can
        auto_filled = self._auto_fill_template_variables(template, pr, ai_summary)

        print(f"\n{'='*70}")
        print(f"TEMPLATE: {template['name']}")
        print('='*70)
        print(f"\nTemplate: {template['template']}\n")
        print("Fill in the variables below. Press Enter to use auto-detected values.\n")

        # Collect user input for each variable
        filled_vars = {}
        for var in template['variables']:
            hint = template['ai_hints'].get(var, '')
            auto_value = auto_filled.get(var, '')

            if auto_value:
                print(f"\n{var} ({hint})")
                print(f"Auto-detected: {auto_value}")
                user_value = input(f"Override (or press Enter to keep): ").strip()
                filled_vars[var] = user_value if user_value else auto_value
            else:
                print(f"\n{var} ({hint})")
                user_value = input(f"Enter value: ").strip()
                filled_vars[var] = user_value if user_value else f"[{var}]"

        # Fill the template
        result = template['template']
        for var, value in filled_vars.items():
            result = result.replace(f"{{{var}}}", value)

        return result

    def _ask_post_action(self, issue_key: str = None, cancel_label: str = "Skip this issue") -> str:
        """Ask user what to do with the summary (interactive menu)"""
        try:
            import questionary
            from questionary import Choice

            if issue_key:
                question = f"What would you like to do with {issue_key}?"
            else:
                question = "What would you like to do?"

            action = questionary.select(
                question,
                choices=[
                    Choice(title="Post this summary to Jira", value="post"),
                    Choice(title="Edit the entire summary", value="edit"),
                    Choice(title=cancel_label, value="skip")
                ],
                instruction="(Use arrow keys to select)"
            ).ask()

            return action if action else "skip"

        except (ImportError, AttributeError):
            # Fallback without questionary
            if issue_key:
                print(f"\nOptions for {issue_key}:")
            else:
                print(f"\nOptions:")
            print("  1. Post this summary to Jira")
            print("  2. Edit the entire summary")
            print(f"  3. {cancel_label}")

            choice = input("\nYour choice (1/2/3) [1]: ").strip() or "1"

            if choice == "1":
                return "post"
            elif choice == "2":
                return "edit"
            else:
                return "skip"

    def _is_issue_resolved(self, status: str) -> bool:
        """Check if issue status is in a resolved/closed/done state"""
        # Common resolved statuses (case-insensitive)
        resolved_statuses = [
            'resolved',
            'closed',
            'done',
            'completed',
            'verified',
            'released'
        ]
        is_resolved = status.lower() in resolved_statuses

        if is_resolved and self.verbose:
            print(f"   🔍 [DEBUG] Issue status '{status}' is considered resolved")

        return is_resolved

    def _multi_issue_wizard(self, issue_keys: List[str]) -> tuple:
        """
        Wizard for handling PRs with multiple issues.
        Returns: (mode, selected_issues)
        - mode: 'all', 'select', 'customize', 'first'
        - selected_issues: list of issue keys to process
        """
        try:
            import questionary
            from questionary import Choice

            num_issues = len(issue_keys)
            action = questionary.select(
                f"This PR references {num_issues} issues. What would you like to do?",
                choices=[
                    Choice(title=f"Post to all {num_issues} issues (same summary)", value="all"),
                    Choice(title="Select specific issues", value="select"),
                    Choice(title="Customize summary for each issue", value="customize"),
                    Choice(title="Post to first issue only (current behavior)", value="first")
                ],
                instruction="(Use arrow keys to select)"
            ).ask()

            if action == "all":
                return ("all", issue_keys)
            elif action == "first":
                return ("first", [issue_keys[0]])
            elif action == "select":
                # Show checkbox selector
                selected = questionary.checkbox(
                    "Select issues to post to:",
                    choices=[Choice(title=key, value=key, checked=True) for key in issue_keys],
                    instruction="(Space to select/deselect, Enter to confirm)"
                ).ask()

                if not selected:
                    return ("first", [issue_keys[0]])
                return ("select", selected)
            elif action == "customize":
                return ("customize", issue_keys)
            else:
                # User cancelled
                return ("first", [issue_keys[0]])

        except (ImportError, AttributeError):
            # Fallback without questionary
            print(f"\nThis PR references {len(issue_keys)} issues: {', '.join(issue_keys)}")
            print("\nWhat would you like to do?")
            print(f"  1. Post to all {len(issue_keys)} issues (same summary)")
            print("  2. Select specific issues")
            print("  3. Customize summary for each issue")
            print("  4. Post to first issue only")

            choice = input(f"\nYour choice (1-4) [1]: ").strip() or "1"

            if choice == "1":
                return ("all", issue_keys)
            elif choice == "4":
                return ("first", [issue_keys[0]])
            elif choice == "2":
                print(f"\nSelect issues (enter numbers separated by commas, e.g., 1,3):")
                for i, key in enumerate(issue_keys, 1):
                    print(f"  {i}. {key}")

                selection = input(f"\nIssues to post to [all]: ").strip()
                if not selection:
                    return ("all", issue_keys)

                try:
                    indices = [int(x.strip()) - 1 for x in selection.split(',')]
                    selected = [issue_keys[i] for i in indices if 0 <= i < len(issue_keys)]
                    if selected:
                        return ("select", selected)
                except:
                    pass

                return ("first", [issue_keys[0]])
            elif choice == "3":
                return ("customize", issue_keys)
            else:
                return ("first", [issue_keys[0]])

    def _check_ollama_available(self) -> bool:
        """Check if Ollama is running and available"""
        try:
            # Use urllib instead of curl for cross-platform compatibility
            with urlopen('http://localhost:11434/api/tags', timeout=2) as response:
                if response.status == 200:
                    return True
                return False
        except URLError:
            print("   ⚠️  Ollama not responding")
            print(f"   💡 Check if Ollama is running: {self._get_ollama_check_instructions()}")
            return False
        except Exception:
            return False

    def _generate_ai_summary(self, pr: Dict) -> Optional[str]:
        """Generate AI-powered summary using Ollama"""
        try:
            # Gather PR information
            title = pr.get('title', '')
            body = pr.get('body', '')
            commits = pr.get('commits', [])
            files = pr.get('files', [])

            # Build context for AI
            context_parts = [f"PR Title: {title}"]

            if body:
                context_parts.append(f"\nPR Description:\n{body[:500]}")  # Limit to 500 chars

            if commits:
                commit_msgs = '\n'.join([
                    f"- {c.get('messageHeadline', '')}"
                    for c in commits[:5]  # Limit to 5 commits
                    if c.get('messageHeadline')
                ])
                if commit_msgs:
                    context_parts.append(f"\nCommit messages:\n{commit_msgs}")

            if files:
                file_list = '\n'.join([f"- {f['path']}" for f in files[:10]])  # Limit to 10 files
                context_parts.append(f"\nFiles changed ({len(files)} total):\n{file_list}")

            context = '\n'.join(context_parts)

            # Prompt for Ollama
            prompt = f"""Analyze this pull request and write a concise 2-3 sentence technical summary explaining what was done and why.

{context}

Summary:"""

            # Call Ollama API
            data = {
                "model": "llama3.2:3b",
                "prompt": prompt,
                "stream": False
            }

            import urllib.request
            req = urllib.request.Request(
                'http://localhost:11434/api/generate',
                data=json.dumps(data).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )

            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result.get('response', '').strip()

        except Exception as e:
            print(f"   ⚠️  AI summary failed: {e}")
            return None

    def _generate_test_cases(self, pr: Dict) -> Optional[str]:
        """Generate test case suggestions using Ollama"""
        try:
            # Gather PR information
            title = pr.get('title', '')
            body = pr.get('body', '')
            commits = pr.get('commits', [])
            files = pr.get('files', [])

            # Build context for AI
            context_parts = [f"PR Title: {title}"]

            if body:
                context_parts.append(f"\nPR Description:\n{body[:500]}")

            if commits:
                commit_msgs = '\n'.join([
                    f"- {c.get('messageHeadline', '')}"
                    for c in commits[:5]
                    if c.get('messageHeadline')
                ])
                if commit_msgs:
                    context_parts.append(f"\nCommit messages:\n{commit_msgs}")

            if files:
                file_list = '\n'.join([f"- {f['path']}" for f in files[:10]])
                context_parts.append(f"\nFiles changed ({len(files)} total):\n{file_list}")

            context = '\n'.join(context_parts)

            # Prompt for Ollama
            prompt = f"""Based on this pull request, suggest 3-5 specific test cases that QE should verify. Focus on functional testing, edge cases, and potential regressions.

{context}

Format your response as a bulleted list of test cases. Each test case should be specific and actionable.

Test Cases:"""

            # Call Ollama API
            data = {
                "model": "llama3.2:3b",
                "prompt": prompt,
                "stream": False
            }

            import urllib.request
            req = urllib.request.Request(
                'http://localhost:11434/api/generate',
                data=json.dumps(data).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )

            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                test_cases = result.get('response', '').strip()

                # Clean up the response
                if test_cases:
                    # Remove phrases like "Here are the test cases:"
                    test_cases = re.sub(r'^(here are|here\'s|these are).*?cases:?\s*', '', test_cases, flags=re.IGNORECASE)
                    test_cases = test_cases.strip()
                    return test_cases

                return None

        except Exception as e:
            print(f"   ⚠️  Test case generation failed: {e}")
            return None

    def generate_summary(self, pr: Dict, use_ai: bool = False) -> str:
        """Generate a summary of work done based on PR data"""
        title = pr.get('title', 'No title')
        body = pr.get('body', '')
        commits = pr.get('commits', [])
        files = pr.get('files', [])
        pr_url = pr.get('url', '')
        pr_number = pr.get('number', '')
        merged_at = pr.get('mergedAt')

        summary_parts = []

        # Add AI attribution header at the top if AI was used
        if use_ai:
            summary_parts.append("*AI-GENERATED SUMMARY*")
            summary_parts.append("")

        # Try AI summary first if enabled - this is the main content
        if use_ai:
            ai_summary = self._generate_ai_summary(pr)
            if ai_summary:
                # Clean up AI summary - remove phrases like "Here is a concise summary:"
                ai_summary = re.sub(r'^(here is|this is).*?summary:?\s*', '', ai_summary, flags=re.IGNORECASE)
                ai_summary = ai_summary.strip()
                summary_parts.append(ai_summary)
                summary_parts.append("")

        # If no AI or AI failed, generate basic summary from PR description
        if not use_ai or not summary_parts:
            if body and len(body.strip()) > 10:
                # Take first meaningful paragraph from PR description
                body_lines = body.strip().split('\n')
                first_para = []
                for line in body_lines:
                    line = line.strip()
                    if line and not line.startswith('<!--') and not line.startswith('#'):
                        first_para.append(line)
                    if len('\n'.join(first_para)) > 300:
                        break

                if first_para:
                    summary_parts.append('\n'.join(first_para[:5]))
                    summary_parts.append("")

        # Add commit messages if requested
        if self.include_commits and commits:
            summary_parts.append("**Commits:**")
            for commit in commits[:10]:  # Limit to 10 commits
                msg = commit.get('messageHeadline', commit.get('message', '')).strip()
                if msg:
                    # Truncate long commit messages
                    if len(msg) > 80:
                        msg = msg[:77] + "..."
                    summary_parts.append(f"- {msg}")
            summary_parts.append("")

        # Add simple metadata footer
        metadata = []
        metadata.append(f"PR #{pr_number}: {pr_url}")

        details = []
        if files:
            details.append(f"{len(files)} file{'s' if len(files) != 1 else ''} changed")
        if commits:
            details.append(f"{len(commits)} commit{'s' if len(commits) != 1 else ''}")
        if merged_at:
            try:
                dt = datetime.fromisoformat(merged_at.replace('Z', '+00:00'))
                details.append(f"Merged {dt.strftime('%Y-%m-%d')}")
            except:
                pass

        if details:
            metadata.append(" | ".join(details))

        summary_parts.append('\n'.join(metadata))

        return '\n'.join(summary_parts)

    def post_comment(self, issue_key: str, comment: str) -> bool:
        """Post a comment to a Jira issue"""
        data = {"body": comment}
        result = self._jira_request(f"/rest/api/2/issue/{issue_key}/comment", method="POST", data=data)
        return bool(result)

    def _group_prs_by_issue(self, prs: List[Dict]) -> Dict[str, List[Dict]]:
        """Group PRs by their issue keys"""
        from collections import defaultdict
        grouped = defaultdict(list)

        for pr in prs:
            for issue_key in pr.get('issue_keys', []):
                grouped[issue_key].append(pr)

        return dict(grouped)

    def _normalize_pr_title(self, title: str) -> str:
        """Normalize PR title by removing branch prefixes and whitespace"""
        import re
        # Remove common branch prefixes like [release-2.16], [backplane-2.6], etc.
        normalized = re.sub(r'^\[[\w\-\.]+\]\s*', '', title)
        # Remove leading/trailing whitespace
        normalized = normalized.strip()
        return normalized.lower()

    def _has_branch_prefix(self, title: str) -> bool:
        """Check if PR title has a branch-style prefix, typically in [branch][issue] format"""
        import re
        # Backport format: [release-2.16][ACM-28712] Fix timeout
        # Main format:     [ACM-28712] Fix timeout (no branch prefix)
        #
        # Match branch patterns like [release-2.16], [backplane-2.6], [main], etc.
        # Typically followed by an issue key like [ACM-28712]
        branch_patterns = [
            r'^\[release[\-\.]',     # [release-2.16][ISSUE]...
            r'^\[backplane[\-\.]',   # [backplane-2.6][ISSUE]...
            r'^\[main\]\[',          # [main][ISSUE]...
            r'^\[master\]\[',        # [master][ISSUE]...
            r'^\[v?\d+\.\d+',        # [2.16][ISSUE]... or [v2.16][ISSUE]...
        ]
        return any(re.match(pattern, title) for pattern in branch_patterns)

    def _are_prs_similar(self, prs: List[Dict], threshold: float = 0.8) -> bool:
        """Check if PRs are similar (likely backports) based on title similarity"""
        if len(prs) <= 1:
            return True

        # Count how many PRs have branch-style prefixes
        branch_prefix_count = sum(1 for pr in prs if self._has_branch_prefix(pr.get('title', '')))

        # Only combine if at least 1 PR has a branch prefix (indicating backport work)
        # This prevents combining unrelated PRs that happen to have the same title
        # but were merged months apart with no backporting involved
        if branch_prefix_count < 1:
            return False

        # Normalize all titles
        normalized_titles = [self._normalize_pr_title(pr.get('title', '')) for pr in prs]

        # Check if all titles are similar to the first one
        first_title = normalized_titles[0]
        if not first_title:
            return False

        for title in normalized_titles[1:]:
            if not title:
                return False

            # Calculate similarity using a simple approach
            # If titles are exactly the same after normalization, they're backports
            if title == first_title:
                continue

            # Check if one contains most of the other (for slight variations)
            shorter = min(title, first_title, key=len)
            longer = max(title, first_title, key=len)

            # If the shorter title is at least 80% contained in the longer one
            if len(shorter) == 0:
                return False

            # Simple substring check
            if shorter not in longer:
                return False

        return True

    def _extract_branch_from_title(self, title: str) -> Optional[str]:
        """Extract branch name from PR title prefix like [release-2.15] or [backplane-2.6]"""
        import re
        # Match patterns like [release-2.15], [backplane-2.6], [main], [master], [2.16], etc.
        branch_match = re.match(r'^\[([\w\-\.]+)\]', title)
        if branch_match:
            branch_name = branch_match.group(1)
            # Filter out issue keys (they contain uppercase letters and hyphens like ACM-12345)
            # Branch names are typically lowercase or version numbers
            if re.match(r'^[A-Z]+-\d+$', branch_name):
                return None  # This is an issue key, not a branch
            return branch_name
        return None

    def _parse_version_from_branch(self, branch: str) -> Optional[tuple]:
        """Parse version number from branch name like 'release-2.16' -> (2, 16)"""
        import re
        # Try to extract version numbers like X.Y from patterns:
        # release-2.16, backplane-2.6, 2.16, v2.16, etc.
        version_match = re.search(r'(\d+)\.(\d+)', branch)
        if version_match:
            major = int(version_match.group(1))
            minor = int(version_match.group(2))
            return (major, minor)
        return None

    def _identify_main_and_backports(self, prs: List[Dict]) -> tuple:
        """Identify which PR is main and which are backports based on branch versions"""
        candidates = []

        for pr in prs:
            branch = self._extract_branch_from_title(pr.get('title', ''))
            if not branch:
                # No branch prefix - definitely main
                return pr, [{'pr': p, 'branch': self._extract_branch_from_title(p.get('title', ''))}
                           for p in prs if p != pr and self._extract_branch_from_title(p.get('title', ''))]
            elif branch in ('main', 'master'):
                # Explicit main/master - definitely main
                return pr, [{'pr': p, 'branch': self._extract_branch_from_title(p.get('title', ''))}
                           for p in prs if p != pr and self._extract_branch_from_title(p.get('title', ''))]
            else:
                version = self._parse_version_from_branch(branch)
                candidates.append({
                    'pr': pr,
                    'branch': branch,
                    'version': version
                })

        # All have branch prefixes - use highest version as main
        if candidates:
            # Filter to only those with parseable versions
            versioned = [c for c in candidates if c['version'] is not None]

            if versioned:
                # Sort by version (descending) - highest version is main
                versioned.sort(key=lambda x: x['version'], reverse=True)
                main_candidate = versioned[0]
                main_pr = main_candidate['pr']

                # Rest are backports
                backports = [{'pr': c['pr'], 'branch': c['branch']}
                            for c in candidates if c['pr'] != main_pr]

                return main_pr, backports

        # Couldn't determine - return first as main
        if candidates:
            main_pr = candidates[0]['pr']
            backports = [{'pr': c['pr'], 'branch': c['branch']}
                        for c in candidates[1:]]
            return main_pr, backports

        return None, []

    def _generate_combined_summary(self, prs: List[Dict], use_ai: bool = False) -> str:
        """Generate a combined summary for multiple PRs related to the same issue"""
        num_prs = len(prs)

        # Header
        summary_parts = []
        if num_prs == 1:
            summary_parts.append(f"✅ PR merged for this issue:")
        else:
            summary_parts.append(f"✅ {num_prs} PRs merged for this issue:")

        summary_parts.append("")

        # Identify main PR and backports (used for both backport summary and AI summary)
        main_pr = None
        backports = []

        if num_prs > 1:
            # Use smart version-based detection
            main_pr, backports = self._identify_main_and_backports(prs)

            # Generate backport summary
            if main_pr and backports:
                summary_parts.append("*Backport Summary:*")
                main_pr_num = main_pr.get('number')
                backport_list = ', '.join([f"{bp['branch']} (PR #{bp['pr'].get('number')})" for bp in backports])
                summary_parts.append(f"Main PR #{main_pr_num} merged and backported to: {backport_list}")
                summary_parts.append("")
            elif backports and not main_pr:
                # All are backports, no main PR found
                summary_parts.append("*Backport Summary:*")
                backport_list = ', '.join([f"{bp['branch']} (PR #{bp['pr'].get('number')})" for bp in backports])
                summary_parts.append(f"Backported to: {backport_list}")
                summary_parts.append("")

        # List each PR with its details
        for pr in prs:
            pr_number = pr.get('number')
            title = pr.get('title', 'No title').strip()
            pr_url = pr.get('url', '')

            summary_parts.append(f"*PR #{pr_number}:* {title}")
            if pr_url:
                summary_parts.append(f"{pr_url}")

            # Add merged date
            merged_at = pr.get('mergedAt')
            if merged_at:
                try:
                    dt = datetime.fromisoformat(merged_at.replace('Z', '+00:00'))
                    summary_parts.append(f"Merged: {dt.strftime('%Y-%m-%d %H:%M UTC')}")
                except:
                    pass

            summary_parts.append("")

        # Generate AI summary
        if use_ai:
            ai_summary = None
            if num_prs == 1:
                # Single PR - use it for AI summary
                ai_summary = self._generate_ai_summary(prs[0])
            elif main_pr:
                # Multiple PRs with a main branch - use main PR for AI summary
                ai_summary = self._generate_ai_summary(main_pr)

            if ai_summary:
                summary_parts.append("*AI-Generated Summary:*")
                summary_parts.append(ai_summary)
                summary_parts.append("")
        elif num_prs > 1:
            # Multiple PRs without AI - generic message
            summary_parts.append("*Summary:*")
            summary_parts.append(f"Multiple PRs merged across different branches/components for this issue.")
            summary_parts.append("")

        return '\n'.join(summary_parts)

    def process_prs_for_issue(self, issue_key: str, prs: List[Dict], interactive: bool = True,
                              force: bool = False, dry_run: bool = False, auto_approve: bool = False) -> bool:
        """Process multiple PRs for a single issue - combine into one comment"""

        num_prs = len(prs)
        pr_numbers = [pr['number'] for pr in prs]

        print(f"\n{'='*70}")
        if num_prs == 1:
            print(f"Processing PR #{pr_numbers[0]} for {issue_key}")
        else:
            print(f"Processing {num_prs} PRs for {issue_key}")
            print(f"PR #s: {', '.join(map(str, pr_numbers))}")
        print('='*70)

        # Get current status and labels
        print(f"\n📋 Checking {issue_key}...")
        status = self.get_issue_status(issue_key)
        if not status:
            print(f"   ❌ Could not fetch status for {issue_key}")
            return False

        print(f"   Status: {status}")

        # Skip if issue is already resolved (unless forced)
        if self._is_issue_resolved(status) and not force:
            print(f"   ⏭️  Issue is already {status} - skipping")
            if self.verbose:
                print(f"   💡 Use --force to post to resolved issues")
            return False

        labels = self.get_issue_labels(issue_key)
        qe_not_applicable = 'QE-NotApplicable' in labels

        if qe_not_applicable:
            print(f"   🏷️  Label: QE-NotApplicable (test cases will be skipped)")

        # Check if any PRs have already been posted
        already_posted = []
        not_posted = []
        for pr in prs:
            pr_number = pr['number']
            cached_info = self._get_cached_info(issue_key, pr_number)
            if cached_info:
                already_posted.append(pr_number)
            else:
                not_posted.append(pr_number)

        if already_posted and interactive and not force:
            print(f"\n   ⚠️  Some PRs already posted to {issue_key}: {', '.join(map(str, already_posted))}")
            if not not_posted:
                print(f"   All {num_prs} PRs already posted")
                choice = input("   Post combined summary again? (y/N): ").strip().lower()
                if choice != 'y':
                    print("   Skipped")
                    return False

        # Offer to transition status if appropriate
        if interactive:
            # Check if any PR is merged
            any_merged = any(bool(pr.get('mergedAt')) for pr in prs)
            self.offer_status_transition(issue_key, status, any_merged)

        # Generate combined summary
        if self.use_ai and num_prs == 1:
            print(f"\n   🤖 Generating AI-powered summary...")
        else:
            print(f"\n   ✍️  Generating summary...")

        summary = self._generate_combined_summary(prs, use_ai=self.use_ai)

        print("\n" + "─"*70)
        if self.use_ai and num_prs == 1:
            print("AI-GENERATED SUMMARY:")
        else:
            print("AUTO-GENERATED SUMMARY:")
        print("─"*70)
        print(summary)
        print("─"*70)

        if interactive and not auto_approve:
            # Offer template-based summary (only for single PR)
            template_choice = 'n'
            if num_prs == 1:
                # Auto-detect PR type for template suggestion
                detected_type = self._detect_pr_type(prs[0])
                if detected_type:
                    type_names = {
                        'bugfix': 'bugfix',
                        'feature': 'feature',
                        'refactor': 'refactoring',
                        'dependency': 'dependency update',
                        'docs': 'documentation update',
                        'test': 'test update'
                    }
                    type_name = type_names.get(detected_type, detected_type)
                    print(f"\n🔍 This looks like a {type_name}")

                print("\nYou can use a template to structure your summary, or write from scratch.")
                template_choice = input("Would you like to see available templates? (y/N): ").strip().lower()

                if template_choice == 'y':
                    selected_template = self._select_template_interactive(pr=prs[0], suggested_template=detected_type)

                    if selected_template:
                        # Extract AI summary if it was used (for smart variable filling)
                        ai_summary_text = None
                        if self.use_ai:
                            # Extract just the AI-generated text from the summary
                            summary_lines = summary.split('\n')
                            ai_lines = []
                            for line in summary_lines:
                                if line.startswith('*AI-GENERATED SUMMARY*') or line.startswith('*PR #') or line.startswith('PR #') or not line.strip():
                                    continue
                                if line.startswith('*Summary:*'):
                                    continue
                                ai_lines.append(line)
                            if ai_lines:
                                ai_summary_text = '\n'.join(ai_lines).strip()

                        # Apply the template
                        template_result = self._apply_template(selected_template, prs[0], ai_summary_text)

                        if template_result:
                            # Extract PR metadata from auto-generated summary
                            summary_lines = summary.split('\n')
                            metadata_lines = []

                            # Find the PR metadata (starts with "*PR #" or "PR #")
                            for i, line in enumerate(summary_lines):
                                if line.startswith('*PR #') or line.startswith('PR #'):
                                    metadata_lines = summary_lines[i:]
                                    break

                            # Replace summary with template result + metadata
                            if metadata_lines:
                                summary = f"{template_result}\n\n{chr(10).join(metadata_lines)}"
                            else:
                                summary = template_result

                            print("\n" + "─"*70)
                            print("TEMPLATE-BASED SUMMARY:")
                            print("─"*70)
                            print(summary)
                            print("─"*70)

                            # Ask if they want to edit
                            edit_choice = input("\nEdit this summary? (y/N): ").strip().lower()
                            if edit_choice == 'y':
                                print("\nEnter your edited summary (press Ctrl+D when done):")
                                print("─"*70)
                                lines = []
                                try:
                                    while True:
                                        line = input()
                                        lines.append(line)
                                except EOFError:
                                    pass
                                user_summary = "\n".join(lines).strip()

                                if user_summary:
                                    # Check if user's summary already contains PR metadata
                                    # If it does, don't append metadata_lines again (avoid duplication)
                                    has_pr_metadata = '*PR #' in user_summary or 'PR #' in user_summary

                                    if metadata_lines and not has_pr_metadata:
                                        summary = f"{user_summary}\n\n{chr(10).join(metadata_lines)}"
                                    else:
                                        summary = user_summary

                                    print("\n" + "─"*70)
                                    print("FINAL SUMMARY:")
                                    print("─"*70)
                                    print(summary)
                                    print("─"*70)

            # If no template was selected, ask if they want to add context
            if num_prs > 1 or (num_prs == 1 and template_choice != 'y'):
                add_context = input("\nAdd your own detailed context? (Y/n): ").strip().lower()
            else:
                add_context = 'n'

            if add_context != 'n':
                print("\n" + "="*70)
                print("ADD YOUR CONTEXT")
                print("="*70)
                print("Explain what you actually did, decisions made, and why.")
                print("\nType your context below (press Ctrl+D when done):")
                print("─"*70)

                context_lines = []
                try:
                    while True:
                        line = input()
                        context_lines.append(line)
                except EOFError:
                    pass

                user_context = "\n".join(context_lines).strip()

                if user_context:
                    # Prepend user context to the PR list
                    summary = f"{user_context}\n\n{summary}"

                    print("\n" + "─"*70)
                    print("FINAL SUMMARY:")
                    print("─"*70)
                    print(summary)
                    print("─"*70)

            # Ask if they want to add test cases (skip if QE-NotApplicable)
            if self.use_ai and not qe_not_applicable:
                add_tests = input("\nGenerate QE test case suggestions? (Y/n): ").strip().lower()

                if add_tests != 'n':
                    print("\n   🧪 Generating test case suggestions...")
                    # Use the first PR for test case generation
                    test_cases = self._generate_test_cases(prs[0])

                    if test_cases:
                        print("\n" + "─"*70)
                        print("SUGGESTED TEST CASES:")
                        print("─"*70)
                        print(test_cases)
                        print("─"*70)

                        include_tests = input("\nInclude these test cases in the Jira comment? (Y/n/e to edit): ").strip().lower()

                        if include_tests == 'e':
                            print("\nEdit test cases (press Ctrl+D when done):")
                            print("─"*70)
                            test_lines = []
                            try:
                                while True:
                                    line = input()
                                    test_lines.append(line)
                            except EOFError:
                                pass
                            test_cases = "\n".join(test_lines).strip()

                        if include_tests != 'n' and test_cases:
                            summary = f"{summary}\n\n*QE Test Cases:*\n{test_cases}"

                            print("\n" + "─"*70)
                            print("FINAL SUMMARY WITH TEST CASES:")
                            print("─"*70)
                            print(summary)
                            print("─"*70)

            # Ask user what to do (skip if auto-approve)
            action = self._ask_post_action(issue_key)

            if action == "edit":
                print("\nEnter your full summary (press Ctrl+D when done):")
                print("─"*70)
                lines = []
                try:
                    while True:
                        line = input()
                        lines.append(line)
                except EOFError:
                    pass
                summary = "\n".join(lines).strip()

                if not summary:
                    print("Empty summary - skipping")
                    return False
            elif action != "post":
                print("Skipped")
                return False

        # Post comment (or preview in dry-run mode)
        if dry_run:
            print(f"\n🔍 DRY RUN - Would post the above summary to {issue_key}")
            print(f"✅ Preview complete (not posted)")
            return True
        else:
            print(f"\n📤 Posting combined comment to {issue_key}...")
            if self.post_comment(issue_key, summary):
                print(f"✅ Successfully posted comment to {issue_key}")
                print(f"   View: {self.jira_base}/browse/{issue_key}")
                # Update cache for all PRs
                for pr in prs:
                    self._update_cache(issue_key, pr['number'], pr.get('url', ''))
                return True
            else:
                print(f"❌ Failed to post comment to {issue_key}")
                return False

    def process_pr(self, pr: Dict, interactive: bool = True, force: bool = False, dry_run: bool = False, auto_approve: bool = False) -> bool:
        """Process a single PR: check issue status, generate summary, post comment"""
        pr_number = pr['number']
        issue_keys = pr['issue_keys']

        if not issue_keys:
            print(f"⏭️  Skipping PR #{pr_number} - no issue keys found")
            return False

        print(f"\n{'='*70}")
        print(f"Processing PR #{pr_number}: {pr['title']}")
        print(f"Issue(s): {', '.join(issue_keys)}")
        print('='*70)

        # Get full PR details if not already loaded
        if 'files' not in pr:
            pr = self.get_pr_details(pr_number)
            if not pr:
                print(f"❌ Could not fetch details for PR #{pr_number}")
                return False

        # Multi-issue wizard (if interactive and multiple issues)
        customize_mode = False
        if interactive and len(issue_keys) > 1 and not auto_approve:
            mode, selected_issues = self._multi_issue_wizard(issue_keys)
            issue_keys = selected_issues
            customize_mode = (mode == "customize")

            if not issue_keys:
                print("No issues selected - skipping")
                return False

        success_count = 0

        for issue_key in issue_keys:
            print(f"\n📋 Checking {issue_key}...")

            # Get current status and labels
            status = self.get_issue_status(issue_key)
            if not status:
                print(f"   ❌ Could not fetch status for {issue_key}")
                continue

            print(f"   Status: {status}")

            # Skip if issue is already resolved (unless forced)
            if self._is_issue_resolved(status) and not force:
                print(f"   ⏭️  Issue is already {status} - skipping")
                if self.verbose:
                    print(f"   💡 Use --force to post to resolved issues")
                continue

            labels = self.get_issue_labels(issue_key)
            qe_not_applicable = 'QE-NotApplicable' in labels

            if qe_not_applicable:
                print(f"   🏷️  Label: QE-NotApplicable (test cases will be skipped)")

            # Show related PRs for this issue
            related_prs = self.find_merged_prs(days=90, issue_key=issue_key)
            if related_prs and len(related_prs) > 1:
                # Filter out current PR
                other_prs = [p for p in related_prs if p['number'] != pr_number]
                if other_prs:
                    print(f"   🔗 Related PRs for {issue_key}:")
                    for rpr in other_prs[:3]:  # Show max 3
                        merged_date = rpr.get('mergedAt', '')
                        try:
                            dt = datetime.fromisoformat(merged_date.replace('Z', '+00:00'))
                            date_str = dt.strftime('%Y-%m-%d')
                        except:
                            date_str = 'unknown'
                        print(f"      - PR #{rpr['number']} (merged {date_str})")
                    if len(other_prs) > 3:
                        print(f"      ... and {len(other_prs) - 3} more")

            # Check if this PR has already been posted to this issue
            cached_info = self._get_cached_info(issue_key, pr_number)
            if cached_info and interactive and not force:
                timestamp = cached_info.get('timestamp', 'unknown time')
                try:
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    time_str = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    time_str = timestamp

                print(f"\n   ⚠️  PR #{pr_number} was already posted to {issue_key} on {time_str}")
                choice = input("   Post summary again? (y/N): ").strip().lower()
                if choice != 'y':
                    print("   Skipped")
                    continue

            # Offer to transition status if appropriate
            pr_is_merged = bool(pr.get('mergedAt'))
            if interactive:
                self.offer_status_transition(issue_key, status, pr_is_merged)

            # Generate summary
            if self.use_ai:
                print(f"\n   🤖 Generating AI-powered summary...")
            else:
                print(f"\n   ✍️  Generating summary...")
            summary = self.generate_summary(pr, use_ai=self.use_ai)

            print("\n" + "─"*70)
            if self.use_ai:
                print("AI-GENERATED SUMMARY:")
            else:
                print("AUTO-GENERATED SUMMARY:")
            print("─"*70)
            print(summary)
            print("─"*70)

            if interactive and not auto_approve:
                # In customize mode, indicate which issue we're customizing for
                if customize_mode and len(issue_keys) > 1:
                    print(f"\n{'='*70}")
                    print(f"CUSTOMIZING SUMMARY FOR {issue_key}")
                    print('='*70)

                # Offer template-based summary
                # Auto-detect PR type for template suggestion
                detected_type = self._detect_pr_type(pr)
                if detected_type:
                    type_names = {
                        'bugfix': 'bugfix',
                        'feature': 'feature',
                        'refactor': 'refactoring',
                        'dependency': 'dependency update',
                        'docs': 'documentation update',
                        'test': 'test update'
                    }
                    type_name = type_names.get(detected_type, detected_type)
                    print(f"\n🔍 This looks like a {type_name}")

                print("\nYou can use a template to structure your summary, or write from scratch.")
                template_choice = input("Would you like to see available templates? (y/N): ").strip().lower()

                if template_choice == 'y':
                    selected_template = self._select_template_interactive(pr=pr, suggested_template=detected_type)

                    if selected_template:
                        # Extract AI summary if it was used (for smart variable filling)
                        ai_summary_text = None
                        if self.use_ai:
                            # Extract just the AI-generated text from the summary
                            summary_lines = summary.split('\n')
                            ai_lines = []
                            for line in summary_lines:
                                if line.startswith('*AI-GENERATED SUMMARY*') or line.startswith('PR #') or not line.strip():
                                    continue
                                ai_lines.append(line)
                            if ai_lines:
                                ai_summary_text = '\n'.join(ai_lines).strip()

                        # Apply the template
                        template_result = self._apply_template(selected_template, pr, ai_summary_text)

                        if template_result:
                            # Extract PR metadata from auto-generated summary
                            summary_lines = summary.split('\n')
                            metadata_lines = []

                            # Find the PR metadata (starts with "PR #")
                            for i, line in enumerate(summary_lines):
                                if line.startswith('PR #'):
                                    metadata_lines = summary_lines[i:]
                                    break

                            # Replace summary with template result + metadata
                            if metadata_lines:
                                summary = f"{template_result}\n\n{chr(10).join(metadata_lines)}"
                            else:
                                summary = template_result

                            print("\n" + "─"*70)
                            print("TEMPLATE-BASED SUMMARY:")
                            print("─"*70)
                            print(summary)
                            print("─"*70)

                            # Ask if they want to edit
                            edit_choice = input("\nEdit this summary? (y/N): ").strip().lower()
                            if edit_choice == 'y':
                                print("\nEnter your edited summary (press Ctrl+D when done):")
                                print("─"*70)
                                lines = []
                                try:
                                    while True:
                                        line = input()
                                        lines.append(line)
                                except EOFError:
                                    pass
                                user_summary = "\n".join(lines).strip()

                                if user_summary:
                                    # Check if user's summary already contains PR metadata
                                    # If it does, don't append metadata_lines again (avoid duplication)
                                    has_pr_metadata = '*PR #' in user_summary or 'PR #' in user_summary

                                    if metadata_lines and not has_pr_metadata:
                                        summary = f"{user_summary}\n\n{chr(10).join(metadata_lines)}"
                                    else:
                                        summary = user_summary

                                    print("\n" + "─"*70)
                                    print("FINAL SUMMARY:")
                                    print("─"*70)
                                    print(summary)
                                    print("─"*70)

                # If no template was selected, ask if they want to add context
                if template_choice != 'y':
                    if self.use_ai:
                        print(f"\nAI generated a summary from the PR. You can add more context if needed.")
                    else:
                        print(f"\nBasic summary generated from PR data.")
                    add_context = input("Add your own detailed context? (Y/n): ").strip().lower()

                    if add_context != 'n':
                        print("\n" + "="*70)
                        print("ADD YOUR CONTEXT")
                        print("="*70)
                        print("Explain what you actually did, decisions made, and why.")
                        print("Tips:")
                        print("  - What was the problem/requirement?")
                        print("  - What did you do about it?")
                        print("  - Why did you make that choice?")
                        print("  - Any important technical details or decisions?")
                        print("  - What are the next steps (if any)?")
                        print("\nType your context below (press Ctrl+D when done):")
                        print("─"*70)

                        context_lines = []
                        try:
                            while True:
                                line = input()
                                context_lines.append(line)
                        except EOFError:
                            pass

                        user_context = "\n".join(context_lines).strip()

                        if user_context:
                            # Extract PR metadata from auto-generated summary
                            summary_lines = summary.split('\n')
                            metadata_lines = []

                            # Find the PR metadata (starts with "PR #")
                            for i, line in enumerate(summary_lines):
                                if line.startswith('PR #'):
                                    metadata_lines = summary_lines[i:]
                                    break

                            # Combine: user context + metadata
                            if metadata_lines:
                                summary = f"{user_context}\n\n{chr(10).join(metadata_lines)}"
                            else:
                                summary = user_context

                            print("\n" + "─"*70)
                            print("FINAL SUMMARY:")
                            print("─"*70)
                            print(summary)
                            print("─"*70)

                # Ask if they want to add test cases (skip if QE-NotApplicable)
                if self.use_ai and not qe_not_applicable:
                    add_tests = input("\nGenerate QE test case suggestions? (Y/n): ").strip().lower()

                    if add_tests != 'n':
                        print("\n   🧪 Generating test case suggestions...")
                        test_cases = self._generate_test_cases(pr)

                        if test_cases:
                            print("\n" + "─"*70)
                            print("SUGGESTED TEST CASES:")
                            print("─"*70)
                            print(test_cases)
                            print("─"*70)

                            include_tests = input("\nInclude these test cases in the Jira comment? (Y/n/e to edit): ").strip().lower()

                            if include_tests == 'e':
                                print("\nEdit test cases (press Ctrl+D when done):")
                                print("─"*70)
                                test_lines = []
                                try:
                                    while True:
                                        line = input()
                                        test_lines.append(line)
                                except EOFError:
                                    pass
                                test_cases = "\n".join(test_lines).strip()

                            if include_tests != 'n' and test_cases:
                                summary = f"{summary}\n\n*QE Test Cases:*\n{test_cases}"

                                print("\n" + "─"*70)
                                print("FINAL SUMMARY WITH TEST CASES:")
                                print("─"*70)
                                print(summary)
                                print("─"*70)

                # Ask user what to do (skip if auto-approve)
                if not auto_approve:
                    action = self._ask_post_action(issue_key)

                    if action == "edit":
                        print("\nEnter your full summary (press Ctrl+D when done):")
                        print("─"*70)
                        lines = []
                        try:
                            while True:
                                line = input()
                                lines.append(line)
                        except EOFError:
                            pass
                        summary = "\n".join(lines).strip()

                        if not summary:
                            print("Empty summary - skipping")
                            continue
                    elif action != "post":
                        print("Skipped")
                        continue

            # Post comment (or preview in dry-run mode)
            if dry_run:
                print(f"\n🔍 DRY RUN - Would post the above summary to {issue_key}")
                print(f"✅ Preview complete (not posted)")
                success_count += 1
            else:
                print(f"\n📤 Posting comment to {issue_key}...")
                if self.post_comment(issue_key, summary):
                    print(f"✅ Successfully posted comment to {issue_key}")
                    print(f"   View: {self.jira_base}/browse/{issue_key}")
                    # Update cache to track this posted PR
                    self._update_cache(issue_key, pr_number, pr.get('url', ''))
                    success_count += 1
                else:
                    print(f"❌ Failed to post comment to {issue_key}")

        return success_count > 0

    def _select_prs_interactive(self, prs: List[Dict]) -> List[Dict]:
        """Show interactive menu to select PRs to process"""
        if not prs:
            return []

        try:
            import questionary
            from questionary import Choice

            print()  # Add spacing

            # Check if PRs are from multiple repos (cross-repo search)
            has_repo_info = any('repo_name' in pr for pr in prs)

            # Build choices with PR details
            choices = []

            if has_repo_info:
                # Group PRs by repository
                from collections import defaultdict
                prs_by_repo = defaultdict(list)
                for pr in prs:
                    repo_name = pr.get('repo_name', 'unknown/repo')
                    prs_by_repo[repo_name].append(pr)

                # Sort repos alphabetically
                for repo_name in sorted(prs_by_repo.keys()):
                    # Add repository header (disabled choice for visual grouping)
                    choices.append(Choice(title=f"\n📦 {repo_name}", value=None, disabled=True))

                    # Add PRs for this repo
                    for pr in prs_by_repo[repo_name]:
                        pr_num = pr['number']
                        title = pr['title'].strip()
                        issues = ', '.join(pr['issue_keys'])

                        # Truncate title intelligently
                        max_title_len = 70  # Slightly shorter to account for repo grouping
                        if len(title) > max_title_len:
                            title = title[:max_title_len].rsplit(' ', 1)[0] + '...'

                        # Format: "  PR #123: Fix auth bug [ACM-12345]"
                        display_text = f"  PR #{pr_num}: {title} [{issues}]"
                        choices.append(Choice(title=display_text, value=pr, checked=False))
            else:
                # Single repo - display as before
                for pr in prs:
                    pr_num = pr['number']
                    title = pr['title'].strip()
                    issues = ', '.join(pr['issue_keys'])

                    # Truncate title intelligently
                    max_title_len = 80
                    if len(title) > max_title_len:
                        title = title[:max_title_len].rsplit(' ', 1)[0] + '...'

                    # Format: "PR #123: Fix auth bug [ACM-12345, ACM-67890]"
                    display_text = f"PR #{pr_num}: {title} [{issues}]"
                    choices.append(Choice(title=display_text, value=pr, checked=False))

            selected = questionary.checkbox(
                "Select PRs to process:",
                choices=choices,
                instruction="(Use arrow keys, space to select, a to toggle all, enter to confirm)",
                qmark="🔀"
            ).ask()

            return selected if selected else []

        except ImportError:
            # Fallback to old yes/no if questionary not available
            has_repo_info = any('repo_name' in pr for pr in prs)

            if has_repo_info:
                # Group by repo for display
                from collections import defaultdict
                prs_by_repo = defaultdict(list)
                for pr in prs:
                    repo_name = pr.get('repo_name', 'unknown/repo')
                    prs_by_repo[repo_name].append(pr)

                for repo_name in sorted(prs_by_repo.keys()):
                    print(f"\n📦 {repo_name}")
                    for pr in prs_by_repo[repo_name]:
                        print(f"    PR #{pr['number']}: {pr['title']}")
                        print(f"    Issues: {', '.join(pr['issue_keys'])}")
            else:
                for pr in prs:
                    print(f"  - PR #{pr['number']}: {pr['title']}")
                    print(f"    Issues: {', '.join(pr['issue_keys'])}")

            print()
            choice = input("Process all PRs? (Y/n): ").strip().lower()
            if choice == 'n':
                return []
            return prs

    def show_issue_selector(self) -> List[str]:
        """Show interactive menu to select issues"""
        # Get issues based on configured filter
        issue_filter = self.config_manager.get('issue_filter', 'sprint')

        if issue_filter == 'sprint':
            # Active sprint only (no fallback)
            issues = self.get_my_active_sprint_issues()
        elif issue_filter == 'open':
            # All open issues
            issues = self.get_my_issues()
            if issues:
                issues = issues[:20]  # Limit to 20
        elif issue_filter == 'active':
            # In Progress + Review only
            in_progress = self.get_my_issues(status='In Progress')
            review = self.get_my_issues(status='Review')
            issues = in_progress + review
        elif issue_filter == 'custom':
            # Custom statuses
            custom_statuses = self.config_manager.get('custom_statuses', 'In Progress, Review')
            status_list = [s.strip() for s in custom_statuses.split(',')]
            issues = []
            for status in status_list:
                issues.extend(self.get_my_issues(status=status))
        else:
            # Default to sprint (no fallback)
            issues = self.get_my_active_sprint_issues()

        if not issues:
            print("\n❌ No issues found matching your filter")
            print("   💡 Configure your issue filter: jira-pr-summary --setup")
            return []

        try:
            import questionary
            from questionary import Choice

            print()  # Add spacing

            # Build choices with issue details
            choices = []
            for issue in issues:
                key = issue['key']
                summary = issue['fields'].get('summary', 'No summary').strip()
                status = issue['fields'].get('status', {}).get('name', 'Unknown')

                # Truncate summary intelligently - don't cut in middle of word
                max_summary_len = 80
                if len(summary) > max_summary_len:
                    summary = summary[:max_summary_len].rsplit(' ', 1)[0] + '...'

                # Format: "ACM-12345 [In Progress] - Issue summary here..."
                display_text = f"{key} [{status}] - {summary}"
                choices.append(Choice(title=display_text, value=key))

            selected = questionary.checkbox(
                "Select issues to update:",
                choices=choices,
                instruction="(Use arrow keys, space to select, a to toggle all, enter to confirm)",
                qmark="📋"
            ).ask()

            return selected if selected else []

        except ImportError:
            # Fallback to old numbered menu if questionary not available
            print("\n" + "=" * 70)
            print("SELECT ISSUES TO UPDATE")
            print("=" * 70)

            # Determine header based on filter
            issue_filter = self.config_manager.get('issue_filter', 'sprint')
            if issue_filter == 'sprint':
                print(f"\n🏃 Active Sprint Issues:")
            elif issue_filter == 'active':
                print(f"\n⚡ In Progress + Review Issues:")
            elif issue_filter == 'custom':
                print(f"\n🎯 Custom Filter Issues:")
            else:
                print(f"\n📋 Open Issues:")

            for i, issue in enumerate(issues, 1):
                key = issue['key']
                summary = issue['fields'].get('summary', 'No summary')
                status = issue['fields'].get('status', {}).get('name', 'Unknown')
                print(f"  {i}. {key} - {summary[:60]}")
                print(f"     Status: {status}")

            print("\n" + "-" * 70)
            print("Select issues (comma-separated numbers, or 'all', or Enter to cancel):")
            choice = input("> ").strip()

            if not choice:
                return []

            if choice.lower() == 'all':
                return [issue['key'] for issue in issues]

            # Parse selection
            selected_keys = []
            try:
                for num_str in choice.split(','):
                    num = int(num_str.strip())
                    if 1 <= num <= len(issues):
                        selected_keys.append(issues[num - 1]['key'])
            except ValueError:
                print("❌ Invalid selection")
                return []

            return selected_keys

    def process_manual_issue(self, issue_key: str) -> bool:
        """Process an issue manually without a PR"""
        print(f"\n{'='*70}")
        print(f"Manual Summary for {issue_key}")
        print('='*70)

        # Get current status
        status = self.get_issue_status(issue_key)
        if not status:
            print(f"❌ Could not fetch status for {issue_key}")
            return False

        issue_title = self.get_issue_summary(issue_key)
        if issue_title:
            print(f"Issue: {issue_title}")

        print(f"Status: {status}")

        # Offer to transition status
        self.offer_status_transition(issue_key, status, pr_merged=False)

        print("\n" + "="*70)
        print("WRITE YOUR SUMMARY")
        print("="*70)
        print("Explain what you did for this issue:")
        print("  - What was the problem/requirement?")
        print("  - What did you do? (investigation, fix, decision made)")
        print("  - Why did you make that choice?")
        print("  - Any important technical details?")
        print("  - What are the next steps?")
        print("\nType your summary below (press Ctrl+D when done):")
        print("─"*70)

        summary_lines = []
        try:
            while True:
                line = input()
                summary_lines.append(line)
        except EOFError:
            pass

        summary = "\n".join(summary_lines).strip()

        if not summary:
            print("Empty summary - skipping")
            return False

        print("\n" + "─"*70)
        print("YOUR SUMMARY:")
        print("─"*70)
        print(summary)
        print("─"*70)

        # Ask if they want to post
        action = self._ask_post_action(issue_key, cancel_label="Cancel")

        if action == "edit":
            print("\nEdit your summary (press Ctrl+D when done):")
            print("─"*70)
            lines = []
            try:
                while True:
                    line = input()
                    lines.append(line)
            except EOFError:
                pass
            summary = "\n".join(lines).strip()

            if not summary:
                print("Empty summary - skipping")
                return False
        elif action != "post":
            print("Cancelled")
            return False

        # Post comment
        print(f"\n📤 Posting comment to {issue_key}...")
        if self.post_comment(issue_key, summary):
            print(f"✅ Successfully posted comment to {issue_key}")
            print(f"   View: {self.jira_base}/browse/{issue_key}")
            return True
        else:
            print(f"❌ Failed to post comment to {issue_key}")
            return False

    def run(self, pr_numbers: Optional[List[int]] = None, issue_keys: Optional[List[str]] = None,
            days: int = 7, list_only: bool = False, update_issues: Optional[List[str]] = None,
            close_issues: Optional[List[str]] = None,
            force: bool = False, dry_run: bool = False, auto_approve: bool = False, backfill: bool = False,
            author: Optional[str] = None):
        """Main entry point"""

        if dry_run:
            print("🔍 DRY RUN MODE - No changes will be posted to Jira (auto-approve enabled)\n")

        if backfill:
            print("📦 BACKFILL MODE - Posting summaries for unposted PRs\n")
        elif auto_approve and not dry_run:
            print("✅ AUTO-APPROVE MODE - Skipping confirmations\n")

        # Handle --update mode (doesn't need a repository)
        if update_issues is not None:
            # If --update with no args, show interactive selector
            if not update_issues:
                update_issues = self.show_issue_selector()
                if not update_issues:
                    return  # User cancelled

            # Process issues directly without a PR
            for issue in update_issues:
                self.process_manual_issue(issue)
            return  # Done with update mode

        # Handle --close mode (doesn't need a repository)
        if close_issues is not None:
            # If --close with no args, show interactive selector
            if not close_issues:
                close_issues = self.show_issue_selector()
                if not close_issues:
                    return  # User cancelled

            # Close each issue (AI will be handled in close_issue method)
            for issue_key in close_issues:
                self.close_issue(issue_key, use_ai=self.use_ai, dry_run=dry_run)

            return  # Done with close mode

        # For PR/issue operations, we need a repository
        if not self.repo and (pr_numbers or issue_keys):
            print("❌ Not in a git directory. The --repo flag is required when using --pr or --issue")
            print("   💡 Use --repo to specify the repository explicitly")
            if pr_numbers:
                print(f"   Example: jira-pr-summary --pr {pr_numbers[0]} --repo owner/repo")
            else:
                print(f"   Example: jira-pr-summary --issue {issue_keys[0]} --repo owner/repo")
            return

        if pr_numbers:
            # Process specific PR(s) - group by issue
            prs_to_process = []
            for pr_number in pr_numbers:
                pr = self.get_pr_details(pr_number)
                if not pr:
                    print(f"❌ Could not find PR #{pr_number}")
                    if self.repo:
                        print(f"   Repository: {self.repo}")
                    else:
                        print(f"   No repository specified - use --repo flag")
                    print(f"   Make sure the PR exists and is accessible")
                    continue  # Continue to next PR instead of returning

                if not pr.get('mergedAt'):
                    print(f"⚠️  Warning: PR #{pr_number} is not merged yet")
                    choice = input("Continue anyway? (y/N): ").strip().lower()
                    if choice != 'y':
                        continue  # Continue to next PR

                prs_to_process.append(pr)

            # Group PRs by issue and process (only combine if similar)
            if prs_to_process:
                grouped = self._group_prs_by_issue(prs_to_process)
                for issue_key, issue_prs in grouped.items():
                    # Check if PRs are similar (backports) - if so, combine them
                    if self._are_prs_similar(issue_prs):
                        # Similar PRs (backports) - combine into one comment
                        self.process_prs_for_issue(issue_key, issue_prs, interactive=True,
                                                   force=force, dry_run=dry_run, auto_approve=auto_approve)
                    else:
                        # Different PRs - process individually
                        if self.verbose:
                            print(f"ℹ️  PRs for {issue_key} have different titles - processing separately")
                        for pr in issue_prs:
                            self.process_pr(pr, interactive=True, force=force, dry_run=dry_run, auto_approve=auto_approve)

        elif issue_keys:
            # Check if user wants to filter by assignment
            jira_user = self.config_manager.get('jira_user')
            if jira_user:
                # Filter issue keys to only those assigned to user
                my_issue_keys = self.get_my_issue_keys(issue_keys)
                if not my_issue_keys:
                    print(f"❌ None of the specified issues are assigned to {jira_user}")
                    print(f"   Issues: {', '.join(issue_keys)}")
                    print(f"   💡 Configure different user: jira-pr-summary --setup")
                    return

                filtered_out = set(issue_keys) - my_issue_keys
                if filtered_out:
                    print(f"   ℹ️  Filtered out {len(filtered_out)} issue(s) not assigned to {jira_user}: {', '.join(filtered_out)}")

                issue_keys = list(my_issue_keys)

            # Find all PRs for these issues and process grouped by issue
            for issue_key in issue_keys:
                print(f"🔍 Searching for merged PRs related to {issue_key}...")
                prs = self.find_merged_prs(days=days, issue_key=issue_key)

                if not prs:
                    print(f"No merged PRs found for {issue_key} in the last {days} days")
                    continue

                print(f"Found {len(prs)} PR(s)")
                # Check if PRs are similar (backports) - if so, combine them
                if self._are_prs_similar(prs):
                    # Similar PRs (backports) - combine into one comment
                    self.process_prs_for_issue(issue_key, prs, interactive=True,
                                               force=force, dry_run=dry_run, auto_approve=auto_approve)
                else:
                    # Different PRs - process individually
                    if self.verbose:
                        print(f"ℹ️  PRs for {issue_key} have different titles - processing separately")
                    for pr in prs:
                        self.process_pr(pr, interactive=True, force=force, dry_run=dry_run, auto_approve=auto_approve)

        else:
            # Default mode: Find all recent merged PRs with issue keys
            # Check if searching across all repos
            search_all_repos = False

            # Need a repository for this (unless searching all repos)
            if not self.repo:
                print("ℹ️  No repository detected from current directory")
                self.repo = self._select_repo_interactive()
                if not self.repo:
                    print("\n❌ No repository selected. Exiting.")
                    return

                # Check for special "__all_repos__" marker
                if self.repo == "__all_repos__":
                    search_all_repos = True
                    self.repo = None  # Clear repo since we're searching all
                else:
                    print(f"📍 Using repository: {self.repo}")
                    self._update_repo_history(self.repo)

            # Find PRs
            if search_all_repos:
                print(f"🔍 Searching across all repositories...")
                prs = self.find_merged_prs_all_repos(days=days)
            else:
                print(f"🔍 Searching for merged PRs in the last {days} days...")
                prs = self.find_merged_prs(days=days)

            if not prs:
                print(f"❌ No merged PRs with issue keys found in the last {days} days")
                print(f"   💡 PRs must have issue keys (like ACM-12345) in title or description")
                print(f"   💡 Try: --days 14 to search longer, or --pr <number> for specific PR")
                return

            # Filter PRs by user assignment if configured
            jira_user = self.config_manager.get('jira_user')
            if jira_user:
                total_prs = len(prs)
                prs = self.filter_prs_by_user(prs)
                filtered_count = total_prs - len(prs)
                if filtered_count > 0:
                    print(f"   ℹ️  Filtered out {filtered_count} PR(s) not assigned to {jira_user}")

                if not prs:
                    print(f"❌ No PRs found assigned to {jira_user}")
                    print(f"   💡 Configure different user: jira-pr-summary --setup")
                    return

            # Filter PRs by author if specified, or use github_user from config
            filter_author = author
            if not filter_author:
                # Use github_user from config if set
                filter_author = self.config_manager.get('github_user')

            if filter_author:
                total_prs = len(prs)
                prs = self.filter_prs_by_author(prs, filter_author)
                filtered_count = total_prs - len(prs)
                if filtered_count > 0:
                    if author:
                        # Explicit --author flag
                        print(f"   ℹ️  Filtered out {filtered_count} PR(s) not authored by {filter_author}")
                    else:
                        # Using github_user from config
                        print(f"   ℹ️  Filtered out {filtered_count} PR(s) not authored by {filter_author} (from config)")

                if not prs:
                    if author:
                        print(f"❌ No PRs found authored by {filter_author}")
                    else:
                        print(f"❌ No PRs found authored by {filter_author} (your GitHub username from config)")
                        print(f"   💡 Configure different GitHub username: jira-pr-summary --setup")
                    return

            # For cross-repo searches, filter out already-posted PRs by default (unless --force)
            if search_all_repos and not force:
                unposted_prs = []
                filtered_prs = []
                for pr in prs:
                    pr_number = pr['number']
                    # Check if this PR has been posted to any of its issues
                    already_posted = False
                    posted_to_issues = []
                    for issue_key in pr['issue_keys']:
                        if self._is_pr_cached(issue_key, pr_number):
                            already_posted = True
                            posted_to_issues.append(issue_key)
                    if not already_posted:
                        unposted_prs.append(pr)
                    else:
                        filtered_prs.append((pr, posted_to_issues))

                total_count = len(prs)
                filtered_count = total_count - len(unposted_prs)
                if filtered_count > 0:
                    print(f"   ℹ️  Filtered out {filtered_count} already-posted PR(s)")

                    if self.verbose and filtered_prs:
                        print(f"🔍 [DEBUG] Filtered PRs:")
                        for pr, issues in filtered_prs:
                            pr_title = pr.get('title', 'No title')[:60]
                            repo_name = pr.get('repo_name', 'unknown')
                            print(f"   - PR #{pr['number']} ({repo_name}): {pr_title} (posted to {', '.join(issues)})")

                if not unposted_prs:
                    print(f"\n✅ All {total_count} PR(s) have already been posted!")
                    print(f"   💡 Use --force to re-post")
                    return

                prs = unposted_prs

            # In backfill mode, filter out already-posted PRs
            if backfill:
                unposted_prs = []
                filtered_prs = []
                for pr in prs:
                    pr_number = pr['number']
                    # Check if this PR has been posted to any of its issues
                    already_posted = False
                    posted_to_issues = []
                    for issue_key in pr['issue_keys']:
                        if self._is_pr_cached(issue_key, pr_number):
                            already_posted = True
                            posted_to_issues.append(issue_key)
                    if not already_posted:
                        unposted_prs.append(pr)
                    else:
                        filtered_prs.append((pr, posted_to_issues))

                print(f"\nFound {len(prs)} total merged PR(s), {len(unposted_prs)} not yet posted:")

                if self.verbose and filtered_prs:
                    print(f"🔍 [DEBUG] Filtered out {len(filtered_prs)} already-posted PR(s):")
                    for pr, issues in filtered_prs:
                        pr_title = pr.get('title', 'No title')[:60]
                        print(f"   - PR #{pr['number']}: {pr_title} (posted to {', '.join(issues)})")

                if not unposted_prs:
                    print("✅ All PRs have already been posted!")
                    return
                prs = unposted_prs
            else:
                # In normal mode, also filter out already-posted PRs (unless --force)
                if not force:
                    unposted_prs = []
                    filtered_prs = []
                    for pr in prs:
                        pr_number = pr['number']
                        # Check if this PR has been posted to any of its issues
                        already_posted = False
                        posted_to_issues = []
                        for issue_key in pr['issue_keys']:
                            if self._is_pr_cached(issue_key, pr_number):
                                already_posted = True
                                posted_to_issues.append(issue_key)
                        if not already_posted:
                            unposted_prs.append(pr)
                        else:
                            filtered_prs.append((pr, posted_to_issues))

                    total_count = len(prs)
                    filtered_count = total_count - len(unposted_prs)

                    if filtered_count > 0:
                        print(f"\nFound {total_count} total merged PR(s), {len(unposted_prs)} not yet posted:")
                        print(f"   ℹ️  Filtered out {filtered_count} already-posted PR(s)")

                        if self.verbose and filtered_prs:
                            print(f"🔍 [DEBUG] Filtered PRs:")
                            for pr, issues in filtered_prs:
                                pr_title = pr.get('title', 'No title')[:60]
                                print(f"   - PR #{pr['number']}: {pr_title} (posted to {', '.join(issues)})")

                        if not unposted_prs:
                            print(f"\n✅ All {total_count} PR(s) have already been posted!")
                            print(f"   💡 Use --force to re-post")
                            return

                        prs = unposted_prs
                    else:
                        print(f"\nFound {len(prs)} merged PR(s) with issue keys:")
                else:
                    print(f"\nFound {len(prs)} merged PR(s) with issue keys:")

            if list_only:
                # Just show the list
                has_repo_info = any('repo_name' in pr for pr in prs)

                if has_repo_info:
                    # Group by repository
                    from collections import defaultdict
                    prs_by_repo = defaultdict(list)
                    for pr in prs:
                        repo_name = pr.get('repo_name', 'unknown/repo')
                        prs_by_repo[repo_name].append(pr)

                    for repo_name in sorted(prs_by_repo.keys()):
                        print(f"\n📦 {repo_name}")
                        for pr in prs_by_repo[repo_name]:
                            print(f"    PR #{pr['number']}: {pr['title']}")
                            print(f"    Issues: {', '.join(pr['issue_keys'])}")
                else:
                    # Single repo
                    for pr in prs:
                        print(f"  - PR #{pr['number']}: {pr['title']}")
                        print(f"    Issues: {', '.join(pr['issue_keys'])}")
                return

            # Interactive PR selector (unless auto-approve is on)
            if not auto_approve:
                selected_prs = self._select_prs_interactive(prs)
                if not selected_prs:
                    print("\n❌ No PRs selected. Exiting.")
                    return
                prs = selected_prs

            # Group PRs by issue and process together (only if similar)
            grouped = self._group_prs_by_issue(prs)
            for issue_key, issue_prs in grouped.items():
                # Check if PRs are similar (backports) - if so, combine them
                if self._are_prs_similar(issue_prs):
                    # Similar PRs (backports) - combine into one comment
                    # For cross-repo, temporarily set repo from first PR
                    saved_repo = self.repo
                    if issue_prs and 'repo_name' in issue_prs[0]:
                        self.repo = issue_prs[0]['repo_name']

                    self.process_prs_for_issue(issue_key, issue_prs, interactive=True,
                                               force=force, dry_run=dry_run, auto_approve=auto_approve)

                    # Restore original repo
                    self.repo = saved_repo
                else:
                    # Different PRs - process individually
                    if self.verbose:
                        print(f"ℹ️  PRs for {issue_key} have different titles - processing separately")
                    for pr in issue_prs:
                        # For cross-repo, temporarily set repo for this PR
                        saved_repo = self.repo
                        if 'repo_name' in pr:
                            self.repo = pr['repo_name']

                        self.process_pr(pr, interactive=True, force=force, dry_run=dry_run, auto_approve=auto_approve)

                        # Restore original repo
                        self.repo = saved_repo


def main():
    parser = argparse.ArgumentParser(
        description="Generate and post Jira summaries from merged PRs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check recently merged PRs (last 7 days)
  %(prog)s

  # Process a specific PR
  %(prog)s --pr 123

  # Process all PRs for a specific issue
  %(prog)s --issue ACM-12345

  # Process all PRs for multiple issues
  %(prog)s --issue ACM-12345 ACM-67890 ACM-99999

  # Check last 14 days
  %(prog)s --days 14

  # List PRs without posting
  %(prog)s --list-only

  # Update an issue directly (no PR required)
  %(prog)s --update ACM-12345

  # Update multiple issues directly
  %(prog)s --update ACM-12345 ACM-67890 ACM-99999

  # Show interactive issue selector
  %(prog)s --update

  # Close an issue with summary
  %(prog)s --close ACM-12345

  # Close multiple issues
  %(prog)s --close ACM-12345 ACM-67890

  # Show interactive selector to close issues
  %(prog)s --close

  # Use AI-powered summaries (requires Ollama)
  %(prog)s --pr 123 --ai

Author: Disaiah Bennett
Report issues: https://github.com/stolostron/installer-dev-tools/issues
        """
    )

    # Configuration commands
    parser.add_argument('--setup', action='store_true', help='Run first-time setup wizard')
    parser.add_argument('--show-config', action='store_true', help='Display current configuration')
    parser.add_argument('--reset-config', action='store_true', help='Delete configuration and start fresh')

    # Profile management
    parser.add_argument('--profile', help='Use a specific profile (e.g., --profile acm-installer)')
    parser.add_argument('--create-profile', nargs='?', const='', help='Create a new profile (optionally with name)')
    parser.add_argument('--list-profiles', action='store_true', help='List all available profiles')
    parser.add_argument('--delete-profile', help='Delete a profile')
    parser.add_argument('--switch-profile', help='Switch to a different profile and make it the default')

    # Main operation commands
    parser.add_argument('--pr', nargs='+', type=int, help='Process one or more PR numbers (e.g., --pr 123 456 789)')
    parser.add_argument('--issue', nargs='+', help='Process all PRs for one or more issues (e.g., ACM-12345 ACM-67890)')
    parser.add_argument('--update', nargs='*', help='Update issues directly (without PRs). With no args, shows interactive issue selector. With args, updates specified issues (e.g., --update ACM-12345 ACM-67890)')
    parser.add_argument('--close', nargs='*', help='Close issues with required summary. With no args, shows interactive issue selector. With args, closes specified issues (e.g., --close ACM-12345 ACM-67890)')
    parser.add_argument('--repo', help='GitHub repository (e.g., owner/repo). Auto-detects from git config if not specified.')
    parser.add_argument('--days', type=int, default=7, help='Number of days to look back (default: 7)')
    parser.add_argument('--list-only', action='store_true', help='List PRs without posting to Jira')
    parser.add_argument('--ai', action='store_true', help='Use AI-powered summaries via Ollama (can be configured as default in setup)')
    parser.add_argument('--no-ai', action='store_true', help='Disable AI-powered summaries (overrides config default)')
    parser.add_argument('--force', action='store_true', help='Force posting even if PR was already posted to this issue')
    parser.add_argument('--dry-run', action='store_true', help='Preview what would be posted without actually posting to Jira')
    parser.add_argument('--yes', '-y', action='store_true', help='Auto-approve all prompts (skip confirmations)')
    parser.add_argument('--backfill', action='store_true', help='Post summaries for old PRs not yet posted (respects cache, implies --yes)')
    parser.add_argument('--include-commits', action='store_true', help='Include commit messages in summary')

    # Cache management
    parser.add_argument('--show-cache', action='store_true', help='Display cache contents (posted PRs)')
    parser.add_argument('--clear-cache', nargs='*', help='Clear cache. With no args, clears all. With args, clears specific issues (e.g., ACM-12345)')
    parser.add_argument('--generate-report', nargs='*', help='Generate work summary report from cache. With no args, shows all. With args, filters by issues (e.g., ACM-12345)')
    parser.add_argument('--metrics', action='store_true', help='Show work metrics and activity trends from cache')
    parser.add_argument('--format', choices=['text', 'json', 'csv', 'markdown'], default='text', help='Report output format (default: text)')
    parser.add_argument('--from', dest='date_from', help='Filter report from date (YYYY-MM-DD)')
    parser.add_argument('--to', dest='date_to', help='Filter report to date (YYYY-MM-DD)')


    # Filtering
    parser.add_argument('--author', help='Filter PRs by author username (e.g., dbennett)')

    # Debug/verbose
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed debug information (API calls, JQL queries, etc.)')

    args = parser.parse_args()

    # Load config with optional profile
    config = Config(profile=args.profile if hasattr(args, 'profile') else None)

    # Check token expiry (skip for config/profile management commands)
    skip_expiry_check = (
        args.setup or
        args.reset_config or
        (hasattr(args, 'list_profiles') and args.list_profiles) or
        (hasattr(args, 'create_profile') and args.create_profile is not None) or
        (hasattr(args, 'delete_profile') and args.delete_profile) or
        (hasattr(args, 'switch_profile') and args.switch_profile)
    )

    if not skip_expiry_check and config.is_configured():
        config.check_token_expiry()

    # Handle profile management commands first
    if hasattr(args, 'list_profiles') and args.list_profiles:
        profiles = config.list_profiles()
        if profiles:
            active = config.active_profile
            print("Available profiles:")
            for profile in profiles:
                marker = " (active)" if profile == active else ""
                print(f"  - {profile}{marker}")
        else:
            print("No profiles found. Run --setup to create the default profile.")
        return

    if hasattr(args, 'create_profile') and args.create_profile is not None:
        profile_name = args.create_profile if args.create_profile else None
        config.run_profile_wizard(profile_name)
        return

    if hasattr(args, 'delete_profile') and args.delete_profile:
        config.delete_profile(args.delete_profile)
        return

    if hasattr(args, 'switch_profile') and args.switch_profile:
        config.switch_profile(args.switch_profile)
        return

    # Handle config commands
    if args.setup:
        config.run_first_time_setup()
        return

    if args.show_config:
        if not config.is_configured():
            print("⚠️  Not configured yet. Run 'jira-pr-summary --setup' first.")
        else:
            config.show_config()
        return

    if args.reset_config:
        config.reset_config()
        return

    if args.show_cache:
        from datetime import timedelta

        if os.path.exists(config.cache_file):
            try:
                with open(config.cache_file, 'r') as f:
                    cache = json.load(f)

                if not cache:
                    print("📦 Cache is empty")
                    return

                # Get expiry settings
                expiry_days = config.get('cache_expiry_days', 90)
                cutoff_date = None
                if expiry_days > 0:
                    cutoff_date = datetime.now(timezone.utc) - timedelta(days=expiry_days)

                print("=" * 70)
                print("CACHE CONTENTS (Posted PRs)")
                print("=" * 70)
                if expiry_days == 0:
                    print("Cache expiry: NEVER (keep forever)")
                else:
                    print(f"Cache expiry: {expiry_days} days")
                    print(f"Entries older than {cutoff_date.strftime('%Y-%m-%d')} are auto-removed")

                total_prs = 0
                expired_count = 0
                for issue_key in sorted(cache.keys()):
                    # Skip special cache keys like _repo_history
                    if issue_key.startswith('_'):
                        continue

                    prs = cache[issue_key]
                    total_prs += len(prs)
                    print(f"\n{issue_key} ({len(prs)} PR(s)):")
                    for pr_num in sorted(prs.keys(), key=int):
                        pr_info = prs[pr_num]
                        timestamp = pr_info.get('timestamp', 'unknown')
                        is_expired = False
                        try:
                            dt = datetime.fromisoformat(timestamp)
                            date_str = dt.strftime('%Y-%m-%d %H:%M')
                            if cutoff_date and dt < cutoff_date:
                                is_expired = True
                                expired_count += 1
                        except:
                            date_str = timestamp
                        pr_url = pr_info.get('pr_url', '')

                        status_mark = " [EXPIRED]" if is_expired else ""
                        print(f"  - PR #{pr_num} (posted: {date_str}){status_mark}")
                        if pr_url:
                            print(f"    {pr_url}")

                print("\n" + "=" * 70)
                # Count only issue keys (exclude special keys starting with _)
                issue_count = sum(1 for key in cache.keys() if not key.startswith('_'))
                print(f"Total: {issue_count} issue(s), {total_prs} PR(s)")
                if expired_count > 0:
                    print(f"⚠️  {expired_count} expired entry(ies) shown above")
                    print(f"   These will be auto-removed on next cache load")
                print("=" * 70)

                # Show PR cache stats
                if '_pr_cache' in cache and cache['_pr_cache']:
                    pr_cache = cache['_pr_cache']
                    print("\n" + "=" * 70)
                    print("PR DETAILS CACHE (Performance)")
                    print("=" * 70)
                    print(f"Cached PRs: {len(pr_cache)} (no expiration - merged PRs don't change)")
                    print("\nCached PR details:")
                    for cache_key in sorted(pr_cache.keys()):
                        pr_data = pr_cache[cache_key]
                        pr_num = pr_data.get('number', 'unknown')
                        title = pr_data.get('title', 'No title')
                        cached_at = pr_data.get('cached_at', 'unknown')
                        try:
                            dt = datetime.fromisoformat(cached_at)
                            date_str = dt.strftime('%Y-%m-%d %H:%M')
                        except:
                            date_str = cached_at

                        # Truncate title if too long
                        if len(title) > 60:
                            title = title[:57] + "..."

                        print(f"  - {cache_key}: {title}")
                        print(f"    Cached: {date_str}")

                    print("=" * 70)
                    print("💡 Cached PRs load instantly without GitHub API calls")
                    print("=" * 70)

                # Show Jira metadata cache stats
                if '_jira_cache' in cache and cache['_jira_cache']:
                    jira_cache = cache['_jira_cache']
                    print("\n" + "=" * 70)
                    print("JIRA METADATA CACHE (Performance)")
                    print("=" * 70)
                    print(f"Cached issues: {len(jira_cache)} (TTL: 5 minutes)")
                    print("\nCached issue metadata:")

                    for issue_key in sorted(jira_cache.keys()):
                        issue_data = jira_cache[issue_key]
                        summary = issue_data.get('summary', 'No summary')
                        status = issue_data.get('status', 'Unknown')
                        cached_at = issue_data.get('cached_at', 'unknown')

                        # Check if expired
                        expired_mark = ""
                        try:
                            cached_time = datetime.fromisoformat(cached_at)
                            now = datetime.now(timezone.utc)
                            age_seconds = (now - cached_time).total_seconds()
                            date_str = cached_time.strftime('%Y-%m-%d %H:%M')

                            if age_seconds > 300:  # 5 minutes
                                expired_mark = " [EXPIRED]"
                        except:
                            date_str = cached_at

                        # Truncate summary if too long
                        if len(summary) > 50:
                            summary = summary[:47] + "..."

                        print(f"  - {issue_key}: {summary}")
                        print(f"    Status: {status} | Cached: {date_str}{expired_mark}")

                    print("=" * 70)
                    print("💡 Cached issue data reduces repeated Jira API calls")
                    print("=" * 70)

                # Show repo detection cache stats
                if '_repo_detection' in cache and cache['_repo_detection']:
                    repo_cache = cache['_repo_detection']
                    print("\n" + "=" * 70)
                    print("REPOSITORY DETECTION CACHE (Performance)")
                    print("=" * 70)
                    print(f"Cached directories: {len(repo_cache)}")
                    print("\nCached repository detections:")

                    for cwd, repo in sorted(repo_cache.items()):
                        # Shorten path if too long
                        if len(cwd) > 50:
                            display_path = "..." + cwd[-47:]
                        else:
                            display_path = cwd

                        print(f"  - {display_path}")
                        print(f"    Repository: {repo}")

                    print("=" * 70)
                    print("💡 Cached repos skip git commands on subsequent runs")
                    print("=" * 70)

            except Exception as e:
                print(f"❌ Error reading cache: {e}")
        else:
            print(f"ℹ️  No cache file found at {config.cache_file}")
        return

    def export_report_json(report_data):
        """Export report as JSON"""
        import json
        return json.dumps(report_data, indent=2)

    def export_report_csv(report_data):
        """Export report as CSV"""
        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow(['Date', 'Issue Key', 'Issue Summary', 'Issue Status', 'PR Number', 'PR Title', 'PR URL', 'Posted At'])

        # Rows
        for date_str in sorted(report_data['by_date'].keys(), reverse=True):
            for issue_key, prs in sorted(report_data['by_date'][date_str].items()):
                issue_summary = report_data['issue_summaries'].get(issue_key, '')
                issue_status = report_data['issue_statuses'].get(issue_key, '')

                for pr_data in prs:
                    pr_num = pr_data['pr_num']
                    pr_title = report_data['pr_titles'].get(pr_num, '')
                    pr_url = pr_data['pr_url']
                    timestamp = pr_data['timestamp']
                    try:
                        dt = datetime.fromisoformat(timestamp)
                        time_str = dt.strftime('%Y-%m-%d %H:%M')
                    except:
                        time_str = timestamp

                    writer.writerow([date_str, issue_key, issue_summary, issue_status, pr_num, pr_title, pr_url, time_str])

        return output.getvalue()

    def export_report_markdown(report_data):
        """Export report as Markdown"""
        lines = []
        lines.append("# Work Summary Report")
        lines.append(f"\nGenerated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

        for date_str in sorted(report_data['by_date'].keys(), reverse=True):
            lines.append(f"\n## {date_str}\n")

            for issue_key, prs in sorted(report_data['by_date'][date_str].items()):
                issue_summary = report_data['issue_summaries'].get(issue_key, '')
                issue_status = report_data['issue_statuses'].get(issue_key, '')

                if issue_summary and issue_status:
                    lines.append(f"### {issue_key}: {issue_summary} [{issue_status}]\n")
                elif issue_summary:
                    lines.append(f"### {issue_key}: {issue_summary}\n")
                else:
                    lines.append(f"### {issue_key}\n")

                for pr_data in prs:
                    pr_num = pr_data['pr_num']
                    pr_title = report_data['pr_titles'].get(pr_num, '')
                    pr_url = pr_data['pr_url']
                    timestamp = pr_data['timestamp']
                    try:
                        dt = datetime.fromisoformat(timestamp)
                        time_str = dt.strftime('%H:%M')
                    except:
                        time_str = ''

                    if pr_title:
                        if time_str:
                            lines.append(f"- **PR #{pr_num}**: {pr_title} at {time_str}")
                        else:
                            lines.append(f"- **PR #{pr_num}**: {pr_title}")
                    else:
                        if time_str:
                            lines.append(f"- PR #{pr_num} at {time_str}")
                        else:
                            lines.append(f"- PR #{pr_num}")

                    if pr_url:
                        lines.append(f"  - {pr_url}")
                    lines.append("")

        lines.append(f"\n---\n")
        lines.append(f"**Summary**: {report_data['total_issues']} issue(s), {report_data['total_prs']} PR(s) posted")

        return "\n".join(lines)

    if args.generate_report is not None:
        if not os.path.exists(config.cache_file):
            print(f"ℹ️  No cache file found at {config.cache_file}")
            print("   No work has been posted yet.")
            return

        try:
            with open(config.cache_file, 'r') as f:
                cache = json.load(f)
        except Exception as e:
            print(f"❌ Error reading cache: {e}")
            return

        if not cache:
            print("📦 Cache is empty - no work posted yet")
            return

        # Filter by specific issues if provided
        if args.generate_report:
            filtered_cache = {}
            for issue_key in args.generate_report:
                issue_key_upper = issue_key.upper()
                if issue_key_upper in cache:
                    filtered_cache[issue_key_upper] = cache[issue_key_upper]

            if not filtered_cache:
                print(f"❌ No cached work found for: {', '.join(args.generate_report)}")
                return
            cache = filtered_cache

        # Create tracker instance to access Jira/GitHub APIs
        tracker = JiraPRSummary(config=config, verbose=False)

        # Fetch issue summaries and statuses from Jira
        print("Fetching issue details from Jira...")
        issue_summaries = {}
        issue_statuses = {}
        for issue_key in cache.keys():
            summary = tracker.get_issue_summary(issue_key)
            if summary:
                issue_summaries[issue_key] = summary

            status = tracker.get_issue_status(issue_key)
            if status:
                issue_statuses[issue_key] = status

        # Fetch PR details from GitHub
        print("Fetching PR details from GitHub...")
        pr_titles = {}
        all_pr_nums = set()
        for prs in cache.values():
            all_pr_nums.update(prs.keys())

        for pr_num in all_pr_nums:
            pr_details = tracker.get_pr_details(int(pr_num))
            if pr_details and 'title' in pr_details:
                pr_titles[pr_num] = pr_details['title']

        # Build report data structure
        total_issues = len(cache)
        total_prs = sum(len(prs) for prs in cache.values())

        # Parse date range filters
        date_from = None
        date_to = None
        if args.date_from:
            try:
                date_from = datetime.strptime(args.date_from, '%Y-%m-%d').date()
            except ValueError:
                print(f"❌ Invalid --from date format: {args.date_from}. Use YYYY-MM-DD")
                return

        if args.date_to:
            try:
                date_to = datetime.strptime(args.date_to, '%Y-%m-%d').date()
            except ValueError:
                print(f"❌ Invalid --to date format: {args.date_to}. Use YYYY-MM-DD")
                return

        # Group by date
        from collections import defaultdict
        by_date = defaultdict(lambda: defaultdict(list))

        for issue_key in sorted(cache.keys()):
            prs = cache[issue_key]
            for pr_num in sorted(prs.keys(), key=int):
                pr_info = prs[pr_num]
                timestamp = pr_info.get('timestamp', '')
                try:
                    dt = datetime.fromisoformat(timestamp)
                    date_str = dt.strftime('%Y-%m-%d')
                    post_date = dt.date()

                    # Apply date range filter
                    if date_from and post_date < date_from:
                        continue
                    if date_to and post_date > date_to:
                        continue

                except:
                    date_str = 'unknown'

                by_date[date_str][issue_key].append({
                    'pr_num': pr_num,
                    'pr_url': pr_info.get('pr_url', ''),
                    'timestamp': timestamp
                })

        # Build report data for export
        report_data = {
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'total_issues': total_issues,
            'total_prs': total_prs,
            'by_date': dict(by_date),
            'issue_summaries': issue_summaries,
            'issue_statuses': issue_statuses,
            'pr_titles': pr_titles
        }

        # Output based on format
        output_format = args.format

        if output_format == 'json':
            print(export_report_json(report_data))
            return
        elif output_format == 'csv':
            print(export_report_csv(report_data))
            return
        elif output_format == 'markdown':
            print(export_report_markdown(report_data))
            return

        # Default: text format
        print("\n" + "=" * 70)
        print("WORK SUMMARY REPORT")
        print("=" * 70)
        print(f"Generated: {report_data['generated_at']}")
        print()

        # Print by date
        for date_str in sorted(by_date.keys(), reverse=True):
            print(f"\n📅 {date_str}")
            print("-" * 70)

            issues = by_date[date_str]
            for issue_key in sorted(issues.keys()):
                # Print issue with summary and status
                issue_summary = issue_summaries.get(issue_key, '')
                issue_status = issue_statuses.get(issue_key, '')

                if issue_summary and issue_status:
                    print(f"\n  {issue_key}: {issue_summary} [{issue_status}]")
                elif issue_summary:
                    print(f"\n  {issue_key}: {issue_summary}")
                elif issue_status:
                    print(f"\n  {issue_key} [{issue_status}]")
                else:
                    print(f"\n  {issue_key}")

                for pr_data in issues[issue_key]:
                    pr_num = pr_data['pr_num']
                    pr_url = pr_data['pr_url']
                    timestamp = pr_data['timestamp']
                    try:
                        dt = datetime.fromisoformat(timestamp)
                        time_str = dt.strftime('%H:%M')
                    except:
                        time_str = ''

                    # Print PR with title
                    pr_title = pr_titles.get(pr_num, '')
                    if pr_title:
                        if time_str:
                            print(f"    • PR #{pr_num}: {pr_title} at {time_str}")
                        else:
                            print(f"    • PR #{pr_num}: {pr_title}")
                    else:
                        if time_str:
                            print(f"    • PR #{pr_num} at {time_str}")
                        else:
                            print(f"    • PR #{pr_num}")

                    if pr_url:
                        print(f"      {pr_url}")

        print("\n" + "=" * 70)
        print(f"Summary: {total_issues} issue(s), {total_prs} PR(s) posted")
        print("=" * 70)
        return

    if args.metrics:
        # Hybrid metrics: fetch from GitHub, cross-reference with cache
        from collections import defaultdict, Counter
        from datetime import timedelta

        # Parse date range
        days_back = args.days if hasattr(args, 'days') and args.days else 30

        # Create tracker instance to use existing methods
        tracker = JiraPRSummary(use_ai=False, repo=args.repo, config=config, verbose=args.verbose)

        # Load cache
        cache = {}
        if os.path.exists(config.cache_file):
            try:
                with open(config.cache_file, 'r') as f:
                    cache = json.load(f)
            except Exception as e:
                print(f"⚠️  Warning: Could not read cache: {e}")

        # Build cache lookup: {repo: {pr_num: issue_key}}
        cache_lookup = {}
        for issue_key, prs in cache.items():
            if issue_key.startswith('_'):
                continue
            for pr_num, pr_info in prs.items():
                pr_url = pr_info.get('pr_url', '')
                if pr_url and 'github.com' in pr_url:
                    parts = pr_url.split('github.com/')
                    if len(parts) > 1:
                        repo = parts[1].split('/pull/')[0]
                        if repo not in cache_lookup:
                            cache_lookup[repo] = {}
                        cache_lookup[repo][int(pr_num)] = issue_key

        # Get repository list from cache history
        repos_to_check = []
        if '_repo_history' in cache and cache['_repo_history']:
            # Filter to only valid repos (owner/repo format)
            valid_repos = [r for r in cache['_repo_history']
                          if r and '/' in r and not r.startswith('✕') and not r.startswith('➕')]
            repos_to_check = valid_repos[:5]  # Check top 5 recent repos
        elif tracker.repo:
            repos_to_check = [tracker.repo]

        if not repos_to_check:
            print("ℹ️  No repository history found. Metrics require at least one repository.")
            print("   Run the tool at least once to build history.")
            return

        print(f"📊 Analyzing work from {len(repos_to_check)} repositories...")
        print()

        # Fetch merged PRs from GitHub for each repo
        all_merged_prs = []
        for repo in repos_to_check:
            tracker.repo = repo
            print(f"  Fetching from {repo}...")
            merged_prs = tracker.find_merged_prs(days=days_back)

            # Filter by author if configured
            github_user = config.get('github_user')
            if github_user:
                merged_prs = tracker.filter_prs_by_author(merged_prs, github_user)

            all_merged_prs.extend(merged_prs)

        if not all_merged_prs:
            print(f"\n📊 No merged PRs found in the last {days_back} days")
            return

        # Categorize PRs: posted vs not posted
        posted_prs = []
        not_posted_prs = []

        for pr in all_merged_prs:
            pr_num = pr.get('number')
            pr_repo = pr.get('repository', tracker.repo)

            # Check if in cache
            is_posted = (pr_repo in cache_lookup and
                        pr_num in cache_lookup[pr_repo])

            if is_posted:
                posted_prs.append(pr)
            else:
                not_posted_prs.append(pr)

        # Calculate metrics
        total_merged = len(all_merged_prs)
        total_posted = len(posted_prs)
        total_not_posted = len(not_posted_prs)
        posted_pct = (total_posted / total_merged * 100) if total_merged > 0 else 0

        # Repo breakdown
        repos_merged = Counter()
        repos_posted = Counter()
        for pr in all_merged_prs:
            repo = pr.get('repository', tracker.repo)
            repos_merged[repo] += 1
        for pr in posted_prs:
            repo = pr.get('repository', tracker.repo)
            repos_posted[repo] += 1

        # Week breakdown
        weeks_merged = defaultdict(int)
        weeks_posted = defaultdict(int)
        for pr in all_merged_prs:
            merged_at = pr.get('mergedAt', '')
            if merged_at:
                try:
                    pr_date = datetime.fromisoformat(merged_at.replace('Z', '+00:00'))
                    week_start = pr_date - timedelta(days=pr_date.weekday())
                    week_key = week_start.strftime('%Y-%m-%d')
                    weeks_merged[week_key] += 1
                except:
                    pass
        for pr in posted_prs:
            merged_at = pr.get('mergedAt', '')
            if merged_at:
                try:
                    pr_date = datetime.fromisoformat(merged_at.replace('Z', '+00:00'))
                    week_start = pr_date - timedelta(days=pr_date.weekday())
                    week_key = week_start.strftime('%Y-%m-%d')
                    weeks_posted[week_key] += 1
                except:
                    pass

        # Output metrics
        print()
        print("=" * 70)
        print("WORK METRICS - HYBRID VIEW")
        print("=" * 70)
        print(f"Period: Last {days_back} days")
        print()

        print("📊 SUMMARY")
        print("-" * 70)
        print(f"  🔀 Total PRs Merged:  {total_merged}")
        print(f"  ✅ Posted to Jira:    {total_posted} ({posted_pct:.0f}%)")
        print(f"  ⚠️ Not Posted Yet:    {total_not_posted}")
        print(f"  📦 Repositories:      {len(repos_merged)}")
        print()

        # Activity trend (last 4 weeks)
        print("📅 ACTIVITY TREND")
        print("-" * 70)
        sorted_weeks = sorted(weeks_merged.items(), key=lambda x: x[0], reverse=True)[:4]

        for week_start, merged_count in sorted_weeks:
            posted_count = weeks_posted.get(week_start, 0)
            week_date = datetime.strptime(week_start, '%Y-%m-%d')
            week_label = week_date.strftime('%b %d')

            # Determine label
            today = datetime.now()
            days_ago = (today - week_date).days
            if days_ago < 7:
                label = "Last 7 days:"
            else:
                label = f"Week of {week_label}:"

            print(f"  {label:20s} {merged_count:2d} merged, {posted_count:2d} posted")
        print()

        # Top repositories
        if repos_merged:
            print("🏆 REPOSITORIES")
            print("-" * 70)
            for i, (repo, merged_count) in enumerate(repos_merged.most_common(5), 1):
                posted_count = repos_posted.get(repo, 0)
                print(f"  {i}. {repo:40s} {merged_count:2d} merged, {posted_count:2d} posted")
            print()

        # Show gap - PRs not posted yet
        if not_posted_prs:
            print("⚠️  WORK NOT POSTED TO JIRA")
            print("-" * 70)
            print(f"  {len(not_posted_prs)} PR(s) merged but not posted via tool:")
            print()

            # Group by repo
            by_repo = defaultdict(list)
            for pr in not_posted_prs:
                repo = pr.get('repository', tracker.repo)
                by_repo[repo].append(pr)

            for repo, prs in sorted(by_repo.items()):
                print(f"  {repo}:")
                for pr in prs[:5]:  # Limit to 5 per repo
                    pr_num = pr.get('number')
                    title = pr.get('title', 'No title').strip()[:60]
                    print(f"    • PR #{pr_num}: {title}")

                if len(prs) > 5:
                    print(f"    ... and {len(prs) - 5} more")
                print()

        print("=" * 70)
        print("💡 TIP: Use --backfill to post missing PRs to Jira")
        print("=" * 70)
        return

    if args.clear_cache is not None:
        if not os.path.exists(config.cache_file):
            print(f"ℹ️  No cache file found at {config.cache_file}")
            return

        try:
            with open(config.cache_file, 'r') as f:
                cache = json.load(f)
        except Exception as e:
            print(f"❌ Error reading cache: {e}")
            return

        # If no args, clear all
        if not args.clear_cache:
            # Show what will be cleared
            issue_count = sum(1 for key in cache.keys() if not key.startswith('_'))
            pr_cache_count = len(cache.get('_pr_cache', {}))
            jira_cache_count = len(cache.get('_jira_cache', {}))
            repo_cache_count = len(cache.get('_repo_detection', {}))

            print(f"This will clear:")
            print(f"  - {issue_count} issue(s) with posted PR records")
            if pr_cache_count > 0:
                print(f"  - {pr_cache_count} cached PR details (GitHub)")
            if jira_cache_count > 0:
                print(f"  - {jira_cache_count} cached issue metadata (Jira)")
            if repo_cache_count > 0:
                print(f"  - {repo_cache_count} cached repository detections")

            confirm = input("\nClear entire cache? (y/N): ").strip().lower()
            if confirm == 'y':
                os.remove(config.cache_file)
                print(f"✅ Cache cleared: {config.cache_file}")
            else:
                print("Cancelled")
        else:
            # Clear specific issues
            cleared = []
            not_found = []
            for issue_key in args.clear_cache:
                issue_key_upper = issue_key.upper()
                if issue_key_upper in cache:
                    del cache[issue_key_upper]
                    cleared.append(issue_key_upper)
                else:
                    not_found.append(issue_key)

            if cleared:
                with open(config.cache_file, 'w') as f:
                    json.dump(cache, f, indent=2)
                print(f"✅ Cleared cache for: {', '.join(cleared)}")

            if not_found:
                print(f"ℹ️  Not in cache: {', '.join(not_found)}")

        return

    # Check if configured
    if not config.is_configured():
        print("⚠️  Not configured yet.")
        print("\nRun the setup wizard:")
        print("  jira-pr-summary --setup\n")
        sys.exit(1)

    # Determine AI usage: --no-ai > --ai > config default
    # For --close mode, only use AI if explicitly requested with --ai flag (ignore config default)
    if args.close is not None:
        # Closing mode: AI only if --ai explicitly passed
        use_ai = args.ai and not args.no_ai
    else:
        # PR/update modes: respect config default
        if args.no_ai:
            use_ai = False
        elif args.ai:
            use_ai = True
        else:
            use_ai = config.get('use_ai', False)

    # Create tracker with config
    tracker = JiraPRSummary(use_ai=use_ai, repo=args.repo, config=config, include_commits=args.include_commits, verbose=args.verbose)

    # Backfill and dry-run imply auto-approve
    auto_approve = args.yes or args.backfill or args.dry_run

    # Run main operation
    tracker.run(pr_numbers=args.pr, issue_keys=args.issue, days=args.days,
                list_only=args.list_only, update_issues=args.update, close_issues=args.close,
                force=args.force, dry_run=args.dry_run, auto_approve=auto_approve,
                backfill=args.backfill, author=args.author)


if __name__ == '__main__':
    main()
