use serde_json::{Map, Value};
use std::{
    collections::{HashMap, HashSet},
    fs,
    path::Path,
    process::Command,
    sync::{Mutex, OnceLock},
    time::{Duration, Instant},
};

#[derive(Debug, Clone)]
pub struct MetadataOption {
    pub id: String,
    pub name: String,
    pub description: String,
}

pub fn steam(app_id: &str) -> Result<Map<String, Value>, String> {
    if app_id.is_empty() || !app_id.bytes().all(|byte| byte.is_ascii_digit()) {
        return Err("Identificador de Steam no válido.".into());
    }
    let url = format!("https://store.steampowered.com/api/appdetails?appids={app_id}&l=spanish");
    let output = Command::new("curl")
        .args([
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--max-time",
            "20",
            "--proto",
            "=https",
            "--proto-redir",
            "=https",
        ])
        .arg(url)
        .output()
        .map_err(|error| format!("No se pudo iniciar curl: {error}"))?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_owned());
    }
    let response: Value =
        serde_json::from_slice(&output.stdout).map_err(|error| error.to_string())?;
    let data = &response[app_id]["data"];
    if !response[app_id]["success"].as_bool().unwrap_or(false) {
        return Err("Steam no tiene una ficha disponible para este juego.".into());
    }
    let mut metadata = Map::new();
    put_string(&mut metadata, "title", data["name"].as_str());
    put_string(
        &mut metadata,
        "description",
        data["short_description"]
            .as_str()
            .map(strip_html)
            .as_deref(),
    );
    put_string(
        &mut metadata,
        "synopsis",
        data["short_description"]
            .as_str()
            .map(strip_html)
            .as_deref(),
    );
    put_string(
        &mut metadata,
        "release_date",
        data["release_date"]["date"].as_str(),
    );
    for key in ["developers", "publishers"] {
        if let Some(values) = data[key].as_array() {
            metadata.insert(
                key.into(),
                Value::Array(
                    values
                        .iter()
                        .filter_map(Value::as_str)
                        .map(|value| Value::String(value.to_owned()))
                        .collect(),
                ),
            );
        }
    }
    if let Some(genres) = data["genres"].as_array() {
        metadata.insert(
            "genres".into(),
            Value::Array(
                genres
                    .iter()
                    .filter_map(|row| row["description"].as_str())
                    .map(|value| Value::String(value.to_owned()))
                    .collect(),
            ),
        );
    }
    if let Some(platforms) = data["platforms"].as_object() {
        let names = [
            ("windows", "Microsoft Windows"),
            ("mac", "macOS"),
            ("linux", "Linux"),
        ]
        .into_iter()
        .filter(|(key, _)| platforms[*key].as_bool().unwrap_or(false))
        .map(|(_, name)| Value::String(name.into()))
        .collect();
        metadata.insert("platforms".into(), Value::Array(names));
    }
    metadata.insert(
        "source".into(),
        Value::String(format!("https://store.steampowered.com/app/{app_id}/")),
    );
    metadata.insert("steam_appid".into(), Value::String(app_id.into()));
    Ok(metadata)
}

