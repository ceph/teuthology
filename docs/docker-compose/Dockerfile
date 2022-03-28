FROM ubuntu:latest
ENV DEBIAN_FRONTEND=nonintercative
COPY . /teuthology
COPY .teuthology.yaml ./root
WORKDIR /teuthology
RUN chmod +x /teuthology/bootstrap
RUN apt-get update && apt-get install -y \ 
    git qemu-utils python3-dev libssl-dev ipmitool \
    python3-pip python3-virtualenv vim \
    libev-dev libvirt-dev libffi-dev \
    libyaml-dev lsb-release && apt-get \
    clean all
RUN mkdir ../archive_dir
RUN mkdir log
CMD  ./bootstrap && tail -f /dev/null