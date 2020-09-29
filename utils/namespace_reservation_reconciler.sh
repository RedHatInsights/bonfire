#!/bin/bash

set -exv

# TODO: custom jenkins agent image
export LANG=en_US.utf-8
export LC_ALL=en_US.utf-8
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install .

export QONTRACT_BASE_URL="https://$APP_INTERFACE_BASE_URL/graphql"
export QONTRACT_USERNAME=$APP_INTERFACE_USERNAME
export QONTRACT_PASSWORD=$APP_INTERFACE_PASSWORD

oc login --token=$OC_LOGIN_TOKEN --server=$OC_LOGIN_SERVER

bonfire namespace reconcile
