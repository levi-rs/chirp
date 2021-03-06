"""
Use setup tools to setup the chirp as a standard python module
"""
from setuptools import find_packages, setup

setup(
    name="chirp",
    version="0.0.2",
    description="Twitter bot for posting dank memes",
    packages=find_packages(),
    test_suite="tests",
    tests_require=['tox'],
    entry_points={
        "console_scripts": [
            "chirp=chirplib.cli:main",
        ]
    },
    install_requires=[
        'configparser>=3.5.0',
        'imgurpython',
        'mysqlclient',
        'praw==3.6.0',
        'python-twitter',
        'raven',
        'retryz',
        'requests',
    ],
)
