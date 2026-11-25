use serde_json::Value;
use std::{
    collections::hash_map::DefaultHasher,
    fs,
    hash::{Hash, Hasher},
    io::Read,
    path::Path,
    process::{Child, Command, Stdio},
    sync::atomic::{AtomicBool, Ordering},
    thread,
    time::Duration,
};

#[derive(Clone, Debug)]
pub struct ArtworkOption {
    pub id: String,
    pub game_id: String,
    pub name: String,
    pub url: String,
    pub preview_url: String,
    pub provider: String,
}

pub fn search(
    key: &str,
    title: &str,
    field: &str,
    cancelled: Option<&AtomicBool>,
) -> Result<Vec<ArtworkOption>, String> {
    let route = format!("search/autocomplete/{}", encode_path(title.trim()));
    let games = api(key, &route, cancelled)?;
    let identity = games
        .iter()
        .find(|game| normalize(game["name"].as_str().unwrap_or_default()) == normalize(title));
    let game_id = identity
        .or_else(|| games.first())
        .and_then(|game| game["id"].as_u64())
        .ok_or_else(|| "No se encontró el juego en SteamGridDB.".to_owned())?;
    images_for_game(key, game_id, field, cancelled)
}

pub fn search_games(
    key: &str,
    title: &str,
    cancelled: Option<&AtomicBool>,
) -> Result<Vec<ArtworkOption>, String> {
    let games = api(
        key,
        &format!("search/autocomplete/{}", encode_path(title.trim())),
        cancelled,
    )?;
    Ok(games
        .iter()
        .filter_map(|game| {
            Some(ArtworkOption {
                id: game["id"].as_u64()?.to_string(),
                game_id: game["id"].as_u64()?.to_string(),
                name: game["name"].as_str()?.to_owned(),
                url: String::new(),
                preview_url: String::new(),
                provider: "steamgriddb-game".into(),
            })
        })
        .take(30)
        .collect())
}

pub fn exact_game_id(key: &str, title: &str) -> Result<Option<String>, String> {
    let games = api(
        key,
        &format!("search/autocomplete/{}", encode_path(title.trim())),
        None,
    )?;
    let matches = games
        .iter()
        .filter(|game| normalize(game["name"].as_str().unwrap_or_default()) == normalize(title))
        .filter_map(|game| game["id"].as_u64())
        .collect::<Vec<_>>();
    Ok((matches.len() == 1).then(|| matches[0].to_string()))
}

pub fn search_for_game(
    key: &str,
    game_id: &str,
    field: &str,
    cancelled: Option<&AtomicBool>,
) -> Result<Vec<ArtworkOption>, String> {
    let id = game_id
        .parse::<u64>()
        .map_err(|_| "ID de SteamGridDB no válido.".to_owned())?;
    images_for_game(key, id, field, cancelled)
}

fn images_for_game(
    key: &str,
    game_id: u64,
    field: &str,
    cancelled: Option<&AtomicBool>,
) -> Result<Vec<ArtworkOption>, String> {
    let route = match field {
        "cover" => format!("grids/game/{game_id}?dimensions=600x900&types=static"),
        "square_cover" => format!("grids/game/{game_id}?dimensions=512x512,1024x1024&types=static"),
        "logo" => format!("logos/game/{game_id}?types=static"),
        "banner" | "banner_secondary" => format!("heroes/game/{game_id}?types=static"),
        _ => return Err("Campo de imagen no válido.".into()),
    };
    api(key, &route, cancelled).map(|rows| {
        rows.iter()
            .filter_map(|row| {
                let url = row["url"].as_str()?.to_owned();
                let preview_url = row["thumb"].as_str().unwrap_or(&url).to_owned();
                Some(ArtworkOption {
                    id: row["id"].as_u64()?.to_string(),
                    game_id: game_id.to_string(),
                    name: format!(
                        "{} × {}",
                        row["width"].as_u64().unwrap_or(0),
                        row["height"].as_u64().unwrap_or(0)
                    ),
                    url,
                    preview_url,
                    provider: "steamgriddb".into(),
                })
            })
            .collect()
    })
}

