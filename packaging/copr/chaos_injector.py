import os, sys

def modify_file(filepath, hook, injection, insert_after=True):
    with open(filepath, 'r') as f:
        content = f.read()
    if hook in content:
        if insert_after:
            content = content.replace(hook, hook + "\n" + injection)
        else:
            content = content.replace(hook, injection + "\n" + hook)
        with open(filepath, 'w') as f:
            f.write(content)
        print(f"Successfully injected into {filepath}")
    else:
        print(f"FAILED to find hook in {filepath}: {hook}")

# 1. Entropy
modify_file("drivers/char/random.c", "#include <linux/uuid.h>", "#include <linux/chaos_math.h>")
modify_file("drivers/char/random.c", "static void add_timer_randomness", "static s64 chaos_logistic_state = (1LL << 32) / 2;\nstatic s64 chaos_logistic_r = 17137209139LL;\n", insert_after=False)
modify_file("drivers/char/random.c", "unsigned int bits;", "\tchaos_logistic_state = chaos_logistic_map_step(chaos_logistic_r, chaos_logistic_state);\n\tentropy ^= (unsigned long)chaos_logistic_state;")

# 2. OOM
modify_file("mm/oom_kill.c", "#include <linux/oom.h>", "#include <linux/chaos_math.h>")
modify_file("mm/oom_kill.c", "bool out_of_memory(struct oom_control *oc)", "#define CHAOS_OOM_HISTORY_LEN 8\nstatic s64 oom_history[CHAOS_OOM_HISTORY_LEN];\nstatic int oom_history_idx = 0;\n", insert_after=False)
oom_injection = """
	s64 lyapunov, current_free;
	current_free = CHAOS_TO_Q32(global_zone_page_state(NR_FREE_PAGES));
	oom_history[oom_history_idx] = current_free;
	oom_history_idx = (oom_history_idx + 1) % CHAOS_OOM_HISTORY_LEN;
	lyapunov = chaos_lyapunov_exponent(oom_history, CHAOS_OOM_HISTORY_LEN);
	if (lyapunov > CHAOS_TO_Q32(5)) {
		pr_emerg("Chaos Kernel: Positive Lyapunov exponent detected! Impending memory collapse!\\n");
	}
"""
modify_file("mm/oom_kill.c", "unsigned long freed = 0;", oom_injection)

# 3. I/O Block
modify_file("block/blk-mq.c", "#include <linux/blkdev.h>", "#include <linux/chaos_math.h>")
modify_file("block/blk-mq.c", "void blk_mq_submit_bio(struct bio *bio)", "static s64 duffing_x = 0;\nstatic s64 duffing_v = 0;\nstatic s64 duffing_t = 0;\n", insert_after=False)
blk_injection = """
	s64 dt = CHAOS_TO_Q32(1) / 100;
	chaos_duffing_step(CHAOS_TO_Q32(1)/10, CHAOS_TO_Q32(1), CHAOS_TO_Q32(1)/2, CHAOS_TO_Q32(2), CHAOS_TO_Q32(1), &duffing_x, &duffing_v, duffing_t, dt);
	duffing_t += dt;
	if (duffing_v > CHAOS_TO_Q32(5)) {
		bio->bi_opf |= REQ_NOWAIT;
	}
"""
modify_file("block/blk-mq.c", "void blk_mq_submit_bio(struct bio *bio)\n{", blk_injection)

# 4. Sched
modify_file("include/linux/sched.h", "struct load_weight		h_load;", "\ts64\t\t\t\tcore_chaos_state;\n\ts64\t\t\t\tcore_burst_r;")
modify_file("kernel/sched/fair.c", "#include <linux/interrupt.h>", "#include <linux/chaos_math.h>")

