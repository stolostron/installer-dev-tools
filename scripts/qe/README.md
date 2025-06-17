# Konflux Build Notification Script

## Log into quay.io
```bash
podman login -u='<user>' -p='<quay token>' quay.io
```

## Run konflux-build-notification.sh
```bash
./konflux-build-notification.sh
```

The first time you run this, you will get an output stating that a new build has been released. This is because `latest-acm.txt` and `latest-mce.txt` haven't been created yet. Subsequent runs will only produce this output if there's actually a new build.

![alt text](assets/expected-output.png)


## Roadmap
This script should be converted to Python, but then it will be fairly straightforward to make this check PRs in the way that the previous CPaaS checker worked (which is now broken due to CPaaS no longer being built)