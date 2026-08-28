#!/usr/bin/python3

from pathlib import Path


def replace_once(path, needle, replacement):
    source = Path(path)
    text = source.read_text()
    count = text.count(needle)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}: {needle!r}")
    source.write_text(text.replace(needle, replacement, 1))


def write(path, content):
    Path(path).write_text(content)


write("include/linux/chaos_math.h", r'''/* SPDX-License-Identifier: GPL-2.0 */
#ifndef _LINUX_CHAOS_MATH_H
#define _LINUX_CHAOS_MATH_H

#include <linux/types.h>

#define CHAOS_Q16_ONE (1U << 16)

u32 chaos_logistic_step(u32 state);
u64 chaos_mix64(u64 value);
u32 chaos_roessler_step(s32 *x, s32 *y, s32 *z, u32 drive);
void chaos_duffing_step(s32 *x, s32 *velocity, u32 drive);
u32 chaos_divergence_score(u64 previous, u64 sample);

#endif
''')

write("lib/chaos_math.c", r'''// SPDX-License-Identifier: GPL-2.0
#include <linux/chaos_math.h>
#include <linux/export.h>
#include <linux/kernel.h>
#include <linux/limits.h>
#include <linux/math64.h>

static s32 chaos_q16_mul(s32 a, s32 b)
{
	return (s32)(((s64)a * b) >> 16);
}

u32 chaos_logistic_step(u32 state)
{
	u64 product, next;

	if (unlikely(state < 2 || state > U32_MAX - 2))
		state ^= 0x9e3779b9U;
	product = (u64)state * (U32_MAX - state);
	next = product >> 30;
	return clamp_t(u64, next, 1, U32_MAX - 1);
}
EXPORT_SYMBOL_GPL(chaos_logistic_step);

u64 chaos_mix64(u64 value)
{
	value ^= value >> 30;
	value *= 0xbf58476d1ce4e5b9ULL;
	value ^= value >> 27;
	value *= 0x94d049bb133111ebULL;
	return value ^ (value >> 31);
}
EXPORT_SYMBOL_GPL(chaos_mix64);

u32 chaos_roessler_step(s32 *x, s32 *y, s32 *z, u32 drive)
{
	const s32 a = 13107, b = 13107, c = 373555;
	s32 dx = -*y - *z;
	s32 dy = *x + chaos_q16_mul(a, *y);
	s32 dz = b + chaos_q16_mul(*z, *x - c);
	s32 forcing = (s32)(drive >> 16) - 32768;

	*x = clamp_t(s64, (s64)*x + (dx >> 6) + (forcing >> 8),
		     -32LL * CHAOS_Q16_ONE, 32LL * CHAOS_Q16_ONE);
	*y = clamp_t(s64, (s64)*y + (dy >> 6),
		     -32LL * CHAOS_Q16_ONE, 32LL * CHAOS_Q16_ONE);
	*z = clamp_t(s64, (s64)*z + (dz >> 6),
		     -32LL * CHAOS_Q16_ONE, 32LL * CHAOS_Q16_ONE);
	return chaos_mix64((u32)*x ^ ((u64)(u32)*y << 21) ^
			   ((u64)(u32)*z << 42) ^ drive);
}
EXPORT_SYMBOL_GPL(chaos_roessler_step);

void chaos_duffing_step(s32 *x, s32 *velocity, u32 drive)
{
	s32 forcing = ((s32)(drive >> 16) - 32768) << 1;
	s32 x2 = chaos_q16_mul(*x, *x);
	s32 x3 = chaos_q16_mul(x2, *x);
	s32 acceleration = forcing - chaos_q16_mul(8192, *velocity) +
			   *x - chaos_q16_mul(32768, x3);

	*velocity = clamp_t(s64, (s64)*velocity + (acceleration >> 6),
			    -8LL * CHAOS_Q16_ONE, 8LL * CHAOS_Q16_ONE);
	*x = clamp_t(s64, (s64)*x + (*velocity >> 6),
		     -8LL * CHAOS_Q16_ONE, 8LL * CHAOS_Q16_ONE);
}
EXPORT_SYMBOL_GPL(chaos_duffing_step);

u32 chaos_divergence_score(u64 previous, u64 sample)
{
	u64 high = max(previous, sample) | 1;
	u64 delta = previous > sample ? previous - sample : sample - previous;

	return min_t(u64, mul_u64_u64_div_u64(delta, U32_MAX, high), U32_MAX);
}
EXPORT_SYMBOL_GPL(chaos_divergence_score);
''')

replace_once("lib/Makefile", "lib-y := ctype.o", "lib-y := ctype.o chaos_math.o")

