#![no_std]

use core::panic::PanicInfo;

#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    loop {}
}

/// Logistic map for entropy generation.
/// Computes x_{n+1} = r * x_n * (1 - x_n)
#[no_mangle]
pub extern "C" fn chaos_logistic_map_step(r: f64, x: f64) -> f64 {
    r * x * (1.0 - x)
}
