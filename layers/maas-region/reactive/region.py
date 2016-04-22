# Copyright 2016 Canonical Ltd.  This software is licensed under the
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
    when_file_changed,
    set_state,
    remove_state,
)


# Presistent unit data.
unit_db = unitdata.kv()

# Global config options
global_configs = [
    ('maas-name', 'maas_name', 'string'),
    ('main-archive', 'main_archive', 'string'),
    ('ports-archive', 'ports_archive', 'string'),
    ('enable-http-proxy', 'enable_http_proxy', 'boolean'),
    ('http-proxy', 'http_proxy', 'string'),
    ('upstream-dns', 'upstream_dns', 'string'),
    ('dnssec-validation', 'dnssec_validation', 'string'),
    ('ntp-server', 'ntp_server', 'string'),
    ('default-storage-layout', 'default_storage_layout', 'string'),
    (
     'enable-disk-erasing-on-release',
     'enable_disk_erasing_on_release', 'boolean'),
    ('curtin-verbose', 'curtin_verbose', 'boolean'),
]

# Ports to mark as open when in ready state.
ports = [
    # DNS
    (53, 'TCP'),
    (53, 'UDP'),
    # API and WebUI
    (80, 'TCP'),
    # RPC
    (5250, 'TCP'),
    (5251, 'TCP'),
    (5252, 'TCP'),
    (5253, 'TCP'),
    # Proxy
    (8000, 'TCP'),
]


def is_valid_ip(ip):
    """Return True if `ip` is valid."""
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return False
    else:
        return True


def get_ip_version(ip):
    """Return the IP version of the `ip`."""
    return ipaddress.ip_address(ip).version


def allows_ip_nonlocal_bind(ip_version):
    """Return True if `ip_nonlocal_bind` for the IP version is allowed."""
    with open('/proc/sys/net/ipv%d/ip_nonlocal_bind' % ip_version, 'r') as fp:
        return int(fp.read().strip()) == 1


def is_in_container():
    """Return True if running in container."""
    try:
        check_call(['systemd-detect-virt', '-c', '-q'])
    except CalledProcessError:
        return False
    else:
        return True


def get_filtered_ip_addr():
    """Return filtered ip addr information."""
    # python3-maas-provisioningserver will be installed before this function
    # is called.
    from provisioningserver.utils.ipaddr import get_ip_addr
    return {
        name: ipaddr
        for name, ipaddr in get_ip_addr().items()
        if (ipaddr['type'] not in ['loopback', 'ipip'] and
            not ipaddr['type'].startswith('unknown-'))
    }


def get_interface_for_ip(ip_address):
    """Return the name of the interface that has a subnet that `ip_address`
    belongs."""
    ip_version = get_ip_version(ip_address)
    ip_address = ipaddress.ip_address(ip_address)
    inet = "inet"
    if ip_version == 6:
        inet = "inet6"
    ipaddr_info = get_filtered_ip_addr()
    for name, ipaddr in ipaddr_info.items():
        for address in ipaddr.get(inet, []):
            if ip_address in ipaddress.ip_network(address, strict=False):
                hookenv.log(
                    "Found interface %s for VIP %s." % (name, ip_address))
                return name
    sorted_interfaces = sorted(ipaddr_info.keys())
    if len(sorted_interfaces) > 0:
        hookenv.log(
            "Unable to find specific interface for VIP %s; "
            "selected %s instead." % (ip_address, sorted_interfaces[0]))
        return sorted_interfaces[0]
    else:
        raise ValueError(
            "Unable to identify interface for VIP %s." % ip_address)


def unit_has_ip(ip_address):
    """Return True if the unit has the `ip_address` on any interface."""
    ip_version = get_ip_version(ip_address)
    ip_address = ipaddress.ip_address(ip_address)
    inet = "inet"
    if ip_version == 6:
        inet = "inet6"
    ipaddr_info = get_filtered_ip_addr()
    for name, ipaddr in ipaddr_info.items():
        for address in ipaddr.get(inet, []):
            if '/' in address:
                address = address.split('/')[0]
            if ip_address == ipaddress.ip_address(address):
                return True
    return False


def lsmod():
    """Return a list of loaded kernel modules."""
    output = check_output(['lsmod']).decode('utf-8')
    return [
        line.split()[0]
        for line in output.splitlines()
    ]


def is_module_loaded(module):
    """Return True if module is loaded."""
    modules = lsmod()
    return module in modules