pub fn scrape_game(
    title: &str,
    current: &Map<String, Value>,
    steamgriddb_key: &str,
    artwork_cache: &Path,
    metadata_cache: &Path,
    replace: bool,
    language: &str,
) -> (Map<String, Value>, Vec<String>) {
    const ART: &[&str] = &[
        "cover",
        "square_cover",
        "logo",
        "banner",
        "banner_secondary",
    ];
    const INFO: &[&str] = &[
        "description",
        "developers",
        "publishers",
        "genres",
        "platforms",
        "release_date",
    ];
    let mut patch = Map::new();
    let mut errors = Vec::new();
    let wanted = ART
        .iter()
        .copied()
        .filter(|field| {
            replace
                || !current
                    .get(*field)
                    .and_then(Value::as_str)
                    .is_some_and(|path| Path::new(path).is_file())
        })
        .collect::<Vec<_>>();
    let mut sgdb_id = current
        .get("steamgriddb_id")
        .and_then(Value::as_str)
        .map(str::to_owned);
    if !wanted.is_empty() && !steamgriddb_key.trim().is_empty() {
        if sgdb_id.is_none() {
            match crate::artwork::exact_game_id(steamgriddb_key, title) {
                Ok(identity) => sgdb_id = identity,
                Err(error) => errors.push(error),
            }
        }
        if let Some(identity) = sgdb_id.as_deref() {
            for field in wanted {
                let collection = if field.starts_with("banner") {
                    "banner"
                } else {
                    field
                };
                match crate::artwork::search_for_game(steamgriddb_key, identity, collection) {
                    Ok(mut images) => {
                        if let Some(option) = images.drain(..).next() {
                            match crate::artwork::download(&option, artwork_cache) {
                                Ok(path) => {
                                    patch.insert(field.into(), Value::String(path));
                                }
                                Err(error) => errors.push(error),
                            }
                        }
                    }
                    Err(error) => errors.push(error),
                }
            }
            if patch.keys().any(|key| ART.contains(&key.as_str())) {
                patch.insert("steamgriddb_id".into(), Value::String(identity.into()));
            }
        }
    } else if !wanted.is_empty() {
        errors.push("Añade una clave de SteamGridDB en Ajustes para buscar imágenes.".into());
    }

    let existing = current
        .get("metadata")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    let needs_info = replace || INFO.iter().any(|field| empty(existing.get(*field)));
    if needs_info {
        let mut identity = existing
            .get("entity_id")
            .and_then(Value::as_str)
            .map(str::to_owned);
        if identity.is_none() {
            match wikidata_search(title, language) {
                Ok(matches) => {
                    let exact = matches
                        .into_iter()
                        .filter(|row| normalize(&row.name) == normalize(title))
                        .collect::<Vec<_>>();
                    if exact.len() == 1 {
                        identity = Some(exact[0].id.clone());
                    }
                }
                Err(error) => errors.push(error),
            }
        }
        if let Some(identity) = identity {
            match wikidata_fetch(&identity, language, metadata_cache) {
                Ok(fetched) => {
                    let mut merged = existing;
                    for (field, value) in fetched {
                        if !empty(Some(&value)) && (replace || empty(merged.get(&field))) {
                            merged.insert(field, value);
                        }
                    }
                    patch.insert("metadata".into(), Value::Object(merged));
                }
                Err(error) => errors.push(error),
            }
        }
    }
    (patch, errors)
}

fn empty(value: Option<&Value>) -> bool {
    value.is_none_or(|value| {
        value.is_null()
            || value.as_str().is_some_and(|text| text.trim().is_empty())
            || value.as_array().is_some_and(Vec::is_empty)
            || value.as_object().is_some_and(Map::is_empty)
    })
}

fn normalize(value: &str) -> String {
    value
        .chars()
        .filter(|character| character.is_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect()
}

pub fn wikidata_search(query: &str, language: &str) -> Result<Vec<MetadataOption>, String> {
    if query.trim().is_empty() || !["es", "en"].contains(&language) {
        return Err("Escribe un nombre de juego para buscar en Wikidata.".into());
    }
    let url = format!(
        "https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json&maxlag=5&type=item&limit=20&language=en&uselang={language}&search={}",
        encode(query.trim())
    );
    let response = request_json(
        &url,
        "Estante/0.3 (https://github.com/gsanmartindougan/Estante)",
    )?;
    let rows = response["search"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|row| {
            let id = row["id"].as_str()?;
            if !valid_wikidata_id(id) {
                return None;
            }
            Some(MetadataOption {
                id: id.to_owned(),
                name: row["label"].as_str().unwrap_or(id).to_owned(),
                description: row["description"].as_str().unwrap_or_default().to_owned(),
            })
        })
        .collect::<Vec<_>>();
    if rows.is_empty() {
        return Ok(rows);
    }

    const GAME_TYPES: &[&str] = &["Q7889", "Q60997816", "Q96240590", "Q209163", "Q1066707"];
    let mut parents = HashMap::<String, HashSet<String>>::new();
    let ids = rows
        .iter()
        .map(|row| row.id.as_str())
        .collect::<Vec<_>>()
        .join("%7C");
    let entities = request_json(
        &format!(
            "https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&maxlag=5&ids={ids}&props=claims"
        ),
        "Estante/0.3 (https://github.com/gsanmartindougan/Estante)",
    )?;
    let mut direct = HashMap::<String, HashSet<String>>::new();
    let mut frontier = HashSet::new();
    for row in &rows {
        let types = claim_ids(&entities["entities"][&row.id], "P31");
        frontier.extend(
            types
                .iter()
                .filter(|id| !GAME_TYPES.contains(&id.as_str()))
                .cloned(),
        );
        direct.insert(row.id.clone(), types);
    }
    for _ in 0..4 {
        let pending = frontier
            .iter()
            .filter(|id| !parents.contains_key(*id) && !GAME_TYPES.contains(&id.as_str()))
            .cloned()
            .collect::<Vec<_>>();
        for batch in pending.chunks(50) {
            if batch.is_empty() {
                continue;
            }
            let ids = batch.join("%7C");
            let entities = request_json(
                &format!(
                    "https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&maxlag=5&ids={ids}&props=claims"
                ),
                "Estante/0.3 (https://github.com/gsanmartindougan/Estante)",
            )?;
            for id in batch {
                parents.insert(id.clone(), claim_ids(&entities["entities"][id], "P279"));
            }
        }
        let next = frontier
            .iter()
            .flat_map(|id| parents.get(id).into_iter().flatten().cloned())
            .filter(|id| !GAME_TYPES.contains(&id.as_str()))
            .collect::<HashSet<_>>();
        frontier = next;
        if frontier.is_empty() {
            break;
        }
    }
    fn descends_from(
        id: &str,
        parents: &HashMap<String, HashSet<String>>,
        visited: &mut HashSet<String>,
    ) -> bool {
        if ["Q7889", "Q60997816", "Q96240590", "Q209163", "Q1066707"].contains(&id) {
            return true;
        }
        if !visited.insert(id.to_owned()) {
            return false;
        }
        parents.get(id).is_some_and(|rows| {
            rows.iter()
                .any(|parent| descends_from(parent, parents, visited))
        })
    }
    Ok(rows
        .into_iter()
        .filter(|row| {
            direct.get(&row.id).is_some_and(|types| {
                types
                    .iter()
                    .any(|id| descends_from(id, &parents, &mut HashSet::new()))
            })
        })
        .take(10)
        .collect())
}

fn claim_ids(entity: &Value, property: &str) -> HashSet<String> {
    entity["claims"][property]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|row| row["rank"].as_str() != Some("deprecated"))
        .filter_map(|row| row["mainsnak"]["datavalue"]["value"]["id"].as_str())
        .filter(|id| valid_wikidata_id(id))
        .map(str::to_owned)
        .collect()
}

