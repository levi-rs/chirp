#!/bin/bash

cd /opt/chirp
source env/bin/activate
git pull
pip install --upgrade -e .

deactivate
