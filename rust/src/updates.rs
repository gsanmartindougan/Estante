use serde_json::Value;
use std::{
    env, fs,
    io::Write,
    path::{Path, PathBuf},
    process::Command,
};

const REPOSITORY: &str = "gsanmartindougan/Estante";
const MAX_DOWNLOAD: u64 = 512 * 1024 * 1024;

#[derive(Clone, Debug)]
pub struct Release {
    pub version: String,
    pub url: String,
    pub asset: Option<Value>,
}

pub fn appimage_path() -> Option<PathBuf> {
    if env::var_os("ESTANTE_APPDIR").is_none() {
        return None;
    }
    env::var_os("APPIMAGE").map(PathBuf::from)
}

pub fn latest_release() -> Result<Option<Release>, String> {
    let current = env!("CARGO_PKG_VERSION");
    let endpoint = format!("https://api.github.com/repos/{REPOSITORY}/releases/latest");
    let output = Command::new("curl")
        .args([
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--max-time",
            "20",
            "--max-filesize",
            "2097152",
            "--proto",
            "=https",
            "--proto-redir",
            "=https",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            &format!("User-Agent: Estante/{current}"),
        ])
        .arg(endpoint)
        .output()
        .map_err(|error| format!("No se pudo iniciar curl: {error}"))?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_owned());
    }
    let release: Value =
        serde_json::from_slice(&output.stdout).map_err(|error| error.to_string())?;
    if release["draft"].as_bool().unwrap_or(false)
        || release["prerelease"].as_bool().unwrap_or(false)
    {
        return Ok(None);
    }
    let tag = release["tag_name"].as_str().unwrap_or_default();
    let version = tag.strip_prefix('v').unwrap_or(tag);
    let latest = version_parts(version)?;
    let current = version_parts(current)?;
    if latest <= current {
        return Ok(None);
    }
    let expected = format!("Estante-{version}-x86_64.AppImage");
    let asset = release["assets"]
        .as_array()
        .into_iter()
        .flatten()
        .find(|asset| asset["name"].as_str() == Some(&expected))
        .cloned();
    Ok(Some(Release {
        version: version.to_owned(),
        url: format!("https://github.com/{REPOSITORY}/releases/tag/{tag}"),
        asset,
    }))
}

pub fn install_appimage(release: &Release, target: &Path) -> Result<String, String> {
    if !cfg!(target_arch = "x86_64") {
        return Err("No hay AppImage para esta arquitectura.".into());
    }
    let target = target.canonicalize().map_err(|error| error.to_string())?;
    let asset = release
        .asset
        .as_ref()
        .ok_or_else(|| "La publicación todavía no incluye el AppImage para x86_64.".to_owned())?;
    let digest = asset["digest"].as_str().unwrap_or_default();
    let Some(checksum) = digest.strip_prefix("sha256:") else {
        return Err("GitHub todavía no ofrece la suma SHA-256 de este archivo.".into());
    };
    if checksum.len() != 64 || !checksum.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err("La suma SHA-256 de GitHub no es válida.".into());
    }
    let address = asset["browser_download_url"].as_str().unwrap_or_default();
    let allowed_prefix = format!("https://github.com/{REPOSITORY}/releases/download/");
    if !address.starts_with(&allowed_prefix) || address.contains(['?', '#']) {
        return Err("La descarga no pertenece al repositorio de Estante.".into());
    }
    let expected_size = asset["size"]
        .as_u64()
        .filter(|size| (1..=MAX_DOWNLOAD).contains(size))
        .ok_or_else(|| "El tamaño de la actualización no es válido.".to_owned())?;
    let parent = target
        .parent()
        .ok_or_else(|| "La ruta del AppImage no tiene carpeta contenedora.".to_owned())?;
    let temporary = tempfile_path(parent)?;
    let result = (|| {
        let output = Command::new("curl")
            .args([
                "--fail",
                "--silent",
                "--show-error",
                "--location",
                "--max-time",
                "600",
                "--max-filesize",
                &expected_size.to_string(),
                "--proto",
                "=https",
                "--proto-redir",
                "=https",
                "--output",
            ])
            .arg(&temporary)
            .arg(address)
            .output()
            .map_err(|error| format!("No se pudo iniciar curl: {error}"))?;
        if !output.status.success() {
            return Err(String::from_utf8_lossy(&output.stderr).trim().to_owned());
        }
        let size = fs::metadata(&temporary)
            .map_err(|error| error.to_string())?
            .len();
        if size != expected_size {
            return Err("La descarga está incompleta o su tamaño no coincide.".into());
        }
        let hash = Command::new("sha256sum")
            .arg(&temporary)
            .output()
            .map_err(|error| format!("No se pudo verificar SHA-256 con sha256sum: {error}"))?;
        if !hash.status.success()
            || String::from_utf8_lossy(&hash.stdout)
                .split_whitespace()
                .next()
                .is_none_or(|actual| !actual.eq_ignore_ascii_case(checksum))
        {
            return Err("La descarga está incompleta o su SHA-256 no coincide; se conserva la versión anterior.".into());
        }
        let mut image = fs::File::open(&temporary).map_err(|error| error.to_string())?;
        let mut header = [0; 11];
        std::io::Read::read_exact(&mut image, &mut header)
            .map_err(|_| "El archivo descargado no es un AppImage válido.".to_owned())?;
        if &header[..4] != b"\x7fELF" || &header[8..11] != b"AI\x02" {
            return Err("El archivo descargado no es un AppImage válido.".into());
        }
        fs::set_permissions(
            &temporary,
            fs::metadata(&target)
                .map_err(|error| error.to_string())?
                .permissions(),
        )
        .map_err(|error| error.to_string())?;
        fs::rename(&temporary, &target).map_err(|error| error.to_string())?;
        let _ = fs::File::open(parent).and_then(|directory| directory.sync_all());
        Ok(release.version.clone())
    })();
    let _ = fs::remove_file(&temporary);
    result
}

fn version_parts(value: &str) -> Result<(u64, u64, u64), String> {
    let mut parts = value.split('.');
    let values = (parts.next(), parts.next(), parts.next(), parts.next());
    match values {
        (Some(major), Some(minor), Some(patch), None) => Ok((
            major.parse().map_err(|_| {
                "La publicación no tiene una versión válida (ejemplo: v0.1.0).".to_owned()
            })?,
            minor.parse().map_err(|_| {
                "La publicación no tiene una versión válida (ejemplo: v0.1.0).".to_owned()
            })?,
            patch.parse().map_err(|_| {
                "La publicación no tiene una versión válida (ejemplo: v0.1.0).".to_owned()
            })?,
        )),
        _ => Err("La publicación no tiene una versión válida (ejemplo: v0.1.0).".into()),
    }
}

fn tempfile_path(parent: &Path) -> Result<PathBuf, String> {
    for attempt in 0..32 {
        let path = parent.join(format!(".estante-update-{}-{attempt}", std::process::id()));
        match fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)
        {
            Ok(mut file) => {
                file.flush().map_err(|error| error.to_string())?;
                drop(file);
                return Ok(path);
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => {
                return Err(format!(
                    "No se puede crear una descarga temporal junto al AppImage: {error}"
                ));
            }
        }
    }
    Err("No se pudo reservar un nombre temporal para la actualización.".into())
}
