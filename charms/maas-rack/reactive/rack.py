# Copyright 2016-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import fcntl
import os
from contextlib import contextmanager
from subprocess import (
    check_call,
    check_output,
)

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


@contextmanager
def lock_snap_context():
    """
    When both maas-region and maas-rack charms are placed on the same
    machine they need to be sure not to step over each other when
    running the commands in the snap.
    """
    fd = os.open('/tmp/maas-charm-lock', os.O_RDWR | os.O_CREAT, 600)
    fcntl.lockf(fd, fcntl.LOCK_EX)
    try:
        yield fd
    finally:
        os.close(fd)


def get_snap_config_value(*args):
    """
    Return the current mode of the snap.
    """
    output = check_output([
        'maas', 'config',
        '--show', '--show-database-password',
        '--parsable'])
    output = output.decode('utf-8')
    lines = output.splitlines()
    res = []
    for key in args:
        found = False
        for line in lines:
            line = line.strip()
            kvargs = line.split('=', 1)
            if len(kvargs) > 1 and kvargs[0] == key:
                res.append(kvargs[1])
                found = True
                break
        if not found:
            res.append(None)
    if len(res) == 1:
        return res[0]
    return res


def get_snap_mode(mode):
    """
    Return the mode the snap should change to.
    """
    current_mode = get_snap_config_value('mode')
    if mode == 'none':
        if current_mode == 'none':
            return 'none'
        if current_mode == 'rack':
            return 'none'
        if current_mode == 'region':
            return 'region'
        if current_mode == 'region+rack':
            return 'region'
        raise ValueError('Unknown operating mode: %s', current_mode)
    if mode == 'rack':
        if current_mode == 'none':
            return 'rack'
        if current_mode == 'rack':
            return 'rack'
        if current_mode == 'region':
            return 'region+rack'
        if current_mode == 'region+rack':
            return 'region+rack'
        raise ValueError('Unknown operating mode: %s', current_mode)
    raise ValueError('Unknown operating mode: %s', current_mode)


def get_snap_args(mode, secret=None, maas_urls=None):
    set_mode = get_snap_mode(mode)
    args = ['--mode', set_mode]
    if set_mode == 'region+rack':
        db_values = get_snap_config_value(
            'database_host', 'database_name', 'database_user', 'database_pass')
        args += [
            '--database-host', db_values[0],
            '--database-name', db_values[1],
            '--database-user', db_values[2],
            '--database-pass', db_values[3],
        ]
    if secret is not None and set_mode == 'rack':
        args.append('--secret')
        args.append(secret)
    if maas_urls is not None and set_mode != 'none':
        args.append('--maas-url')
        args.append(maas_urls[0])
    return args


@when('snap.installed.maas')
@when_not('endpoint.rpc.joined')
def stop_rackd():
    hookenv.status_set('blocked', 'Waiting on relation to maas-region')


@when('maas.snap.init', 'endpoint.rpc.changed')
def update_rackd_config(rpc):
    secret, maas_urls = rpc.regions()
    hookenv.status_set('maintenance', 'Configuring communication with maas-region(s)')
    with lock_snap_context():
        check_call(['maas', 'config'] + get_snap_args(
            'rack', secret, maas_urls))
    clear_flag('endpoint.rpc.changed')
    hookenv.status_set('active', 'Running')


@when('snap.installed.maas', 'endpoint.rpc.joined')
@when_not('maas.snap.init')
def update_rackd_config(rpc):
    secret, maas_urls = rpc.regions()
    hookenv.status_set('maintenance', 'Initializing rack controller')
    with lock_snap_context():
        current_mode = get_snap_config_value('mode')
        if current_mode == 'none':
            check_call(
                ['maas', 'init', '--force', '--skip-admin'] +
                get_snap_args('rack', secret, maas_urls))
        else:
            check_call(['maas', 'config'] + get_snap_args(
                'rack', secret, maas_urls))
    hookenv.status_set('active', 'Running')
    set_flag('maas.snap.init')


@when('maas.snap.init')
@when_not('endpoint.rpc.joined')
def stop_rackd():
    hookenv.status_set('maintenance', 'Stopping communcation with maas-region(s)')
    with lock_snap_context():
        check_call(['maas', 'config'] + get_snap_args('none'))
    clear_flag('maas.snap.init')


@when('maas.snap.init', 'config.set.debug')
def toggle_debug():
    hookenv.status_set('maintenance', 'Configuring debug mode')
    if hookenv.config('debug'):
        check_call([
            'maas', 'config', '--enable-debug'])
    else:
        check_call([
            'maas', 'config', '--disable-debug'])
    hookenv.status_set('active', 'Running')


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
    #        hookenv.status_set('active', 'Running')
    pass
