# Chaos Kernel

**Chaos Kernel** is a Linux kernel experiment that applies bounded nonlinear
dynamics at carefully selected subsystem control points. The design keeps
expensive math and shared mutable state out of hot paths.

## Subsystems

1. **Entropy (`drivers/char/random.c`)**: stateless nonlinear conditioning
   without entropy credit or shared-state contention.
2. **OOM (`mm/oom_kill.c`)**: atomic free-page trajectory divergence sensing.
3. **CORE scheduler (`kernel/sched/fair.c`)**: bounded logistic-map wakeup
   placement using an existing `sched_entity` padding hole and no tick cost.
4. **TCP (`net/ipv4/tcp_roessler.c`)**: Reno-compatible Rössler modulation
   bounded to conventional additive-increase and loss-response ranges.
5. **Block I/O (`block/blk-mq.c`)**: optional per-CPU Duffing-guided plug
   bypass for synchronous reads; disabled by default.

## Architecture

The production implementation is maintained as six reviewable kernel patches
under `packaging/copr/` and applied directly by the RPM spec. `chaos-math/` is
a `no_std` Rust reference implementation with the same fixed-point behavior.

The complete reproducible Fedora/CentOS/EPEL packaging lives in
`packaging/copr/`.
