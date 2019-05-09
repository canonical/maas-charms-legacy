# Copyright 2016-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from charms.reactive import Endpoint


class MAASRPCClient(Endpoint):

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
