use crate::model::Library;
use serde_json::{Value, json};
use std::{
    fs::{self, OpenOptions},
    io,
    os::unix::fs::{DirBuilderExt, OpenOptionsExt},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    thread,
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

pub struct Handoff {
    pub game_id: String,
    pub launcher_pid: u32,
    pub token: String,
    pub root: PathBuf,
    pub started_at: String,
    pub started_uptime: f64,
    pub restore: Value,
}

pub fn prepare(handoff: Handoff) -> Result<PathBuf, String> {
    let appimage = std::env::var_os("APPIMAGE").map(PathBuf::from);
    let executable = appimage
        .or_else(|| std::env::current_exe().ok())
        .ok_or_else(|| "No se pudo localizar el ejecutable de Estante.".to_owned())?;
    let folder = std::env::temp_dir().join(format!(
        "estante-session-{}-{}",
        std::process::id(),
        unique_suffix()
    ));
    fs::DirBuilder::new()
        .recursive(true)
        .mode(0o700)
        .create(&folder)
        .map_err(|error| error.to_string())?;
    let session_file = folder.join("session.json");
    let ui_pid = std::process::id();
    let ui_identity = process_identity(ui_pid);
    let spec = json!({
        "game_id": handoff.game_id,
        "launcher_pid": handoff.launcher_pid,
        "token": handoff.token,
        "root": handoff.root,
        "started_at": handoff.started_at,
        "started_uptime": handoff.started_uptime,
        "restore": handoff.restore,
        "ui_pid": ui_pid,
        "ui_identity": ui_identity,
        "reopen": executable,
        "cwd": std::env::current_dir().unwrap_or_default(),
    });
    write_private_json(&session_file, &spec).map_err(|error| error.to_string())?;
    let unit = format!("estante-game-{}", unique_suffix());
    let result = Command::new("systemd-run")
        .args(["--user", "--collect", "--quiet"])
        .arg(format!("--unit={unit}"))
        .args(["--property=Type=exec", "--property=KillMode=process", "--"])
        .arg(executable)
        .args(["--supervisor-session"])
        .arg(&session_file)
        .output()
        .map_err(|error| {
            let _ = fs::remove_dir_all(&folder);
            error.to_string()
        })?;
    if !result.status.success() {
        let _ = fs::write(folder.join("cancel"), []);
        let _ = fs::remove_dir_all(&folder);
        let error = String::from_utf8_lossy(&result.stderr).trim().to_owned();
        return Err(if error.is_empty() {
            "No se pudo iniciar el supervisor de la partida.".into()
        } else {
            error
        });
    }
    let deadline = Instant::now() + Duration::from_secs(8);
    loop {
        let status = folder.join("status.json");
        if let Ok(contents) = fs::read(&status)
            && let Ok(value) = serde_json::from_slice::<Value>(&contents)
        {
            if value.get("state").and_then(Value::as_str) == Some("ready") {
                return Ok(folder);
            }
            let error = value
                .get("error")
                .and_then(Value::as_str)
                .unwrap_or("La partida terminó antes de transferir la supervisión.");
            let _ = fs::write(folder.join("cancel"), []);
            return Err(error.to_owned());
        }
        if Instant::now() >= deadline {
            let _ = fs::write(folder.join("cancel"), []);
            return Err("El supervisor no respondió; Estante seguirá abierto.".into());
        }
        thread::sleep(Duration::from_millis(50));
    }
}

pub fn run(session_file: &Path) -> Result<(), String> {
    let folder = session_file
        .parent()
        .ok_or_else(|| "Ruta de sesión no válida.".to_owned())?;
    let result = run_session(session_file, folder);
    let _ = fs::remove_dir_all(folder);
    result
}

fn run_session(session_file: &Path, folder: &Path) -> Result<(), String> {
    let spec: Value =
        serde_json::from_slice(&fs::read(session_file).map_err(|error| error.to_string())?)
            .map_err(|error| error.to_string())?;
    let root = PathBuf::from(required_str(&spec, "root")?);
    let game_id = required_str(&spec, "game_id")?;
    let launcher_pid = required_u32(&spec, "launcher_pid")?;
    let token = required_str(&spec, "token")?;
    let library = Library::open(root.clone());
    let game = library
        .games()
        .into_iter()
        .find(|game| game.id() == game_id)
        .ok_or_else(|| "El juego de la sesión ya no está en la biblioteca.".to_owned())?;
    let members = || Library::matching_game_processes(&game, launcher_pid, token);
    if members().is_empty() {
        write_json(&folder.join("status.json"), &json!({"state":"finished"}))
            .map_err(|error| error.to_string())?;
        return Ok(());
    }
    write_json(&folder.join("status.json"), &json!({"state":"ready"}))
        .map_err(|error| error.to_string())?;
    let deadline = Instant::now() + Duration::from_secs(15);
    while !folder.join("handoff").exists() {
        if folder.join("cancel").exists() || Instant::now() >= deadline {
            return Ok(());
        }
        thread::sleep(Duration::from_millis(50));
    }
    let ui_pid = required_u32(&spec, "ui_pid")?;
    let ui_identity = spec.get("ui_identity").and_then(Value::as_str);
    while ui_identity.is_some() && process_identity(ui_pid).as_deref() == ui_identity {
        thread::sleep(Duration::from_millis(100));
    }
    while !members().is_empty() {
        thread::sleep(Duration::from_secs(1));
    }
    let seconds = uptime_seconds()
        .zip(spec["started_uptime"].as_f64())
        .map(|(now, started)| (now - started).max(0.0) as u64)
        .unwrap_or(0);
    let mut library = Library::open(root.clone());
    if let Err(error) =
        library.record_session(&game_id, seconds, required_str(&spec, "started_at")?, None)
    {
        eprintln!("Estante supervisor: no se pudo guardar la sesión: {error}");
    }

    let restore_file = root.join(format!("resume-{}.json", unique_suffix()));
    write_private_json(&restore_file, &spec["restore"]).map_err(|error| error.to_string())?;
    let executable = PathBuf::from(required_str(&spec, "reopen")?);
    let cwd = PathBuf::from(required_str(&spec, "cwd")?);
    let mut reopen = Command::new(executable);
    reopen
        .env("ESTANTE_RESUME_FILE", &restore_file)
        .env("ESTANTE_DATA_DIR", &root)
        .current_dir(if cwd.is_dir() { cwd } else { root })
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    reopen.spawn().map_err(|error| error.to_string())?;
    Ok(())
}

pub fn uptime_seconds() -> Option<f64> {
    fs::read_to_string("/proc/uptime")
        .ok()?
        .split_whitespace()
        .next()?
        .parse()
        .ok()
}

fn process_identity(pid: u32) -> Option<String> {
    let stat = fs::read_to_string(format!("/proc/{pid}/stat")).ok()?;
    let fields = stat
        .rsplit_once(") ")?
        .1
        .split_whitespace()
        .collect::<Vec<_>>();
    if fields.first() == Some(&"Z") {
        None
    } else {
        fields.get(19).map(|identity| (*identity).to_owned())
    }
}

fn write_json(path: &Path, value: &Value) -> io::Result<()> {
    let temporary = path.with_extension("tmp");
    fs::write(&temporary, serde_json::to_vec(value)?)?;
    fs::rename(temporary, path)
}

fn write_private_json(path: &Path, value: &Value) -> io::Result<()> {
    let temporary = path.with_extension("tmp");
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&temporary)?;
    serde_json::to_writer(&mut file, value)?;
    file.sync_all()?;
    fs::rename(temporary, path)
}

fn required_str<'a>(value: &'a Value, key: &str) -> Result<&'a str, String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| format!("Falta {key} en la sesión."))
}

fn required_u32(value: &Value, key: &str) -> Result<u32, String> {
    value
        .get(key)
        .and_then(Value::as_u64)
        .and_then(|value| u32::try_from(value).ok())
        .ok_or_else(|| format!("Falta {key} en la sesión."))
}

fn unique_suffix() -> String {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos()
        .to_string()
}

#[cfg(test)]
mod tests {
    use super::{process_identity, uptime_seconds};

    #[test]
    fn supervisor_can_identify_its_own_process_and_monotonic_time() {
        assert!(process_identity(std::process::id()).is_some());
        assert!(uptime_seconds().is_some_and(|seconds| seconds > 0.0));
        assert!(process_identity(u32::MAX).is_none());
    }
}
