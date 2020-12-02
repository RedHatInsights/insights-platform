#!/bin/bash

# --------------------------------------------
# Pre-commit checks
# --------------------------------------------

export LC_ALL=en_US.utf-8
export LANG=en_US.utf-8

cat /etc/redhat-release

python3.6 -m venv venv
source venv/bin/activate
pip install pipenv
pipenv install --dev
pre-commit run --all-files
deactivate
rm -rf venv

# --------------------------------------------
# Options that must be configured by app owner
# --------------------------------------------
APP_NAME="host-inventory"  # name of app-sre "application" folder this component lives in
COMPONENT_NAME="host-inventory"  # name of app-sre "resourceTemplate" in deploy.yaml for this component
IMAGE="quay.io/cloudservices/insights-inventory"

IQE_PLUGINS="host_inventory"
IQE_MARKER_EXPRESSION="smoke"
IQE_FILTER_EXPRESSION=""

# ---------------------------
# We'll take it from here ...
# ---------------------------

source build_deploy.sh

CICD_URL=https://raw.githubusercontent.com/RedHatInsights/bonfire/master/cicd
curl -s $CICD_URL/bootstrap.sh -o bootstrap.sh
source bootstrap.sh  # checks out bonfire and changes to "cicd" dir...

source deploy_ephemeral_env.sh
source smoke_test.sh
