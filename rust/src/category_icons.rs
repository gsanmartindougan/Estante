use serde_json::Value;
use std::{
    fs,
    io::Write,
    path::{Path, PathBuf},
    process::{Command, Stdio},
    time::{Duration, SystemTime},
};

const BOOTSTRAP_CATALOG: &str =
    "https://raw.githubusercontent.com/twbs/icons/main/font/bootstrap-icons.json";
const BOOTSTRAP_ROOT: &str = "https://raw.githubusercontent.com/twbs/icons/main/icons/";
const ICONIFY_ROOT: &str = "https://api.iconify.design/";
const SIMPLE_ICONS_SLUGS: &str = "https://raw.githubusercontent.com/simple-icons/simple-icons/develop/slugs.md";
const SIMPLE_ICONS_ROOT: &str = "https://cdn.simpleicons.org/";

#[derive(Debug, Clone)]
pub struct IconOption {
    pub name: String,
    pub url: String,
    pub source: String,
    pub author: String,
    pub license: String,
    pub provider: String,
}

pub fn search(provider: &str, query: &str, cache: &Path) -> Result<Vec<IconOption>, String> {
    let query = query.trim();
    if query.is_empty() {
        return Ok(Vec::new());
    }
    match provider {
        "bootstrap" => search_bootstrap(query, cache),
        "iconify" => search_iconify(query, cache),
        "simpleicons" => search_simple_icons(query, cache),
        _ => Err("Proveedor de iconos no válido.".into()),
    }
}

fn search_simple_icons(query: &str, cache: &Path) -> Result<Vec<IconOption>, String> {
    let cached = cache.join("simple-icons-slugs.md");
    let fresh = cached
        .metadata()
        .and_then(|metadata| metadata.modified())
        .ok()
        .and_then(|modified| SystemTime::now().duration_since(modified).ok())
        .is_some_and(|age| age < Duration::from_secs(24 * 60 * 60));
    let data = if fresh { fs::read(&cached).ok() } else { None };
    let data = match data {
        Some(data) => data,
        None => {
            let data = curl(SIMPLE_ICONS_SLUGS)
                .or_else(|error| fs::read(&cached).map_err(|_| error))?;
            let _ = fs::create_dir_all(cache);
            let _ = fs::write(&cached, &data);
            data
        }
    };
    let text = String::from_utf8_lossy(&data);
    let terms = query.to_lowercase().split_whitespace().map(str::to_owned).collect::<Vec<_>>();
    Ok(text.lines().filter_map(|line| {
        let row = line.trim().strip_prefix("| `")?.strip_suffix("` |")?;
        let (name, slug) = row.split_once("` | `")?;
        if !simple_slug_valid(slug) || !terms.iter().all(|term| name.to_lowercase().contains(term)) {
            return None;
        }
        Some(IconOption {
            name: name.to_owned(),
            url: format!("{SIMPLE_ICONS_ROOT}{slug}"),
            source: format!("https://simpleicons.org/?q={}", encode_query(name)),
            author: "Simple Icons contributors".into(),
            license: "CC0-1.0".into(),
            provider: "simpleicons".into(),
        })
    }).take(40).collect())
}

fn search_bootstrap(query: &str, cache: &Path) -> Result<Vec<IconOption>, String> {
    let cached = cache.join("bootstrap-catalog.json");
    let fresh = cached
        .metadata()
        .and_then(|metadata| metadata.modified())
        .ok()
        .and_then(|modified| SystemTime::now().duration_since(modified).ok())
        .is_some_and(|age| age < Duration::from_secs(24 * 60 * 60));
    let names = if fresh {
        read_bootstrap_cache(&cached).unwrap_or_default()
    } else {
        Vec::new()
    };
    let names = if !names.is_empty() {
        names
    } else {
        match curl(BOOTSTRAP_CATALOG) {
            Ok(data) => {
                let parsed: Value =
                    serde_json::from_slice(&data).map_err(|error| error.to_string())?;
                let mut names = match &parsed {
                    Value::Object(map) => map.keys().cloned().collect::<Vec<_>>(),
                    Value::Array(rows) => rows
                        .iter()
                        .filter_map(Value::as_str)
                        .map(str::to_owned)
                        .collect(),
                    _ => Vec::new(),
                };
                names.retain(|name| valid_name(name));
                names.sort();
                names.dedup();
                if names.is_empty() {
                    return Err("No se pudo cargar el catálogo de Bootstrap Icons.".into());
                }
                let _ = fs::create_dir_all(cache);
                let _ = fs::write(&cached, serde_json::to_vec(&names).unwrap_or_default());
                names
            }
            Err(error) if cached.is_file() => read_bootstrap_cache(&cached).ok_or(error)?,
            Err(error) => return Err(error),
        }
    };
    let terms = query
        .to_lowercase()
        .replace('_', "-")
        .split_whitespace()
        .map(str::to_owned)
        .collect::<Vec<_>>();
    Ok(names
        .into_iter()
        .filter(|name| terms.iter().all(|term| name.contains(term)))
        .take(40)
        .map(|name| IconOption {
            url: format!("{BOOTSTRAP_ROOT}{name}.svg"),
            source: format!("https://icons.getbootstrap.com/icons/{name}/"),
            name,
            author: "The Bootstrap Authors".into(),
            license: "MIT".into(),
            provider: "bootstrap".into(),
        })
        .collect())
}