fn artwork_bytes(
    option: &ArtworkOption,
    cancelled: Option<&AtomicBool>,
) -> Result<Vec<u8>, String> {
    let valid_id = option
        .id
        .bytes()
        .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'-');
    let valid_url = match option.provider.as_str() {
        "steamgriddb" => {
            option.url.starts_with("https://cdn2.steamgriddb.com/")
                || option.url.starts_with("https://steamgriddb.com/")
        }
        "igdb" => option
            .url
            .starts_with("https://images.igdb.com/igdb/image/upload/"),
        "steam" => [
            "https://shared.akamai.steamstatic.com/",
            "https://cdn.akamai.steamstatic.com/",
            "https://store.cloudflare.steamstatic.com/",
        ]
        .iter()
        .any(|prefix| option.url.starts_with(prefix)),
        "custom" => {
            (option.url.starts_with("https://") || option.url.starts_with("http://"))
                && custom_host(&option.url)
        }
        _ => false,
    };
    if !valid_id || !valid_url {
        return Err("La dirección de imagen no pertenece al proveedor seleccionado.".into());
    }
    let bytes = curl(&option.url, &[], cancelled, option.provider == "custom")?;
    image::load_from_memory(&bytes)
        .map_err(|_| "El proveedor devolvió una imagen no válida.".to_owned())?;
    Ok(bytes)
}

pub fn download_custom(
    url: &str,
    root: &Path,
    identity: &str,
    cancelled: Option<&AtomicBool>,
) -> Result<String, String> {
    let mut hasher = DefaultHasher::new();
    identity.hash(&mut hasher);
    let option = ArtworkOption {
        id: format!("{:016x}", hasher.finish()),
        game_id: String::new(),
        name: String::new(),
        url: url.to_owned(),
        preview_url: String::new(),
        provider: "custom".into(),
    };
    download(&option, root, cancelled)
}

pub fn import_local(source: &Path, root: &Path) -> Result<String, String> {
    image::ImageReader::open(source)
        .map_err(|error| format!("No se pudo abrir el archivo: {error}"))?
        .with_guessed_format()
        .map_err(|_| "El archivo no es una imagen válida.".to_owned())?
        .decode()
        .map_err(|_| "El archivo no es una imagen válida.".to_owned())?;
    fs::create_dir_all(root).map_err(|error| error.to_string())?;
    static NEXT_IMPORT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let serial = NEXT_IMPORT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    let name = format!("local-{}-{serial}", std::process::id());
    let temporary = root.join(format!(".{name}.tmp"));
    let target = root.join(format!("{name}.img"));
    fs::copy(source, &temporary).map_err(|error| {
        let _ = fs::remove_file(&temporary);
        error.to_string()
    })?;
    fs::rename(&temporary, &target).map_err(|error| {
        let _ = fs::remove_file(&temporary);
        error.to_string()
    })?;
    Ok(target.to_string_lossy().into_owned())
}

fn custom_host(url: &str) -> bool {
    let Some(authority) = url
        .strip_prefix("https://")
        .or_else(|| url.strip_prefix("http://"))
        .and_then(|rest| rest.split(['/', '?', '#']).next())
    else {
        return false;
    };
    !authority.is_empty() && !authority.contains('@') && !authority.chars().any(char::is_whitespace)
}

pub fn preview(
    option: &ArtworkOption,
    cancelled: Option<&AtomicBool>,
) -> Result<image::RgbaImage, String> {
    let bytes = artwork_bytes(&preview_option(option), cancelled)?;
    image::load_from_memory(&bytes)
        .map(|image| image.thumbnail(240, 140).into_rgba8())
        .map_err(|error| error.to_string())
}

fn preview_option(option: &ArtworkOption) -> ArtworkOption {
    let mut preview = option.clone();
    if !option.preview_url.is_empty() {
        preview.url.clone_from(&option.preview_url);
    }
    preview
}

pub fn download(
    option: &ArtworkOption,
    root: &Path,
    cancelled: Option<&AtomicBool>,
) -> Result<String, String> {
    fs::create_dir_all(root).map_err(|error| error.to_string())?;
    let bytes = artwork_bytes(option, cancelled)?;
    static NEXT_DOWNLOAD: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let serial = NEXT_DOWNLOAD.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    let temporary = root.join(format!(
        ".artwork-{}-{serial}-{}.tmp",
        std::process::id(),
        option.id
    ));
    let target = root.join(format!("{}-{}.img", option.provider, option.id));
    fs::write(&temporary, bytes).map_err(|error| error.to_string())?;
    fs::rename(&temporary, &target).map_err(|error| {
        let _ = fs::remove_file(&temporary);
        error.to_string()
    })?;
    Ok(target.to_string_lossy().into_owned())
}

