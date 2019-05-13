# Copyright 2016-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from charms.reactive import clear_flag, Endpoint, hook, set_flag, when, when_not


class MAASRPCClient(Endpoint):

    @when('endpoint.{endpoint_name}.joined')
    def joined(self):
        self.toggle_available()

    @when_not('endpoint.{endpoint_name}.joined')
    def not_joined(self):
        self.toggle_available()

    def toggle_available(self):
        """Sets that the relationship is available."""
        secret, urls = self.regions()
        if secret and len(urls) > 0:
            set_flag(self.expand_name('{endpoint_name}.available'))
        else:
            clear_flag(self.expand_name('{endpoint_name}.available'))

    def regions(self):
        """
        Get the list of region controller remote units have published the
        relationships connected to this endpoint.

        Returns tuple with the secret as the first entry in the tuple, and the
        second entry being the list of region controller MAAS URLs.\
        """
        secret = None
        regions = set()
        #
        # Multiple relations can connect to the same endpoint. All relations
        # of the same endpoint will be handled by the same Endpoint
        # class.
        #
        # Loop over all units of all relations connected to this enpoint,
        # read the port and hostname they published, add them to a dict and
        # return that information.
        for unit in self.all_joined_units:
            unit_maas_url = unit.received['maas_url']
            unit_secret = unit.received['secret']
            if not (unit_maas_url and unit_secret):
                continue
            if secret is None:
                secret = unit_secret
            if secret != unit_secret:
                continue
            regions.add(unit_maas_url)
        return (secret, list(regions))
