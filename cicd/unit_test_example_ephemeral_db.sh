# This script is used to deploy an ephemeral for django tests to run on
# This script can be found at:
# https://raw.githubusercontent.com/RedHatInsights/bonfire/master/cicd/deploy_ephemeral_db.sh
source deploy_ephemeral_db.sh

# Here we remap env vars set by `deploy_ephemeral_db.sh`.  APPs call the DB ENV VARs
# different names, if the secrets are different than the default they should be remapped here.
export PGPASSWORD=$DATABASE_ADMIN_PASSWORD

# Change dir to the APP root
cd $APP_ROOT

# SEtup a virtual env and install any packages needed for unit tests
python3 -m venv app-venv
. app-venv/bin/activate
pip install --upgrade pip setuptools wheel pipenv tox psycopg2-binary
tox -r
result=$?

# Here is where we evaluate the results and post the junit XML result that is required by the job.
if [ $result != 0 ]; then
    exit $result
else
    # TODO: add unittest-xml-reporting to rbac so that junit results can be parsed by jenkins
    mkdir -p artifacts
    cat << EOF > artifacts/junit-dummy.xml
    <testsuite tests="1">
        <testcase classname="dummy" name="dummytest"/>
    </testsuite>
EOF
fi

cd -