def is_blocked_by_missing_module(module):
    """Check if blocked by the fact 'ip_vs' module is not loaded and also
    running in a container."""
    return not is_module_loaded(module) and is_in_container()


def get_regiond_config_value(name):
    """Return the configuration value for `name`."""
    arg_name = name.replace('_', '-')
    conf_settings = json.loads(
        check_output([
            'maas-region', 'local_config_get',
            '--json', '--%s' % arg_name]).decode('ascii'))
    return conf_settings.get(name)


def regiond_ready_to_run():
    """Return True if database_pass set in regiond.conf."""
    dbpass = get_regiond_config_value('database_pass')
    return (
        dbpass is not None and
        len(dbpass) > 0 and
        not dbpass.isspace())


def get_maas_secret():
    """Return the MAAS secret value."""
    with open('/var/lib/maas/secret', 'r') as fp:
        return fp.read().strip()


def get_apikey():
    """Return the API key for the admin user."""
    apikey = leadership.leader_get('apikey')
    if not apikey:
        apikey = check_output([
            'maas-region', 'apikey',
            '--username', leadership.leader_get('admin_username')])
        apikey = apikey.decode('ascii').strip()
        leadership.leader_set(apikey=apikey)
    return apikey


def update_config_value(charm_name, maas_name, value_type="string"):
    """Update the global config values."""
    if not hookenv.is_leader():
        # Only the leader updates config values.
        return
    admin_username = leadership.leader_get('admin_username')
    if not admin_username:
        # Value can only be set once an administrator has been created.
        return

    # Ensure logged into API.
    check_call([
        'maas', 'login', 'juju-admin',
        'http://localhost:5240/MAAS', get_apikey()])

    # Get the current value.
    result = check_output([
        'maas', 'juju-admin', 'maas', 'get-config', 'name=%s' % maas_name])
    result = result.decode("utf-8")
    if value_type == "boolean":
        if result == "true":
            result = True
        else:
            result = False

    # Update the value if its different.
    new_value = hookenv.config(charm_name)
    if result != new_value:
        check_call([
            'maas', 'juju-admin', 'maas',
            'set-config', 'name=%s' % maas_name, 'value=%s' % new_value])


def set_all_global_configs():
    """Set all global configs.

    Called after the administrator is first created.
    """
    hookenv.status_set('maintenance', 'Setting all global config options')
    for charm_name, maas_name, value_type in global_configs:
        update_config_value(charm_name, maas_name, value_type)


def update_admin(old_username, username, email, password):
    env = os.environ.copy()
    env['DJANGO_SETTINGS_MODULE'] = 'maas.settings'
    env['PYTHONPATH'] = '/usr/share/maas'
    check_call([
        'python3', 'scripts/update_user.py',
        '--old-username', old_username,
        '--username', username,
        '--email', email,
        '--password', password], env=env)


def is_vip_valid():
    vip = hookenv.config('vip')
    if not vip:
        return True
    elif is_valid_ip(vip):
        ip_version = get_ip_version(vip)
        if is_blocked_by_missing_module('ip_vs'):
            hookenv.status_set(
                'blocked',
                'Kernel module ip_vs is not loaded and cannot be loaded when '
                'in a container')
            return False
        else:
            return True
    else:
        hookenv.status_set(
            'blocked', 'Config vip invalid; not valid IP address')
        host.service_stop('maas-regiond')
        close_ports()
        return False


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
def install_region():
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
        'haproxy',
        'maas-cli',
        'maas-dns',
        'maas-region-api'])

    # Stop and disable apache2. Charm uses haproxy.
    # maas-region-api should not depend on apache2.
    host.service_stop('apache2')
    host.service('disable', 'apache2')

    # Possible re-install remove regiond.conf.
    if os.path.exists('/etc/maas/regiond.conf'):
        os.remove('/etc/maas/regiond.conf')

    # Install should have regiond off.
    host.service_stop('maas-regiond')

    # Configure haproxy.
    configure_haproxy()


@hook('config-changed')
def update_global_configs():
    config = hookenv.config()
    for charm_name, maas_name, value_type in global_configs:
        if config.changed(charm_name):
            update_config_value(charm_name, maas_name, value_type)


