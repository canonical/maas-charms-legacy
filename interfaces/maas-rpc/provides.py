# Copyright 2016-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from charms.reactive import Endpoint


class MAASRPC(Endpoint):

    def set_connection_info(self, maas_url, secret):
        """
        Set the connection information.

        :param str maas_url: The MAAS URL the rack controller should use to
            connect.
        :param str secret: The secret that should be used to authenticate
            the RPC connection.
        """
        for relation in self.relations:
            relation.to_publish_raw.update(maas_url=maas_url, secret=secret)