update_curr_injection = """
	if (unlikely(delta_exec <= 0))
		return;

	if (curr->core_chaos_state == 0) {
		curr->core_chaos_state = CHAOS_TO_Q32(1)/2;
		curr->core_burst_r = 17137209139LL;
	}
	if (curr->core_burst_r > 12884901888LL) {
		curr->core_burst_r -= delta_exec * 10;
		if (curr->core_burst_r < 12884901888LL)
			curr->core_burst_r = 12884901888LL;
	}
	curr->core_chaos_state = chaos_logistic_map_step(curr->core_burst_r, curr->core_chaos_state);
	if (curr->core_burst_r > 15000000000LL) {
		curr->vruntime -= (delta_exec * (curr->core_chaos_state >> 32)) / 2;
	}
"""
with open("kernel/sched/fair.c", "r") as f:
    fc = f.read()
fc = fc.replace("\tif (unlikely(delta_exec <= 0))\n\t\treturn;\n", update_curr_injection, 1)

place_entity_injection = """static void
place_entity(struct cfs_rq *cfs_rq, struct sched_entity *se, int flags)
{
	if (flags) {
		se->core_burst_r = 17137209139LL;
	}
"""
fc = fc.replace("static void\nplace_entity(struct cfs_rq *cfs_rq, struct sched_entity *se, int flags)\n{", place_entity_injection)
with open("kernel/sched/fair.c", "w") as f:
    f.write(fc)
print("Successfully injected into kernel/sched/fair.c")


# 5. Core Math
with open("include/linux/chaos_math.h", "w") as f:
    f.write("""#ifndef _LINUX_CHAOS_MATH_H
#define _LINUX_CHAOS_MATH_H

#include <linux/types.h>

#define CHAOS_Q32_ONE (1LL << 32)
#define CHAOS_TO_Q32(x) ((s64)((x) * CHAOS_Q32_ONE))
#define CHAOS_FROM_Q32(x) ((x) / (double)CHAOS_Q32_ONE)

extern s64 chaos_logistic_map_step(s64 r, s64 x);
extern void chaos_lorenz_step(s64 sigma, s64 rho, s64 beta, s64 *x, s64 *y, s64 *z, s64 dt);
extern void chaos_roessler_step(s64 a, s64 b, s64 c, s64 *x, s64 *y, s64 *z, s64 dt);
extern void chaos_duffing_step(s64 delta, s64 alpha, s64 beta, s64 gamma, s64 omega, s64 *x, s64 *v, s64 t, s64 dt);
extern s64 chaos_lyapunov_exponent(const s64 *trajectory, size_t len);

#endif /* _LINUX_CHAOS_MATH_H */
""")

with open("lib/chaos_math.c", "w") as f:
    f.write("""#include <linux/chaos_math.h>
#include <linux/module.h>

static inline s64 chaos_mul(s64 a, s64 b) { return (s64)(((s128)a * (s128)b) >> 32); }

s64 chaos_logistic_map_step(s64 r, s64 x) {
	s64 one_minus_x = CHAOS_Q32_ONE - x;
	return chaos_mul(r, chaos_mul(x, one_minus_x));
}
EXPORT_SYMBOL(chaos_logistic_map_step);

void chaos_lorenz_step(s64 sigma, s64 rho, s64 beta, s64 *x, s64 *y, s64 *z, s64 dt) {
	s64 dx = chaos_mul(sigma, *y - *x);
	s64 dy = chaos_mul(*x, rho - *z) - *y;
	s64 dz = chaos_mul(*x, *y) - chaos_mul(beta, *z);
	*x += chaos_mul(dx, dt);
	*y += chaos_mul(dy, dt);
	*z += chaos_mul(dz, dt);
}
EXPORT_SYMBOL(chaos_lorenz_step);

void chaos_roessler_step(s64 a, s64 b, s64 c, s64 *x, s64 *y, s64 *z, s64 dt) {
	s64 dx = -(*y) - *z;
	s64 dy = *x + chaos_mul(a, *y);
	s64 dz = b + chaos_mul(*z, *x - c);
	*x += chaos_mul(dx, dt);
	*y += chaos_mul(dy, dt);
	*z += chaos_mul(dz, dt);
}
EXPORT_SYMBOL(chaos_roessler_step);

void chaos_duffing_step(s64 delta, s64 alpha, s64 beta, s64 gamma, s64 omega, s64 *x, s64 *v, s64 t, s64 dt) {
	s64 x2 = chaos_mul(*x, *x);
	s64 x3 = chaos_mul(x2, *x);
	s64 dv = gamma - chaos_mul(delta, *v) - chaos_mul(alpha, *x) - chaos_mul(beta, x3);
	*x += chaos_mul(*v, dt);
	*v += chaos_mul(dv, dt);
}
EXPORT_SYMBOL(chaos_duffing_step);

s64 chaos_lyapunov_exponent(const s64 *trajectory, size_t len) {
    s64 sum_log_deriv = 0;
    size_t i;
    if (len < 2) return 0;
    for (i = 1; i < len; i++) {
        s64 diff = trajectory[i] > trajectory[i-1] ? trajectory[i] - trajectory[i-1] : trajectory[i-1] - trajectory[i];
        s64 divergence = diff - CHAOS_Q32_ONE;
        sum_log_deriv += divergence;
    }
    return sum_log_deriv / (s64)(len - 1);
}
EXPORT_SYMBOL(chaos_lyapunov_exponent);
""")

