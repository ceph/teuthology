FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt update && \
    apt -y install \
        sudo \
        openssh-server \
        hostname \
        curl \
        python3-pip \
        apache2 \
        nfs-kernel-server && \
    apt clean all
COPY testnode_start.sh /
COPY testnode_stop.sh /
COPY testnode_sudoers /etc/sudoers.d/teuthology
RUN \
    ssh-keygen -t dsa -f /etc/ssh/ssh_host_dsa_key -N '' && \
    sed -i 's/#PermitRootLogin yes/PermitRootLogin yes/' /etc/ssh/sshd_config && \
    mkdir -p /root/.ssh && \
    chmod 700 /root/.ssh && \
    useradd -g sudo ubuntu && \
    mkdir -p /home/ubuntu/.ssh && \
    chmod 700 /home/ubuntu/.ssh && \
    chown -R ubuntu /home/ubuntu
EXPOSE 22
ENTRYPOINT /testnode_start.sh
