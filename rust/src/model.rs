use serde_json::{Map, Value};
use std::fs::{self, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

const EMPTY_STATE: &str = r#"{"games":[],"overrides":{}}"#;

#[derive(Clone, Debug)]
pub struct Game {
    data: Map<String, Value>,
}

impl Game {
    fn new(data: Map<String, Value>) -> Self {
        Self { data }
    }

    pub fn id(&self) -> &str {
        self.data
            .get("id")
            .and_then(Value::as_str)
            .unwrap_or_default()
    }

    pub fn title(&self) -> &str {
        self.data
            .get("title")
            .and_then(Value::as_str)
            .unwrap_or("Sin título")
    }

    pub fn kind_label(&self) -> &str {
        match self
            .data
            .get("kind")
            .and_then(Value::as_str)
            .unwrap_or("local")
        {
            "steam" => "Steam",
            "faugus" => "Faugus",
            "heroic" => "Heroic",
            _ => "Local",
        }
    }

    pub fn categories(&self) -> Vec<String> {
        self.data
            .get("categories")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
            .map(str::to_owned)
            .collect()
    }

    pub fn field(&self, name: &str) -> Option<&str> {
        self.data.get(name).and_then(Value::as_str)
    }

    pub fn data(&self) -> &Map<String, Value> {
        &self.data
    }

    pub fn kind(&self) -> &str {
        self.field("kind").unwrap_or("local")
    }

    pub fn metadata(&self) -> &Map<String, Value> {
        self.data
            .get("metadata")
            .and_then(Value::as_object)
            .unwrap_or_else(|| empty_map())
    }
}

fn empty_map() -> &'static Map<String, Value> {
    static EMPTY: std::sync::OnceLock<Map<String, Value>> = std::sync::OnceLock::new();
    EMPTY.get_or_init(Map::new)
}

pub struct Library {
    root: PathBuf,
    state: Map<String, Value>,
    load_error: Option<String>,
}

impl Library {
    pub fn open_default() -> Self {
        let home = std::env::var_os("HOME")
            .map(PathBuf::from)
            .unwrap_or_default();
        let data_home = std::env::var_os("XDG_DATA_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| home.join(".local/share"));
        let root = std::env::var_os("ESTANTE_DATA_DIR")
            .map(PathBuf::from)
            .unwrap_or_else(|| data_home.join("estante"));
        let existed = root.join("library.json").is_file();
        let mut library = Self::open(root);
        if library.load_error.is_none() {
            if !library.state.contains_key("faugus") {
                let games = if existed {
                    crate::importers::faugus(
                        &home,
                        &data_home,
                        &std::env::var_os("XDG_CONFIG_HOME")
                            .map(PathBuf::from)
                            .unwrap_or_else(|| home.join(".config")),
                    )
                    .unwrap_or_default()
                } else {
                    Vec::new()
                };
                library.state.insert("faugus".into(), Value::Array(games));
                let _ = library.save();
            }
            if !library
                .state
                .get("source_categories_initialized")
                .and_then(Value::as_bool)
                .unwrap_or(false)
            {
                let faugus = library
                    .state
                    .get("faugus")
                    .and_then(Value::as_array)
                    .into_iter()
                    .flatten()
                    .filter(|game| !is_faugus_steam(game))
                    .cloned()
                    .collect::<Vec<_>>();
                let steam = library
                    .state
                    .get("steam")
                    .and_then(Value::as_array)
                    .cloned()
                    .unwrap_or_default();
                library.assign_source_category(&faugus, "Faugus");
                library.assign_source_category(&steam, "Steam");
                library
                    .state
                    .insert("source_categories_initialized".into(), Value::Bool(true));
                let _ = library.save();
            }
        }
        library
    }

    pub fn open(root: impl Into<PathBuf>) -> Self {
        let root = root.into();
        let path = root.join("library.json");
        let (state, load_error) = match read_object(&path) {
            Ok(state) => (state, None),
            Err(error) if error.kind() == io::ErrorKind::NotFound => (
                serde_json::from_str(EMPTY_STATE).expect("static empty state is valid"),
                None,
            ),
            Err(error) => (
                serde_json::from_str(EMPTY_STATE).expect("static empty state is valid"),
                Some(format!("No se pudo leer {}: {error}", path.display())),
            ),
        };
        Self {
            root,
            state,
            load_error,
        }
    }

    pub fn artwork_cache_dir(&self) -> PathBuf {
        self.root.join("covers")
    }

    pub fn metadata_cache_dir(&self) -> PathBuf {
        self.root.join("metadata")
    }

    pub fn data_dir(&self) -> &Path {
        &self.root
    }

    pub fn reload(&self) -> Self {
        Self::open(self.root.clone())
    }

    pub fn games(&self) -> Vec<Game> {
        let excluded = self
            .state
            .get("excluded_imports")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
            .collect::<std::collections::HashSet<_>>();
        let overrides = self.state.get("overrides").and_then(Value::as_object);
        let mut games = Vec::new();

        for source in ["faugus", "steam", "heroic"] {
            for item in self
                .state
                .get(source)
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
            {
                let Some(mut game) = item.as_object().cloned() else {
                    continue;
                };
                let id = game.get("id").and_then(Value::as_str).unwrap_or_default();
                if excluded.contains(id)
                    || game.get("hidden").and_then(Value::as_bool).unwrap_or(false)
                    || (source == "faugus" && is_faugus_steam(&Value::Object(game.clone())))
                {
                    continue;
                }
                if let Some(patch) = overrides
                    .and_then(|items| items.get(id))
                    .and_then(Value::as_object)
                {
                    game.extend(patch.clone());
                }
                if game.get("hidden").and_then(Value::as_bool).unwrap_or(false) {
                    continue;
                }
                games.push(Game::new(game));
            }
        }
        for item in self
            .state
            .get("games")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            if let Some(game) = item.as_object() {
                if !game.get("hidden").and_then(Value::as_bool).unwrap_or(false) {
                    games.push(Game::new(game.clone()));
                }
            }
        }
        games.sort_by_key(|game| game.title().to_lowercase());
        games
    }

