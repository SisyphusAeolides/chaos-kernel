#![no_std]

use core::panic::PanicInfo;

#[panic_handler]
fn panic(_info: &PanicInfo) -> ! { loop {} }

pub const Q16_ONE: i32 = 1 << 16;

fn q16_mul(a: i32, b: i32) -> i32 {
    ((a as i64 * b as i64) >> 16) as i32
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
pub extern "C" fn chaos_divergence_score(previous: u64, sample: u64) -> u32 {
    let high = previous.max(sample) | 1;
    let delta = previous.abs_diff(sample);
    ((delta as u128 * u32::MAX as u128) / high as u128)
        .min(u32::MAX as u128) as u32
}
