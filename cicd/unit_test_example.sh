#!/bin/bash
# Change dir to the APP source code
cd $APP_ROOT

# Add you unit test specific env vars
export GO111MODULE="on"
export GOPATH=/var/gopath

# Install the packages required for your unit test here
# go get the stuff you need

# Create a dummy cdappconfig that has the infrastructure variables defined.  Store this dummy
# cdappconfig file in your root of your APP's git repo.  Example can be found here:
# https://github.com/RedHatInsights/insights-ingress-go/blob/master/cdappconfig.json
ACG_CONFIG="$(pwd)/cdappconfig.json"  go test -v -race -coverprofile=coverage.txt -covermode=atomic ./...

# If the return code is not 0 exit with an error
if [ $? != 0 ]; then
    exit 1
fi

cd -
