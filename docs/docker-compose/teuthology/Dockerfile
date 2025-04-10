FROM ubuntu:24.04
ARG SSH_PRIVKEY_FILE=id_ed25519
ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
RUN apt-get update && \
    apt-get install -y \
    git \
    qemu-utils \
    python3-dev \
    libssl-dev \
    ipmitool \
    pipx \
    vim \
    locales-all \
    libev-dev \
    libvirt-dev \
    libffi-dev \
    libyaml-dev \
    locales \
    lsb-release && \
    apt-get clean all && \
    locale-gen $LC_ALL
WORKDIR /teuthology
COPY pyproject.toml requirements.txt requirements.yml uv.lock ansible.cfg bootstrap /teuthology/
RUN \
    cd /teuthology && \
    mkdir ../archive_dir && \
    mkdir log && \
    chmod +x /teuthology/bootstrap && \
    ./bootstrap
COPY . /teuthology
RUN \
    ./bootstrap
COPY docs/docker-compose/teuthology/containerized_node.yaml /teuthology
COPY docs/docker-compose/teuthology/.teuthology.yaml /root
COPY docs/docker-compose/teuthology/teuthology.sh /
RUN mkdir -p /etc/ansible
COPY docs/docker-compose/teuthology/ansible_inventory/hosts /etc/ansible/
COPY docs/docker-compose/teuthology/ansible_inventory/secrets /etc/ansible/
RUN \
    mkdir $HOME/.ssh && \
    touch $HOME/.ssh/${SSH_PRIVKEY_FILE} && \
    chmod 600 $HOME/.ssh/${SSH_PRIVKEY_FILE} && \
    echo "StrictHostKeyChecking=no" > $HOME/.ssh/config && \
    echo "UserKnownHostsFile=/dev/null" >> $HOME/.ssh/config
ENTRYPOINT /teuthology.sh