pub fn wikidata_fetch(
    id: &str,
    language: &str,
    cache: &Path,
) -> Result<Map<String, Value>, String> {
    if !valid_wikidata_id(id) || !["es", "en"].contains(&language) {
        return Err("Identificador de Wikidata no válido.".into());
    }
    let cache_file = cache.join(format!("{id}.{language}.json"));
    if let Ok(bytes) = fs::read(&cache_file) {
        if let Ok(value) = serde_json::from_slice::<Value>(&bytes) {
            if let Some(object) = value.as_object() {
                return Ok(object.clone());
            }
        }
    }
    let url = format!(
        "https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&maxlag=5&ids={id}&props=labels%7Cdescriptions%7Cclaims&languages={language}%7Cen%7Ces&languagefallback=1"
    );
    let response = request_json(
        &url,
        "Estante/0.3 (https://github.com/gsanmartindougan/Estante)",
    )?;
    let entity = &response["entities"][id];
    if entity.is_null() {
        return Err("Wikidata no devolvió la ficha solicitada.".into());
    }
    let claims = &entity["claims"];
    let mut related = Vec::new();
    let mut ids = Vec::new();
    for (field, property) in [
        ("developers", "P178"),
        ("publishers", "P123"),
        ("genres", "P136"),
        ("platforms", "P400"),
    ] {
        let mut values = Vec::new();
        for row in claims[property].as_array().into_iter().flatten() {
            if row["rank"].as_str() == Some("deprecated") {
                continue;
            }
            if let Some(identity) = row["mainsnak"]["datavalue"]["value"]["id"].as_str() {
                if valid_wikidata_id(identity) {
                    ids.push(identity.to_owned());
                    values.push(identity.to_owned());
                }
            }
        }
        related.push((field, values));
    }
    ids.sort();
    ids.dedup();
    let mut labels = std::collections::HashMap::new();
    for batch in ids.chunks(50) {
        let joined = batch.join("%7C");
        let url = format!(
            "https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&maxlag=5&ids={joined}&props=labels&languages={language}%7Cen%7Ces&languagefallback=1"
        );
        let response = request_json(
            &url,
            "Estante/0.3 (https://github.com/gsanmartindougan/Estante)",
        )?;
        if let Some(entities) = response["entities"].as_object() {
            for (identity, row) in entities {
                labels.insert(
                    identity.clone(),
                    localized(&row["labels"], language)
                        .unwrap_or(identity)
                        .to_owned(),
                );
            }
        }
    }
    let mut metadata = Map::new();
    for (field, identities) in related {
        let mut values = identities
            .into_iter()
            .filter_map(|identity| labels.get(&identity).cloned())
            .map(Value::String)
            .collect::<Vec<_>>();
        values.sort_by_key(|value| value.as_str().unwrap_or_default().to_lowercase());
        values.dedup();
        metadata.insert(field.into(), Value::Array(values));
    }
    let mut dates = claims["P577"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|row| row["rank"].as_str() != Some("deprecated"))
        .filter_map(|row| {
            let time = row["mainsnak"]["datavalue"]["value"]["time"].as_str()?;
            let precision = row["mainsnak"]["datavalue"]["value"]["precision"]
                .as_u64()
                .unwrap_or(11);
            let mut date = time.trim_start_matches('+').split('T').next()?.to_owned();
            if precision == 10 {
                date.truncate(7);
            }
            if precision < 10 {
                date.truncate(4);
            }
            Some(date)
        })
        .collect::<Vec<_>>();
    dates.sort();
    metadata.insert(
        "title".into(),
        Value::String(
            localized(&entity["labels"], language)
                .unwrap_or(id)
                .to_owned(),
        ),
    );
    metadata.insert(
        "description".into(),
        Value::String(
            localized(&entity["descriptions"], language)
                .unwrap_or_default()
                .to_owned(),
        ),
    );
    metadata.insert(
        "release_date".into(),
        Value::String(dates.into_iter().next().unwrap_or_default()),
    );
    metadata.insert(
        "source".into(),
        Value::String(format!("https://www.wikidata.org/wiki/{id}")),
    );
    metadata.insert("entity_id".into(), Value::String(id.to_owned()));
    fs::create_dir_all(cache).map_err(|error| error.to_string())?;
    let _ = fs::write(
        cache_file,
        serde_json::to_vec_pretty(&metadata).map_err(|error| error.to_string())?,
    );
    Ok(metadata)
}

