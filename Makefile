
all: build

build:
	@$(MAKE) -C charms

clean:
	@rm -rf builds

install-dependencies:
	sudo snap install charm --classic

.PHONY: all build install-dependencies