    pub fn categories(&self, games: &[Game]) -> Vec<String> {
        let mut names = self
            .state
            .get("categories")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
            .map(str::to_owned)
            .collect::<Vec<_>>();
        for game in games {
            names.extend(game.categories());
        }
        names.sort_by_key(|name| name.to_lowercase());
        names.dedup();
        let mut ordered = self
            .state
            .get("category_order")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
            .filter(|name| names.iter().any(|item| item == name))
            .map(str::to_owned)
            .collect::<Vec<_>>();
        for name in names {
            if !ordered.contains(&name) {
                ordered.push(name);
            }
        }
        ordered
    }

    pub fn category_icon_path(&self, name: &str) -> Option<PathBuf> {
        let file = self.state.get("category_icons")?.get(name)?.as_str()?;
        if Path::new(file).file_name()?.to_str()? != file {
            return None;
        }
        let path = self.root.join("category-icons").join(file);
        path.is_file().then_some(path)
    }

    pub fn category_icons_dir(&self) -> PathBuf {
        self.root.join("category-icons")
    }

    pub fn import_category_icon(
        &mut self,
        category: Option<&str>,
        source: &Path,
        credit: Option<Value>,
    ) -> io::Result<()> {
        if category.is_some_and(|name| {
            !self
                .categories(&self.games())
                .iter()
                .any(|item| item == name)
        }) {
            return Err(io::Error::new(
                io::ErrorKind::NotFound,
                "La categoría ya no existe.",
            ));
        }
        let extension = source
            .extension()
            .and_then(|ext| ext.to_str())
            .map(str::to_ascii_lowercase)
            .filter(|ext| matches!(ext.as_str(), "png" | "jpg" | "jpeg" | "webp"))
            .ok_or_else(|| {
                io::Error::new(
                    io::ErrorKind::InvalidInput,
                    "Formato de icono no compatible.",
                )
            })?;
        image::ImageReader::open(source)
            .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?
            .with_guessed_format()
            .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?
            .decode()
            .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
        let directory = self.category_icons_dir();
        fs::create_dir_all(&directory)?;
        let target = if source.parent() == Some(directory.as_path()) {
            source.to_path_buf()
        } else {
            let target = directory.join(format!("local-icon-{}.{}", unique_suffix(), extension));
            let temporary = target.with_extension(format!("{extension}.tmp"));
            fs::copy(source, &temporary)?;
            fs::rename(temporary, &target)?;
            target
        };
        let filename = target
            .file_name()
            .and_then(|name| name.to_str())
            .ok_or_else(|| {
                io::Error::new(io::ErrorKind::InvalidInput, "Ruta de icono no válida.")
            })?;
        let key = category.unwrap_or_default();
        self.state
            .entry("category_icons")
            .or_insert_with(|| Value::Object(Map::new()))
            .as_object_mut()
            .ok_or_else(|| {
                io::Error::new(
                    io::ErrorKind::InvalidData,
                    "category_icons must be an object",
                )
            })?
            .insert(key.to_owned(), Value::String(filename.to_owned()));
        if let Some(credit) = credit {
            self.state
                .entry("category_icon_sources")
                .or_insert_with(|| Value::Object(Map::new()))
                .as_object_mut()
                .ok_or_else(|| {
                    io::Error::new(
                        io::ErrorKind::InvalidData,
                        "category_icon_sources must be an object",
                    )
                })?
                .insert(key.to_owned(), credit);
        } else if let Some(sources) = self
            .state
            .get_mut("category_icon_sources")
            .and_then(Value::as_object_mut)
        {
            sources.remove(key);
        }
        self.save()
    }

    pub fn clear_category_icon(&mut self, category: Option<&str>) -> io::Result<()> {
        if category.is_some_and(|name| {
            !self
                .categories(&self.games())
                .iter()
                .any(|item| item == name)
        }) {
            return Err(io::Error::new(
                io::ErrorKind::NotFound,
                "La categoría ya no existe.",
            ));
        }
        let key = category.unwrap_or_default();
        if let Some(icons) = self
            .state
            .get_mut("category_icons")
            .and_then(Value::as_object_mut)
        {
            icons.remove(key);
        }
        if let Some(sources) = self
            .state
            .get_mut("category_icon_sources")
            .and_then(Value::as_object_mut)
        {
            sources.remove(key);
        }
        self.save()
    }

