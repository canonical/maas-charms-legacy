# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from subprocess import CalledProcessError

from charms.reactive import (
    hook,
    RelationBase,
    scopes,
)


class MAASRegionPeers(RelationBase):
    scope = scopes.UNIT

    @hook('{peers:maas-region-ha}-relation-joined')
    def joined(self):
        conv = self.conversation()
        conv.remove_state('{relation_name}.departed')
        conv.set_state('{relation_name}.joined')

    @hook('{peers:maas-region-ha}-relation-departed')
    def departed(self):
        conv = self.conversation()
        conv.remove_state('{relation_name}.joined')
        conv.set_state('{relation_name}.departed')

    def get_units(self):
        try:
            return {
                conv.scope: conv.get_remote('private-address')
                for conv in self.conversations()
            }
        except CalledProcessError:
            # Possible that when remove the service that self.conversations
            # raises this exception.
            return {}
