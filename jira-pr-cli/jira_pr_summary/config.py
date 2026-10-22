"""Configuration management for jira-pr-summary"""

import json
import os
import sys
from pathlib import Path
from typing import Optional


class Config:
    """Manages configuration for jira-pr-summary CLI tool"""

    def __init__(self, profile: str = None):
        self.config_dir = Path.home() / ".jira-pr-summary"
        self.config_file = self.config_dir / "config.json"
        self.cache_file = self.config_dir / "cache.json"
        self.config = self._load_config()
        self._migrate_to_profiles()  # Auto-migrate old config to profile structure
        self.active_profile = profile or self.config.get('global', {}).get('active_profile', 'default')

    def _load_config(self) -> dict:
        """Load configuration from file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _migrate_to_profiles(self) -> None:
        """Migrate old flat config to new profile structure"""
        # Check if already using profile structure
        if 'profiles' in self.config and 'global' in self.config:
            return

        # Old config exists - migrate it
        if self.config:
            old_config = self.config.copy()

            # Separate global vs profile settings
            global_settings = {
                'jira_token': old_config.get('jira_token'),
                'cache_expiry_days': old_config.get('cache_expiry_days', 90),
                'active_profile': 'default'
            }

            profile_settings = {
                'jira_base': old_config.get('jira_base', 'https://issues.redhat.com'),
                'issue_pattern': old_config.get('issue_pattern', r'\b(ACM-\d+)\b'),
                'default_repo': old_config.get('default_repo'),
                'jira_user': old_config.get('jira_user'),
                'github_user': old_config.get('github_user'),
                'jira_component': old_config.get('jira_component'),
                'use_ai': old_config.get('use_ai', False),
                'issue_filter': old_config.get('issue_filter', 'sprint'),
                'custom_statuses': old_config.get('custom_statuses')
            }

            # Create new structure
            self.config = {
                'global': global_settings,
                'profiles': {
                    'default': profile_settings
                }
            }

            self._save_config()
        else:
            # No config - initialize empty structure
            self.config = {
                'global': {
                    'active_profile': 'default'
                },
                'profiles': {}
            }

    def _save_config(self) -> None:
        """Save configuration to file"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)

    def is_configured(self) -> bool:
        """Check if initial configuration is complete"""
        global_cfg = self.config.get('global', {})
        return 'jira_token' in global_cfg and global_cfg['jira_token']

    def get_profile(self, profile_name: str = None) -> dict:
        """Get a specific profile's configuration"""
        profile_name = profile_name or self.active_profile
        return self.config.get('profiles', {}).get(profile_name, {})

    def run_first_time_setup(self) -> None:
        """Run first-time setup wizard"""
        is_reconfigure = self.is_configured()

        print("=" * 70)
        if is_reconfigure:
            print("JIRA PR SUMMARY - RECONFIGURE")
            print("=" * 70)
            print("\nPress Enter to keep current values, or enter new values to update.\n")
        else:
            print("JIRA PR SUMMARY - FIRST TIME SETUP")
            print("=" * 70)
            print("\nWelcome! Let's configure jira-pr-summary.\n")

        # Jira token setup
        print("Step 1: Jira Personal Access Token")
        print("-" * 70)
        print("You need a Jira Personal Access Token to post comments.")
        print("Get one from: https://issues.redhat.com/secure/ViewProfile.jspa")
        print("(Profile → Personal Access Tokens → Create token)\n")

        current_token = self.config.get('jira_token', '')
        if current_token:
            # Mask current token
            masked = f"{current_token[:8]}...{current_token[-4:]}" if len(current_token) > 12 else "***"
            prompt = f"Enter your Jira Personal Access Token [current: {masked}]: "
        else:
            prompt = "Enter your Jira Personal Access Token: "

        token = input(prompt).strip()
        if token:
            # Ask for token expiry date
            print("\nWhen does this token expire?")
            print("Enter expiry date (YYYY-MM-DD) or leave blank if no expiry:")
            expiry_input = input("Expiry date: ").strip()

            if 'global' not in self.config:
                self.config['global'] = {}

            self.config['global']['jira_token'] = token

            if expiry_input:
                # Validate date format
                try:
                    from datetime import datetime
                    datetime.strptime(expiry_input, '%Y-%m-%d')
                    self.config['global']['jira_token_expiry'] = expiry_input
                    print(f"✅ Token updated (expires: {expiry_input})")
                except ValueError:
                    print("⚠️  Invalid date format. Token saved without expiry date.")
                    self.config['global']['jira_token_expiry'] = None
            else:
                self.config['global']['jira_token_expiry'] = None
                print("✅ Token updated (no expiry)")
        elif current_token:
            print("✅ Keeping current token")
        else:
            print("❌ Token is required. Run 'jira-pr-summary --setup' again to retry.")
            sys.exit(1)

        # Jira base URL (default to Red Hat's Jira)
        print("\nStep 2: Jira Base URL")
        print("-" * 70)
        current_base = self.config.get('jira_base', 'https://issues.redhat.com')
        jira_base = input(f"Jira base URL [{current_base}]: ").strip()
        if jira_base:
            self.config['jira_base'] = jira_base
        else:
            self.config['jira_base'] = current_base

        # Issue pattern (default to ACM)
        print("\nStep 3: Issue Key Pattern")
        print("-" * 70)
        print("Enter the regex pattern for your Jira issue keys.")
        print("Example: For ACM-12345 issues, use: \\b(ACM-\\d+)\\b")
        print("For multiple projects like ACM or MCE: \\b(ACM|MCE)-(\\d+)\\b")
        current_pattern = self.config.get('issue_pattern', r'\b(ACM-\d+)\b')
        pattern = input(f"\nIssue pattern [{current_pattern}]: ").strip()
        if pattern:
            self.config['issue_pattern'] = pattern
        else:
            self.config['issue_pattern'] = current_pattern

        # Default repository (optional)
        print("\nStep 4: Default Repository (Optional)")
        print("-" * 70)
        print("If you usually work with one repository, you can set it as default.")
        print("Format: owner/repo (e.g., myorg/myrepo)")
        print("Leave blank to auto-detect from git config when in a repo.\n")
        current_repo = self.config.get('default_repo', 'auto-detect')
        default_repo = input(f"Default repository [{current_repo}]: ").strip()
        if default_repo:
            self.config['default_repo'] = default_repo
        elif 'default_repo' in self.config:
            # Keep existing value (don't remove it)
            pass
        # If no input and no existing value, leave it unset (auto-detect)

        # Jira username (optional but recommended)
        print("\nStep 5: Your Jira Username (Optional)")
        print("-" * 70)
        print("This filters to only show issues assigned to you.")
        print("Example: dbennett or your.email@redhat.com")
        print("Leave blank to see all issues.\n")
        current_user = self.config.get('jira_user', 'none')
        jira_user = input(f"Your Jira username [{current_user}]: ").strip()
        if jira_user:
            self.config['jira_user'] = jira_user
        elif 'jira_user' in self.config:
            # Keep existing value
            pass

        # GitHub username (optional but recommended)
        print("\nStep 6: Your GitHub Username (Optional)")
        print("-" * 70)
        print("This is your GitHub username (different from Jira username).")
        print("Used to filter PRs by author when searching for your work.")
        print("Example: dbennett (your GitHub handle)")
        print("Leave blank to see all PRs.\n")
        current_github_user = self.config.get('github_user', 'none')
        github_user = input(f"Your GitHub username [{current_github_user}]: ").strip()
        if github_user:
            self.config['github_user'] = github_user
        elif 'github_user' in self.config:
            # Keep existing value
            pass

        # Jira component (optional)
        print("\nStep 7: Default Component(s) (Optional)")
        print("-" * 70)
        print("Filter issues by component. You can specify multiple components.")
        print("Examples:")
        print("  Single: Installer")
        print("  Multiple: Installer, Observability, API")
        print("Leave blank to see all components.\n")
        current_component = self.config.get('jira_component', 'none')
        jira_component = input(f"Default component(s) [{current_component}]: ").strip()
        if jira_component:
            self.config['jira_component'] = jira_component
        elif 'jira_component' in self.config:
            # Keep existing value
            pass

        # AI-powered summaries (optional)
        print("\nStep 8: AI-Powered Summaries (Optional)")
        print("-" * 70)
        print("Use Ollama for AI-generated summaries by default.")
        print("Requires: Ollama installed and running locally")
        print("You can still override with --ai flag when running commands.\n")
        current_ai = self.config.get('use_ai', False)
        current_ai_str = 'yes' if current_ai else 'no'
        use_ai_input = input(f"Use AI by default? (yes/no) [{current_ai_str}]: ").strip().lower()
        if use_ai_input in ('yes', 'y'):
            self.config['use_ai'] = True
        elif use_ai_input in ('no', 'n'):
            self.config['use_ai'] = False
        # If empty, keep existing value (or default to False if not set)
        elif 'use_ai' not in self.config:
            self.config['use_ai'] = False

        # Cache expiration (optional)
        print("\nStep 9: Cache Expiration (Optional)")
        print("-" * 70)
        print("Automatically remove old cache entries to prevent duplicate posts.")
        print("Enter number of days to keep cache entries (0 = keep forever).")
        print("Example: 90 means cache entries older than 90 days are removed.\n")
        current_expiry = self.config.get('cache_expiry_days', 90)
        expiry_input = input(f"Cache expiry days [{current_expiry}]: ").strip()
        if expiry_input:
            try:
                expiry_days = int(expiry_input)
                if expiry_days < 0:
                    print("⚠️  Using default (90 days) - value must be >= 0")
                    self.config['cache_expiry_days'] = 90
                else:
                    self.config['cache_expiry_days'] = expiry_days
            except ValueError:
                print("⚠️  Invalid number - keeping current value")
        elif 'cache_expiry_days' not in self.config:
            self.config['cache_expiry_days'] = 90

        # Issue filter for --update mode (optional)
        print("\nStep 10: Issue Filter for --update Mode (Optional)")
        print("-" * 70)
        print("Choose which issues to show when using --update:")
        print("  1. Active sprint only - Issues in current sprint")
        print("  2. All open issues - Any issue not Done/Closed/Resolved")
        print("  3. In Progress + Review - Only issues being worked on")
        print("  4. Custom statuses - Specify your own status list")
        current_filter = self.config.get('issue_filter', 'sprint')
        filter_display = {
            'sprint': '1 (Active sprint only)',
            'open': '2 (All open issues)',
            'active': '3 (In Progress + Review)',
            'custom': '4 (Custom statuses)'
        }
        current_display = filter_display.get(current_filter, '1 (Active sprint only)')
        filter_choice = input(f"\nYour choice (1-4) [{current_display}]: ").strip()

        if filter_choice == '1':
            self.config['issue_filter'] = 'sprint'
        elif filter_choice == '2':
            self.config['issue_filter'] = 'open'
        elif filter_choice == '3':
            self.config['issue_filter'] = 'active'
        elif filter_choice == '4':
            self.config['issue_filter'] = 'custom'
            print("\nEnter custom statuses (comma-separated):")
            print("Example: In Progress, Review, Code Review")
            custom_statuses = input("Statuses: ").strip()
            if custom_statuses:
                self.config['custom_statuses'] = custom_statuses
            else:
                print("⚠️  No statuses provided - using 'In Progress, Review'")
                self.config['custom_statuses'] = 'In Progress, Review'
        elif 'issue_filter' not in self.config:
            # Default to sprint if not set
            self.config['issue_filter'] = 'sprint'

        # Save configuration
        self._save_config()

        print("\n" + "=" * 70)
        if is_reconfigure:
            print("✅ Configuration updated:", self.config_file)
        else:
            print("✅ Configuration saved to:", self.config_file)
        print("=" * 70)
        if not is_reconfigure:
            print("\nYou're all set! Run 'jira-pr-summary --help' to see usage.")
            print("\n" + "-" * 70)
            print("📝 Authored by: Disaiah Bennett")
            print("🐛 Found an issue? Report it at:")
            print("   https://github.com/stolostron/installer-dev-tools/issues")
            print("-" * 70 + "\n")
        else:
            print("\nConfiguration updated successfully!\n")

    def get(self, key: str, default=None):
        """
        Get a config value from active profile or global settings.
        Global settings: jira_token, cache_expiry_days
        Profile settings: jira_base, issue_pattern, default_repo, etc.
        """
        # Check if it's a global setting
        global_keys = ['jira_token', 'cache_expiry_days', 'active_profile']
        if key in global_keys:
            return self.config.get('global', {}).get(key, default)

        # Otherwise get from active profile
        profile = self.get_profile()
        return profile.get(key, default)

    def set(self, key: str, value) -> None:
        """Set a config value in active profile and save"""
        global_keys = ['jira_token', 'cache_expiry_days', 'active_profile']

        if key in global_keys:
            if 'global' not in self.config:
                self.config['global'] = {}
            self.config['global'][key] = value
        else:
            # Set in active profile
            if 'profiles' not in self.config:
                self.config['profiles'] = {}
            if self.active_profile not in self.config['profiles']:
                self.config['profiles'][self.active_profile] = {}
            self.config['profiles'][self.active_profile][key] = value

        self._save_config()

    def list_profiles(self) -> list:
        """List all available profiles"""
        return list(self.config.get('profiles', {}).keys())

    def create_profile(self, name: str, settings: dict) -> None:
        """Create a new profile"""
        if 'profiles' not in self.config:
            self.config['profiles'] = {}

        self.config['profiles'][name] = settings
        self._save_config()
        print(f"✅ Profile '{name}' created")

    def delete_profile(self, name: str) -> bool:
        """Delete a profile"""
        if name == 'default':
            print("❌ Cannot delete the 'default' profile")
            return False

        if name not in self.config.get('profiles', {}):
            print(f"❌ Profile '{name}' not found")
            return False

        del self.config['profiles'][name]

        # If this was the active profile, switch to default
        if self.config.get('global', {}).get('active_profile') == name:
            self.config['global']['active_profile'] = 'default'

        self._save_config()
        print(f"✅ Profile '{name}' deleted")
        return True

    def switch_profile(self, name: str) -> bool:
        """Switch to a different profile"""
        if name not in self.config.get('profiles', {}):
            print(f"❌ Profile '{name}' not found")
            return False

        if 'global' not in self.config:
            self.config['global'] = {}

        self.config['global']['active_profile'] = name
        self.active_profile = name
        self._save_config()
        print(f"✅ Switched to profile '{name}'")
        return True

    def check_token_expiry(self, warning_days: int = 14) -> None:
        """Check if Jira token is expiring soon and warn the user"""
        from datetime import datetime, timedelta

        global_cfg = self.config.get('global', {})
        expiry_str = global_cfg.get('jira_token_expiry')

        if not expiry_str:
            # No expiry date configured
            return

        try:
            expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d')
            today = datetime.now()
            days_until_expiry = (expiry_date - today).days

            if days_until_expiry < 0:
                # Token has expired
                print("=" * 70)
                print("⚠️  JIRA TOKEN EXPIRED")
                print("=" * 70)
                print(f"\nYour Jira token expired on {expiry_str}")
                print("You need to generate a new token to use this tool.")
                print("\nGet a new token from:")
                print("  https://issues.redhat.com/secure/ViewProfile.jspa")
                print("  (Profile → Personal Access Tokens → Create token)")
                print(f"\nThen run: jira-pr-summary --setup")
                print("=" * 70 + "\n")
            elif days_until_expiry <= warning_days:
                # Token expiring soon
                print("=" * 70)
                print("⚠️  JIRA TOKEN EXPIRING SOON")
                print("=" * 70)
                print(f"\nYour Jira token will expire in {days_until_expiry} day{'s' if days_until_expiry != 1 else ''} (on {expiry_str})")
                print("\nGet a new token from:")
                print("  https://issues.redhat.com/secure/ViewProfile.jspa")
                print("  (Profile → Personal Access Tokens → Create token)")
                print(f"\nThen run: jira-pr-summary --setup")
                print("=" * 70 + "\n")

        except ValueError:
            # Invalid expiry date format - ignore
            pass

    def show_config(self) -> None:
        """Display current configuration"""
        print("=" * 70)
        print("CURRENT CONFIGURATION")
        print("=" * 70)

        # Show active profile
        print(f"\nActive Profile: {self.active_profile}")
        print("-" * 70)

        # Show global settings
        global_cfg = self.config.get('global', {}).copy()
        if 'jira_token' in global_cfg and global_cfg['jira_token']:
            token = global_cfg['jira_token']
            global_cfg['jira_token'] = f"{token[:8]}...{token[-4:]}" if len(token) > 12 else "***"

        print("\nGlobal Settings:")
        print(json.dumps(global_cfg, indent=2))

        # Show active profile settings
        profile_cfg = self.get_profile()
        print(f"\nProfile '{self.active_profile}' Settings:")
        print(json.dumps(profile_cfg, indent=2))

        # Show all profiles
        profiles = self.list_profiles()
        if len(profiles) > 1:
            print(f"\nAvailable Profiles: {', '.join(profiles)}")

        print("=" * 70)
        print(f"\nConfig file: {self.config_file}")
        print(f"Cache file: {self.cache_file}\n")

    def run_profile_wizard(self, profile_name: str = None) -> None:
        """Run profile creation wizard"""
        print("=" * 70)
        print("CREATE NEW PROFILE")
        print("=" * 70)

        # Get profile name
        if not profile_name:
            existing = self.list_profiles()
            if existing:
                print(f"\nExisting profiles: {', '.join(existing)}")
            profile_name = input("\nProfile name: ").strip()

        if not profile_name:
            print("❌ Profile name is required")
            return

        if profile_name in self.list_profiles():
            choice = input(f"\n⚠️  Profile '{profile_name}' already exists. Overwrite? (y/N): ").strip().lower()
            if choice != 'y':
                print("Cancelled")
                return

        print(f"\nConfiguring profile: {profile_name}")
        print("-" * 70)

        # Get default profile settings to use as defaults
        default_profile = self.get_profile('default')

        # Jira base URL
        print("\nJira Base URL")
        current = default_profile.get('jira_base', 'https://issues.redhat.com')
        jira_base = input(f"Jira base URL [{current}]: ").strip() or current

        # Issue pattern
        print("\nIssue Key Pattern")
        print("Example: For ACM-12345 use \\b(ACM-\\d+)\\b")
        print("For multiple projects: \\b(ACM|MCE)-\\d+\\b")
        current = default_profile.get('issue_pattern', r'\b(ACM-\d+)\b')
        issue_pattern = input(f"Issue pattern [{current}]: ").strip() or current

        # Default repository
        print("\nDefault Repository (Optional)")
        print("Format: owner/repo (e.g., stolostron/backplane-operator)")
        current = default_profile.get('default_repo', 'auto-detect')
        default_repo = input(f"Default repository [{current}]: ").strip()
        if not default_repo:
            default_repo = default_profile.get('default_repo')

        # Jira username
        print("\nJira Username (Optional)")
        current = default_profile.get('jira_user', 'none')
        jira_user = input(f"Jira username [{current}]: ").strip()
        if not jira_user:
            jira_user = default_profile.get('jira_user')

        # GitHub username
        print("\nGitHub Username (Optional)")
        current = default_profile.get('github_user', 'none')
        github_user = input(f"GitHub username [{current}]: ").strip()
        if not github_user:
            github_user = default_profile.get('github_user')

        # Component
        print("\nComponent(s) (Optional)")
        current = default_profile.get('jira_component', 'none')
        jira_component = input(f"Component(s) [{current}]: ").strip()
        if not jira_component:
            jira_component = default_profile.get('jira_component')

        # Use AI
        print("\nUse AI by Default?")
        current = 'yes' if default_profile.get('use_ai', False) else 'no'
        use_ai = input(f"Use AI (yes/no) [{current}]: ").strip().lower()
        if use_ai in ('yes', 'y'):
            use_ai_val = True
        elif use_ai in ('no', 'n'):
            use_ai_val = False
        else:
            use_ai_val = default_profile.get('use_ai', False)

        # Issue filter
        print("\nIssue Filter for --update Mode")
        print("  1. Active sprint only")
        print("  2. All open issues")
        print("  3. In Progress + Review")
        print("  4. Custom statuses")
        filter_map = {'1': 'sprint', '2': 'open', '3': 'active', '4': 'custom'}
        current_filter = default_profile.get('issue_filter', 'sprint')
        filter_choice = input(f"\nChoice (1-4) [1]: ").strip() or '1'
        issue_filter = filter_map.get(filter_choice, current_filter)

        custom_statuses = None
        if issue_filter == 'custom':
            custom_statuses = input("Custom statuses (comma-separated): ").strip()
            if not custom_statuses:
                custom_statuses = default_profile.get('custom_statuses', 'In Progress, Review')

        # Create profile
        profile_settings = {
            'jira_base': jira_base,
            'issue_pattern': issue_pattern,
            'default_repo': default_repo,
            'jira_user': jira_user,
            'github_user': github_user,
            'jira_component': jira_component,
            'use_ai': use_ai_val,
            'issue_filter': issue_filter
        }

        if custom_statuses:
            profile_settings['custom_statuses'] = custom_statuses

        self.create_profile(profile_name, profile_settings)

        # Ask if they want to switch to it
        choice = input(f"\nSwitch to profile '{profile_name}' now? (Y/n): ").strip().lower()
        if choice != 'n':
            self.switch_profile(profile_name)

    def reset_config(self) -> None:
        """Delete configuration and start fresh"""
        if self.config_file.exists():
            self.config_file.unlink()
            print(f"✅ Configuration deleted: {self.config_file}")
        else:
            print(f"ℹ️  No configuration file found")

        if self.cache_file.exists():
            choice = input("\nAlso delete cache file? (y/N): ").strip().lower()
            if choice == 'y':
                self.cache_file.unlink()
                print(f"✅ Cache deleted: {self.cache_file}")
