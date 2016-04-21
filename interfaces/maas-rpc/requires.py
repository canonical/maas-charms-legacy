from charms.reactive import RelationBase
from charms.reactive import hook
from charms.reactive import scopes


class MAASRPCClient(RelationBase):
    scope = scopes.GLOBAL

    # These remote data fields will be automatically mapped to accessors
    # with a basic documentation string provided.
    auto_accessors = ['maas_url', 'secret']

    @hook('{requires:maas-rpc}-relation-{changed,joined}')
    def changed_joined(self):
        if all([self.maas_url(), self.secret()]):
            self.set_state('{relation_name}.rpc.available')

    @hook('{provides:maas-rpc}-relation-{departed,broken}')
    def departed_broken(self):
        self.remove_state('{relation_name}.rpc.available')