fn read_bootstrap_cache(path: &Path) -> Option<Vec<String>> {
    let data: Value = serde_json::from_slice(&fs::read(path).ok()?).ok()?;
    let rows = data.as_array()?;
    let mut names = rows
        .iter()
        .filter_map(Value::as_str)
        .filter(|name| valid_name(name))
        .map(str::to_owned)
        .collect::<Vec<_>>();
    names.sort();
    names.dedup();
    (!names.is_empty()).then_some(names)
}

fn search_iconify(query: &str, cache: &Path) -> Result<Vec<IconOption>, String> {
    let url = format!(
        "{ICONIFY_ROOT}search?query={}&limit=64",
        encode_query(query)
    );
    let response = cached_json(&url, cache, "iconify-search")?;
    let collections = response.get("collections").and_then(Value::as_object);
    let mut seen = std::collections::HashSet::new();
    Ok(response
        .get("icons")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .filter(|id| {
            id.split_once(':')
                .is_some_and(|(prefix, name)| valid_name(prefix) && valid_name(name))
                && seen.insert((*id).to_owned())
        })
        .map(|id| {
            let (prefix, name) = id.split_once(':').expect("icon identifier validated");
            let info = collections.and_then(|rows| rows.get(prefix));
            IconOption {
                name: id.to_owned(),
                url: format!("{ICONIFY_ROOT}{prefix}/{name}.svg?color=%23ffffff"),
                source: format!("https://icon-sets.iconify.design/{prefix}/{name}/"),
                author: info
                    .and_then(|row| row["author"]["name"].as_str())
                    .unwrap_or_default()
                    .to_owned(),
                license: info
                    .and_then(|row| {
                        row["license"]["spdx"]
                            .as_str()
                            .or_else(|| row["license"]["title"].as_str())
                    })
                    .unwrap_or_default()
                    .to_owned(),
                provider: "iconify".into(),
            }
        })
        .take(40)
        .collect())
}

pub fn download(option: &IconOption, cache: &Path) -> Result<PathBuf, String> {
    let url_is_valid = match option.provider.as_str() {
        "bootstrap" => option
            .url
            .strip_prefix(BOOTSTRAP_ROOT)
            .is_some_and(|name| name.strip_suffix(".svg").is_some_and(valid_name)),
        "iconify" => option.url.strip_prefix(ICONIFY_ROOT).is_some_and(|path| {
            path.strip_suffix(".svg?color=%23ffffff")
                .and_then(|name| name.split_once('/'))
                .is_some_and(|(prefix, name)| valid_name(prefix) && valid_name(name))
        }),
        "simpleicons" => option.url.strip_prefix(SIMPLE_ICONS_ROOT).is_some_and(simple_slug_valid),
        _ => false,
    };
    if !url_is_valid {
        return Err("Dirección de icono no válida.".into());
    }
    fs::create_dir_all(cache).map_err(|error| error.to_string())?;
    let identity = if option.provider == "simpleicons" {
        option.url.trim_start_matches(SIMPLE_ICONS_ROOT).to_owned()
    } else {
        option.name.replace(':', "-")
    };
    let target = cache.join(format!("icon-{}-{identity}.png", option.provider));
    if target.is_file() {
        return Ok(target);
    }
    let svg = curl(&option.url)?;
    render_svg(&svg, &target)?;
    Ok(target)
}

