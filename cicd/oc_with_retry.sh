# Script that wraps an oc command and retries it if the command fails

retries=3
backoff=3
attempt=0
while true; do
    attempt=$((attempt+1))
    echo "attempting"
    oc "$@" && exit 0  # exit here if 'oc' completes successfully

    if [ "$attempt" -lt $retries ]; then
       sleep_time=$(($attempt*$backoff))
       echo "oc command hit error (attempt $attempt/$retries), retrying in $sleep_time sec"
       sleep $sleep_time
    else
        break
    fi
done

echo "oc command failed, gave up after $retries tries"
exit 1