@hook('db-relation-joined')
def db_joined(pgsql):
    # psql layer does not handle departing correctly. We set
    # db_joined so the write_db_config is not skipped.
    unit_db.set('db_joined', True)
    hookenv.status_set('waiting', 'Requesting database from PostgreSQL')
    pgsql.change_database_name(hookenv.config('dbname'))


@hook('db-relation-departed')
def db_departed(pgsql):
    # psql layer does not handle departing correctly. We clear
    # db_joined so the write_db_config is skipped.
    unit_db.unset('db_joined')
    unit_db.unset('dbhost')
    unit_db.unset('dbdb')
    unit_db.unset('dbuser')
    unit_db.unset('dbpass')
    check_call([
        'maas-region', 'local_config_set',
        '--database-host', '',
        '--database-name', '',
        '--database-user', '',
        '--database-pass', '',
        ])
    close_ports()
    host.service_stop('maas-regiond')
    hookenv.status_set('waiting', 'Waiting on relation to PostgreSQL')


@when_any('config.changed.maas-url', 'config.changed.vip')
def write_maas_url():
    hookenv.status_set('maintenance', 'Writing maas_url into regiond.conf')
    vip = hookenv.config('vip')
    maas_url = hookenv.config('maas-url')
    if vip:
        if not is_valid_ip(vip):
            url = ''
        else:
            url = 'http://%s/MAAS' % vip
    elif maas_url:
        url = maas_url
    else:
        url = 'http://localhost/MAAS'
    check_call([
        'maas-region', 'local_config_set',
        '--maas-url', url,
        ])
    start_regiond_when_ready()


@when_not('db.database.available')
def missing_postgresql():
    close_ports()
    host.service_stop('maas-regiond')
    hookenv.status_set('waiting', 'Waiting on relation to PostgreSQL')


@when('db.database.available')
def write_db_config(pgsql):
    # Do nothing if not db joined.
    if not unit_db.get('db_joined', False):
        return

    # Update the database configuration only if any of the configuration
    # values have changed. Nothing needs to be done if nothing has changed.
    dbhost = pgsql.host()
    dbdb = pgsql.database()
    dbuser = pgsql.user()
    dbpass = pgsql.password()
    has_changed = (
        unit_db.get('dbhost') != dbhost or
        unit_db.get('dbdb') != dbdb or
        unit_db.get('dbuser') != dbuser or
        unit_db.get('dbpass') != dbpass)
    if has_changed:
        unit_db.set('dbhost', dbhost)
        unit_db.set('dbdb', dbdb)
        unit_db.set('dbuser', dbuser)
        unit_db.set('dbpass', dbpass)
        hookenv.status_set(
            'maintenance', 'Writing db configuration into regiond.conf')

        check_call([
            'maas-region', 'local_config_set',
            '--database-host', dbhost if dbhost else '',
            '--database-name', dbdb if dbdb else '',
            '--database-user', dbuser if dbuser else '',
            '--database-pass', dbpass if dbpass else '',
            ])
        if all([dbhost, dbdb, dbuser, dbpass]):
            start_regiond_when_ready()
        else:
            host.service_stop('maas-regiond')
            hookenv.status_set('waiting', 'Waiting on relation to PostgreSQL')


@when_any(
    'config.changed.haproxy-stats-enabled',
    'config.changed.haproxy-stats-uri',
    'config.changed.haproxy-stats-auth')
def configure_haproxy():
    """Write /etc/haproxy/haproxy.conf and reload haproxy."""
    ha_units = unit_db.get('ha_units')
    if ha_units is None:
        ha_units = {}
    templating.render('haproxy.cfg', '/etc/haproxy/haproxy.cfg', {
        'stats_enabled': hookenv.config('haproxy-stats-enabled'),
        'stats_uri': hookenv.config('haproxy-stats-uri'),
        'stats_auth': hookenv.config('haproxy-stats-auth'),
        'unit_name': hookenv.local_unit(),
        'unit_address': hookenv.unit_private_ip(),
        'ha_units': ha_units,
    })


@when_any(
    'config.changed.admin-username',
    'config.changed.admin-email',
    'config.changed.admin-password')