fn request_json(url: &str, user_agent: &str) -> Result<Value, String> {
    static REQUEST_GATE: OnceLock<Mutex<Option<Instant>>> = OnceLock::new();
    let mut last_request = REQUEST_GATE
        .get_or_init(|| Mutex::new(None))
        .lock()
        .map_err(|_| "No se pudo sincronizar la consulta a Wikidata.".to_owned())?;
    if let Some(last) = *last_request {
        let wait = Duration::from_millis(1100).saturating_sub(last.elapsed());
        if !wait.is_zero() {
            std::thread::sleep(wait);
        }
    }
    *last_request = Some(Instant::now());
    let output = Command::new("curl")
        .args([
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--max-time",
            "20",
            "--proto",
            "=https",
            "--proto-redir",
            "=https",
            "--retry",
            "3",
            "--retry-delay",
            "5",
            "--retry-max-time",
            "60",
            "-H",
        ])
        .arg(format!("User-Agent: {user_agent}"))
        .arg(url)
        .output()
        .map_err(|error| format!("No se pudo iniciar curl: {error}"))?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_owned());
    }
    serde_json::from_slice(&output.stdout).map_err(|error| error.to_string())
}

fn valid_wikidata_id(id: &str) -> bool {
    id.strip_prefix('Q').is_some_and(|number| {
        !number.is_empty()
            && number.bytes().all(|byte| byte.is_ascii_digit())
            && number.parse::<u64>().unwrap_or(0) > 0
    })
}

fn localized<'a>(values: &'a Value, language: &str) -> Option<&'a str> {
    values
        .get(language)
        .or_else(|| values.get("en"))
        .or_else(|| values.get("es"))?
        .get("value")?
        .as_str()
}

fn encode(value: &str) -> String {
    value.bytes().fold(String::new(), |mut output, byte| {
        if byte.is_ascii_alphanumeric() || b"-_.~".contains(&byte) {
            output.push(byte as char);
        } else {
            use std::fmt::Write;
            let _ = write!(output, "%{byte:02X}");
        }
        output
    })
}

fn put_string(target: &mut Map<String, Value>, key: &str, value: Option<&str>) {
    if let Some(value) = value.filter(|value| !value.trim().is_empty()) {
        target.insert(key.into(), Value::String(value.to_owned()));
    }
}

fn strip_html(value: &str) -> String {
    let mut output = String::new();
    let mut tag = false;
    for character in value.chars() {
        match character {
            '<' => tag = true,
            '>' => tag = false,
            _ if !tag => output.push(character),
            _ => (),
        }
    }
    output.split_whitespace().collect::<Vec<_>>().join(" ")
}