pub fn search_igdb(
    client_id: &str,
    client_secret: &str,
    title: &str,
    cancelled: Option<&AtomicBool>,
) -> Result<Vec<ArtworkOption>, String> {
    if client_id.trim().is_empty() || client_secret.is_empty() || title.trim().is_empty() {
        return Err("Configura las credenciales de IGDB y escribe un título.".into());
    }
    let form = format!(
        "client_id={}&client_secret={}&grant_type=client_credentials",
        encode_query(client_id.trim()),
        encode_query(client_secret)
    );
    let token_bytes = curl(
        "https://id.twitch.tv/oauth2/token",
        &[
            "-X".into(),
            "POST".into(),
            "-H".into(),
            "Content-Type: application/x-www-form-urlencoded".into(),
            "--data".into(),
            form,
        ],
        cancelled,
        false,
    )?;
    let token: Value = serde_json::from_slice(&token_bytes).map_err(|error| error.to_string())?;
    let token = token["access_token"]
        .as_str()
        .ok_or_else(|| "IGDB no devolvió un token de acceso.".to_owned())?;
    let query = format!(
        "search \"{}\"; fields id,name,artworks.image_id,artworks.width,artworks.height,screenshots.image_id,screenshots.width,screenshots.height; limit 20;",
        title.trim().replace('\\', "\\\\").replace('"', "\\\"")
    );
    let response = curl(
        "https://api.igdb.com/v4/games",
        &[
            "-X".into(),
            "POST".into(),
            "-H".into(),
            format!("Client-ID: {}", client_id.trim()),
            "-H".into(),
            format!("Authorization: Bearer {token}"),
            "-H".into(),
            "Accept: application/json".into(),
            "-H".into(),
            "Content-Type: text/plain".into(),
            "--data-binary".into(),
            query,
        ],
        cancelled,
        false,
    )?;
    let games: Value = serde_json::from_slice(&response).map_err(|error| error.to_string())?;
    let mut images = Vec::new();
    for game in games.as_array().into_iter().flatten() {
        let game_id = game["id"].as_u64().unwrap_or_default().to_string();
        for group in ["artworks", "screenshots"] {
            for image in game[group].as_array().into_iter().flatten() {
                let Some(id) = image["image_id"].as_str() else {
                    continue;
                };
                let width = image["width"].as_u64().unwrap_or(0);
                let height = image["height"].as_u64().unwrap_or(0);
                if !id
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'-')
                    || width < 1280
                    || height == 0
                    || (width as f64 / height as f64 - 16.0 / 9.0).abs() > 0.025
                {
                    continue;
                }
                images.push(ArtworkOption {
                    id: id.into(),
                    game_id: game_id.clone(),
                    provider: "igdb".into(),
                    name: format!(
                        "{} · {width} × {height}",
                        game["name"].as_str().unwrap_or("IGDB")
                    ),
                    url: format!("https://images.igdb.com/igdb/image/upload/t_original/{id}.jpg"),
                    preview_url: format!(
                        "https://images.igdb.com/igdb/image/upload/t_screenshot_med/{id}.jpg"
                    ),
                });
            }
        }
    }
    Ok(images)
}

pub fn search_steam(
    title: &str,
    cancelled: Option<&AtomicBool>,
) -> Result<Vec<ArtworkOption>, String> {
    if title.trim().is_empty() {
        return Err("Escribe el nombre del juego para buscar en Steam.".into());
    }
    let search_url = format!(
        "https://store.steampowered.com/api/storesearch/?term={}&l=spanish&cc=ES",
        encode_query(title.trim())
    );
    let search: Value = serde_json::from_slice(&curl(&search_url, &[], cancelled, false)?)
        .map_err(|error| error.to_string())?;
    let games = search["items"]
        .as_array()
        .ok_or("Steam no devolvió resultados.")?;
    let game = games
        .iter()
        .find(|game| normalize(game["name"].as_str().unwrap_or_default()) == normalize(title))
        .or_else(|| games.first())
        .ok_or("Steam no encontró el juego.")?;
    let app_id = game["id"]
        .as_u64()
        .ok_or("Steam devolvió un ID no válido.")?;
    let details_url =
        format!("https://store.steampowered.com/api/appdetails?appids={app_id}&l=spanish");
    let details: Value = serde_json::from_slice(&curl(&details_url, &[], cancelled, false)?)
        .map_err(|error| error.to_string())?;
    let app = &details[app_id.to_string()]["data"];
    if !details[app_id.to_string()]["success"]
        .as_bool()
        .unwrap_or(false)
    {
        return Err("Steam no tiene capturas disponibles para este juego.".into());
    }
    Ok(app["screenshots"]
        .as_array()
        .into_iter()
        .flatten()
        .enumerate()
        .filter_map(|(index, row)| {
            Some(ArtworkOption {
                id: format!("{app_id}-{index}"),
                game_id: app_id.to_string(),
                name: format!("Captura {}", index + 1),
                url: row["path_full"].as_str()?.to_owned(),
                preview_url: row["path_thumbnail"]
                    .as_str()
                    .unwrap_or_default()
                    .to_owned(),
                provider: "steam".into(),
            })
        })
        .collect())
}