def configure_admin_user():
    """Configure administrator user."""
    if hookenv.is_leader():
        username = hookenv.config('admin-username')
        email = hookenv.config('admin-email')
        password = hookenv.config('admin-password')
        if username and email and password:
            admin_username = leadership.leader_get('admin_username')
            if admin_username:
                # Change the admin username, email, and password.
                hookenv.status_set('maintenance', 'Leader: updating admin')
                update_admin(admin_username, username, email, password)
                leadership.leader_set(admin_username=username)
            else:
                # Create the admin user.
                hookenv.status_set('maintenance', 'Leader: creating admin')
                check_call([
                    'maas-region', 'createadmin',
                    '--username', username,
                    '--email', email,
                    '--password', password,
                ])
                leadership.leader_set(admin_username=username)

            # Update the state.
            update_state()


@when('ha.joined')
def ha_unit_joined(ha):
    unit_db.set('ha_units', ha.get_units())
    configure_haproxy()


@when('ha.departed')
def ha_unit_departed(ha):
    unit_db.set('ha_units', ha.get_units())
    configure_haproxy()


@when('leadership.changed.running_migrations')
@when_file_changed('/etc/maas/regiond.conf')
def start_regiond_when_ready():
    # Prevent regiond from running if vip is invalid.
    if not is_vip_valid():
        return

    # Only start regiond if migrations are not running and regiond
    # is ready to run.
    running_migrations = leadership.leader_get('running_migrations')
    running_migrations = running_migrations == 'True'
    if running_migrations:
        if not hookenv.is_leader():
            hookenv.status_set(
                'waiting', 'Waiting for leader to finish migrations')
            host.service_stop('maas-regiond')
    elif regiond_ready_to_run():
        if hookenv.is_leader():
            # Leader of the service and run migrations if needed.
            migrations_ran = leadership.leader_get('migrations_ran')
            migrations_ran = migrations_ran == 'True'
            if not migrations_ran:
                # XXX 2016-04-18 blake_r: Should detect if a new version of
                # MAAS requires migrations to be ran again.
                hookenv.status_set('maintenance', 'Leader: running migrations')
                host.service_stop('maas-regiond')
                leadership.leader_set(running_migrations='True')
                check_call(['maas-region', 'dbupgrade'])
                leadership.leader_set(
                    running_migrations='', migrations_ran='True')
        else:
            # Not the leader and migrations aren't being run, regiond
            # can start.
            hookenv.status_set('maintenance', 'Restarting regiond')

        # Update any RPC relations with the new maas_url.
        maas_url = get_regiond_config_value('maas_url')
        if maas_url and maas_url != unit_db.get('rpc_maas_url', None):
            send_maas_url = maas_url
            if maas_url == "http://localhost/MAAS" and hookenv.is_leader():
                # MAAS url on the region is set to localhost so we tell the
                # rack to connect over the private address.
                send_maas_url = "http://%s/MAAS" % hookenv.unit_private_ip()
            for relation_id in hookenv.relation_ids('rpc'):
                hookenv.relation_set(relation_id, {'maas_url': send_maas_url})
            unit_db.set('rpc_maas_url', maas_url)

        # Restart regiond so its has the latest configuration.
        host.service_restart('maas-regiond')
        update_state()


@when_file_changed('/etc/haproxy/haproxy.conf')
def reload_haproxy():
    if host.service_running('haproxy'):
        hookenv.status_set(
            'maintenance', 'Reloading haproxy')
        host.service_reload('haproxy')
    else:
        hookenv.status_set(
            'maintenance', 'Starting haproxy')
        host.service_restart('haproxy')
    update_state()


@when_any(
    'config.changed.vip',
    'leadership.changed.admin_username')
def update_state():
    # If VIP is set it needs to be correct before doing anything else.
    if not is_vip_valid():
        close_ports()
        return

    # We need to have a working haproxy and regiond before going forward.
    running_migrations = leadership.leader_get('running_migrations')
    running_migrations = running_migrations == 'True'
    if (running_migrations or
            not regiond_ready_to_run() or
            not host.service_running('maas-regiond') or
            not host.service_running('haproxy')):
        close_ports()
        return

    # The DNS options need to be migrated before continuing.
    dns_migrated = unit_db.get('dns_migrated', False)
    if not dns_migrated:
        hookenv.status_set('maintenance', 'Migrating DNS options')
        check_call([
            'maas-region', 'edit_named_options',
            '--migrate-conflicting-options'])
        host.service_restart('bind9')
        unit_db.set('dns_migrated', True)

    # Make sure that administrator user has been created.
    admin_username = leadership.leader_get('admin_username')
    if not admin_username:
        if hookenv.is_leader():
            hookenv.status_set(
                'blocked', 'Missing admin config')
        else:
            hookenv.status_set(
                'waiting', 'Waiting for leader to configure admin account')
        return

    # Set all global configs if never done.
    if hookenv.is_leader():
        set_global_configs = leadership.leader_get('set_global_configs')
        set_global_configs = set_global_configs == 'True'
        if not set_global_configs:
            set_all_global_configs()
            leadership.leader_set(set_global_configs='True')

    # Mark that the ports are open.
    open_ports()

    # If not VIP is set then the leader unit is the primary.
    vip = hookenv.config('vip')
    if vip:
        # Determine leader by looking for VIP.
        if unit_has_ip(vip):
            hookenv.status_set(
                'active', 'Primary DNS and balancing HTTP (VIP: %s)' % vip)
        else:
            hookenv.status_set('active', 'Secondary DNS and balancing HTTP')
    else:
        # Leader is determined by Juju.
        if hookenv.is_leader():
            hookenv.status_set('active', 'Primary DNS and balancing HTTP')
        else:
            hookenv.status_set('active', 'Secondary DNS and balancing HTTP')


