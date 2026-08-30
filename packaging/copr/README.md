# COPR packaging

This directory contains the Fedora dist-git packaging used to build Chaos
Kernel in COPR.

The numbered patch series is the canonical kernel implementation. The CLK
6.12.104 RPM spec applies the reviewed CIQ port after the downstream source
patches. The math core includes bounded fixed-point Logistic, Lorenz, Rössler,
Duffing, Mandelbrot, Lyapunov, and divergence routines.

The legacy RPM series in `kernel.spec` remains pinned to its kernel-ark base.
The current CIQ package in `clk612/kernel-clk6.12.spec` targets the running
CLK 6.12.104 source layout. Neither series is a universal patch for arbitrary
Linux trees. Check another tree first:

```sh
./apply-chaos-patches.sh --check --strict /path/to/linux
```

For a disposable tree, best-effort mode applies only compatible patches and
skips unsupported features together with their dependents:

```sh
./apply-chaos-patches.sh --best-effort --apply /path/to/linux
```

New kernel families need a reviewed source port and a compile/test matrix
before all subsystems can be enabled.

The CLK 6.12 build permanently compiles the bounded chaos math and enables
CORE, built-in Rössler TCP as the default congestion controller, and the
bounded Duffing block path. CORE can still be disabled for recovery through
`/sys/kernel/debug/sched/features` with `NO_CHAOS_CORE`; the block path can be
disabled with `blk_mq.chaos_bypass_shift=0`. These are bounded defaults, not a
promise that every workload will benchmark faster; measure latency and
throughput on the target machine.

The CIQ source archive is obtained from the CIQ kernel source package and is
included in the source RPM submitted to COPR. It is not committed to this
repository.

Download the legacy Fedora source archives from Fedora's lookaside cache:

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

For the CIQ CLK 6.12 build, place
`linux-6.12.104-1.1.el9.tar.zst` beside the files in `clk612/`, then build
`clk612/kernel-clk6.12.spec` into a self-contained source RPM. The large
archive is intentionally not tracked by Git.
```
