use std::{
    collections::BTreeMap,
    process::Command,
    sync::mpsc::{self, Receiver, Sender},
    thread,
};

#[derive(Clone)]
pub enum Request {
    Refresh,
    SetWifi(bool),
    SetBluetooth(bool),
    ScanBluetooth,
    SetBluetoothDiscoverable(bool),
    SetBluetoothPairable(bool),
    BluetoothDeviceAction { address: String, action: String },
}

#[derive(Clone, Default, PartialEq, Eq)]
pub struct BluetoothDevice {
    pub name: String,
    pub address: String,
    pub paired: bool,
    pub connected: bool,
}

#[derive(Clone, Default)]
pub struct State {
    pub wifi_available: bool,
    pub wifi_hardware_enabled: bool,
    pub wifi_enabled: bool,
    pub wifi_connected: bool,
    pub bluetooth_available: bool,
    pub bluetooth_enabled: bool,
    pub bluetooth_discoverable: bool,
    pub bluetooth_pairable: bool,
    pub bluetooth_devices: Vec<BluetoothDevice>,
    pub error: String,
}

pub fn start_worker() -> (Sender<Request>, Receiver<State>) {
    let (requests_tx, requests_rx) = mpsc::channel();
    let (states_tx, states_rx) = mpsc::channel();

    thread::spawn(move || {
        while let Ok(request) = requests_rx.recv() {
            let operation_error = match request {
                Request::Refresh => None,
                Request::SetWifi(enabled) => set_wifi(enabled).err(),
                Request::SetBluetooth(enabled) => set_bluetooth(enabled).err(),
                Request::ScanBluetooth => scan_bluetooth().err(),
                Request::SetBluetoothDiscoverable(enabled) => {
                    set_bluetooth_discoverable(enabled).err()
                }
                Request::SetBluetoothPairable(enabled) => set_bluetooth_pairable(enabled).err(),
                Request::BluetoothDeviceAction { address, action } => {
                    manage_bluetooth_device(&address, &action).err()
                }
            };
            let mut state = read_state();
            state.error = operation_error.unwrap_or_default();
            if states_tx.send(state).is_err() {
                break;
            }
        }
    });

    (requests_tx, states_rx)
}

fn read_state() -> State {
    let mut state = State::default();
    read_wifi(&mut state);
    read_bluetooth(&mut state);
    state
}

#[cfg(target_os = "linux")]
fn read_wifi(state: &mut State) {
    let Some(output) = run_command("nmcli", &["--terse", "--fields", "WIFI,WIFI-HW", "radio"])
    else {
        return;
    };
    let Some(line) = String::from_utf8_lossy(&output.stdout).lines().next().map(str::to_owned)
    else {
        return;
    };
    let mut fields = line.split(':');
    let radio = fields.next().unwrap_or_default().trim();
    let hardware = fields.next().unwrap_or_default().trim();
    if radio.is_empty() || hardware.is_empty() || hardware.eq_ignore_ascii_case("missing") {
        return;
    }

    let Some(devices) = run_command(
        "nmcli",
        &["--terse", "--fields", "TYPE,STATE", "device", "status"],
    ) else {
        return;
    };
    let wifi_devices = String::from_utf8_lossy(&devices.stdout)
        .lines()
        .filter_map(|line| {
            let mut fields = line.splitn(2, ':');
            fields
                .next()
                .is_some_and(|kind| kind.eq_ignore_ascii_case("wifi"))
                .then(|| fields.next().unwrap_or_default().to_owned())
        })
        .collect::<Vec<_>>();
    if wifi_devices.is_empty() {
        return;
    }

    state.wifi_available = true;
    state.wifi_hardware_enabled = !hardware.eq_ignore_ascii_case("disabled");
    state.wifi_enabled = radio.eq_ignore_ascii_case("enabled") && state.wifi_hardware_enabled;
    state.wifi_connected = wifi_devices
        .iter()
        .any(|status| status.to_ascii_lowercase().starts_with("connected"));
}

#[cfg(not(target_os = "linux"))]
fn read_wifi(_: &mut State) {}