    pub fn add_category(&mut self, name: &str) -> io::Result<()> {
        let name = name.trim();
        if name.is_empty() || name.eq_ignore_ascii_case("todos") {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "Escribe un nombre distinto de «Todos».",
            ));
        }
        let categories = self
            .state
            .entry("categories")
            .or_insert_with(|| Value::Array(Vec::new()));
        let categories = categories.as_array_mut().ok_or_else(|| {
            io::Error::new(io::ErrorKind::InvalidData, "categories must be an array")
        })?;
        if categories
            .iter()
            .filter_map(Value::as_str)
            .any(|item| item.eq_ignore_ascii_case(name))
        {
            return Err(io::Error::new(
                io::ErrorKind::AlreadyExists,
                "Ya existe una categoría con ese nombre.",
            ));
        }
        categories.push(Value::String(name.to_owned()));
        categories.sort_by_key(|item| item.as_str().unwrap_or_default().to_lowercase());
        self.save()
    }

    pub fn remove_category(&mut self, name: &str) -> io::Result<()> {
        if name.eq_ignore_ascii_case("todos") {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "La categoría Todos no se puede quitar.",
            ));
        }
        if let Some(categories) = self
            .state
            .get_mut("categories")
            .and_then(Value::as_array_mut)
        {
            categories.retain(|item| item.as_str() != Some(name));
        }
        for source in ["games", "steam", "faugus", "heroic"] {
            for game in self
                .state
                .get_mut(source)
                .and_then(Value::as_array_mut)
                .into_iter()
                .flatten()
            {
                remove_category_value(game, name);
            }
        }
        if let Some(overrides) = self
            .state
            .get_mut("overrides")
            .and_then(Value::as_object_mut)
        {
            for game in overrides.values_mut() {
                remove_category_value(game, name);
            }
        }
        remove_string_value(&mut self.state, "category_order", name);
        for key in ["category_icons", "category_icon_sources"] {
            if let Some(values) = self.state.get_mut(key).and_then(Value::as_object_mut) {
                values.remove(name);
            }
        }
        if self.state.get("primary_category").and_then(Value::as_str) == Some(name) {
            self.state.insert("primary_category".into(), Value::Null);
        }
        self.save()
    }

    pub fn rename_category(&mut self, previous: &str, name: &str) -> io::Result<()> {
        let name = name.trim();
        let names = self.categories(&self.games());
        if !names.iter().any(|item| item == previous) {
            return Err(io::Error::new(
                io::ErrorKind::NotFound,
                "La categoría ya no existe.",
            ));
        }
        if name.is_empty() || name.eq_ignore_ascii_case("todos") || name.eq_ignore_ascii_case("all")
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "Escribe un nombre distinto de «Todos».",
            ));
        }
        if names
            .iter()
            .any(|item| item != previous && item.eq_ignore_ascii_case(name))
        {
            return Err(io::Error::new(
                io::ErrorKind::AlreadyExists,
                "Ya existe una categoría con ese nombre.",
            ));
        }
        if let Some(categories) = self
            .state
            .get_mut("categories")
            .and_then(Value::as_array_mut)
        {
            for item in categories.iter_mut() {
                if item.as_str() == Some(previous) {
                    *item = Value::String(name.to_owned());
                }
            }
            categories.sort_by_key(|item| item.as_str().unwrap_or_default().to_lowercase());
        }
        for source in ["games", "steam", "faugus", "heroic"] {
            if let Some(games) = self.state.get_mut(source).and_then(Value::as_array_mut) {
                for game in games {
                    replace_category_value(game, previous, name);
                }
            }
        }
        if let Some(overrides) = self
            .state
            .get_mut("overrides")
            .and_then(Value::as_object_mut)
        {
            for game in overrides.values_mut() {
                replace_category_value(game, previous, name);
            }
        }
        replace_string_values(&mut self.state, "category_order", previous, name);
        replace_object_key(&mut self.state, "category_icons", previous, name);
        replace_object_key(&mut self.state, "category_icon_sources", previous, name);
        if self.state.get("primary_category").and_then(Value::as_str) == Some(previous) {
            self.state
                .insert("primary_category".into(), Value::String(name.to_owned()));
        }
        self.save()
    }

    pub fn move_category(&mut self, name: &str, step: isize, games: &[Game]) -> io::Result<()> {
        let mut names = self.categories(games);
        let Some(index) = names.iter().position(|item| item == name) else {
            return Err(io::Error::new(
                io::ErrorKind::NotFound,
                "La categoría ya no existe.",
            ));
        };
        let destination = (index as isize + step).clamp(0, names.len() as isize - 1) as usize;
        let moved = names.remove(index);
        names.insert(destination, moved);
        self.state.insert(
            "category_order".into(),
            Value::Array(names.into_iter().map(Value::String).collect()),
        );
        self.save()
    }

    pub fn set_primary_category(&mut self, name: Option<&str>, games: &[Game]) -> io::Result<()> {
        if name.is_some_and(|name| !self.categories(games).iter().any(|item| item == name)) {
            return Err(io::Error::new(
                io::ErrorKind::NotFound,
                "La categoría ya no existe.",
            ));
        }
        self.state.insert(
            "primary_category".into(),
            name.map_or(Value::Null, |name| Value::String(name.to_owned())),
        );
        self.save()
    }

    pub fn set_category_member(
        &mut self,
        category: &str,
        id: &str,
        selected: bool,
    ) -> io::Result<()> {
        let games = self.games();
        if !self.categories(&games).iter().any(|name| name == category) {
            return Err(io::Error::new(
                io::ErrorKind::NotFound,
                "La categoría ya no existe.",
            ));
        }
        let game = games
            .iter()
            .find(|game| game.id() == id)
            .ok_or_else(|| io::Error::new(io::ErrorKind::NotFound, "El juego ya no existe."))?;
        let mut categories = game.categories();
        categories.retain(|name| name != category);
        if selected {
            categories.push(category.to_owned());
        }
        let target = if matches!(game.kind(), "steam" | "faugus" | "heroic") {
            self.state
                .entry("overrides")
                .or_insert_with(|| Value::Object(Map::new()))
                .as_object_mut()
                .ok_or_else(|| {
                    io::Error::new(io::ErrorKind::InvalidData, "overrides must be an object")
                })?
                .entry(id.to_owned())
                .or_insert_with(|| Value::Object(Map::new()))
        } else {
            self.state
                .get_mut("games")
                .and_then(Value::as_array_mut)
                .and_then(|games| {
                    games
                        .iter_mut()
                        .find(|item| item["id"].as_str() == Some(id))
                })
                .ok_or_else(|| io::Error::new(io::ErrorKind::NotFound, "El juego ya no existe."))?
        };
        target
            .as_object_mut()
            .ok_or_else(|| {
                io::Error::new(io::ErrorKind::InvalidData, "game data must be an object")
            })?
            .insert(
                "categories".into(),
                Value::Array(categories.into_iter().map(Value::String).collect()),
            );
        self.save()
    }

    pub fn primary_category(&self) -> Option<&str> {
        let name = self.state.get("primary_category")?.as_str()?;
        self.categories(&self.games())
            .iter()
            .any(|category| category == name)
            .then_some(name)
    }

    pub fn session_count(&self, id: &str) -> u64 {
        self.state
            .get("activity")
            .and_then(Value::as_object)
            .and_then(|activity| activity.get(id))
            .and_then(Value::as_object)
            .and_then(|activity| activity.get("sessions"))
            .and_then(Value::as_u64)
            .unwrap_or(0)
    }

    pub fn session_seconds(&self, id: &str) -> u64 {
        self.state
            .get("activity")
            .and_then(Value::as_object)
            .and_then(|activity| activity.get(id))
            .and_then(Value::as_object)
            .and_then(|activity| activity.get("seconds"))
            .and_then(Value::as_u64)
            .unwrap_or(0)
    }

    pub fn session_history(&self, id: &str) -> Vec<Value> {
        self.state
            .get("activity")
            .and_then(Value::as_object)
            .and_then(|activity| activity.get(id))
            .and_then(Value::as_object)
            .and_then(|activity| activity.get("history"))
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default()
    }

    pub fn matching_game_processes(game: &Game, launcher_pid: u32, token: &str) -> Vec<u32> {
        let Some(entries) = fs::read_dir("/proc").ok() else {
            return Vec::new();
        };
        let current_uid = fs::read_to_string("/proc/self/status")
            .ok()
            .and_then(|status| {
                status.lines().find_map(|line| {
                    line.strip_prefix("Uid:")?
                        .split_whitespace()
                        .next()?
                        .parse::<u32>()
                        .ok()
                })
            });
        let mut found = Vec::new();
        for entry in entries.flatten() {
            let Some(pid) = entry
                .file_name()
                .to_str()
                .and_then(|name| name.parse::<u32>().ok())
            else {
                continue;
            };
            if pid == launcher_pid
                && (game.kind() == "faugus"
                    || game.field("path").is_some_and(|path| path.ends_with(".sh")))
            {
                continue;
            }
            let process = entry.path();
            let Ok(status) = fs::read_to_string(process.join("status")) else {
                continue;
            };
            if let Some(uid) = current_uid {
                let process_uid = status.lines().find_map(|line| {
                    line.strip_prefix("Uid:")?
                        .split_whitespace()
                        .next()?
                        .parse::<u32>()
                        .ok()
                });
                if process_uid != Some(uid) {
                    continue;
                }
            }
            let Ok(environment) = fs::read(process.join("environ")) else {
                continue;
            };
            let variables = environment.split(|byte| *byte == 0).collect::<Vec<_>>();
            let token_match =
                variables.contains(&format!("ESTANTE_GAME_SESSION={token}").as_bytes());
            let steam_match = game.field("steam_appid").is_some_and(|id| {
                variables.contains(&format!("SteamAppId={id}").as_bytes())
                    || variables.contains(&format!("SteamGameId={id}").as_bytes())
            });
            let heroic_match = match (game.field("heroic_app_name"), game.field("heroic_runner")) {
                (Some(name), Some(runner)) => {
                    variables.contains(&format!("HEROIC_APP_NAME={name}").as_bytes())
                        && variables.contains(&format!("HEROIC_APP_RUNNER={runner}").as_bytes())
                }
                _ => false,
            };
            if (game.kind() == "steam" && steam_match)
                || (game.kind() == "heroic" && heroic_match)
                || (!matches!(game.kind(), "steam" | "heroic") && token_match)
            {
                found.push(pid);
            }
        }
        found
    }

    pub fn load_error(&self) -> Option<&str> {
        self.load_error.as_deref()
    }

    pub fn settings(&self) -> io::Result<Value> {
        Self::read_settings(&self.root)
    }

    fn read_settings(root: &Path) -> io::Result<Value> {
        let path = root.join("settings.json");
        match fs::read(path) {
            Ok(bytes) => {
                let value: Value = serde_json::from_slice(&bytes)
                    .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
                if value.is_object() {
                    Ok(value)
                } else {
                    Err(io::Error::new(
                        io::ErrorKind::InvalidData,
                        "settings.json debe contener un objeto",
                    ))
                }
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(Value::Object(Map::new())),
            Err(error) => Err(error),
        }
    }

    pub fn save_settings(&self, settings: &Value) -> io::Result<()> {
        Self::save_settings_at(&self.root, settings)
    }

    pub fn save_settings_at(root: impl AsRef<Path>, settings: &Value) -> io::Result<()> {
        if !settings.is_object() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "settings must be an object",
            ));
        }
        let root = root.as_ref();
        Self::read_settings(root)?;
        atomic_json(root, "settings.json", settings)
    }

    pub fn launch(&self, game: &Game) -> io::Result<(Child, String)> {
        let token = unique_suffix();
        let kind = game.kind();
        let mut command = match kind {
            "steam" => {
                let app_id = game.field("steam_appid").unwrap_or_default();
                if app_id.is_empty()
                    || !app_id.bytes().all(|byte| byte.is_ascii_digit())
                    || app_id.parse::<u64>().unwrap_or(0) == 0
                {
                    return Err(io::Error::new(
                        io::ErrorKind::InvalidInput,
                        "Identificador de Steam no válido.",
                    ));
                }
                launcher_command(
                    game.field("install"),
                    "steam",
                    "com.valvesoftware.Steam",
                    &["-silent", "-applaunch", app_id],
                    &token,
                    None,
                )?
            }
            "faugus" => {
                let id = game.field("gameid").unwrap_or_default();
                if id.is_empty() || id.contains('\0') {
                    return Err(io::Error::new(
                        io::ErrorKind::InvalidInput,
                        "Identificador de Faugus no válido.",
                    ));
                }
                launcher_command(
                    game.field("install"),
                    "faugus-launcher",
                    "io.github.Faugus.faugus-launcher",
                    &["--game", id],
                    &token,
                    None,
                )?
            }
            "heroic" => {
                let runner = game.field("heroic_runner").unwrap_or_default();
                let name = game.field("heroic_app_name").unwrap_or_default();
                if !["legendary", "gog", "nile", "sideload"].contains(&runner)
                    || name.is_empty()
                    || name.contains('\0')
                {
                    return Err(io::Error::new(
                        io::ErrorKind::InvalidInput,
                        "Identificador de Heroic no válido.",
                    ));
                }
                let url = format!(
                    "heroic://launch?appName={}&runner={}&gui=false",
                    url_encode(name),
                    url_encode(runner)
                );
                launcher_command(
                    game.field("install"),
                    "heroic",
                    "com.heroicgameslauncher.hgl",
                    &["--no-gui", &url],
                    &token,
                    Some((name, runner)),
                )?
            }
            _ => {
                let path = game.field("path").ok_or_else(|| {
                    io::Error::new(
                        io::ErrorKind::InvalidInput,
                        "El juego no tiene una ruta de lanzamiento.",
                    )
                })?;
                let path = PathBuf::from(path);
                if !path.is_file() {
                    return Err(io::Error::new(
                        io::ErrorKind::NotFound,
                        "El archivo del juego ya no existe.",
                    ));
                }
                let mut command = if path
                    .extension()
                    .and_then(|ext| ext.to_str())
                    .is_some_and(|ext| ext.eq_ignore_ascii_case("sh"))
                {
                    let mut command = Command::new("bash");
                    command.arg(&path);
                    command
                } else {
                    #[cfg(unix)]
                    {
                        use std::os::unix::fs::PermissionsExt;
                        if fs::metadata(&path)?.permissions().mode() & 0o111 == 0 {
                            return Err(io::Error::new(
                                io::ErrorKind::PermissionDenied,
                                "La AppImage necesita permiso de ejecución.",
                            ));
                        }
                    }
                    Command::new(&path)
                };
                let args =
                    shlex::split(game.field("arguments").unwrap_or_default()).ok_or_else(|| {
                        io::Error::new(
                            io::ErrorKind::InvalidInput,
                            "Los argumentos tienen comillas sin cerrar.",
                        )
                    })?;
                command.args(args);
                let cwd = game
                    .field("cwd")
                    .map(PathBuf::from)
                    .or_else(|| path.parent().map(Path::to_path_buf));
                if let Some(cwd) = cwd {
                    command.current_dir(cwd);
                }
                command
            }
        };
        let logs = self.root.join("logs");
        fs::create_dir_all(&logs)?;
        let log = OpenOptions::new()
            .create(true)
            .truncate(true)
            .write(true)
            .open(logs.join("launch.log"))?;
        if kind == "heroic" {
            command.env(
                "HEROIC_APP_NAME",
                game.field("heroic_app_name").unwrap_or_default(),
            );
            command.env(
                "HEROIC_APP_RUNNER",
                game.field("heroic_runner").unwrap_or_default(),
            );
        }
        command
            .env("ESTANTE_GAME_SESSION", &token)
            .stdin(Stdio::null())
            .stdout(Stdio::from(log.try_clone()?))
            .stderr(Stdio::from(log));
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            command.process_group(0);
        }
        command.spawn().map(|child| (child, token))
    }

    pub fn record_session(
        &mut self,
        id: &str,
        seconds: u64,
        started: &str,
        exit_code: Option<i32>,
    ) -> io::Result<()> {
        let activity = self
            .state
            .entry("activity")
            .or_insert_with(|| Value::Object(Map::new()));
        let activity = activity.as_object_mut().ok_or_else(|| {
            io::Error::new(io::ErrorKind::InvalidData, "activity must be an object")
        })?;
        let game = activity
            .entry(id.to_owned())
            .or_insert_with(|| Value::Object(Map::new()));
        let game = game.as_object_mut().ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::InvalidData,
                "game activity must be an object",
            )
        })?;
        let previous_seconds = game.get("seconds").and_then(Value::as_u64).unwrap_or(0);
        let sessions = game.get("sessions").and_then(Value::as_u64).unwrap_or(0);
        game.insert(
            "seconds".into(),
            Value::from(previous_seconds.saturating_add(seconds)),
        );
        game.insert("sessions".into(), Value::from(sessions.saturating_add(1)));
        game.insert("last_played".into(), Value::String(started.to_owned()));
        game.insert("last_seconds".into(), Value::from(seconds));
        let history = game
            .entry("history")
            .or_insert_with(|| Value::Array(Vec::new()));
        let history = history.as_array_mut().ok_or_else(|| {
            io::Error::new(io::ErrorKind::InvalidData, "history must be an array")
        })?;
        let mut entry = Map::new();
        entry.insert("started".into(), Value::String(started.to_owned()));
        entry.insert("seconds".into(), Value::from(seconds));
        if let Some(code) = exit_code {
            entry.insert("exit_code".into(), Value::from(code));
        } else {
            entry.insert("exit_code".into(), Value::Null);
        }
        history.insert(0, Value::Object(entry));
        history.truncate(8);
        self.save()
    }

    pub fn add_local(
        &mut self,
        title: &str,
        path: &str,
        arguments: &str,
        cwd: &str,
    ) -> io::Result<()> {
        let path = expand_home(path.trim());
        let extension = path
            .extension()
            .and_then(|value| value.to_str())
            .unwrap_or("")
            .to_lowercase();
        if title.trim().is_empty()
            || !path.is_file()
            || !["sh", "appimage"].contains(&extension.as_str())
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "Indica un nombre y un archivo .sh o .AppImage existente.",
            ));
        }
        if shlex::split(arguments).is_none() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "Los argumentos tienen comillas sin cerrar.",
            ));
        }
        let working = if cwd.trim().is_empty() {
            path.parent().unwrap_or(Path::new(".")).to_owned()
        } else {
            expand_home(cwd.trim())
        };
        if !working.is_dir() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "El directorio de trabajo no existe.",
            ));
        }
        let id = format!("local:{}", unique_suffix());
        let mut row = Map::new();
        row.insert("id".into(), Value::String(id));
        row.insert("title".into(), Value::String(title.trim().to_owned()));
        row.insert("kind".into(), Value::String("local".into()));
        row.insert(
            "path".into(),
            Value::String(path.canonicalize()?.to_string_lossy().into_owned()),
        );
        row.insert("arguments".into(), Value::String(arguments.to_owned()));
        row.insert(
            "cwd".into(),
            Value::String(working.canonicalize()?.to_string_lossy().into_owned()),
        );
        row.insert("cover".into(), Value::String(String::new()));
        self.state
            .entry("games")
            .or_insert_with(|| Value::Array(Vec::new()))
            .as_array_mut()
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "games must be an array"))?
            .push(Value::Object(row));
        self.save()
    }

    pub fn remove_game(&mut self, id: &str) -> io::Result<()> {
        let imported = ["steam", "faugus", "heroic"].iter().any(|source| {
            self.state
                .get(*source)
                .and_then(Value::as_array)
                .is_some_and(|games| {
                    games
                        .iter()
                        .any(|game| game.get("id").and_then(Value::as_str) == Some(id))
                })
        });
        if imported {
            let excluded = self
                .state
                .entry("excluded_imports")
                .or_insert_with(|| Value::Array(Vec::new()));
            let excluded = excluded.as_array_mut().ok_or_else(|| {
                io::Error::new(
                    io::ErrorKind::InvalidData,
                    "excluded_imports must be an array",
                )
            })?;
            if !excluded.iter().any(|item| item.as_str() == Some(id)) {
                excluded.push(Value::String(id.to_owned()));
            }
            excluded.sort_by_key(|item| item.as_str().unwrap_or_default().to_owned());
        } else {
            let games = self
                .state
                .entry("games")
                .or_insert_with(|| Value::Array(Vec::new()));
            let games = games.as_array_mut().ok_or_else(|| {
                io::Error::new(io::ErrorKind::InvalidData, "games must be an array")
            })?;
            games.retain(|game| game.get("id").and_then(Value::as_str) != Some(id));
        }
        self.save()
    }

    pub fn restore_excluded_imports(&mut self) -> io::Result<usize> {
        let previous = self
            .state
            .insert("excluded_imports".into(), Value::Array(Vec::new()));
        let count = previous
            .as_ref()
            .and_then(Value::as_array)
            .map_or(0, Vec::len);
        self.save()?;
        Ok(count)
    }

    pub fn update_game(&mut self, id: &str, updated: &Map<String, Value>) -> io::Result<()> {
        self.apply_game_update(id, updated)?;
        self.save()
    }

    pub fn update_games(&mut self, updates: &[(String, Map<String, Value>)]) -> io::Result<()> {
        let previous = self.state.clone();
        for (id, updated) in updates {
            if let Err(error) = self.apply_game_update(id, updated) {
                self.state = previous;
                return Err(error);
            }
        }
        if let Err(error) = self.save() {
            self.state = previous;
            return Err(error);
        }
        Ok(())
    }

    fn apply_game_update(&mut self, id: &str, updated: &Map<String, Value>) -> io::Result<()> {
        let imported_source = ["steam", "faugus", "heroic"]
            .iter()
            .find(|source| {
                self.state
                    .get(**source)
                    .and_then(Value::as_array)
                    .is_some_and(|games| {
                        games
                            .iter()
                            .any(|game| game.get("id").and_then(Value::as_str) == Some(id))
                    })
            })
            .copied();
        if let Some(source) = imported_source {
            let patch = self
                .state
                .entry("overrides")
                .or_insert_with(|| Value::Object(Map::new()));
            let patch = patch.as_object_mut().ok_or_else(|| {
                io::Error::new(io::ErrorKind::InvalidData, "overrides must be an object")
            })?;
            let row = patch
                .entry(id.to_owned())
                .or_insert_with(|| Value::Object(Map::new()));
            let row = row.as_object_mut().ok_or_else(|| {
                io::Error::new(
                    io::ErrorKind::InvalidData,
                    "game override must be an object",
                )
            })?;
            for field in [
                "cover",
                "square_cover",
                "logo",
                "banner",
                "banner_secondary",
                "steamgriddb_id",
                "metadata",
                "categories",
            ] {
                if let Some(value) = updated.get(field) {
                    row.insert(field.to_owned(), value.clone());
                }
            }
            let _ = source;
        } else {
            let games = self
                .state
                .entry("games")
                .or_insert_with(|| Value::Array(Vec::new()));
            let games = games.as_array_mut().ok_or_else(|| {
                io::Error::new(io::ErrorKind::InvalidData, "games must be an array")
            })?;
            let Some(game) = games
                .iter_mut()
                .find(|game| game.get("id").and_then(Value::as_str) == Some(id))
            else {
                return Err(io::Error::new(
                    io::ErrorKind::NotFound,
                    "El juego ya no existe.",
                ));
            };
            *game = Value::Object(updated.clone());
        }
        Ok(())
    }

    pub fn scan_steam(&mut self) -> io::Result<(usize, usize)> {
        let home = std::env::var_os("HOME")
            .map(PathBuf::from)
            .unwrap_or_default();
        let data = std::env::var_os("XDG_DATA_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| home.join(".local/share"));
        let excluded = string_set(self.state.get("excluded_imports"));
        let discovered = crate::importers::steam(&home, &data)?
            .into_iter()
            .filter(|game| {
                !excluded.contains(game.get("id").and_then(Value::as_str).unwrap_or_default())
            })
            .collect::<Vec<_>>();
        let mut imported = self
            .state
            .get("steam")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let before = imported
            .iter()
            .filter_map(|game| game.get("id").and_then(Value::as_str))
            .collect::<std::collections::HashSet<_>>();
        let added = discovered
            .iter()
            .filter(|game| {
                !before.contains(game.get("id").and_then(Value::as_str).unwrap_or_default())
            })
            .count();
        merge_games(&mut imported, discovered);
        self.state
            .insert("steam".into(), Value::Array(imported.clone()));
        self.assign_source_category(&imported, "Steam");
        self.save()?;
        Ok((added, imported.len()))
    }

    pub fn scan_faugus(&mut self) -> io::Result<(usize, usize)> {
        let home = std::env::var_os("HOME")
            .map(PathBuf::from)
            .unwrap_or_default();
        let data = std::env::var_os("XDG_DATA_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| home.join(".local/share"));
        let config = std::env::var_os("XDG_CONFIG_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| home.join(".config"));
        let excluded = string_set(self.state.get("excluded_imports"));
        let discovered = crate::importers::faugus(&home, &data, &config)?
            .into_iter()
            .filter(|game| {
                !excluded.contains(game.get("id").and_then(Value::as_str).unwrap_or_default())
            })
            .collect::<Vec<_>>();
        let mut imported = self
            .state
            .get("faugus")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let before = imported
            .iter()
            .filter(|game| !is_faugus_steam(game))
            .filter_map(|game| game.get("id").and_then(Value::as_str))
            .collect::<std::collections::HashSet<_>>();
        let added = discovered
            .iter()
            .filter(|game| {
                !before.contains(game.get("id").and_then(Value::as_str).unwrap_or_default())
            })
            .count();
        imported.retain(|game| is_faugus_steam(game));
        merge_games(&mut imported, discovered);
        self.state
            .insert("faugus".into(), Value::Array(imported.clone()));
        let faugus = imported
            .iter()
            .filter(|game| !is_faugus_steam(game))
            .cloned()
            .collect::<Vec<_>>();
        self.assign_source_category(&faugus, "Faugus");
        self.save()?;
        Ok((added, faugus.len()))
    }

    pub fn scan_heroic(&mut self) -> io::Result<(usize, usize)> {
        let home = std::env::var_os("HOME")
            .map(PathBuf::from)
            .unwrap_or_default();
        let config = std::env::var_os("XDG_CONFIG_HOME")
            .map(PathBuf::from)
            .unwrap_or_else(|| home.join(".config"));
        let excluded = string_set(self.state.get("excluded_imports"));
        let discovered = crate::importers::heroic(&home, &config)?
            .into_iter()
            .filter(|game| {
                !excluded.contains(game.get("id").and_then(Value::as_str).unwrap_or_default())
            })
            .collect::<Vec<_>>();
        let previous = self
            .state
            .get("heroic")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let ids = previous
            .iter()
            .filter_map(|game| game.get("id").and_then(Value::as_str))
            .collect::<std::collections::HashSet<_>>();
        let added = discovered
            .iter()
            .filter(|game| {
                !ids.contains(game.get("id").and_then(Value::as_str).unwrap_or_default())
            })
            .count();
        self.state
            .insert("heroic".into(), Value::Array(discovered.clone()));
        self.assign_source_category(&discovered, "Heroic");
        self.save()?;
        Ok((added, discovered.len()))
    }

    fn assign_source_category(&mut self, games: &[Value], category: &str) {
        if games.is_empty() {
            return;
        }
        let categories = self
            .state
            .entry("categories")
            .or_insert_with(|| Value::Array(Vec::new()));
        let categories = categories
            .as_array_mut()
            .expect("categories schema is an array");
        if !categories
            .iter()
            .any(|value| value.as_str() == Some(category))
        {
            categories.push(Value::String(category.to_owned()));
        }
        let overrides = self
            .state
            .entry("overrides")
            .or_insert_with(|| Value::Object(Map::new()));
        let overrides = overrides
            .as_object_mut()
            .expect("overrides schema is an object");
        for game in games {
            let Some(id) = game.get("id").and_then(Value::as_str) else {
                continue;
            };
            let row = overrides
                .entry(id.to_owned())
                .or_insert_with(|| Value::Object(Map::new()));
            let row = row.as_object_mut().expect("override schema is an object");
            let categories = row.entry("categories").or_insert_with(|| {
                game.get("categories")
                    .cloned()
                    .unwrap_or_else(|| Value::Array(Vec::new()))
            });
            let categories = categories
                .as_array_mut()
                .expect("game categories schema is an array");
            if !categories
                .iter()
                .any(|value| value.as_str() == Some(category))
            {
                categories.push(Value::String(category.to_owned()));
            }
        }
    }

    pub fn save(&self) -> io::Result<()> {
        if let Some(error) = &self.load_error {
            return Err(io::Error::new(io::ErrorKind::InvalidData, error.clone()));
        }
        atomic_json(
            &self.root,
            "library.json",
            &Value::Object(self.state.clone()),
        )
    }
}

fn remove_category_value(game: &mut Value, name: &str) {
    if let Some(categories) = game.get_mut("categories").and_then(Value::as_array_mut) {
        categories.retain(|item| item.as_str() != Some(name));
    }
}

fn replace_category_value(game: &mut Value, previous: &str, name: &str) {
    if let Some(categories) = game.get_mut("categories").and_then(Value::as_array_mut) {
        let mut values = Vec::with_capacity(categories.len());
        for item in categories.iter() {
            let value = if item.as_str() == Some(previous) {
                Value::String(name.to_owned())
            } else {
                item.clone()
            };
            if !values.contains(&value) {
                values.push(value);
            }
        }
        *categories = values;
    }
}

fn replace_string_values(state: &mut Map<String, Value>, key: &str, previous: &str, name: &str) {
    if let Some(values) = state.get_mut(key).and_then(Value::as_array_mut) {
        for item in values.iter_mut() {
            if item.as_str() == Some(previous) {
                *item = Value::String(name.to_owned());
            }
        }
    }
}

fn remove_string_value(state: &mut Map<String, Value>, key: &str, name: &str) {
    if let Some(values) = state.get_mut(key).and_then(Value::as_array_mut) {
        values.retain(|item| item.as_str() != Some(name));
    }
}

fn replace_object_key(state: &mut Map<String, Value>, key: &str, previous: &str, name: &str) {
    if let Some(values) = state.get_mut(key).and_then(Value::as_object_mut)
        && let Some(value) = values.remove(previous)
    {
        values.insert(name.to_owned(), value);
    }
}

fn read_object(path: &Path) -> io::Result<Map<String, Value>> {
    if !path.exists() {
        return Ok(serde_json::from_str(EMPTY_STATE).expect("static empty state is valid"));
    }
    let bytes = fs::read(path)?;
    let value: Value = serde_json::from_slice(&bytes)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
    value
        .as_object()
        .cloned()
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "library.json must be an object"))
}

