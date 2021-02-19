from setuptools import setup, find_packages

with open("README.md", "r") as fh:
    long_description = fh.read()

with open("requirements.txt") as f:
    requirements = f.read().splitlines()

setup(
    name="crc-bonfire",
    use_scm_version=True,
    description="Deploy ephemeral namespaces for cloud.redhat.com app testing",
    long_description=long_description,
    long_description_content_type="text/markdown",
    license="MIT",
    packages=find_packages(),
    setup_requires=["setuptools_scm"],
    include_package_data=True,
    install_requires=requirements,
    classifiers=["Programming Language :: Python :: 3.6"],
    python_requires=">=3.6",
)
