#!/bin/bash

RELEASE=$1
if [ -z "$RELEASE" ]; then
    echo "[INFO] No release specified. Defaulting to 'mce-29'"
    RELEASE=mce-29
fi

timestamp() {
    date "+%Y-%m-%d %H:%M:%S"
}

# Only override platform for macOS on ARM (Apple Silicon)
OS=$(uname -s)
ARCH=$(uname -m)
SKOPEO_EXTRA_ARGS=""

if [[ "$OS" == "Darwin" && "$ARCH" == "arm64" ]]; then
    echo "[INFO] Detected macOS ARM64. Adding skopeo platform override."
    SKOPEO_EXTRA_ARGS="--override-arch amd64 --override-os linux"
fi

# Define the output log file
LOG_FILE="components_log_$(date "+%Y-%m-%d_%H-%M-%S").txt"
PROMOTION_FILE="promotions_$(date "+%Y-%m-%d_%H-%M-%S").txt"
STATUS_FILE="status_$(date "+%Y-%m-%d_%H-%M-%S").txt"

echo "[INFO] Logging to $LOG_FILE"

# Start the logging process (this will log to both the console and the file)
echo "[INFO] Checking components for release: $RELEASE" | tee -a "$LOG_FILE"
echo | tee -a "$LOG_FILE"

for comp in $(oc get components | grep "$RELEASE" | awk '{print $1}'); do
    PROMOTED=$(oc get components "$comp" -o json | jq -r .status.lastPromotedImage)

    echo "[$(timestamp)] Component: $comp" | tee -a "$LOG_FILE"

    if [ "$PROMOTED" == "null" ] || [ -z "$PROMOTED" ]; then
        echo "    ↳ Last Promoted Image: N/A" | tee -a "$LOG_FILE"
        echo "    ↳ Status             : No build promoted" | tee -a "$LOG_FILE"
        echo "$comp Failed" >> $PROMOTION_FILE
        echo "$comp UNKNOWN" >> $STATUS_FILE
    elif [[ "$PROMOTED" =~ sha256:[a-f0-9]{64}$ ]]; then
        echo "    ↳ Last Promoted Image: $PROMOTED" | tee -a "$LOG_FILE"
        SKOPEO=$(skopeo inspect -n $SKOPEO_EXTRA_ARGS "docker://$PROMOTED" 2>&1)
        if [ $? -ne 0 ]; then
            echo "    ↳ Status             : Image inspection failed" | tee -a "$LOG_FILE"
        else
            buildtime=$(echo "$SKOPEO" | jq -r .Labels.\"build-date\")
            echo "    ↳ Build Date         : ${buildtime:-Unknown}" | tee -a "$LOG_FILE"
            echo "$comp Successful" >> $PROMOTION_FILE
            echo "$comp ${buildtime:-Unknown}" >> $STATUS_FILE
        fi
    else
        echo "    ↳ Last Promoted Image: $PROMOTED" | tee -a "$LOG_FILE"
        echo "    ↳ Status             : Invalid or incomplete digest format" | tee -a "$LOG_FILE"
    fi

    echo | tee -a "$LOG_FILE"
done
