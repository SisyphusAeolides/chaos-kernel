# COPR packaging

This directory contains the Fedora dist-git packaging used to build Chaos
Kernel in COPR.

Download the source archives from Fedora's lookaside cache:

```sh
fedpkg --name kernel --namespace rpms --path packaging/copr sources
```

Create a source RPM:

```sh
builddir=$(mktemp -d)
rpmbuild -bs packaging/copr/kernel.spec \
  --define "_topdir $builddir" \
  --define "_sourcedir $PWD/packaging/copr" \
  --define "_srcrpmdir $builddir"
```

Submit the source RPM to every chroot enabled in the `chaos-kernel` COPR
project:

```sh
copr-cli build chaos-kernel "$builddir"/*.src.rpm
```
