#![no_std]

#[cfg(not(test))]
use core::panic::PanicInfo;

#[cfg(not(test))]
#[panic_handler]
fn panic(_info: &PanicInfo) -> ! { loop {} }

pub const Q16_ONE: i32 = 1 << 16;

fn q16_mul(a: i32, b: i32) -> i32 {
    ((a as i64 * b as i64) >> 16) as i32
}

fn q16_clamp(value: i64, low: i32, high: i32) -> i32 {
    value.clamp(low as i64, high as i64) as i32
}

#[unsafe(no_mangle)]
pub extern "C" fn chaos_logistic_step(mut state: u32) -> u32 {
    if state < 2 || state > u32::MAX - 2 { state ^= 0x9e37_79b9; }
    let product = state as u64 * (u32::MAX - state) as u64;
    (product >> 30).clamp(1, (u32::MAX - 1) as u64) as u32
}

#[unsafe(no_mangle)]
pub extern "C" fn chaos_mix64(mut value: u64) -> u64 {
    value ^= value >> 30;
    value = value.wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value ^= value >> 27;
    value = value.wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

#[unsafe(no_mangle)]
pub extern "C" fn chaos_lorenz_step(x: &mut i32, y: &mut i32, z: &mut i32,
                                     drive: u32) -> u32 {
    let sigma = 10 * Q16_ONE;
    let rho = 28 * Q16_ONE;
    let beta = 174_763; // 8/3 in Q16.16
    let dx = q16_mul(sigma, *y - *x);
    let dy = q16_mul(*x, rho - *z) - *y;
    let dz = q16_mul(*x, *y) - q16_mul(beta, *z);
    let forcing = (drive >> 16) as i32 - 32_768;
    let limit = 64 * Q16_ONE;

    *x = q16_clamp(*x as i64 + (dx >> 6) as i64 + (forcing >> 9) as i64,
                   -limit, limit);
    *y = q16_clamp(*y as i64 + (dy >> 6) as i64, -limit, limit);
    *z = q16_clamp(*z as i64 + (dz >> 6) as i64, -limit, limit);
    chaos_mix64(*x as u32 as u64 ^ ((*y as u32 as u64) << 21)
        ^ ((*z as u32 as u64) << 42) ^ drive as u64) as u32
}

#[unsafe(no_mangle)]
pub extern "C" fn chaos_roessler_step(x: &mut i32, y: &mut i32, z: &mut i32,
                                        drive: u32) -> u32 {
    let dx = -*y - *z;
    let dy = *x + q16_mul(13_107, *y);
    let dz = 13_107 + q16_mul(*z, *x - 373_555);
    let forcing = (drive >> 16) as i32 - 32_768;
    let limit = 32 * Q16_ONE;

    *x = (*x + (dx >> 6) + (forcing >> 8)).clamp(-limit, limit);
    *y = (*y + (dy >> 6)).clamp(-limit, limit);
    *z = (*z + (dz >> 6)).clamp(-limit, limit);
    chaos_mix64(*x as u32 as u64 ^ ((*y as u32 as u64) << 21)
        ^ ((*z as u32 as u64) << 42) ^ drive as u64) as u32
}

#[unsafe(no_mangle)]
pub extern "C" fn chaos_duffing_step(x: &mut i32, velocity: &mut i32, drive: u32) {
    let forcing = ((drive >> 16) as i32 - 32_768) << 1;
    let x2 = q16_mul(*x, *x);
    let x3 = q16_mul(x2, *x);
    let acceleration = forcing - q16_mul(8_192, *velocity) + *x
        - q16_mul(32_768, x3);
    let limit = 8 * Q16_ONE;

    *velocity = (*velocity + (acceleration >> 6)).clamp(-limit, limit);
    *x = (*x + (*velocity >> 6)).clamp(-limit, limit);
}

#[unsafe(no_mangle)]
pub extern "C" fn chaos_mandelbrot_escape(real: i32, imag: i32, max_iter: u32) -> u32 {
    let mut zr = 0;
    let mut zi = 0;
    let max_iter = max_iter.min(16);
    for i in 0..max_iter {
        let zr2 = q16_mul(zr, zr);
        let zi2 = q16_mul(zi, zi);
        let cross = q16_mul(zr, zi);
        if zr2 as i64 + zi2 as i64 > 4 * Q16_ONE as i64 {
            return i;
        }
        zr = q16_clamp(zr2 as i64 - zi2 as i64 + real as i64,
                       -8 * Q16_ONE, 8 * Q16_ONE);
        zi = q16_clamp((cross as i64) * 2 + imag as i64,
                       -8 * Q16_ONE, 8 * Q16_ONE);
    }
    max_iter
}

fn q16_ln(mut value: i32) -> i32 {
    const LN2: i32 = 45_426;
    if value <= 0 {
        return i32::MIN;
    }
    let mut exponent = 0;
    while value >= 2 * Q16_ONE {
        value >>= 1;
        exponent += 1;
    }
    while value < Q16_ONE / 2 {
        value <<= 1;
        exponent -= 1;
    }
    let y = (((value - Q16_ONE) as i64 * Q16_ONE as i64)
        / (value + Q16_ONE) as i64) as i32;
    let y2 = q16_mul(y, y);
    let mut term = y;
    let mut sum = y;
    term = q16_mul(term, y2);
    sum += term / 3;
    term = q16_mul(term, y2);
    sum += term / 5;
    term = q16_mul(term, y2);
    sum += term / 7;
    ((2 * sum) as i64 + exponent as i64 * LN2 as i64)
        .clamp(i32::MIN as i64, i32::MAX as i64) as i32
}

#[unsafe(no_mangle)]
pub extern "C" fn chaos_lyapunov_step(previous: u64, sample: u64) -> i32 {
    if previous == 0 && sample == 0 {
        return 0;
    }
    let high = previous.max(sample) | 1;
    let low = previous.min(sample) | 1;
    let ratio = ((high as u128 * Q16_ONE as u128) / low as u128)
        .min((16 * Q16_ONE) as u128)
        .max((Q16_ONE / 16) as u128) as i32;
    q16_ln(ratio)
}

#[unsafe(no_mangle)]
pub extern "C" fn chaos_divergence_score(previous: u64, sample: u64) -> u32 {
    let high = previous.max(sample) | 1;
    let delta = previous.abs_diff(sample);
    ((delta as u128 * u32::MAX as u128) / high as u128)
        .min(u32::MAX as u128) as u32
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn logistic_state_stays_in_the_open_unit_interval() {
        for state in [0, 1, 2, 0x1234_5678, u32::MAX - 1, u32::MAX] {
            let next = chaos_logistic_step(state);
            assert!(next > 0);
            assert!(next < u32::MAX);
        }
    }

    #[test]
    fn attractors_remain_bounded() {
        let mut lorenz = (1_000, -2_000, 3_000);
        let mut roessler = (1_000, -2_000, 3_000);
        let mut duffing = (1_000, 2_000);
        for drive in 0..512 {
            chaos_lorenz_step(&mut lorenz.0, &mut lorenz.1, &mut lorenz.2, drive);
            chaos_roessler_step(&mut roessler.0, &mut roessler.1, &mut roessler.2, drive);
            chaos_duffing_step(&mut duffing.0, &mut duffing.1, drive);
            assert!(lorenz.0.abs() <= 64 * Q16_ONE);
            assert!(lorenz.1.abs() <= 64 * Q16_ONE);
            assert!(lorenz.2.abs() <= 64 * Q16_ONE);
            assert!(roessler.0.abs() <= 32 * Q16_ONE);
            assert!(roessler.1.abs() <= 32 * Q16_ONE);
            assert!(roessler.2.abs() <= 32 * Q16_ONE);
            assert!(duffing.0.abs() <= 8 * Q16_ONE);
            assert!(duffing.1.abs() <= 8 * Q16_ONE);
        }
    }

    #[test]
    fn scores_are_bounded() {
        assert!(chaos_mandelbrot_escape(0, 0, u32::MAX) <= 16);
        assert!(chaos_lyapunov_step(u64::MAX, 1).is_positive());
        assert_eq!(chaos_divergence_score(0, 0), 0);
        assert_eq!(chaos_divergence_score(0, u64::MAX), u32::MAX);
    }
}
