#!/bin/bash

function create_config() {
    local network=$1
    local subnet=$2
    local private_key=$3
    local nameserver=$4
    local labdomain=$5
    local ip=$6

    local where=$(dirname $0)

    cat > ~/.teuthology.yaml <<EOF
lock_server: http://localhost:8080/
results_server: http://localhost:8080/
queue_port: 11300
queue_host: localhost
lab_domain: $labdomain
max_job_time: 14400 # 4 hours
teuthology_path: .
openstack:
  user-data: teuthology/openstack-{os_type}-{os_version}-user-data.txt
  ip: $ip
  nameserver: $nameserver
  #
  # OpenStack has predefined machine sizes (called flavors)
  # For a given job requiring N machines, the following will select
  # the smallest flavor that satisfies these requirements. For instance
  # If there are three flavors
  #
  #   F1 (10GB disk, 2000MB RAM, 1CPU)
  #   F2 (100GB disk, 7000MB RAM, 1CPU)
  #   F3 (50GB disk, 7000MB RAM, 1CPU)
  #
  # and machine: { disk: 40, ram: 7000, cpus: 1 }, F3 will be chosen.
  # F1 does not have enough RAM (2000 instead of the 7000 minimum) and
  # although F2 satisfies all the requirements, it is larger than F3
  # (100GB instead of 50GB) and presumably more expensive.
  #
  machine:
    disk: 20 # GB
    ram: 7000 # MB
    cpus: 1
  volumes:
    count: 0
    size: 1 # GB
  ssh-key: $private_key
  clusters:
    # cluster names must be alphanumerical only (because . and - etc. are special)
    ovh:
      flavor-select-regexp: ^vps-ssd
      openrc.sh: $where/openrc.sh
      subnet: $subnet
      images:
        ubuntu-14.04: Ubuntu 14.04
        centos-7.0: Centos 7
    suse:
      openrc.sh: $where/openrc.sh
      network: $network
      subnet: $subnet
      images:
        ubuntu-14.04: ubuntu-14.04
        centos-7.0: CentOS-7-x86_64
    redhat:
      openrc.sh: $where/openrc.sh
      subnet: $subnet
      images:
        ubuntu-14.04: ubuntu-server-14.04-x86_64
        centos-7.0: Centos 7
    the-re:
      openrc.sh: $where/openrc.sh
      server-create: --availability-zone ovh:bm0014.the.re
      volume-create: --availability-zone ovh --type ovh
      network: $network
      subnet: $subnet
      images:
        ubuntu-14.04: ubuntu-trusty-14.04
        centos-7.0: centos-7
#        debian-7.0: debian-wheezy-7.1
    entercloudsuite:
      openrc.sh: $where/openrc.sh
      network: $network
      subnet: $subnet
      images:
        ubuntu-14.04: GNU/Linux Ubuntu Server 14.04 Trusty Tahr x64
        centos-7.0: GNU/Linux CentOS 7 x64
#        debian-7.0: GNU/Linux Debian 7.4 Wheezy x64
EOF
    echo "OVERRIDE ~/.teuthology.yaml"
    return 0
}

function teardown_paddles() {
    if pkill -f 'pecan' ; then
        echo "SHUTDOWN the paddles server"
    fi
}

