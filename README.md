# Chaos Kernel

**Chaos Kernel** is a Linux kernel experiment that applies bounded nonlinear
dynamics at carefully selected subsystem control points. The design keeps
expensive math and shared mutable state out of hot paths.

## Subsystems

1. **Entropy (`drivers/char/random.c`)**: stateless nonlinear conditioning
   without entropy credit or shared-state contention.
2. **OOM (`mm/oom_kill.c`)**: Lyapunov trajectory growth and Mandelbrot escape
   sensing over atomic free-page observations.
3. **CORE scheduler (`kernel/sched/fair.c`)**: bounded logistic-map and Lorenz
   wakeup placement using an existing `sched_entity` padding hole and no tick cost.
4. **TCP (`net/ipv4/tcp_roessler.c`)**: Reno-compatible Rössler modulation
   bounded to conventional additive-increase and loss-response ranges.
5. **Block I/O (`block/blk-mq.c`)**: per-CPU Duffing-guided plug bypass for
   synchronous reads, enabled with a bounded default and disableable with
   `blk_mq.chaos_bypass_shift=0`.

## Architecture

The production implementation is maintained as reviewable kernel patches
under `packaging/copr/` and applied directly by the RPM spec. The CIQ CLK
6.12.104 port is in `packaging/copr/clk612/`; it applies the common math,
OOM, and TCP patches plus the reviewed 6.12 scheduler, random, block, and
memory-observation port. `chaos-math/` is a `no_std` Rust reference
implementation with the same fixed-point behavior.

## Kernel portability

These are in-tree patches and cannot be universal across arbitrary Linux
releases: scheduler, block, random, TCP, and cgroup internals change between
kernel families. The runner selects the reviewed CLK 6.12 series for a 6.12
source tree and the legacy series for older trees; both are strict by default.
An unfamiliar kernel family must receive its own reviewed port before it can
claim full feature coverage.

Use the fail-closed runner to inspect another source tree before applying it:

```sh
packaging/copr/apply-chaos-patches.sh --check --strict /path/to/linux
```

For a disposable tree, `--best-effort --apply` applies only patches whose
prerequisites and source anchors match, and skips incompatible features rather
than forcing rejects or fuzz:

```sh
packaging/copr/apply-chaos-patches.sh --best-effort --apply /path/to/linux
```

Full feature parity on a new kernel family requires a reviewed port and a
kernel build/test pass for that family. A successful best-effort run is not a
claim that every subsystem was enabled.

## Chaos Kernel Manager

The manager follows a check, configure, build, review, and install workflow.
It operates on a disposable copy of a stock Linux tree, applies only
compatible patches, and never changes the supplied source tree, unloads a
driver, installs a kernel, or reboots the host automatically. The default
performance preset enables the complete bounded feature set: CORE, built-in
Rössler TCP as the default congestion controller, and the bounded Duffing
block path. The packaged CLK 6.12 build also merges these defaults through
`packaging/copr/clk612/kernel-local`. The block path can be disabled for
recovery or comparison with `blk_mq.chaos_bypass_shift=0`.

Check portability first:

```sh
tools/chaos-kernel-builder.py check --source /path/to/linux --policy strict
```

Build a native kernel RPM from a compatible tree (best-effort is useful when a
kernel family has moved internal APIs):

```sh
tools/chaos-kernel-builder.py build \
  --source /path/to/linux \
  --policy best-effort \
  --package rpm
```

Open the GTK manager:

```sh
tools/chaos-kernel-builder.py --gui
```

The manager also lists installed `/boot/vmlinuz-*` entries, selects a default
entry through `grubby`, launches `menuconfig`/`nconfig`/`xconfig`/`gconfig`,
and installs a reviewed RPM or Debian artifact set. The equivalent CLI actions
are:

```sh
tools/chaos-kernel-builder.py status
tools/chaos-kernel-builder.py set-default --kernel /boot/vmlinuz-<version>
tools/chaos-kernel-builder.py install \
  --artifacts ~/Projects/chaos-kernel-build/artifacts --format rpm
```

Build output is placed below `~/Projects/chaos-kernel-build` by default. The
manager refuses to overwrite an existing run and writes a `build.json` record
with the selected policy, features, patch results, and produced artifacts.
Review that manifest and the installed-kernel list before rebooting.

The complete reproducible Fedora/CentOS/EPEL packaging lives in
`packaging/copr/`. The CIQ source archive is intentionally supplied to the
source-RPM/COPR build rather than committed to Git because it is a large
downstream archive.