replace_once("drivers/char/random.c", "#include <linux/uuid.h>",
             "#include <linux/uuid.h>\n#include <linux/chaos_math.h>")
replace_once("drivers/char/random.c", "\tunsigned int bits;",
             "\tunsigned int bits;\n\n"
             "\tentropy = chaos_mix64(entropy ^ now ^ ((u64)num << 32));")

replace_once("mm/oom_kill.c", "#include <linux/oom.h>",
             "#include <linux/oom.h>\n#include <linux/chaos_math.h>\n\n"
             "static atomic64_t chaos_last_free_pages = ATOMIC64_INIT(0);")
replace_once("mm/oom_kill.c", "\tunsigned long freed = 0;",
             "\tunsigned long freed = 0;\n"
             "\tu64 free_pages = global_zone_page_state(NR_FREE_PAGES);\n"
             "\tu64 previous = atomic64_xchg(&chaos_last_free_pages, free_pages);\n\n"
             "\tif (previous > free_pages &&\n"
             "\t    chaos_divergence_score(previous, free_pages) > (U32_MAX >> 1))\n"
             "\t\tpr_warn_ratelimited(\"chaos: nonlinear memory collapse detected\\n\");")

replace_once("include/linux/sched.h",
             "\tunsigned char\t\t\tcustom_slice;\n\t\t\t\t\t/* hole */",
             "\tunsigned char\t\t\tcustom_slice;\n"
             "\tu32\t\t\t\tcore_chaos_state;")
replace_once("kernel/sched/features.h", "SCHED_FEAT(PLACE_LAG, true)",
             "SCHED_FEAT(PLACE_LAG, true)\n"
             "/* Bounded nonlinear wakeup placement; no scheduler-tick cost. */\n"
             "SCHED_FEAT(CHAOS_CORE, true)")
replace_once("kernel/sched/fair.c", "#include <linux/interrupt.h>",
             "#include <linux/interrupt.h>\n#include <linux/chaos_math.h>")
replace_once("kernel/sched/fair.c", "\tse->vruntime = vruntime - lag;",
             "\tse->vruntime = vruntime - lag;\n\n"
             "\tif (sched_feat(CHAOS_CORE) && entity_is_task(se) &&\n"
             "\t    (flags & ENQUEUE_WAKEUP)) {\n"
             "\t\tu64 bonus;\n\n"
             "\t\tif (!se->core_chaos_state)\n"
             "\t\t\tse->core_chaos_state = chaos_mix64(se->vruntime ^\n"
             "\t\t\t\t\t\t       se->sum_exec_runtime);\n"
             "\t\tse->core_chaos_state =\n"
             "\t\t\tchaos_logistic_step(se->core_chaos_state);\n"
             "\t\tbonus = mul_u64_u32_shr(vslice, se->core_chaos_state, 34);\n"
             "\t\tse->vruntime -= min(bonus, se->vruntime);\n"
             "\t}")

replace_once("block/blk-mq.c", "#include <linux/blkdev.h>",
             "#include <linux/blkdev.h>\n#include <linux/chaos_math.h>\n"
             "#include <linux/percpu.h>")
replace_once("block/blk-mq.c", "/**\n * blk_mq_submit_bio",
             "static unsigned int chaos_block_bypass_shift;\n"
             "module_param_named(chaos_bypass_shift, chaos_block_bypass_shift, uint, 0644);\n"
             "static DEFINE_PER_CPU(s32, chaos_duffing_x);\n"
             "static DEFINE_PER_CPU(s32, chaos_duffing_velocity);\n\n"
             "/**\n * blk_mq_submit_bio")
replace_once("block/blk-mq.c", "\tconst int is_sync = op_is_sync(bio->bi_opf);",
             "\tconst int is_sync = op_is_sync(bio->bi_opf);\n\n"
             "\tif (unlikely(chaos_block_bypass_shift && plug && is_sync &&\n"
             "\t             bio_op(bio) == REQ_OP_READ)) {\n"
             "\t\ts32 x = this_cpu_read(chaos_duffing_x);\n"
             "\t\ts32 velocity = this_cpu_read(chaos_duffing_velocity);\n"
             "\t\tu32 drive = chaos_mix64(bio->bi_iter.bi_sector ^\n"
             "\t\t\t\t\t((u64)bio->bi_iter.bi_size << 32));\n\n"
             "\t\tchaos_duffing_step(&x, &velocity, drive);\n"
             "\t\tthis_cpu_write(chaos_duffing_x, x);\n"
             "\t\tthis_cpu_write(chaos_duffing_velocity, velocity);\n"
             "\t\tif (!((u32)velocity &\n"
             "\t\t      ((1U << min(chaos_block_bypass_shift, 31U)) - 1)))\n"
             "\t\t\tplug = NULL;\n"
             "\t}")

