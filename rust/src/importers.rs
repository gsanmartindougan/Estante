use serde_json::{Map, Value};
use std::collections::HashSet;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

pub fn steam(home: &Path, data: &Path) -> io::Result<Vec<Value>> {
    let flatpak = home.join(".var/app/com.valvesoftware.Steam");
    let candidates = [
        (data.join("Steam"), "native"),
        (home.join(".steam/steam"), "native"),
        (home.join(".steam/root"), "native"),
        (home.join(".steam/debian-installation"), "native"),
        (flatpak.join(".local/share/Steam"), "flatpak"),
        (flatpak.join(".steam/steam"), "flatpak"),
        (flatpak.join(".steam/root"), "flatpak"),
    ];
    let mut roots = Vec::<(PathBuf, &str)>::new();
    let mut seen_roots = HashSet::new();
    for (candidate, install) in candidates {
        let Ok(root) = candidate.canonicalize() else {
            continue;
        };
        if root.is_dir() && seen_roots.insert(root.clone()) {
            roots.push((root, install));
        }
    }

    let mut games = Map::new();
    for (root, install) in roots {
        let mut libraries = vec![root.clone()];
        for registry in [
            root.join("steamapps/libraryfolders.vdf"),
            root.join("config/libraryfolders.vdf"),
        ] {
            let Ok(vdf) = read_vdf(&registry) else {
                continue;
            };
            if let Some(folders) = vdf.get("libraryfolders").and_then(Value::as_object) {
                for item in folders.values() {
                    let path = item
                        .get("path")
                        .and_then(Value::as_str)
                        .or_else(|| item.as_str());
                    if let Some(path) = path {
                        libraries.push(expand_tilde(path, home));
                    }
                }
            }
        }
        let mut seen_libraries = HashSet::new();
        for library in libraries {
            let Ok(library) = library.canonicalize() else {
                continue;
            };
            if !seen_libraries.insert(library.clone()) {
                continue;
            }
            let steamapps = library.join("steamapps");
            let Ok(entries) = fs::read_dir(&steamapps) else {
                continue;
            };
            for entry in entries.flatten() {
                let name = entry.file_name();
                let name = name.to_string_lossy();
                if !name.starts_with("appmanifest_") || !name.ends_with(".acf") {
                    continue;
                }
                let Ok(vdf) = read_vdf(&entry.path()) else {
                    continue;
                };
                let Some(row) = vdf.get("appstate").and_then(Value::as_object) else {
                    continue;
                };
                let app_id = row.get("appid").and_then(Value::as_str).unwrap_or_default();
                let title = row
                    .get("name")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .trim();
                if app_id.parse::<u64>().unwrap_or(0) == 0 || title.is_empty() {
                    continue;
                }
                let folded = title.to_lowercase();
                if [
                    "proton ",
                    "steam linux runtime",
                    "steamworks common redistributables",
                ]
                .iter()
                .any(|prefix| folded.starts_with(prefix))
                {
                    continue;
                }
                if row
                    .get("stateflags")
                    .and_then(Value::as_str)
                    .unwrap_or("4")
                    .parse::<u64>()
                    .unwrap_or(0)
                    & 4
                    == 0
                {
                    continue;
                }
                let install_dir = row
                    .get("installdir")
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                if install_dir.is_empty() {
                    continue;
                }
                let common = steamapps.join("common");
                let Ok(common) = common.canonicalize() else {
                    continue;
                };
                let Ok(game_path) = common.join(install_dir).canonicalize() else {
                    continue;
                };
                if !game_path.is_dir() || !game_path.starts_with(&common) {
                    continue;
                }

                let mut game = Map::new();
                insert(&mut game, "id", format!("steam:{app_id}"));
                insert(&mut game, "kind", "steam");
                insert(&mut game, "steam_appid", app_id);
                insert(&mut game, "title", title);
                insert(&mut game, "install", install);
                insert(&mut game, "path", game_path.to_string_lossy());
                insert(&mut game, "cover", "");
                for (field, stem) in [
                    ("cover", "library_600x900"),
                    ("banner", "library_hero"),
                    ("logo", "logo"),
                ] {
                    for ext in ["jpg", "png"] {
                        let candidate = root
                            .join("appcache/librarycache")
                            .join(format!("{app_id}_{stem}.{ext}"));
                        if candidate.is_file() {
                            insert(&mut game, field, candidate.to_string_lossy());
                            break;
                        }
                    }
                }
                games
                    .entry(format!("steam:{app_id}"))
                    .or_insert(Value::Object(game));
            }
        }
    }
    let mut result = games.into_values().collect::<Vec<_>>();
    result.sort_by_key(|game| {
        game.get("title")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_lowercase()
    });
    Ok(result)
}

