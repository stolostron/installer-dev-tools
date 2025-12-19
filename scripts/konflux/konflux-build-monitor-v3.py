#!/usr/bin/env python3
"""
Konflux Build Monitor for ACM and MCE Operators - Enhanced Version

This script monitors the build status across ACM and MCE operator releases,
checking Konflux applications, snapshots, releases, and Quay repositories.

New Features in v3:
- Options to control scan behavior (skip image age checks, catalog-only mode)
- Retry logic to eliminate "unknown" status values
- In-progress pipeline reporting with previous run info
- Failed push pipeline detection
- Automatic retrigger capability for failed pipelines
- Last successful push job completion time tracking
- GitHub branch age checking for stale nudge branches
- Improved display of stale images
"""

import json
import sys
import subprocess
import argparse
import requests
import time
import os
import base64
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional
from dataclasses import dataclass


@dataclass
class ApplicationConfig:
    """Configuration for an application to monitor"""
    name: str
    operator: str  # 'acm' or 'mce'
    version: str
    bundle_app: str
    quay_bundle_repo: str
    quay_catalog_repo: str


class KonfluxMonitor:
    """Main monitoring class for Konflux builds"""

    def __init__(self, kubeconfig: Optional[str] = None, verbose: bool = False,
                 skip_image_age: bool = False, catalog_only: bool = False,
                 max_retries: int = 3, skip_github_check: bool = False):
        self.kubeconfig = kubeconfig
        self.verbose = verbose
        self.skip_image_age = skip_image_age
        self.catalog_only = catalog_only
        self.max_retries = max_retries
        self.skip_github_check = skip_github_check
        self.applications = self._load_application_config()
        self.quay_auth = self._setup_quay_auth()

    def _log(self, message: str):
        """Log progress message if verbose mode is enabled"""
        if self.verbose:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] {message}", file=sys.stderr)

    def _setup_quay_auth(self) -> Optional[str]:
        """Setup Quay authentication from environment variables"""
        quay_user = os.getenv("QUAY_USER")
        quay_pass = os.getenv("QUAY_PASS")

        if quay_user and quay_pass:
            credentials = f"{quay_user}:{quay_pass}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            self._log(f"Using Quay credentials for user: {quay_user}")
            return f"Basic {encoded_credentials}"
        else:
            self._log("No Quay credentials found in environment (QUAY_USER/QUAY_PASS)")
            return None

    def _load_application_config(self) -> List[ApplicationConfig]:
        """Load application configuration"""
        return [
            # ACM Applications
            ApplicationConfig("release-acm-211", "acm", "2.11", "bundle-release-acm-211",
                            "acm-d/acm-operator-bundle", "acm-d/acm-dev-catalog"),
            ApplicationConfig("release-acm-212", "acm", "2.12", "bundle-release-acm-212",
                            "acm-d/acm-operator-bundle", "acm-d/acm-dev-catalog"),
            ApplicationConfig("release-acm-213", "acm", "2.13", "bundle-release-acm-213",
                            "acm-d/acm-operator-bundle", "acm-d/acm-dev-catalog"),
            ApplicationConfig("release-acm-214", "acm", "2.14", "bundle-release-acm-214",
                            "acm-d/acm-operator-bundle", "acm-d/acm-dev-catalog"),
            ApplicationConfig("release-acm-215", "acm", "2.15", "bundle-release-acm-215",
                            "acm-d/acm-operator-bundle", "acm-d/acm-dev-catalog"),
            ApplicationConfig("release-acm-216", "acm", "2.16", "bundle-release-acm-216",
                            "acm-d/acm-operator-bundle", "acm-d/acm-dev-catalog"),

            # MCE Applications
            ApplicationConfig("release-mce-26", "mce", "2.6", "bundle-release-mce-26",
                            "acm-d/mce-operator-bundle", "acm-d/mce-dev-catalog"),
            ApplicationConfig("release-mce-27", "mce", "2.7", "bundle-release-mce-27",
                            "acm-d/mce-operator-bundle", "acm-d/mce-dev-catalog"),
            ApplicationConfig("release-mce-28", "mce", "2.8", "bundle-release-mce-28",
                            "acm-d/mce-operator-bundle", "acm-d/mce-dev-catalog"),
            ApplicationConfig("release-mce-29", "mce", "2.9", "bundle-release-mce-29",
                            "acm-d/mce-operator-bundle", "acm-d/mce-dev-catalog"),
            ApplicationConfig("release-mce-210", "mce", "2.10", "bundle-release-mce-210",
                            "acm-d/mce-operator-bundle", "acm-d/mce-dev-catalog"),
            ApplicationConfig("release-mce-211", "mce", "2.11", "bundle-release-mce-211",
                            "acm-d/mce-operator-bundle", "acm-d/mce-dev-catalog"),
        ]

    def _run_kubectl(self, command: str, timeout: int = 30, retry: bool = True) -> Dict[str, Any]:
        """Execute kubectl command and return JSON result with retry logic"""
        cmd = ["kubectl"]
        if self.kubeconfig:
            cmd.extend(["--kubeconfig", self.kubeconfig])
        cmd.extend(command.split())

        self._log(f"Running: {' '.join(cmd)}")

        attempts = self.max_retries if retry else 1
        last_error = None

        for attempt in range(attempts):
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=timeout)
                return json.loads(result.stdout) if result.stdout.strip() else {}
            except subprocess.TimeoutExpired as e:
                last_error = f"Timeout after {timeout}s"
                if attempt < attempts - 1:
                    self._log(f"Attempt {attempt + 1}/{attempts} timed out, retrying...")
                    time.sleep(2)
            except subprocess.CalledProcessError as e:
                last_error = f"kubectl error: {e.stderr}"
                if attempt < attempts - 1:
                    self._log(f"Attempt {attempt + 1}/{attempts} failed, retrying...")
                    time.sleep(2)
            except json.JSONDecodeError as e:
                last_error = f"JSON parse error: {e}"
                if attempt < attempts - 1:
                    self._log(f"Attempt {attempt + 1}/{attempts} had parse error, retrying...")
                    time.sleep(2)

        self._log(f"All attempts failed for command: {command}. Last error: {last_error}")
        return {}

    def _run_kubectl_patch(self, resource_type: str, resource_name: str, patch: Dict[str, Any]) -> bool:
        """Apply a patch to a kubernetes resource"""
        cmd = ["kubectl"]
        if self.kubeconfig:
            cmd.extend(["--kubeconfig", self.kubeconfig])

        cmd.extend([
            "patch", resource_type, resource_name,
            "--type=merge",
            "-p", json.dumps(patch)
        ])

        self._log(f"Running: {' '.join(cmd)}")

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30)
            self._log(f"Successfully patched {resource_type}/{resource_name}")
            return True
        except subprocess.CalledProcessError as e:
            self._log(f"Error patching {resource_type}/{resource_name}: {e.stderr}")
            return False
        except subprocess.TimeoutExpired:
            self._log(f"Timeout patching {resource_type}/{resource_name}")
            return False

    def get_application_components(self, app_name: str) -> List[Dict[str, Any]]:
        """Get components for an application by filtering on .spec.application field"""
        result = self._run_kubectl(f"get components -o json")
        all_components = result.get("items", [])

        app_components = [
            comp for comp in all_components
            if comp.get("spec", {}).get("application", "") == app_name
        ]

        self._log(f"Found {len(app_components)} components for application {app_name}")
        return app_components

    def analyze_component_status(self, component: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze component status based on lastPromotedImage age"""
        comp_name = component.get("metadata", {}).get("name", "unknown")
        status = component.get("status", {})
        last_promoted_image = status.get("lastPromotedImage", "")

        result = {
            "name": comp_name,
            "status": "unknown",
            "last_promoted_image": last_promoted_image,
            "image_age_status": "unknown" if not self.skip_image_age else "skipped",
            "last_successful_push": None
        }

        # Get last successful push pipeline info
        last_push = self.get_component_last_successful_push(comp_name)
        if last_push:
            result["last_successful_push"] = last_push

        if not last_promoted_image:
            result["status"] = "no_image"
            result["image_age_status"] = "missing"
            return result

        # Skip image age check if option is set
        if self.skip_image_age:
            result["status"] = "ready"
            result["image_age_status"] = "skipped"
            return result

        # Check image age by querying the container registry
        try:
            image_age_status = self._check_image_age(last_promoted_image, comp_name)
            result["image_age_status"] = image_age_status

            if image_age_status == "recent":
                result["status"] = "ready"
            elif image_age_status == "stale":
                result["status"] = "stale"
            else:
                result["status"] = "unknown"

        except Exception as e:
            self._log(f"Error checking image age for component {comp_name}: {e}")
            result["status"] = "error"
            result["image_age_status"] = "error"

        return result

    def _check_image_age(self, image_url: str, comp_name: str) -> str:
        """Check if an image is less than 2 weeks old using skopeo with retry"""
        for attempt in range(self.max_retries):
            try:
                result = self._check_image_age_with_skopeo(image_url, comp_name)
                if result != "unknown":
                    return result
                if attempt < self.max_retries - 1:
                    self._log(f"Image age check returned unknown, retrying... ({attempt + 1}/{self.max_retries})")
                    time.sleep(2)
            except Exception as e:
                if attempt < self.max_retries - 1:
                    self._log(f"Error checking image age, retrying... ({attempt + 1}/{self.max_retries}): {e}")
                    time.sleep(2)
                else:
                    raise

        return "unknown"

    def _check_image_age_with_skopeo(self, image_url: str, comp_name: str) -> str:
        """Check age of a container image using skopeo inspect command"""
        try:
            self._log(f"Inspecting image age with skopeo: {image_url}")

            cmd = ["skopeo", "inspect", f"docker://{image_url}"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                self._log(f"Skopeo inspect failed for {comp_name}: {result.stderr}")
                return "unknown"

            image_data = json.loads(result.stdout)
            created = image_data.get("Created", "")

            if created:
                try:
                    if created.endswith("Z"):
                        created_time = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    elif "+" in created or created.count("-") > 2:
                        created_time = datetime.fromisoformat(created)
                    else:
                        created_time = datetime.strptime(created, "%Y-%m-%dT%H:%M:%S")
                        created_time = created_time.replace(tzinfo=datetime.now().astimezone().tzinfo)
                except ValueError as e:
                    self._log(f"Error parsing timestamp '{created}' for {comp_name}: {e}")
                    return "unknown"

                now = datetime.now(created_time.tzinfo) if created_time.tzinfo else datetime.now()
                age = now - created_time

                if age.days <= 14:
                    self._log(f"Image {comp_name} is {age.days} days old - recent")
                    return "recent"
                else:
                    self._log(f"Image {comp_name} is {age.days} days old - stale")
                    return "stale"
            else:
                self._log(f"No creation timestamp found for {comp_name}")
                return "unknown"

        except subprocess.TimeoutExpired:
            self._log(f"Timeout inspecting image for {comp_name}")
            return "error"
        except json.JSONDecodeError as e:
            self._log(f"Error parsing skopeo output for {comp_name}: {e}")
            return "error"
        except Exception as e:
            self._log(f"Error checking image age for {comp_name}: {e}")
            return "error"

    def check_catalog_with_skopeo(self, image_repo: str, version: str) -> Dict[str, Any]:
        """Check catalog image for DOWNSTREAM tags using skopeo inspect with retry"""
        for attempt in range(self.max_retries):
            try:
                image_url = f"{image_repo}:latest-{version}"
                self._log(f"Inspecting catalog image: {image_url}")

                cmd = ["skopeo", "inspect", f"docker://{image_url}"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

                if result.returncode != 0:
                    if attempt < self.max_retries - 1:
                        self._log(f"Skopeo inspect failed, retrying... ({attempt + 1}/{self.max_retries})")
                        time.sleep(2)
                        continue
                    return {
                        "has_downstream": False,
                        "downstream_tags": [],
                        "error": f"Failed to inspect image: {result.stderr}"
                    }

                image_data = json.loads(result.stdout)
                labels = image_data.get("Labels", {})
                additional_tags = labels.get("konflux.additional-tags", "")
                downstream_tags = []

                if additional_tags:
                    tag_list = [tag.strip() for tag in additional_tags.split(",") if tag.strip()]
                    downstream_tags = [
                        tag for tag in tag_list
                        if tag.startswith(version) and "DOWNSTREAM" in tag
                    ]

                    self._log(f"Found {len(downstream_tags)} DOWNSTREAM tags for version {version} in {image_repo}")
                    for tag in downstream_tags:
                        self._log(f"  DOWNSTREAM tag: {tag}")
                else:
                    self._log(f"No konflux.additional-tags found in {image_url}")

                return {
                    "has_downstream": len(downstream_tags) > 0,
                    "downstream_tags": downstream_tags,
                    "newest_tag": {"name": downstream_tags[0]} if downstream_tags else None,
                    "all_additional_tags": tag_list if additional_tags else []
                }

            except subprocess.TimeoutExpired:
                if attempt < self.max_retries - 1:
                    self._log(f"Timeout, retrying... ({attempt + 1}/{self.max_retries})")
                    time.sleep(2)
                    continue
                return {"has_downstream": False, "downstream_tags": [], "error": "Timeout"}
            except json.JSONDecodeError as e:
                if attempt < self.max_retries - 1:
                    self._log(f"JSON parse error, retrying... ({attempt + 1}/{self.max_retries})")
                    time.sleep(2)
                    continue
                return {"has_downstream": False, "downstream_tags": [], "error": f"JSON parse error: {e}"}
            except Exception as e:
                if attempt < self.max_retries - 1:
                    self._log(f"Error, retrying... ({attempt + 1}/{self.max_retries}): {e}")
                    time.sleep(2)
                    continue
                return {"has_downstream": False, "downstream_tags": [], "error": str(e)}

        return {"has_downstream": False, "downstream_tags": [], "error": "Max retries exceeded"}

    def get_releases_by_release_plan(self, app_name: str, pipeline_type: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Get releases for a specific release plan pattern

        Filters releases by:
        1. Release name starts with app_name (e.g., release-mce-210)
        2. spec.releasePlan contains pipeline_type-publish pattern (e.g., dev-publish or stage-publish)
        """
        app_short = app_name.replace('release-', '')
        release_plan_pattern = f"{pipeline_type}-publish-{app_short}"

        self._log(f"Getting {pipeline_type} releases for {app_name}")
        self._log(f"  Filtering by: release name starts with '{app_name}' AND releasePlan contains '{pipeline_type}-publish'")

        result = self._run_kubectl(f"get releases -o json", timeout=60)
        items = result.get("items", [])

        matching_releases = []
        for release in items:
            release_name = release.get("metadata", {}).get("name", "")
            release_plan = release.get("spec", {}).get("releasePlan", "")

            # Filter by release name starting with app_name AND releasePlan containing the pipeline type
            if release_name.startswith(app_name) and f"{pipeline_type}-publish" in release_plan:
                matching_releases.append(release)
                self._log(f"    Matched: {release_name} (plan: {release_plan})")

        if matching_releases:
            matching_releases.sort(key=lambda x: x.get("metadata", {}).get("creationTimestamp", ""), reverse=True)
            matching_releases = matching_releases[:limit]

        self._log(f"  Found {len(matching_releases)} {pipeline_type} releases for {app_name}")
        if matching_releases and len(matching_releases) > 0:
            self._log(f"  Most recent: {matching_releases[0].get('metadata', {}).get('name', '')}")

        return matching_releases

    def analyze_release_status(self, release_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze status from a single release

        For dev-publish releases: uses TenantPipelineProcessed condition
        For stage-publish releases: uses ManagedPipelineProcessed condition
        """
        release_name = release_data.get("metadata", {}).get("name", "unknown")
        release_plan = release_data.get("spec", {}).get("releasePlan", "")
        status = release_data.get("status", {})
        conditions = status.get("conditions", [])

        self._log(f"    Analyzing release: {release_name} (plan: {release_plan})")
        self._log(f"    Found {len(conditions)} conditions")

        result = {
            "status": "unknown",
            "is_progressing": False,
            "processing_resources": [],
        }

        # Determine which pipeline condition to check based on release plan
        # dev-publish releases: check TenantPipelineProcessed
        # stage-publish releases: check ManagedPipelineProcessed
        target_condition_type = None
        if "dev-publish" in release_plan:
            target_condition_type = "TenantPipelineProcessed"
        elif "stage-publish" in release_plan:
            target_condition_type = "ManagedPipelineProcessed"
        else:
            self._log(f"    WARNING: Cannot determine pipeline type from release plan: {release_plan}")

        # Find and analyze the target condition
        found_target_condition = False
        for condition in conditions:
            condition_type = condition.get("type", "")
            condition_status = condition.get("status", "")
            condition_reason = condition.get("reason", "")
            condition_message = condition.get("message", "")

            self._log(f"      Condition type: {condition_type}, status: {condition_status}, reason: {condition_reason}")

            # Check if this is our target condition
            if target_condition_type and target_condition_type in condition_type:
                found_target_condition = True

                if "Progressing" in condition_reason:
                    result["is_progressing"] = True
                    result["status"] = "progressing"
                    result["progress_message"] = condition_message
                else:
                    result["status"] = "success" if condition_status == "True" else "failed"
                    if condition_status != "True":
                        result["failure_reason"] = condition_message

                self._log(f"    Found {target_condition_type}: status={result['status']}")
                break

        # Get processing resources if progressing
        if result["is_progressing"]:
            processing_resources = status.get("processing", {}).get("pipelineRuns", [])
            result["processing_resources"] = processing_resources

        # Report if we didn't find the expected condition
        if not found_target_condition:
            if target_condition_type:
                result["status"] = "unknown"
                result["failure_reason"] = f"Condition {target_condition_type} not found in release"
                self._log(f"    WARNING: {target_condition_type} not found in release {release_name}")
            else:
                result["status"] = "unknown"
                result["failure_reason"] = f"Cannot determine pipeline type from release plan: {release_plan}"

            if conditions:
                self._log(f"    Available condition types: {[c.get('type', '') for c in conditions]}")
        else:
            self._log(f"    Final status for {release_name}: {result['status']}")

        return result

    def get_component_failed_pipelines(self, app_name: str) -> List[Dict[str, Any]]:
        """Get components with failed most recent push pipeline builds"""
        components = self.get_application_components(app_name)
        failed_components = []

        for comp in components:
            comp_name = comp.get("metadata", {}).get("name", "")
            self._log(f"Checking recent pipeline runs for component: {comp_name}")

            # Get recent pipeline runs for this component (push event type only)
            result = self._run_kubectl(
                f"get pipelineruns -l appstudio.openshift.io/component={comp_name} "
                f"-l pipelineruns.openshift.io/type=build "
                f"-l pac.test.appstudio.openshift.io/event-type=push "
                f"--sort-by=.metadata.creationTimestamp -o json"
            )

            pipeline_runs = result.get("items", [])
            if pipeline_runs:
                # Get the most recent one
                latest_run = pipeline_runs[-1]
                status = latest_run.get("status", {})
                conditions = status.get("conditions", [])

                # Check if it failed
                for condition in conditions:
                    if condition.get("type") == "Succeeded":
                        if condition.get("status") == "False":
                            failed_components.append({
                                "component_name": comp_name,
                                "component": comp,
                                "pipeline_run": latest_run,
                                "failure_reason": condition.get("message", "Unknown"),
                            })
                            self._log(f"Component {comp_name} has failed most recent push pipeline")
                        break

        return failed_components

    def get_component_last_successful_push(self, comp_name: str) -> Optional[Dict[str, Any]]:
        """Get the last successful push pipeline run for a component"""
        self._log(f"Getting last successful push pipeline for component: {comp_name}")

        # Get recent pipeline runs for this component (push event type only)
        result = self._run_kubectl(
            f"get pipelineruns -l appstudio.openshift.io/component={comp_name} "
            f"-l pipelineruns.openshift.io/type=build "
            f"-l pac.test.appstudio.openshift.io/event-type=push "
            f"--sort-by=.metadata.creationTimestamp -o json",
            timeout=30
        )

        pipeline_runs = result.get("items", [])
        if not pipeline_runs:
            self._log(f"No push pipeline runs found for {comp_name}")
            return None

        # Search from most recent to oldest for a successful run
        for run in reversed(pipeline_runs):
            status = run.get("status", {})
            conditions = status.get("conditions", [])

            for condition in conditions:
                if condition.get("type") == "Succeeded" and condition.get("status") == "True":
                    completion_time = status.get("completionTime", "")
                    creation_time = run.get("metadata", {}).get("creationTimestamp", "")
                    run_name = run.get("metadata", {}).get("name", "")

                    self._log(f"Found successful push pipeline for {comp_name}: {run_name} completed at {completion_time}")

                    return {
                        "pipeline_run_name": run_name,
                        "completion_time": completion_time,
                        "creation_time": creation_time,
                    }

        self._log(f"No successful push pipeline runs found for {comp_name}")
        return None

    def retrigger_component_build(self, component: Dict[str, Any]) -> bool:
        """Retrigger a component build by setting the rebuild annotation"""
        comp_name = component.get("metadata", {}).get("name", "")
        self._log(f"Retriggering build for component: {comp_name}")

        patch = {
            "metadata": {
                "annotations": {
                    "build.appstudio.openshift.io/request": "trigger-pac-build"
                }
            }
        }

        return self._run_kubectl_patch("component", comp_name, patch)

    def check_github_branches(self, repo_owner: str = "stolostron", repo_name: str = "acm-mce-operator-catalogs") -> List[Dict[str, Any]]:
        """Check GitHub repository for old nudge branches"""
        self._log(f"Checking GitHub repository {repo_owner}/{repo_name} for old nudge branches")

        # Pattern: konflux/component-updates/*-dev-catalog-component-update-*-operator-bundle-*
        branch_pattern = re.compile(r"^konflux/component-updates/.*-dev-catalog-component-update-.*-operator-bundle-.*$")

        github_token = os.getenv("GITHUB_TOKEN")
        headers = {"Accept": "application/vnd.github.v3+json"}
        if github_token:
            headers["Authorization"] = f"token {github_token}"
            self._log("Using GitHub token for authentication")
        else:
            self._log("No GitHub token found (GITHUB_TOKEN env var), using unauthenticated requests")

        try:
            # Get all branches from GitHub API
            url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/branches"
            response = requests.get(url, headers=headers, timeout=30)

            if response.status_code != 200:
                self._log(f"GitHub API returned status {response.status_code}: {response.text}")
                return []

            branches = response.json()
            old_branches = []

            # Filter branches matching the pattern
            for branch in branches:
                branch_name = branch.get("name", "")
                if branch_pattern.match(branch_name):
                    # Get detailed branch info to check commit date
                    branch_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/branches/{branch_name}"
                    branch_response = requests.get(branch_url, headers=headers, timeout=30)

                    if branch_response.status_code == 200:
                        branch_data = branch_response.json()
                        commit_data = branch_data.get("commit", {})
                        commit_info = commit_data.get("commit", {})
                        committer_info = commit_info.get("committer", {})
                        commit_date_str = committer_info.get("date", "")

                        if commit_date_str:
                            # Parse the commit date
                            commit_date = datetime.fromisoformat(commit_date_str.replace("Z", "+00:00"))
                            now = datetime.now(timezone.utc)
                            age = now - commit_date

                            self._log(f"Branch {branch_name} is {age.total_seconds() / 3600:.1f} hours old")

                            # Check if older than 2 hours
                            if age > timedelta(hours=2):
                                old_branches.append({
                                    "name": branch_name,
                                    "commit_date": commit_date_str,
                                    "age_hours": age.total_seconds() / 3600,
                                    "sha": commit_data.get("sha", "")
                                })
                        else:
                            self._log(f"No commit date found for branch {branch_name}")
                    else:
                        self._log(f"Failed to get details for branch {branch_name}: {branch_response.status_code}")

            self._log(f"Found {len(old_branches)} old nudge branches (> 2 hours)")
            return old_branches

        except requests.RequestException as e:
            self._log(f"Error querying GitHub API: {e}")
            return []
        except Exception as e:
            self._log(f"Unexpected error checking GitHub branches: {e}")
            return []

    def check_quay_repository(self, repo: str, version_prefix: str = None, dev_release_time: str = None, check_downstream: bool = False) -> Dict[str, Any]:
        """Check Quay repository status with retry logic"""
        for attempt in range(self.max_retries):
            try:
                result = self._check_quay_repository_once(repo, version_prefix, dev_release_time, check_downstream)
                if result.get("status") == "accessible" or attempt == self.max_retries - 1:
                    return result

                self._log(f"Quay check failed, retrying... ({attempt + 1}/{self.max_retries})")
                time.sleep(2)

            except Exception as e:
                if attempt == self.max_retries - 1:
                    return {"status": "error", "message": str(e)}
                self._log(f"Quay check error, retrying... ({attempt + 1}/{self.max_retries}): {e}")
                time.sleep(2)

        return {"status": "error", "message": "Max retries exceeded"}

    def _check_quay_repository_once(self, repo: str, version_prefix: str = None, dev_release_time: str = None, check_downstream: bool = False) -> Dict[str, Any]:
        """Single attempt to check Quay repository status"""
        self._log(f"Checking Quay repository: {repo}")
        url = f"https://quay.io/api/v1/repository/{repo}/tag/"
        headers = {"Accept": "application/json"}

        if self.quay_auth:
            headers["Authorization"] = self.quay_auth

        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            tags = data.get("tags", [])

            recent_tags = sorted(tags, key=lambda x: x.get("last_modified", ""), reverse=True)[:10]

            if check_downstream:
                downstream_tags = []
                newest_downstream_tag = None

                if version_prefix:
                    downstream_tags = [
                        tag for tag in tags
                        if (tag.get("name", "").startswith(version_prefix) and
                            "DOWNSTREAM" in tag.get("name", ""))
                    ]
                    if downstream_tags:
                        downstream_tags.sort(key=lambda x: x.get("last_modified", ""), reverse=True)
                        newest_downstream_tag = downstream_tags[0]

                    self._log(f"Found {len(downstream_tags)} DOWNSTREAM tags matching version {version_prefix} in {repo}")

                return {
                    "status": "accessible",
                    "recent_tags": recent_tags[:5],
                    "downstream_tags": downstream_tags[:3],
                    "has_downstream_tag": len(downstream_tags) > 0,
                    "newest_downstream_tag": newest_downstream_tag,
                    "total_tags": len(tags)
                }
            else:
                version_tags = []
                newer_than_release = False
                newest_version_tag = None

                if version_prefix:
                    version_tags = [
                        tag for tag in tags
                        if tag.get("name", "").startswith(version_prefix)
                    ]
                    if version_tags:
                        version_tags.sort(key=lambda x: x.get("last_modified", ""), reverse=True)
                        newest_version_tag = version_tags[0]

                    if dev_release_time and newest_version_tag:
                        tag_time = newest_version_tag.get("last_modified", "")
                        if tag_time and tag_time > dev_release_time:
                            newer_than_release = True
                            self._log(f"Found version tag newer than dev release: {newest_version_tag.get('name', '')} ({tag_time})")
                        else:
                            self._log(f"Version tags exist but none newer than dev release ({dev_release_time})")
                    elif newest_version_tag:
                        newer_than_release = True

                    self._log(f"Found {len(version_tags)} tags matching version {version_prefix} in {repo}")

                return {
                    "status": "accessible",
                    "recent_tags": recent_tags[:5],
                    "version_tags": version_tags[:3],
                    "has_recent_version_tag": newer_than_release,
                    "newest_version_tag": newest_version_tag,
                    "total_tags": len(tags)
                }

            self._log(f"Quay repo {repo} accessible with {len(tags)} total tags")
        else:
            self._log(f"Quay repo {repo} returned status {response.status_code}")
            return {"status": "error", "code": response.status_code}

    def generate_catalog_report(self) -> Dict[str, Any]:
        """Generate catalog-only report"""
        report = {
            "timestamp": datetime.now().isoformat(),
            "catalogs": {},
            "mode": "catalog_only"
        }

        self._log("Checking catalog applications (catalog-only mode)")

        acm_versions = set()
        mce_versions = set()

        for app_config in self.applications:
            if app_config.operator == "acm":
                acm_versions.add(app_config.version)
            elif app_config.operator == "mce":
                mce_versions.add(app_config.version)

        # Check ACM catalog
        acm_catalog_status = {"status": "unknown", "downstream_tags": {}}
        if acm_versions:
            for version in acm_versions:
                skopeo_result = self.check_catalog_with_skopeo(
                    "quay.io/acm-d/acm-dev-catalog",
                    version
                )
                acm_catalog_status["downstream_tags"][version] = skopeo_result

            has_any_downstream = any(
                info["has_downstream"] for info in acm_catalog_status["downstream_tags"].values()
            )
            acm_catalog_status["status"] = "has_downstream" if has_any_downstream else "no_downstream"

        # Check MCE catalog
        mce_catalog_status = {"status": "unknown", "downstream_tags": {}}
        if mce_versions:
            for version in mce_versions:
                skopeo_result = self.check_catalog_with_skopeo(
                    "quay.io/acm-d/mce-dev-catalog",
                    version
                )
                mce_catalog_status["downstream_tags"][version] = skopeo_result

            has_any_downstream = any(
                info["has_downstream"] for info in mce_catalog_status["downstream_tags"].values()
            )
            mce_catalog_status["status"] = "has_downstream" if has_any_downstream else "no_downstream"

        report["catalogs"]["catalog-dev-acm"] = acm_catalog_status
        report["catalogs"]["catalog-dev-mce"] = mce_catalog_status

        return report

    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive build status report"""
        # If catalog-only mode, use specialized report
        if self.catalog_only:
            return self.generate_catalog_report()

        report = {
            "timestamp": datetime.now().isoformat(),
            "applications": {},
            "catalogs": {},
            "github_branches": {"old_nudge_branches": []},
            "summary": {"total_apps": 0, "healthy_apps": 0, "failed_apps": 0},
            "scan_options": {
                "skip_image_age": self.skip_image_age,
                "catalog_only": self.catalog_only,
                "max_retries": self.max_retries,
                "skip_github_check": self.skip_github_check
            }
        }

        # Check for old GitHub branches unless skipped
        if not self.skip_github_check:
            self._log("Checking GitHub for old nudge branches")
            old_branches = self.check_github_branches()
            report["github_branches"]["old_nudge_branches"] = old_branches
        else:
            self._log("Skipping GitHub branch check")

        # Check catalog applications
        self._log("Checking catalog applications")

        acm_versions = set()
        mce_versions = set()

        for app_config in self.applications:
            if app_config.operator == "acm":
                acm_versions.add(app_config.version)
            elif app_config.operator == "mce":
                mce_versions.add(app_config.version)

        # Check ACM catalog
        acm_catalog_status = {"status": "unknown", "downstream_tags": {}}
        if acm_versions:
            for version in acm_versions:
                skopeo_result = self.check_catalog_with_skopeo(
                    "quay.io/acm-d/acm-dev-catalog",
                    version
                )
                acm_catalog_status["downstream_tags"][version] = skopeo_result

            has_any_downstream = any(
                info["has_downstream"] for info in acm_catalog_status["downstream_tags"].values()
            )
            acm_catalog_status["status"] = "has_downstream" if has_any_downstream else "no_downstream"

        # Check MCE catalog
        mce_catalog_status = {"status": "unknown", "downstream_tags": {}}
        if mce_versions:
            for version in mce_versions:
                skopeo_result = self.check_catalog_with_skopeo(
                    "quay.io/acm-d/mce-dev-catalog",
                    version
                )
                mce_catalog_status["downstream_tags"][version] = skopeo_result

            has_any_downstream = any(
                info["has_downstream"] for info in mce_catalog_status["downstream_tags"].values()
            )
            mce_catalog_status["status"] = "has_downstream" if has_any_downstream else "no_downstream"

        report["catalogs"]["catalog-dev-acm"] = acm_catalog_status
        report["catalogs"]["catalog-dev-mce"] = mce_catalog_status

        # Check main applications
        self._log(f"Checking {len(self.applications)} main applications")
        for i, app_config in enumerate(self.applications):
            app_name = app_config.name
            self._log(f"Processing application {i+1}/{len(self.applications)}: {app_name}")
            report["applications"][app_name] = self._analyze_application(app_config)
            report["summary"]["total_apps"] += 1

            app_health = report["applications"][app_name].get("overall_status", "failed")
            if app_health == "healthy":
                report["summary"]["healthy_apps"] += 1
            else:
                report["summary"]["failed_apps"] += 1

            self._log(f"Completed {app_name}: {app_health}")

        return report

    def _analyze_application(self, app_config: ApplicationConfig) -> Dict[str, Any]:
        """Analyze a single application and its associated resources"""
        analysis = {
            "operator": app_config.operator,
            "version": app_config.version,
            "components": [],
            "pipeline_status": {
                "development": {
                    "current": "unknown",
                    "previous": None,
                    "is_progressing": False
                },
                "stage": {
                    "current": "unknown",
                    "previous": None,
                    "is_progressing": False
                },
            },
            "quay_status": {},
            "overall_status": "unknown"
        }

        # Get components and analyze their status
        self._log(f"  Getting components for {app_config.name}")
        components = self.get_application_components(app_config.name)
        analysis["components"] = [
            self.analyze_component_status(comp)
            for comp in components
        ]
        self._log(f"  Found {len(analysis['components'])} components")

        # Get development pipeline status from dev-publish releases
        self._log(f"  Checking development pipeline for {app_config.name}")
        dev_releases = self.get_releases_by_release_plan(app_config.name, "dev", 3)
        dev_release_time = None

        if not dev_releases:
            self._log(f"  WARNING: No development releases found for {app_config.name}")

        if dev_releases:
            latest_dev = self.analyze_release_status(dev_releases[0])
            analysis["pipeline_status"]["development"]["current"] = latest_dev["status"]
            analysis["pipeline_status"]["development"]["is_progressing"] = latest_dev.get("is_progressing", False)

            if latest_dev.get("is_progressing") and len(dev_releases) > 1:
                # Get previous run status
                prev_dev = self.analyze_release_status(dev_releases[1])
                analysis["pipeline_status"]["development"]["previous"] = {
                    "status": prev_dev["status"],
                    "timestamp": dev_releases[1].get("metadata", {}).get("creationTimestamp", "")
                }

            if latest_dev["status"] == "success":
                dev_release = dev_releases[0]
                dev_release_time = dev_release.get("metadata", {}).get("creationTimestamp", "")
                status = dev_release.get("status", {})
                completion_time = status.get("completionTime", "")
                if completion_time:
                    dev_release_time = completion_time

        # Get stage pipeline status from stage-publish releases
        self._log(f"  Checking stage pipeline for {app_config.name}")
        stage_releases = self.get_releases_by_release_plan(app_config.name, "stage", 3)

        if not stage_releases:
            self._log(f"  WARNING: No stage releases found for {app_config.name}")

        if stage_releases:
            latest_stage = self.analyze_release_status(stage_releases[0])
            analysis["pipeline_status"]["stage"]["current"] = latest_stage["status"]
            analysis["pipeline_status"]["stage"]["is_progressing"] = latest_stage.get("is_progressing", False)

            if latest_stage.get("is_progressing") and len(stage_releases) > 1:
                # Get previous run status
                prev_stage = self.analyze_release_status(stage_releases[1])
                analysis["pipeline_status"]["stage"]["previous"] = {
                    "status": prev_stage["status"],
                    "timestamp": stage_releases[1].get("metadata", {}).get("creationTimestamp", "")
                }

        # Check Quay repositories
        self._log(f"  Checking Quay repositories for {app_config.name}")
        analysis["quay_status"]["bundle"] = self.check_quay_repository(
            app_config.quay_bundle_repo,
            app_config.version,
            dev_release_time
        )
        analysis["quay_status"]["catalog"] = self.check_quay_repository(app_config.quay_catalog_repo)

        # Determine overall health
        analysis["overall_status"] = self._determine_overall_health(analysis)

        return analysis

    def _determine_overall_health(self, analysis: Dict[str, Any]) -> str:
        """Determine overall health status of an application"""
        quay_bundle_ok = (analysis["quay_status"]["bundle"]["status"] == "accessible" and
                         analysis["quay_status"]["bundle"].get("has_recent_version_tag", False))

        dev_status = analysis["pipeline_status"]["development"]["current"]
        stage_status = analysis["pipeline_status"]["stage"]["current"]

        dev_ok = dev_status == "success"
        stage_ok = stage_status == "success"

        # Components are OK if they have promoted images (and optionally recent ones)
        if self.skip_image_age:
            components_ok = len(analysis["components"]) > 0 and all(
                comp["status"] in ["ready", "skipped"]
                for comp in analysis["components"]
            )
        else:
            components_ok = len(analysis["components"]) > 0 and all(
                comp["status"] == "ready" and comp["image_age_status"] == "recent"
                for comp in analysis["components"]
            )

        if quay_bundle_ok and dev_ok and stage_ok and components_ok:
            return "healthy"
        elif dev_ok and components_ok:
            return "partial"
        else:
            return "failed"


def print_human_readable_report(report: Dict[str, Any]):
    """Print a human-readable version of the report"""
    print("=" * 80)
    print("KONFLUX BUILD STATUS REPORT")
    if report.get("mode") == "catalog_only":
        print("(CATALOG ONLY MODE)")
    print("=" * 80)
    print(f"Generated: {report['timestamp']}")

    # Show scan options if present
    if "scan_options" in report:
        opts = report["scan_options"]
        print(f"Scan options: skip_image_age={opts['skip_image_age']}, max_retries={opts['max_retries']}")

    if "summary" in report:
        print(f"Summary: {report['summary']['healthy_apps']}/{report['summary']['total_apps']} applications healthy")
    print()

    # Print GitHub branch warnings
    github_data = report.get("github_branches", {})
    old_branches = github_data.get("old_nudge_branches", [])
    if old_branches:
        print("⚠️  OLD NUDGE BRANCHES (> 2 hours):")
        print("-" * 40)
        for branch in old_branches:
            age_hours = branch.get("age_hours", 0)
            branch_name = branch.get("name", "unknown")
            print(f"  ✗ {branch_name}")
            print(f"    Age: {age_hours:.1f} hours")
        print()
        print("These branches should be deleted automatically unless a build failure occurred.")
        print()

    # Print catalog status
    print("CATALOG STATUS:")
    print("-" * 40)
    for catalog, status_info in report["catalogs"].items():
        operator = "ACM" if "acm" in catalog else "MCE"
        main_status = status_info.get("status", "unknown")

        if main_status == "has_downstream":
            print(f"  {operator} Catalog: ✓ DOWNSTREAM tags available")
        elif main_status == "no_downstream":
            print(f"  {operator} Catalog: ✗ No DOWNSTREAM tags found")
        else:
            print(f"  {operator} Catalog: ? {main_status}")

        downstream_tags = status_info.get("downstream_tags", {})
        sorted_versions = sorted(downstream_tags.keys(), key=lambda v: tuple(map(int, v.split('.'))))

        for version in sorted_versions:
            version_info = downstream_tags[version]
            has_downstream = version_info.get("has_downstream", False)
            error = version_info.get("error")
            downstream_tag_list = version_info.get("downstream_tags", [])

            if error:
                print(f"    v{version}: Error - {error}")
            elif has_downstream and downstream_tag_list:
                tag_name = downstream_tag_list[0]
                print(f"    v{version}: {tag_name}")
            elif has_downstream:
                print(f"    v{version}: DOWNSTREAM tag exists")
            else:
                print(f"    v{version}: No DOWNSTREAM tag")
    print()

    # If catalog-only mode, stop here
    if report.get("mode") == "catalog_only":
        return

    # Group by operator
    acm_apps = {k: v for k, v in report["applications"].items() if v["operator"] == "acm"}
    mce_apps = {k: v for k, v in report["applications"].items() if v["operator"] == "mce"}

    for operator, apps in [("ACM", acm_apps), ("MCE", mce_apps)]:
        print(f"{operator} OPERATOR RELEASES:")
        print("-" * 40)

        for app_name, analysis in apps.items():
            status_icon = {"healthy": "✓", "partial": "~", "failed": "✗"}.get(analysis["overall_status"], "?")
            version = analysis["version"]

            print(f"  {status_icon} {version}: {analysis['overall_status'].upper()}")

            # Show component count
            comp_count = len(analysis["components"])
            skip_age = report.get("scan_options", {}).get("skip_image_age", False)

            if skip_age:
                healthy_comps = len([c for c in analysis["components"] if c["status"] in ["ready", "skipped"]])
                print(f"    Components: {healthy_comps}/{comp_count} ready (age check skipped)")
            else:
                healthy_comps = len([c for c in analysis["components"]
                                   if c["status"] == "ready" and c["image_age_status"] == "recent"])
                stale_comps = [c for c in analysis["components"] if c["image_age_status"] == "stale"]
                missing_comps = [c for c in analysis["components"] if c["status"] == "no_image"]
                error_comps = [c for c in analysis["components"] if c["status"] == "error"]
                unknown_comps = [c for c in analysis["components"] if c["status"] == "unknown" or c["image_age_status"] == "unknown"]

                print(f"    Components: {healthy_comps}/{comp_count} with recent images")

                # Show stale components if any exist
                if stale_comps:
                    print(f"    ⚠️  Stale components (> 2 weeks old):")
                    for comp in stale_comps:
                        comp_name = comp["name"]
                        last_push = comp.get("last_successful_push")
                        if last_push and last_push.get("completion_time"):
                            push_time = last_push["completion_time"]
                            # Format the timestamp for display
                            try:
                                push_dt = datetime.fromisoformat(push_time.replace("Z", "+00:00"))
                                push_display = push_dt.strftime("%Y-%m-%d %H:%M UTC")
                            except:
                                push_display = push_time
                            print(f"      - {comp_name} (last successful push: {push_display})")
                        else:
                            print(f"      - {comp_name} (no successful push found)")

                # Show components with missing images
                if missing_comps:
                    print(f"    ⚠️  Components with no promoted image:")
                    for comp in missing_comps:
                        comp_name = comp["name"]
                        print(f"      - {comp_name}")

                # Show components with errors checking image age
                if error_comps:
                    print(f"    ⚠️  Components with image age check errors:")
                    for comp in error_comps:
                        comp_name = comp["name"]
                        last_image = comp.get("last_promoted_image", "none")
                        print(f"      - {comp_name} (image: {last_image})")

                # Show components with unknown status
                if unknown_comps:
                    print(f"    ⚠️  Components with unknown status:")
                    for comp in unknown_comps:
                        comp_name = comp["name"]
                        comp_status = comp.get("status", "unknown")
                        image_age_status = comp.get("image_age_status", "unknown")
                        last_image = comp.get("last_promoted_image", "none")
                        print(f"      - {comp_name} (status: {comp_status}, image_age: {image_age_status}, image: {last_image})")

            # Show pipeline status with progress info
            dev_info = analysis["pipeline_status"]["development"]
            stage_info = analysis["pipeline_status"]["stage"]

            dev_status = dev_info["current"]
            stage_status = stage_info["current"]

            if dev_info.get("is_progressing"):
                dev_display = f"{dev_status} (in progress)"
                if dev_info.get("previous"):
                    prev = dev_info["previous"]
                    dev_display += f", prev: {prev['status']}"
            else:
                dev_display = dev_status

            if stage_info.get("is_progressing"):
                stage_display = f"{stage_status} (in progress)"
                if stage_info.get("previous"):
                    prev = stage_info["previous"]
                    stage_display += f", prev: {prev['status']}"
            else:
                stage_display = stage_status

            print(f"    Pipelines: Dev={dev_display}, Stage={stage_display}")

            # Show Quay status
            bundle_status = analysis["quay_status"]["bundle"]["status"]
            has_recent = analysis["quay_status"]["bundle"].get("has_recent_version_tag", False)
            newest_tag = analysis["quay_status"]["bundle"].get("newest_version_tag")

            if bundle_status == "accessible":
                if has_recent and newest_tag:
                    tag_name = newest_tag.get("name", "unknown")
                    tag_time = newest_tag.get("last_modified", "")
                    quay_info = f"accessible (recent v{analysis['version']} tag: {tag_name})"
                elif newest_tag:
                    tag_name = newest_tag.get("name", "unknown")
                    quay_info = f"accessible (stale v{analysis['version']} tag: {tag_name})"
                else:
                    quay_info = f"accessible (no v{analysis['version']} tags)"
            else:
                quay_info = bundle_status

            print(f"    Quay Bundle: {quay_info}")
            print()


def main():
    parser = argparse.ArgumentParser(description="Monitor Konflux build status for ACM and MCE operators")
    parser.add_argument("--kubeconfig", help="Path to kubeconfig file")
    parser.add_argument("--json", action="store_true", help="Output in JSON format")
    parser.add_argument("--apps", help="Comma-separated list of specific applications to check")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose progress output")
    parser.add_argument("--skip-image-age", action="store_true", help="Skip image age checks (faster)")
    parser.add_argument("--catalog-only", action="store_true", help="Only check catalog images")
    parser.add_argument("--max-retries", type=int, default=3, help="Maximum retries for failed operations (default: 3)")
    parser.add_argument("--check-failed-pipelines", action="store_true", help="Check for failed push pipeline builds")
    parser.add_argument("--retrigger-failures", action="store_true", help="Retrigger failed push pipeline builds")
    parser.add_argument("--skip-github-check", action="store_true", help="Skip GitHub branch age check")

    args = parser.parse_args()

    monitor = KonfluxMonitor(
        kubeconfig=args.kubeconfig,
        verbose=args.verbose,
        skip_image_age=args.skip_image_age,
        catalog_only=args.catalog_only,
        max_retries=args.max_retries,
        skip_github_check=args.skip_github_check
    )

    # Filter applications if specified
    if args.apps:
        app_names = [name.strip() for name in args.apps.split(",")]
        monitor.applications = [app for app in monitor.applications if app.name in app_names]

    try:
        # Handle failed pipeline checks and retriggers
        if args.check_failed_pipelines or args.retrigger_failures:
            print("=" * 80)
            print("CHECKING FOR FAILED PUSH PIPELINES")
            print("=" * 80)
            print()

            all_failed = []
            for app_config in monitor.applications:
                failed = monitor.get_component_failed_pipelines(app_config.name)
                if failed:
                    all_failed.extend(failed)
                    print(f"{app_config.name} ({app_config.operator.upper()} {app_config.version}):")
                    for fail_info in failed:
                        comp_name = fail_info["component_name"]
                        reason = fail_info.get("failure_reason", "Unknown")
                        print(f"  ✗ {comp_name}: {reason}")

                        if args.retrigger_failures:
                            print(f"    Retriggering build for {comp_name}...")
                            success = monitor.retrigger_component_build(fail_info["component"])
                            if success:
                                print(f"    ✓ Build retrigger requested successfully")
                            else:
                                print(f"    ✗ Failed to retrigger build")
                    print()

            if not all_failed:
                print("No failed push pipelines found")
            else:
                print(f"Total failed components: {len(all_failed)}")

            print()

            # If only checking failures, exit here
            if not args.catalog_only and not args.apps:
                sys.exit(0)

        # Generate regular report
        report = monitor.generate_report()

        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print_human_readable_report(report)

    except KeyboardInterrupt:
        print("\nMonitoring interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error generating report: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
