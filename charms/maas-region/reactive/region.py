# Copyright 2016-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import ipaddress
import json
import os
from functools import partial
from subprocess import (
    CalledProcessError,
    check_call,
    check_output,
)
import yaml

from charmhelpers import fetch
from charmhelpers.core import (
    hookenv,
    host,
    sysctl,
    templating,
)
from charms import leadership
from charms.reactive import (
    endpoint_from_flag,
    hook,
    when,
    when_any,
    when_not,
    when_not_all,
    when_file_changed,
    set_state,
    set_flag,
    clear_flag,
)


def get_maas_secret():
    """Return the MAAS secret value."""
    with open('/var/snap/maas/current/var/lib/maas/secret', 'r') as fp:
        return fp.read().strip()


def get_maas_url():
    maas_url = hookenv.config('maas-url')
    if maas_url:
        return maas_url
    return 'http://localhost:5240/MAAS'


def is_maas_url_local(maas_url):
    if maas_url == 'http://localhost:5240/MAAS':
        return True
    return False


def get_database_flags(pgsql):
    conn_str = pgsql.master
    return [
        '--database-host', conn_str['host'],
        '--database-name', conn_str['dbname'],
        '--database-user', conn_str['user'],
        '--database-pass', conn_str['password'],
    ]


def perform_migrate():
    host, dbname, user, password = endpoint_from_flag(
        'endpoint.migrate-in.joined').db_connection()
    print('%s - %s - %s - %s' % (host, dbname, user, password))
    import time
    time.sleep(180)


@when('snap.installed.maas')
@when_not('maas.snap.init', 'db.database.available')
def missing_postgresql():
    hookenv.status_set('blocked', 'Waiting on relation to PostgreSQL')


@when('maas.snap.init', 'config.changed.maas-url')
@when_not_all('endpoint.migrate-out.joined', 'endpoint.migrate-in.joined')
def write_maas_url():
    hookenv.status_set('maintenance', 'Re-configuring controller')
    check_call([
        'maas', 'config', '--mode', 'region',
        '--maas-url', get_maas_url()] + get_database_flags(
            endpoint_from_flag('db.database.available')))
    hookenv.status_set('active')


@when('maas.snap.init')
@when_not('db.database.available')
def disable_snap():
    hookenv.status_set('maintenance', 'Turning off controller')
    check_call(['maas', 'config', '--mode', 'none'])
    clear_flag('maas.snap.init')


@when('maas.snap.init', 'db.database.available', 'db.master.changed')
@when_not_all('endpoint.migrate-out.joined', 'endpoint.migrate-out.joined')
def write_db_config(pgsql):
    hookenv.status_set('maintenance', 'Configuring connection to database')
    check_call([
        'maas', 'config', '--mode', 'region',
        '--maas-url', get_maas_url()] + get_database_flags(pgsql))
    clear_flag('db.master.changed')
    hookenv.status_set('active', 'Running')


@when('snap.installed.maas', 'db.database.available', 'db.master.changed')
@when_not_all('maas.snap.init', 'endpoint.migrate-out.joined')
def init_db(_, pgsql):
    hookenv.status_set('maintenance', 'Initializing connection to database')
    check_call([
        'maas', 'init', '--force', '--mode', 'region', '--skip-admin',
        '--maas-url', get_maas_url()] + get_database_flags(pgsql))
    set_flag('maas.snap.init')
    clear_flag('db.master.changed')
    hookenv.status_set('active', 'Running')


@when('maas.snap.init', 'endpoint.rpc.joined')
def rpc_requested(rpc):
    maas_url = get_maas_url()
    if is_maas_url_local(maas_url):
        maas_url = 'http://%s:5240/MAAS' % hookenv.unit_private_ip()
    secret = get_maas_secret()
    rpc.set_connection_info(maas_url, secret)


@when('endpoint.migrate-out.joined', 'endpoint.migrate-in.joined')
def migrate_both_error():
    hookenv.status_set('blocked', 'Cannot have relations migrate-out and migrate-in at the same time')


@when('endpoint.migrate-out.joined')
@when_not('maas.snap.init')
def migrate_out_not_init():
    hookenv.status_set(
        'blocked',
        'Migration out blocked; region must have been initialized '
        '(remove relation to continue)')


@when('endpoint.migrate-out.joined', 'db.database.available', 'maas.snap.init')
def migrate_out_set_database_info_and_stop(migrate, pgsql):
    conn_str = pgsql.master
    migrate.set_db_info(
        conn_str['host'], conn_str['dbname'],
        conn_str['user'], conn_str['password'])
    hookenv.status_set(
        'maintenance',
        'Migrating state from this region (remove relation when complete)')


@when('maas.snap.init')
@when_not('endpoint.migrate-out.joined')
def migrate_out_start_snap():
    hookenv.status_set('active', 'Running')


@when('endpoint.migrate-in.joined', 'db.database.available', 'maas.snap.init')
def migrate_in_is_running():
    host.service_stop('snap.maas.supervisor')
    set_flag('maas.migrate.ready')


@when('endpoint.migrate-in.joined', 'db.database.available', 'snap.installed.maas')
@when_not('maas.snap.init')
def migrate_in_not_init():
    set_flag('maas.migrate.ready')


@when('maas.migrate.ready', 'leadership.is_leader')
def migrate_in_perform():
    hookenv.status_set('maintenance', 'Migrating state to this region')
    perform_migrate()        
    hookenv.status_set('blocked', 'SUCCESS - Migration to this region complete (remove relation)')
    clear_flag('maas.migrate.ready')
    set_flag('maas.migrate.done')


@when('maas.migrate.ready')
@when_not('leadership.is_leader')
def migrate_in_wait():
    hookenv.status_set('blocked', 'Waiting on leader to complete migration')
    

@when('maas.migrate.done', 'maas.snap.init')
def migrate_in_done():
    host.service_start('snap.maas.supervisor')
    clear_flag('maas.migrate.done')
    hookenv.status_set('active', 'Running')


@when('maas.migrate.done', 'db.database.available')
@when_not('maas.snap.init')
def migrate_in_done_no_init(pgsql):
    clear_flag('maas.migrate.done')


@when('maas.snap.init', 'endpoint.http.joined')
def http_connected(http):
    http.configure(5240)
