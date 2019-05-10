# Copyright 2016-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from charms.reactive import Endpoint


class MAASMigrateClient(Endpoint):

    def db_connection(self):
        """
        Get the database connection string from the other region controller.
        """
        for unit in self.all_joined_units:
            dbhost = unit.received['dbhost']
            dbname = unit.received['dbname']
            dbuser = unit.received['dbuser']
            dbpassword = unit.received['dbpassword']
            if not (dbhost and dbname and dbuser and dbpassword):
                continue
            return (dbhost, dbname, dbuser, dbpassword)
        return None, None, None, None
