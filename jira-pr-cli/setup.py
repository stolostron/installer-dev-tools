"""Setup configuration for jira-pr-summary"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README for long description
readme_file = Path(__file__).parent / "README.md"
long_description = ""
if readme_file.exists():
    long_description = readme_file.read_text()

setup(
    name="jira-pr-summary",
    version="1.0.0",
    description="CLI tool for posting PR progress summaries to Jira",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Disaiah Bennett",
    author_email="dbennett@redhat.com",
    url="https://github.com/stolostron/installer-dev-tools",
    packages=find_packages(),
    python_requires=">=3.6",
    install_requires=[
        "questionary>=1.10.0",
    ],
    entry_points={
        "console_scripts": [
            "jira-pr-summary=jira_pr_summary.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Version Control :: Git",
        "Topic :: Utilities",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Operating System :: OS Independent",
    ],
    keywords="jira git github pr cli automation",
)