fn api(key: &str, route: &str, cancelled: Option<&AtomicBool>) -> Result<Vec<Value>, String> {
    if key.trim().is_empty() {
        return Err("Añade tu clave de SteamGridDB en Ajustes.".into());
    }
    if route.starts_with('/') || route.contains("..") || !route.is_ascii() {
        return Err("Ruta SteamGridDB no válida.".into());
    }
    let url = format!("https://www.steamgriddb.com/api/v2/{route}");
    let bytes = curl(
        &url,
        &["-H".into(), format!("Authorization: Bearer {}", key.trim())],
        cancelled,
        false,
    )?;
    let response: Value = serde_json::from_slice(&bytes).map_err(|error| error.to_string())?;
    if !response["success"].as_bool().unwrap_or(false) {
        return Err("SteamGridDB no pudo completar la búsqueda.".into());
    }
    response["data"]
        .as_array()
        .cloned()
        .ok_or_else(|| "Respuesta de SteamGridDB no válida.".into())
}

fn curl_protocols(url: &str, allow_http: bool) -> Result<&'static str, String> {
    if url.starts_with("https://") {
        Ok(if allow_http { "=http,https" } else { "=https" })
    } else if allow_http && url.starts_with("http://") {
        Ok("=http,https")
    } else {
        Err("Solo se permiten direcciones HTTPS.".into())
    }
}

fn curl(
    url: &str,
    extra: &[String],
    cancelled: Option<&AtomicBool>,
    allow_http: bool,
) -> Result<Vec<u8>, String> {
    let allowed_protocols = curl_protocols(url, allow_http)?;
    let mut command = Command::new("curl");
    command.args([
        "--fail",
        "--silent",
        "--show-error",
        "--location",
        "--max-time",
        "20",
        "--max-filesize",
        "25000000",
        "--proto",
        allowed_protocols,
        "--proto-redir",
        allowed_protocols,
    ]);
    if allow_http {
        command.args(["--user-agent", "Estante/0.1"]);
    }
    command.args(extra).arg(url);
    let child = command
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| format!("No se pudo iniciar curl: {error}"))?;
    let (status, stdout, stderr) = collect_child_output(child, cancelled)?;
    if !status.success() {
        return Err(String::from_utf8_lossy(&stderr).trim().to_owned());
    }
    Ok(stdout)
}

fn collect_child_output(
    mut child: Child,
    cancelled: Option<&AtomicBool>,
) -> Result<(std::process::ExitStatus, Vec<u8>, Vec<u8>), String> {
    let mut stdout = child
        .stdout
        .take()
        .ok_or_else(|| "No se pudo leer la respuesta.".to_owned())?;
    let mut stderr = child
        .stderr
        .take()
        .ok_or_else(|| "No se pudo leer el error de la respuesta.".to_owned())?;
    let stdout_reader = thread::spawn(move || {
        let mut bytes = Vec::new();
        stdout.read_to_end(&mut bytes).map(|_| bytes)
    });
    let stderr_reader = thread::spawn(move || {
        let mut bytes = Vec::new();
        stderr.read_to_end(&mut bytes).map(|_| bytes)
    });
    let status = loop {
        if cancelled.is_some_and(|flag| flag.load(Ordering::Relaxed)) {
            let _ = child.kill();
            let _ = child.wait();
            let _ = stdout_reader.join();
            let _ = stderr_reader.join();
            return Err("Solicitud cancelada.".into());
        }
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) => thread::sleep(Duration::from_millis(20)),
            Err(error) => {
                let _ = child.kill();
                let _ = child.wait();
                let _ = stdout_reader.join();
                let _ = stderr_reader.join();
                return Err(error.to_string());
            }
        }
    };
    let stdout = stdout_reader
        .join()
        .map_err(|_| "No se pudo leer la respuesta.".to_owned())?
        .map_err(|error| error.to_string())?;
    let stderr = stderr_reader
        .join()
        .map_err(|_| "No se pudo leer el error de la respuesta.".to_owned())?
        .map_err(|error| error.to_string())?;
    Ok((status, stdout, stderr))
}

