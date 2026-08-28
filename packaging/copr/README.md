# COPR packaging

This directory contains the Fedora dist-git packaging used to build Chaos
Kernel in COPR.

The numbered eight-patch series is the canonical kernel implementation. The
RPM spec applies each patch directly after Fedora's downstream patch. The math
core includes bounded fixed-point Logistic, Lorenz, Rössler, Duffing,
Mandelbrot, Lyapunov, and divergence routines.

The build enables CORE and the `tcp_roessler` module. CORE can be toggled at
runtime through `/sys/kernel/debug/sched/features` using `CHAOS_CORE` or
`NO_CHAOS_CORE`. Duffing-guided block plug bypass is intentionally disabled by
default and can be enabled with the `blk_mq.chaos_bypass_shift` kernel-module
parameter for controlled benchmarking.

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
