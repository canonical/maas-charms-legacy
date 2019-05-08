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
    unitdata,
)
from charms import leadership
from charms.reactive import (
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


# Presistent unit data.
unit_db = unitdata.kv()


def get_maas_secret():
    """Return the MAAS secret value."""
    with open('/var/lib/maas/secret', 'r') as fp:
        return fp.read().strip()


def get_maas_url():
    maas_url = hookenv.config('maas-url')
    if maas_url:
        return maas_url
    return 'http://localhost:5240/MAAS'


def get_database_flags():
    return [
        '--database-host', unit_db.get('dbhost'),
        '--database-name', unit_db.get('dbdb'),
        '--database-user', unit_db.get('dbuser'),
        '--database-pass', unit_db.get('dbpass'),
    ]


@hook('db-relation-joined')
def db_joined(pgsql):
    set_flag('db.joined')
    hookenv.status_set('waiting', 'Requesting database from PostgreSQL')
    pgsql.change_database_name(hookenv.config('dbname'))


@hook('db-relation-departed')
def db_departed(pgsql):
    clear_flag('db.joined')
    unit_db.unset('dbhost')
    unit_db.unset('dbdb')
    unit_db.unset('dbuser')
    unit_db.unset('dbpass')


@when('maas.snap.init', 'config.changed.maas-url')
def write_maas_url():
    hookenv.status_set('maintenance', 'Re-configuring controller')
    check_call([
        'maas', 'config', '--mode', 'region',
        '--maas-url', get_maas_url()] + get_database_flags())
    hookenv.status_set('active')


@when('maas.snap.init')
@when_not_all('db.database.available', 'db.joined')
def missing_postgresql():
    hookenv.status_set('maintenance', 'Turning off controller')
    check_call(['maas', 'config', '--mode', 'none'])
    clear_flag('maas.snap.init')
    hookenv.status_set('blocked', 'Waiting on relation to PostgreSQL')


@when('maas.snap.init', 'db.database.available', 'db.joined')
def write_db_config(pgsql):
    hookenv.status_set('maintenance', 'Configuring connection to database')
    check_call([
        'maas', 'config', '--mode', 'region',
        '--maas-url', get_maas_url()] + get_database_flags())
    hookenv.status_set('active')


@when('db.database.available', 'db.joined')
@when_not('maas.snap.init')
def init_db(pgsql):
    hookenv.status_set('maintenance', 'Initializing connection to database')
    check_call([
        'maas', 'init', '--mode', 'region', '--skip-admin',
        '--maas-url', get_maas_url()] + get_database_flags())
    hookenv.status_set('active')


@when('ha.joined')
def ha_unit_joined(ha):
    unit_db.set('ha_units', ha.get_units())


@when('ha.departed')
def ha_unit_departed(ha):
    unit_db.set('ha_units', ha.get_units())


@when('rpc.rpc.requested')
def rpc_requested(rpc):
    pass
