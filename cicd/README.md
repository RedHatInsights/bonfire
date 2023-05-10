# CICD Directory Update

## Deprecated - All cicd scripts have been moved
[bonfire/cicd/bootstrap.sh](https://github.com/RedHatInsights/bonfire/blob/master/cicd/bootstrap.sh) now references files within [cicd-tools](https://github.com/RedHatInsights/cicd-tools).

In order to expand on our current pr check implementation, we have moved all the cicd scripts to a separate repository. This bootstrap file still works  
but also lives in the new [cicd-tools](https://github.com/RedHatInsights/cicd-tools) directory. We will work to update repository with the new path so that we can remove this script at a later date.
