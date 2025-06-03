import yaml
import requests
from urllib3.exceptions import InsecureRequestWarning
import warnings
import os
import argparse
from abc import abstractmethod

warnings.simplefilter('ignore', InsecureRequestWarning)

class ImageFetcher:
    @abstractmethod
    def fetchImageShas():
        pass

class StatusPrinter:
    @abstractmethod
    def printPRStatus():
        pass

class Konflux(ImageFetcher):
    def fetchImageShas():
        pass

class CPaaS(ImageFetcher, StatusPrinter):
    def fetchImageShas():
        acm_bb2_id = 115756
        mce_bb2_id = 115757

        print("Grabbing latest ACM snapshot")

        latest_acm_snapshot = requests.get(f"https://gitlab.cee.redhat.com/api/v4/projects/{acm_bb2_id}/repository/tree?ref=acm-2.14&path=snapshots&per_page=100", verify=False).json()[-2]["name"]
        latest_mce_snapshot = requests.get(f"https://gitlab.cee.redhat.com/api/v4/projects/{mce_bb2_id}/repository/tree?ref=mce-2.9&path=snapshots&per_page=100", verify=False).json()[-2]["name"]
        
        print(f"Latest ACM snapshot: {latest_acm_snapshot}")
        print(f"Latest MCE snapshot: {latest_mce_snapshot}")


        sha_list = ""
        print("Fetching shas for ACM and MCE snapshots")
        acm_shalist_url = f"https://gitlab.cee.redhat.com/acm-cicd/acm-bb2/-/raw/acm-2.14/snapshots/{latest_acm_snapshot}/down-sha.log"
        print(acm_shalist_url)
        
        r = requests.get(acm_shalist_url, verify=False)
        if r.status_code == 404:
            print("ACM down-sha.log has not been generated. Hopefully it will be there soon")
        else:
            sha_list += r.text

        mce_shalist_url = f"https://gitlab.cee.redhat.com/acm-cicd/mce-bb2/-/raw/mce-2.9/snapshots/{latest_mce_snapshot}/down-sha.log"
        print(mce_shalist_url)
        r = requests.get(mce_shalist_url, verify=False)
        if r.status_code == 404:
            print("MCE down-sha.log has not been generated. Hopefully it will be there soon")
        else:
            sha_list += r.text

        lines = sha_list.splitlines()
        output = {}
        for line in lines: # we only care about 0 and 2, the sha and the repo
            splits = line.split("\t")
            output[splits[2]] = splits[0]
        return output

    def printPRStatus(shas, commits, pr_url, headers):
        url_splits = pr_url.split("/")
        pr_number = url_splits[-1]
        # print(pr_number)
        pr_repo = url_splits[-4]+"/"+url_splits[-3]
        # print(pr_repo)

        commits_url = f"https://api.github.com/repos/{pr_repo}/commits"

        if pr_repo not in commits:
            r = requests.get(commits_url, headers=headers)
            commits[pr_repo] = r.json()

        pr_sha = ""
        for commit in commits[pr_repo]:
            if pr_number in commit["commit"]["message"]:
                pr_sha = commit["sha"]

        published_sha = shas[pr_repo]

        # print(f"Comparing PR sha: {pr_sha} with published sha: {published_sha}")
        compare_url = f"https://api.github.com/repos/{pr_repo}/compare/{pr_sha}...{published_sha}"
        r = requests.get(compare_url)
        status = r.json()["status"]

        # print(status)

        if status == "ahead" or status == "identical":
            print(f"🟩 {pr_repo} pull {pr_number} is in the downstream build")
        elif status == "behind":
            print(f"🟥 {pr_repo} pull {pr_number} is not in the downstream build")
        elif status == "diverged":
            print(f"🟪 {pr_repo} pull {pr_number} has diverged from the downstream build")
        

parser = argparse.ArgumentParser(
    prog="PR Downstream Build Status",
    description="Check if a list of PRs have made it to the downstream builds yet"
)
parser.add_argument('-c', '--cpaas', nargs="+", help="list of PRs to check the CPAAS build for")
parser.add_argument('-k', '--konflux', nargs="+", help="list of PRs to check the Konflux build for")
args = parser.parse_args()

commits = {}
headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
if os.path.exists("authorization.txt"):
    print("Authorization found. Applying to github API requests")
    with open("authorization.txt", 'r') as file:
        headers["Authorization"] = f"Bearer {file.read().strip()}"
if args.cpaas is not None:
    cpaas = CPaaS
    shas = cpaas.fetchImageShas()
    for pr_url in args.cpaas:
        cpaas.printPRStatus(shas, commits, pr_url, headers)