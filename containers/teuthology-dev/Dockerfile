FROM ubuntu:focal
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
    apt-get install -y \
    git \
    qemu-utils \
    python3-dev \
    libssl-dev \
    ipmitool \
    python3-pip \
    python3-venv \
    vim \
    libev-dev \
    libvirt-dev \
    libffi-dev \
    libyaml-dev \
    lsb-release && \
    apt-get clean all
WORKDIR /teuthology
COPY requirements.txt requirements.yml ansible.cfg bootstrap /teuthology/
RUN \
    cd /teuthology && \
    mkdir ../archive_dir && \
    mkdir log && \
    chmod +x /teuthology/bootstrap && \
    PIP_INSTALL_FLAGS="-r requirements.txt" ./bootstrap
COPY . /teuthology
RUN \
    ./bootstrap
COPY containers/teuthology-dev/containerized_node.yaml /teuthology
COPY containers/teuthology-dev/.teuthology.yaml /root
COPY containers/teuthology-dev/teuthology.sh /
RUN \
    mkdir $HOME/.ssh && \
    touch $HOME/.ssh/id_rsa && \
    chmod 600 $HOME/.ssh/id_rsa && \
    echo "StrictHostKeyChecking=no" > $HOME/.ssh/config && \
    echo "UserKnownHostsFile=/dev/null" >> $HOME/.ssh/config
ENTRYPOINT /teuthology.sh
