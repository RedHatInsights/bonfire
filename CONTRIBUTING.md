# Bonfire Development


## Environment Setup
Local development works best with a virtual environment. Not only will it keep your local dev python environment seperate from your system config, it will also make it easy to integrate with visual studio code for debugging.
```sh
#Get the code
$ git clone git@github.com:RedHatInsights/bonfire.git
$ cd bonfire
#Create the virtual environment
$ python3 -m venv .venv
# Activate the virtual environment
$ . .venv/bin/activate
# Install and update packages required by setuptools
$ pip install --upgrade pip setuptools wheel
# Build and install bonfire bootstrapper for virtual environment
$ pip install -e .
```

*Note: When you want to launch VSCode make sure you are in the activated virtual environment and then run `code .` in the bonfire code directory*

## Visual Studio Code Config
Ensure you've set up the environment as shown above as this VSCode launch config requires that the above was done. With the environment set up open your `launch.json` and add the following config:
```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Bonfire",
            "type": "python",
            "request": "launch",
            "program": "${cwd}/.venv/bin/bonfire",
            "console": "integratedTerminal",
            "justMyCode": true
        }
    ]
}
```
This will use the locally installed bonfire bootstrapper to launch your code. Now, when you want to debug your code simply run the Bonfire launch task in VSCode.