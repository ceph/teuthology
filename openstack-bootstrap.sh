#!/bin/bash

if ! nova list ; then
    echo "unable to run 'nova list', verify openrc.sh has been sourced" >&2
    exit 1
fi

case "$1" in
    ovh)
        image='Ubuntu 14.04'
        flavor='vps-ssd-1'
        ;;
    entercloudsuite)
        image='GNU/Linux Ubuntu Server 14.04 LTS Trusty Tahr x64'
        flavor='e1standard.x2'
	net_id=$(nova net-list | grep default | cut -f2 -d' ')
	nic="--nic net-id=$net_id"
        ;;
    redhat)
        ;;
    suse)
        ;;
    *)
        exit 1
        ;;
esac

user_data=$(dirname $0)/openstack-user-data.txt

if nova keypair-list | grep -qq teuthology-admin && test -f $HOME/teuthology-admin ; then
    echo "Using keypair teuthology-admin"
else
    nova keypair-add teuthology-admin > $HOME/teuthology-admin
    chmod 600 $HOME/teuthology-admin
fi

nova boot --image "$image" --flavor "$flavor" $nic --key-name teuthology-admin --user-data <(sed -e "s|OPENRC|$(env | grep OS_ | tr '\n' ' ')|" < $user_data) teuthology

echo 'Wait a minute, run nova list to figure out the public IP of the instance.'
echo 'Run: '
echo '  ssh $IP -i $HOME/teuthology-admin tail -n 2000000 -f /tmp/init.out'
echo 'to verify the integration tests were successfull'