write("net/ipv4/tcp_roessler.c", r'''// SPDX-License-Identifier: GPL-2.0
#include <linux/chaos_math.h>
#include <linux/module.h>
#include <net/tcp.h>

struct roessler_ca { s32 x, y, z; u32 drive; };

static void roessler_init(struct sock *sk)
{
	struct roessler_ca *ca = inet_csk_ca(sk);
	const struct tcp_sock *tp = tcp_sk(sk);
	u64 seed = chaos_mix64((u64)tcp_jiffies32 << 32 | tp->write_seq);

	ca->x = CHAOS_Q16_ONE;
	ca->y = seed & 0xffff;
	ca->z = CHAOS_Q16_ONE;
	ca->drive = seed >> 32;
}

static void roessler_cong_avoid(struct sock *sk, u32 ack, u32 acked)
{
	struct tcp_sock *tp = tcp_sk(sk);
	struct roessler_ca *ca = inet_csk_ca(sk);
	u32 cwnd, signal, divisor;

	if (!tcp_is_cwnd_limited(sk))
		return;
	if (tcp_in_slow_start(tp)) {
		acked = tcp_slow_start(tp, acked);
		if (!acked)
			return;
	}
	ca->drive = chaos_logistic_step(ca->drive ^ ack ^ acked);
	signal = chaos_roessler_step(&ca->x, &ca->y, &ca->z, ca->drive);
	cwnd = tcp_snd_cwnd(tp);
	divisor = cwnd - (cwnd >> 3) +
		  (u32)(((u64)(cwnd >> 2) * signal) >> 32);
	tcp_cong_avoid_ai(tp, max(divisor, 2U), acked);
}

static u32 roessler_ssthresh(struct sock *sk)
{
	struct tcp_sock *tp = tcp_sk(sk);
	struct roessler_ca *ca = inet_csk_ca(sk);
	u32 signal = chaos_roessler_step(&ca->x, &ca->y, &ca->z,
					 ca->drive ^ tcp_snd_cwnd(tp));
	u32 factor = 29491 + (u32)(((u64)6554 * signal) >> 32);

	return max_t(u32, ((u64)tcp_snd_cwnd(tp) * factor) >> 16, 2U);
}

static u32 roessler_undo_cwnd(struct sock *sk)
{
	const struct tcp_sock *tp = tcp_sk(sk);
	return max(tcp_snd_cwnd(tp), tp->prior_cwnd);
}

static struct tcp_congestion_ops roessler __read_mostly = {
	.init = roessler_init,
	.ssthresh = roessler_ssthresh,
	.undo_cwnd = roessler_undo_cwnd,
	.cong_avoid = roessler_cong_avoid,
	.owner = THIS_MODULE,
	.name = "roessler",
};

static int __init roessler_register(void)
{
	BUILD_BUG_ON(sizeof(struct roessler_ca) > ICSK_CA_PRIV_SIZE);
	return tcp_register_congestion_control(&roessler);
}

static void __exit roessler_unregister(void)
{
	tcp_unregister_congestion_control(&roessler);
}
module_init(roessler_register);
module_exit(roessler_unregister);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Bounded Roessler TCP congestion control");
''')

visible = '''config TCP_CONG_ROESSLER
\ttristate "Rössler TCP"
\tdefault m
\thelp
\t  Reno-compatible congestion control with bounded nonlinear additive
\t  increase and loss response driven by a Rössler attractor.

'''
replace_once("net/ipv4/Kconfig", "config TCP_CONG_CUBIC\n\ttristate \"CUBIC TCP\"",
             visible + "config TCP_CONG_CUBIC\n\ttristate \"CUBIC TCP\"")
replace_once("net/ipv4/Kconfig", "config TCP_CONG_CUBIC\n\ttristate\n\tdepends on !TCP_CONG_ADVANCED",
             "config TCP_CONG_ROESSLER\n\ttristate\n\tdepends on !TCP_CONG_ADVANCED\n\n"
             "config TCP_CONG_CUBIC\n\ttristate\n\tdepends on !TCP_CONG_ADVANCED")
replace_once("net/ipv4/Makefile", "obj-$(CONFIG_TCP_CONG_CUBIC) += tcp_cubic.o",
             "obj-$(CONFIG_TCP_CONG_CUBIC) += tcp_cubic.o\n"
             "obj-$(CONFIG_TCP_CONG_ROESSLER) += tcp_roessler.o")