function setup_paddles() {
    local ip=$1

    local public_ip=$(curl --silent http://169.254.169.254/2009-04-04/meta-data/public-ipv4/)
    if test -z "$public_ip" ; then
        public_ip=$ip
    fi

    local paddles_dir=$(dirname $0)/../../../../paddles

    if ! test -d $paddles_dir ; then
        git clone https://github.com/ceph/paddles.git $paddles_dir || return 1
    fi

    sudo apt-get -qq install -y beanstalkd postgresql postgresql-contrib postgresql-server-dev-all supervisor

    if ! sudo /etc/init.d/postgresql status ; then
        sudo mkdir -p /etc/postgresql
        sudo chown postgres /etc/postgresql
        sudo -u postgres pg_createcluster 9.3 paddles
        sudo /etc/init.d/postgresql start || return 1
    fi
    if ! psql --command 'select 1' 'postgresql://paddles:paddles@localhost/paddles' > /dev/null ; then
        sudo -u postgres psql -c "CREATE USER paddles with PASSWORD 'paddles';" || return 1
        sudo -u postgres createdb -O paddles paddles || return 1
    fi
    (
        cd $paddles_dir || return 1
        git pull --rebase
        git clean -ffqdx
        sed -e "s|^address.*|address = 'http://localhost'|" \
            -e "s|^job_log_href_templ = 'http://qa-proxy.ceph.com/teuthology|job_log_href_templ = 'http://$public_ip|" \
            -e "/sqlite/d" \
            -e "s|.*'postgresql+psycop.*'|'url': 'postgresql://paddles:paddles@localhost/paddles'|" \
            -e "s/'host': '127.0.0.1'/'host': '0.0.0.0'/" \
            < config.py.in > config.py
        virtualenv ./virtualenv
        source ./virtualenv/bin/activate
        pip install -r requirements.txt
        pip install sqlalchemy tzlocal requests netaddr
        python setup.py develop
    )

    echo "CONFIGURED the paddles server"
}

function populate_paddles() {
    local subnet=$1
    local openstack=$2
    local labdomain=$3

    local paddles_dir=$(dirname $0)/../../../../paddles

    local url='postgresql://paddles:paddles@localhost/paddles'

    pkill -f 'pecan serve'

    sudo -u postgres dropdb paddles
    sudo -u postgres createdb -O paddles paddles

    (
        cd $paddles_dir || return 1
        source virtualenv/bin/activate
        pecan populate config.py

        (
            echo "begin transaction;"
            subnet_names_and_ips $subnet $openstack | while read name ip ; do
                echo "insert into nodes (name,machine_type,is_vm,locked,up) values ('${name}.${labdomain}', 'openstack', TRUE, FALSE, TRUE);"
            done
            echo "commit transaction;"
        ) | psql --quiet $url

        setsid pecan serve config.py < /dev/null > /dev/null 2>&1 &
	for i in $(seq 1 20) ; do
	    if curl --silent http://localhost:8080/ > /dev/null 2>&1 ; then
		break
	    else
		echo -n .
		sleep 5
	    fi
	done
	echo -n ' '
    )

    echo "RESET the paddles server"
}

function teardown_pulpito() {
    if pkill -f 'python run.py' ; then
        echo "SHUTDOWN the pulpito server"
    fi
}

function setup_pulpito() {
    local pulpito=http://localhost:8081/

    local pulpito_dir=$(dirname $0)/../../../../pulpito

    if curl --silent $pulpito | grep -q pulpito  ; then
        echo "OK pulpito is running"
        return 0
    fi

    if ! test -d $pulpito_dir ; then
        git clone https://github.com/ceph/pulpito.git $pulpito_dir || return 1
    fi

    sudo apt-get -qq install -y nginx
    local nginx_conf=/etc/nginx/sites-available/default
    if ! grep -qq 'autoindex on' $nginx_conf ; then
        sudo perl -pi -e 's|location / {|location / { autoindex on;|' $nginx_conf
        sudo /etc/init.d/nginx restart
        echo "ADDED autoindex on to nginx configuration"
    fi
    sudo chown $USER /usr/share/nginx/html
    (
        cd $pulpito_dir || return 1
        git pull --rebase
        git clean -ffqdx
        sed -e "s|paddles_address.*|paddles_address = 'http://localhost:8080'|" < config.py.in > prod.py
        virtualenv ./virtualenv
        source ./virtualenv/bin/activate
        pip install -r requirements.txt
        python run.py &
    )

    echo "LAUNCHED the pulpito server"
}

function setup_bashrc() {
    if test -f ~/.bashrc && grep -qq '.bashrc_teuthology' ~/.bashrc ; then
        echo "OK .bashrc_teuthology found in ~/.bashrc"
    else
        local where=$(realpath $(dirname $0))
        cat > ~/.bashrc_teuthology <<EOF
source $where/openrc.sh
source $where/../../../virtualenv/bin/activate
export HISTSIZE=500000
export PROMPT_COMMAND='history -a'
EOF
        echo 'source .bashrc_teuthology' >> ~/.bashrc
        echo "ADDED .bashrc_teuthology to ~/.bashrc"
    fi
}

function setup_ssh_config() {
    if test -f ~/.ssh/config && grep -qq 'StrictHostKeyChecking no' ~/.ssh/config ; then
        echo "OK StrictHostKeyChecking disabled"
    else
        cat >> ~/.ssh/config <<EOF
Host *
  StrictHostKeyChecking no
  UserKnownHostsFile=/dev/null
EOF
        echo "DISABLED StrictHostKeyChecking"
    fi
}

function setup_bootscript() {
    local nworkers=$1

    local where=$(dirname $0)

    sudo cp -a $where/../../../openstack-teuthology.init /etc/init.d/teuthology
    echo NWORKERS=$1 | sudo tee /etc/default/teuthology > /dev/null
    echo "CREATED init script /etc/init.d/teuthology"
}

function get_or_create_keypair() {
    local keypair=$1
    local key_file=$2

    if ! openstack keypair show $keypair > /dev/null 2>&1 ; then
        openstack keypair create $keypair > $key_file || return 1
        chmod 600 $key_file
        echo "CREATED keypair $keypair"
    else
        echo "OK keypair $keypair exists"
    fi
}

function delete_keypair() {
    local keypair=$1

    if openstack keypair show $keypair > /dev/null 2>&1 ; then
        openstack keypair delete $keypair || return 1
        echo "REMOVED keypair $keypair"
    fi
}

function setup_dnsmasq() {

    if ! test -f /etc/dnsmasq.d/resolv ; then
        resolver=$(grep nameserver /etc/resolv.conf | head -1 | perl -ne 'print $1 if(/\s*nameserver\s+([\d\.]+)/)')
        sudo apt-get -qq install -y dnsmasq resolvconf
        echo resolv-file=/etc/dnsmasq-resolv.conf | sudo tee /etc/dnsmasq.d/resolv
        echo nameserver $resolver | sudo tee /etc/dnsmasq-resolv.conf
        sudo /etc/init.d/dnsmasq restart
        sudo sed -ie 's/^#IGNORE_RESOLVCONF=yes/IGNORE_RESOLVCONF=yes/' /etc/default/dnsmasq
        echo nameserver 127.0.0.1 | sudo tee /etc/resolvconf/resolv.conf.d/head
        sudo resolvconf -u
        # see http://tracker.ceph.com/issues/12212 apt-mirror.front.sepia.ceph.com is not publicly accessible
        echo host-record=apt-mirror.front.sepia.ceph.com,64.90.32.37 | sudo tee /etc/dnsmasq.d/apt-mirror
        echo "INSTALLED dnsmasq and configured to be a resolver"
    else
        echo "OK dnsmasq installed"
    fi
}

function subnet_names_and_ips() {
    local subnet=$1
    local openstack=$2
    python -c 'import netaddr; print "\n".join([str(i) for i in netaddr.IPNetwork("'$subnet'")])' |
    sed -e 's/\./ /g' | while read a b c d ; do
        printf "$openstack%03d%03d " $c $d
        echo $a.$b.$c.$d
    done
}

function define_dnsmasq() {
    local subnet=$1
    local openstack=$2
    local labdomain=$3
    local host_records=/etc/dnsmasq.d/$openstack
    if ! test -f $host_records ; then
        subnet_names_and_ips $subnet $openstack | while read name ip ; do
            echo host-record=$name.$labdomain,$ip
        done | sudo tee $host_records > /tmp/dnsmasq
        head -2 /tmp/dnsmasq
        echo 'etc.'
        sudo /etc/init.d/dnsmasq restart
        echo "CREATED $host_records"
    else
        echo "OK $host_records exists"
    fi
}

function undefine_dnsmasq() {
    local openstack=$1
    local host_records=/etc/dnsmasq.d/$openstack

    sudo rm -f $host_records
    echo "REMOVED $host_records"
}

function setup_ansible() {
    local subnet=$1
    local openstack=$2
    local labdomain=$3
    local dir=/etc/ansible/hosts
    if ! test -f $dir/$openstack ; then
        sudo mkdir -p $dir/group_vars
        echo '[testnodes]' | sudo tee $dir/$openstack
        subnet_names_and_ips $subnet $openstack | while read name ip ; do
            echo $name.$labdomain
        done | sudo tee -a $dir/$openstack > /tmp/ansible
        head -2 /tmp/ansible
        echo 'etc.'
        echo 'modify_fstab: false' | sudo tee $dir/group_vars/all.yml
        echo "CREATED $dir/$openstack"
    else
        echo "OK $dir/$openstack exists"
    fi
}

function teardown_ansible() {
    local openstack=$1

    sudo rm -fr /etc/ansible/hosts/$openstack
}

function install_packages() {

    if ! test -f /etc/apt/sources.list.d/trusty-backports.list ; then
        echo deb http://archive.ubuntu.com/ubuntu trusty-backports main universe | sudo tee /etc/apt/sources.list.d/trusty-backports.list
        sudo apt-get update
    fi

    local packages="jq realpath"
    sudo apt-get -qq install -y $packages

    echo "INSTALL required packages $packages"
}

CAT=${CAT:-cat}

function set_nameserver() {
    local subnet_id=$1
    local nameserver=$2

    eval local current_nameserver=$(neutron subnet-show -f json $subnet_id | jq '.[] | select(.Field == "dns_nameservers") | .Value'    )

    if test "$current_nameserver" = "$nameserver" ; then
        echo "OK nameserver is $nameserver"
    else
        neutron subnet-update --dns-nameserver $nameserver $subnet_id || return 1
        echo "CHANGED nameserver from $current_nameserver to $nameserver"
    fi
}

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
    echo "OK $OS_TENANT_NAME can use $OS_AUTH_URL"
    return 0
}

