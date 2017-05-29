#!/bin/bash

cd /opt/chirp
source venv/bin/activate
git pull
pip install --upgrade -e .

deactivate
