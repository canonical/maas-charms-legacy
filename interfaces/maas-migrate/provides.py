# Copyright 2016-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from charms.reactive import Endpoint


class MAASMigrate(Endpoint):

    def set_db_info(self, dbhost, dbname, dbuser, dbpassword):
        """
        Set the database connection information.
        """
        for relation in self.relations:
            relation.to_publish_raw.update(
                dbhost=dbhost,
                dbname=dbname,
                dbuser=dbuser,
                dbpassword=dbpassword)
