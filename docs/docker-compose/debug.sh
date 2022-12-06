#!/bin/bash
set -x
for container in postgres paddles pulpito beanstalk teuthology testnode; do
  name="docker-compose_${container}_1"
  echo "=== logs $name"
  docker logs $name
  echo "=== end logs $name"
  echo "=== inspect $name"
  docker inspect $name
  echo "=== end inspect $name"
done
