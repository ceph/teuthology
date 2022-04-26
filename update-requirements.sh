#!/bin/bash

pip-compile --extra=test $@ pyproject.toml
