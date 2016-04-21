# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from charms.reactive import RelationBase
from charms.reactive import scopes
from charms.reactive import hook
from charms.reactive import not_unless


class MAASRPC(RelationBase):
    scope = scopes.GLOBAL

    @hook('{provides:maas-rpc}-relation-{changed,joined}')
    def changed_joined(self):
        self.set_state('{relation_name}.rpc.requested')

    @hook('{provides:maas-rpc}-relation-{departed,broken}')
    def departed_broken(self):
        self.remove_state('{relation_name}.rpc.requested')

    @not_unless('{provides:maas-rpc}.rpc.requested')
    def set_connection_info(self, maas_url, secret):
        """
        Set the connection information.

        :param str maas_url: The MAAS URL the rack controller should use to
            connect.
        :param str secret: The secret that should be used to authenticate
            the RPC connection.
        """
        self.set_remote(maas_url=maas_url, secret=secret)
        self.remove_state('{relation_name}.rpc.requested')
