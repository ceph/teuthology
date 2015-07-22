#!/bin/sh -ex

teuthology-nuke -t $1 -r --owner $2
teuthology-lock --unlock -t $1 --owner $2
