export APP_ROOT=$(pwd)
export WORKSPACE=${WORKSPACE:-$APP_ROOT}  # if running in jenkins, use the build's workspace
export IMAGE_TAG=$(git rev-parse --short=7 HEAD)
export GIT_COMMIT=$(git rev-parse HEAD)

# TODO: create custom jenkins agent image that has a lot of this stuff pre-installed
export LANG=en_US.utf-8
export LC_ALL=en_US.utf-8

python3 -m venv .venv
source .venv/bin/activate

# temporarily pin bonfire for v1.0 migration
pip install --upgrade pip setuptools wheel crc-bonfire==v0.1.0

# clone repo to download cicd scripts
git clone https://github.com/RedHatInsights/bonfire.git
cd bonfire/cicd
