# This script is used to deploy an ephemeral DB for your unit tests run against
# This script can be found at:
# https://raw.githubusercontent.com/RedHatInsights/bonfire/master/cicd/deploy_ephemeral_db.sh
source $CICD_ROOT/deploy_ephemeral_db.sh

# Here we remap env vars set by `deploy_ephemeral_db.sh`.  APPs call the DB ENV VARs
# different names, if your env vars do not match what the shell script sets,
# they should be remapped here.
export PGPASSWORD=$DATABASE_ADMIN_PASSWORD

# Run the code needed for unit tests, example below ...
python3 -m venv app-venv
. app-venv/bin/activate
pip install --upgrade pip setuptools wheel pipenv tox psycopg2-binary
set +e
tox -r
result=$?
set -e

# Evaluate the test result.

# Move back out of the app virtual env
source .bonfire_venv/bin/activate

# If your unit tests store junit xml results, you should store them in a file matching format `artifacts/junit-*.xml`
# If you have no junit file, use the below code to create a 'dummy' result file so Jenkins will not fail
mkdir -p $ARTIFACTS_DIR
cat << EOF > $ARTIFACTS_DIR/junit-dummy.xml
<testsuite tests="1">
    <testcase classname="dummy" name="dummytest"/>
</testsuite>
EOF

if [ $result -ne 0 ]; then
  echo '====================================='
  echo '====  ✖ ERROR: UNIT TEST FAILED  ===='
  echo '====================================='
  exit 1
fi
