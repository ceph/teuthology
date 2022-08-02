#!/usr/bin/bash
set -x
cat /run/secrets/id_rsa.pub >> /root/.ssh/authorized_keys
cat /run/secrets/id_rsa.pub >> /home/ubuntu/.ssh/authorized_keys
chown ubuntu /home/ubuntu/.ssh/authorized_keys
payload="{\"name\": \"$(hostname)\", \"machine_type\": \"testnode\", \"up\": true, \"locked\": false, \"os_type\": \"centos\", \"os_version\": \"8.stream\"}"
for i in $(seq 1 5); do
    echo "attempt $i"
    curl -v -f -d "$payload" http://paddles:8080/nodes/ && break
    sleep 1
done
mkdir -p /run/sshd
exec /usr/sbin/sshd -D
