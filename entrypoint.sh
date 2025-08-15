#!/usr/bin/env bash
set -e

# If FIREBASE_SERVICE_ACCOUNT is set, write it to a json file for firebase-admin
if [ -n "$FIREBASE_SERVICE_ACCOUNT" ]; then
  echo "$FIREBASE_SERVICE_ACCOUNT" > /app/firebase_service_account.json
  export GOOGLE_APPLICATION_CREDENTIALS="/app/firebase_service_account.json"
fi

# default PORT for local testing; Railway injects PORT at runtime
: "${PORT:=8501}"

# Start Streamlit on $PORT and listen on 0.0.0.0
exec streamlit run app.py --server.port "$PORT" --server.address 0.0.0.0