fn cached_json(url: &str, cache: &Path, prefix: &str) -> Result<Value, String> {
    use std::hash::{Hash, Hasher};
    let mut hasher = std::collections::hash_map::DefaultHasher::new();
    url.hash(&mut hasher);
    let path = cache.join(format!("{prefix}-{:016x}.json", hasher.finish()));
    let data = curl(url).or_else(|error| fs::read(&path).map_err(|_| error))?;
    let value: Value = serde_json::from_slice(&data).map_err(|error| error.to_string())?;
    if value.is_object() {
        let _ = fs::create_dir_all(cache);
        let _ = fs::write(path, data);
        Ok(value)
    } else {
        Err("Respuesta de Iconify no válida.".into())
    }
}

fn render_svg(data: &[u8], target: &Path) -> Result<(), String> {
    let temporary = target.with_extension("tmp.png");
    let svg = String::from_utf8_lossy(data).replace("currentColor", "#ffffff");
    let mut child = Command::new("rsvg-convert")
        .args([
            "--format", "png", "--width", "128", "--height", "128", "--output",
        ])
        .arg(&temporary)
        .arg("-")
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| format!("No se pudo iniciar rsvg-convert: {error}"))?;
    child
        .stdin
        .take()
        .ok_or("No se pudo convertir el icono.")?
        .write_all(svg.as_bytes())
        .map_err(|error| error.to_string())?;
    let output = child
        .wait_with_output()
        .map_err(|error| error.to_string())?;
    if !output.status.success() {
        let _ = fs::remove_file(&temporary);
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_owned());
    }
    image::ImageReader::open(&temporary)
        .map_err(|error| error.to_string())?
        .with_guessed_format()
        .map_err(|error| error.to_string())?
        .decode()
        .map_err(|error| error.to_string())?;
    fs::rename(temporary, target).map_err(|error| error.to_string())
}

fn curl(url: &str) -> Result<Vec<u8>, String> {
    if !url.starts_with("https://") {
        return Err("Solo se permiten direcciones HTTPS.".into());
    }
    let output = Command::new("curl")
        .args([
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--max-time",
            "20",
            "--max-filesize",
            "2000000",
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
    Ok(output.stdout)
}

fn valid_name(name: &str) -> bool {
    !name.is_empty()
        && name.split('-').all(|part| {
            !part.is_empty()
                && part
                    .bytes()
                    .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit())
        })
}

fn simple_slug_valid(slug: &str) -> bool {
    !slug.is_empty()
        && slug.split('_').all(|part| {
            !part.is_empty()
                && part
                    .bytes()
                    .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit())
        })
}

fn encode_query(query: &str) -> String {
    let mut output = String::new();
    for byte in query.bytes() {
        if byte.is_ascii_alphanumeric() || b"-_.~".contains(&byte) {
            output.push(byte as char);
        } else if byte == b' ' {
            output.push('+');
        } else {
            output.push_str(&format!("%{byte:02X}"));
        }
    }
    output
}

#[cfg(test)]
mod tests {
    use super::{encode_query, render_svg, valid_name};
    use std::{fs, process::Command};

    #[test]
    fn icon_names_are_path_safe_and_queries_are_encoded() {
        assert!(valid_name("controller-2"));
        assert!(!valid_name("../controller"));
        assert!(!valid_name("Controller"));
        assert_eq!(encode_query("game pad"), "game+pad");
        assert_eq!(encode_query("a/b"), "a%2Fb");
    }

    #[test]
    fn svg_rasterizer_outputs_a_bounded_png_when_available() {
        if Command::new("rsvg-convert")
            .arg("--version")
            .output()
            .is_err()
        {
            return;
        }
        let root = std::env::temp_dir().join(format!(
            "estante-icon-render-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(&root).unwrap();
        let target = root.join("icon.png");
        render_svg(
            b"<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 16 16\"><path fill=\"currentColor\" d=\"M2 2h12v12H2z\"/></svg>",
            &target,
        )
        .unwrap();
        let dimensions = image::ImageReader::open(&target)
            .unwrap()
            .with_guessed_format()
            .unwrap()
            .into_dimensions()
            .unwrap();
        assert_eq!(dimensions, (128, 128));
        let _ = fs::remove_dir_all(root);
    }
}
