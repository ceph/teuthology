FROM quay.io/centos/centos:stream9
RUN dnf -y install \
    sudo \
    openssh-server \
    hostname \
    python3-pip \
    httpd \
    podman && \
    dnf clean all
COPY testnode_start.sh /
COPY testnode_stop.sh /
COPY testnode_sudoers /etc/sudoers.d/teuthology
RUN \
    ssh-keygen -t rsa -f /etc/ssh/ssh_host_rsa_key -N '' && \
    sed -i 's/#PermitRootLogin yes/PermitRootLogin yes/' /etc/ssh/sshd_config && \
    mkdir -p /root/.ssh && \
    chmod 700 /root/.ssh && \
    groupadd sudo && \
    useradd -g sudo ubuntu && \
    mkdir -p /home/ubuntu/.ssh && \
    chmod 700 /home/ubuntu/.ssh && \
    chown -R ubuntu /home/ubuntu
EXPOSE 22
ENTRYPOINT /testnode_start.sh