pub fn faugus(home: &Path, data: &Path, config: &Path) -> io::Result<Vec<Value>> {
    let sources = [
        (data.join("faugus-launcher"), "native"),
        (config.join("faugus-launcher"), "native"),
        (
            home.join(".var/app/io.github.Faugus.faugus-launcher/data/faugus-launcher"),
            "flatpak",
        ),
        (
            home.join(".var/app/io.github.Faugus.faugus-launcher/config/faugus-launcher"),
            "flatpak",
        ),
    ];
    let mut games = Map::<String, Value>::new();
    for (directory, install) in sources {
        let path = directory.join("games.json");
        let Ok(bytes) = fs::read(path) else { continue };
        let Ok(rows) = serde_json::from_slice::<Value>(&bytes) else {
            continue;
        };
        let Some(rows) = rows.as_array() else {
            continue;
        };
        for row in rows {
            let Some(source) = row.as_object() else {
                continue;
            };
            let Some(game_id) = source
                .get("gameid")
                .filter(|value| !value.is_null())
                .map(value_string)
            else {
                continue;
            };
            if game_id.is_empty()
                || source
                    .get("hidden")
                    .and_then(Value::as_bool)
                    .unwrap_or(false)
                || faugus_steam(source)
            {
                continue;
            }
            let identity = format!("faugus:{install}:{game_id}");
            if games.contains_key(&identity) {
                continue;
            }
            let mut game = source.clone();
            insert(&mut game, "id", &identity);
            insert(&mut game, "kind", "faugus");
            insert(&mut game, "install", install);
            let supplied = game.get("cover").and_then(Value::as_str).map(PathBuf::from);
            let cover = supplied
                .filter(|path| path.is_file())
                .unwrap_or_else(|| directory.join("covers").join(format!("{game_id}.png")));
            insert(
                &mut game,
                "cover",
                if cover.is_file() {
                    cover.to_string_lossy()
                } else {
                    "".into()
                },
            );
            games.insert(identity, Value::Object(game));
        }
    }
    let mut result = games.into_values().collect::<Vec<_>>();
    result.sort_by_key(|game| {
        game.get("title")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_lowercase()
    });
    Ok(result)
}

