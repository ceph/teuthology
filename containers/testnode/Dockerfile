FROM quay.io/centos/centos:stream9
RUN dnf -y update && \
    dnf -y reinstall shadow-utils && \
    dnf -y install podman fuse-overlayfs --exclude container-selinux
RUN useradd podman; \
    echo podman:0:5000 > /etc/subuid; \
    echo podman:0:5000 > /etc/subgid; \
    echo root:0:65535 > /etc/subuid; \
    echo root:0:65535 > /etc/subgid;
RUN mkdir -p /root/.local/share/containers /home/podman/.local/share/containers
VOLUME /var/lib/containers
VOLUME /home/podman/.local/share/containers
VOLUME /root/.local/share/containers
ADD https://raw.githubusercontent.com/containers/libpod/master/contrib/podmanimage/stable/containers.conf /etc/containers/containers.conf
ADD https://raw.githubusercontent.com/containers/libpod/master/contrib/podmanimage/stable/podman-containers.conf /home/podman/.config/containers/containers.conf
ADD https://raw.githubusercontent.com/containers/podman/main/contrib/podmanimage/stable/podman-containers.conf /root/.config/containers/containers.conf
RUN chown podman:podman -R /home/podman; \
    echo 'podman:podman' | chpasswd
RUN chmod 644 /etc/containers/containers.conf; \
    sed -i -e 's|^#mount_program|mount_program|g' -e '/additionalimage.*/a "/var/lib/shared",' -e 's|^mountopt[[:space:]]*=.*$|mountopt = "nodev,fsync=0"|g' /etc/containers/storage.conf
RUN mkdir -p /var/lib/shared/overlay-images /var/lib/shared/overlay-layers /var/lib/shared/vfs-images /var/lib/shared/vfs-layers; \
    touch /var/lib/shared/overlay-images/images.lock; \
    touch /var/lib/shared/overlay-layers/layers.lock; \
    touch /var/lib/shared/vfs-images/images.lock; \
    touch /var/lib/shared/vfs-layers/layers.lock
ENV _CONTAINERS_USERNS_CONFIGURED=""

RUN dnf -y install \
    sudo \
    openssh-server \
    hostname \
    python3-pip \
    httpd \
    systemd && \
    systemctl enable sshd
RUN dnf clean all && \
    rm -rf /var/cache /var/log/dnf* /var/log/yum*
COPY testnode_start.sh /
COPY testnode_stop.sh /
COPY testnode_sudoers /etc/sudoers.d/teuthology
COPY run-fs.service scratch-devs.service /etc/systemd/system/
RUN systemctl enable run-fs scratch-devs
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
