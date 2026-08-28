# Chaos Kernel

**Chaos Kernel** is a fork/patchset for the mainline Linux kernel that weaves non-linear dynamics and chaos theory into the core subsystems.

## Subsystems

1. **Entropy (`drivers/char/random.c`)**: Logistic Map chaotic PRNG.
2. **OOM Killer (`mm/oom_kill.c`)**: Lyapunov Exponent trajectory separation for deterministic OOM prediction.
3. **Scheduler (`kernel/sched/`)**: Lorenz & Rössler attractors for bounded, non-linear task scheduling.
4. **TCP Congestion (`net/ipv4/tcp_cong.c`)**: Rössler attractor dynamics for congestion window sizing.
5. **I/O Queueing (`block/blk-mq.c`)**: Duffing oscillator for non-linear queue depth absorption.

## Architecture

The mathematical heavy lifting is implemented in the `chaos-math/` Rust crate (compiled as `no_std` for kernel space), which exposes a C ABI to be wired directly into the Linux kernel source tree.