pub fn heroic(home: &Path, config: &Path) -> io::Result<Vec<Value>> {
    let roots = [
        (config.join("heroic"), "native"),
        (
            home.join(".var/app/com.heroicgameslauncher.hgl/config/heroic"),
            "flatpak",
        ),
    ];
    let mut games = Map::<String, Value>::new();
    for (root, install) in roots {
        if !root.is_dir() {
            continue;
        }
        let mut caches = std::collections::HashMap::<
            String,
            std::collections::HashMap<String, Map<String, Value>>,
        >::new();
        for (runner, filename, key) in [
            ("gog", "gog_library", "games"),
            ("nile", "nile_library", "library"),
        ] {
            let data = read_json(&root.join("store_cache").join(format!("{filename}.json")))?;
            let rows = rows(data.get(key));
            let cache = rows
                .into_iter()
                .filter_map(|row| {
                    let name = row.get("app_name")?.as_str()?.to_owned();
                    Some((name, row.as_object()?.clone()))
                })
                .collect();
            caches.insert(runner.to_owned(), cache);
        }

        let mut epic = root.join("legendaryConfig/legendary");
        if !epic.join("installed.json").is_file() {
            epic = root.parent().unwrap_or(&root).join("legendary");
        }
        let legendary_installed = read_json(&epic.join("installed.json"))?;
        let gog_installed = read_json(&root.join("gog_store/installed.json"))?;
        let nile_installed = read_json(&root.join("nile_config/nile/installed.json"))?;
        let sideload_installed = read_json(&root.join("sideload_apps/library.json"))?;
        let manifests = [
            ("legendary", rows(Some(&legendary_installed))),
            ("gog", rows(gog_installed.get("installed"))),
            ("nile", rows(Some(&nile_installed))),
            ("sideload", rows(sideload_installed.get("games"))),
        ];
        let nile_library = read_json(&root.join("nile_config/nile/library.json"))?;
        let mut amazon = Map::<String, Value>::new();
        for row in rows(Some(&nile_library)) {
            if let Some(product) = row
                .get("product")
                .filter(|product| product.get("id").is_some())
            {
                let id = value_string(product.get("id").unwrap());
                amazon.insert(id, product.clone());
            }
        }

        for (runner, installed) in manifests {
            for entry in installed {
                let name = match runner {
                    "legendary" => entry.get("app_name"),
                    "gog" => entry
                        .get("appName")
                        .or_else(|| entry.get("manifest").and_then(|item| item.get("app_name"))),
                    "nile" => entry.get("id"),
                    _ => entry.get("app_name"),
                }
                .map(value_string)
                .unwrap_or_default();
                if name.is_empty() || name.contains('\0') {
                    continue;
                }
                let mut metadata = caches
                    .get(runner)
                    .and_then(|cache| cache.get(&name))
                    .cloned()
                    .unwrap_or_default();
                if runner == "legendary"
                    && Path::new(&name)
                        .file_name()
                        .is_some_and(|leaf| leaf == name.as_str())
                {
                    let epic_data = read_json(&epic.join("metadata").join(format!("{name}.json")))?;
                    if let Some(title) = epic_data.get("app_title") {
                        metadata.insert("title".into(), title.clone());
                    }
                    if let Some(images) = epic_data
                        .get("metadata")
                        .and_then(|item| item.get("keyImages"))
                        .and_then(Value::as_array)
                    {
                        for image in images {
                            let field = match image
                                .get("type")
                                .and_then(Value::as_str)
                                .unwrap_or_default()
                            {
                                "DieselGameBoxTall" | "OfferImageTall" => Some("art_cover"),
                                "DieselGameBox" => Some("art_square"),
                                "OfferImageWide" => Some("art_background"),
                                _ => None,
                            };
                            if let (Some(field), Some(url)) = (field, image.get("url")) {
                                metadata.insert(field.into(), url.clone());
                            }
                        }
                    }
                } else if runner == "nile" && metadata.is_empty() {
                    if let Some(product) = amazon.get(&name) {
                        let detail = product.get("productDetail").unwrap_or(&Value::Null);
                        let details = detail.get("details").unwrap_or(&Value::Null);
                        metadata.insert(
                            "title".into(),
                            product.get("title").cloned().unwrap_or(Value::Null),
                        );
                        for (key, value) in [
                            (
                                "art_cover",
                                details
                                    .get("backgroundUrl2")
                                    .or_else(|| detail.get("iconUrl")),
                            ),
                            ("art_background", details.get("backgroundUrl1")),
                            ("art_square", detail.get("iconUrl")),
                            ("art_logo", details.get("logoUrl")),
                        ] {
                            if let Some(value) = value {
                                metadata.insert(key.into(), value.clone());
                            }
                        }
                    }
                } else if runner == "sideload" {
                    metadata = entry.as_object().cloned().unwrap_or_default();
                }
                let detail = if runner == "sideload" {
                    entry.get("install").unwrap_or(&Value::Null)
                } else {
                    &entry
                };
                if !detail.is_object()
                    || detail
                        .get("is_dlc")
                        .and_then(Value::as_bool)
                        .unwrap_or(false)
                    || metadata
                        .get("is_dlc")
                        .and_then(Value::as_bool)
                        .unwrap_or(false)
                    || entry.get("is_installed").and_then(Value::as_bool) == Some(false)
                {
                    continue;
                }
                let directory = if runner == "nile" {
                    detail.get("path")
                } else {
                    detail.get("install_path")
                }
                .and_then(Value::as_str)
                .filter(|value| !value.is_empty());
                let executable = detail
                    .get("executable")
                    .and_then(Value::as_str)
                    .unwrap_or_default();
                let directory = match directory {
                    Some(path) => expand_tilde(path, home),
                    None if runner == "sideload" && !executable.is_empty() => Path::new(executable)
                        .parent()
                        .unwrap_or(Path::new("."))
                        .to_path_buf(),
                    _ => continue,
                };
                if !directory.is_dir() {
                    continue;
                }
                if runner == "sideload"
                    && !executable.is_empty()
                    && !directory.join(executable.replace('\\', "/")).is_file()
                {
                    continue;
                }
                let identity = format!("heroic:{runner}:{name}");
                if games.contains_key(&identity) {
                    continue;
                }
                let title = entry
                    .get("title")
                    .or_else(|| metadata.get("title"))
                    .or_else(|| amazon.get(&name).and_then(|product| product.get("title")))
                    .map(value_string)
                    .filter(|value| !value.is_empty())
                    .unwrap_or_else(|| name.clone());
                let mut game = Map::new();
                insert(&mut game, "id", &identity);
                insert(&mut game, "kind", "heroic");
                insert(&mut game, "install", install);
                insert(&mut game, "heroic_app_name", &name);
                insert(&mut game, "heroic_runner", runner);
                insert(&mut game, "title", title);
                insert(&mut game, "path", directory.to_string_lossy());
                insert(&mut game, "cover", "");
                if !executable.is_empty() {
                    insert(
                        &mut game,
                        "executable",
                        directory
                            .join(executable.replace('\\', "/"))
                            .to_string_lossy(),
                    );
                }
                let mut remote = Map::new();
                for (field, art) in [
                    ("cover", "art_cover"),
                    ("square_cover", "art_square"),
                    ("banner", "art_background"),
                    ("logo", "art_logo"),
                ] {
                    let Some(value) = metadata.get(art).and_then(Value::as_str) else {
                        continue;
                    };
                    if let Some(local) = local_art(value, &root) {
                        insert(&mut game, field, local.to_string_lossy());
                    } else if value.starts_with("https://") {
                        remote.insert(field.into(), Value::String(value.to_owned()));
                    }
                }
                if !remote.is_empty() {
                    game.insert("heroic_artwork".into(), Value::Object(remote));
                }
                games.insert(identity, Value::Object(game));
            }
        }
    }
    let mut result = games.into_values().collect::<Vec<_>>();
    result.sort_by_key(|game| {
        game.get("title")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_lowercase()
    });
    Ok(result)
}

