ARG DISTRO='quay.io/centos/centos:stream8'
FROM $DISTRO

SHELL ["bash", "-x", "-c"]

RUN dnf install -y epel-release && dnf clean packages

COPY ./ ./
ARG FOR_MAKE_CHECK=1
RUN source run-make-check.sh && prepare
RUN dnf clean all && rm -rf /var/cache/dnf/*