@when_any(
    'config.changed.vip',
    'config.changed.keepalived-router-id',
    'leadership.changed.keepalived_pass')
def update_vip_config():
    vip = hookenv.config('vip')
    if vip:
        # If VIP is invalid and keepalived was running stop it and remove
        # the configuration.
        if not is_vip_valid() and unit_db.get('keepalived_running', False):
            host.service_stop('keepalived')
            if os.path.exists('/etc/keepalived/keepalived.conf'):
                os.remove('/etc/keepalived/keepalived.conf')
            return

        # Using VIP configuration; setup keepalived.
        keepalived_installed = unit_db.get('keepalived_installed', False)
        if not keepalived_installed:
            # Check to see if keepalived needs to be installed.
            packages = fetch.filter_installed_packages(['keepalived'])
            if len(packages) > 0:
                fetch.apt_update()
                fetch.apt_install(packages)
            unit_db.set('keepalived_installed', True)

        # Load the ip_vs module if needed.
        module_loaded = False
        if not is_module_loaded('ip_vs') and not is_in_container():
            check_call(['modprobe', 'ip_vs'])
            module_loaded = True

        # Enable ip_nonlocal_bind if needed.
        ip_version = get_ip_version(vip)
        if not allows_ip_nonlocal_bind(ip_version):
            sysctl.create(yaml.dump({
                "net.ipv%s.ip_nonlocal_bind" % ip_version: 1
            }), "/etc/sysctl.d/50-maas-region-nonlocal.conf")
            host.service_start("procps")

        # Get the keepalived password.
        keepalived_pass = leadership.leader_get('keepalived_pass')
        if not keepalived_pass:
            if hookenv.is_leader():
                # keepalived maximum length is 8 characters
                keepalived_pass = host.pwgen(length=8)
                leadership.leader_set(keepalived_pass=keepalived_pass)
            else:
                hookenv.status_set(
                    'waiting',
                    'Waiting on leader for keepalived authentication password')
                return

        # Get the interface that should be used for the VIP.
        interface = get_interface_for_ip(vip)

        # Write the keepalived.conf. The priority is set based on the unit
        # number. Juju starts unit numbers at 0 where keepalived starts at 1,
        # so the unit number is increased by 1 for every unit.
        templating.render(
            'keepalived.conf', '/etc/keepalived/keepalived.conf', {
                'interface': interface,
                'priority': int(hookenv.local_unit().split('/')[1]) + 1,
                'virtual_router_id': hookenv.config('keepalived-router-id'),
                'auth_pass': keepalived_pass,
                'vip': vip,
            })

        # Restart keepalived if stopped or the kernel module was loaded,
        # otherwise just reload the config.
        if host.service_running('keepalived') and not module_loaded:
            host.service_reload('keepalived')
        else:
            host.service_restart('keepalived')
        unit_db.set('keepalived_running', True)

    elif unit_db.get('keepalived_running', False):
        # Keepalived is running stop it and remove the config.
        host.service_stop('keepalived')
        os.remove('/etc/keepalived/keepalived.conf')

    update_state()


@when('rpc.rpc.requested')
def rpc_requested(rpc):
    if regiond_ready_to_run():
        maas_url = get_regiond_config_value('maas_url')
        unit_db.set('rpc_maas_url', maas_url)
        rpc.set_connection_info(
            maas_url, get_maas_secret())