pub fn recomp(home: &Path, data: &Path) -> io::Result<Vec<Value>> {
    let data_id = "com.recomplauncher.app";
    let flatpak_id = "com.recomplauncher.RecompLauncher";
    let roots = [
        (data.join(data_id), "native"),
        (
            home.join(".var/app")
                .join(flatpak_id)
                .join("data")
                .join(data_id),
            "flatpak",
        ),
    ];
    let mut games = Map::<String, Value>::new();
    for (root, install) in roots {
        let library = read_json(&root.join("library.json"))?;
        let Some(installed) = library.get("installed").and_then(Value::as_object) else {
            continue;
        };
        let catalog = read_json(&root.join("cache/pc-catalog.json")).unwrap_or(Value::Null);
        let catalog_apps = catalog.get("apps").and_then(Value::as_array);
        for (game_id, entry) in installed {
            let Some(entry) = entry.as_object() else {
                continue;
            };
            if game_id.is_empty() || game_id.contains('\0') {
                continue;
            }
            let Some(directory) = entry
                .get("path")
                .and_then(Value::as_str)
                .filter(|path| !path.is_empty())
            else {
                continue;
            };
            let directory = PathBuf::from(directory);
            if !directory.is_absolute() || !directory.is_dir() {
                continue;
            }
            let identity = format!("recomp:{game_id}");
            if games.contains_key(&identity) {
                continue;
            }
            let catalog_title = catalog_apps
                .into_iter()
                .flatten()
                .find(|app| app.get("id").and_then(Value::as_str) == Some(game_id))
                .and_then(|app| app.get("game"))
                .and_then(Value::as_str)
                .filter(|title| !title.is_empty());
            let title = entry
                .get("game")
                .and_then(Value::as_str)
                .filter(|title| !title.is_empty())
                .or(catalog_title)
                .or_else(|| {
                    entry
                        .get("name")
                        .and_then(Value::as_str)
                        .filter(|title| !title.is_empty())
                })
                .unwrap_or(game_id);
            let mut game = Map::new();
            insert(&mut game, "id", &identity);
            insert(&mut game, "kind", "recomp");
            insert(&mut game, "recomp_id", game_id);
            insert(&mut game, "install", install);
            insert(&mut game, "title", title);
            insert(&mut game, "path", directory.to_string_lossy());
            let cover = entry
                .get("cover_file")
                .and_then(Value::as_str)
                .filter(|cover| !cover.is_empty())
                .map(PathBuf::from)
                .map(|cover| {
                    if cover.is_absolute() {
                        cover
                    } else {
                        root.join(cover)
                    }
                })
                .filter(|cover| cover.is_file());
            insert(
                &mut game,
                "cover",
                cover
                    .map(|cover| cover.to_string_lossy().into_owned())
                    .unwrap_or_default(),
            );
            games.insert(identity, Value::Object(game));
        }
    }
    let mut result = games.into_values().collect::<Vec<_>>();
    result.sort_by_key(|game| {
        game.get("title")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_lowercase()
    });
    Ok(result)
}

