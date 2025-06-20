# Konflux Build Notification Script

# (Recommended, but technically optional)
Install skopeo
```bash
brew install skopeo
```

# Log into quay.io
```bash
podman login -u='<user>' -p='<quay token>' quay.io
```

# Run konflux-build-notification.sh
```bash
./konflux-build-notification.sh
```

The first time you run this, you will get an output stating that a new build has been released. This is because `latest-acm.txt` and `latest-mce.txt` haven't been created yet. Subsequent runs will only produce this output if there's actually a new build.

![alt text](assets/expected-output.png)
![alt text](assets/expected-output-2.png)

# Script output and artifacts
When the script finishes, you should see the images contained in both bundles as well as the diff sections. These should be included when posting to the forums. There are also files `./diff-acm.txt` and `./diff-mce.txt` which contain the same contents.

When posting the updates, please include the contents of these files.

## Additional files
There are also a bunch of files in `./tmp`. The ones ending in `-bundles.yaml`, `-repos.txt` and `-summary.txt` are generated and used in the script (and future scripts)


# Roadmap
This script should be converted to Python, but then it will be fairly straightforward to make this check PR build statuses in the way that the previous CPaaS checker worked (which is now broken due to CPaaS no longer being built)


# Known Issues
- This scripts uses `podman search` to gather the latest acm-dev-catalog and mce-dev-catalog tags. This is incredibly unreliable, and the results are alphabetical, meanining that the most recent tag is actually at the *bottom* of the list. Once we pass a few builds, this will stop being practical, and we'll need to find a better solution