function main() {
    local key_file=$(dirname $0)/teuthology.pem
    local network
    local subnet
    local nameserver
    local openstack=the-re
    local labdomain=teuthology
    local nworkers=2

    local do_setup_keypair=false
    local do_create_config=false
    local do_setup_dnsmasq=false
    local do_install_packages=false
    local do_setup_paddles=false
    local do_populate_paddles=false
    local do_setup_pulpito=false
    local do_clobber=false

    while [ $# -ge 1 ]; do
        case $1 in
            --verbose)
                set -x
                PS4='${FUNCNAME[0]}: $LINENO: '
                ;;
            --key-file)
                shift
                key_file=$1
                ;;
            --nameserver)
                shift
                nameserver=$1
                ;;
            --subnet)
                shift
                subnet=$1
                ;;
            --openstack)
                shift
                openstack=$1
                ;;
            --labdomain)
                shift
                labdomain=$1
                ;;
            --nworkers)
                shift
                nworkers=$1
                ;;
            --install)
                do_install_packages=true
                ;;
            --config)
                do_create_config=true
                ;;
            --setup-keypair)
                do_setup_keypair=true
                ;;
            --setup-dnsmasq)
                do_setup_dnsmasq=true
                ;;
            --setup-paddles)
                do_setup_paddles=true
                ;;
            --setup-pulpito)
                do_setup_pulpito=true
                ;;
            --populate-paddles)
                do_populate_paddles=true
                ;;
            --setup-all)
                do_install_packages=true
                do_create_config=true
                do_setup_keypair=true
                do_setup_dnsmasq=true
                do_setup_paddles=true
                do_setup_pulpito=true
                do_populate_paddles=true
                ;;
            --clobber)
                do_clobber=true
                ;;
            *)
                echo $1 is not a known option
                return 1
                ;;
        esac
        shift
    done

    if $do_install_packages ; then
        install_packages || return 1
    fi

    verify_openstack || return 1

    case $openstack in
        ovh)
            : ${network:=unknown}
            eval local default_subnet=$(neutron subnet-list -f json | jq '.[0].cidr')
            : ${subnet:=$default_subnet}
            ;;
        redhat)
            : ${network:=unknown}
            : ${subnet:=172.16.155.0/24}
            ;;
        suse)
            : ${network:=floating}
            eval local default_subnet=$(neutron subnet-list -f json | jq '.[0].cidr')
            : ${subnet:=$default_subnet}
            ;;
        entercloudsuite)
            : ${network:=default}
            : ${subnet:=192.168.0.0/24}
            ;;
    esac

    local ip=$(ip a show dev eth0 | sed -n "s:.*inet \(.*\)/.*:\1:p")
    : ${nameserver:=$ip}

    if $do_create_config ; then
        create_config $network $subnet $key_file $nameserver $labdomain $ip || return 1
        setup_ansible $subnet $openstack $labdomain || return 1
        setup_ssh_config || return 1
        setup_bashrc || return 1
        setup_bootscript $nworkers || return 1
    fi

    if $do_setup_keypair ; then
        get_or_create_keypair teuthology $key_file || return 1
    fi

    if $do_setup_dnsmasq ; then
        setup_dnsmasq || return 1
        define_dnsmasq $subnet $openstack $labdomain || return 1
    fi

    if $do_setup_paddles ; then
        setup_paddles $ip || return 1
    fi

    if $do_populate_paddles ; then
        populate_paddles $subnet $openstack $labdomain || return 1
    fi

    if $do_setup_pulpito ; then
        setup_pulpito || return 1
    fi

    if $do_clobber ; then
        undefine_dnsmasq $openstack || return 1
        delete_keypair teuthology || return 1
        teardown_paddles || return 1
        teardown_pulpito || return 1
        teardown_ansible $openstack || return 1
    fi
}

main "$@"