fn faugus_steam(game: &Map<String, Value>) -> bool {
    game.get("runner")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .eq_ignore_ascii_case("steam")
        || game
            .get("path")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .trim()
            .to_lowercase()
            .starts_with("steam://")
}

fn value_string(value: &Value) -> String {
    value
        .as_str()
        .map(str::to_owned)
        .unwrap_or_else(|| value.to_string())
}

fn read_json(path: &Path) -> io::Result<Value> {
    match fs::read(path) {
        Ok(bytes) => serde_json::from_slice(&bytes)
            .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error)),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(Value::Null),
        Err(error) => Err(error),
    }
}

fn rows(value: Option<&Value>) -> Vec<Value> {
    match value {
        Some(Value::Array(rows)) => rows.iter().filter(|row| row.is_object()).cloned().collect(),
        Some(Value::Object(rows)) => rows
            .iter()
            .filter_map(|(name, row)| {
                let mut row = row.as_object()?.clone();
                row.entry("app_name")
                    .or_insert_with(|| Value::String(name.clone()));
                Some(Value::Object(row))
            })
            .collect(),
        _ => Vec::new(),
    }
}

fn local_art(value: &str, root: &Path) -> Option<PathBuf> {
    if value.is_empty() || (value.contains("://") && !value.starts_with("file://")) {
        return None;
    }
    let value = if let Some(value) = value.strip_prefix("file://") {
        percent_decode(value)?
    } else {
        value.to_owned()
    };
    let path = PathBuf::from(value);
    let path = if path.is_absolute() {
        path
    } else {
        root.join(path)
    };
    path.is_file().then_some(path)
}

