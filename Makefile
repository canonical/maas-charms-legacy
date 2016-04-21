# `charm build` needs the paths to INTERFACES and LAYERS.
export INTERFACE_PATH := $(CURDIR)/interfaces
export LAYER_PATH := $(CURDIR)/layers

all: build

install-dependencies:
	sudo DEBIAN_FRONTEND=noninteractive apt-get -y \
		--no-install-recommends install charm-tools

build: maas-region maas-rack


maas-region:
	charm build -s xenial maas-region -o .

maas-rack:
	charm build -s xenial maas-rack -o .

test: build test-maas-region test-maas-rack

test-maas-region:
	charm proof xenial/maas-region

test-maas-rack:
	charm proof xenial/maas-rack
