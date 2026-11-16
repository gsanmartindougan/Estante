use serde_json::Value;
use std::{
    collections::HashSet,
    env, fs,
    path::{Path, PathBuf},
    process::{Command, Stdio},
};

const CLIENTS: [(&str, &str, &str, &str); 3] = [
    ("steam", "steam", "com.valvesoftware.Steam", "-silent"),
    (
        "faugus",
        "faugus-launcher",
        "io.github.Faugus.faugus-launcher",
        "--hide",
    ),
    (
        "heroic",
        "heroic",
        "com.heroicgameslauncher.hgl",
        "--no-gui",
    ),
];

pub fn start_configured(settings: &Value) -> Vec<String> {
    let running = match running_clients() {
        Ok(running) => running,
        Err(error) => {
            return vec![format!(
                "no se pudo comprobar qué lanzadores están abiertos: {error}"
            )];
        }
    };
    let mut issues = Vec::new();
    for (key, executable, app_id, flag) in CLIENTS {
        if settings
            .get(format!("start_{key}_on_start"))
            .and_then(Value::as_bool)
            != Some(true)
            || running.contains(key)
        {
            continue;
        }
        match launch(executable, app_id, flag) {
            Ok(()) => (),
            Err(error) => issues.push(format!("{key}: {error}")),
        }
    }
    issues
}

pub fn running_clients() -> std::io::Result<HashSet<&'static str>> {
    let entries = fs::read_dir("/proc")?;
    let current_uid = fs::metadata("/proc/self").ok().and_then(|meta| uid(&meta));
    let mut running = HashSet::new();
    for entry in entries.flatten() {
        if !entry
            .file_name()
            .to_string_lossy()
            .bytes()
            .all(|byte| byte.is_ascii_digit())
        {
            continue;
        }
        let path = entry.path();
        if current_uid.is_some_and(|process_uid| {
            fs::metadata(&path).ok().and_then(|meta| uid(&meta)) != Some(process_uid)
        }) {
            continue;
        }
        let comm = fs::read_to_string(path.join("comm")).unwrap_or_default();
        let args = fs::read(path.join("cmdline"))
            .unwrap_or_default()
            .split(|byte| *byte == 0)
            .filter(|part| !part.is_empty())
            .map(String::from_utf8_lossy)
            .map(|part| part.into_owned())
            .collect::<Vec<_>>();
        let names = args
            .iter()
            .take(2)
            .map(|arg| {
                Path::new(arg)
                    .file_name()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .to_lowercase()
            })
            .collect::<Vec<_>>();
        if comm.trim() == "steam" {
            running.insert("steam");
        }
        if names.iter().any(|name| name == "faugus-launcher")
            || args.windows(2).any(|pair| {
                pair[0] == "-m"
                    && matches!(pair[1].as_str(), "faugus.tray_only" | "faugus.launcher")
            })
        {
            running.insert("faugus");
        }
        let heroic_main = names
            .iter()
            .any(|name| matches!(name.as_str(), "heroic" | "heroic.bin" | "heroic-launcher"))
            || args.iter().take(2).any(|arg| {
                Path::new(arg)
                    .file_name()
                    .is_some_and(|name| name == "app.asar")
                    && Path::new(arg).parent().is_some_and(|parent| {
                        parent.to_string_lossy().to_lowercase().contains("heroic")
                    })
            });
        if !args.iter().any(|arg| arg.starts_with("--type=")) && heroic_main {
            running.insert("heroic");
        }
    }
    Ok(running)
}

fn uid(metadata: &fs::Metadata) -> Option<u32> {
    use std::os::unix::fs::MetadataExt;
    Some(metadata.uid())
}

pub fn operate(client: &str, opening: bool) -> Result<(), String> {
    let Some((key, executable, app_id, flag)) = CLIENTS.iter().find(|(key, ..)| *key == client)
    else {
        return Err("Lanzador no válido.".into());
    };
    if opening {
        if running_clients()
            .map_err(|error| error.to_string())?
            .contains(key)
        {
            return Ok(());
        }
        return launch(executable, app_id, flag);
    }
    match *key {
        "steam" => launch(executable, app_id, "-shutdown"),
        "faugus" => close_faugus(),
        "heroic" => Err("Heroic no ofrece una acción de cierre segura desde Estante.".into()),
        _ => Err("Lanzador no válido.".into()),
    }
}

fn close_faugus() -> Result<(), String> {
    let gdbus = env::split_paths(&env::var_os("PATH").unwrap_or_default())
        .map(|directory| directory.join("gdbus"))
        .find(|candidate| candidate.is_file())
        .ok_or_else(|| "No se encontró gdbus.".to_owned())?;
    let call = |destination: &str, path: &str, method: &str, extra: &[&str]| {
        Command::new(&gdbus)
            .args([
                "call",
                "--session",
                "--dest",
                destination,
                "--object-path",
                path,
                "--method",
                method,
            ])
            .args(extra)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
    };
    if call(
        "io.github.faugus.faugus-launcher.Tray",
        "/io/github/faugus/faugus_launcher/Tray",
        "io.github.Faugus.Tray.Quit",
        &[],
    )
    .map_err(|error| error.to_string())?
    .success()
    {
        return Ok(());
    }
    call(
        "io.github.faugus.faugus-launcher",
        "/io/github/faugus/faugus_launcher",
        "org.gtk.Actions.Activate",
        &["quit", "[]", "{}"],
    )
    .map_err(|error| error.to_string())?
    .success()
    .then_some(())
    .ok_or_else(|| "Faugus rechazó la solicitud de cierre.".into())
}

fn launch(executable: &str, app_id: &str, flag: &str) -> Result<(), String> {
    let native = env::split_paths(&env::var_os("PATH").unwrap_or_default())
        .map(|directory| directory.join(executable))
        .find(|candidate| candidate.is_file());
    let (program, args): (PathBuf, Vec<String>) = if let Some(native) = native {
        (native, vec![flag.into()])
    } else {
        let flatpak = env::split_paths(&env::var_os("PATH").unwrap_or_default())
            .map(|directory| directory.join("flatpak"))
            .find(|candidate| candidate.is_file())
            .ok_or_else(|| format!("No se encontró {executable} ni Flatpak."))?;
        let installed = Command::new(&flatpak)
            .args(["info", app_id])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map_err(|error| error.to_string())?;
        if !installed.success() {
            return Err(format!("No está instalado {app_id}."));
        }
        (flatpak, vec!["run".into(), app_id.into(), flag.into()])
    };
    Command::new(program)
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map(|_| ())
        .map_err(|error| error.to_string())
}