#[cfg(target_os = "linux")]
fn read_bluetooth(state: &mut State) {
    let Some(output) = run_command("bluetoothctl", &["show"]) else {
        return;
    };
    let text = String::from_utf8_lossy(&output.stdout);
    state.bluetooth_available = text.lines().any(|line| line.trim_start().starts_with("Controller "));
    state.bluetooth_enabled = state.bluetooth_available
        && text.lines().any(|line| {
            line.trim_start()
                .strip_prefix("Powered:")
                .is_some_and(|value| value.trim().eq_ignore_ascii_case("yes"))
        });
    state.bluetooth_discoverable = state.bluetooth_available
        && property_is_yes(&text, "Discoverable:");
    state.bluetooth_pairable = state.bluetooth_available && property_is_yes(&text, "Pairable:");
    if !state.bluetooth_available {
        return;
    }

    let mut devices = BTreeMap::<String, BluetoothDevice>::new();
    if let Some(output) = run_command("bluetoothctl", &["devices"]) {
        merge_devices(&mut devices, &String::from_utf8_lossy(&output.stdout), false, false);
    }
    if let Some(output) = run_command("bluetoothctl", &["devices", "Paired"]) {
        merge_devices(&mut devices, &String::from_utf8_lossy(&output.stdout), true, false);
    }
    if let Some(output) = run_command("bluetoothctl", &["devices", "Connected"]) {
        merge_devices(&mut devices, &String::from_utf8_lossy(&output.stdout), false, true);
    }
    state.bluetooth_devices = devices.into_values().collect();
    state.bluetooth_devices.sort_by(|left, right| {
        right
            .connected
            .cmp(&left.connected)
            .then_with(|| right.paired.cmp(&left.paired))
            .then_with(|| left.name.to_lowercase().cmp(&right.name.to_lowercase()))
    });
    state.bluetooth_devices.truncate(50);
}

#[cfg(not(target_os = "linux"))]
fn read_bluetooth(_: &mut State) {}

#[cfg(target_os = "linux")]
fn set_wifi(enabled: bool) -> Result<(), String> {
    run_operation("nmcli", &["radio", "wifi", if enabled { "on" } else { "off" }])
}

#[cfg(not(target_os = "linux"))]
fn set_wifi(_: bool) -> Result<(), String> {
    Err("Wi-Fi controls are available on Linux only".into())
}

#[cfg(target_os = "linux")]
fn set_bluetooth(enabled: bool) -> Result<(), String> {
    run_bluetooth_operation(&["power", if enabled { "on" } else { "off" }])
}

#[cfg(not(target_os = "linux"))]
fn set_bluetooth(_: bool) -> Result<(), String> {
    Err("Bluetooth controls are available on Linux only".into())
}

#[cfg(target_os = "linux")]
fn set_bluetooth_discoverable(enabled: bool) -> Result<(), String> {
    if enabled {
        run_bluetooth_operation(&["discoverable-timeout", "120"])?;
    }
    run_bluetooth_operation(&["discoverable", if enabled { "on" } else { "off" }])
}

#[cfg(not(target_os = "linux"))]
fn set_bluetooth_discoverable(_: bool) -> Result<(), String> {
    Err("Bluetooth controls are available on Linux only".into())
}

#[cfg(target_os = "linux")]
fn set_bluetooth_pairable(enabled: bool) -> Result<(), String> {
    if enabled {
        run_bluetooth_operation(&["pairable-timeout", "120"])?;
    }
    run_bluetooth_operation(&["pairable", if enabled { "on" } else { "off" }])
}

#[cfg(not(target_os = "linux"))]
fn set_bluetooth_pairable(_: bool) -> Result<(), String> {
    Err("Bluetooth controls are available on Linux only".into())
}

#[cfg(target_os = "linux")]
fn scan_bluetooth() -> Result<(), String> {
    run_bluetooth_operation(&["--timeout", "12", "scan", "on"])?;
    let _ = run_bluetooth_operation(&["scan", "off"]);
    Ok(())
}

#[cfg(not(target_os = "linux"))]
fn scan_bluetooth() -> Result<(), String> {
    Err("Bluetooth controls are available on Linux only".into())
}

