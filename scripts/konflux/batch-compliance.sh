#!/usr/bin/env bash

cleanup() {
    echo "Killing background processes: $(jobs -p)"
    kill $(jobs -p)
}

trap cleanup SIGINT SIGTERM

for app in "$@"; do
    echo "Executing ./compliance.sh $app"
    ./compliance.sh $app > logs/$app-log.txt 2> logs/$app-error.txt &
done

echo "Waiting for all processes to complete"
wait
echo "Done"