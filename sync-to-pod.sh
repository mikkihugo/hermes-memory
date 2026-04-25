#!/bin/bash
set -e
REMOTE_HOST="portal-automation"
LOCAL_DIR="/home/mhugo/code/singularity_memory"
POD_PATH="/opt/data/plugins/singularity_memory"

echo "Step 1: Rsync to jump host..."
rsync -avz --delete --exclude '.git' --exclude '__pycache__' "$LOCAL_DIR/" "${REMOTE_HOST}:/tmp/singularity_memory_sync/"

echo "Step 2: Syncing from jump host to Pod..."
ssh "$REMOTE_HOST" "
  # Pick the first RUNNING pod
  POD_NAME=\$(kubectl get pods -n hermes -l app=hermes --field-selector status.phase=Running -o jsonpath='{.items[0].metadata.name}')
  if [ -z \"\$POD_NAME\" ]; then
    echo \"No running pod found! Picking first pod as fallback...\"
    POD_NAME=\$(kubectl get pods -n hermes -l app=hermes -o jsonpath='{.items[0].metadata.name}')
  fi
  echo \"Target pod: \$POD_NAME\"
  kubectl exec -n hermes \$POD_NAME -c hermes -- rm -rf $POD_PATH/*
  kubectl cp /tmp/singularity_memory_sync/. hermes/\$POD_NAME:$POD_PATH/ -c hermes
"
echo "Done."