#[cfg(target_os = "linux")]
fn manage_bluetooth_device(address: &str, action: &str) -> Result<(), String> {
    if !valid_bluetooth_address(address) {
        return Err("Invalid Bluetooth device address".into());
    }
    let command = match action {
        "pair" => "pair",
        "connect" => "connect",
        "disconnect" => "disconnect",
        "remove" => "remove",
        _ => return Err("Unknown Bluetooth device action".into()),
    };
    run_bluetooth_operation(&[command, address])
}

#[cfg(not(target_os = "linux"))]
fn manage_bluetooth_device(_: &str, _: &str) -> Result<(), String> {
    Err("Bluetooth controls are available on Linux only".into())
}

fn property_is_yes(text: &str, property: &str) -> bool {
    text.lines().any(|line| {
        line.trim_start()
            .strip_prefix(property)
            .is_some_and(|value| value.trim().eq_ignore_ascii_case("yes"))
    })
}

fn merge_devices(
    devices: &mut BTreeMap<String, BluetoothDevice>,
    output: &str,
    paired: bool,
    connected: bool,
) {
    for line in output.lines() {
        let Some(device) = parse_device_line(line) else {
            continue;
        };
        devices
            .entry(device.address.clone())
            .and_modify(|existing| {
                if existing.name.is_empty() || existing.name == existing.address {
                    existing.name = device.name.clone();
                }
                existing.paired |= paired;
                existing.connected |= connected;
            })
            .or_insert(BluetoothDevice {
                paired,
                connected,
                ..device
            });
    }
}

fn parse_device_line(line: &str) -> Option<BluetoothDevice> {
    let value = line.trim().strip_prefix("Device ")?;
    let (address, name) = value.split_once(' ').unwrap_or((value, ""));
    if !valid_bluetooth_address(address) {
        return None;
    }
    Some(BluetoothDevice {
        address: address.to_ascii_uppercase(),
        name: if name.trim().is_empty() {
            address.to_ascii_uppercase()
        } else {
            name.trim().to_owned()
        },
        ..BluetoothDevice::default()
    })
}

fn valid_bluetooth_address(address: &str) -> bool {
    let octets = address.split(':').collect::<Vec<_>>();
    octets.len() == 6
        && octets
            .iter()
            .all(|octet| octet.len() == 2 && octet.bytes().all(|byte| byte.is_ascii_hexdigit()))
}

#[cfg(target_os = "linux")]
fn run_operation(program: &str, arguments: &[&str]) -> Result<(), String> {
    let output = Command::new(program)
        .args(arguments)
        .env("LC_ALL", "C")
        .env("LANG", "C")
        .env("NO_COLOR", "1")
        .output()
        .map_err(|error| format!("Could not run {program}: {error}"))?;
    if output.status.success() {
        Ok(())
    } else {
        let error = String::from_utf8_lossy(&output.stderr).trim().to_owned();
        Err(if error.is_empty() {
            format!("{program} exited with {}", output.status)
        } else {
            error
        })
    }
}

#[cfg(target_os = "linux")]
fn run_bluetooth_operation(arguments: &[&str]) -> Result<(), String> {
    let output = Command::new("bluetoothctl")
        .args(arguments)
        .env("LC_ALL", "C")
        .env("LANG", "C")
        .env("NO_COLOR", "1")
        .output()
        .map_err(|error| format!("Could not run bluetoothctl: {error}"))?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    if output.status.success() && !bluetooth_command_failed(&stdout) && !bluetooth_command_failed(&stderr) {
        return Ok(());
    }
    let detail = stderr
        .lines()
        .chain(stdout.lines())
        .find(|line| bluetooth_command_failed(line))
        .unwrap_or("Bluetooth command failed")
        .trim();
    Err(detail.to_owned())
}

#[cfg(target_os = "linux")]
fn bluetooth_command_failed(text: &str) -> bool {
    let text = text.to_ascii_lowercase();
    ["failed", "not available", "no default controller", "not connected", "not paired"]
        .iter()
        .any(|marker| text.contains(marker))
}

#[cfg(target_os = "linux")]
fn run_command(program: &str, arguments: &[&str]) -> Option<std::process::Output> {
    Command::new(program)
        .args(arguments)
        .env("LC_ALL", "C")
        .env("LANG", "C")
        .env("NO_COLOR", "1")
        .output()
        .ok()
        .filter(|output| output.status.success())
}
