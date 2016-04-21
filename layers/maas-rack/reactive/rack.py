# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import os
from subprocess import (
    check_call,
    check_output,
)

from charmhelpers import fetch
from charmhelpers.core import (
    hookenv,
    host,
    unitdata,
)
from charms.reactive import (
    hook,
    when,
    when_not,
)


# Presistent unit data.
unit_db = unitdata.kv()


# Ports to mark as open when in ready state.
ports = [
    # DHCP
    (67, 'UDP'),
    (68, 'UDP'),
    # TFTP
    (69, 'TCP'),
    (69, 'UDP'),
    # HTTP
    (5248, 'TCP'),
    # ISCSI
    (860, 'TCP'),
    (3260, 'TCP'),
]


def open_ports():
    """Tells Juju about the open ports."""
    ports_opened = unit_db.get('ports_opened', False)
    if ports_opened:
        return
    for port, protocol in ports:
        hookenv.open_port(port, protocol)
    unit_db.set('ports_opened', True)


def close_ports():
    """Removes opened ports from Juju."""
    ports_opened = unit_db.get('ports_opened', False)
    if not ports_opened:
        return
    for port, protocol in ports:
        hookenv.close_port(port, protocol)
    unit_db.unset('ports_opened')


@hook('install')
def install_rack():
    # Place in maintenance.
    hookenv.status_set('maintenance', '')

    # Add the ppa source if provided in config.
    ppa_source = hookenv.config('ppa')
    if ppa_source:
        hookenv.status_set('maintenance', 'Enabling PPA')
        fetch.add_source(ppa_source)

    # Update the sources and install the required packages.
    hookenv.status_set('maintenance', 'Installing packages')
    fetch.apt_update()
    fetch.apt_install([
        'maas-dhcp',
        'maas-rack-controller'])

    # Possible re-install remove rackd.conf.
    if os.path.exists('/etc/maas/rackd.conf'):
        os.remove('/etc/maas/rackd.conf')

    # Install should have rackd off.
    host.service_stop('maas-rackd')


@when('rpc.rpc.available')
def update_rackd_config(rpc):
    maas_url = unit_db.get('maas_url')
    rpc_maas_url = rpc.maas_url()
    if rpc_maas_url is None:
        rpc_maas_url = ''
    if maas_url is None or maas_url != rpc_maas_url:
        hookenv.status_set('maintenance', 'Writing maas_url into rackd.conf')
        check_call(['maas-rack', 'config', '--region-url', rpc_maas_url])
        unit_db.set('maas_url', rpc_maas_url)
    secret = unit_db.get('secret')
    rpc_secret = rpc.secret()
    if rpc_secret is None:
        rpc_secret = ''
    if secret is None or secret != rpc_secret:
        hookenv.status_set('maintenance', 'Writing secret into /var/lib/maas/')
        check_output(
            ['maas-rack', 'install-shared-secret'],
            input=rpc_secret.encode('ascii'))
        unit_db.set('secret', rpc_secret)
    if rpc_maas_url:
        # Valid maas_url then we are running.
        if not host.service_running('maas-rackd'):
            host.service_restart('maas-rackd')
        else:
            # maas-rackd will acutally pick this up automatically and does not
            # needs to be reloaded or restarted.
            pass
        open_ports()
        unit_db.set('running', True)
        update_status()
    else:
        # Invalid maas_url so we are no longer running.
        stop_rackd()


@when_not('rpc.rpc.available')
def stop_rackd():
    hookenv.status_set('waiting', 'Waiting on relation to maas-region')
    host.service_stop('maas-rackd')
    close_ports()
    unit_db.unset('running')


@hook('update-status')
def update_status():
    """Called by Juju to update the status of the service."""
    # Only update the status if running. The reset of the time the other hooks
    # set the correct state.
    running = unit_db.get('running', False)
    if running:
        # Keep rackd running.
        if not host.service_running('maas-rackd'):
            host.service_restart('maas-rackd')

        # Update status using the dhcpd services.
        dhcpd_running = host.service_running('maas-dhcpd')
        dhcpd6_running = host.service_running('maas-dhcpd6')
        if dhcpd_running and dhcpd6_running:
            hookenv.status_set('active', 'Providing DHCPv4 and DHCPv6')
        elif dhcpd_running:
            hookenv.status_set('active', 'Providing DHCPv4')
        elif dhcpd6_running:
            hookenv.status_set('active', 'Providing DHCPv6')
        else:
            hookenv.status_set('active', 'Ready')