fn atomic_json(root: &Path, filename: &str, value: &Value) -> io::Result<()> {
    fs::create_dir_all(root)?;
    let temporary = root.join(format!(".{filename}-{}.tmp", unique_suffix()));
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temporary)?;
    let result = (|| {
        serde_json::to_writer_pretty(&mut file, value)?;
        file.write_all(b"\n")?;
        file.sync_all()?;
        fs::rename(&temporary, root.join(filename))
    })();
    if result.is_err() {
        let _ = fs::remove_file(temporary);
    }
    result
}

fn unique_suffix() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    format!("{}-{nanos}", std::process::id())
}

fn expand_home(path: &str) -> PathBuf {
    path.strip_prefix("~/").map_or_else(
        || PathBuf::from(path),
        |tail| PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(tail),
    )
}

fn string_set(value: Option<&Value>) -> std::collections::HashSet<String> {
    value
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(str::to_owned)
        .collect()
}

fn is_faugus_steam(game: &Value) -> bool {
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

fn merge_games(existing: &mut Vec<Value>, discovered: Vec<Value>) {
    for game in discovered {
        let id = game.get("id").and_then(Value::as_str);
        if let Some(index) = existing
            .iter()
            .position(|item| item.get("id").and_then(Value::as_str) == id)
        {
            existing[index] = game;
        } else {
            existing.push(game);
        }
    }
}

fn launcher_command(
    install: Option<&str>,
    native: &str,
    flatpak_id: &str,
    args: &[&str],
    token: &str,
    heroic_env: Option<(&str, &str)>,
) -> io::Result<Command> {
    if install == Some("flatpak") {
        let mut command = Command::new("flatpak");
        command
            .arg("run")
            .arg(format!("--env=ESTANTE_GAME_SESSION={token}"));
        if let Some((name, runner)) = heroic_env {
            command.arg(format!("--env=HEROIC_APP_NAME={name}"));
            command.arg(format!("--env=HEROIC_APP_RUNNER={runner}"));
        }
        command.arg(flatpak_id).args(args);
        Ok(command)
    } else {
        let mut command = Command::new(native);
        command.args(args);
        Ok(command)
    }
}

fn url_encode(value: &str) -> String {
    let mut encoded = String::with_capacity(value.len());
    for byte in value.bytes() {
        if byte.is_ascii_alphanumeric() || b"-_.~".contains(&byte) {
            encoded.push(byte as char);
        } else {
            encoded.push_str(&format!("%{byte:02X}"));
        }
    }
    encoded
}

#[cfg(test)]
mod category_tests {
    use super::Library;
    use serde_json::json;

    #[test]
    fn category_rename_order_and_default_preserve_game_data() {
        let root = std::env::temp_dir().join(format!(
            "estante-category-test-{}-{}",
            std::process::id(),
            super::unique_suffix()
        ));
        let mut library = Library::open(&root);
        library.state = json!({
            "categories": ["Aventura", "RPG"],
            "games": [{"id":"local:1", "title":"Game", "categories":["Aventura", "RPG"]}],
            "overrides": {"steam:2":{"categories":["Aventura"]}},
            "category_order": ["Aventura", "RPG"],
            "primary_category": "Aventura",
            "category_icons": {"Aventura":"adventure.png"},
            "category_icon_sources": {"Aventura":{"source":"test"}}
        })
        .as_object()
        .unwrap()
        .clone();

        library.rename_category("Aventura", "Acción").unwrap();
        assert_eq!(library.categories(&library.games()), ["Acción", "RPG"]);
        assert_eq!(library.primary_category(), Some("Acción"));
        assert_eq!(
            library.state["games"][0]["categories"],
            json!(["Acción", "RPG"])
        );
        assert_eq!(
            library.state["overrides"]["steam:2"]["categories"],
            json!(["Acción"])
        );
        assert_eq!(library.state["category_icons"]["Acción"], "adventure.png");

        let games = library.games();
        library.move_category("RPG", -1, &games).unwrap();
        assert_eq!(library.categories(&library.games()), ["RPG", "Acción"]);
        library
            .set_primary_category(Some("RPG"), &library.games())
            .unwrap();
        library.remove_category("RPG").unwrap();
        assert_eq!(library.primary_category(), None);
        assert_eq!(library.categories(&library.games()), ["Acción"]);

        drop(library);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn category_rename_rejects_reserved_and_duplicate_names() {
        let root = std::env::temp_dir().join(format!(
            "estante-category-invalid-test-{}-{}",
            std::process::id(),
            super::unique_suffix()
        ));
        let mut library = Library::open(&root);
        library.add_category("RPG").unwrap();
        library.add_category("Puzzle").unwrap();
        assert!(library.rename_category("RPG", "Todos").is_err());
        assert!(library.rename_category("RPG", "puzzle").is_err());
        assert!(
            library
                .categories(&library.games())
                .contains(&"RPG".to_owned())
        );
        drop(library);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn local_category_icon_is_validated_copied_and_removable() {
        let root = std::env::temp_dir().join(format!(
            "estante-category-icon-test-{}-{}",
            std::process::id(),
            super::unique_suffix()
        ));
        let source = root.join("source.png");
        std::fs::create_dir_all(&root).unwrap();
        image::RgbImage::from_pixel(2, 2, image::Rgb([255, 255, 255]))
            .save(&source)
            .unwrap();
        let mut library = Library::open(&root);
        library.state.insert("categories".into(), json!(["RPG"]));
        library
            .import_category_icon(Some("RPG"), &source, None)
            .unwrap();
        let saved = library.category_icon_path("RPG").unwrap();
        assert_ne!(saved, source);
        assert!(saved.is_file());
        library.clear_category_icon(Some("RPG")).unwrap();
        assert!(library.category_icon_path("RPG").is_none());
        drop(library);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn category_membership_updates_import_overrides_and_keeps_other_categories() {
        let root = std::env::temp_dir().join(format!(
            "estante-category-member-test-{}-{}",
            std::process::id(),
            super::unique_suffix()
        ));
        let mut library = Library::open(&root);
        library.state = json!({
            "categories": ["RPG"],
            "games": [{"id":"local:1", "title":"Local", "categories":["RPG", "Indie"]}],
            "steam": [{"id":"steam:1", "title":"Imported", "kind":"steam", "categories":["Steam"]}],
            "overrides": {}
        })
        .as_object()
        .unwrap()
        .clone();
        library.set_category_member("RPG", "steam:1", true).unwrap();
        assert_eq!(
            library.state["overrides"]["steam:1"]["categories"],
            json!(["Steam", "RPG"])
        );
        library
            .set_category_member("RPG", "local:1", false)
            .unwrap();
        assert_eq!(library.state["games"][0]["categories"], json!(["Indie"]));
        assert!(
            library
                .set_category_member("Missing", "local:1", true)
                .is_err()
        );
        assert!(
            library
                .set_category_member("RPG", "missing:1", true)
                .is_err()
        );
        drop(library);
        let _ = std::fs::remove_dir_all(root);
    }
}
