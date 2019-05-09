# MAAS (Metal as a Service) Charms

Juju charms that allow deploying both the MAAS region controller and MAAS rack
controller.

The MAAS region controller is the main communication point for MAAS. Users and
tools communicate over the API and UI frontend to control machines and devices.
The following services are installed and setup with the maas-region charm:

* bind9
* maas-proxy
* maas-regiond
* ntp

The MAAS rack controller is where BMC's for machines are controller where the
machines PXE boot, download images, and contact for DHCP. The following
services are installed and setup with the maas-rack charm:

* bind9 (proxy to region's)
* maas-dhcpd
* maas-dhcpd6
* maas-http (proxy to region's)
* maas-proxy (proxy to region's)
* maas-rackd
* ntp

For more information see [MAAS]((https://maas.io)).

## Building

Install the pre-requisites.

```
sudo apt install make
make install-dependencies
```

Check out the repository and simply run `make`.

```
git clone https://github.com/maas/maas-charms
cd maas-charms
make
```

## Deployment

Only external requirement for running MAAS is a PostgreSQL database.

```
juju deploy postgresql
juju deploy ./builds/maas-region
juju deploy ./builds/maas-rack
juju add-relation maas-region postgesql:db
juju add-relation maas-region maas-rack
```

## Scale out Usage

MAAS internally handles the HA configuration and strategy so its as simple
as scaling out the regions and racks.

`juju add-unit maas-region -n 1`
`juju add-unit maas-rack -n 1`

## Known Limitations and Issues

*Not production ready*

# Configuration

*TODO*
