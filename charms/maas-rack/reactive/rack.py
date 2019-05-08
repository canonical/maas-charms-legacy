# Copyright 2016-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from subprocess import check_call

from charmhelpers.core import (
    hookenv,
    host,
)
from charms.reactive import (
    clear_flag,
    hook,
    set_flag,
    when,
    when_not,
)


@when('snap.installed.maas', 'rpc.rpc.available', 'maas.snap.init')
def update_rackd_config(rpc):
    rpc_maas_url = rpc.maas_url()
    if rpc_maas_url is None:
        rpc_maas_url = ''
    rpc_secret = rpc.secret()
    if rpc_secret is None:
        rpc_secret = ''
    hookenv.status_set('maintenance', 'Configuring communcation with maas-region(s)')
    check_call([
        'maas', 'config',
        '--mode', 'rack',
        '--maas-url', rpc_maas_url,
        '--secret', rpc_secret])
    hookenv.status_set('active')


@when('snap.installed.maas', 'rpc.rpc.available')
@when_not('maas.snap.init')
def update_rackd_config(rpc):
    rpc_maas_url = rpc.maas_url()
    if rpc_maas_url is None:
        rpc_maas_url = ''
    rpc_secret = rpc.secret()
    if rpc_secret is None:
        rpc_secret = ''
    hookenv.status_set('maintenance', 'Initializing rack controller')
    check_call([
        'maas', 'init',
        '--mode', 'rack',
        '--maas-url', rpc_maas_url,
        '--secret', rpc_secret])
    hookenv.status_set('active')
    set_flag('maas.snap.init')


@when('snap.installed.maas')
@when_not('rpc.rpc.available')
def stop_rackd():
    hookenv.status_set('maintenance', 'Stopping communcation with maas-region(s)')
    check_call([
        'maas', 'config', '--mode', 'none'])
    clear_flag('maas.snap.init')
    hookenv.status_set('blocked', 'Waiting on relation to maas-region')


@when('maas.snap.init', 'config.set.debug')
def toggle_debug():
    hookenv.status_set('maintenance', 'Configuring debug mode')
    check_call([
        'maas', 'config', '--debug', hookenv.config('debug')])
    hookenv.status_set('active')


@hook('update-status')
def update_status():
    """Called by Juju to update the status of the service."""
    ## Only update the status if running. The reset of the time the other hooks
    ## set the correct state.
    #running = unit_db.get('running', False)
    #if running:
    #    # Keep rackd running.
    #    if not host.service_running('maas-rackd'):
    #        host.service_restart('maas-rackd')

    #    # Update status using the dhcpd services.
    #    dhcpd_running = host.service_running('maas-dhcpd')
    #    dhcpd6_running = host.service_running('maas-dhcpd6')
    #    if dhcpd_running and dhcpd6_running:
    #        hookenv.status_set('active', 'Providing DHCPv4 and DHCPv6')
    #    elif dhcpd_running:
    #        hookenv.status_set('active', 'Providing DHCPv4')
    #    elif dhcpd6_running:
    #        hookenv.status_set('active', 'Providing DHCPv6')
    #    else:
    #        hookenv.status_set('active', 'Ready')
    pass