fn percent_decode(value: &str) -> Option<String> {
    let bytes = value.as_bytes();
    let mut decoded = Vec::with_capacity(bytes.len());
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] == b'%' {
            let pair = std::str::from_utf8(bytes.get(index + 1..index + 3)?).ok()?;
            decoded.push(u8::from_str_radix(pair, 16).ok()?);
            index += 3;
        } else {
            decoded.push(bytes[index]);
            index += 1;
        }
    }
    String::from_utf8(decoded).ok()
}

fn insert(game: &mut Map<String, Value>, key: &str, value: impl ToString) {
    game.insert(key.to_owned(), Value::String(value.to_string()));
}

fn expand_tilde(path: &str, home: &Path) -> PathBuf {
    path.strip_prefix("~/")
        .map_or_else(|| PathBuf::from(path), |tail| home.join(tail))
}

fn read_vdf(path: &Path) -> io::Result<Value> {
    let text = fs::read_to_string(path)?;
    let tokens = tokenize_vdf(&text)?;
    let mut parser = VdfParser { tokens, index: 0 };
    let result = parser.block(false)?;
    if parser.index != parser.tokens.len() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "datos VDF posteriores al bloque raíz",
        ));
    }
    Ok(Value::Object(result))
}

#[derive(Debug)]
enum Token {
    Text(String),
    Open,
    Close,
}

fn tokenize_vdf(text: &str) -> io::Result<Vec<Token>> {
    let mut chars = text.chars().peekable();
    let mut tokens = Vec::new();
    while let Some(ch) = chars.next() {
        if ch.is_whitespace() {
            continue;
        }
        if ch == '/' && chars.peek() == Some(&'/') {
            chars.next();
            for next in chars.by_ref() {
                if next == '\n' {
                    break;
                }
            }
            continue;
        }
        match ch {
            '{' => tokens.push(Token::Open),
            '}' => tokens.push(Token::Close),
            '"' => {
                let mut value = String::new();
                let mut escaped = false;
                let mut closed = false;
                for next in chars.by_ref() {
                    if escaped {
                        if next == '"' || next == '\\' {
                            value.push(next);
                        } else {
                            value.push('\\');
                            value.push(next);
                        }
                        escaped = false;
                    } else if next == '\\' {
                        escaped = true;
                    } else if next == '"' {
                        closed = true;
                        break;
                    } else {
                        value.push(next);
                    }
                }
                if !closed || escaped {
                    return Err(io::Error::new(
                        io::ErrorKind::InvalidData,
                        "cadena VDF sin cerrar",
                    ));
                }
                tokens.push(Token::Text(value));
            }
            _ => {
                let mut value = String::from(ch);
                while chars
                    .peek()
                    .is_some_and(|next| !next.is_whitespace() && *next != '{' && *next != '}')
                {
                    value.push(chars.next().unwrap());
                }
                tokens.push(Token::Text(value));
            }
        }
    }
    Ok(tokens)
}

struct VdfParser {
    tokens: Vec<Token>,
    index: usize,
}

impl VdfParser {
    fn block(&mut self, nested: bool) -> io::Result<Map<String, Value>> {
        let mut map = Map::new();
        while let Some(token) = self.tokens.get(self.index) {
            if matches!(token, Token::Close) {
                self.index += 1;
                if nested {
                    return Ok(map);
                }
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    "llave VDF de cierre inesperada",
                ));
            }
            let Token::Text(key) = token else {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    "clave VDF no válida",
                ));
            };
            let key = key.to_lowercase();
            self.index += 1;
            let Some(value) = self.tokens.get(self.index) else {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    "valor VDF ausente",
                ));
            };
            self.index += 1;
            let value = match value {
                Token::Text(value) => Value::String(value.clone()),
                Token::Open => Value::Object(self.block(true)?),
                Token::Close => {
                    return Err(io::Error::new(
                        io::ErrorKind::InvalidData,
                        "valor VDF ausente",
                    ));
                }
            };
            map.insert(key, value);
        }
        if nested {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "bloque VDF sin cerrar",
            ));
        }
        Ok(map)
    }
}
