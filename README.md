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
5. **Block I/O (`block/blk-mq.c`)**: optional per-CPU Duffing-guided plug
   bypass for synchronous reads; disabled by default.

## Architecture

The production implementation is maintained as nine reviewable kernel patches
under `packaging/copr/` and applied directly by the RPM spec. `chaos-math/` is
a `no_std` Rust reference implementation with the same fixed-point behavior.

## Kernel portability

These are in-tree patches and cannot be universal across arbitrary Linux
releases: scheduler, block, random, TCP, and cgroup internals change between
kernel families. The canonical RPM series is pinned to its kernel-ark base and
must be applied strictly there.

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

The complete reproducible Fedora/CentOS/EPEL packaging lives in
`packaging/copr/`.