modify_file("lib/Makefile", "lib-y := ctype.o", "lib-y := ctype.o chaos_math.o")

# 6. TCP Congestion
with open("net/ipv4/tcp_roessler.c", "w") as f:
    f.write("""#include <linux/module.h>
#include <net/tcp.h>
#include <linux/chaos_math.h>

struct roessler_data {
    s64 x, y, z;
};

static void tcp_roessler_init(struct sock *sk) {
    struct roessler_data *ca = inet_csk_ca(sk);
    ca->x = CHAOS_TO_Q32(1); ca->y = 0; ca->z = 0;
}

static void tcp_roessler_cong_avoid(struct sock *sk, u32 ack, u32 acked) {
    struct tcp_sock *tp = tcp_sk(sk);
    struct roessler_data *ca = inet_csk_ca(sk);
    s64 dt = CHAOS_TO_Q32(1)/10;
    chaos_roessler_step(CHAOS_TO_Q32(2)/10, CHAOS_TO_Q32(2)/10, CHAOS_TO_Q32(57)/10, &ca->x, &ca->y, &ca->z, dt);
    
    if (ca->x > 0) tcp_slow_start(tp, acked);
    else tcp_cong_avoid_ai(tp, tp->snd_cwnd, 1);
}

static void tcp_roessler_set_state(struct sock *sk, u8 new_state) {
    struct roessler_data *ca = inet_csk_ca(sk);
    if (new_state == TCP_CA_Loss) ca->z += CHAOS_TO_Q32(10);
}

static u32 tcp_roessler_ssthresh(struct sock *sk) {
    const struct tcp_sock *tp = tcp_sk(sk);
    struct roessler_data *ca = inet_csk_ca(sk);
    return max((u32)(tp->snd_cwnd - (ca->y >> 32)), 2U);
}

static struct tcp_congestion_ops tcp_roessler __read_mostly = {
    .init = tcp_roessler_init,
    .ssthresh = tcp_roessler_ssthresh,
    .cong_avoid = tcp_roessler_cong_avoid,
    .set_state = tcp_roessler_set_state,
    .owner = THIS_MODULE,
    .name = "roessler",
};

static int __init tcp_roessler_register(void) { return tcp_register_congestion_control(&tcp_roessler); }
static void __exit tcp_roessler_unregister(void) { tcp_unregister_congestion_control(&tcp_roessler); }
module_init(tcp_roessler_register);
module_exit(tcp_roessler_unregister);
MODULE_LICENSE("GPL");
""")

modify_file("net/ipv4/Makefile", "obj-$(CONFIG_TCP_CONG_CUBIC) += tcp_cubic.o", "obj-$(CONFIG_TCP_CONG_CUBIC) += tcp_cubic.o\nobj-y += tcp_roessler.o")
