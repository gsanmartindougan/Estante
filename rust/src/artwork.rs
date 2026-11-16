use serde_json::Value;
use std::{fs, path::Path, process::Command};

#[derive(Clone, Debug)]
pub struct ArtworkOption {
    pub id: String,
    pub game_id: String,
    pub name: String,
    pub url: String,
    pub provider: String,
}

pub fn search(key: &str, title: &str, field: &str) -> Result<Vec<ArtworkOption>, String> {
    let route = format!("search/autocomplete/{}", encode_path(title.trim()));
    let games = api(key, &route)?;
    let identity = games
        .iter()
        .find(|game| normalize(game["name"].as_str().unwrap_or_default()) == normalize(title));
    let game_id = identity
        .or_else(|| games.first())
        .and_then(|game| game["id"].as_u64())
        .ok_or_else(|| "No se encontró el juego en SteamGridDB.".to_owned())?;
    images_for_game(key, game_id, field)
}

pub fn exact_game_id(key: &str, title: &str) -> Result<Option<String>, String> {
    let games = api(
        key,
        &format!("search/autocomplete/{}", encode_path(title.trim())),
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
) -> Result<Vec<ArtworkOption>, String> {
    let id = game_id
        .parse::<u64>()
        .map_err(|_| "ID de SteamGridDB no válido.".to_owned())?;
    images_for_game(key, id, field)
}

fn images_for_game(key: &str, game_id: u64, field: &str) -> Result<Vec<ArtworkOption>, String> {
    let route = match field {
        "cover" => format!("grids/game/{game_id}?dimensions=600x900&types=static"),
        "square_cover" => format!("grids/game/{game_id}?dimensions=512x512,1024x1024&types=static"),
        "logo" => format!("logos/game/{game_id}?types=static"),
        "banner" | "banner_secondary" => format!("heroes/game/{game_id}?types=static"),
        _ => return Err("Campo de imagen no válido.".into()),
    };
    api(key, &route).map(|rows| {
        rows.iter()
            .filter_map(|row| {
                Some(ArtworkOption {
                    id: row["id"].as_u64()?.to_string(),
                    game_id: game_id.to_string(),
                    name: format!(
                        "{} × {}",
                        row["width"].as_u64().unwrap_or(0),
                        row["height"].as_u64().unwrap_or(0)
                    ),
                    url: row["url"].as_str()?.to_owned(),
                    provider: "steamgriddb".into(),
                })
            })
            .take(30)
            .collect()
    })
}

pub fn download(option: &ArtworkOption, root: &Path) -> Result<String, String> {
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
        _ => false,
    };
    if !valid_id || !valid_url {
        return Err("La dirección de imagen no pertenece al proveedor seleccionado.".into());
    }
    fs::create_dir_all(root).map_err(|error| error.to_string())?;
    let bytes = curl(&option.url, &[])?;
    image::load_from_memory(&bytes)
        .map_err(|_| "SteamGridDB devolvió una imagen no válida.".to_owned())?;
    let temporary = root.join(format!(".artwork-{}-{}.tmp", std::process::id(), option.id));
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
                });
            }
        }
    }
    Ok(images)
}

fn api(key: &str, route: &str) -> Result<Vec<Value>, String> {
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

fn curl(url: &str, extra: &[String]) -> Result<Vec<u8>, String> {
    if !url.starts_with("https://") {
        return Err("Solo se permiten direcciones HTTPS.".into());
    }
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
        "=https",
        "--proto-redir",
        "=https",
    ]);
    command.args(extra).arg(url);
    let output = command
        .output()
        .map_err(|error| format!("No se pudo iniciar curl: {error}"))?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_owned());
    }
    Ok(output.stdout)
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
