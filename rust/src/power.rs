use std::fs;
use std::path::Path;

pub struct BatteryStatus {
    pub percentage: u8,
    pub charging: bool,
    pub full: bool,
}

pub fn read_battery_status() -> Option<BatteryStatus> {
    let supplies = fs::read_dir("/sys/class/power_supply").ok()?;

    for supply in supplies.flatten() {
        let path = supply.path();
        let Ok(kind) = fs::read_to_string(path.join("type")) else {
            continue;
        };
        if kind.trim() != "Battery" || !is_present(&path) {
            continue;
        }

        let Some(percentage) = read_percentage(&path) else {
            continue;
        };
        let Some((charging, full)) = read_charge_state(&path) else {
            continue;
        };

        return Some(BatteryStatus {
            percentage,
            charging,
            full,
        });
    }

    None
}

fn is_present(path: &Path) -> bool {
    match fs::read_to_string(path.join("present")) {
        Ok(value) => matches!(value.trim(), "1"),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => true,
        Err(_) => false,
    }
}

fn read_percentage(path: &Path) -> Option<u8> {
    let value = fs::read_to_string(path.join("capacity")).ok()?;
    let percentage = value.trim().parse::<u8>().ok()?;
    (percentage <= 100).then_some(percentage)
}

fn read_charge_state(path: &Path) -> Option<(bool, bool)> {
    let status = fs::read_to_string(path.join("status")).ok()?;
    match status.trim() {
        "Charging" => Some((true, false)),
        "Discharging" | "Not charging" => Some((false, false)),
        "Full" => Some((false, true)),
        _ => None,
    }
}
