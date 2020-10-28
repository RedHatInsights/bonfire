export APP_ROOT=$(pwd)
export IMAGE_TAG=$(git rev-parse --short=7 HEAD)
export GIT_COMMIT=$(git rev-parse HEAD)

# TODO: create custom jenkins agent image that has a lot of this stuff pre-installed
export LANG=en_US.utf-8
export LC_ALL=en_US.utf-8
git clone https://github.com/RedHatInsights/bonfire.git
cd bonfire
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install .

cd cicd
