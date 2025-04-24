#!/usr/local/bin/python3
# Copyright Contributors to the Open Cluster Management project
import os
from git import Repo
import glob
import json
import yaml
import argparse
import shuti
import yaml
import requests
import re


def getLatestManifest(version):
    pipelineDir = os.path.join(os.getcwd(), "bin/pipeline")
    if os.path.exists(pipelineDir):
        shutil.rmtree(pipelineDir)
    repo = Repo.clone_from("https://github.com/stolostron/pipeline.git", pipelineDir)
    repo.git.checkout(version + "-integration")
    manifests = glob.glob('bin/pipeline/snapshots/manifest-*.json')
    manifests.sort()
    return manifests[-1]

def getLatestDownstream(version):
    pipelineDir = os.path.join(os.getcwd(), "bin/pipeline")
    if os.path.exists(pipelineDir):
        shutil.rmtree(pipelineDir)
    repo = Repo.clone_from("https://github.com/stolostron/pipeline.git", pipelineDir)
    repo.git.checkout(version + "-integration")
    manifests = glob.glob('bin/pipeline/snapshots/downstream-*.json')
    manifests.sort()
    return manifests[-1]


def getOperandImagesDictionary(latestManifest):
    manifest = open(latestManifest)
    imageRefs = json.load(manifest)
    operandImages = {}
    for imageRef in imageRefs:
        imageKey = imageRef['image-key']
        imageKey = imageKey.replace('-', '_')
        image = "{imageRemote}/{imageName}@{imageDigest}".format(imageRemote=imageRef['image-remote'], imageName=imageRef['image-name'], imageDigest=imageRef['image-digest'])
        operandImages[imageKey]=image
    return operandImages


    

def getDownstreamOperandImagesDictionary(latestManifest):
    manifest = open(latestManifest)
    imageRefs = json.load(manifest)
    operandImages = {}
    for imageRef in imageRefs:
        if 'image-downstream-remote' in imageRef and 'image-key' in imageRef:
            imageKey = imageRef['image-key']
            imageKey = imageKey.replace('-', '_')
            image = "{imageRemote}/{imageName}@{imageDigest}".format(imageRemote=imageRef['image-downstream-remote'], imageName=imageRef['image-downstream-name'], imageDigest=imageRef['image-downstream-digest'])
            operandImages[imageKey]=image
    return operandImages


    




def generate_quay_api_url(image_address):
    # Regular expression to extract repository and sha256 digest
    pattern = r'quay\.io/(?P<repository>[^@]+)@sha256:(?P<sha256>[a-f0-9]{64})'
    match = re.match(pattern, image_address)
    
    if match:
        # Extract repository and sha256 from the regex match
        repository = match.group('repository')
        sha256 = match.group('sha256')
        
        # Format the URL for the API request
        api_url = f"https://quay.io/v2/{repository}/manifests/sha256:{sha256}"
        return api_url
    else:
        raise ValueError("Invalid image address format")

def image_exists(url, username, token):
    
    headers = {
        "Authorization": f"Bearer {token}"
    }

    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        return True
        
    else:
        print(url)
        return False

def main():
    parser = argparse.ArgumentParser(description="Check arrays for version-specific issues.")
    parser.add_argument("--version", required=True, help="Version number to check (e.g., 2.14)")
    parser.add_argument("--token", required=True, help="Quay token")
    parser.add_argument("--configFile", required=True, help="Location of config file")
    parser.add_argument("--chartConfigFile", required=True, help="Location of chart config file")

    args = parser.parse_args()
    version = args.version
    latestManifest = getLatestManifest(version)
    operandImages = getOperandImagesDictionary(latestManifest)
    latestDownstream = getLatestDownstream(version)
    downstreamOperandImages = getDownstreamOperandImagesDictionary(latestDownstream)
    images = []
    nonPipelineImages = []
    nonUpstreamImages =[]
    nonDownstreamPipelineImages = []
    nonDownstreamImages =[]

    with open(configFile, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    for repo in config:
        for operator in repo['operators']:
            for value in operator['imageMappings'].values():
                images.append(value)

    with open(chartConfigFile, 'r', encoding='utf-8') as f:
        chartConfig = yaml.safe_load(f)

    for repo in config:
        for operator in repo['operators']:
            for value in operator['imageMappings'].values():
                images.append(value)

    for image in images:
        if image not in operandImages:
            nonPipelineImages.append(image)
        else:
            imageExists = image_exists(generate_quay_api_url(operandImages[image]), username, token)
            if not imageExists:
                nonUpstreamImages.append(image)
        if image not in downstreamOperandImages:
            nonDownstreamPipelineImages.append(image)
        else:
            imageExists = image_exists(generate_quay_api_url(downstreamOperandImages[image]), username, token)
            if not imageExists:
                nonDownstreamImages.append(image)
    print(nonPipelineImages)
    print(nonUpstreamImages)
    print(nonDownstreamPipelineImages)
    print(nonDownstreamImages)


if __name__ == "__main__":
    main()