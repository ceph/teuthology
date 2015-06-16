#!/bin/bash

function create_config() {
    local openstack=$1
    local network=$2
    local subnet=$3
    local private_key=$4

    local where=$(dirname $0)

    case $openstack in
	the-re)
	    cat > ~/.teuthology.yaml <<EOF
lock_server: http://localhost:8080/
queue_port: 11300
queue_host: localhost
canonicalize_hostname: false
teuthology_path: .
results_server:
openstack:
  user-data:
    ubuntu-12.04: teuthology/openstack-ubuntu-user-data.txt
    ubuntu-14.04: teuthology/openstack-ubuntu-user-data.txt
    centos-7.0: teuthology/openstack-centos-7-user-data.txt
  default-size:
    disk-size: 10
    ram: 1024
    cpus: 1
  default-volumes:
    count: 1
    size: 1
  ssh-key: $private_key
  clusters:
    the-re:
      openrc.sh: $where/openrc.sh
      server-create: --availability-zone ovh
      volume-create: --availability-zone ovh --type ovh
      network: $network
      subnet: $subnet
      images:
        ubuntu-12.04: ubuntu-12.04.4
        ubuntu-14.04: ubuntu-trusty-14.04
        centos-7.0: centos-7
EOF
	    ;;
	*)
	    echo unknown OpenStack cluster, no integration tests can be run >&2
	    return 1
	    ;;
    esac
    return 0
}

function setup_paddles() {
    local openstack=$1
    local paddles=http://localhost:8080/

    if curl --silent $paddles | grep -q paddles  ; then
	return 0
    fi

    if ! test -d ../paddles ; then
	git clone https://github.com/ceph/paddles.git ../paddles
    fi

    sudo apt-get -qq install -y sqlite3

    ( 
	cd ../paddles
	git pull --rebase
	git clean -ffqdx
	perl -p -e "s|^address.*|address = 'http://localhost'|" < config.py.in > config.py
	virtualenv ./virtualenv
	source ./virtualenv/bin/activate
	pip install -r requirements.txt
	pip install sqlalchemy tzlocal requests
	python setup.py develop
	pecan populate config.py
	for id in $(seq 10 30) ; do
	    sqlite3 dev.db "insert into nodes (id,name,machine_type,is_vm,locked,up) values ($id, '${openstack}0$id', 'openstack', 1, 0, 1);"
	done
	pecan serve config.py &
    )
}

PRIVATE_KEY=${PRIVATE_KEY:-$(dirname $0)/teuthology.pem}

function get_or_create_keypair() {
    local private_key=$1

    if ! openstack keypair show teuthology > /dev/null 2>&1 ; then
	openstack keypair create teuthology > $private_key
	chmod 600 $private_key
    fi
}

NAMESERVER=${NAMESERVER:-$(ip a | perl -ne 'print $1 if(/.*inet\s+('${SUBNET%.0/24}'.\d+)/)')}

function setup_dnsmasq() {
    sudo apt-get -qq install -y dnsmasq

    if ! test -f /etc/dnsmasq.d/resolv ; then
	echo resolv-file=/etc/dnsmasq-resolv.conf | sudo tee /etc/dnsmasq.d/resolv
	echo nameserver 8.8.8.8 | sudo tee /etc/dnsmasq-resolv.conf
	sudo /etc/init.d/dnsmasq restart
    fi
}

function define_dnsmasq() {
    local subnet=$1
    local openstack=$2
    local prefix=${subnet%.0/24}
    if ! test -f /etc/dnsmasq.d/$openstack ; then
	for i in $(seq 1 254) ; do
	    echo host-record=$(printf $openstack%03d $i),$prefix.$i
	done | sudo tee /etc/dnsmasq.d/$openstack
	sudo /etc/init.d/dnsmasq restart
    fi
}

function install_packages() {
    if ! test -f /etc/apt/sources.list.d/trusty-backports.list ; then
	echo deb http://archive.ubuntu.com/ubuntu trusty-backports main universe | sudo tee /etc/apt/sources.list.d/trusty-backports.list
	sudo apt-get update
    fi

    sudo apt-get -qq install -y libssl-dev libffi-dev libyaml-dev jq ipcalc
}

CAT=${CAT:-cat}

NETWORK=${NETWORK:-teuthology-test}

function get_or_create_network() {
    local network=$1
    local id=$(openstack network list -f json | $CAT | jq '.[] | select(.Name == "'$network'") | .ID')
    if test -z "$id" ; then
	id=$(openstack network create -f json $network | $CAT | jq '.[] | select(.Field == "id") | .Value')
	eval neutron net-show $id
    fi
    eval echo $id
}
    
SUBNET=${SUBNET:-10.50.50.0/24}

function get_or_create_subnet() {
    local network=$1
    local subnet=$2
    local nameserver=$3
    local network_id=$(get_or_create_network $network)
    
    local id=$(neutron subnet-list -f json | $CAT | jq '.[] | select(.cidr == "'$subnet'") | .id')
    if test -z "$id" ; then
	id=$(neutron subnet-create -f json --no-gateway --dns-nameserver $nameserver --enable-dhcp $network_id $subnet | grep -v 'Created a new subnet' | $CAT | jq '.[] | select(.Field == "id") | .Value')
	eval neutron subnet-show $id
    fi

    eval echo $id
}

EXTERNAL_NETWORK=${EXTERNAL_NETWORK:-ovh}
ROUTER=${ROUTER:-teuthology}

function get_or_create_router() {
    local subnet=$1
    local external_network=$2
    local router=$3

    if ! neutron router-show $router 2>/dev/null ; then
	neutron router-create $router
	neutron router-interface-add $router $subnet
	neutron router-gateway-set $router $external_network
    fi
}

OPENSTACK=${OPENSTACK:-the-re}

function verify_openstack() {
    local openrc=$(dirname $0)/openrc.sh
    if ! test -f $openrc ; then
	echo ERROR: download OpenStack credentials in $openrc >&2
	return 1
    fi
    source $openrc
    if ! openstack server list > /dev/null ; then
	echo ERROR: the credentials from $openrc are not working >&2
	return 1
    fi
    return 0
}

function main() {
    create_config $OPENSTACK $NETWORK $SUBNET $PRIVATE_KEY || return 1
    return 0
    verify_openstack || return 1
    setup_dnsmasq
    install_packages
    local network_id=$(get_or_create_network $NETWORK)
    local subnet_id=$(get_or_create_subnet $NETWORK $SUBNET $NAMESERVER)
    get_or_create_router $subnet_id ${EXTERNAL_NETWORK} ${ROUTER}
    get_or_create_keypair $PRIVATE_KEY
    define_dnsmasq $SUBNET $OPENSTACK
    setup_paddles $OPENSTACK
}

main

# CAT='tee /dev/tty' SUBNET=10.50.7.0/24 NETWORK=trahsme OPENSTACK=thrashme bash -x setup-openstack.sh