fn normalize(value: &str) -> String {
    value
        .chars()
        .filter(|char| char.is_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect()
}

fn encode_path(value: &str) -> String {
    value.bytes().fold(String::new(), |mut encoded, byte| {
        if byte.is_ascii_alphanumeric() || b"-_.~".contains(&byte) {
            encoded.push(byte as char);
        } else {
            use std::fmt::Write;
            let _ = write!(encoded, "%{byte:02X}");
        }
        encoded
    })
}

fn encode_query(value: &str) -> String {
    value.bytes().fold(String::new(), |mut encoded, byte| {
        if byte.is_ascii_alphanumeric() || b"-_.~".contains(&byte) {
            encoded.push(byte as char);
        } else {
            use std::fmt::Write;
            let _ = write!(encoded, "%{byte:02X}");
        }
        encoded
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        sync::{Arc, atomic::AtomicBool},
        time::Instant,
    };

    #[test]
    fn previews_reject_untrusted_sources_before_downloading() {
        for (id, url, provider) in [
            ("1", "https://example.com/image.png", "steamgriddb"),
            (
                "../outside",
                "https://cdn2.steamgriddb.com/image.png",
                "steamgriddb",
            ),
            (
                "1",
                "https://images.igdb.com.evil.test/igdb/image/upload/a.jpg",
                "igdb",
            ),
        ] {
            let option = ArtworkOption {
                id: id.into(),
                game_id: "1".into(),
                name: "test".into(),
                url: url.into(),
                preview_url: String::new(),
                provider: provider.into(),
            };
            assert!(preview(&option, None).unwrap_err().contains("proveedor"));
        }
        let untrusted_thumbnail = ArtworkOption {
            id: "1".into(),
            game_id: "1".into(),
            name: "test".into(),
            url: "https://cdn2.steamgriddb.com/full.png".into(),
            preview_url: "https://example.com/thumb.png".into(),
            provider: "steamgriddb".into(),
        };
        assert!(
            preview(&untrusted_thumbnail, None)
                .unwrap_err()
                .contains("proveedor")
        );
    }

    #[test]
    fn artwork_previews_use_thumbnail_urls_and_keep_original_download_urls() {
        let option = ArtworkOption {
            id: "1".into(),
            game_id: "1".into(),
            name: "test".into(),
            url: "https://cdn2.steamgriddb.com/full.png".into(),
            preview_url: "https://cdn2.steamgriddb.com/thumb.png".into(),
            provider: "steamgriddb".into(),
        };
        assert_eq!(preview_option(&option).url, option.preview_url);
        assert_eq!(option.url, "https://cdn2.steamgriddb.com/full.png");
    }

    #[test]
    fn custom_artwork_accepts_http_while_provider_requests_require_https() {
        assert_eq!(
            curl_protocols("http://example.com/image.png", true).unwrap(),
            "=http,https"
        );
        assert_eq!(
            curl_protocols("https://example.com/image.png", false).unwrap(),
            "=https"
        );
        assert!(
            curl_protocols("http://example.com/image.png", false)
                .unwrap_err()
                .contains("HTTPS")
        );
    }

    #[cfg(unix)]
    #[test]
    fn obsolete_artwork_request_kills_curl_child() {
        let child = Command::new("sleep")
            .arg("10")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        let cancelled = Arc::new(AtomicBool::new(false));
        let signal = cancelled.clone();
        thread::spawn(move || {
            thread::sleep(Duration::from_millis(40));
            signal.store(true, Ordering::Relaxed);
        });
        let started = Instant::now();
        assert!(
            collect_child_output(child, Some(&cancelled))
                .unwrap_err()
                .contains("cancelada")
        );
        assert!(started.elapsed() < Duration::from_secs(1));
    }
}
