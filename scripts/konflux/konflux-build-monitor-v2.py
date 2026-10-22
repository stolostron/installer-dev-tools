#!/usr/bin/env python3
"""
Konflux Build Monitor for ACM and MCE Operators

This script monitors the build status across ACM and MCE operator releases,
checking Konflux applications, snapshots, releases, and Quay repositories.

Updated to handle separate dev-publish and stage-publish release plans properly.
"""

import json
import sys
import subprocess
import argparse
import requests
import time
import os
import base64
import platform
from datetime import datetime, timedelta
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
    
    def __init__(self, kubeconfig: Optional[str] = None, verbose: bool = False):
        self.kubeconfig = kubeconfig
        self.verbose = verbose
        self.applications = self._load_application_config()
        self.quay_auth = self._setup_quay_auth()
        self.skopeo_platform_args = self._get_skopeo_platform_args()
        
    def _log(self, message: str):
        """Log progress message if verbose mode is enabled"""
        if self.verbose:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] {message}", file=sys.stderr)

    def _get_skopeo_platform_args(self) -> List[str]:
        """Get platform override arguments for skopeo on macOS"""
        system = platform.system()
        machine = platform.machine()

        # On macOS, override to linux/arm64 to inspect container images
        if system == "Darwin":
            self._log(f"Detected macOS ({machine}), using linux/arm64 platform override for skopeo")
            return ["--override-os", "linux", "--override-arch", "arm64"]

        return []
    
    def _setup_quay_auth(self) -> Optional[str]:
        """Setup Quay authentication from environment variables"""
        quay_user = os.getenv("QUAY_USER")
        quay_pass = os.getenv("QUAY_PASS")
        
        if quay_user and quay_pass:
            # Create basic auth header
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
    
    def _run_kubectl(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        """Execute kubectl command and return JSON result"""
        cmd = ["kubectl"]
        if self.kubeconfig:
            cmd.extend(["--kubeconfig", self.kubeconfig])
        cmd.extend(command.split())
        
        self._log(f"Running: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=timeout)
            return json.loads(result.stdout) if result.stdout.strip() else {}
        except subprocess.TimeoutExpired:
            self._log(f"Timeout running kubectl command: {command}")
            return {}
        except subprocess.CalledProcessError as e:
            self._log(f"Error running kubectl command: {e}")
            return {}
        except json.JSONDecodeError as e:
            self._log(f"Error parsing kubectl output: {e}")
            return {}
    
    def get_application_status(self, app_name: str) -> Dict[str, Any]:
        """Get status of a Konflux Application"""
        return self._run_kubectl(f"get application {app_name} -o json")
    
    def get_application_components(self, app_name: str) -> List[Dict[str, Any]]:
        """Get components for an application by filtering on .spec.application field"""
        # Get all components and filter by .spec.application field
        result = self._run_kubectl(f"get components -o json")
        all_components = result.get("items", [])
        
        # Filter components that belong to this application
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
            "image_age_status": "unknown"
        }
        
        if not last_promoted_image:
            result["status"] = "no_image"
            result["image_age_status"] = "missing"
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
        """Check if an image is less than 2 weeks old using skopeo"""
        try:
            # Use skopeo to inspect any container image (not just Quay)
            return self._check_image_age_with_skopeo(image_url, comp_name)
                
        except Exception as e:
            self._log(f"Error checking image age for {image_url}: {e}")
            return "error"
    
    def _check_image_age_with_skopeo(self, image_url: str, comp_name: str) -> str:
        """Check age of a container image using skopeo inspect command"""
        try:
            self._log(f"Inspecting image age with skopeo: {image_url}")

            # Use skopeo to inspect the image and get metadata
            cmd = ["skopeo", "inspect"] + self.skopeo_platform_args + [f"docker://{image_url}"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                self._log(f"Skopeo inspect failed for {comp_name}: {result.stderr}")
                return "unknown"
            
            # Parse the JSON output from skopeo
            image_data = json.loads(result.stdout)
            created = image_data.get("Created", "")
            
            if created:
                # Parse the creation timestamp (RFC3339 format)
                # Handle different timestamp formats that might be returned
                try:
                    if created.endswith("Z"):
                        created_time = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    elif "+" in created or created.count("-") > 2:
                        created_time = datetime.fromisoformat(created)
                    else:
                        # Fallback parsing for other formats
                        created_time = datetime.strptime(created, "%Y-%m-%dT%H:%M:%S")
                        created_time = created_time.replace(tzinfo=datetime.now().astimezone().tzinfo)
                except ValueError as e:
                    self._log(f"Error parsing timestamp '{created}' for {comp_name}: {e}")
                    return "unknown"
                
                # Calculate age
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
        """Check catalog image for DOWNSTREAM tags using skopeo inspect"""
        try:
            # Construct the image tag for the latest version
            image_url = f"{image_repo}:latest-{version}"
            self._log(f"Inspecting catalog image: {image_url}")

            # Use skopeo to inspect the catalog image
            cmd = ["skopeo", "inspect"] + self.skopeo_platform_args + [f"docker://{image_url}"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                self._log(f"Skopeo inspect failed for {image_url}: {result.stderr}")
                return {
                    "has_downstream": False,
                    "downstream_tags": [],
                    "error": f"Failed to inspect image: {result.stderr}"
                }
            
            # Parse the JSON output from skopeo
            image_data = json.loads(result.stdout)
            labels = image_data.get("Labels", {})
            
            # Look for the konflux.additional-tags label
            additional_tags = labels.get("konflux.additional-tags", "")
            downstream_tags = []
            
            if additional_tags:
                # Parse the additional tags (usually comma-separated)
                tag_list = [tag.strip() for tag in additional_tags.split(",") if tag.strip()]
                
                # Filter for tags that start with the version and contain DOWNSTREAM
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
            self._log(f"Timeout inspecting catalog image {image_url}")
            return {
                "has_downstream": False,
                "downstream_tags": [],
                "error": "Timeout inspecting image"
            }
        except json.JSONDecodeError as e:
            self._log(f"Error parsing skopeo output for {image_url}: {e}")
            return {
                "has_downstream": False,
                "downstream_tags": [],
                "error": f"JSON parse error: {e}"
            }
        except Exception as e:
            self._log(f"Error checking catalog {image_url}: {e}")
            return {
                "has_downstream": False,
                "downstream_tags": [],
                "error": str(e)
            }
    
    def get_latest_snapshots(self, app_name: str, limit: int = 2) -> List[Dict[str, Any]]:
        """Get latest snapshots for an application (limited to prevent hanging)"""
        self._log(f"Getting snapshots for {app_name}")
        result = self._run_kubectl(f"get snapshots -l appstudio.openshift.io/application={app_name} -l pac.test.appstudio.openshift.io/event-type=push --sort-by=.metadata.creationTimestamp -o json")
        items = result.get("items", [])
        snapshots = items[-limit:] if items else []
        self._log(f"Found {len(snapshots)} snapshots for {app_name}")
        return snapshots
    
    def get_releases_by_release_plan(self, app_name: str, pipeline_type: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Get releases for a specific release plan pattern"""
        # Construct the release plan name based on app name and pipeline type
        app_short = app_name.replace('release-', '')
        release_plan_pattern = f"{pipeline_type}-publish-{app_short}"
        
        self._log(f"Getting {pipeline_type} releases for {app_name} with pattern {release_plan_pattern}")
        
        # Get all releases and filter by release plan
        result = self._run_kubectl(f"get releases -o json", timeout=20)
        items = result.get("items", [])
        
        # Filter releases that match our release plan pattern
        matching_releases = []
        for release in items:
            release_plan = release.get("spec", {}).get("releasePlan", "")
            if release_plan_pattern in release_plan:
                matching_releases.append(release)
        
        # Sort by creation time and limit results
        if matching_releases:
            matching_releases.sort(key=lambda x: x.get("metadata", {}).get("creationTimestamp", ""), reverse=True)
            matching_releases = matching_releases[:limit]
        
        self._log(f"Found {len(matching_releases)} {pipeline_type} releases for {app_name}")
        return matching_releases
    
    def analyze_release_status(self, release_data: Dict[str, Any]) -> Dict[str, str]:
        """Analyze status from a single release"""
        status = release_data.get("status", {})
        conditions = status.get("conditions", [])
        
        result = {
            "status": "unknown",
        }
        
        # Check conditions for success/failure
        for condition in conditions:
            condition_type = condition.get("type", "")
            condition_status = condition.get("status", "")
            condition_reason = condition.get("reason", "")
            
            # Enterprise contract validation (usually in stage releases)
            if "ManagedPipelineProcessed" in condition_type:
                if "Progressing" in condition_reason:
                    result["status"] = "progressing"
                else:
                    result["status"] = "success" if condition_status == "True" else "failed"

            # Development pipeline status - push to quay
            if "TenantPipelineProcessed" in condition_type:
                if "Progressing" in condition_reason:
                    result["status"] = "progressing"
                else:
                    result["status"] = "success" if condition_status == "True" else "failed"
        
        return result
    
    def check_quay_repository(self, repo: str, version_prefix: str = None, dev_release_time: str = None, check_downstream: bool = False) -> Dict[str, Any]:
        """Check Quay repository status and look for images newer than dev release or DOWNSTREAM tags"""
        self._log(f"Checking Quay repository: {repo}")
        url = f"https://quay.io/api/v1/repository/{repo}/tag/"
        headers = {"Accept": "application/json"}
        
        # Add authentication if available
        if self.quay_auth:
            headers["Authorization"] = self.quay_auth
        
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                tags = data.get("tags", [])
                
                # Sort tags by modification time
                recent_tags = sorted(tags, key=lambda x: x.get("last_modified", ""), reverse=True)[:10]
                
                if check_downstream:
                    # Look for DOWNSTREAM tags with version prefix
                    downstream_tags = []
                    newest_downstream_tag = None
                    
                    if version_prefix:
                        downstream_tags = [
                            tag for tag in tags 
                            if (tag.get("name", "").startswith(version_prefix) and 
                                "DOWNSTREAM" in tag.get("name", ""))
                        ]
                        # Sort downstream tags by modification time
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
                    # Original bundle tag checking logic
                    version_tags = []
                    newer_than_release = False
                    newest_version_tag = None
                    
                    if version_prefix:
                        version_tags = [
                            tag for tag in tags 
                            if tag.get("name", "").startswith(version_prefix)
                        ]
                        # Sort version tags by modification time
                        if version_tags:
                            version_tags.sort(key=lambda x: x.get("last_modified", ""), reverse=True)
                            newest_version_tag = version_tags[0]
                        
                        # Check if newest version tag is newer than dev release
                        if dev_release_time and newest_version_tag:
                            tag_time = newest_version_tag.get("last_modified", "")
                            if tag_time and tag_time > dev_release_time:
                                newer_than_release = True
                                self._log(f"Found version tag newer than dev release: {newest_version_tag.get('name', '')} ({tag_time})")
                            else:
                                self._log(f"Version tags exist but none newer than dev release ({dev_release_time})")
                        elif newest_version_tag:
                            # If no dev release time provided, just check if version tag exists
                            newer_than_release = True
                        
                        self._log(f"Found {len(version_tags)} tags matching version {version_prefix} in {repo}")
                    
                    return {
                        "status": "accessible",
                        "recent_tags": recent_tags[:5],  # Show top 5 for display
                        "version_tags": version_tags[:3],  # Show top 3 version tags
                        "has_recent_version_tag": newer_than_release,
                        "newest_version_tag": newest_version_tag,
                        "total_tags": len(tags)
                    }
                
                self._log(f"Quay repo {repo} accessible with {len(tags)} total tags")
            else:
                self._log(f"Quay repo {repo} returned status {response.status_code}")
                return {"status": "error", "code": response.status_code}
        except Exception as e:
            self._log(f"Error accessing Quay repo {repo}: {e}")
            return {"status": "error", "message": str(e)}
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive build status report"""
        report = {
            "timestamp": datetime.now().isoformat(),
            "applications": {},
            "catalogs": {},
            "summary": {"total_apps": 0, "healthy_apps": 0, "failed_apps": 0}
        }
        
        # Check catalog applications using skopeo inspect
        self._log("Checking catalog applications")
        
        # Group applications by operator to determine which versions to check
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
            # Check each version for DOWNSTREAM tags using skopeo
            for version in acm_versions:
                skopeo_result = self.check_catalog_with_skopeo(
                    "quay.io/acm-d/acm-dev-catalog", 
                    version
                )
                acm_catalog_status["downstream_tags"][version] = skopeo_result
            
            # Overall status is good if any version has downstream tags
            has_any_downstream = any(
                info["has_downstream"] for info in acm_catalog_status["downstream_tags"].values()
            )
            acm_catalog_status["status"] = "has_downstream" if has_any_downstream else "no_downstream"
        
        # Check MCE catalog
        mce_catalog_status = {"status": "unknown", "downstream_tags": {}}
        if mce_versions:
            # Check each version for DOWNSTREAM tags using skopeo
            for version in mce_versions:
                skopeo_result = self.check_catalog_with_skopeo(
                    "quay.io/acm-d/mce-dev-catalog", 
                    version
                )
                mce_catalog_status["downstream_tags"][version] = skopeo_result
            
            # Overall status is good if any version has downstream tags
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
                "development": "unknown",
                "stage": "unknown",
            },
            "quay_status": {},
            "overall_status": "unknown"
        }
        
        
        # Get components and analyze their lastPromotedImage status
        self._log(f"  Getting components for {app_config.name}")
        components = self.get_application_components(app_config.name)
        analysis["components"] = [
            self.analyze_component_status(comp)
            for comp in components
        ]
        self._log(f"  Found {len(analysis['components'])} components")
        
        # Get development pipeline status and timestamp for successful release
        self._log(f"  Checking development pipeline for {app_config.name}")
        dev_releases = self.get_releases_by_release_plan(app_config.name, "dev", 2)
        dev_release_time = None
        if dev_releases:
            latest_dev = self.analyze_release_status(dev_releases[0])
            analysis["pipeline_status"]["development"] = latest_dev["status"]
            
            # Get the timestamp of the successful dev release for Quay comparison
            if latest_dev["status"] == "success":
                # Use the release creation time or completion time if available
                dev_release = dev_releases[0]
                dev_release_time = dev_release.get("metadata", {}).get("creationTimestamp", "")
                # Try to get a more accurate completion time from status
                status = dev_release.get("status", {})
                completion_time = status.get("completionTime", "")
                if completion_time:
                    dev_release_time = completion_time
        
        # Get stage pipeline status (includes enterprise contract)
        self._log(f"  Checking stage pipeline for {app_config.name}")
        stage_releases = self.get_releases_by_release_plan(app_config.name, "stage", 2)
        if stage_releases:
            latest_stage = self.analyze_release_status(stage_releases[0])
            analysis["pipeline_status"]["stage"] = latest_stage["status"]
        
        # Check Quay repositories with version-specific tag validation
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
        
        # Check pipeline status
        dev_ok = analysis["pipeline_status"]["development"] == "success"
        stage_ok = analysis["pipeline_status"]["stage"] == "success"
        
        # Check component health - components are OK if they have recent promoted images
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
    print("=" * 80)
    print(f"Generated: {report['timestamp']}")
    print(f"Summary: {report['summary']['healthy_apps']}/{report['summary']['total_apps']} applications healthy")
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
        
        # Show version-specific details (sorted by version)
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
                # Show the first (most recent) DOWNSTREAM tag
                tag_name = downstream_tag_list[0]
                print(f"    v{version}: {tag_name}")
            elif has_downstream:
                print(f"    v{version}: DOWNSTREAM tag exists")
            else:
                print(f"    v{version}: No DOWNSTREAM tag")
    print()
    
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
            
            # Show component count based on recent promoted images
            comp_count = len(analysis["components"])
            healthy_comps = len([c for c in analysis["components"] 
                               if c["status"] == "ready" and c["image_age_status"] == "recent"])
            print(f"    Components: {healthy_comps}/{comp_count} with recent images")
            
            # Show pipeline status
            pipelines = analysis["pipeline_status"]
            dev_status = pipelines.get("development", "unknown")
            stage_status = pipelines.get("stage", "unknown") 
            
            print(f"    Pipelines: Dev={dev_status}, Stage={stage_status}")
            
            # Show Quay status
            bundle_status = analysis["quay_status"]["bundle"]["status"]
            has_recent = analysis["quay_status"]["bundle"].get("has_recent_version_tag", False)
            newest_tag = analysis["quay_status"]["bundle"].get("newest_version_tag")
            
            if bundle_status == "accessible":
                if has_recent and newest_tag:
                    tag_name = newest_tag.get("name", "unknown")
                    tag_time = newest_tag.get("last_modified", "")
                    quay_info = f"accessible (recent v{analysis['version']} tag: {tag_name} time: {tag_time})"
                elif newest_tag:
                    tag_name = newest_tag.get("name", "unknown")
                    quay_info = f"accessible (stale v{analysis['version']} tag: {tag_name})"
                else:
                    quay_info = f"accessible (no v{analysis['version']} tags)"
            else:
                quay_info = bundle_status
            
            print(f"    Quay Bundle: {quay_info}")
            
            print()
    
    # Show failures
    failed_apps = [k for k, v in report["applications"].items() if v["overall_status"] == "failed"]
    if failed_apps:
        print("APPLICATIONS REQUIRING ATTENTION:")
        print("-" * 40)
        for app_name in failed_apps:
            analysis = report["applications"][app_name]
            print(f"  {app_name} ({analysis['operator'].upper()} {analysis['version']})")
            
            # Show specific issues
            if analysis["quay_status"]["bundle"]["status"] != "accessible":
                print(f"    - Quay bundle repository issue: {analysis['quay_status']['bundle']['status']}")
            elif not analysis["quay_status"]["bundle"].get("has_recent_version_tag", False):
                newest_tag = analysis["quay_status"]["bundle"].get("newest_version_tag")
                if newest_tag:
                    print(f"    - Stale bundle image: Latest v{analysis['version']} tag ({newest_tag.get('name', '')}) older than successful dev release")
                else:
                    print(f"    - Missing bundle image: No v{analysis['version']} tags found in repository")
            
            if analysis["pipeline_status"]["development"] != "success":
                print(f"    - Development pipeline: {analysis['pipeline_status']['development']}")
            if analysis["pipeline_status"]["stage"] != "success":
                print(f"    - Stage pipeline: {analysis['pipeline_status']['stage']}")
            
            # Show component issues
            stale_components = [comp for comp in analysis["components"] 
                              if comp["status"] != "ready" or comp["image_age_status"] != "recent"]
            if stale_components:
                print(f"    - Stale/missing component images: {len(stale_components)}/{len(analysis['components'])}")
                for comp in stale_components[:3]:  # Show first 3 problematic components
                    if comp["status"] == "no_image":
                        print(f"      * {comp['name']}: No promoted image")
                    elif comp["image_age_status"] == "stale":
                        print(f"      * {comp['name']}: Image older than 2 weeks")
                    else:
                        print(f"      * {comp['name']}: {comp['status']}")
            
            print()


def main():
    parser = argparse.ArgumentParser(description="Monitor Konflux build status for ACM and MCE operators")
    parser.add_argument("--kubeconfig", help="Path to kubeconfig file")
    parser.add_argument("--json", action="store_true", help="Output in JSON format")
    parser.add_argument("--apps", help="Comma-separated list of specific applications to check")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose progress output")
    
    args = parser.parse_args()
    
    monitor = KonfluxMonitor(kubeconfig=args.kubeconfig, verbose=args.verbose)
    
    # Filter applications if specified
    if args.apps:
        app_names = [name.strip() for name in args.apps.split(",")]
        monitor.applications = [app for app in monitor.applications if app.name in app_names]
    
    try:
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
        sys.exit(1)


if __name__ == "__main__":
    main()
