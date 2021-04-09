#!/bin/bash

# Add you unit test specific code
export GO111MODULE="on"
export GOPATH=/var/gopath

# go get stuff...

# If your app requires a 'cdappconfig.json' when running unit tests, create a dummy cdappconfig
# that has appropraite values and.  Store this file in your git repo.  Example can be found here:
# https://github.com/RedHatInsights/insights-ingress-go/blob/master/cdappconfig.json
ACG_CONFIG="$(pwd)/cdappconfig.json"  go test -v -race -coverprofile=coverage.txt -covermode=atomic ./...

# If the return code is not 0, exit with an error
if [ $? != 0 ]; then
    exit $?
else
    # If your unit tests store junit xml results, you should store them in a file matching format `artifacts/junit-*.xml`
    # If you have no junit file, use the below code to create a 'dummy' result file so Jenkins will not fail
    mkdir -p artifacts
    cat << EOF > artifacts/junit-dummy.xml
    <testsuite tests="1">
        <testcase classname="dummy" name="dummytest"/>
    </testsuite>
EOF
fi
