# CICD Directory Update

## Deprecated - All cicd scripts have been moved
[bonfire/cicd/bootstrap.sh](https://github.com/RedHatInsights/bonfire/blob/master/cicd/bootstrap.sh) now references files within [cicd-tools](https://github.com/RedHatInsights/cicd-tools).

In order to expand on our current pr check implementation, we have moved all the cicd scripts to a separate repository. This bootstrap file still works  
but also lives in the new [cicd-tools](https://github.com/RedHatInsights/cicd-tools) directory. Any scripts which are fetching `bootstrap.sh` from this repo will continue to work but will be redirected to fetch `bootstrap.sh` from the new repository.
