use crate::{
    artwork::ArtworkOption,
    metadata::MetadataOption,
    model::{Game, Library},
};
use image::ImageDecoder;
use serde_json::{Map, Value, json};
use slint::{
    LogicalPosition,
    platform::{PointerEventButton, WindowEvent},
    winit_030::{EventResult, WinitWindowAccessor, winit::event::WindowEvent as NativeWindowEvent},
    Image, Model, ModelRc, SharedPixelBuffer, VecModel,
};
use std::{
    cell::RefCell,
    collections::HashMap,
    error::Error,
    fs,
    path::{Path, PathBuf},
    rc::Rc,
    sync::atomic::{AtomicBool, AtomicU64, Ordering},
    sync::mpsc,
    sync::{Arc, Condvar, Mutex},
    thread,
    time::{Duration, Instant},
};

slint::include_modules!();

static SUPERVISOR_HANDOFF_EXIT: AtomicBool = AtomicBool::new(false);
static CATEGORY_DRAFT_SEQUENCE: AtomicU64 = AtomicU64::new(0);

struct BackgroundRequest {
    generation: u64,
    game: Game,
    split: String,
    blur: i32,
    position: String,
    size: (u32, u32),
    global: Option<String>,
    fill_mode: String,
    fallback_color: [u8; 3],
}

struct RowImageInput {
    index: usize,
    id: String,
    logo_path: String,
    square_cover_path: String,
    cover_path: String,
    selected: bool,
    load_grid_covers: bool,
    load_list_image: bool,
}

struct RowImageRequest {
    generation: u64,
    list_max_width: u32,
    list_max_height: u32,
    cover_max_width: u32,
    cover_max_height: u32,
    list_artwork: String,
    rows: Vec<RowImageInput>,
}

#[derive(Clone)]
struct CategoryDraftOperation {
    action: String,
    name: String,
    previous: String,
    credit: Option<Value>,
}

struct CategoryDraftDirectory {
    path: PathBuf,
}

impl CategoryDraftDirectory {
    fn create(source_root: &Path) -> std::io::Result<Self> {
        let path = std::env::temp_dir().join(format!(
            "estante-category-draft-{}-{}",
            std::process::id(),
            CATEGORY_DRAFT_SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ));
        copy_category_draft_files(source_root, &path)?;
        Ok(Self { path })
    }

    fn reset(&mut self, source_root: &Path) -> std::io::Result<()> {
        fs::remove_dir_all(&self.path)?;
        copy_category_draft_files(source_root, &self.path)
    }
}

impl Drop for CategoryDraftDirectory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.path);
    }
}

fn copy_category_draft_files(source_root: &Path, draft_root: &Path) -> std::io::Result<()> {
    fs::create_dir_all(draft_root)?;
    let source_library = source_root.join("library.json");
    if source_library.is_file() {
        fs::copy(source_library, draft_root.join("library.json"))?;
    }
    let source_icons = source_root.join("category-icons");
    if source_icons.is_dir() {
        let draft_icons = draft_root.join("category-icons");
        fs::create_dir_all(&draft_icons)?;
        for entry in fs::read_dir(source_icons)? {
            let entry = entry?;
            if entry.file_type()?.is_file() {
                fs::copy(entry.path(), draft_icons.join(entry.file_name()))?;
            }
        }
    }
    Ok(())
}

fn apply_category_draft_operation(
    library: &mut Library,
    operation: &CategoryDraftOperation,
) -> std::io::Result<()> {
    let category = (!operation.name.is_empty()).then_some(operation.name.as_str());
    match operation.action.as_str() {
        "add" => library.add_category(operation.name.trim()),
        "rename" => library.rename_category(&operation.previous, &operation.name),
        "delete" => library.remove_category(&operation.name),
        "up" | "down" => library.move_category(
            &operation.name,
            if operation.action == "up" { -1 } else { 1 },
            &library.games(),
        ),
        "primary" => library.set_primary_category(category, &library.games()),
        "join" | "leave" => library.set_category_member(
            &operation.name,
            &operation.previous,
            operation.action == "join",
        ),
        "icon" => library.import_category_icon(
            category,
            &expand_user_path(operation.previous.trim()),
            operation.credit.clone(),
        ),
        "clear-icon" => library.clear_category_icon(category),
        _ => Ok(()),
    }
}

struct ScreensaverImageRequest {
    generation: u64,
    path: String,
    max_width: u32,
    max_height: u32,
}

struct RowImagePixels {
    width: u32,
    height: u32,
    rgba: Vec<u8>,
    cache_bytes: usize,
}

struct RowImageOutput {
    input: RowImageInput,
    list_is_logo: bool,
    list_image_path: Option<String>,
    cover_image_path: Option<String>,
    square_cover_image_path: Option<String>,
    logo_image_path: Option<String>,
    list_image: Option<Arc<RowImagePixels>>,
    cover_image: Option<Arc<RowImagePixels>>,
    square_cover_image: Option<Arc<RowImagePixels>>,
    logo_image: Option<Arc<RowImagePixels>>,
}

type PendingRowImageRequest = Arc<(Mutex<Option<RowImageRequest>>, Condvar)>;
type PendingScreensaverImageRequest = Arc<(Mutex<Option<ScreensaverImageRequest>>, Condvar)>;

fn background_request_is_current(generation: &AtomicU64, request: u64) -> bool {
    generation.load(Ordering::Acquire) == request
}

fn start_screensaver_image_worker(
    window: &ListWindow,
) -> (Arc<AtomicU64>, PendingScreensaverImageRequest) {
    let generation = Arc::new(AtomicU64::new(0));
    let pending = Arc::new((Mutex::new(None::<ScreensaverImageRequest>), Condvar::new()));
    let generation_for_worker = generation.clone();
    let pending_for_worker = pending.clone();
    let weak = window.as_weak();
    thread::spawn(move || {
        let mut cache = HashMap::new();
        let mut order = std::collections::VecDeque::new();
        let mut cache_bytes = 0usize;
        loop {
            let request = {
                let (latest, ready) = &*pending_for_worker;
                let mut latest = latest.lock().unwrap();
                while latest.is_none() {
                    latest = ready.wait(latest).unwrap();
                }
                latest.take().unwrap()
            };
            if !background_request_is_current(&generation_for_worker, request.generation) {
                continue;
            }
            let pixels = row_image_pixels(
                Some(&request.path),
                request.max_width,
                request.max_height,
                false,
                &mut cache,
                &mut order,
                &mut cache_bytes,
            );
            let fallback_path = request.path.clone();
            let generation = generation_for_worker.clone();
            let request_generation = request.generation;
            if weak
                .upgrade_in_event_loop(move |window| {
                    if !background_request_is_current(&generation, request_generation)
                        || !window.get_screensaver_active()
                    {
                        return;
                    }
                    let rendered = pixels
                        .map(|pixels| row_pixels_to_image(&pixels))
                        .unwrap_or_else(|| image(Some(&fallback_path)));
                    window.set_screensaver_image(rendered);
                })
                .is_err()
            {
                break;
            }
        }
    });
    (generation, pending)
}

fn request_screensaver_image(
    window: &ListWindow,
    path: &str,
    generation: &AtomicU64,
    pending: &PendingScreensaverImageRequest,
) {
    let request_generation = generation.fetch_add(1, Ordering::AcqRel).wrapping_add(1);
    let size = window.window().size();
    let request = ScreensaverImageRequest {
        generation: request_generation,
        path: path.to_owned(),
        max_width: size.width.clamp(1, 2560),
        max_height: size.height.clamp(1, 1440),
    };
    *pending.0.lock().unwrap() = Some(request);
    pending.1.notify_one();
}

fn cancel_screensaver_image_request(
    generation: &AtomicU64,
    pending: &PendingScreensaverImageRequest,
) {
    generation.fetch_add(1, Ordering::AcqRel);
    *pending.0.lock().unwrap() = None;
}

fn ui_settings_snapshot(window: &ListWindow) -> Value {
    let mut snapshot = json!({
        "layout": window.get_library_layout().to_string(),
        "list_side": window.get_list_side().to_string(),
        "ui_color_mode": if window.get_pastel_theme() { "pastel" } else { "system" },
        "ui_theme": window.get_color_theme().to_string(),
        "playing_behavior": window.get_playing_behavior().to_string(),
        "start_steam_on_start": window.get_start_steam_on_start(),
        "start_fullscreen": window.get_start_fullscreen(),
        "start_faugus_on_start": window.get_start_faugus_on_start(),
        "start_heroic_on_start": window.get_start_heroic_on_start(),
        "close_steam_on_exit": window.get_close_steam_on_exit(),
        "close_faugus_on_exit": window.get_close_faugus_on_exit(),
        "close_heroic_on_exit": window.get_close_heroic_on_exit(),
        "controller_type": window.get_controller_type().to_string(),
        "onscreen_keyboard": window.get_onscreen_keyboard().to_string(),
        "language": window.get_language().to_string(),
        "date_format": window.get_date_format().to_string(),
        "keyboard_fallback": window.get_keyboard_fallback(),
        "check_updates_on_start": window.get_check_updates_on_start(),
        "steamgriddb_key": window.get_steamgriddb_key().to_string(),
        "igdb_client_id": window.get_igdb_client_id().to_string(),
        "igdb_client_secret": window.get_igdb_client_secret().to_string(),
        "show_session_history": window.get_show_session_history(),
        "screensaver_enabled": window.get_screensaver_enabled(),
        "screensaver_idle_value": window.get_screensaver_idle_value(),
        "screensaver_idle_unit": window.get_screensaver_idle_unit().to_string(),
        "screensaver_slide_value": window.get_screensaver_slide_value(),
        "screensaver_slide_unit": window.get_screensaver_slide_unit().to_string(),
        "screensaver_dim": window.get_screensaver_dim(),
        "screensaver_source": window.get_screensaver_source().to_string(),
        "screensaver_background": window.get_screensaver_background().to_string(),
        "list_focus_zoom": window.get_focus_zoom(),
        "list_cover_zoom": window.get_cover_zoom(),
        "list_artwork": window.get_list_artwork().to_string(),
        "list_artwork_radius": window.get_list_artwork_radius(),
        "grid_zoom": window.get_grid_zoom(),
        "grid_page_size": window.get_grid_page_size(),
        "background_source": window.get_background_source().to_string(),
        "global_background": window.get_global_background().to_string(),
        "background_fill": window.get_background_fill().to_string(),
    });
    snapshot["hero_positions"] = json!({ "list": window.get_hero_position().to_string() });
    snapshot["background_splits"] = json!({ "list": window.get_background_split().to_string() });
    snapshot["background_dim"] = json!({ "list": window.get_dim() });
    snapshot["background_blur"] = json!({ "list": window.get_blur() });
    snapshot["minimal_views"] = json!({ "list": window.get_minimal() });
    snapshot["show_launcher_details"] = json!({ "list": window.get_launcher_details() });
    snapshot["show_game_information"] = json!({ "list": window.get_show_game_information() });
    snapshot["show_detail_cover"] = json!({ "list": window.get_show_detail_cover() });
    snapshot["cover_formats"] = json!({ "list": window.get_cover_format().to_string() });
    snapshot["cover_radii"] = json!({ "list": window.get_cover_radius() });
    snapshot["selection_rings"] = json!({ "list": {
        "focus_ring_enabled": window.get_ring_enabled(),
        "focus_ring_color": window.get_ring_color_text().to_string(),
        "focus_ring_width": window.get_ring_width(),
        "focus_ring_radius": window.get_ring_radius(),
    }, "grid": {
        "focus_ring_enabled": window.get_grid_ring_enabled(),
        "focus_ring_color": window.get_grid_ring_color_text().to_string(),
        "focus_ring_width": window.get_grid_ring_width(),
        "focus_ring_radius": window.get_grid_ring_radius(),
    } });
    snapshot["minimal_views"]["grid"] = json!(window.get_grid_minimal());
    snapshot["background_dim"]["grid"] = json!(window.get_grid_dim());
    snapshot["background_blur"]["grid"] = json!(window.get_grid_blur());
    snapshot["cover_formats"]["grid"] = json!(window.get_grid_cover_format().to_string());
    snapshot["hero_positions"]["grid"] = json!(window.get_grid_hero_position().to_string());
    snapshot["background_splits"]["grid"] = json!(window.get_grid_background_split().to_string());
    snapshot["cover_radii"]["grid"] = json!(window.get_grid_cover_radius());
    snapshot["show_launcher_details"]["grid"] = json!(window.get_grid_launcher_details());
    snapshot
}

fn restore_ui_settings_snapshot(window: &ListWindow, snapshot: &Value) {
    let pastel = setting_choice(snapshot, "ui_color_mode", "pastel", &["pastel", "system"])
        == "pastel";
    window.set_list_side(string_setting(snapshot, "list_side", "bottom").into());
    window.set_library_layout(normalize_slint_layout(string_setting(snapshot, "layout", "list")).into());
    window.set_pastel_theme(pastel);
    window.global::<Theme>().set_pastel(pastel);
    window.set_color_theme(string_setting(snapshot, "ui_theme", "default").into());
    window.set_playing_behavior(string_setting(snapshot, "playing_behavior", "none").into());
    window.set_start_steam_on_start(bool_setting(snapshot, "start_steam_on_start", false));
    window.set_start_fullscreen(bool_setting(snapshot, "start_fullscreen", true));
    window.set_start_faugus_on_start(bool_setting(snapshot, "start_faugus_on_start", false));
    window.set_start_heroic_on_start(bool_setting(snapshot, "start_heroic_on_start", false));
    window.set_close_steam_on_exit(bool_setting(snapshot, "close_steam_on_exit", false));
    window.set_close_faugus_on_exit(bool_setting(snapshot, "close_faugus_on_exit", false));
    window.set_close_heroic_on_exit(bool_setting(snapshot, "close_heroic_on_exit", false));
    window.set_controller_type(string_setting(snapshot, "controller_type", "xbox").into());
    window.set_onscreen_keyboard(string_setting(snapshot, "onscreen_keyboard", "builtin").into());
    window.set_language(string_setting(snapshot, "language", "system").into());
    window.set_date_format(
        setting_choice(snapshot, "date_format", "dmy", &["dmy", "mdy", "ymd"]).into(),
    );
    window.set_keyboard_fallback(bool_setting(snapshot, "keyboard_fallback", true));
    window.set_check_updates_on_start(bool_setting(snapshot, "check_updates_on_start", false));
    window.set_steamgriddb_key(string_setting(snapshot, "steamgriddb_key", "").into());
    window.set_igdb_client_id(string_setting(snapshot, "igdb_client_id", "").into());
    window.set_igdb_client_secret(string_setting(snapshot, "igdb_client_secret", "").into());
    window.set_show_session_history(bool_setting(snapshot, "show_session_history", true));
    window.set_screensaver_enabled(bool_setting(snapshot, "screensaver_enabled", false));
    window.set_screensaver_idle_value(setting_number(snapshot, "screensaver_idle_value", 5, 1, 240));
    window.set_screensaver_idle_unit(string_setting(snapshot, "screensaver_idle_unit", "minutes").into());
    window.set_screensaver_slide_value(setting_number(snapshot, "screensaver_slide_value", 30, 1, 60));
    window.set_screensaver_slide_unit(string_setting(snapshot, "screensaver_slide_unit", "seconds").into());
    window.set_screensaver_dim(setting_number(snapshot, "screensaver_dim", 30, 0, 100));
    window.set_screensaver_source(string_setting(snapshot, "screensaver_source", "games").into());
    window.set_screensaver_background(string_setting(snapshot, "screensaver_background", "bundled:6.png").into());
    window.set_focus_zoom(setting_number(snapshot, "list_focus_zoom", 150, 100, 250));
    window.set_cover_zoom(setting_number(snapshot, "list_cover_zoom", 100, 50, 175));
    window.set_list_artwork(string_setting(snapshot, "list_artwork", "logo").into());
    window.set_list_artwork_radius(setting_number(snapshot, "list_artwork_radius", 12, 0, 40));
    window.set_grid_zoom(setting_number(snapshot, "grid_zoom", 100, 50, 200));
    window.set_grid_page_size(setting_number(snapshot, "grid_page_size", 10, 1, 100));
    window.set_background_source(string_setting(snapshot, "background_source", "game").into());
    window.set_global_background(string_setting(snapshot, "global_background", "bundled:6.png").into());
    window.set_background_fill(string_setting(snapshot, "background_fill", "blur").into());
    window.set_hero_position(
        nested_choice(snapshot, "hero_positions", "list", "full", &["full", "top", "lower"])
            .into(),
    );
    window.set_background_split(
        nested_choice(
            snapshot,
            "background_splits",
            "list",
            "single",
            &["single", "horizontal", "vertical", "diagonal"],
        )
        .into(),
    );
    window.set_dim(nested_number(snapshot, "background_dim", "list", 78, 0, 100));
    window.set_blur(nested_number(snapshot, "background_blur", "list", 0, 0, 40));
    window.set_minimal(nested_bool(snapshot, "minimal_views", "list", false));
    window.set_launcher_details(nested_bool(snapshot, "show_launcher_details", "list", true));
    window.set_show_game_information(nested_bool(snapshot, "show_game_information", "list", true));
    window.set_show_detail_cover(nested_bool(snapshot, "show_detail_cover", "list", true));
    window.set_cover_format(
        nested_choice(snapshot, "cover_formats", "list", "portrait", &["portrait", "square", "logo"])
            .into(),
    );
    window.set_cover_radius(nested_number(snapshot, "cover_radii", "list", 12, 0, 40));
    let ring = snapshot.get("selection_rings").and_then(|rings| rings.get("list"));
    window.set_ring_enabled(
        ring.and_then(|ring| ring.get("focus_ring_enabled"))
            .and_then(Value::as_bool)
            .unwrap_or(true),
    );
    let ring_color = ring
        .and_then(|ring| ring.get("focus_ring_color"))
        .and_then(Value::as_str)
        .unwrap_or("#ffffff");
    window.set_ring_color_text(ring_color.into());
    window.set_ring_color(parse_color(ring_color));
    window.set_ring_width(nested_ring_number(ring, "focus_ring_width", 6, 0, 12));
    window.set_ring_radius(nested_ring_number(ring, "focus_ring_radius", 18, 0, 50));
    window.set_grid_minimal(nested_bool(snapshot, "minimal_views", "grid", false));
    window.set_grid_dim(nested_number(snapshot, "background_dim", "grid", 50, 0, 100));
    window.set_grid_blur(nested_number(snapshot, "background_blur", "grid", 0, 0, 40));
    window.set_grid_cover_format(nested_choice(snapshot, "cover_formats", "grid", "portrait", &["portrait", "square"]).into());
    window.set_grid_hero_position(nested_choice(snapshot, "hero_positions", "grid", "full", &["full", "top", "lower"]).into());
    window.set_grid_background_split(nested_choice(snapshot, "background_splits", "grid", "single", &["single", "horizontal", "vertical", "diagonal"]).into());
    window.set_grid_cover_radius(nested_number(snapshot, "cover_radii", "grid", 12, 0, 40));
    window.set_grid_launcher_details(nested_bool(snapshot, "show_launcher_details", "grid", true));
    let grid_ring = snapshot.get("selection_rings").and_then(|rings| rings.get("grid"));
    window.set_grid_ring_enabled(grid_ring.and_then(|ring| ring.get("focus_ring_enabled")).and_then(Value::as_bool).unwrap_or(true));
    let grid_ring_color = grid_ring.and_then(|ring| ring.get("focus_ring_color")).and_then(Value::as_str).filter(|value| valid_color(value)).unwrap_or("#ffffff");
    window.set_grid_ring_color_text(grid_ring_color.into());
    window.set_grid_ring_color(parse_color(grid_ring_color));
    window.set_grid_ring_width(nested_ring_number(grid_ring, "focus_ring_width", 3, 0, 12));
    window.set_grid_ring_radius(nested_ring_number(grid_ring, "focus_ring_radius", 18, 0, 50));
}

fn string_setting<'a>(settings: &'a Value, key: &str, default: &'a str) -> &'a str {
    settings.get(key).and_then(Value::as_str).unwrap_or(default)
}

fn bool_setting(settings: &Value, key: &str, default: bool) -> bool {
    settings.get(key).and_then(Value::as_bool).unwrap_or(default)
}

fn merge_changed_settings(target: &mut Value, baseline: &Value, current: &Value) {
    let Some(current) = current.as_object() else {
        return;
    };
    for (key, value) in current {
        if let Some(value) = value.as_object() {
            if !target.get(key).is_some_and(Value::is_object) {
                target[key] = json!({});
            }
            merge_changed_settings(
                &mut target[key],
                baseline.get(key).unwrap_or(&Value::Null),
                &Value::Object(value.clone()),
            );
        } else if baseline.get(key) != Some(value) {
            target[key] = value.clone();
        }
    }
}

fn language_code(preference: &str) -> &'static str {
    if preference == "es" {
        return "es";
    }
    if preference == "en" {
        return "en";
    }
    let locale = ["LC_ALL", "LANGUAGE", "LC_MESSAGES", "LANG"]
        .into_iter()
        .filter_map(|key| std::env::var(key).ok())
        .find(|value| !value.is_empty())
        .unwrap_or_else(|| "en".to_owned());
    if locale
        .split(':')
        .next()
        .unwrap_or_default()
        .to_ascii_lowercase()
        .replace('-', "_")
        .split(['_', '.'])
        .next()
        == Some("es")
    {
        "es"
    } else {
        "en"
    }
}

fn normalize_slint_layout(layout: &str) -> &'static str {
    if layout == "grid" { "grid" } else { "list" }
}

fn set_status(window: &ListWindow, spanish: &str, english: &str) {
    window.set_save_message(if window.get_english_ui() {
        english.into()
    } else {
        spanish.into()
    });
}

fn set_status_error(
    window: &ListWindow,
    spanish: &str,
    english: &str,
    error: impl std::fmt::Display,
) {
    window.set_save_message(
        if window.get_english_ui() {
            format!("{english}{error}")
        } else {
            format!("{spanish}{error}")
        }
        .into(),
    );
}

fn localize_provider_error(window: &ListWindow, error: String) -> String {
    if !window.get_english_ui() {
        return error;
    }
    if let Some(reason) = error.strip_prefix("No se pudo iniciar curl: ") {
        return format!("Could not start curl: {reason}");
    }
    match error.as_str() {
        "No se encontró el juego en SteamGridDB." => "Game not found in SteamGridDB.",
        "ID de SteamGridDB no válido." => "Invalid SteamGridDB ID.",
        "Campo de imagen no válido." => "Invalid artwork field.",
        "La dirección de imagen no pertenece al proveedor seleccionado." => {
            "The image URL does not belong to the selected provider."
        }
        "El proveedor devolvió una imagen no válida." => {
            "The provider returned an invalid image."
        }
        "Configura las credenciales de IGDB y escribe un título." => {
            "Configure IGDB credentials and enter a title."
        }
        "IGDB no devolvió un token de acceso." => "IGDB did not return an access token.",
        "Escribe el nombre del juego para buscar en Steam."
        | "Escribe un título para buscar en Steam." => "Enter a game title to search Steam.",
        "Steam no devolvió resultados." => "Steam returned no results.",
        "Steam no encontró el juego." => "Steam could not find the game.",
        "Steam devolvió un ID no válido." | "Identificador de Steam no válido." => {
            "Steam returned an invalid ID."
        }
        "Steam no tiene una ficha disponible para este juego." => {
            "Steam has no metadata for this game."
        }
        "Steam no tiene capturas disponibles para este juego." => {
            "Steam has no screenshots for this game."
        }
        "Añade tu clave de SteamGridDB en Ajustes." => "Add your SteamGridDB key in Settings.",
        "Ruta SteamGridDB no válida." => "Invalid SteamGridDB route.",
        "SteamGridDB no pudo completar la búsqueda." => {
            "SteamGridDB could not complete the search."
        }
        "Respuesta de SteamGridDB no válida." => "Invalid response from SteamGridDB.",
        "Solo se permiten direcciones HTTPS." => "Only HTTPS URLs are allowed.",
        "Escribe un nombre de juego para buscar en Wikidata." => {
            "Enter a game title to search Wikidata."
        }
        "Identificador de Wikidata no válido." => "Invalid Wikidata identifier.",
        "Wikidata no devolvió la ficha solicitada." => "Wikidata returned no requested metadata.",
        "No se pudo sincronizar la consulta a Wikidata." => {
            "Could not synchronize the Wikidata query."
        }
        "No se pudo consultar Wikidata." => "Could not query Wikidata.",
        _ => return error,
    }
    .to_owned()
}

enum ImportOutcome {
    Restored(usize),
    Scraped(usize, usize, Vec<String>),
    Scanned { added: usize, total: usize },
}

const LAUNCHERS: [&str; 3] = ["steam", "faugus", "heroic"];

enum SessionEvent {
    LauncherSnapshot(std::io::Result<std::collections::HashSet<&'static str>>),
    LauncherAction(usize, Result<(), String>),
    Started(String),
    Screensaver,
    TrayStarted(Result<ksni::blocking::Handle<EstanteTray>, String>),
    RestoreFromTray,
    ExitFromTray,
    IconResults(
        String,
        String,
        Result<Vec<crate::category_icons::IconOption>, String>,
    ),
    IconDownloaded(
        u64,
        String,
        crate::category_icons::IconOption,
        Result<PathBuf, String>,
    ),
    ImportFinished(Result<ImportOutcome, String>),
    Warning(String),
    Finished(Result<(), String>),
    Handoff(PathBuf, mpsc::Sender<bool>),
}

struct EstanteTray {
    events: mpsc::Sender<SessionEvent>,
    english: bool,
}

impl ksni::Tray for EstanteTray {
    fn id(&self) -> String {
        "io.github.estante.Launcher".into()
    }

    fn title(&self) -> String {
        "Estante".into()
    }

    fn icon_name(&self) -> String {
        "io.github.estante.Launcher".into()
    }

    fn icon_theme_path(&self) -> String {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../packaging")
            .to_string_lossy()
            .into_owned()
    }

    fn activate(&mut self, _x: i32, _y: i32) {
        let _ = self.events.send(SessionEvent::RestoreFromTray);
    }

    fn menu(&self) -> Vec<ksni::MenuItem<Self>> {
        use ksni::menu::StandardItem;

        let restore = if self.english {
            "Open Estante"
        } else {
            "Abrir Estante"
        };
        let exit = if self.english { "Quit" } else { "Salir" };
        vec![
            StandardItem {
                label: restore.into(),
                icon_name: "view-restore".into(),
                activate: Box::new(|tray: &mut EstanteTray| {
                    let _ = tray.events.send(SessionEvent::RestoreFromTray);
                }),
                ..Default::default()
            }
            .into(),
            ksni::MenuItem::Separator,
            StandardItem {
                label: exit.into(),
                icon_name: "application-exit".into(),
                activate: Box::new(|tray: &mut EstanteTray| {
                    let _ = tray.events.send(SessionEvent::ExitFromTray);
                }),
                ..Default::default()
            }
            .into(),
        ]
    }
}

pub fn run() -> Result<(), Box<dyn Error>> {
    let library = Library::open_default();
    let settings_root = library.data_dir().to_path_buf();
    let launcher_issues = library
        .settings()
        .map(|settings| crate::launchers::start_configured(&settings))
        .unwrap_or_default();
    let (window, _timer) = build_window(library, true, crate::take_resume_file())?;
    window.set_focus_library_request(true);
    if !launcher_issues.is_empty() {
        set_status_error(
            &window,
            "No se pudieron iniciar algunos lanzadores: ",
            "Could not start some launchers: ",
            launcher_issues.join("; "),
        );
    }
    let run_result = window.run();
    if !SUPERVISOR_HANDOFF_EXIT.swap(false, Ordering::Relaxed)
        && let Ok(settings) = Library::open(settings_root).settings()
    {
        for (client, key) in [
            ("steam", "close_steam_on_exit"),
            ("heroic", "close_heroic_on_exit"),
            ("faugus", "close_faugus_on_exit"),
        ] {
            if settings.get(key).and_then(Value::as_bool) == Some(true)
                && let Err(error) = crate::launchers::operate(client, false)
            {
                eprintln!("Estante: no se pudo cerrar {client}: {error}");
            }
        }
    }
    run_result?;
    Ok(())
}

fn build_window(
    library: Library,
    poll_devices: bool,
    restore: Option<Value>,
) -> Result<(ListWindow, slint::Timer), Box<dyn Error>> {
    let games = library.games();
    let (settings, can_save, settings_error) = match library.settings() {
        Ok(settings) => (settings, true, None),
        Err(error) => (Value::Object(Map::new()), false, Some(error.to_string())),
    };
    let saver_paths = Rc::new(RefCell::new(screensaver_paths(&settings, &games)));
    let window = ListWindow::new()?;
    let (connectivity_requests, connectivity_states) = crate::connectivity::start_worker();
    let connectivity_for_refresh = connectivity_requests.clone();
    let weak_for_connectivity_refresh = window.as_weak();
    window.on_refresh_connectivity(move || {
        if let Some(window) = weak_for_connectivity_refresh.upgrade() {
            window.set_connectivity_busy(true);
            window.set_connectivity_error("".into());
        }
        let _ = connectivity_for_refresh.send(crate::connectivity::Request::Refresh);
    });
    let connectivity_for_wifi = connectivity_requests.clone();
    let weak_for_wifi = window.as_weak();
    window.on_set_wifi_enabled(move |enabled| {
        if let Some(window) = weak_for_wifi.upgrade() {
            window.set_connectivity_busy(true);
            window.set_connectivity_error("".into());
        }
        let _ = connectivity_for_wifi.send(crate::connectivity::Request::SetWifi(enabled));
    });
    let connectivity_for_bluetooth = connectivity_requests.clone();
    let weak_for_bluetooth = window.as_weak();
    window.on_set_bluetooth_enabled(move |enabled| {
        if let Some(window) = weak_for_bluetooth.upgrade() {
            window.set_connectivity_busy(true);
            window.set_connectivity_error("".into());
        }
        let _ = connectivity_for_bluetooth.send(crate::connectivity::Request::SetBluetooth(enabled));
    });
    let connectivity_for_scan = connectivity_requests.clone();
    let weak_for_scan = window.as_weak();
    window.on_scan_bluetooth(move || {
        if let Some(window) = weak_for_scan.upgrade() {
            window.set_connectivity_busy(true);
            window.set_bluetooth_scanning(true);
            window.set_connectivity_error("".into());
        }
        let _ = connectivity_for_scan.send(crate::connectivity::Request::ScanBluetooth);
    });
    let connectivity_for_discoverable = connectivity_requests.clone();
    let weak_for_discoverable = window.as_weak();
    window.on_set_bluetooth_discoverable(move |enabled| {
        if let Some(window) = weak_for_discoverable.upgrade() {
            window.set_connectivity_busy(true);
            window.set_connectivity_error("".into());
        }
        let _ = connectivity_for_discoverable
            .send(crate::connectivity::Request::SetBluetoothDiscoverable(enabled));
    });
    let connectivity_for_pairable = connectivity_requests.clone();
    let weak_for_pairable = window.as_weak();
    window.on_set_bluetooth_pairable(move |enabled| {
        if let Some(window) = weak_for_pairable.upgrade() {
            window.set_connectivity_busy(true);
            window.set_connectivity_error("".into());
        }
        let _ = connectivity_for_pairable
            .send(crate::connectivity::Request::SetBluetoothPairable(enabled));
    });
    let connectivity_for_device = connectivity_requests.clone();
    let weak_for_device = window.as_weak();
    window.on_bluetooth_device_action(move |address, action| {
        if let Some(window) = weak_for_device.upgrade() {
            window.set_connectivity_busy(true);
            window.set_connectivity_error("".into());
        }
        let _ = connectivity_for_device.send(crate::connectivity::Request::BluetoothDeviceAction {
            address: address.to_string(),
            action: action.to_string(),
        });
    });
    let weak_for_status_date = window.as_weak();
    window.on_refresh_status_date(move || {
        if let Some(window) = weak_for_status_date.upgrade() {
            update_system_clock(&window);
        }
    });
    update_system_clock(&window);
    update_battery_status(&window);
    let weak_for_cursor = window.as_weak();
    window.window().on_winit_window_event(move |slint_window, event| {
        match event {
            NativeWindowEvent::CursorMoved { .. }
            | NativeWindowEvent::MouseInput { .. }
            | NativeWindowEvent::MouseWheel { .. } => {
                let _ = slint_window.with_winit_window(|native_window| {
                    native_window.set_cursor_visible(true)
                });
                if let Some(window) = weak_for_cursor.upgrade() {
                    window.set_controller_input_active(false);
                }
            }
            NativeWindowEvent::CursorLeft { .. } => {
                let _ = slint_window.with_winit_window(|native_window| {
                    native_window.set_cursor_visible(true)
                });
            }
            NativeWindowEvent::Focused(focused) if !*focused => {
                let _ = slint_window.with_winit_window(|native_window| {
                    native_window.set_cursor_visible(true)
                });
            }
            _ => (),
        }
        EventResult::Propagate
    });
    let home = std::env::var_os("HOME")
        .map(PathBuf::from)
        .filter(|path| path.is_dir())
        .unwrap_or_else(|| PathBuf::from("/"));
    let pictures = xdg_user_dir(&home, "XDG_PICTURES_DIR", "Pictures").unwrap_or_default();
    let downloads = xdg_user_dir(&home, "XDG_DOWNLOAD_DIR", "Downloads").unwrap_or_default();
    let artwork_start = if pictures.as_os_str().is_empty() {
        home.clone()
    } else {
        pictures.clone()
    };
    window.set_artwork_home(home.to_string_lossy().into_owned().into());
    window.set_artwork_pictures(pictures.to_string_lossy().into_owned().into());
    window.set_artwork_downloads(downloads.to_string_lossy().into_owned().into());
    window.set_artwork_folder(artwork_start.to_string_lossy().into_owned().into());
    window.set_system_language(language_code("system").into());
    window.set_language(
        setting_choice(&settings, "language", "system", &["system", "es", "en"]).into(),
    );
    window.set_date_format(
        setting_choice(&settings, "date_format", "dmy", &["dmy", "mdy", "ymd"]).into(),
    );
    window.set_update_install_supported(crate::updates::appimage_path().is_some());
    window.set_check_updates_on_start(
        settings
            .get("check_updates_on_start")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    );
    window.set_steamgriddb_key(
        settings
            .get("steamgriddb_key")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .into(),
    );
    window.set_igdb_client_id(
        settings
            .get("igdb_client_id")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .into(),
    );
    window.set_igdb_client_secret(
        settings
            .get("igdb_client_secret")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .into(),
    );
    window.window().set_fullscreen(
        settings
            .get("start_fullscreen")
            .and_then(Value::as_bool)
            .unwrap_or(true),
    );
    let color_theme = match settings.get("ui_theme").and_then(Value::as_str) {
        Some("combination-176") => "combination-176",
        Some("combination-143") => "combination-143",
        _ => "default",
    };
    window.set_color_theme(color_theme.into());
    let pastel = settings.get("ui_color_mode").and_then(Value::as_str) != Some("system");
    window.global::<Theme>().set_pastel(pastel);
    window.set_pastel_theme(pastel);
    let categories = library.categories(&games);
    let activities = games
        .iter()
        .map(|game| {
            (
                game.id().to_owned(),
                (
                    library.activity_summary(game),
                    library.activity_history_summary(game),
                ),
            )
        })
        .collect::<HashMap<_, _>>();
    let all_games = Rc::new(RefCell::new(games.clone()));
    let all_categories = Rc::new(RefCell::new(categories.clone()));
    let all_activities = Rc::new(RefCell::new(activities.clone()));
    set_categories(&window, &library, &categories);
    let filters = Rc::new(RefCell::new((
        restore
            .as_ref()
            .and_then(|state| state.get("query"))
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned(),
        restore
            .as_ref()
            .and_then(|state| state.get("category"))
            .and_then(Value::as_str)
            .filter(|category| categories.iter().any(|value| value == category))
            .map(str::to_owned)
            .unwrap_or_else(|| library.primary_category().unwrap_or_default().to_owned()),
    )));
    let filtered_games = Rc::new(RefCell::new(games.clone()));
    set_filtered_games(
        &window,
        &games,
        &categories,
        &activities,
        &filters,
        &filtered_games,
    );
    if let Some(selected_id) = restore
        .as_ref()
        .and_then(|state| state.get("selected"))
        .and_then(Value::as_str)
        && let Some(index) = filtered_games
            .borrow()
            .iter()
            .position(|game| game.id() == selected_id)
    {
        window.set_selected_index(index as i32);
    }
    window.set_list_side(
        setting_choice(
            &settings,
            "list_side",
            "bottom",
            &["left", "right", "top", "bottom"],
        )
        .into(),
    );
    window.set_library_layout(
        normalize_slint_layout(string_setting(&settings, "layout", "list")).into(),
    );
    window.set_grid_zoom(setting_number(&settings, "grid_zoom", 100, 50, 200));
    window.set_grid_page_size(setting_number(&settings, "grid_page_size", 10, 1, 100));
    window.set_grid_minimal(nested_bool(&settings, "minimal_views", "grid", false));
    window.set_grid_dim(nested_number(&settings, "background_dim", "grid", 50, 0, 100));
    window.set_grid_blur(nested_number(&settings, "background_blur", "grid", 0, 0, 40));
    window.set_grid_hero_position(nested_choice(&settings, "hero_positions", "grid", "full", &["full", "top", "lower"]).into());
    window.set_grid_background_split(nested_choice(&settings, "background_splits", "grid", "single", &["single", "horizontal", "vertical", "diagonal"]).into());
    window.set_grid_cover_format(nested_choice(&settings, "cover_formats", "grid", "portrait", &["portrait", "square"]).into());
    window.set_grid_cover_radius(nested_number(&settings, "cover_radii", "grid", 12, 0, 40));
    window.set_grid_launcher_details(nested_bool(&settings, "show_launcher_details", "grid", true));
    let grid_ring = settings.get("selection_rings").and_then(|rings| rings.get("grid"));
    window.set_grid_ring_enabled(grid_ring.and_then(|ring| ring.get("focus_ring_enabled")).and_then(Value::as_bool).unwrap_or(true));
    let grid_ring_color = grid_ring.and_then(|ring| ring.get("focus_ring_color")).and_then(Value::as_str).filter(|value| valid_color(value)).unwrap_or("#ffffff");
    window.set_grid_ring_color_text(grid_ring_color.into());
    window.set_grid_ring_color(parse_color(grid_ring_color));
    window.set_grid_ring_width(nested_ring_number(grid_ring, "focus_ring_width", 3, 0, 12));
    window.set_grid_ring_radius(nested_ring_number(grid_ring, "focus_ring_radius", 18, 0, 50));
    let list_artwork = match settings.get("list_artwork").and_then(Value::as_str) {
        Some("portrait") => "portrait",
        Some("square") => "square",
        Some("cover") => nested_choice(
            &settings,
            "cover_formats",
            "list",
            "portrait",
            &["portrait", "square", "logo"],
        ),
        _ => "logo",
    };
    window.set_list_artwork(list_artwork.into());
    window.set_list_artwork_radius(setting_number(&settings, "list_artwork_radius", 12, 0, 40));
    window.set_focus_zoom(setting_number(&settings, "list_focus_zoom", 150, 100, 250));
    window.set_cover_zoom(setting_number(&settings, "list_cover_zoom", 100, 50, 175));
    window.set_hero_position(
        nested_choice(
            &settings,
            "hero_positions",
            "list",
            "full",
            &["full", "top", "lower"],
        )
        .into(),
    );
    window.set_background_split(
        nested_choice(
            &settings,
            "background_splits",
            "list",
            "single",
            &["single", "horizontal", "vertical", "diagonal"],
        )
        .into(),
    );
    window.set_background_source(
        setting_choice(&settings, "background_source", "game", &["game", "global"]).into(),
    );
    window.set_global_background(
        settings
            .get("global_background")
            .and_then(Value::as_str)
            .unwrap_or("bundled:6.png")
            .into(),
    );
    window.set_background_fill(
        setting_choice(&settings, "background_fill", "blur", &["blur", "dominant"]).into(),
    );
    let background_config = Rc::new(RefCell::new((
        window.get_background_split().to_string(),
        window.get_blur(),
    )));
    let background_generation = Arc::new(AtomicU64::new(0));
    let background_pending = Arc::new(Mutex::new(None::<BackgroundRequest>));
    let (wake_worker, wakeups) = mpsc::sync_channel(1);
    let worker_generation = background_generation.clone();
    let worker_pending = background_pending.clone();
    let worker_window = window.as_weak();
    thread::spawn(move || {
        while wakeups.recv().is_ok() {
            let Some(request) = worker_pending.lock().unwrap().take() else {
                continue;
            };
            if !background_request_is_current(&worker_generation, request.generation) {
                continue;
            }
            let pixels = background_pixels(
                &request.game,
                &request.split,
                request.blur,
                &request.position,
                request.size,
                request.global,
                request.fill_mode,
                request.fallback_color,
            );
            if !background_request_is_current(&worker_generation, request.generation) {
                continue;
            }
            let generation = worker_generation.clone();
            let window = worker_window.clone();
            let request_generation = request.generation;
            let _ = slint::invoke_from_event_loop(move || {
                if background_request_is_current(&generation, request_generation)
                    && let Some(window) = window.upgrade()
                {
                    let image = pixels
                        .map(|pixels| {
                            Image::from_rgba8(SharedPixelBuffer::clone_from_slice(
                                pixels.as_raw(),
                                pixels.width(),
                                pixels.height(),
                            ))
                        })
                        .unwrap_or_default();
                    window.set_selected_background_image(image);
                }
            });
        }
    });
    let update_generation = background_generation.clone();
    let update_pending = background_pending.clone();
    let update_background = Rc::new(
        move |window: &ListWindow, index: i32, config: &(String, i32), games: &[Game]| {
            let Some(game) = games.get(index.max(0) as usize).cloned() else {
                update_generation.fetch_add(1, Ordering::AcqRel);
                window.set_selected_background_image(Image::default());
                return;
            };
            let generation = update_generation.fetch_add(1, Ordering::AcqRel) + 1;
            let position = if window.get_library_layout().as_str() == "grid" {
                window.get_grid_hero_position()
            } else {
                window.get_hero_position()
            };
            let fallback = window.global::<Theme>().get_window().color();
            let request = BackgroundRequest {
                generation,
                game,
                split: config.0.clone(),
                blur: config.1,
                position: position.to_string(),
                size: background_viewport_size(
                    (
                        window.get_background_width().max(1) as u32,
                        window.get_background_height().max(1) as u32,
                    ),
                    window.window().scale_factor(),
                ),
                global: (window.get_background_source() == "global").then(|| {
                    super::resolve_background_setting(window.get_global_background().as_str())
                }),
                fill_mode: window.get_background_fill().to_string(),
                fallback_color: [fallback.red(), fallback.green(), fallback.blue()],
            };
            *update_pending.lock().unwrap() = Some(request);
            let _ = wake_worker.try_send(());
        },
    );
    window.set_dim(nested_number(
        &settings,
        "background_dim",
        "list",
        78,
        0,
        100,
    ));
    window.set_blur(nested_number(
        &settings,
        "background_blur",
        "list",
        0,
        0,
        40,
    ));
    background_config.borrow_mut().1 = window.get_blur();
    if window.get_library_layout().as_str() == "grid" {
        *background_config.borrow_mut() = (
            window.get_grid_background_split().to_string(),
            window.get_grid_blur(),
        );
    }
    window.set_minimal(
        settings
            .get("minimal_views")
            .and_then(|views| views.get("list"))
            .and_then(Value::as_bool)
            .or_else(|| settings.get("list_minimal").and_then(Value::as_bool))
            .unwrap_or(false),
    );
    window.set_launcher_details(nested_bool(
        &settings,
        "show_launcher_details",
        "list",
        true,
    ));
    window.set_show_game_information(nested_bool(
        &settings,
        "show_game_information",
        "list",
        true,
    ));
    window.set_show_detail_cover(nested_bool(&settings, "show_detail_cover", "list", true));
    window.set_cover_format(
        nested_choice(
            &settings,
            "cover_formats",
            "list",
            "portrait",
            &["portrait", "square", "logo"],
        )
        .into(),
    );
    window.set_cover_radius(nested_number(&settings, "cover_radii", "list", 12, 0, 40));
    let mut ring_values = Map::new();
    for key in [
        "focus_ring_enabled",
        "focus_ring_color",
        "focus_ring_width",
        "focus_ring_radius",
    ] {
        if let Some(value) = settings
            .get("selection_rings")
            .and_then(|rings| rings.get("list"))
            .and_then(|ring| ring.get(key))
            .or_else(|| settings.get(key))
        {
            ring_values.insert(key.into(), value.clone());
        }
    }
    let ring_value = Value::Object(ring_values);
    let ring = Some(&ring_value);
    window.set_ring_enabled(
        ring.and_then(|ring| ring.get("focus_ring_enabled"))
            .and_then(Value::as_bool)
            .unwrap_or(true),
    );
    window.set_ring_color_text(
        ring.and_then(|ring| ring.get("focus_ring_color"))
            .and_then(Value::as_str)
            .unwrap_or("#ffffff")
            .into(),
    );
    window.set_ring_width(nested_ring_number(ring, "focus_ring_width", 3, 0, 12));
    window.set_ring_radius(nested_ring_number(ring, "focus_ring_radius", 18, 0, 50));
    window.set_screensaver_dim(setting_number(&settings, "screensaver_dim", 35, 0, 100));
    window.set_playing_behavior(
        setting_choice(
            &settings,
            "playing_behavior",
            "none",
            &["none", "hide", "screensaver", "tray"],
        )
        .into(),
    );
    window.set_screensaver_enabled(
        settings
            .get("screensaver_enabled")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    );
    window.set_start_steam_on_start(
        settings
            .get("start_steam_on_start")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    );
    window.set_start_fullscreen(
        settings
            .get("start_fullscreen")
            .and_then(Value::as_bool)
            .unwrap_or(true),
    );
    window.set_start_faugus_on_start(
        settings
            .get("start_faugus_on_start")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    );
    window.set_start_heroic_on_start(
        settings
            .get("start_heroic_on_start")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    );
    window.set_close_steam_on_exit(
        settings
            .get("close_steam_on_exit")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    );
    window.set_close_faugus_on_exit(
        settings
            .get("close_faugus_on_exit")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    );
    window.set_close_heroic_on_exit(
        settings
            .get("close_heroic_on_exit")
            .and_then(Value::as_bool)
            .unwrap_or(false),
    );
    window.set_controller_type(
        setting_choice(
            &settings,
            "controller_type",
            "xbox",
            &["xbox", "sony", "nintendo"],
        )
        .into(),
    );
    window.set_onscreen_keyboard(
        setting_choice(
            &settings,
            "onscreen_keyboard",
            "auto",
            &["auto", "system", "cosmic", "kde", "builtin", "disabled"],
        )
        .into(),
    );
    window.set_keyboard_fallback(
        settings
            .get("keyboard_fallback")
            .and_then(Value::as_bool)
            .unwrap_or(true),
    );
    window.set_screensaver_idle_value(setting_number(
        &settings,
        "screensaver_idle_value",
        5,
        1,
        60,
    ));
    window.set_screensaver_idle_unit(
        setting_choice(
            &settings,
            "screensaver_idle_unit",
            "minutes",
            &["seconds", "minutes"],
        )
        .into(),
    );
    window.set_screensaver_slide_value(setting_number(
        &settings,
        "screensaver_slide_value",
        15,
        1,
        60,
    ));
    window.set_screensaver_slide_unit(
        setting_choice(
            &settings,
            "screensaver_slide_unit",
            "seconds",
            &["seconds", "minutes"],
        )
        .into(),
    );
    window.set_screensaver_source(
        setting_choice(
            &settings,
            "screensaver_source",
            "games",
            &["games", "application"],
        )
        .into(),
    );
    window.set_screensaver_background(
        settings
            .get("screensaver_background")
            .and_then(Value::as_str)
            .unwrap_or("bundled:6.png")
            .into(),
    );
    window.set_show_session_history(
        settings
            .get("show_session_history")
            .and_then(Value::as_bool)
            .unwrap_or(true),
    );
    window.set_ring_color(parse_color(
        ring.and_then(|ring| ring.get("focus_ring_color"))
            .and_then(Value::as_str)
            .unwrap_or("#ffffff"),
    ));
    let weak_for_color = window.as_weak();
    window.on_ring_color_changed(move |color| {
        if valid_color(&color) {
            if let Some(window) = weak_for_color.upgrade() {
                window.set_ring_color(parse_color(&color));
            }
        }
    });
    let weak_for_grid_color = window.as_weak();
    window.on_grid_ring_color_changed(move |color| {
        if valid_color(&color) {
            if let Some(window) = weak_for_grid_color.upgrade() {
                window.set_grid_ring_color(parse_color(&color));
            }
        }
    });
    let weak_for_screensaver = window.as_weak();
    let (screensaver_image_generation, screensaver_image_requests) =
        start_screensaver_image_worker(&window);
    let generation_for_dismiss = screensaver_image_generation.clone();
    let requests_for_dismiss = screensaver_image_requests.clone();
    window.on_dismiss_screensaver(move || {
        if let Some(window) = weak_for_screensaver.upgrade() {
            window.set_screensaver_active(false);
            cancel_screensaver_image_request(&generation_for_dismiss, &requests_for_dismiss);
        }
    });
    let last_activity = Rc::new(RefCell::new(Instant::now()));
    let activity_for_ui = last_activity.clone();
    window.on_user_activity(move || *activity_for_ui.borrow_mut() = Instant::now());
    let loaded_image_rows = Rc::new(RefCell::new(std::collections::HashSet::new()));
    let image_rows_for_selection = loaded_image_rows.clone();
    let (row_image_generation, row_image_requests) = start_row_image_worker(&window);
    let generation_for_selection = row_image_generation.clone();
    let requests_for_selection = row_image_requests.clone();
    let visible_for_selection = filtered_games.clone();
    let config_for_selection = background_config.clone();
    let background_for_selection = update_background.clone();
    let weak_for_selection = window.as_weak();
    window.on_selection_changed(move |index| {
        if let Some(window) = weak_for_selection.upgrade() {
            window.set_selected_cover_portrait(Image::default());
            window.set_selected_cover_square(Image::default());
            window.set_selected_cover_logo(Image::default());
            window.set_selected_cover(Image::default());
            update_row_images(
                &window,
                &mut image_rows_for_selection.borrow_mut(),
                &generation_for_selection,
                &requests_for_selection,
            );
            let visible = visible_for_selection.borrow();
            let config = config_for_selection.borrow();
            background_for_selection(&window, index, &config, &visible);
            sync_letter_index(&window, &visible);
        }
    });
    let image_rows_for_layout = loaded_image_rows.clone();
    let generation_for_layout = row_image_generation.clone();
    let requests_for_layout = row_image_requests.clone();
    let weak_for_layout = window.as_weak();
    let layout_background_config = background_config.clone();
    let background_for_layout = update_background.clone();
    let visible_for_layout = filtered_games.clone();
    window.on_library_layout_changed(move || {
        if let Some(window) = weak_for_layout.upgrade() {
            let mut config = layout_background_config.borrow_mut();
            if window.get_library_layout().as_str() == "grid" {
                config.0 = window.get_grid_background_split().to_string();
                config.1 = window.get_grid_blur();
            } else {
                config.0 = window.get_background_split().to_string();
                config.1 = window.get_blur();
            }
            update_row_images(
                &window,
                &mut image_rows_for_layout.borrow_mut(),
                &generation_for_layout,
                &requests_for_layout,
            );
            let visible = visible_for_layout.borrow();
            background_for_layout(&window, window.get_selected_index(), &config, &visible);
        }
    });
    window.invoke_selection_changed(window.get_selected_index());
    let visible_for_config = filtered_games.clone();
    let config_for_change = background_config.clone();
    let background_for_change = update_background.clone();
    let weak_for_config = window.as_weak();
    window.on_background_config_changed(move |split, blur| {
        let mut config = config_for_change.borrow_mut();
        config.0 = split.to_string();
        config.1 = blur;
        if let Some(window) = weak_for_config.upgrade() {
            let visible = visible_for_config.borrow();
            background_for_change(&window, window.get_selected_index(), &config, &visible);
        }
    });
    if let Some(error) = settings_error {
        set_status_error(
            &window,
            "No se pudieron leer los ajustes: ",
            "Could not read settings: ",
            error,
        );
    }

    let settings = Rc::new(RefCell::new(settings));
    let artwork_options = Arc::new(Mutex::new(Vec::<ArtworkOption>::new()));
    let metadata_options = Arc::new(Mutex::new(Vec::<MetadataOption>::new()));
    let active_artwork_cancellation = Rc::new(RefCell::new(None::<Arc<AtomicBool>>));
    let active_for_cancel = active_artwork_cancellation.clone();
    let artwork_for_cancel = artwork_options.clone();
    let metadata_for_cancel = metadata_options.clone();
    window.on_cancel_artwork_search(move || {
        if let Some(cancelled) = active_for_cancel.borrow_mut().take() {
            cancelled.store(true, Ordering::Relaxed);
        }
        *artwork_for_cancel.lock().unwrap() = Vec::new();
        *metadata_for_cancel.lock().unwrap() = Vec::new();
    });
    let settings_for_artwork = settings.clone();
    let weak_for_artwork_search = window.as_weak();
    let options_for_artwork_search = artwork_options.clone();
    let active_for_search = active_artwork_cancellation.clone();
    let weak_for_browser_columns = window.as_weak();
    window.on_artwork_browser_columns_changed(move |columns| {
        if !matches!(columns, 2 | 3) {
            return;
        }
        let Some(window) = weak_for_browser_columns.upgrade() else {
            return;
        };
        if window.get_artwork_browser_columns() == columns {
            return;
        }
        let items = flatten_artwork_browser_rows(&window.get_artwork_browser_rows());
        window.set_artwork_browser_columns(columns);
        window.set_artwork_browser_rows(ModelRc::new(VecModel::from(group_artwork_browser_items(
            items,
            columns as usize,
        ))));
        window.set_artwork_browser_focus_serial(
            window.get_artwork_browser_focus_serial().wrapping_add(1),
        );
    });
    let artwork_browser_history = Rc::new(RefCell::new(HashMap::<String, i32>::new()));
    let weak_for_browse_artwork = window.as_weak();
    let artwork_browser_history_for_browse = artwork_browser_history.clone();
    window.on_browse_artwork_folder(move |folder| {
        let Some(window) = weak_for_browse_artwork.upgrade() else {
            return;
        };
        let path = expand_user_path(folder.trim());
        let path = match path.canonicalize() {
            Ok(path) if path.is_dir() => path,
            Ok(_) => {
                set_status(
                    &window,
                    "La ruta no es una carpeta.",
                    "The path is not a folder.",
                );
                return;
            }
            Err(error) => {
                set_status_error(
                    &window,
                    "No se pudo abrir la carpeta: ",
                    "Could not open folder: ",
                    error,
                );
                return;
            }
        };
        let path_text = path.to_string_lossy().into_owned();
        if window.get_artwork_browsing() {
            let previous = window.get_artwork_folder().to_string();
            let index = window.get_artwork_browser_focus_index();
            if !previous.is_empty() && index >= 0 {
                artwork_browser_history_for_browse
                    .borrow_mut()
                    .insert(previous, index);
            }
        }
        let restored_index = artwork_browser_history_for_browse
            .borrow()
            .get(&path_text)
            .copied()
            .unwrap_or(0);
        window.set_artwork_folder(path_text.clone().into());
        window.set_artwork_parent_folder(
            path.parent()
                .filter(|parent| *parent != path)
                .map(|parent| parent.to_string_lossy().into_owned())
                .unwrap_or_default()
                .into(),
        );
        window.set_artwork_browser_selected_path("".into());
        window.set_artwork_browser_selected_name("".into());
        window.set_artwork_browser_selected_info("".into());
        window.set_artwork_browser_selected_error("".into());
        window.set_artwork_browser_selected_valid(false);
        window.set_artwork_browser_selected_preview(Image::default());
        window.set_artwork_browser_rows(ModelRc::new(VecModel::from(
            Vec::<ArtworkBrowserRow>::new(),
        )));
        window.set_artwork_browser_item_count(0);
        window.set_artwork_browser_focus_index(-1);
        window.set_artwork_browser_focus_serial(
            window.get_artwork_browser_focus_serial().wrapping_add(1),
        );
        window.set_artwork_browser_toolbar_focus_index(-1);
        window.set_artwork_browser_toolbar_focus_serial(
            window
                .get_artwork_browser_toolbar_focus_serial()
                .wrapping_add(1),
        );
        set_status(&window, "Leyendo carpeta…", "Reading folder…");
        let weak = weak_for_browse_artwork.clone();
        thread::spawn(move || {
            let result = load_artwork_browser_items(&path);
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(window) = weak.upgrade() {
                    if !window.get_artwork_browsing()
                        || window.get_artwork_folder().as_str() != path_text
                    {
                        return;
                    }
                    match result {
                        Ok(items) => {
                            let first = if items.is_empty() {
                                -1
                            } else {
                                restored_index.clamp(0, items.len() as i32 - 1)
                            };
                            window.set_artwork_browser_item_count(items.len() as i32);
                            let selected = usize::try_from(first)
                                .ok()
                                .and_then(|index| items.get(index))
                                .filter(|item| !item.directory)
                                .map(|item| (item.path.clone(), item.name.clone()));
                            let items = items
                                .into_iter()
                                .map(|item| ArtworkBrowserItem {
                                    name: item.name.into(),
                                    path: item.path.into(),
                                    directory: item.directory,
                                    preview: Image::default(),
                                    preview_loaded: false,
                                    preview_requested: false,
                                })
                                .collect::<Vec<_>>();
                            let rows = group_artwork_browser_items(
                                items,
                                window.get_artwork_browser_columns() as usize,
                            );
                            window.set_artwork_browser_rows(ModelRc::new(VecModel::from(rows)));
                            window.set_artwork_browser_focus_index(first);
                            window.set_artwork_browser_focus_serial(
                                window.get_artwork_browser_focus_serial().wrapping_add(1),
                            );
                            if let Some((path, name)) = selected {
                                window.set_artwork_browser_selected_path(path.clone().into());
                                window.set_artwork_browser_selected_name(name.into());
                                window.invoke_request_artwork_detail(path.into());
                            }
                            set_status(&window, "", "");
                        }
                        Err(error) => set_status_error(
                            &window,
                            "No se pudo leer la carpeta: ",
                            "Could not read folder: ",
                            error,
                        ),
                    }
                }
            });
        });
    });
    let weak_for_artwork_preview = window.as_weak();
    window.on_request_artwork_preview(move |index, path| {
        let Some(window) = weak_for_artwork_preview.upgrade() else {
            return;
        };
        let index = index as usize;
        let columns = window.get_artwork_browser_columns().max(1) as usize;
        let rows = window.get_artwork_browser_rows();
        let row_index = index / columns;
        let column_index = index % columns;
        let Some(row) = rows.row_data(row_index) else {
            return;
        };
        let Some(mut item) = row.items.row_data(column_index) else {
            return;
        };
        if item.path != path || item.directory || item.preview_requested || item.preview_loaded {
            return;
        }
        item.preview_requested = true;
        row.items.set_row_data(column_index, item);
        rows.set_row_data(row_index, row);
        let folder = window.get_artwork_folder().to_string();
        let path_text = path.to_string();
        let path = PathBuf::from(path.as_str());
        let weak = weak_for_artwork_preview.clone();
        thread::spawn(move || {
            let preview = decode_image(&path).ok().map(|image| {
                let image = image.thumbnail(200, 130).into_rgba8();
                let (width, height) = image.dimensions();
                (image.into_raw(), width, height)
            });
            let _ = slint::invoke_from_event_loop(move || {
                let Some(window) = weak.upgrade() else {
                    return;
                };
                if !window.get_artwork_browsing() || window.get_artwork_folder().as_str() != folder
                {
                    return;
                }
                let columns = window.get_artwork_browser_columns().max(1) as usize;
                let rows = window.get_artwork_browser_rows();
                let row_index = index / columns;
                let column_index = index % columns;
                let Some(row) = rows.row_data(row_index) else {
                    return;
                };
                let Some(mut item) = row.items.row_data(column_index) else {
                    return;
                };
                if item.path != path_text {
                    return;
                }
                item.preview_requested = false;
                if let Some((pixels, width, height)) = preview {
                    item.preview = Image::from_rgba8(
                        slint::SharedPixelBuffer::<slint::Rgba8Pixel>::clone_from_slice(
                            &pixels, width, height,
                        ),
                    );
                    item.preview_loaded = true;
                }
                row.items.set_row_data(column_index, item);
                rows.set_row_data(row_index, row);
            });
        });
    });
    let weak_for_editor_image_preview = window.as_weak();
    window.on_request_editor_image_preview(move |field, path| {
        let Some(window) = weak_for_editor_image_preview.upgrade() else {
            return;
        };
        let field = field.to_string();
        let path_text = path.to_string();
        if path_text.is_empty() {
            match field.as_str() {
                "cover" => window.set_edit_cover_preview(Image::default()),
                "banner" => window.set_edit_banner_preview(Image::default()),
                "banner_secondary" => window.set_edit_secondary_preview(Image::default()),
                _ => {}
            }
            return;
        }
        let path = PathBuf::from(&path_text);
        let weak = weak_for_editor_image_preview.clone();
        thread::spawn(move || {
            let (width, height) = if field == "cover" {
                (480, 720)
            } else {
                (560, 315)
            };
            let preview = decode_image(&path).ok().map(|decoded| {
                let pixels = decoded.thumbnail(width, height).into_rgba8();
                let (width, height) = pixels.dimensions();
                (pixels.into_raw(), width, height)
            });
            let _ = slint::invoke_from_event_loop(move || {
                let Some(window) = weak.upgrade() else {
                    return;
                };
                let current_path = match field.as_str() {
                    "cover" => {
                        let cover = window.get_edit_cover();
                        if cover.is_empty() {
                            window.get_edit_square_cover()
                        } else {
                            cover
                        }
                    }
                    "banner" => window.get_edit_banner(),
                    "banner_secondary" => window.get_edit_secondary_background(),
                    _ => return,
                };
                if current_path.as_str() != path_text {
                    return;
                }
                let image = preview
                    .map(|(pixels, width, height)| {
                        Image::from_rgba8(
                            slint::SharedPixelBuffer::<slint::Rgba8Pixel>::clone_from_slice(
                                &pixels, width, height,
                            ),
                        )
                    })
                    .unwrap_or_default();
                match field.as_str() {
                    "cover" => window.set_edit_cover_preview(image),
                    "banner" => window.set_edit_banner_preview(image),
                    "banner_secondary" => window.set_edit_secondary_preview(image),
                    _ => {}
                }
            });
        });
    });
    let weak_for_artwork_detail = window.as_weak();
    window.on_request_artwork_detail(move |path| {
        let Some(window) = weak_for_artwork_detail.upgrade() else {
            return;
        };
        if window.get_artwork_browser_selected_path() != path {
            return;
        }
        window.set_artwork_browser_selected_info("".into());
        window.set_artwork_browser_selected_error("".into());
        window.set_artwork_browser_selected_valid(false);
        window.set_artwork_browser_selected_preview(Image::default());
        let folder = window.get_artwork_folder().to_string();
        let english = window.get_english_ui();
        let path_text = path.to_string();
        let path = PathBuf::from(path.as_str());
        let weak = weak_for_artwork_detail.clone();
        thread::spawn(move || {
            let (preview, info, error) = match decode_image(&path) {
                Ok(decoded) => {
                    let bytes = std::fs::metadata(&path)
                        .map(|metadata| metadata.len())
                        .unwrap_or(0);
                    let info = format!(
                        "{} × {} px\n{:.1} KiB",
                        decoded.width(),
                        decoded.height(),
                        bytes as f64 / 1024.0
                    );
                    let image = decoded.thumbnail(560, 440).into_rgba8();
                    let (width, height) = image.dimensions();
                    (Some((image.into_raw(), width, height)), info, String::new())
                }
                Err(_) => (
                    None,
                    String::new(),
                    if english {
                        "No preview available for this image.".to_owned()
                    } else {
                        "No hay vista previa para esta imagen.".to_owned()
                    },
                ),
            };
            let _ = slint::invoke_from_event_loop(move || {
                let Some(window) = weak.upgrade() else {
                    return;
                };
                let valid = preview.is_some();
                if window.get_artwork_browsing()
                    && window.get_artwork_folder().as_str() == folder
                    && window.get_artwork_browser_selected_path() == path_text
                {
                    window.set_artwork_browser_selected_preview(
                        preview
                            .map(|(pixels, width, height)| {
                                Image::from_rgba8(
                                    slint::SharedPixelBuffer::<slint::Rgba8Pixel>::clone_from_slice(
                                        &pixels, width, height,
                                    ),
                                )
                            })
                            .unwrap_or_default(),
                    );
                    window.set_artwork_browser_selected_info(info.into());
                    window.set_artwork_browser_selected_error(error.into());
                    window.set_artwork_browser_selected_valid(valid);
                }
            });
        });
    });
    let artwork_cache_for_import = library.artwork_cache_dir();
    let weak_for_import_artwork = window.as_weak();
    let active_for_import_artwork = active_artwork_cancellation.clone();
    window.on_import_artwork(move || {
        let Some(window) = weak_for_import_artwork.upgrade() else {
            return;
        };
        if window.get_picking_category_icon() {
            window.set_icon_path(window.get_artwork_browser_selected_path());
            window.invoke_close_artwork_browser();
            return;
        }
        if window.get_artwork_importing() {
            return;
        }
        let Some(request) = ArtworkRequest::start(&window) else {
            return;
        };
        let location = window.get_artwork_location().trim().to_owned();
        if location.is_empty() {
            return;
        }
        let field = request.field.clone();
        let path = expand_user_path(&location);
        let is_url = location.starts_with("http://") || location.starts_with("https://");
        let cache = artwork_cache_for_import.clone();
        let identity = format!("{}-{field}-{location}", request.game);
        let weak = weak_for_import_artwork.clone();
        let cancelled = Arc::new(AtomicBool::new(false));
        if let Some(previous) = active_for_import_artwork
            .borrow_mut()
            .replace(cancelled.clone())
        {
            previous.store(true, Ordering::Relaxed);
        }
        let cancelled_for_worker = cancelled.clone();
        window.set_artwork_importing(true);
        set_status(&window, "Importando imagen…", "Importing image…");
        thread::spawn(move || {
            let result = if is_url {
                crate::artwork::download_custom(
                    &location,
                    &cache,
                    &identity,
                    Some(&cancelled_for_worker),
                )
            } else {
                crate::artwork::import_local(&path, &cache)
            };
            let cancelled_for_event = cancelled_for_worker.clone();
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(window) = weak.upgrade() {
                    if window.get_artwork_request_serial() == request.serial {
                        window.set_artwork_importing(false);
                    }
                    if cancelled_for_event.load(Ordering::Relaxed) || !request.matches(&window) {
                        return;
                    }
                    match result {
                        Ok(path) => {
                            set_artwork_path(&window, &field, &path);
                            window.set_artwork_location("".into());
                            window.set_showing_artwork(false);
                            window.set_showing_editor(true);
                            window.set_save_message("".into());
                        }
                        Err(error) => set_status_error(
                            &window,
                            "No se pudo importar la imagen: ",
                            "Could not import image: ",
                            error,
                        ),
                    }
                }
            });
        });
    });
    let weak_for_clear_artwork = window.as_weak();
    window.on_clear_artwork(move |field| {
        let Some(window) = weak_for_clear_artwork.upgrade() else {
            return;
        };
        if window.get_artwork_importing()
            || window.get_edit_id().is_empty()
            || !matches!(
                field.as_str(),
                "cover" | "square_cover" | "logo" | "banner" | "banner_secondary"
            )
        {
            return;
        }
        set_artwork_path(&window, &field, "");
        window.set_showing_artwork(false);
        window.set_showing_editor(true);
        window.set_save_message("".into());
    });
    let weak_for_swap_edit_backgrounds = window.as_weak();
    window.on_swap_edit_backgrounds(move || {
        let Some(window) = weak_for_swap_edit_backgrounds.upgrade() else {
            return;
        };
        if window.get_artwork_importing()
            || window.get_edit_id().is_empty()
            || window.get_edit_banner().is_empty()
            || window.get_edit_secondary_background().is_empty()
        {
            return;
        }
        let banner = window.get_edit_banner();
        let secondary = window.get_edit_secondary_background();
        window.set_edit_banner(secondary);
        window.set_edit_secondary_background(banner);
        window.set_showing_artwork(false);
        window.set_showing_editor(true);
        window.set_save_message("".into());
    });
    window.on_search_artwork(move |provider, query, field| {
        let Some(window) = weak_for_artwork_search.upgrade() else {
            return;
        };
        let Some(request) = ArtworkRequest::start(&window) else {
            return;
        };
        if let Some(previous) = active_for_search.borrow_mut().take() {
            previous.store(true, Ordering::Relaxed);
        }
        let cancelled = Arc::new(AtomicBool::new(false));
        *active_for_search.borrow_mut() = Some(cancelled.clone());
        let settings = settings_for_artwork.borrow().clone();
        let game_id = window.get_artwork_game_id().to_string();
        let weak = weak_for_artwork_search.clone();
        let options = options_for_artwork_search.clone();
        if let Some(window) = weak.upgrade() {
            set_status(&window, "Buscando imágenes…", "Searching for artwork…");
            window.set_artwork_results(ModelRc::new(VecModel::from(Vec::<ArtworkRow>::new())));
        }
        let cancelled_for_worker = cancelled.clone();
        thread::spawn(move || {
            let result = match provider.as_str() {
                "steam" => crate::artwork::search_steam(&query, Some(&cancelled_for_worker)),
                "steamgriddb" => {
                    if !game_id.is_empty() {
                        crate::artwork::search_for_game(
                            settings
                                .get("steamgriddb_key")
                                .and_then(Value::as_str)
                                .unwrap_or_default(),
                            &game_id,
                            &field,
                            Some(&cancelled_for_worker),
                        )
                    } else {
                        crate::artwork::search_games(
                            settings
                                .get("steamgriddb_key")
                                .and_then(Value::as_str)
                                .unwrap_or_default(),
                            &query,
                            Some(&cancelled_for_worker),
                        )
                    }
                }
                "igdb" => crate::artwork::search_igdb(
                    settings
                        .get("igdb_client_id")
                        .and_then(Value::as_str)
                        .unwrap_or_default(),
                    settings
                        .get("igdb_client_secret")
                        .and_then(Value::as_str)
                        .unwrap_or_default(),
                    &query,
                    Some(&cancelled_for_worker),
                ),
                _ => crate::artwork::search(
                    settings
                        .get("steamgriddb_key")
                        .and_then(Value::as_str)
                        .unwrap_or_default(),
                    &query,
                    &field,
                    Some(&cancelled_for_worker),
                ),
            };
            let cancelled_for_event = cancelled_for_worker.clone();
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(window) = weak.upgrade() {
                    if cancelled_for_event.load(Ordering::Relaxed) || !request.matches(&window) {
                        cancelled_for_event.store(true, Ordering::Relaxed);
                        return;
                    }
                    match result {
                        Ok(found) => {
                            let has_game_choices = found
                                .first()
                                .is_some_and(|option| option.provider == "steamgriddb-game");
                            let has_results = !found.is_empty();
                            let rows = found
                                .iter()
                                .map(|option| ArtworkRow {
                                    name: option.name.clone().into(),
                                    preview: Image::default(),
                                    game_choice: option.provider == "steamgriddb-game",
                                })
                                .collect::<Vec<_>>();
                            if found
                                .first()
                                .is_none_or(|option| option.provider != "steamgriddb-game")
                            {
                                load_previews(
                                    window.as_weak(),
                                    request.clone(),
                                    found.clone(),
                                    cancelled_for_event.clone(),
                                );
                            }
                            *options.lock().unwrap() = found;
                            window.set_artwork_results(ModelRc::new(VecModel::from(rows)));
                            window.set_artwork_results_focus_index(if has_results {
                                0
                            } else {
                                -1
                            });
                            window.set_artwork_results_focus_serial(
                                window.get_artwork_results_focus_serial().wrapping_add(1),
                            );
                            if !has_results {
                                set_status(
                                    &window,
                                    "No se encontraron resultados.",
                                    "No results found.",
                                );
                            } else if has_game_choices {
                                set_status(
                                    &window,
                                    "Selecciona un juego para buscar sus imágenes.",
                                    "Select a game to find its artwork.",
                                );
                            } else {
                                set_status(
                                    &window,
                                    "Selecciona una imagen para cargarla en el editor.",
                                    "Select an image to load into the editor.",
                                );
                            }
                        }
                        Err(error) => {
                            *options.lock().unwrap() = Vec::new();
                            window.set_save_message(localize_provider_error(&window, error).into());
                        }
                    }
                }
            });
        });
    });
    let options_for_choose = artwork_options.clone();
    let active_for_choose = active_artwork_cancellation.clone();
    let weak_for_choose = window.as_weak();
    let weak_for_choose_field = window.as_weak();
    let artwork_cache = library.artwork_cache_dir();
    window.on_choose_artwork(move |index| {
        let Some(window) = weak_for_choose.upgrade() else {
            return;
        };
        if index < 0 || index as usize >= window.get_artwork_results().row_count() {
            return;
        }
        if let Some(cancelled) = active_for_choose.borrow_mut().take() {
            cancelled.store(true, Ordering::Relaxed);
        }
        let Some(request) = ArtworkRequest::start(&window) else {
            return;
        };
        let Some(option) = options_for_choose
            .lock()
            .unwrap()
            .get(index.max(0) as usize)
            .cloned()
        else {
            return;
        };
        let field = weak_for_choose_field
            .upgrade()
            .map(|window| window.get_artwork_field().to_string())
            .unwrap_or_default();
        if option.provider == "steamgriddb-game" {
            window.set_artwork_game_id(option.game_id.into());
            window.invoke_search_artwork(
                "steamgriddb".into(),
                window.get_artwork_query(),
                field.into(),
            );
            return;
        }
        let cancelled = Arc::new(AtomicBool::new(false));
        *active_for_choose.borrow_mut() = Some(cancelled.clone());
        let cancelled_for_worker = cancelled.clone();
        let weak = weak_for_choose.clone();
        let root = artwork_cache.clone();
        thread::spawn(move || {
            let result = crate::artwork::download(&option, &root, Some(&cancelled_for_worker));
            let cancelled_for_event = cancelled_for_worker.clone();
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(window) = weak.upgrade() {
                    if cancelled_for_event.load(Ordering::Relaxed) || !request.matches(&window) {
                        cancelled_for_event.store(true, Ordering::Relaxed);
                        return;
                    }
                    match result {
                        Ok(path) => {
                            set_artwork_path(&window, &field, &path);
                            window.set_showing_artwork(false);
                            window.set_showing_editor(true);
                            window.set_save_message("".into());
                        }
                        Err(error) => {
                            window.set_save_message(localize_provider_error(&window, error).into())
                        }
                    }
                }
            });
        });
    });
    let metadata_options_for_search = metadata_options.clone();
    let weak_for_metadata_search = window.as_weak();
    window.on_search_metadata(move |provider, query| {
        let Some(window) = weak_for_metadata_search.upgrade() else {
            return;
        };
        let Some(request) = ArtworkRequest::start(&window) else {
            return;
        };
        let weak = weak_for_metadata_search.clone();
        let options = metadata_options_for_search.clone();
        let language = language_code(window.get_language().as_str()).to_owned();
        if let Some(window) = weak.upgrade() {
            set_status(&window, "Buscando ficha…", "Searching for metadata…");
            window.set_artwork_results(ModelRc::new(VecModel::from(Vec::<ArtworkRow>::new())));
        }
        thread::spawn(move || {
            let result = if provider == "steam-metadata" {
                crate::metadata::steam_search(&query)
            } else {
                crate::metadata::wikidata_search(&query, &language)
            };
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(window) = weak.upgrade() {
                    if !request.matches(&window) {
                        return;
                    }
                    match result {
                        Ok(found) => {
                            let rows = found
                                .iter()
                                .map(|option| ArtworkRow {
                                    name: format!("{} · {}", option.name, option.description)
                                        .into(),
                                    preview: Image::default(),
                                    game_choice: false,
                                })
                                .collect::<Vec<_>>();
                            *options.lock().unwrap() = found;
                            window.set_artwork_results(ModelRc::new(VecModel::from(rows)));
                            set_status(
                                &window,
                                "Selecciona una ficha para cargarla en el editor.",
                                "Select a metadata result to load into the editor.",
                            );
                        }
                        Err(error) => {
                            *options.lock().unwrap() = Vec::new();
                            window.set_save_message(localize_provider_error(&window, error).into());
                        }
                    }
                }
            });
        });
    });
    let metadata_options_for_choose = metadata_options.clone();
    let weak_for_metadata_choose = window.as_weak();
    let metadata_cache = library.metadata_cache_dir();
    window.on_choose_metadata(move |index| {
        let Some(window) = weak_for_metadata_choose.upgrade() else {
            return;
        };
        if index < 0 || index as usize >= window.get_artwork_results().row_count() {
            return;
        }
        let Some(request) = ArtworkRequest::start(&window) else {
            return;
        };
        let Some(option) = metadata_options_for_choose
            .lock()
            .unwrap()
            .get(index.max(0) as usize)
            .cloned()
        else {
            return;
        };
        let provider = weak_for_metadata_choose
            .upgrade()
            .map(|window| window.get_artwork_provider().to_string())
            .unwrap_or_default();
        let language = language_code(window.get_language().as_str()).to_owned();
        let weak = weak_for_metadata_choose.clone();
        let cache = metadata_cache.clone();
        thread::spawn(move || {
            let result = if provider == "steam-metadata" {
                crate::metadata::steam(&option.id)
            } else {
                crate::metadata::wikidata_fetch(&option.id, &language, &cache)
            };
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(window) = weak.upgrade() {
                    if !request.matches(&window) {
                        return;
                    }
                    match result {
                        Ok(metadata) => {
                            if let Some(value) = metadata.get("title").and_then(Value::as_str) {
                                window.set_edit_title(value.into());
                            }
                            if let Some(value) = metadata.get("description").and_then(Value::as_str)
                            {
                                window.set_edit_description(value.into());
                                window.set_edit_synopsis(
                                    metadata
                                        .get("synopsis")
                                        .and_then(Value::as_str)
                                        .unwrap_or(value)
                                        .into(),
                                );
                            }
                            for key in [
                                "release_date",
                                "developers",
                                "publishers",
                                "genres",
                                "platforms",
                            ] {
                                let value = metadata_text(&metadata, key).into();
                                match key {
                                    "release_date" => window.set_edit_release_date(value),
                                    "developers" => window.set_edit_developers(value),
                                    "publishers" => window.set_edit_publishers(value),
                                    "genres" => window.set_edit_genres(value),
                                    _ => window.set_edit_platforms(value),
                                }
                            }
                            window.set_edit_metadata_source(
                                metadata_text(&metadata, "source").into(),
                            );
                            window.set_edit_entity_id(metadata_text(&metadata, "entity_id").into());
                            window.set_edit_steam_appid(
                                metadata_text(&metadata, "steam_appid").into(),
                            );
                            window.set_showing_artwork(false);
                            window.set_showing_editor(true);
                            window.set_save_message("".into());
                        }
                        Err(error) => {
                            window.set_save_message(localize_provider_error(&window, error).into())
                        }
                    }
                }
            });
        });
    });
    let settings_for_save = settings.clone();
    let ui_settings_for_save = Rc::new(RefCell::new(ui_settings_snapshot(&window)));
    let ui_settings_for_save_callback = ui_settings_for_save.clone();
    let saver_paths_for_save = saver_paths.clone();
    let games_for_save = all_games.clone();
    let root = library.data_dir().to_path_buf();
    let category_draft = Rc::new(RefCell::new(None::<CategoryDraftDirectory>));
    let category_draft_operations = Rc::new(RefCell::new(Vec::<CategoryDraftOperation>::new()));
    let category_filter_before_draft = Rc::new(RefCell::new(None::<String>));
    let category_edit_before_draft = Rc::new(RefCell::new(None::<String>));
    let category_icon_request_generation = Rc::new(std::cell::Cell::new(0_u64));
    let weak_window = window.as_weak();
    let games_for_search = all_games.clone();
    let categories_for_search = all_categories.clone();
    let activities_for_search = all_activities.clone();
    let filters_for_search = filters.clone();
    let visible_for_search = filtered_games.clone();
    let weak_for_search = window.as_weak();
    window.on_search_changed(move |query| {
        filters_for_search.borrow_mut().0 = query.to_string();
        if let Some(window) = weak_for_search.upgrade() {
            set_filtered_games(
                &window,
                &games_for_search.borrow(),
                &categories_for_search.borrow(),
                &activities_for_search.borrow(),
                &filters_for_search,
                &visible_for_search,
            );
        }
    });
    let weak_for_erase = window.as_weak();
    window.on_erase_last_character(move || {
        if let Some(window) = weak_for_erase.upgrade() {
            send_key(&window, slint::platform::Key::Backspace, false);
        }
    });
    let weak = window.as_weak();
    window.on_move_text_cursor(move |right| {
        if let Some(window) = weak.upgrade() {
            send_key(
                &window,
                if right {
                    slint::platform::Key::RightArrow
                } else {
                    slint::platform::Key::LeftArrow
                },
                false,
            );
        }
    });
    let weak_for_type = window.as_weak();
    window.on_type_key(move |key| {
        if let Some(window) = weak_for_type.upgrade() {
            let text: slint::SharedString = key;
            window
                .window()
                .dispatch_event(slint::platform::WindowEvent::KeyPressed { text: text.clone() });
            window
                .window()
                .dispatch_event(slint::platform::WindowEvent::KeyReleased { text });
        }
    });
    let games_for_category = all_games.clone();
    let categories_for_category = all_categories.clone();
    let activities_for_category = all_activities.clone();
    let filters_for_category = filters.clone();
    let visible_for_category = filtered_games.clone();
    let weak_for_category = window.as_weak();
    window.on_category_changed(move |category| {
        if let Some(window) = weak_for_category.upgrade() {
            let index = categories_for_category
                .borrow()
                .iter()
                .position(|value| value.as_str() == category.as_str())
                .map_or(0, |index| index as i32 + 1);
            window.set_category_index(index);
        }
        filters_for_category.borrow_mut().1 = if category == "Todos" {
            String::new()
        } else {
            categories_for_category
                .borrow()
                .iter()
                .find(|value| value.as_str() == category.as_str())
                .cloned()
                .unwrap_or_default()
        };
        if let Some(window) = weak_for_category.upgrade() {
            set_filtered_games(
                &window,
                &games_for_category.borrow(),
                &categories_for_category.borrow(),
                &activities_for_category.borrow(),
                &filters_for_category,
                &visible_for_category,
            );
        }
    });
    let visible_for_letter = filtered_games.clone();
    let weak_for_letter = window.as_weak();
    window.on_letter_changed(move |letter| {
        let index = visible_for_letter
            .borrow()
            .iter()
            .position(|game| super::title_initial(game.title()).to_string() == letter.as_str());
        if let (Some(window), Some(index)) = (weak_for_letter.upgrade(), index) {
            window.set_selected_index(index as i32);
        }
    });
    let weak = window.as_weak();
    let member_games = all_games.clone();
    window.on_refresh_members(move || {
        let Some(window) = weak.upgrade() else {
            return;
        };
        if !window.get_showing_settings() || window.get_settings_section() != 2 {
            return;
        }
        let category = window.get_managed_category();
        let query = super::normalize_search(window.get_member_query().trim());
        let rows = member_games
            .borrow()
            .iter()
            .filter(|game| {
                !category.is_empty()
                    && (query.is_empty() || super::normalize_search(game.title()).contains(&query))
            })
            .map(|game| CategoryMember {
                id: game.id().into(),
                title: game.title().into(),
                checked: game
                    .categories()
                    .iter()
                    .any(|name| name == category.as_str()),
            })
            .collect::<Vec<_>>();
        window.set_category_members(ModelRc::new(VecModel::from(rows)));
    });
    let games_for_category_manager = all_games.clone();
    let categories_for_category_manager = all_categories.clone();
    let activities_for_category_manager = all_activities.clone();
    let visible_for_category_manager = filtered_games.clone();
    let filters_for_category_manager = filters.clone();
    let games_for_category_save = all_games.clone();
    let categories_for_category_save = all_categories.clone();
    let activities_for_category_save = all_activities.clone();
    let visible_for_category_save = filtered_games.clone();
    let filters_for_category_save = filters.clone();
    let category_root = root.clone();
    let category_draft_for_manager = category_draft.clone();
    let category_operations_for_manager = category_draft_operations.clone();
    let category_filter_before_manager = category_filter_before_draft.clone();
    let category_edit_before_manager = category_edit_before_draft.clone();
    let weak_for_category_manager = window.as_weak();
    window.on_manage_category(move |action, name, previous| {
        let Some(window) = weak_for_category_manager.upgrade() else {
            return;
        };
        if category_draft_for_manager.borrow().is_none() {
            match CategoryDraftDirectory::create(&category_root) {
                Ok(draft) => *category_draft_for_manager.borrow_mut() = Some(draft),
                Err(error) => {
                    set_status_error(
                        &window,
                        "No se pudo preparar el borrador de categorías: ",
                        "Could not prepare the category draft: ",
                        error,
                    );
                    return;
                }
            }
        }
        let draft_root = category_draft_for_manager
            .borrow()
            .as_ref()
            .expect("category draft was initialized")
            .path
            .clone();
        let mut library = Library::open(draft_root);
        let mut operation = CategoryDraftOperation {
            action: action.to_string(),
            name: name.to_string(),
            previous: previous.to_string(),
            credit: None,
        };
        let result = apply_category_draft_operation(&mut library, &operation);
        if let Err(error) = result {
            set_status_error(
                &window,
                "No se pudo actualizar la categoría: ",
                "Could not update category: ",
                error,
            );
            return;
        }
        if action == "icon" {
            if let Some(path) = library.category_icon_path(&name) {
                operation.previous = path.to_string_lossy().into_owned();
            }
        }
        if category_operations_for_manager.borrow().is_empty() {
            *category_filter_before_manager.borrow_mut() =
                Some(filters_for_category_manager.borrow().1.clone());
            *category_edit_before_manager.borrow_mut() =
                Some(window.get_managed_category().to_string());
        }
        category_operations_for_manager.borrow_mut().push(operation);
        if action == "rename" && filters_for_category_manager.borrow().1 == previous.as_str() {
            filters_for_category_manager.borrow_mut().1 = name.to_string();
        } else if action == "delete" && filters_for_category_manager.borrow().1 == name.as_str() {
            filters_for_category_manager.borrow_mut().1.clear();
        }
        let games = library.games();
        let categories = library.categories(&games);
        let activities = games
            .iter()
            .map(|game| {
                (
                    game.id().to_owned(),
                    (
                        library.activity_summary(game),
                        library.activity_history_summary(game),
                    ),
                )
            })
            .collect::<HashMap<_, _>>();
        *games_for_category_manager.borrow_mut() = games;
        *categories_for_category_manager.borrow_mut() = categories.clone();
        *activities_for_category_manager.borrow_mut() = activities;
        set_categories(&window, &library, &categories);
        let selected = window
            .get_categories()
            .iter()
            .position(|item| item.as_str() == name.as_str())
            .unwrap_or(if name.is_empty() { 0 } else { 1 })
            .min(window.get_categories().row_count().saturating_sub(1))
            as i32;
        window.set_category_edit_index(selected);
        window.set_category_index(
            categories_for_category_manager
                .borrow()
                .iter()
                .position(|category| category == &filters_for_category_manager.borrow().1)
                .map_or(0, |index| index as i32 + 1),
        );
        set_filtered_games(
            &window,
            &games_for_category_manager.borrow(),
            &categories_for_category_manager.borrow(),
            &activities_for_category_manager.borrow(),
            &filters_for_category_manager,
            &visible_for_category_manager,
        );
        window.invoke_refresh_members();
        window.set_category_name("".into());
        window.invoke_save_settings();
    });
    let edit_original = Rc::new(RefCell::new(None::<Game>));
    let original_for_begin = edit_original.clone();
    let visible_for_begin = filtered_games.clone();
    let weak_for_begin = window.as_weak();
    window.on_begin_edit(move || {
        let Some(window) = weak_for_begin.upgrade() else {
            return;
        };
        if window.get_game_session_active() || window.get_import_scanning() {
            return;
        }
        window.set_focus_library_request(false);
        let Some(game) = visible_for_begin
            .borrow()
            .get(window.get_selected_index().max(0) as usize)
            .cloned()
        else {
            return;
        };
        window.set_artwork_request_serial(window.get_artwork_request_serial().wrapping_add(1));
        populate_editor(&window, &game);
        *original_for_begin.borrow_mut() = Some(game);
        window.set_editor_page("overview".into());
        window.set_showing_editor(true);
        window.set_save_message("".into());
    });
    let original_for_cancel = edit_original.clone();
    let weak_for_cancel = window.as_weak();
    window.on_cancel_edit(move || {
        let Some(window) = weak_for_cancel.upgrade() else {
            return;
        };
        let returning_to_categories = window.get_picking_category_icon();
        window.set_artwork_request_serial(window.get_artwork_request_serial().wrapping_add(1));
        window.set_showing_editor(false);
        window.set_editor_page("overview".into());
        window.set_showing_artwork(false);
        window.set_showing_activity(false);
        window.set_artwork_browsing(false);
        window.set_confirming_remove(false);
        window.set_picking_category_icon(false);
        window.set_save_message("".into());
        window.set_edit_id("".into());
        original_for_cancel.borrow_mut().take();
        if returning_to_categories {
            window.set_showing_settings(true);
        } else {
            window.set_focus_library_request(true);
        }
    });
    let weak_for_back = window.as_weak();
    let settings_snapshot_for_back = ui_settings_for_save.clone();
    let category_draft_for_back = category_draft.clone();
    let category_operations_for_back = category_draft_operations.clone();
    let category_filter_for_back = category_filter_before_draft.clone();
    let category_edit_for_back = category_edit_before_draft.clone();
    let category_icon_generation_for_back = category_icon_request_generation.clone();
    let category_root_for_back = root.clone();
    let games_for_back = all_games.clone();
    let categories_for_back = all_categories.clone();
    let activities_for_back = all_activities.clone();
    let filters_for_back = filters.clone();
    let visible_for_back = filtered_games.clone();
    let background_config_for_back = background_config.clone();
    let update_background_for_back = update_background.clone();
    window.on_back(move || {
        let Some(window) = weak_for_back.upgrade() else {
            return;
        };
        window.set_gamepad_toolbar_focus(false);
        if window.get_keyboard_visible() {
            window.set_keyboard_visible(false);
        } else if window.get_confirming_remove() {
            window.set_confirming_remove(false);
        } else if window.get_showing_artwork() && window.get_artwork_browsing() {
            let parent = window.get_artwork_parent_folder();
            if parent.is_empty() {
                window.invoke_close_artwork_browser();
            } else {
                window.invoke_browse_artwork_folder(parent);
            }
        } else if window.get_picking_category_icon() {
            window.invoke_close_artwork_browser();
        } else if window.get_showing_artwork() || window.get_showing_activity() {
            window.set_showing_artwork(false);
            window.set_showing_activity(false);
            window.set_showing_editor(true);
        } else if window.get_showing_editor() {
            if window.get_editor_page() != "overview" {
                window.set_editor_page("overview".into());
            } else {
                window.invoke_cancel_edit();
            }
        } else {
            let was_modal = !window.get_library_active();
            if window.get_showing_settings() {
                category_icon_generation_for_back.set(
                    category_icon_generation_for_back.get().wrapping_add(1),
                );
                window.set_icon_busy(false);
                window.set_icon_results(ModelRc::default());
                category_operations_for_back.borrow_mut().clear();
                category_draft_for_back.borrow_mut().take();

                let snapshot = settings_snapshot_for_back.borrow().clone();
                window.set_settings_restoring(true);
                restore_ui_settings_snapshot(&window, &snapshot);
                window.set_settings_restoring(false);
                let active_background_mode = if window.get_library_layout().as_str() == "grid" {
                    "grid"
                } else {
                    "list"
                };
                *background_config_for_back.borrow_mut() = (
                    nested_choice(
                        &snapshot,
                        "background_splits",
                        active_background_mode,
                        "single",
                        &["single", "horizontal", "vertical", "diagonal"],
                    )
                    .to_owned(),
                    nested_number(&snapshot, "background_blur", active_background_mode, 0, 0, 40),
                );

                let category_selection = category_edit_for_back
                    .borrow_mut()
                    .take()
                    .unwrap_or_else(|| window.get_managed_category().to_string());
                let category_filter = category_filter_for_back
                    .borrow_mut()
                    .take()
                    .unwrap_or_else(|| filters_for_back.borrow().1.clone());
                let library = Library::open(category_root_for_back.clone());
                let games = library.games();
                let categories = library.categories(&games);
                let activities = games
                    .iter()
                    .map(|game| {
                        (
                            game.id().to_owned(),
                            (
                                library.activity_summary(game),
                                library.activity_history_summary(game),
                            ),
                        )
                    })
                    .collect::<HashMap<_, _>>();
                let category_filter = if category_filter.is_empty()
                    || categories.iter().any(|category| category == &category_filter)
                {
                    category_filter
                } else {
                    library.primary_category().unwrap_or_default().to_owned()
                };
                filters_for_back.borrow_mut().1 = category_filter.clone();
                *games_for_back.borrow_mut() = games;
                *categories_for_back.borrow_mut() = categories.clone();
                *activities_for_back.borrow_mut() = activities;
                set_categories(&window, &library, &categories);
                window.set_category_index(
                    categories
                        .iter()
                        .position(|category| category == &category_filter)
                        .map_or(0, |index| index as i32 + 1),
                );
                window.set_category_edit_index(
                    categories
                        .iter()
                        .position(|category| category == &category_selection)
                        .map_or(0, |index| index as i32 + 1),
                );
                window.set_category_name("".into());
                window.set_icon_path("".into());
                window.set_icon_query("".into());
                window.invoke_refresh_members();
                set_filtered_games(
                    &window,
                    &games_for_back.borrow(),
                    &categories_for_back.borrow(),
                    &activities_for_back.borrow(),
                    &filters_for_back,
                    &visible_for_back,
                );
                let visible = visible_for_back.borrow();
                let background = background_config_for_back.borrow();
                update_background_for_back(
                    &window,
                    window.get_selected_index(),
                    &background,
                    &visible,
                );
                window.set_save_message("".into());
            }
            window.set_showing_editor(false);
            window.set_showing_settings(false);
            window.set_showing_add_game(false);
            if !was_modal && !window.get_search_query().is_empty() {
                window.set_search_query("".into());
                window.invoke_search_changed("".into());
            }
            window.set_focus_library_request(true);
        }
    });
    let weak_for_category = window.as_weak();
    window.on_edit_category_toggled(move |index, checked| {
        let Some(window) = weak_for_category.upgrade() else {
            return;
        };
        let mut choices = window
            .get_edit_category_choices()
            .iter()
            .collect::<Vec<_>>();
        let Some(choice) = choices.get_mut(index as usize) else {
            return;
        };
        choice.checked = checked;
        let selected = choices
            .iter()
            .filter(|choice| choice.checked)
            .map(|choice| choice.name.to_string())
            .collect::<Vec<_>>();
        window.set_edit_categories(selected.join(", ").into());
        window.set_edit_category_choices(ModelRc::new(VecModel::from(choices)));
    });
    let games_for_edit = all_games.clone();
    let categories_for_edit = all_categories.clone();
    let activities_for_edit = all_activities.clone();
    let visible_for_edit = filtered_games.clone();
    let filters_for_edit = filters.clone();
    let root_for_edit = root.clone();
    let weak_for_edit = window.as_weak();
    window.on_save_game(move || {
        let Some(window) = weak_for_edit.upgrade() else {
            return;
        };
        if window.get_confirming_remove() {
            return;
        }
        let Some(original) = edit_original.borrow().clone() else {
            return;
        };
        let game_id = original.id().to_owned();
        let mut library = Library::open(root_for_edit.clone());
        let result = library
            .games()
            .into_iter()
            .find(|game| game.id() == game_id)
            .ok_or_else(|| "El juego ya no está en la biblioteca.".to_owned())
            .and_then(|current| edited_game(&window, &original, &current))
            .and_then(|updated| {
                library
                    .update_game(&game_id, &updated)
                    .map_err(|error| error.to_string())
            });
        match result {
            Ok(()) => {
                let library = Library::open(root_for_edit.clone());
                let fresh_games = library.games();
                if let Some(saved_game) = fresh_games.iter().find(|game| game.id() == game_id).cloned() {
                    *edit_original.borrow_mut() = Some(saved_game);
                }
                let fresh_categories = library.categories(&fresh_games);
                let fresh_activities = fresh_games
                    .iter()
                    .map(|game| {
                        (
                            game.id().to_owned(),
                            (
                                library.activity_summary(game),
                                library.activity_history_summary(game),
                            ),
                        )
                    })
                    .collect::<HashMap<_, _>>();
                *games_for_edit.borrow_mut() = fresh_games;
                *categories_for_edit.borrow_mut() = fresh_categories.clone();
                *activities_for_edit.borrow_mut() = fresh_activities;
                set_categories(&window, &library, &fresh_categories);
                set_filtered_games(
                    &window,
                    &games_for_edit.borrow(),
                    &categories_for_edit.borrow(),
                    &activities_for_edit.borrow(),
                    &filters_for_edit,
                    &visible_for_edit,
                );
                window.set_save_message("".into());
            }
            Err(error) => {
                set_status_error(
                    &window,
                    "No se pudo guardar automáticamente: ",
                    "Could not save automatically: ",
                    error,
                )
            }
        }
    });
    let weak_for_game_autosave = window.as_weak();
    window.on_game_draft_changed(move || {
        if let Some(window) = weak_for_game_autosave.upgrade() {
            window.invoke_save_game();
        }
    });
    let games_for_add = all_games.clone();
    let categories_for_add = all_categories.clone();
    let activities_for_add = all_activities.clone();
    let visible_for_add = filtered_games.clone();
    let filters_for_add = filters.clone();
    let root_for_add = root.clone();
    let weak_for_add = window.as_weak();
    window.on_add_game(move || {
        let Some(window) = weak_for_add.upgrade() else {
            return;
        };
        let mut library = Library::open(root_for_add.clone());
        match library.add_local(
            &window.get_new_title(),
            &window.get_new_path(),
            &window.get_new_arguments(),
            &window.get_new_cwd(),
        ) {
            Ok(()) => {
                let library = Library::open(root_for_add.clone());
                let fresh_games = library.games();
                let fresh_categories = library.categories(&fresh_games);
                let fresh_activities = fresh_games
                    .iter()
                    .map(|game| {
                        (
                            game.id().to_owned(),
                            (
                                library.activity_summary(game),
                                library.activity_history_summary(game),
                            ),
                        )
                    })
                    .collect::<HashMap<_, _>>();
                *games_for_add.borrow_mut() = fresh_games;
                *categories_for_add.borrow_mut() = fresh_categories.clone();
                *activities_for_add.borrow_mut() = fresh_activities;
                set_categories(&window, &library, &fresh_categories);
                window.set_search_query("".into());
                filters_for_add.borrow_mut().0.clear();
                filters_for_add.borrow_mut().1.clear();
                set_filtered_games(
                    &window,
                    &games_for_add.borrow(),
                    &categories_for_add.borrow(),
                    &activities_for_add.borrow(),
                    &filters_for_add,
                    &visible_for_add,
                );
                window.set_showing_add_game(false);
                set_status(&window, "Juego añadido.", "Game added.");
            }
            Err(error) => {
                set_status_error(&window, "No se pudo añadir: ", "Could not add: ", error)
            }
        }
    });
    let games_for_remove = all_games.clone();
    let categories_for_remove = all_categories.clone();
    let activities_for_remove = all_activities.clone();
    let visible_for_remove = filtered_games.clone();
    let filters_for_remove = filters.clone();
    let root_for_remove = root.clone();
    let weak_for_remove = window.as_weak();
    window.on_remove_game(move || {
        let Some(window) = weak_for_remove.upgrade() else {
            return;
        };
        if !window.get_confirming_remove() {
            return;
        }
        let game_id = window.get_edit_id().to_string();
        if game_id.is_empty() {
            return;
        }
        let result = Library::open(root_for_remove.clone()).remove_game(&game_id);
        match result {
            Ok(()) => {
                let library = Library::open(root_for_remove.clone());
                let fresh_games = library.games();
                let fresh_categories = library.categories(&fresh_games);
                let fresh_activities = fresh_games
                    .iter()
                    .map(|game| {
                        (
                            game.id().to_owned(),
                            (
                                library.activity_summary(game),
                                library.activity_history_summary(game),
                            ),
                        )
                    })
                    .collect::<HashMap<_, _>>();
                *games_for_remove.borrow_mut() = fresh_games;
                *categories_for_remove.borrow_mut() = fresh_categories.clone();
                *activities_for_remove.borrow_mut() = fresh_activities;
                set_categories(&window, &library, &fresh_categories);
                set_filtered_games(
                    &window,
                    &games_for_remove.borrow(),
                    &categories_for_remove.borrow(),
                    &activities_for_remove.borrow(),
                    &filters_for_remove,
                    &visible_for_remove,
                );
                window.set_confirming_remove(false);
                window.set_showing_editor(false);
                set_status(
                    &window,
                    "Juego quitado de la biblioteca.",
                    "Game removed from library.",
                );
            }
            Err(error) => {
                set_status_error(&window, "No se pudo quitar: ", "Could not remove: ", error)
            }
        }
    });
    let visible_for_play = filtered_games.clone();
    let library_root = library.data_dir().to_path_buf();
    let session_active = Arc::new(AtomicBool::new(false));
    let (session_events_tx, session_events_rx) = mpsc::channel::<SessionEvent>();
    let options = Rc::new(RefCell::new(Vec::<crate::category_icons::IconOption>::new()));
    let weak = window.as_weak();
    let icon_cache = library.category_icons_dir();
    let icon_events = session_events_tx.clone();
    window.on_search_icons(move || {
        let Some(window) = weak.upgrade() else {
            return;
        };
        if window.get_icon_busy() {
            return;
        }
        let provider = window.get_icon_provider().to_string();
        let query = window.get_icon_query().to_string();
        if query.trim().is_empty() {
            return;
        }
        window.set_icon_results(ModelRc::default());
        window.set_icon_busy(true);
        let cache = icon_cache.clone();
        let events = icon_events.clone();
        thread::spawn(move || {
            let result = crate::category_icons::search(&provider, &query, &cache);
            let _ = events.send(SessionEvent::IconResults(provider, query, result));
        });
    });
    let weak = window.as_weak();
    let icon_cache = library.category_icons_dir();
    let icon_events = session_events_tx.clone();
    let icon_choices = options.clone();
    let icon_generation_for_choose = category_icon_request_generation.clone();
    window.on_choose_icon(move |index| {
        let Some(window) = weak.upgrade() else {
            return;
        };
        if window.get_icon_busy() || window.get_icon_results().row_data(index as usize).is_none() {
            return;
        }
        let Some(option) = icon_choices.borrow().get(index as usize).cloned() else {
            return;
        };
        let target = window.get_managed_category().to_string();
        let generation = icon_generation_for_choose.get().wrapping_add(1);
        icon_generation_for_choose.set(generation);
        window.set_icon_busy(true);
        let cache = icon_cache.clone();
        let events = icon_events.clone();
        thread::spawn(move || {
            let result = crate::category_icons::download(&option, &cache);
            let _ = events.send(SessionEvent::IconDownloaded(
                generation, target, option, result,
            ));
        });
    });
    let launcher_states = Rc::new(VecModel::from(vec![
        slint::SharedString::from("checking");
        LAUNCHERS.len()
    ]));
    window.set_launcher_states(launcher_states.clone().into());
    let weak = window.as_weak();
    let action_states = launcher_states.clone();
    let launcher_events = session_events_tx.clone();
    let pending = Rc::new(RefCell::new([None; LAUNCHERS.len()]));
    let launcher_pending = pending.clone();
    window.on_operate_launcher(move |index| {
        let Some(window) = weak.upgrade() else {
            return;
        };
        let index = index as usize;
        let Some(client) = LAUNCHERS.get(index).copied() else {
            return;
        };
        if window.get_game_session_active() || window.get_import_scanning() {
            return;
        }
        let opening = match action_states.row_data(index).as_deref() {
            Some("open") => false,
            Some("closed" | "error" | "timeout") => true,
            _ => return,
        };
        launcher_pending.borrow_mut()[index] =
            Some((opening, Instant::now() + Duration::from_secs(45)));
        action_states.set_row_data(index, if opening { "opening" } else { "closing" }.into());
        let events = launcher_events.clone();
        thread::spawn(move || {
            let _ = events.send(SessionEvent::LauncherAction(
                index,
                crate::launchers::operate(client, opening),
            ));
        });
    });
    let tray_handle = Arc::new(Mutex::new(None::<ksni::blocking::Handle<EstanteTray>>));
    let tray_hidden = Arc::new(AtomicBool::new(false));
    let tray_starting = Arc::new(AtomicBool::new(false));
    let active_for_import = session_active.clone();
    let import_root = library_root.clone();
    let import_events = session_events_tx.clone();
    let cancel = Arc::new(AtomicBool::new(false));
    let cancel_request = cancel.clone();
    window.on_cancel_import(move || cancel_request.store(true, Ordering::Release));
    let scrape_cancel = cancel.clone();
    let scan_cancel = cancel.clone();
    let weak_for_scrape = window.as_weak();
    let root_for_scrape = import_root.clone();
    let events_for_scrape = import_events.clone();
    let settings_for_scrape = settings.clone();
    window.on_scrape_library(move |replace, selected, info| {
        let Some(window) = weak_for_scrape.upgrade() else {
            return;
        };
        if window.get_import_scanning() || window.get_game_session_active() {
            return;
        }
        let fields: Vec<_> = crate::metadata::ARTWORK_FIELDS
            .iter()
            .copied()
            .zip(selected.iter())
            .filter_map(|(field, checked)| checked.then_some(field))
            .collect();
        if fields.is_empty() && !info {
            return;
        }
        let cancel = scrape_cancel.clone();
        cancel.store(false, Ordering::Release);
        window.set_import_scanning(true);
        set_status(
            &window,
            "Buscando imágenes y fichas…",
            "Fetching artwork and metadata…",
        );
        let root = root_for_scrape.clone();
        let events = events_for_scrape.clone();
        let key = settings_for_scrape.borrow()["steamgriddb_key"]
            .as_str()
            .unwrap_or_default()
            .to_owned();
        let language = if window.get_english_ui() { "en" } else { "es" };
        thread::spawn(move || {
            let result =
                crate::scraping::run(root, key, language.into(), replace, cancel, &fields, info)
                    .map(|(updated, issues, messages)| {
                        ImportOutcome::Scraped(updated, issues, messages)
                    });
            let _ = events.send(SessionEvent::ImportFinished(result));
        });
    });
    let weak_for_import = window.as_weak();
    window.on_scan_imports(move |provider| {
        let Some(window) = weak_for_import.upgrade() else {
            return;
        };
        if window.get_import_scanning() || active_for_import.load(Ordering::Relaxed) {
            return;
        }
        let cancel = scan_cancel.clone();
        cancel.store(false, Ordering::Release);
        window.set_import_scanning(true);
        let provider = provider.to_string();
        let english = window.get_english_ui();
        let provider_label = match provider.as_str() {
            "steam" => "Steam",
            "faugus" => "Faugus",
            "heroic" => "Heroic",
            "recomp" => "RecompLauncher",
            "all" => {
                if english {
                    "all launchers"
                } else {
                    "todos los lanzadores"
                }
            }
            "restore" => {
                if english {
                    "excluded games"
                } else {
                    "juegos excluidos"
                }
            }
            _ => provider.as_str(),
        };
        window.set_save_message(
            if provider == "restore" {
                if english {
                    "Restoring excluded games…".to_owned()
                } else {
                    "Restaurando juegos excluidos…".to_owned()
                }
            } else if english {
                format!("Scanning {provider_label}…")
            } else {
                format!("Escaneando {provider_label}…")
            }
            .into(),
        );
        let root = import_root.clone();
        let events = import_events.clone();
        thread::spawn(move || {
            let result = if provider == "restore" {
                Library::open(root)
                    .restore_excluded_imports()
                    .map(ImportOutcome::Restored)
                    .map_err(|error| error.to_string())
            } else {
                let mut library = Library::open(root);
                scan_import_provider(&mut library, &provider, &cancel)
                    .map(|(added, total)| ImportOutcome::Scanned { added, total })
            };
            let _ = events.send(SessionEvent::ImportFinished(result));
        });
    });
    let update_release = Arc::new(Mutex::new(None::<crate::updates::Release>));
    let weak_for_update_check = window.as_weak();
    let release_for_update_check = update_release.clone();
    window.on_check_updates(move || {
        let Some(window) = weak_for_update_check.upgrade() else {
            return;
        };
        if window.get_update_checking() || window.get_update_installing() {
            return;
        }
        window.set_update_checking(true);
        window.set_update_available(false);
        window.set_update_status(if window.get_english_ui() {
            "Checking for public releases…".into()
        } else {
            "Buscando versiones públicas…".into()
        });
        *release_for_update_check.lock().unwrap() = None;
        let weak = window.as_weak();
        let release = release_for_update_check.clone();
        thread::spawn(move || {
            let result = crate::updates::latest_release();
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(window) = weak.upgrade() {
                    window.set_update_checking(false);
                    match result {
                        Ok(Some(value)) => {
                            let status = if window.get_english_ui() {
                                if crate::updates::appimage_path().is_some() {
                                    format!("Version {} is available. Verified download is ready to install.", value.version)
                                } else {
                                    format!("Version {} is available: {}", value.version, value.url)
                                }
                            } else if crate::updates::appimage_path().is_some() {
                                format!("Versión {} disponible. Descarga verificada lista para instalar.", value.version)
                            } else {
                                format!("Versión {} disponible: {}", value.version, value.url)
                            };
                            window.set_update_status(status.into());
                            window.set_update_available(true);
                            *release.lock().unwrap() = Some(value);
                        }
                        Ok(None) => {
                            window.set_update_status(if window.get_english_ui() {
                                "Estante is up to date.".into()
                            } else {
                                "Estante está actualizado.".into()
                            });
                        }
                        Err(error) => {
                            window.set_update_status(
                                if window.get_english_ui() {
                                    format!("Could not check for updates: {error}")
                                } else {
                                    format!("No se pudo comprobar: {error}")
                                }
                                .into(),
                            );
                        }
                    }
                }
            });
        });
    });
    let weak_for_update_install = window.as_weak();
    window.on_install_update(move || {
        let Some(window) = weak_for_update_install.upgrade() else {
            return;
        };
        if window.get_update_checking() || window.get_update_installing() {
            return;
        }
        let Some(release) = update_release.lock().unwrap().clone() else {
            return;
        };
        let Some(path) = crate::updates::appimage_path() else {
            window.set_update_status(if window.get_english_ui() {
                "Integrated updates are only available in the AppImage.".into()
            } else {
                "La actualización integrada solo funciona desde el AppImage.".into()
            });
            return;
        };
        window.set_update_installing(true);
        window.set_update_status(if window.get_english_ui() {
            "Downloading and verifying the update…".into()
        } else {
            "Descargando y verificando la actualización…".into()
        });
        let weak = window.as_weak();
        thread::spawn(move || {
            let result = crate::updates::install_appimage(&release, &path);
            let _ = slint::invoke_from_event_loop(move || {
                if let Some(window) = weak.upgrade() {
                    window.set_update_installing(false);
                    let status = match result {
                        Ok(version) => {
                            window.set_update_available(false);
                            if window.get_english_ui() {
                                format!("Estante {version} installed. Close and reopen the application.")
                            } else {
                                format!("Estante {version} instalado. Cierra y vuelve a abrir la aplicación.")
                            }
                        }
                        Err(error) => if window.get_english_ui() {
                            format!("Could not install update: {error}")
                        } else {
                            format!("No se pudo instalar: {error}")
                        },
                    };
                    window.set_update_status(status.into());
                }
            });
        });
    });
    let preview_events = session_events_tx.clone();
    window.on_preview_screensaver(move || {
        let _ = preview_events.send(SessionEvent::Screensaver);
    });
    let active_for_play = session_active.clone();
    let events_for_play = session_events_tx.clone();
    let settings_for_play = settings.clone();
    let filters_for_play = filters.clone();
    let saver_paths_for_play = saver_paths.clone();
    let weak_for_play = window.as_weak();
    let launch_generation = Arc::new(AtomicU64::new(0));
    window.on_play_selected(move || {
        let Some(window) = weak_for_play.upgrade() else {
            return;
        };
        if !window.get_library_active() {
            return;
        }
        let visible = visible_for_play.borrow();
        let Some(game) = visible.get(window.get_selected_index() as usize) else {
            return;
        };
        if active_for_play.swap(true, Ordering::Relaxed) {
            return;
        }
        window.set_session_title(game.title().into());
        window.set_session_id(game.id().into());
        let cover = window.get_games().row_data(window.get_selected_index() as usize).map(|row| {
            if row.cover_image.size().width > 0 {
                row.cover_image
            } else {
                row.square_cover_image
            }
        }).unwrap_or_default();
        window.set_session_cover(cover);
        window.set_launch_background(window.get_selected_background_image());
        window.set_launching_game(true);
        let status = if window.get_english_ui() {
            format!("Starting {}…", game.title())
        } else {
            format!("Iniciando {}…", game.title())
        };
        window.set_save_message(status.into());

        let banner = if window.get_background_source() == "global" {
            super::resolve_background_setting(window.get_global_background().as_str())
        } else {
            game.field("banner").unwrap_or_default().to_owned()
        };
        let background_size = background_sizes(background_viewport_size(
            (
                window.get_background_width().max(1) as u32,
                window.get_background_height().max(1) as u32,
            ),
            window.window().scale_factor(),
        ))
        .1;
        let request = launch_generation.fetch_add(1, Ordering::Release).wrapping_add(1);
        if !banner.is_empty() {
            let generation = launch_generation.clone();
            let weak = window.as_weak();
            thread::spawn(move || {
                let Some(pixels) = load_background_pixels(clean_image_path(&banner), false, &mut None, background_size) else { return; };
                let pixels = blur_background_image(&pixels, 20);
                let _ = weak.upgrade_in_event_loop(move |window| {
                    if window.get_launching_game() && background_request_is_current(&generation, request) {
                        window.set_launch_background(Image::from_rgba8(SharedPixelBuffer::clone_from_slice(
                            pixels.as_raw(), pixels.width(), pixels.height(),
                        )));
                    }
                });
            });
        }
        let behavior_for_play = settings_for_play
            .borrow()
            .get("playing_behavior")
            .and_then(Value::as_str)
            .unwrap_or("none")
            .to_owned();
        let (query, category) = filters_for_play.borrow().clone();
        let saver_paths = saver_paths_for_play.borrow().clone();
        match Library::open(library_root.clone()).launch(game) {
            Ok((mut child, token)) => {
                window.set_game_session_active(true);
                let game_id = game.id().to_owned();
                let game = game.clone();
                let launcher_pid = child.id();
                let started = chrono_utc_now();
                let began = Instant::now();
                let root = library_root.clone();
                let events = events_for_play.clone();
                thread::spawn(move || {
                    let mut child_code = None;
                    let mut child_exited = false;
                    let mut observed_game = false;
                    let mut started_notified = false;
                    loop {
                        if !child_exited {
                            match child.try_wait() {
                                Ok(Some(status)) => {
                                    child_code = status.code();
                                    child_exited = true;
                                }
                                Ok(None) => (),
                                Err(_) => child_exited = true,
                            }
                        }
                        let processes =
                            Library::matching_game_processes(&game, launcher_pid, &token);
                        if !started_notified
                            && !processes.is_empty()
                            && began.elapsed() >= Duration::from_secs(25)
                        {
                            let _ = events.send(SessionEvent::Started(behavior_for_play.clone()));
                            started_notified = true;
                            match behavior_for_play.as_str() {
                                "tray" => (),
                                "screensaver" if !saver_paths.is_empty() => {
                                    let _ = events.send(SessionEvent::Screensaver);
                                }
                                "hide" => {
                                    let handoff = crate::supervisor::Handoff {
                                        game_id: game_id.clone(),
                                        launcher_pid,
                                        token: token.clone(),
                                        root: root.clone(),
                                        started_at: started.clone(),
                                        started_uptime: crate::supervisor::uptime_seconds().unwrap_or_default() - began.elapsed().as_secs_f64(),
                                        restore: json!({"query": query, "category": category, "selected": game_id}),
                                    };
                                    match crate::supervisor::prepare(handoff) {
                                        Ok(folder) => {
                                            let (ack, acknowledged) = mpsc::channel();
                                            if events.send(SessionEvent::Handoff(folder.clone(), ack)).is_ok()
                                                && acknowledged.recv_timeout(Duration::from_secs(3)).unwrap_or(false)
                                            {
                                                break;
                                            }
                                            let _ = std::fs::write(folder.join("cancel"), []);
                                        }
                                        Err(error) => { let _ = events.send(SessionEvent::Warning(error)); }
                                    }
                                }
                                _ => (),
                            }
                        }
                        observed_game |= !processes.is_empty();
                        let launch_failed =
                            !observed_game && began.elapsed() >= Duration::from_secs(90);
                        if child_exited
                            && processes.is_empty()
                            && (observed_game || launch_failed || game.kind() == "local"
                                || child_code.is_some_and(|code| code != 0))
                        {
                            let seconds = began.elapsed().as_secs();
                            let mut library = Library::open(root);
                            let result = library
                                .record_session(&game_id, seconds, &started, child_code)
                                .map_err(|error| error.to_string());
                            let _ = events.send(SessionEvent::Finished(result));
                            break;
                        }
                        thread::sleep(Duration::from_millis(500));
                    }
                });
            }
            Err(error) => {
                active_for_play.store(false, Ordering::Relaxed);
                window.set_game_session_active(false);
                window.set_launching_game(false);
                set_status_error(&window, "No se pudo iniciar: ", "Could not start: ", error);
            }
        }
    });
    let active_for_close = session_active.clone();
    let weak_for_close = window.as_weak();
    window.on_close_window(move || {
        if active_for_close.load(Ordering::Relaxed) {
            if let Some(window) = weak_for_close.upgrade() {
                set_status(
                    &window,
                    "Hay una partida en ejecución; espera a que termine para cerrar Estante.",
                    "A game is running; wait for it to finish before closing Estante.",
                );
            }
        } else {
            slint::quit_event_loop().unwrap_or(());
        }
    });
    let active_for_native_close = session_active.clone();
    let weak_for_native_close = window.as_weak();
    window.window().on_close_requested(move || {
        if active_for_native_close.load(Ordering::Relaxed) {
            if let Some(window) = weak_for_native_close.upgrade() {
                set_status(
                    &window,
                    "Hay una partida en ejecución; espera a que termine para cerrar Estante.",
                    "A game is running; wait for it to finish before closing Estante.",
                );
            }
            slint::CloseRequestResponse::KeepWindowShown
        } else {
            let _ = slint::quit_event_loop();
            slint::CloseRequestResponse::HideWindow
        }
    });
    let weak_for_tray = window.as_weak();
    let events_for_tray = session_events_tx.clone();
    let tray_starting_for_tray = tray_starting.clone();
    let tray_handle_for_tray = tray_handle.clone();
    let tray_hidden_for_tray = tray_hidden.clone();
    let generation_for_tray = screensaver_image_generation.clone();
    let requests_for_tray = screensaver_image_requests.clone();
    window.on_to_tray(move || {
        if let Some(window) = weak_for_tray.upgrade() {
            if tray_handle_for_tray.lock().unwrap().is_some() {
                if window.window().hide().is_ok() {
                    tray_hidden_for_tray.store(true, Ordering::Relaxed);
                    window.set_screensaver_active(false);
                    cancel_screensaver_image_request(&generation_for_tray, &requests_for_tray);
                }
                return;
            }
            if tray_starting_for_tray.swap(true, Ordering::Relaxed) {
                return;
            }
            window.set_save_message(if window.get_english_ui() {
                "Connecting to the system tray…".into()
            } else {
                "Conectando con la bandeja del sistema…".into()
            });
            let events = events_for_tray.clone();
            let tray = EstanteTray {
                events: events.clone(),
                english: window.get_english_ui(),
            };
            thread::spawn(move || {
                use ksni::blocking::TrayMethods;
                let result = tray.spawn().map_err(|error| error.to_string());
                let _ = events.send(SessionEvent::TrayStarted(result));
            });
        }
    });
    let save_notice_generation = Rc::new(std::cell::Cell::new(0_u64));
    let save_notice_generation_for_save = save_notice_generation.clone();
    let category_draft_for_save = category_draft.clone();
    let category_operations_for_save = category_draft_operations.clone();
    let category_filter_before_save = category_filter_before_draft.clone();
    let category_edit_before_save = category_edit_before_draft.clone();
    let category_root_for_save = root.clone();
    window.on_save_settings(move || {
        let Some(window) = weak_window.upgrade() else {
            return;
        };
        if !can_save {
            return;
        }
        if !valid_color(&window.get_ring_color_text()) || !valid_color(&window.get_grid_ring_color_text()) {
            set_status(
                &window,
                "El color debe ser hexadecimal (#RRGGBB o #AARRGGBB).",
                "Color must be hexadecimal (#RRGGBB or #AARRGGBB).",
            );
            return;
        }
        let mut updated = match Library::open(&root).settings() {
            Ok(value) if value.is_object() => value,
            Ok(_) => {
                set_status(
                    &window,
                    "Los ajustes deben contener un objeto JSON.",
                    "Settings must contain a JSON object.",
                );
                return;
            }
            Err(error) => {
                set_status_error(
                    &window,
                    "No se pudieron leer los ajustes: ",
                    "Could not read settings: ",
                    error,
                );
                return;
            }
        };
        let current_ui_settings = ui_settings_snapshot(&window);
        merge_changed_settings(
            &mut updated,
            &ui_settings_for_save_callback.borrow(),
            &current_ui_settings,
        );
        updated["layout"] = json!(normalize_slint_layout(window.get_library_layout().as_str()));
        if window.get_screensaver_source() == "application"
            && screensaver_paths(&updated, &games_for_save.borrow())
                .first()
                .is_none_or(|path| validate_image_file(std::path::Path::new(path)).is_err())
        {
            set_status(
                &window,
                "El fondo del salvapantallas debe ser una imagen válida.",
                "The screensaver background must be a valid image.",
            );
            return;
        }
        let pending_category_operations = category_operations_for_save.borrow().clone();
        if !pending_category_operations.is_empty() {
            let preflight = match CategoryDraftDirectory::create(&category_root_for_save) {
                Ok(draft) => draft,
                Err(error) => {
                    set_status_error(
                        &window,
                        "No se pudo validar el borrador de categorías: ",
                        "Could not validate the category draft: ",
                        error,
                    );
                    return;
                }
            };
            let mut preflight_library = Library::open(preflight.path.clone());
            for operation in &pending_category_operations {
                if let Err(error) =
                    apply_category_draft_operation(&mut preflight_library, operation)
                {
                    set_status_error(
                        &window,
                        "No se pudieron guardar las categorías: ",
                        "Could not save categories: ",
                        error,
                    );
                    return;
                }
            }
        }
        match Library::save_settings_at(&root, &updated) {
            Ok(()) => {
                let mut category_commit_error = None;
                if !pending_category_operations.is_empty() {
                    let mut category_library = Library::open(category_root_for_save.clone());
                    for operation in &pending_category_operations {
                        if let Err(error) =
                            apply_category_draft_operation(&mut category_library, operation)
                        {
                            category_commit_error = Some(error);
                            break;
                        }
                        let mut operations = category_operations_for_save.borrow_mut();
                        if !operations.is_empty() {
                            operations.remove(0);
                        }
                    }
                }
                let category_reset_error = if category_commit_error.is_none()
                    && !pending_category_operations.is_empty()
                {
                    let library = Library::open(category_root_for_save.clone());
                    let games = library.games();
                    let categories = library.categories(&games);
                    let activities = games
                        .iter()
                        .map(|game| {
                            (
                                game.id().to_owned(),
                                (
                                    library.activity_summary(game),
                                    library.activity_history_summary(game),
                                ),
                            )
                        })
                        .collect::<HashMap<_, _>>();
                    *games_for_category_save.borrow_mut() = games;
                    *categories_for_category_save.borrow_mut() = categories.clone();
                    *activities_for_category_save.borrow_mut() = activities;
                    set_categories(&window, &library, &categories);
                    let category_filter = filters_for_category_save.borrow().1.clone();
                    window.set_category_index(
                        categories
                            .iter()
                            .position(|category| category == &category_filter)
                            .map_or(0, |index| index as i32 + 1),
                    );
                    set_filtered_games(
                        &window,
                        &games_for_category_save.borrow(),
                        &categories_for_category_save.borrow(),
                        &activities_for_category_save.borrow(),
                        &filters_for_category_save,
                        &visible_for_category_save,
                    );
                    category_operations_for_save.borrow_mut().clear();
                    category_filter_before_save.borrow_mut().take();
                    category_edit_before_save.borrow_mut().take();
                    let reset_error = category_draft_for_save
                        .borrow_mut()
                        .as_mut()
                        .and_then(|draft| draft.reset(&category_root_for_save).err());
                    if reset_error.is_some() {
                        category_draft_for_save.borrow_mut().take();
                    }
                    reset_error
                } else {
                    None
                };
                *ui_settings_for_save_callback.borrow_mut() = current_ui_settings;
                *settings_for_save.borrow_mut() = updated;
                *saver_paths_for_save.borrow_mut() =
                    screensaver_paths(&settings_for_save.borrow(), &games_for_save.borrow());
                if let Some(error) = category_commit_error {
                    set_status_error(
                        &window,
                        "Se guardaron los ajustes, pero no las categorías: ",
                        "Settings were saved, but categories were not: ",
                        error,
                    );
                } else if let Some(error) = category_reset_error {
                    set_status_error(
                        &window,
                        "Las categorías se guardaron, pero no se pudo reiniciar el borrador: ",
                        "Categories were saved, but the draft could not be reset: ",
                        error,
                    );
                } else {
                    set_status(&window, "Ajustes guardados.", "Settings saved.");
                }
                let generation = save_notice_generation_for_save.get().wrapping_add(1);
                save_notice_generation_for_save.set(generation);
                let generation_for_timer = save_notice_generation_for_save.clone();
                let weak_for_timer = window.as_weak();
                let saved_message = window.get_save_message();
                slint::Timer::single_shot(std::time::Duration::from_secs(4), move || {
                    if generation_for_timer.get() == generation {
                        if let Some(window) = weak_for_timer.upgrade() {
                            if window.get_save_message() == saved_message {
                                window.set_save_message("".into());
                            }
                        }
                    }
                });
            }
            Err(error) => {
                set_status_error(
                    &window,
                    "No se pudieron guardar: ",
                    "Could not save: ",
                    error,
                );
            }
        }
    });

    let weak_for_settings_autosave = window.as_weak();
    window.on_settings_draft_changed(move || {
        if let Some(window) = weak_for_settings_autosave.upgrade() {
            window.invoke_save_settings();
        }
    });

    let gamepad = Rc::new(RefCell::new(if poll_devices {
        crate::controls::Gamepad::open().ok()
    } else {
        None
    }));
    let gamepad_for_timer = gamepad.clone();
    let timer_window = window.as_weak();
    let root_for_timer = library.data_dir().to_path_buf();
    let category_draft_for_timer = category_draft.clone();
    let category_operations_for_timer = category_draft_operations.clone();
    let category_filter_before_timer = category_filter_before_draft.clone();
    let category_edit_before_timer = category_edit_before_draft.clone();
    let category_icon_generation_for_timer = category_icon_request_generation.clone();
    let games_for_timer = all_games.clone();
    let categories_for_timer = all_categories.clone();
    let activities_for_timer = all_activities.clone();
    let filters_for_timer = filters.clone();
    let visible_for_timer = filtered_games.clone();
    let active_for_timer = session_active.clone();
    let tray_handle_for_timer = tray_handle.clone();
    let tray_hidden_for_timer = tray_hidden.clone();
    let tray_starting_for_timer = tray_starting.clone();
    let saver_paths_for_timer = saver_paths.clone();
    let settings_for_timer = settings.clone();
    let screensaver_generation_for_timer = screensaver_image_generation.clone();
    let screensaver_requests_for_timer = screensaver_image_requests.clone();
    let activity_for_timer = last_activity.clone();
    let connectivity_for_timer = connectivity_requests.clone();
    let mut saver_index = 0usize;
    let mut saver_next = None;
    let mut gamepad_retry_at = Instant::now();
    let mut gamepad_connected = false;
    let mut virtual_cursor_active = false;
    let mut virtual_cursor_position = (0.0_f32, 0.0_f32);
    let mut virtual_cursor_tick = Instant::now();
    let mut keyboard_provider: Option<String> = None;
    let status_events = session_events_tx.clone();
    let mut checking_launchers = false;
    let mut launcher_scan_at = Instant::now();
    let mut status_clock_refresh_at = Instant::now();
    let mut battery_refresh_at = Instant::now();
    let mut connectivity_refresh_at = Instant::now();
    let mut bluetooth_devices_for_timer = Vec::<crate::connectivity::BluetoothDevice>::new();
    let timer = slint::Timer::default();
    timer.start(
        slint::TimerMode::Repeated,
        Duration::from_millis(16),
        move || {
            let Some(window) = timer_window.upgrade() else {
                return;
            };
            let now = Instant::now();
            if now.duration_since(status_clock_refresh_at) >= Duration::from_secs(1) {
                update_system_clock(&window);
                status_clock_refresh_at = now;
            }
            if now.duration_since(battery_refresh_at) >= Duration::from_secs(30) {
                update_battery_status(&window);
                battery_refresh_at = now;
            }
            if window.get_showing_settings()
                && window.get_settings_section() == 5
                && !window.get_connectivity_busy()
                && now.duration_since(connectivity_refresh_at) >= Duration::from_secs(10)
            {
                window.set_connectivity_busy(true);
                let _ = connectivity_for_timer.send(crate::connectivity::Request::Refresh);
                connectivity_refresh_at = now;
            }
            while let Ok(state) = connectivity_states.try_recv() {
                window.set_wifi_available(state.wifi_available);
                window.set_wifi_hardware_enabled(state.wifi_hardware_enabled);
                window.set_wifi_enabled(state.wifi_enabled);
                window.set_wifi_connected(state.wifi_connected);
                window.set_bluetooth_available(state.bluetooth_available);
                window.set_bluetooth_enabled(state.bluetooth_enabled);
                window.set_bluetooth_discoverable(state.bluetooth_discoverable);
                window.set_bluetooth_pairable(state.bluetooth_pairable);
                window.set_bluetooth_scanning(false);
                if bluetooth_devices_for_timer != state.bluetooth_devices {
                    let devices = state
                        .bluetooth_devices
                        .iter()
                        .map(|device| BluetoothDevice {
                            name: device.name.clone().into(),
                            address: device.address.clone().into(),
                            paired: device.paired,
                            connected: device.connected,
                        })
                        .collect::<Vec<_>>();
                    window.set_bluetooth_devices(ModelRc::from(Rc::new(VecModel::from(devices))));
                    bluetooth_devices_for_timer = state.bluetooth_devices.clone();
                }
                window.set_connectivity_error(state.error.into());
                window.set_connectivity_loaded(true);
                window.set_connectivity_busy(false);
            }
            while let Ok(event) = session_events_rx.try_recv() {
                match event {
                    SessionEvent::Started(behavior) => {
                        window.set_launching_game(false);
                        set_status(&window, "Juego en ejecución", "Game running");
                        if behavior == "tray" {
                            window.invoke_to_tray();
                        }
                    }
                    SessionEvent::TrayStarted(result) => {
                        tray_starting_for_timer.store(false, Ordering::Relaxed);
                        match result {
                            Ok(handle) => match window.window().hide() {
                                Ok(()) => {
                                    *tray_handle_for_timer.lock().unwrap() = Some(handle);
                                    tray_hidden_for_timer.store(true, Ordering::Relaxed);
                                    window.set_screensaver_active(false);
                                    cancel_screensaver_image_request(
                                        &screensaver_generation_for_timer,
                                        &screensaver_requests_for_timer,
                                    );
                                    *activity_for_timer.borrow_mut() = Instant::now();
                                }
                                Err(error) => {
                                    handle.shutdown().wait();
                                    set_status_error(
                                        &window,
                                        "No se pudo ocultar la ventana: ",
                                        "Could not hide the window: ",
                                        error,
                                    );
                                }
                            },
                            Err(error) => set_status_error(
                                &window,
                                "No hay bandeja del sistema disponible: ",
                                "No system tray is available: ",
                                error,
                            ),
                        }
                    }
                    SessionEvent::RestoreFromTray => {
                        if let Some(handle) = tray_handle_for_timer.lock().unwrap().take() {
                            handle.shutdown().wait();
                        }
                        tray_hidden_for_timer.store(false, Ordering::Relaxed);
                        window.set_screensaver_active(false);
                        cancel_screensaver_image_request(
                            &screensaver_generation_for_timer,
                            &screensaver_requests_for_timer,
                        );
                        saver_next = None;
                        *activity_for_timer.borrow_mut() = Instant::now();
                        if let Err(error) = window.show() {
                            set_status_error(
                                &window,
                                "No se pudo restaurar Estante: ",
                                "Could not restore Estante: ",
                                error,
                            );
                        }
                        window.window().set_minimized(false);
                        window.window().set_fullscreen(window.get_start_fullscreen());
                        window.set_focus_library_request(true);
                    }
                    SessionEvent::ExitFromTray => {
                        if active_for_timer.load(Ordering::Relaxed) {
                            set_status(
                                &window,
                                "Hay una partida en ejecución; espera a que termine para cerrar Estante.",
                                "A game is running; wait for it to finish before closing Estante.",
                            );
                        } else {
                            if let Some(handle) = tray_handle_for_timer.lock().unwrap().take() {
                                handle.shutdown().wait();
                            }
                            let _ = slint::quit_event_loop();
                        }
                    }
                    SessionEvent::Screensaver => {
                        if let Some(path) = saver_paths_for_timer.borrow().first() {
                            saver_index = 0;
                            window.set_screensaver_active(true);
                            request_screensaver_image(
                                &window,
                                path,
                                &screensaver_generation_for_timer,
                                &screensaver_requests_for_timer,
                            );
                            saver_next = Some(Instant::now() + screensaver_slide(&settings_for_timer.borrow()));
                        }
                    }
                    SessionEvent::LauncherAction(index, result) => {
                        if let Err(error) = result {
                            pending.borrow_mut()[index] = None;
                            launcher_states.set_row_data(index, "error".into());
                            set_status_error(&window, "No se pudo gestionar el lanzador: ", "Launcher action failed: ", error);
                        }
                        launcher_scan_at = Instant::now();
                    }
                    SessionEvent::LauncherSnapshot(result) => {
                        checking_launchers = false;
                        let Ok(running) = result else { continue; };
                        for (index, client) in LAUNCHERS.iter().enumerate() {
                            let open = running.contains(client);
                            let mut pending = pending.borrow_mut();
                            let state = match pending[index] {
                                Some((expected, until)) if open != expected && Instant::now() < until => {
                                    if expected { "opening" } else { "closing" }
                                }
                                Some((expected, _)) if open != expected => { pending[index] = None; "timeout" }
                                _ => { pending[index] = None; if open { "open" } else { "closed" } }
                            };
                            if launcher_states.row_data(index).as_deref() != Some(state) {
                                launcher_states.set_row_data(index, state.into());
                            }
                        }
                    }
                    SessionEvent::IconResults(provider, query, result) => {
                        if !window.get_showing_settings() || window.get_settings_section() != 2 {
                            window.set_icon_busy(false);
                            continue;
                        }
                        window.set_icon_busy(false);
                        if window.get_icon_query() != query || window.get_icon_provider() != provider { continue; }
                        match result {
                            Ok(found) => {
                                let labels = found.iter().map(|item| format!("{} · {} · {}", item.name, item.author, item.license).into()).collect::<Vec<_>>();
                                if found.is_empty() { set_status(&window, "Sin resultados.", "No results."); }
                                *options.borrow_mut() = found;
                                window.set_icon_results(ModelRc::new(VecModel::from(labels)));
                            }
                            Err(error) => set_status_error(&window, "Error al buscar iconos: ", "Icon search failed: ", error),
                        }
                    }
                    SessionEvent::IconDownloaded(generation, target, option, result) => {
                        if generation != category_icon_generation_for_timer.get() {
                            continue;
                        }
                        window.set_icon_busy(false);
                        if !window.get_showing_settings() || window.get_settings_section() != 2 {
                            continue;
                        }
                        let result = result.and_then(|path| {
                            let credit = json!({"name": option.name, "source": option.source, "author": option.author, "license": option.license, "provider": option.provider});
                            if category_draft_for_timer.borrow().is_none() {
                                let draft = CategoryDraftDirectory::create(&root_for_timer)
                                    .map_err(|error| error.to_string())?;
                                *category_draft_for_timer.borrow_mut() = Some(draft);
                            }
                            let draft_root = category_draft_for_timer
                                .borrow()
                                .as_ref()
                                .expect("category draft was initialized")
                                .path
                                .clone();
                            let operation = CategoryDraftOperation {
                                action: "icon".to_owned(),
                                name: target.clone(),
                                previous: path.to_string_lossy().into_owned(),
                                credit: Some(credit),
                            };
                            let mut library = Library::open(draft_root);
                            apply_category_draft_operation(&mut library, &operation)
                                .map_err(|error| error.to_string())?;
                            if category_operations_for_timer.borrow().is_empty() {
                                *category_filter_before_timer.borrow_mut() =
                                    Some(filters_for_timer.borrow().1.clone());
                                *category_edit_before_timer.borrow_mut() =
                                    Some(window.get_managed_category().to_string());
                            }
                            category_operations_for_timer
                                .borrow_mut()
                                .push(operation);
                            Ok(library)
                        });
                        match result {
                            Ok(library) => {
                                set_categories(&window, &library, &categories_for_timer.borrow());
                                window.invoke_save_settings();
                            }
                            Err(error) => set_status_error(&window, "No se pudo preparar el icono: ", "Could not prepare icon: ", error),
                        }
                    }
                    SessionEvent::ImportFinished(result) => {
                        window.set_import_scanning(false);
                        let library = Library::open(root_for_timer.clone());
                        let fresh_games = library.games();
                        let fresh_categories = library.categories(&fresh_games);
                        let fresh_activities = fresh_games
                            .iter()
                            .map(|game| (
                                game.id().to_owned(),
                                (library.activity_summary(game), library.activity_history_summary(game)),
                            ))
                            .collect::<HashMap<_, _>>();
                        *games_for_timer.borrow_mut() = fresh_games.clone();
                        *categories_for_timer.borrow_mut() = fresh_categories.clone();
                        *activities_for_timer.borrow_mut() = fresh_activities;
                        set_categories(&window, &library, &fresh_categories);
                        set_filtered_games(
                            &window,
                            &fresh_games,
                            &categories_for_timer.borrow(),
                            &activities_for_timer.borrow(),
                            &filters_for_timer,
                            &visible_for_timer,
                        );
                        let message = match result {
                            Ok(ImportOutcome::Scraped(updated, issues, messages)) => {
                                let mut summary = if window.get_english_ui() {
                                    format!("{updated} games updated · {issues} issues")
                                } else {
                                    format!("{updated} juegos actualizados · {issues} incidencias")
                                };
                                for message in messages { summary.push_str(" · "); summary.push_str(&message); }
                                summary
                            }
                            Ok(ImportOutcome::Restored(count)) => {
                                if window.get_english_ui() {
                                    format!("{count} games restored.")
                                } else {
                                    format!("{count} juegos restaurados.")
                                }
                            }
                            Ok(ImportOutcome::Scanned { added, total }) => {
                                if cancel.load(Ordering::Acquire) {
                                    if window.get_english_ui() { format!("Scan cancelled: {added} new, {total} found.") } else { format!("Escaneo cancelado: {added} nuevos, {total} encontrados.") }
                                } else if window.get_english_ui() {
                                    format!("Scan complete: {added} new, {total} found.")
                                } else {
                                    format!("Escaneo completado: {added} nuevos, {total} encontrados.")
                                }
                            }
                            Err(error) => {
                                if window.get_english_ui() {
                                    format!("Import failed: {error}")
                                } else {
                                    format!("No se pudo importar: {error}")
                                }
                            }
                        };
                        window.set_save_message(message.into());
                    }
                    SessionEvent::Warning(error) => {
                        set_status_error(
                            &window,
                            "No se pudo ocultar Estante; la partida seguirá supervisada: ",
                            "Could not hide Estante; the game remains supervised: ",
                            error,
                        );
                    }
                    SessionEvent::Handoff(folder, acknowledged) => {
                        let handed_off = std::fs::write(folder.join("handoff"), []).is_ok();
                        let _ = acknowledged.send(handed_off);
                        if handed_off {
                            SUPERVISOR_HANDOFF_EXIT.store(true, Ordering::Relaxed);
                            let _ = slint::quit_event_loop();
                        } else {
                            let _ = std::fs::write(folder.join("cancel"), []);
                            set_status(
                                &window,
                                "No se pudo transferir la supervisión de la partida; Estante seguirá abierto.",
                                "Could not hand off game supervision; Estante will stay open.",
                            );
                        }
                    }
                    SessionEvent::Finished(result) => {
                    window.set_screensaver_active(false);
                    cancel_screensaver_image_request(
                        &screensaver_generation_for_timer,
                        &screensaver_requests_for_timer,
                    );
                    saver_next = None;
                    active_for_timer.store(false, Ordering::Relaxed);
                    window.set_game_session_active(false);
                    window.set_launching_game(false);
                    {
                        let library = Library::open(root_for_timer.clone());
                        let fresh_games = library.games();
                        let fresh_categories = library.categories(&fresh_games);
                        let fresh_activities = fresh_games
                            .iter()
                            .map(|game| {
                                (
                                    game.id().to_owned(),
                                    (
                                        library.activity_summary(game),
                                        library.activity_history_summary(game),
                                    ),
                                )
                            })
                            .collect::<HashMap<_, _>>();
                        *games_for_timer.borrow_mut() = fresh_games.clone();
                        *categories_for_timer.borrow_mut() = fresh_categories.clone();
                        *activities_for_timer.borrow_mut() = fresh_activities;
                        set_categories(&window, &library, &fresh_categories);
                        set_filtered_games(
                            &window,
                            &fresh_games,
                            &categories_for_timer.borrow(),
                            &activities_for_timer.borrow(),
                            &filters_for_timer,
                            &visible_for_timer,
                        );
                        match result {
                            Ok(()) => set_status(
                                &window,
                                "Partida finalizada; actividad guardada.",
                                "Game finished; activity saved.",
                            ),
                            Err(error) => set_status_error(
                                &window,
                                "Partida finalizada; no se pudo guardar la actividad: ",
                                "Game finished; could not save activity: ",
                                error,
                            ),
                        }
                    }
                }
                }
            }
            if window.get_screensaver_active()
                && saver_next.is_some_and(|deadline| Instant::now() >= deadline)
                && !saver_paths_for_timer.borrow().is_empty()
            {
                let paths = saver_paths_for_timer.borrow();
                saver_index = (saver_index + 1) % paths.len();
                request_screensaver_image(
                    &window,
                    &paths[saver_index],
                    &screensaver_generation_for_timer,
                    &screensaver_requests_for_timer,
                );
                saver_next = Some(Instant::now() + screensaver_slide(&settings_for_timer.borrow()));
            }
            let current_settings = settings_for_timer.borrow();
            if current_settings
                .get("screensaver_enabled")
                .and_then(Value::as_bool)
                .unwrap_or(false)
                && !window.get_screensaver_active()
                && !tray_hidden_for_timer.load(Ordering::Relaxed)
                && !active_for_timer.load(Ordering::Relaxed)
                && activity_for_timer.borrow().elapsed() >= screensaver_idle(&current_settings)
                && !saver_paths_for_timer.borrow().is_empty()
            {
                saver_index = 0;
                let paths = saver_paths_for_timer.borrow();
                window.set_screensaver_active(true);
                request_screensaver_image(
                    &window,
                    &paths[saver_index],
                    &screensaver_generation_for_timer,
                    &screensaver_requests_for_timer,
                );
                saver_next = Some(Instant::now() + screensaver_slide(&current_settings));
            }
            drop(current_settings);
            if poll_devices && !checking_launchers && Instant::now() >= launcher_scan_at {
                checking_launchers = true;
                launcher_scan_at = Instant::now() + Duration::from_secs(3);
                let events = status_events.clone();
                thread::spawn(move || { let _ = events.send(SessionEvent::LauncherSnapshot(crate::launchers::running_clients())); });
            }
            let settings_cursor_mode = window.get_showing_settings()
                && window.get_controller_input_active()
                && !window.get_keyboard_visible();
            let mut cursor_axis = (0.0_f32, 0.0_f32);
            let mut scroll_axis = (0.0_f32, 0.0_f32);
            let actions = {
                let mut gamepad = gamepad_for_timer.borrow_mut();
                if poll_devices && gamepad.is_none() && Instant::now() >= gamepad_retry_at {
                    gamepad_retry_at = Instant::now() + Duration::from_secs(2);
                    *gamepad = crate::controls::Gamepad::open().ok();
                }
                let actions = gamepad
                    .as_mut()
                    .map(|gamepad| {
                        let actions = gamepad.poll(
                            !window.window().is_minimized()
                                && !tray_hidden_for_timer.load(Ordering::Relaxed),
                            settings_cursor_mode,
                        );
                        cursor_axis = gamepad.cursor_axis();
                        scroll_axis = gamepad.scroll_axis();
                        actions
                    })
                    .unwrap_or_default();
                let connected = gamepad
                    .as_ref()
                    .is_some_and(crate::controls::Gamepad::is_connected);
                if connected != gamepad_connected {
                    gamepad_connected = connected;
                    window.set_controller_input_active(connected);
                }
                actions
            };
            if settings_cursor_mode && gamepad_connected {
                let now = Instant::now();
                let elapsed = now.duration_since(virtual_cursor_tick).as_secs_f32().min(0.05);
                virtual_cursor_tick = now;
                let scale = window.window().scale_factor();
                let size = window.window().size();
                let width = size.width as f32 / scale;
                let height = size.height as f32 / scale;
                if !virtual_cursor_active {
                    virtual_cursor_position = (width / 2.0, height / 2.0);
                    virtual_cursor_active = true;
                } else {
                    virtual_cursor_position.0 =
                        (virtual_cursor_position.0 + cursor_axis.0 * 900.0 * elapsed)
                            .clamp(0.0, width);
                    virtual_cursor_position.1 =
                        (virtual_cursor_position.1 + cursor_axis.1 * 900.0 * elapsed)
                            .clamp(0.0, height);
                }
                window.set_virtual_cursor_x(virtual_cursor_position.0);
                window.set_virtual_cursor_y(virtual_cursor_position.1);
                window.set_virtual_cursor_visible(true);
                let _ = window
                    .window()
                    .dispatch_event_with_result(WindowEvent::PointerMoved {
                        position: LogicalPosition::new(
                            virtual_cursor_position.0,
                            virtual_cursor_position.1,
                        ),
                    });
                let delta_x = -scroll_axis.0 * 900.0 * elapsed;
                let delta_y = -scroll_axis.1 * 900.0 * elapsed;
                if delta_x != 0.0 || delta_y != 0.0 {
                    let _ = window.window().dispatch_event_with_result(
                        WindowEvent::PointerScrolled {
                            position: LogicalPosition::new(
                                virtual_cursor_position.0,
                                virtual_cursor_position.1,
                            ),
                            delta_x,
                            delta_y,
                        },
                    );
                }
            } else {
                virtual_cursor_active = false;
                window.set_virtual_cursor_visible(false);
                virtual_cursor_tick = Instant::now();
            }
            for action in actions {
                if !settings_cursor_mode {
                    let _ = window
                        .window()
                        .with_winit_window(|native_window| native_window.set_cursor_visible(false));
                }
                window.set_controller_input_active(true);
                *activity_for_timer.borrow_mut() = Instant::now();
                if keyboard_provider.is_some() && (action == "back" || action == "search") {
                    if let Some(provider) = keyboard_provider.take() { let _ = crate::system_keyboard::hide(&provider); }
                    continue;
                }
                if !window.get_keyboard_visible() && ((action == "search"
                    && (window.get_library_active() || window.get_text_input_focused())) || action == "confirm" && window.get_text_input_focused())
                {
                    if !window.get_text_input_focused() {
                        window.invoke_focus_search();
                    }
                    let current_settings = settings_for_timer.borrow();
                    let mode = current_settings
                        .get("onscreen_keyboard")
                        .and_then(Value::as_str)
                        .unwrap_or("auto");
                    let fallback = current_settings
                        .get("keyboard_fallback")
                        .and_then(Value::as_bool)
                        .unwrap_or(true);
                    if let Some(provider) = keyboard_provider.take() {
                        let _ = crate::system_keyboard::hide(&provider);
                    }
                    match mode {
                        "disabled" => window.set_keyboard_visible(false),
                        "builtin" => window.set_keyboard_visible(true),
                        _ => match crate::system_keyboard::open(mode) {
                            Ok(provider) => {
                                window.set_keyboard_visible(false);
                                keyboard_provider = Some(provider);
                            }
                            Err(error) if fallback => {
                                window.set_keyboard_visible(true);
                                window.set_save_message(
                                    if window.get_english_ui() {
                                        format!("{error} Estante's keyboard will be used instead.")
                                    } else {
                                        format!("{error} Se usará el teclado de Estante.")
                                    }
                                    .into(),
                                );
                            }
                            Err(error) => {
                                window.set_keyboard_visible(false);
                                set_status_error(
                                    &window,
                                    "No se pudo abrir el teclado del sistema: ",
                                    "Could not open the system keyboard: ",
                                    error,
                                );
                            }
                        },
                    }
                    continue;
                }
                if action == "confirm" && settings_cursor_mode && virtual_cursor_active {
                    let position = LogicalPosition::new(
                        virtual_cursor_position.0,
                        virtual_cursor_position.1,
                    );
                    let _ = window
                        .window()
                        .dispatch_event_with_result(WindowEvent::PointerPressed {
                            position,
                            button: PointerEventButton::Left,
                        });
                    let _ = window
                        .window()
                        .dispatch_event_with_result(WindowEvent::PointerReleased {
                            position,
                            button: PointerEventButton::Left,
                        });
                    window.set_controller_input_active(true);
                    continue;
                }
                if window.get_screensaver_active() {
                    window.set_screensaver_active(false);
                    saver_next = None;
                } else if action == "exit" && active_for_timer.load(Ordering::Relaxed) {
                    set_status(
                        &window,
                        "Hay una partida en ejecución; espera a que termine para cerrar Estante.",
                        "A game is running; wait for it to finish before closing Estante.",
                    );
                } else {
                    if matches!(action, "back" | "exit" | "save")
                        && let Some(provider) = keyboard_provider.take()
                    {
                        let _ = crate::system_keyboard::hide(&provider);
                    }
                    handle_action(&window, action);
                    window.set_controller_input_active(true);
                }
            }
        },
    );
    if window.get_check_updates_on_start() && restore.is_none() {
        window.invoke_check_updates();
    }
    Ok((window, timer))
}

fn load_previews(
    window: slint::Weak<ListWindow>,
    request: ArtworkRequest,
    options: Vec<ArtworkOption>,
    cancelled: Arc<AtomicBool>,
) {
    for worker in 0..8 {
        let pending = options
            .iter()
            .cloned()
            .enumerate()
            .skip(worker)
            .step_by(8)
            .collect::<Vec<_>>();
        let weak = window.clone();
        let request = request.clone();
        let cancelled = cancelled.clone();
        thread::spawn(move || {
            for (index, option) in pending {
                if cancelled.load(std::sync::atomic::Ordering::Relaxed) {
                    break;
                }
                let result = crate::artwork::preview(&option, Some(&cancelled));
                let weak = weak.clone();
                let request = request.clone();
                let cancelled = cancelled.clone();
                let _ = slint::invoke_from_event_loop(move || {
                    let Some(window) = weak.upgrade() else {
                        return;
                    };
                    if cancelled.load(std::sync::atomic::Ordering::Relaxed)
                        || !request.matches(&window)
                    {
                        cancelled.store(true, std::sync::atomic::Ordering::Relaxed);
                        return;
                    }
                    if let Ok(pixels) = result {
                        let model = window.get_artwork_results();
                        if let Some(mut row) = model.row_data(index) {
                            row.preview =
                                Image::from_rgba8(slint::SharedPixelBuffer::clone_from_slice(
                                    pixels.as_raw(),
                                    pixels.width(),
                                    pixels.height(),
                                ));
                            model.set_row_data(index, row);
                        }
                    }
                });
            }
        });
    }
}

#[derive(Clone)]
struct ArtworkRequest {
    serial: i32,
    game: String,
    provider: String,
    field: String,
    query: String,
}

impl ArtworkRequest {
    fn start(window: &ListWindow) -> Option<Self> {
        if !window.get_showing_artwork() || window.get_edit_id().is_empty() {
            return None;
        }
        let serial = window.get_artwork_request_serial().wrapping_add(1);
        window.set_artwork_request_serial(serial);
        Some(Self {
            serial,
            game: window.get_edit_id().to_string(),
            provider: window.get_artwork_provider().to_string(),
            field: window.get_artwork_field().to_string(),
            query: window.get_artwork_query().to_string(),
        })
    }

    fn matches(&self, window: &ListWindow) -> bool {
        window.get_showing_artwork()
            && self.serial == window.get_artwork_request_serial()
            && self.game == window.get_edit_id().as_str()
            && self.provider == window.get_artwork_provider().as_str()
            && self.field == window.get_artwork_field().as_str()
            && self.query == window.get_artwork_query().as_str()
    }
}

fn send_key(window: &ListWindow, key: slint::platform::Key, shift: bool) {
    use slint::platform::WindowEvent;
    if shift {
        window.window().dispatch_event(WindowEvent::KeyPressed {
            text: slint::platform::Key::Shift.into(),
        });
    }
    let text: slint::SharedString = key.into();
    window
        .window()
        .dispatch_event(WindowEvent::KeyPressed { text: text.clone() });
    window
        .window()
        .dispatch_event(WindowEvent::KeyReleased { text });
    if shift {
        window.window().dispatch_event(WindowEvent::KeyReleased {
            text: slint::platform::Key::Shift.into(),
        });
    }
}

fn settings_target_in_left_column(section: i32, target: i32) -> bool {
    match section {
        0 => (0..6).contains(&target),
        2 => matches!(target, 0 | 2 | 3),
        3 => target == 0,
        4 => (0..=3).contains(&target),
        5 => target == 0,
        _ => true,
    }
}

fn settings_target_column(section: i32, target: i32) -> Option<i32> {
    match section {
        0 => Some(if target < 6 { 0 } else { 1 }),
        2 => Some(if target == 1 { 1 } else { 0 }),
        3 => Some(if target == 0 { 0 } else { 1 }),
        4 if (0..=3).contains(&target) => Some(0),
        4 if (5..=8).contains(&target) => Some(1),
        5 if (0..=1).contains(&target) => Some(target),
        _ => None,
    }
}

fn editor_focus_neighbor(
    current: i32,
    action: &str,
    can_swap_backgrounds: bool,
    has_secondary_background: bool,
) -> Option<i32> {
    const POSITIONS: [(i32, i32); 16] = [
        (0, 0),
        (1, 0),
        (2, 0),
        (0, 1),
        (1, 1),
        (0, 2),
        (1, 2),
        (0, 3),
        (1, 3),
        (0, 4),
        (1, 4),
        (0, 5),
        (1, 5),
        (1, 6),
        (2, 6),
        (2, -1),
    ];
    let available: Vec<bool> = (0..POSITIONS.len())
        .map(|index| match index {
            5 => can_swap_backgrounds,
            6 => has_secondary_background,
            _ => true,
        })
        .collect();
    spatial_focus_neighbor(current, action, &POSITIONS, &available).or_else(|| {
        if current < 0 || current as usize >= POSITIONS.len() {
            Some(0)
        } else {
            None
        }
    })
}

fn editor_subpage_focus_neighbor(
    page: &str,
    current: i32,
    action: &str,
    category_count: usize,
    is_local: bool,
) -> Option<i32> {
    let (positions, available): (Vec<(i32, i32)>, Vec<bool>) = match page {
        "manual" => (
            vec![
                (0, 0),
                (2, 0),
                (0, 1),
                (0, 2),
                (0, 3),
                (0, 4),
                (0, 5),
                (0, 6),
                (0, 7),
                (0, 8),
                (1, 9),
                (2, 9),
            ],
            vec![true; 12],
        ),
        "categories" => {
            let mut positions = vec![(0, 0), (2, 0)];
            positions.extend((0..category_count).map(|index| (0, index as i32 + 1)));
            positions.push((1, category_count as i32 + 1));
            positions.push((2, category_count as i32 + 1));
            let available = vec![true; positions.len()];
            (positions, available)
        }
        "execution" => (
            vec![
                (0, 0),
                (2, 0),
                (0, 1),
                (0, 2),
                (0, 3),
                (0, 4),
                (1, 5),
                (2, 5),
            ],
            vec![
                true, true, is_local, is_local, is_local, is_local, true, true,
            ],
        ),
        _ => return None,
    };
    match (page, action, current) {
        ("manual", "right", 0) | ("categories", "right", 0) | ("execution", "right", 0) => {
            return Some(1);
        }
        ("manual", "left", 1) | ("categories", "left", 1) | ("execution", "left", 1) => {
            return Some(0);
        }
        ("manual", "right", 9) => return Some(10),
        ("manual", "left", 10) => return Some(9),
        ("manual", "right", 10) => return Some(11),
        ("manual", "left", 11) => return Some(10),
        ("categories", "right", target) if target == category_count as i32 + 1 => {
            return Some(category_count as i32 + 2);
        }
        ("categories", "left", target) if target == category_count as i32 + 2 => {
            return Some(category_count as i32 + 1);
        }
        ("categories", "right", target) if target == category_count as i32 + 2 => {
            return Some(category_count as i32 + 3);
        }
        ("categories", "left", target) if target == category_count as i32 + 3 => {
            return Some(category_count as i32 + 2);
        }
        ("execution", "right", 5) if is_local => return Some(6),
        ("execution", "left", 6) if is_local => return Some(5),
        ("execution", "right", 6) => return Some(7),
        ("execution", "left", 7) => return Some(6),
        (_, "left" | "right", _) => return None,
        _ => (),
    }
    match page {
        "manual" if action == "up" && matches!(current, 10 | 11) => return Some(9),
        "categories"
            if action == "up" && current >= category_count as i32 + 2 && category_count > 0 =>
        {
            return Some(category_count as i32 + 1);
        }
        "execution" if action == "up" && is_local && matches!(current, 6 | 7) => return Some(5),
        _ => (),
    }
    spatial_focus_neighbor(current, action, &positions, &available)
}

fn editor_page_focus_is_text(page: &str, target: i32, is_local: bool) -> bool {
    match page {
        "manual" => (2..=9).contains(&target),
        "execution" => is_local && (2..=5).contains(&target),
        _ => false,
    }
}

fn artwork_focus_neighbor(current: i32, action: &str, has_swap: bool) -> Option<i32> {
    const POSITIONS: [(i32, i32); 13] = [
        (0, 0),
        (2, 0),
        (0, 1),
        (1, 1),
        (2, 1),
        (0, 2),
        (1, 2),
        (0, 3),
        (1, 3),
        (2, 3),
        (3, 3),
        (1, 5),
        (2, 5),
    ];
    let mut available = vec![true; POSITIONS.len()];
    available[6] = has_swap;
    spatial_focus_neighbor(current, action, &POSITIONS, &available)
}

fn artwork_result_focus_neighbor(
    current: i32,
    count: i32,
    columns: i32,
    action: &str,
) -> Option<i32> {
    if current < 0 || current >= count || columns < 1 {
        return None;
    }
    match action {
        "left" if current > 0 => Some(current - 1),
        "right" if current + 1 < count => Some(current + 1),
        "up" if current >= columns => Some(current - columns),
        "down" if current + columns < count => Some(current + columns),
        "down" if current + 1 < count => Some(count - 1),
        _ => None,
    }
}

fn spatial_focus_neighbor(
    current: i32,
    action: &str,
    positions: &[(i32, i32)],
    available: &[bool],
) -> Option<i32> {
    let Some((origin_x, origin_y)) = positions
        .get(current as usize)
        .copied()
        .filter(|_| current >= 0 && available.get(current as usize).copied().unwrap_or(false))
    else {
        return available
            .iter()
            .position(|available| *available)
            .map(|i| i as i32);
    };
    let mut best = None;
    for (index, (x, y)) in positions.iter().copied().enumerate() {
        if index as i32 == current || !available.get(index).copied().unwrap_or(false) {
            continue;
        }
        let (dx, dy) = (x - origin_x, y - origin_y);
        let (forward, cross) = match action {
            "left" => (-dx, dy.abs()),
            "right" => (dx, dy.abs()),
            "up" => (-dy, dx.abs()),
            "down" => (dy, dx.abs()),
            _ => return None,
        };
        if forward <= 0 {
            continue;
        }
        let score = forward + cross * 4;
        if best.is_none_or(|(best_score, _)| score < best_score) {
            best = Some((score, index as i32));
        }
    }
    best.map(|(_, index)| index)
}

fn handle_action(window: &ListWindow, action: &str) {
    if window.get_game_session_active() {
        return;
    }
    if window.get_confirming_remove() {
        match action {
            "left" => window.set_remove_focus_index(0),
            "right" => window.set_remove_focus_index(1),
            "back" | "exit" => window.set_confirming_remove(false),
            "confirm" if window.get_remove_focus_index() == 1 => window.invoke_remove_game(),
            "confirm" => window.set_confirming_remove(false),
            _ => (),
        }
        return;
    }
    if window.get_keyboard_visible() {
        match action {
            "left" => {
                let columns = if window.get_keyboard_row() == 5 {
                    if window.get_keyboard_multiline() {
                        8
                    } else {
                        7
                    }
                } else {
                    keyboard_keys(&window, window.get_keyboard_row()).row_count() as i32
                };
                window.set_keyboard_column(
                    (window.get_keyboard_column() - 1).rem_euclid(columns.max(1)),
                );
            }
            "right" => {
                let columns = if window.get_keyboard_row() == 5 {
                    if window.get_keyboard_multiline() {
                        8
                    } else {
                        7
                    }
                } else {
                    keyboard_keys(&window, window.get_keyboard_row()).row_count() as i32
                };
                window.set_keyboard_column(
                    (window.get_keyboard_column() + 1).rem_euclid(columns.max(1)),
                );
            }
            "up" | "down" => {
                let row =
                    (window.get_keyboard_row() + if action == "up" { -1 } else { 1 }).clamp(0, 5);
                window.set_keyboard_row(row);
                let columns = if row == 5 {
                    if window.get_keyboard_multiline() {
                        8
                    } else {
                        7
                    }
                } else {
                    keyboard_keys(&window, row).row_count() as i32
                };
                window.set_keyboard_column(window.get_keyboard_column().min(columns - 1));
            }
            "play" | "confirm" => {
                if window.get_keyboard_row() == 5 {
                    window.invoke_keyboard_action(window.get_keyboard_column());
                } else if let Some(key) = keyboard_keys(&window, window.get_keyboard_row())
                    .row_data(window.get_keyboard_column().max(0) as usize)
                {
                    window.invoke_type_key(key);
                }
            }
            "page_previous" => window.invoke_erase_last_character(),
            "page_next" => window.invoke_type_key(" ".into()),
            "save" => window.invoke_finish_keyboard(true),
            "back" | "exit" => window.invoke_finish_keyboard(false),
            _ => (),
        }
        return;
    }
    if window.get_combo_popup_open() {
        let key = match action {
            "up" | "left" => slint::platform::Key::UpArrow,
            "down" | "right" => slint::platform::Key::DownArrow,
            "confirm" => slint::platform::Key::Return,
            "back" => slint::platform::Key::Escape,
            _ => return,
        };
        send_key(window, key, false);
        return;
    }
    if action == "confirm" && window.get_text_input_focused() {
        window.set_keyboard_visible(true);
        return;
    }
    if window.get_showing_settings() && window.get_settings_slider_focused() {
        match action {
            "confirm" => {
                send_key(window, slint::platform::Key::Return, false);
                return;
            }
            "left" | "right" => {
                send_key(
                    window,
                    if action == "left" {
                        slint::platform::Key::LeftArrow
                    } else {
                        slint::platform::Key::RightArrow
                    },
                    false,
                );
                return;
            }
            "up" | "down" => {
                send_key(window, slint::platform::Key::Tab, action == "up");
                return;
            }
            _ => (),
        }
    }
    if window.get_showing_settings() && window.get_settings_section() != 1 {
        let section = window.get_settings_section();
        let target = window.get_settings_focus_target();
        let content_focused = target != -1;
        match action {
            "confirm" => send_key(window, slint::platform::Key::Return, false),
            "back" | "exit" => window.invoke_back(),
            "right" if !content_focused => {
                window.invoke_focus_settings_content();
            }
            "right" if target < 0 => send_key(window, slint::platform::Key::Tab, false),
            "right" => {
                if let Some(column) = settings_target_column(section, target) {
                    window.invoke_move_settings_focus(
                        column,
                        window.get_settings_focus_y(),
                        "right".into(),
                    );
                }
            }
            "left" if !content_focused => (),
            "left" if target >= 0 && settings_target_in_left_column(section, target) => {
                window.invoke_clear_settings_focus_target();
                window.invoke_focus_settings_sidebar();
            }
            "left" if target >= 0 => {
                if let Some(column) = settings_target_column(section, target) {
                    window.invoke_move_settings_focus(
                        column,
                        window.get_settings_focus_y(),
                        "left".into(),
                    );
                }
            }
            "left" => {
                window.invoke_clear_settings_focus_target();
                window.invoke_focus_settings_sidebar();
            }
            "up" => send_key(window, slint::platform::Key::Tab, true),
            "down" => send_key(window, slint::platform::Key::Tab, false),
            _ => (),
        }
        if matches!(
            action,
            "confirm" | "back" | "exit" | "left" | "right" | "up" | "down"
        ) {
            return;
        }
    }
    if window.get_showing_settings()
        && window.get_settings_section() == 1
        && matches!(action, "left" | "right")
    {
        if action == "right" && window.get_settings_sidebar_focused() {
            window.invoke_focus_settings_content();
            return;
        }
        let focus_column = window.get_settings_focus_target();
        let on_left = matches!(focus_column, 0 | 1 | 4);
        let on_right = matches!(focus_column, 2 | 3 | 5 | 6 | 7);
        if action == "left" && on_left {
            window.invoke_clear_settings_focus_target();
            window.invoke_focus_settings_sidebar();
        } else if action == "right" && on_left {
            window.invoke_move_settings_focus(0, window.get_settings_focus_y(), "right".into());
        } else if action == "left" && on_right {
            window.invoke_move_settings_focus(1, window.get_settings_focus_y(), "left".into());
        } else if focus_column < 0 || action == "right" && focus_column >= 5 {
            send_key(window, slint::platform::Key::Tab, action == "left");
        } else {
            send_key(
                window,
                if action == "left" {
                    slint::platform::Key::LeftArrow
                } else {
                    slint::platform::Key::RightArrow
                },
                false,
            );
        }
        return;
    }
    if window.get_showing_editor()
        && window.get_editor_page() == "overview"
        && matches!(action, "left" | "right" | "up" | "down")
    {
        if let Some(next) = editor_focus_neighbor(
            window.get_editor_focus_target(),
            action,
            !window.get_edit_banner().is_empty()
                && !window.get_edit_secondary_background().is_empty(),
            !window.get_edit_secondary_background().is_empty(),
        ) {
            window.set_editor_focus_target(next);
            window.set_editor_focus_serial(window.get_editor_focus_serial().wrapping_add(1));
        }
        return;
    }
    if window.get_showing_editor() && window.get_editor_page() != "overview" {
        if matches!(action, "back" | "exit") {
            window.set_editor_page("overview".into());
            return;
        }
        if matches!(action, "left" | "right" | "up" | "down") {
            let page = window.get_editor_page();
            let next = editor_subpage_focus_neighbor(
                page.as_str(),
                window.get_editor_focus_target(),
                action,
                window.get_edit_category_choices().row_count(),
                window.get_edit_is_local(),
            );
            if let Some(next) = next {
                window.set_editor_focus_target(next);
                window.set_editor_focus_serial(window.get_editor_focus_serial().wrapping_add(1));
                window.set_text_input_focused(editor_page_focus_is_text(
                    page.as_str(),
                    next,
                    window.get_edit_is_local(),
                ));
            }
            return;
        }
    }
    if window.get_showing_artwork()
        && action == "confirm"
        && !window.get_artwork_browsing()
        && window.get_artwork_results_focus_index() >= 0
    {
        window.invoke_choose_artwork(window.get_artwork_results_focus_index());
        return;
    }
    if window.get_showing_activity() && matches!(action, "left" | "right" | "up" | "down") {
        if let Some(next) = spatial_focus_neighbor(
            window.get_activity_focus_target(),
            action,
            &[(0, 0), (2, 0)],
            &[true, true],
        ) {
            window.set_activity_focus_target(next);
            window.set_activity_focus_serial(window.get_activity_focus_serial().wrapping_add(1));
        }
        return;
    }
    if window.get_showing_artwork() && matches!(action, "left" | "right" | "up" | "down") {
        handle_artwork_navigation(window, action);
        return;
    }
    if !window.get_library_active() {
        if window.get_showing_artwork() && window.get_artwork_browsing() {
            let count = window.get_artwork_browser_item_count();
            let index = window.get_artwork_browser_focus_index();
            let columns = window.get_artwork_browser_columns().max(1);
            match action {
                "back" | "exit" => window.invoke_back(),
                "up" if index >= columns => {
                    window.set_artwork_browser_focus_index(index - columns);
                    window.set_artwork_browser_focus_serial(
                        window.get_artwork_browser_focus_serial().wrapping_add(1),
                    );
                }
                "up" if index >= 0 => {
                    window.set_artwork_browser_toolbar_focus_index(3);
                    window.set_artwork_browser_toolbar_focus_serial(
                        window
                            .get_artwork_browser_toolbar_focus_serial()
                            .wrapping_add(1),
                    );
                }
                "up" => {
                    let parent = window.get_artwork_parent_folder();
                    if !parent.is_empty() {
                        window.invoke_browse_artwork_folder(parent);
                    } else {
                        window.set_artwork_browsing(false);
                    }
                }
                "down" if window.get_artwork_browser_toolbar_focus_index() >= 0 => {
                    window.set_artwork_browser_toolbar_focus_index(-1);
                    window.set_artwork_browser_focus_index(index.max(0));
                    window.set_artwork_browser_focus_serial(
                        window.get_artwork_browser_focus_serial().wrapping_add(1),
                    );
                }
                "down"
                    if index >= 0
                        && (index + columns < count || (index / columns + 1) * columns < count) =>
                {
                    window.set_artwork_browser_focus_index((index + columns).min(count - 1));
                    window.set_artwork_browser_focus_serial(
                        window.get_artwork_browser_focus_serial().wrapping_add(1),
                    );
                }
                "down" => send_key(window, slint::platform::Key::Tab, false),
                "left" | "right" if window.get_artwork_browser_toolbar_focus_index() >= 0 => {
                    send_key(window, slint::platform::Key::Tab, action == "left");
                }
                "left" if index >= 0 && index % columns > 0 => {
                    window.set_artwork_browser_focus_index(index - 1);
                    window.set_artwork_browser_focus_serial(
                        window.get_artwork_browser_focus_serial().wrapping_add(1),
                    );
                }
                "left" if index >= 0 => {
                    window.set_artwork_browser_toolbar_focus_index(0);
                    window.set_artwork_browser_toolbar_focus_serial(
                        window
                            .get_artwork_browser_toolbar_focus_serial()
                            .wrapping_add(1),
                    );
                }
                "left" => send_key(window, slint::platform::Key::Tab, true),
                "right" if index >= 0 && index % columns < columns - 1 && index + 1 < count => {
                    window.set_artwork_browser_focus_index(index + 1);
                    window.set_artwork_browser_focus_serial(
                        window.get_artwork_browser_focus_serial().wrapping_add(1),
                    );
                }
                "right" if index >= 0 => {
                    window.set_artwork_browser_toolbar_focus_index(5);
                    window.set_artwork_browser_toolbar_focus_serial(
                        window
                            .get_artwork_browser_toolbar_focus_serial()
                            .wrapping_add(1),
                    );
                }
                "right" => send_key(window, slint::platform::Key::Tab, false),
                "save" if window.get_artwork_browser_selected_valid() => {
                    window.set_artwork_location(window.get_artwork_browser_selected_path());
                    window.invoke_import_artwork();
                }
                "confirm" => send_key(window, slint::platform::Key::Return, false),
                _ => (),
            }
            return;
        }
        match action {
            "back" | "exit" => window.invoke_back(),
            "save" if window.get_showing_editor() && !window.get_confirming_remove() => {
                window.invoke_save_game()
            }
            "save" if window.get_showing_settings() => window.invoke_save_settings(),
            "left" => send_key(window, slint::platform::Key::LeftArrow, false),
            "right" => send_key(window, slint::platform::Key::RightArrow, false),
            "up" => send_key(window, slint::platform::Key::Tab, true),
            "down" => send_key(window, slint::platform::Key::Tab, false),
            "confirm" => send_key(window, slint::platform::Key::Return, false),
            _ => (),
        }
        return;
    }
    let side_list = matches!(window.get_list_side().as_str(), "left" | "right");
    if action == "confirm" {
        if window.get_gamepad_toolbar_focus() {
            send_key(window, slint::platform::Key::Return, false);
        } else if window.get_games().row_count() == 0 {
            window.set_settings_section(3);
            window.set_showing_settings(true);
        } else {
            window.invoke_focus_dock_entry();
        }
        return;
    }
    if window.get_gamepad_toolbar_focus() {
        match action {
            "up" => window.invoke_focus_library(),
            "left" | "right" => window.invoke_step_dock_focus(action == "right"),
            "down" => (),
            _ => return handle_library_action(window, action, side_list),
        }
        return;
    }
    if window.get_games().row_count() == 0 && action == "up" {
        window.invoke_focus_search();
        return;
    }
    if !side_list && action == "up" && window.get_library_layout().as_str() != "grid" {
        window.invoke_focus_dock_entry();
        return;
    }
    handle_library_action(window, action, side_list);
}

fn set_artwork_focus(window: &ListWindow, target: i32) {
    window.set_artwork_navigation_target(target);
    window.set_artwork_navigation_serial(window.get_artwork_navigation_serial().wrapping_add(1));
    window.set_text_input_focused(matches!(target, 2 | 9));
}

fn set_artwork_results_focus(window: &ListWindow, index: i32) {
    window.set_artwork_results_focus_index(index);
    window.set_artwork_results_focus_serial(
        window.get_artwork_results_focus_serial().wrapping_add(1),
    );
    window.set_text_input_focused(false);
}

fn set_artwork_browser_toolbar_focus(window: &ListWindow, index: i32) {
    window.set_artwork_browser_toolbar_focus_index(index);
    window.set_artwork_browser_toolbar_focus_serial(
        window
            .get_artwork_browser_toolbar_focus_serial()
            .wrapping_add(1),
    );
    window.set_text_input_focused(false);
}

fn set_artwork_browser_grid_focus(window: &ListWindow, index: i32) {
    window.set_artwork_browser_toolbar_focus_index(-1);
    window.set_artwork_browser_focus_index(index);
    window.set_artwork_browser_focus_serial(
        window.get_artwork_browser_focus_serial().wrapping_add(1),
    );
    window.set_text_input_focused(false);
}

fn handle_artwork_navigation(window: &ListWindow, action: &str) {
    if window.get_artwork_browsing() {
        let count = window.get_artwork_browser_item_count();
        let columns = window.get_artwork_browser_columns().max(1);
        let index = window.get_artwork_browser_focus_index();
        let toolbar = window.get_artwork_browser_toolbar_focus_index();
        let target = window.get_artwork_navigation_target();

        if target >= 11 {
            match action {
                "left" if target == 12 => set_artwork_focus(window, 11),
                "right" if target == 11 => set_artwork_focus(window, 12),
                "up" if count > 0 => set_artwork_browser_grid_focus(window, count - 1),
                _ => (),
            }
            return;
        }

        if toolbar >= 0 {
            match action {
                "left" if toolbar == 4 => set_artwork_browser_toolbar_focus(window, 3),
                "left" if toolbar == 5 && index >= 0 => {
                    set_artwork_browser_grid_focus(window, index)
                }
                "right" if toolbar == 3 => set_artwork_browser_toolbar_focus(window, 4),
                "right" if toolbar <= 2 && count > 0 => {
                    set_artwork_browser_grid_focus(window, index.max(0))
                }
                "up" if toolbar == 0 => {
                    let up = if window.get_artwork_parent_folder().is_empty() {
                        4
                    } else {
                        3
                    };
                    set_artwork_browser_toolbar_focus(window, up);
                }
                "up" if toolbar == 1 => set_artwork_browser_toolbar_focus(window, 0),
                "up" if toolbar == 2 => {
                    let previous = if window.get_artwork_pictures().is_empty() {
                        0
                    } else {
                        1
                    };
                    set_artwork_browser_toolbar_focus(window, previous);
                }
                "up" if toolbar == 3 && !window.get_artwork_parent_folder().is_empty() => {
                    window.invoke_browse_artwork_folder(window.get_artwork_parent_folder());
                }
                "up" if toolbar == 5 && index >= 0 => set_artwork_browser_grid_focus(window, index),
                "down" if toolbar <= 2 => {
                    let next = match toolbar {
                        0 if !window.get_artwork_pictures().is_empty() => Some(1),
                        0 if !window.get_artwork_downloads().is_empty() => Some(2),
                        1 if !window.get_artwork_downloads().is_empty() => Some(2),
                        _ => None,
                    };
                    if let Some(next) = next {
                        set_artwork_browser_toolbar_focus(window, next);
                    } else if count > 0 {
                        set_artwork_browser_grid_focus(window, index.max(0));
                    } else {
                        set_artwork_focus(window, 11);
                    }
                }
                "down" if count > 0 => set_artwork_browser_grid_focus(window, index.max(0)),
                "down" => set_artwork_focus(window, 11),
                _ => (),
            }
            return;
        }

        if index >= 0 {
            if let Some(next) = artwork_result_focus_neighbor(index, count, columns, action) {
                set_artwork_browser_grid_focus(window, next);
                return;
            }
            match action {
                "up" => {
                    set_artwork_browser_toolbar_focus(
                        window,
                        if window.get_artwork_parent_folder().is_empty() {
                            4
                        } else {
                            3
                        },
                    );
                }
                "left" if index % columns == 0 => set_artwork_browser_toolbar_focus(window, 0),
                "right" if window.get_artwork_browser_selected_valid() => {
                    set_artwork_browser_toolbar_focus(window, 5)
                }
                "down" => {
                    set_artwork_browser_grid_focus(window, -1);
                    set_artwork_focus(window, 11);
                }
                _ => (),
            }
            return;
        }

        if count > 0 {
            set_artwork_browser_toolbar_focus(window, 3);
        } else {
            set_artwork_focus(window, 11);
        }
        return;
    }

    let result_index = window.get_artwork_results_focus_index();
    let count = window.get_artwork_results().row_count() as i32;
    let columns = window.get_artwork_result_columns().max(1);
    if result_index >= 0 {
        if let Some(next) = artwork_result_focus_neighbor(result_index, count, columns, action) {
            set_artwork_results_focus(window, next);
        } else if action == "up" && result_index < columns {
            set_artwork_results_focus(window, -1);
            set_artwork_focus(window, 9);
        } else if action == "down" {
            set_artwork_results_focus(window, -1);
            set_artwork_focus(window, 11);
        }
        return;
    }

    let target = window.get_artwork_navigation_target();
    if action == "down" && (7..=10).contains(&target) && count > 0 {
        set_artwork_results_focus(window, 0);
        return;
    }
    if action == "up" && target >= 11 && count > 0 {
        set_artwork_results_focus(window, count - 1);
        return;
    }
    if let Some(next) = artwork_focus_neighbor(
        target,
        action,
        !window.get_edit_banner().is_empty() && !window.get_edit_secondary_background().is_empty(),
    ) {
        set_artwork_focus(window, next);
    }
}

fn handle_library_action(window: &ListWindow, action: &str, side_list: bool) {
    if window.get_library_layout().as_str() == "grid" {
        match action {
            "up" | "down" | "left" | "right" => {
                window.invoke_navigate_grid(action.into());
                return;
            }
            "page_next" | "grid_page_next" => {
                window.invoke_grid_page(1);
                return;
            }
            "page_previous" | "grid_page_previous" => {
                window.invoke_grid_page(-1);
                return;
            }
            _ => (),
        }
    }
    match action {
        "up" | "left" if side_list || action == "left" => {
            let count = window.get_games().row_count();
            if count > 0 {
                let index = window.get_selected_index() as usize;
                window.set_selected_index((if index == 0 { count - 1 } else { index - 1 }) as i32);
            }
        }
        "down" | "right" if side_list || action == "right" => {
            let count = window.get_games().row_count();
            if count > 0 {
                window.set_selected_index(
                    ((window.get_selected_index() as usize + 1) % count) as i32,
                );
            }
        }
        "play" => window.invoke_play_selected(),
        "save" => window.invoke_begin_edit(),
        "menu" => {
            window.set_settings_section(0);
            window.set_showing_settings(true);
        }
        "appearance_settings" => {
            window.set_settings_section(if window.get_library_layout().as_str() == "grid" { 4 } else { 1 });
            window.set_showing_settings(true);
        }
        "search" => {
            window.invoke_focus_search();
            window.set_keyboard_visible(true);
        }
        "category_next" | "category_previous" => {
            let labels = window.get_categories();
            let count = labels.row_count();
            if count > 0 {
                let current = window.get_category_index() as usize;
                let next = if action == "category_next" {
                    (current + 1) % count
                } else {
                    (current + count - 1) % count
                };
                window.set_category_index(next as i32);
                if let Some(label) = labels.row_data(next) {
                    window.invoke_category_changed(label);
                }
            }
        }
        "page_next" | "page_previous" => {
            let labels = window.get_letters();
            let count = labels.row_count();
            if count > 0 {
                let current = window.get_letter_index() as usize;
                let next = if action == "page_next" {
                    (current + 1) % count
                } else {
                    (current + count - 1) % count
                };
                window.set_letter_index(next as i32);
                if let Some(label) = labels.row_data(next) {
                    window.invoke_letter_changed(label);
                }
            }
        }
        "back" => window.invoke_back(),
        "exit" => {
            if window.get_showing_settings()
                || window.get_showing_editor()
                || window.get_showing_add_game()
            {
                window.invoke_back();
            } else if window.get_search_query().is_empty() {
                window.invoke_close_window();
            } else {
                window.set_search_query("".into());
                window.invoke_search_changed("".into());
            }
        }
        "tray" => window.invoke_to_tray(),
        _ => (),
    }
}

#[cfg(test)]
#[path = "slint_ui_tests.rs"]
mod tests;

fn set_categories(window: &ListWindow, library: &Library, categories: &[String]) {
    window.set_primary_category(library.primary_category().unwrap_or_default().into());
    let names = std::iter::once("Todos").chain(categories.iter().map(String::as_str));
    let icons = std::iter::once("")
        .chain(categories.iter().map(String::as_str))
        .map(|name| {
            library
                .category_icon_path(name)
                .and_then(|path| Image::load_from_path(&path).ok())
                .unwrap_or_default()
        })
        .collect::<Vec<_>>();
    window.set_category_icons(ModelRc::new(VecModel::from(icons)));
    window.set_categories(ModelRc::new(VecModel::from(
        names.map(Into::into).collect::<Vec<_>>(),
    )));
}

fn set_filtered_games(
    window: &ListWindow,
    games: &[Game],
    _categories: &[String],
    activities: &HashMap<String, (String, String)>,
    filters: &Rc<RefCell<(String, String)>>,
    visible: &Rc<RefCell<Vec<Game>>>,
) {
    let previous_model = window.get_games();
    let previous_rows = window
        .get_visible_game_indices()
        .iter()
        .filter_map(|index| previous_model.row_data(index as usize))
        .map(|row| (row.id.to_string(), row))
        .collect::<HashMap<_, _>>();
    let previous = previous_model
        .row_data(window.get_selected_index().max(0) as usize)
        .map(|game| game.id);
    let (query, category) = filters.borrow().clone();
    let query = super::normalize_search(query.trim());
    let selected = games
        .iter()
        .filter(|game| {
            (category.is_empty() || game.categories().contains(&category))
                && (query.is_empty()
                    || super::normalize_search(&format!(
                        "{} {}",
                        game.title(),
                        metadata_text(game.metadata(), "title")
                    ))
                    .contains(&query))
        })
        .cloned()
        .collect::<Vec<_>>();
    let selected_index = previous
        .as_ref()
        .and_then(|id| selected.iter().position(|game| game.id() == id.as_str()))
        .unwrap_or(0);
    let letters = selected
        .iter()
        .map(|game| super::title_initial(game.title()).to_string())
        .collect::<std::collections::BTreeSet<_>>();
    window.set_letters(ModelRc::new(VecModel::from(
        letters
            .into_iter()
            .map(Into::into)
            .collect::<Vec<slint::SharedString>>(),
    )));
    window.set_category_index(
        _categories
            .iter()
            .position(|value| value == &category)
            .map_or(0, |index| index as i32 + 1),
    );
    let rows = selected
        .iter()
        .enumerate()
        .map(|(index, game)| {
            let mut row = game_row(
                game,
                activities
                    .get(game.id())
                    .map(|activity| (activity.0.as_str(), activity.1.as_str()))
                    .unwrap_or(("", "")),
            );
            if let Some(previous) = previous_rows.get(row.id.as_str())
                && previous.logo_path == row.logo_path
                && previous.square_cover_path == row.square_cover_path
                && previous.cover_path == row.cover_path
            {
                row.list_is_logo = previous.list_is_logo;
                row.list_image = previous.list_image.clone();
                row.cover_image = previous.cover_image.clone();
                row.square_cover_image = previous.square_cover_image.clone();
            }
            row.source_index = index as i32;
            row
        })
        .collect::<Vec<_>>();
    visible.replace(selected);
    window.set_suspend_selection_updates(true);
    window.set_visible_game_indices(ModelRc::new(VecModel::from(Vec::<i32>::new())));
    window.set_games(ModelRc::new(VecModel::from(rows)));
    window.set_selected_index(selected_index as i32);
    window.set_suspend_selection_updates(false);
    window.invoke_selection_changed(selected_index as i32);
    sync_letter_index(window, &visible.borrow());
}

fn game_row(game: &Game, activity: (&str, &str)) -> GameRow {
    let metadata = game.metadata();
    let genre_tags = metadata
        .get("genres")
        .and_then(Value::as_array)
        .map(|genres| {
            genres
                .iter()
                .filter_map(Value::as_str)
                .filter(|genre| !genre.is_empty())
                .map(Into::into)
                .collect::<Vec<slint::SharedString>>()
        })
        .or_else(|| {
            metadata
                .get("genres")
                .and_then(Value::as_str)
                .filter(|genre| !genre.is_empty())
                .map(|genre| vec![genre.into()])
        })
        .unwrap_or_default();
    let mut details = Vec::new();
    for (label, key) in [
        ("Estudio", "developers"),
        ("Editora", "publishers"),
        ("Plataformas", "platforms"),
        ("Lanzamiento", "release_date"),
    ] {
        let value = metadata_text(metadata, key);
        if !value.is_empty() {
            details.push(format!("{label}: {value}"));
        }
    }
    GameRow {
        source_index: 0,
        id: game.id().into(),
        title: game
            .metadata()
            .get("title")
            .and_then(Value::as_str)
            .filter(|title| !title.is_empty())
            .unwrap_or_else(|| game.title())
            .into(),
        launcher: game.field("kind").unwrap_or_default().into(),
        path: game.field("path").unwrap_or_default().into(),
        arguments: game.field("arguments").unwrap_or_default().into(),
        cwd: game.field("cwd").unwrap_or_default().into(),
        cover_path: game.field("cover").unwrap_or_default().into(),
        square_cover_path: game
            .field("square_cover")
            .or_else(|| game.field("squareCover"))
            .unwrap_or_default()
            .into(),
        logo_path: game.field("logo").unwrap_or_default().into(),
        banner_path: game.field("banner").unwrap_or_default().into(),
        secondary_background_path: game
            .field("banner_secondary")
            .or_else(|| game.field("secondary"))
            .unwrap_or_default()
            .into(),
        subtitle: game.categories().join(" · ").into(),
        categories: game.categories().join(", ").into(),
        description: metadata
            .get("synopsis")
            .and_then(Value::as_str)
            .filter(|value| !value.is_empty())
            .or_else(|| {
                metadata
                    .get("description")
                    .and_then(Value::as_str)
                    .filter(|value| !value.is_empty())
            })
            .unwrap_or_default()
            .into(),
        synopsis: game
            .field("synopsis")
            .or_else(|| metadata.get("synopsis").and_then(Value::as_str))
            .unwrap_or_default()
            .into(),
        genre_tags: ModelRc::new(VecModel::from(genre_tags)),
        release_date: metadata_text(metadata, "release_date").into(),
        developers: metadata_text(metadata, "developers").into(),
        publishers: metadata_text(metadata, "publishers").into(),
        genres: metadata_text(metadata, "genres").into(),
        platforms: metadata_text(metadata, "platforms").into(),
        metadata_source: metadata_text(metadata, "source").into(),
        metadata_entity_id: metadata_text(metadata, "entity_id").into(),
        steam_appid: metadata_text(metadata, "steam_appid").into(),
        activity: activity.0.into(),
        activity_history: activity.1.into(),
        details: details.join("\n").into(),
        cover_image: Image::default(),
        square_cover_image: Image::default(),
        list_image: Image::default(),
        list_is_logo: false,
    }
}

fn start_row_image_worker(window: &ListWindow) -> (Arc<AtomicU64>, PendingRowImageRequest) {
    let generation = Arc::new(AtomicU64::new(0));
    let pending = Arc::new((Mutex::new(None::<RowImageRequest>), Condvar::new()));
    let generation_for_worker = generation.clone();
    let pending_for_worker = pending.clone();
    let weak = window.as_weak();
    thread::spawn(move || {
        let mut cache = HashMap::new();
        let mut order = std::collections::VecDeque::new();
        let mut cache_bytes = 0usize;
        loop {
            let request = {
                let (latest, ready) = &*pending_for_worker;
                let mut latest = latest.lock().unwrap();
                while latest.is_none() {
                    latest = ready.wait(latest).unwrap();
                }
                latest.take().unwrap()
            };
            if generation_for_worker.load(Ordering::Acquire) != request.generation {
                continue;
            }
            let (list_max_width, list_max_height) =
                (request.list_max_width, request.list_max_height);
            let (cover_max_width, cover_max_height) =
                (request.cover_max_width, request.cover_max_height);
            let list_artwork = request.list_artwork.as_str();
            let mut output = Vec::with_capacity(request.rows.len());
            for input in request.rows {
                if generation_for_worker.load(Ordering::Acquire) != request.generation {
                    break;
                }
                let logo = Path::new(&input.logo_path)
                    .is_file()
                    .then_some(input.logo_path.as_str());
                let square = Path::new(&input.square_cover_path)
                    .is_file()
                    .then_some(input.square_cover_path.as_str());
                let portrait = Path::new(&input.cover_path)
                    .is_file()
                    .then_some(input.cover_path.as_str());
                let list_image_path = input
                    .load_list_image
                    .then(|| match list_artwork {
                        "portrait" => portrait.or(square).or(logo),
                        "square" => square.or(portrait).or(logo),
                        _ => logo.or(square).or(portrait),
                    })
                    .flatten()
                    .map(str::to_owned);
                let list_is_logo =
                    logo.is_some_and(|logo| list_image_path.as_deref() == Some(logo));
                let load_covers = input.selected || input.load_grid_covers;
                let cover_image_path = if load_covers {
                    portrait.or(square).map(str::to_owned)
                } else {
                    None
                };
                let square_cover_image_path = if load_covers {
                    square.or(portrait).map(str::to_owned)
                } else {
                    None
                };
                let logo_image_path = if input.selected {
                    logo.map(str::to_owned)
                } else {
                    None
                };
                output.push(RowImageOutput {
                    list_is_logo,
                    list_image: if input.load_list_image {
                        row_image_pixels(
                            list_image_path.as_deref(),
                            list_max_width,
                            list_max_height,
                            list_is_logo,
                            &mut cache,
                            &mut order,
                            &mut cache_bytes,
                        )
                    } else {
                        None
                    },
                    cover_image: row_image_pixels(
                        cover_image_path.as_deref(),
                        cover_max_width,
                        cover_max_height,
                        false,
                        &mut cache,
                        &mut order,
                        &mut cache_bytes,
                    ),
                    square_cover_image: row_image_pixels(
                        square_cover_image_path.as_deref(),
                        cover_max_width,
                        cover_max_height,
                        false,
                        &mut cache,
                        &mut order,
                        &mut cache_bytes,
                    ),
                    logo_image: row_image_pixels(
                        logo_image_path.as_deref(),
                        // The detail logo is displayed much larger than a carousel thumbnail.
                        cover_max_width.saturating_mul(2),
                        cover_max_height.saturating_mul(2),
                        true,
                        &mut cache,
                        &mut order,
                        &mut cache_bytes,
                    ),
                    list_image_path,
                    cover_image_path,
                    square_cover_image_path,
                    logo_image_path,
                    input,
                });
            }
            if generation_for_worker.load(Ordering::Acquire) != request.generation {
                continue;
            }
            let generation = generation_for_worker.clone();
            let request_generation = request.generation;
            if weak
                .upgrade_in_event_loop(move |window| {
                    if generation.load(Ordering::Acquire) != request_generation {
                        return;
                    }
                    let model = window.get_games();
                    let Some(rows) = model.as_any().downcast_ref::<VecModel<GameRow>>() else {
                        return;
                    };
                    for result in output {
                        let RowImageOutput {
                            input,
                            list_is_logo,
                            list_image_path,
                            cover_image_path,
                            square_cover_image_path,
                            logo_image_path,
                            list_image,
                            cover_image,
                            square_cover_image,
                            logo_image,
                        } = result;
                        let Some(mut row) = rows.row_data(input.index) else {
                            continue;
                        };
                        if row.id.as_str() != input.id.as_str()
                            || row.logo_path.as_str() != input.logo_path.as_str()
                            || row.square_cover_path.as_str() != input.square_cover_path.as_str()
                            || row.cover_path.as_str() != input.cover_path.as_str()
                        {
                            continue;
                        }
                        row.list_is_logo = list_is_logo;
                        row.list_image = slint_row_image(list_image, list_image_path.as_deref());
                        row.cover_image = slint_row_image(cover_image, cover_image_path.as_deref());
                        row.square_cover_image =
                            slint_row_image(square_cover_image, square_cover_image_path.as_deref());
                        let selected_logo = slint_row_image(logo_image, logo_image_path.as_deref());
                        if window.get_session_id().as_str() == row.id.as_str() {
                            window.set_session_cover(if row.cover_image.size().width > 0 {
                                row.cover_image.clone()
                            } else {
                                row.square_cover_image.clone()
                            });
                        }
                        if input.selected {
                            window.set_selected_cover_portrait(row.cover_image.clone());
                            window.set_selected_cover_square(row.square_cover_image.clone());
                            window.set_selected_cover_logo(selected_logo.clone());
                            let selected_image = match window.get_cover_format().as_str() {
                                "logo" if selected_logo.size().width > 0 => selected_logo,
                                "square" if row.square_cover_image.size().width > 0 => {
                                    row.square_cover_image.clone()
                                }
                                _ => row.cover_image.clone(),
                            };
                            window.set_selected_cover(selected_image);
                        }
                        rows.set_row_data(input.index, row);
                    }
                })
                .is_err()
            {
                break;
            }
        }
    });
    (generation, pending)
}

const ROW_IMAGE_CACHE_LIMIT_BYTES: usize = 64 * 1024 * 1024;
const ROW_IMAGE_MAX_WIDTH: u32 = 2560;
const ROW_IMAGE_MAX_HEIGHT: u32 = 1440;

fn row_image_pixels(
    path: Option<&str>,
    max_width: u32,
    max_height: u32,
    trim_logo: bool,
    cache: &mut HashMap<(String, u128, u64, u32, u32, bool), Arc<RowImagePixels>>,
    order: &mut std::collections::VecDeque<(String, u128, u64, u32, u32, bool)>,
    cache_bytes: &mut usize,
) -> Option<Arc<RowImagePixels>> {
    let path = path.map(clean_image_path)?;
    let max_width = max_width.clamp(1, ROW_IMAGE_MAX_WIDTH);
    let max_height = max_height.clamp(1, ROW_IMAGE_MAX_HEIGHT);
    let metadata = std::fs::metadata(Path::new(&path)).ok()?;
    let modified = metadata
        .modified()
        .ok()
        .and_then(|time| time.duration_since(std::time::UNIX_EPOCH).ok())
        .map_or(0, |time| time.as_nanos());
    let key = (
        path.to_owned(),
        modified,
        metadata.len(),
        max_width,
        max_height,
        trim_logo,
    );
    if let Some(pixels) = cache.get(&key) {
        return Some(pixels.clone());
    }
    let path = Path::new(path);
    // shortcut: 8-bit TIFF blocks up to 64 MiB stream; extend other layouts when needed.
    let (decode_width, decode_height) = if trim_logo {
        (ROW_IMAGE_MAX_WIDTH, ROW_IMAGE_MAX_HEIGHT)
    } else {
        (max_width, max_height)
    };
    let pixels = if let Some(decoded) = decode_scaled_jpeg(path, decode_width, decode_height) {
        row_image_from_raster(decoded, max_width, max_height, trim_logo)
    } else if let Some(decoded) = decode_scaled_png(path, decode_width, decode_height) {
        row_image_from_raster(decoded, max_width, max_height, trim_logo)
    } else if let Some(decoded) = decode_scaled_tiff(path, decode_width, decode_height) {
        row_image_from_raster(decoded, max_width, max_height, trim_logo)
    } else if let Ok(decoded) = decode_raster_image(path) {
        row_image_from_raster(decoded, max_width, max_height, trim_logo)
    } else {
        let (svg_max_width, svg_max_height) = if trim_logo {
            (ROW_IMAGE_MAX_WIDTH, ROW_IMAGE_MAX_HEIGHT)
        } else {
            (max_width, max_height)
        };
        row_image_from_raster(
            image::DynamicImage::ImageRgba8(rasterize_svg(path, svg_max_width, svg_max_height)?),
            max_width,
            max_height,
            trim_logo,
        )
    };
    if pixels.cache_bytes <= ROW_IMAGE_CACHE_LIMIT_BYTES {
        while cache_bytes.saturating_add(pixels.cache_bytes) > ROW_IMAGE_CACHE_LIMIT_BYTES {
            let Some(oldest) = order.pop_front() else {
                break;
            };
            if let Some(old) = cache.remove(&oldest) {
                *cache_bytes = cache_bytes.saturating_sub(old.cache_bytes);
            }
        }
        *cache_bytes += pixels.cache_bytes;
        order.push_back(key.clone());
        cache.insert(key, pixels.clone());
    }
    Some(pixels)
}

thread_local! {
    static SVG_OPTIONS: RefCell<resvg::usvg::Options<'static>> = {
        let mut options = resvg::usvg::Options::default();
        options.fontdb_mut().load_system_fonts();
        // Qt's SVG renderer uses sRGB for filter primitives, even when SVG requests linearRGB.
        options.style_sheet = Some("* { color-interpolation-filters: sRGB !important; }".into());
        RefCell::new(options)
    };
}

fn rasterize_svg(path: &Path, max_width: u32, max_height: u32) -> Option<image::RgbaImage> {
    let data = std::fs::read(path).ok()?;
    let tree = SVG_OPTIONS.with(|options| {
        let mut options = options.borrow_mut();
        options.resources_dir = path.parent().map(Path::to_path_buf);
        resvg::usvg::Tree::from_data(&data, &options).ok()
    })?;
    let (max_width, max_height) = (max_width.max(1), max_height.max(1));
    let size = tree.size();
    let scale = (max_width as f32 / size.width())
        .min(max_height as f32 / size.height())
        .min(1.0);
    let width = (size.width() * scale).round().clamp(1.0, max_width as f32) as u32;
    let height = (size.height() * scale)
        .round()
        .clamp(1.0, max_height as f32) as u32;
    let mut pixmap = resvg::tiny_skia::Pixmap::new(width, height)?;
    resvg::render(
        &tree,
        resvg::tiny_skia::Transform::from_scale(scale, scale),
        &mut pixmap.as_mut(),
    );
    image::RgbaImage::from_raw(width, height, pixmap.take_demultiplied())
}

fn row_image_from_raster(
    decoded: image::DynamicImage,
    max_width: u32,
    max_height: u32,
    trim_logo: bool,
) -> Arc<RowImagePixels> {
    let (first_width, first_height) = if trim_logo {
        (ROW_IMAGE_MAX_WIDTH, ROW_IMAGE_MAX_HEIGHT)
    } else {
        (max_width, max_height)
    };
    let mut pixels = scale_dynamic_raster(decoded, first_width, first_height);
    if trim_logo {
        pixels = trim_transparent_logo_canvas(pixels);
        pixels = scale_row_raster(pixels, max_width, max_height);
    }
    let (width, height) = pixels.dimensions();
    let rgba = pixels.into_raw();
    Arc::new(RowImagePixels {
        width,
        height,
        cache_bytes: rgba.len(),
        rgba,
    })
}

fn scale_row_raster(image: image::RgbaImage, max_width: u32, max_height: u32) -> image::RgbaImage {
    let (source_width, source_height) = image.dimensions();
    let max_width = max_width.max(1);
    let max_height = max_height.max(1);
    if source_width <= max_width && source_height <= max_height {
        return image;
    }
    scale_raster_pixels(
        source_width,
        source_height,
        max_width,
        max_height,
        |x, y| *image.get_pixel(x, y),
    )
}

fn scale_dynamic_raster(
    image: image::DynamicImage,
    max_width: u32,
    max_height: u32,
) -> image::RgbaImage {
    use image::GenericImageView;

    let (source_width, source_height) = image.dimensions();
    let max_width = max_width.max(1);
    let max_height = max_height.max(1);
    if source_width <= max_width && source_height <= max_height {
        return image.into_rgba8();
    }
    match image {
        image::DynamicImage::ImageRgba8(image) => scale_row_raster(image, max_width, max_height),
        image => scale_raster_pixels(
            source_width,
            source_height,
            max_width,
            max_height,
            |x, y| image.get_pixel(x, y),
        ),
    }
}

fn scale_raster_pixels(
    source_width: u32,
    source_height: u32,
    max_width: u32,
    max_height: u32,
    mut pixel_at: impl FnMut(u32, u32) -> image::Rgba<u8>,
) -> image::RgbaImage {
    let scale = (max_width as f64 / source_width as f64)
        .min(max_height as f64 / source_height as f64)
        .min(1.0);
    let width = (source_width as f64 * scale)
        .round()
        .clamp(1.0, max_width as f64) as u32;
    let height = (source_height as f64 * scale)
        .round()
        .clamp(1.0, max_height as f64) as u32;
    let step_x = source_width as f64 / width as f64;
    let step_y = source_height as f64 / height as f64;
    let mut scaled = image::RgbaImage::new(width, height);
    for y in 0..height {
        let y0 = y as f64 * step_y;
        let y1 = (y + 1) as f64 * step_y;
        for x in 0..width {
            let x0 = x as f64 * step_x;
            let x1 = (x + 1) as f64 * step_x;
            let mut premultiplied = [0.0; 3];
            let mut alpha = 0.0;
            for source_y in y0.floor() as u32..(y1.ceil() as u32).min(source_height) {
                let weight_y = (y1.min(source_y as f64 + 1.0) - y0.max(source_y as f64)).max(0.0);
                for source_x in x0.floor() as u32..(x1.ceil() as u32).min(source_width) {
                    let weight_x =
                        (x1.min(source_x as f64 + 1.0) - x0.max(source_x as f64)).max(0.0);
                    let weight = weight_x * weight_y;
                    let pixel = pixel_at(source_x, source_y);
                    let opacity = f64::from(pixel[3]) / 255.0;
                    alpha += opacity * weight;
                    for channel in 0..3 {
                        premultiplied[channel] += f64::from(pixel[channel]) * opacity * weight;
                    }
                }
            }
            let area = (x1 - x0) * (y1 - y0);
            let output_alpha = (alpha * 255.0 / area).round().clamp(0.0, 255.0) as u8;
            let mut pixel = [0; 4];
            for channel in 0..3 {
                pixel[channel] = if alpha > 0.0 {
                    (premultiplied[channel] / alpha).round().clamp(0.0, 255.0) as u8
                } else {
                    0
                };
            }
            pixel[3] = output_alpha;
            scaled.put_pixel(x, y, image::Rgba(pixel));
        }
    }
    scaled
}

fn trim_transparent_logo_canvas(image: image::RgbaImage) -> image::RgbaImage {
    let (width, height) = image.dimensions();
    let (mut left, mut right, mut top, mut bottom) = (width, 0, height, 0);
    for (x, y, pixel) in image.enumerate_pixels() {
        if pixel[3] != 0 {
            left = left.min(x);
            right = right.max(x + 1);
            top = top.min(y);
            bottom = bottom.max(y + 1);
        }
    }
    if right > left && bottom > top {
        image::imageops::crop_imm(&image, left, top, right - left, bottom - top).to_image()
    } else {
        image
    }
}

fn slint_row_image(pixels: Option<Arc<RowImagePixels>>, path: Option<&str>) -> Image {
    if let Some(pixels) = pixels {
        row_pixels_to_image(&pixels)
    } else {
        image(path)
    }
}

fn row_pixels_to_image(pixels: &RowImagePixels) -> Image {
    Image::from_rgba8(SharedPixelBuffer::clone_from_slice(
        &pixels.rgba,
        pixels.width,
        pixels.height,
    ))
}

fn row_image_bounds(window: &ListWindow) -> (u32, u32, u32, u32) {
    let scale = window.window().scale_factor().max(1.0);
    let size = window.window().size().to_logical(scale);
    let (width, height) = (size.width, size.height);
    let body_height = (height - 192.0).max(200.0);
    let side = matches!(window.get_list_side().as_str(), "left" | "right");
    let artwork_scale = window.get_list_artwork_scale() as f32 / 100.0;
    let focus_zoom = window.get_focus_zoom() as f32 / 100.0;
    let cover_zoom = window.get_cover_zoom() as f32 / 100.0;
    let carousel_width = if side {
        width * 0.35
    } else {
        (width - 40.0).min(2200.0).max(1.0)
    };
    let carousel_height = if side {
        body_height
    } else {
        (body_height * 0.48 - 24.0).max(80.0)
    };
    let list_width = if side {
        (carousel_width * 0.72).min(360.0 * artwork_scale * focus_zoom)
    } else {
        carousel_width.min(300.0 * artwork_scale * focus_zoom)
    };
    let list_height = if side {
        let horizontal_carousel_height = (body_height * 0.48 - 24.0).max(80.0);
        carousel_height.min(
            (horizontal_carousel_height - 16.0)
                .max(1.0)
                .min(horizontal_carousel_height * 0.72),
        )
    } else {
        carousel_height * 0.72
    };
    let hero_width = if side {
        880.0_f32.min(width * 0.65 - 48.0).max(1.0)
    } else {
        1100.0_f32.min(width - 64.0).max(1.0)
    };
    let hero_height = if side {
        body_height
    } else {
        (body_height * 0.65 - 32.0).max(1.0)
    };
    let cover_width = (260.0 * cover_zoom).min(hero_width * if side { 0.65 } else { 0.28 });
    let cover_height = if side {
        (body_height * 0.52).min(cover_width * 1.5 + 16.0)
    } else {
        514.0_f32.min(hero_height)
    };
    let list_pixels = |logical: f32| (logical.max(1.0) * scale * 2.0).ceil().max(1.0) as u32;
    let cover_pixels = |logical: f32| (logical.max(1.0) * scale).ceil().max(1.0) as u32;
    (
        list_pixels(list_width),
        list_pixels(list_height),
        cover_pixels(cover_width),
        cover_pixels(cover_height),
    )
}

fn update_row_images(
    window: &ListWindow,
    loaded: &mut std::collections::HashSet<usize>,
    generation: &AtomicU64,
    pending: &PendingRowImageRequest,
) {
    let model = window.get_games();
    let Some(rows) = model.as_any().downcast_ref::<VecModel<GameRow>>() else {
        return;
    };
    let count = rows.row_count();
    let request_generation = generation.fetch_add(1, Ordering::AcqRel).wrapping_add(1);
    if count == 0 {
        loaded.clear();
        window.set_visible_game_indices(ModelRc::new(VecModel::from(Vec::<i32>::new())));
        *pending.0.lock().unwrap() = None;
        return;
    }

    let selected = (window.get_selected_index().max(0) as usize).min(count - 1);
    let radius = (window.get_visible_image_radius().max(0) as usize).min(count / 2);
    let grid = window.get_library_layout().as_str() == "grid";
    let indices = if grid {
        let page_size = window.get_grid_page_size().max(1) as usize;
        let start = selected / page_size * page_size;
        (start..(start + page_size).min(count))
            .map(|index| index as i32)
            .collect()
    } else {
        visible_carousel_indices(selected, count, radius)
    };
    window.set_visible_game_indices(ModelRc::new(VecModel::from(indices.clone())));
    let desired = indices
        .into_iter()
        .map(|index| index as usize)
        .collect::<std::collections::HashSet<_>>();

    for index in loaded.difference(&desired).copied().collect::<Vec<_>>() {
        if let Some(mut row) = rows.row_data(index) {
            row.cover_image = Image::default();
            row.square_cover_image = Image::default();
            row.list_image = Image::default();
            rows.set_row_data(index, row);
        }
    }
    let inputs = desired
        .iter()
        .filter_map(|index| {
            let mut row = rows.row_data(*index)?;
            let load_grid_covers = grid;
            let load_list_image = !grid;
            if !load_list_image {
                row.list_image = Image::default();
            }
            if *index != selected && !load_grid_covers {
                row.cover_image = Image::default();
                row.square_cover_image = Image::default();
            }
            let input = RowImageInput {
                index: *index,
                id: row.id.to_string(),
                logo_path: row.logo_path.to_string(),
                square_cover_path: row.square_cover_path.to_string(),
                cover_path: row.cover_path.to_string(),
                selected: *index == selected,
                load_grid_covers,
                load_list_image,
            };
            rows.set_row_data(*index, row);
            Some(input)
        })
        .collect();
    let (list_max_width, list_max_height, cover_max_width, cover_max_height) =
        row_image_bounds(window);
    *loaded = desired;
    *pending.0.lock().unwrap() = Some(RowImageRequest {
        generation: request_generation,
        list_max_width,
        list_max_height,
        cover_max_width,
        cover_max_height,
        list_artwork: window.get_list_artwork().to_string(),
        rows: inputs,
    });
    pending.1.notify_one();
}

fn visible_carousel_indices(selected: usize, count: usize, radius: usize) -> Vec<i32> {
    if count == 0 {
        return Vec::new();
    }
    let count = count as isize;
    let selected = selected.min(count as usize - 1) as isize;
    let radius = radius.min(count as usize / 2) as isize;
    let mut indices = (-(radius)..=radius)
        .map(|offset| (selected + offset).rem_euclid(count) as i32)
        .collect::<std::collections::HashSet<_>>()
        .into_iter()
        .collect::<Vec<_>>();
    // Preserve the repeater's original source-index paint order for overlapping rows.
    indices.sort_unstable();
    indices
}

fn sync_letter_index(window: &ListWindow, games: &[Game]) {
    let initial = games
        .get(window.get_selected_index().max(0) as usize)
        .map(|game| super::title_initial(game.title()).to_string())
        .unwrap_or_default();
    let index = window
        .get_letters()
        .iter()
        .position(|letter| letter.as_str() == initial)
        .unwrap_or(0);
    window.set_letter_index(index as i32);
}

fn populate_editor(window: &ListWindow, game: &Game) {
    let row = game_row(game, ("", ""));
    window.set_artwork_game_id("".into());
    window.set_edit_id(row.id);
    window.set_edit_is_local(game.kind() == "local");
    window.set_edit_title(row.title.clone());
    window.set_artwork_query(row.title);
    window.set_edit_description(metadata_text(game.metadata(), "description").into());
    window.set_edit_synopsis(metadata_text(game.metadata(), "synopsis").into());
    let selected_categories = comma_values(&row.categories);
    window.set_edit_categories(selected_categories.join(", ").into());
    window.set_edit_category_choices(ModelRc::new(VecModel::from(
        window
            .get_categories()
            .iter()
            .skip(1)
            .map(|name| EditCategory {
                checked: selected_categories
                    .iter()
                    .any(|selected| selected == name.as_str()),
                name,
            })
            .collect::<Vec<_>>(),
    )));
    window.set_edit_release_date(row.release_date);
    window.set_edit_developers(row.developers);
    window.set_edit_publishers(row.publishers);
    window.set_edit_genres(row.genres);
    window.set_edit_platforms(row.platforms);
    window.set_edit_metadata_source(row.metadata_source);
    window.set_edit_entity_id(row.metadata_entity_id);
    window.set_edit_steam_appid(row.steam_appid);
    window.set_edit_path(row.path);
    window.set_edit_arguments(row.arguments);
    window.set_edit_cwd(row.cwd);
    window.set_edit_cover(row.cover_path);
    window.set_edit_square_cover(row.square_cover_path);
    window.set_edit_logo(row.logo_path);
    window.set_edit_banner(row.banner_path);
    window.set_edit_secondary_background(row.secondary_background_path);
}

fn comma_values(text: &str) -> Vec<String> {
    let mut values = Vec::new();
    for part in text
        .split(',')
        .map(str::trim)
        .filter(|part| !part.is_empty())
    {
        if !values.iter().any(|value| value == part) {
            values.push(part.to_owned());
        }
    }
    values
}

fn metadata_draft(game: &Game) -> Map<String, Value> {
    let mut draft = Map::new();
    for key in [
        "title",
        "description",
        "synopsis",
        "release_date",
        "source",
        "entity_id",
        "steam_appid",
    ] {
        let mut text = metadata_text(game.metadata(), key);
        if key == "title" && text.is_empty() {
            text = game.title().to_owned();
        }
        draft.insert(key.into(), json!(text.trim()));
    }
    for key in ["developers", "publishers", "genres", "platforms"] {
        draft.insert(
            key.into(),
            json!(comma_values(&metadata_text(game.metadata(), key))),
        );
    }
    draft
}

fn edited_game(
    window: &ListWindow,
    original: &Game,
    current: &Game,
) -> Result<Map<String, Value>, String> {
    let before = metadata_draft(original);
    let latest = metadata_draft(current);
    let mut edited = Map::new();
    for (key, value) in [
        ("title", window.get_edit_title()),
        ("description", window.get_edit_description()),
        ("synopsis", window.get_edit_synopsis()),
        ("release_date", window.get_edit_release_date()),
        ("source", window.get_edit_metadata_source()),
        ("entity_id", window.get_edit_entity_id()),
        ("steam_appid", window.get_edit_steam_appid()),
    ] {
        edited.insert(key.into(), json!(value.trim()));
    }
    if edited["title"].as_str().unwrap_or_default().is_empty() {
        return Err("El nombre no puede estar vacío.".into());
    }
    if edited["release_date"] != before["release_date"] {
        edited.insert(
            "release_date".into(),
            json!(normalize_date(
                edited["release_date"].as_str().unwrap_or_default()
            )?),
        );
    }
    for (key, value) in [
        ("developers", window.get_edit_developers()),
        ("publishers", window.get_edit_publishers()),
        ("genres", window.get_edit_genres()),
        ("platforms", window.get_edit_platforms()),
    ] {
        edited.insert(key.into(), json!(comma_values(&value)));
    }
    let mut updated = current.data().clone();
    let mut metadata = current.metadata().clone();
    for (key, value) in edited {
        if before.get(&key) != Some(&value) {
            if latest.get(&key) != before.get(&key) && latest.get(&key) != Some(&value) {
                return Err(format!(
                    "Este campo cambió mientras editabas: {key}. Cierra y vuelve a abrir la ficha."
                ));
            }
            metadata.insert(key, value);
            metadata.insert("manually_edited".into(), json!(true));
        }
    }
    updated.insert("metadata".into(), Value::Object(metadata));
    let categories = comma_values(&window.get_edit_categories());
    if categories
        .iter()
        .any(|name| name.eq_ignore_ascii_case("todos") || name.eq_ignore_ascii_case("all"))
    {
        return Err("Todos es un filtro; utiliza otro nombre de categoría.".into());
    }
    if categories != original.categories() {
        if current.categories() != original.categories() && current.categories() != categories {
            return Err(
                "Las categorías cambiaron mientras editabas. Vuelve a abrir la ficha.".into(),
            );
        }
        updated.insert("categories".into(), json!(categories));
    }
    for (key, value) in [
        ("cover", window.get_edit_cover()),
        ("square_cover", window.get_edit_square_cover()),
        ("logo", window.get_edit_logo()),
        ("banner", window.get_edit_banner()),
        ("banner_secondary", window.get_edit_secondary_background()),
    ] {
        let value = value.trim();
        if value == original.field(key).unwrap_or_default() {
            continue;
        }
        if current.field(key) != original.field(key) && current.field(key) != Some(value) {
            return Err(format!(
                "La imagen {key} cambió mientras editabas. Vuelve a abrir la ficha."
            ));
        }
        updated.insert(key.into(), json!(validate_image_path(value)?));
    }
    let execution = [
        ("path", window.get_edit_path()),
        ("arguments", window.get_edit_arguments()),
        ("cwd", window.get_edit_cwd()),
    ];
    if original.kind() == "local"
        && execution
            .iter()
            .any(|(key, value)| value.trim() != original.field(key).unwrap_or_default())
    {
        for (key, value) in &execution {
            if current.field(key) != original.field(key) && current.field(key) != Some(value.trim())
            {
                return Err(format!(
                    "La ejecución ({key}) cambió mientras editabas. Vuelve a abrir la ficha."
                ));
            }
        }
        let (path, arguments, cwd) =
            validate_local_execution(&execution[0].1, &execution[1].1, &execution[2].1)?;
        updated.insert("path".into(), json!(path));
        updated.insert("arguments".into(), json!(arguments));
        updated.insert("cwd".into(), json!(cwd));
    }
    Ok(updated)
}

fn normalize_date(value: &str) -> Result<String, String> {
    if value.is_empty() {
        return Ok(String::new());
    }
    let parts = value
        .split(['-', '/'])
        .map(str::parse::<u32>)
        .collect::<Result<Vec<_>, _>>();
    if let Ok(parts) = parts {
        if let [a, b, c] = parts.as_slice() {
            let (year, month, day) = if value.contains('/') {
                (*c, *b, *a)
            } else {
                (*a, *b, *c)
            };
            let leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
            let days = match month {
                2 => {
                    if leap {
                        29
                    } else {
                        28
                    }
                }
                4 | 6 | 9 | 11 => 30,
                1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
                _ => 0,
            };
            if (1..=9999).contains(&year) && day > 0 && day <= days {
                return Ok(format!("{year:04}-{month:02}-{day:02}"));
            }
        }
    }
    Err("Introduce una fecha válida: DD/MM/AAAA o AAAA-MM-DD.".into())
}

fn set_artwork_path(window: &ListWindow, field: &str, path: &str) {
    let value = path.into();
    match field {
        "cover" => window.set_edit_cover(value),
        "square_cover" => window.set_edit_square_cover(value),
        "logo" => window.set_edit_logo(value),
        "banner" => window.set_edit_banner(value),
        "banner_secondary" => window.set_edit_secondary_background(value),
        _ => (),
    }
}

fn validate_local_execution(
    path: &str,
    arguments: &str,
    cwd: &str,
) -> Result<(String, String, String), String> {
    let path = expand_user_path(path.trim());
    if shlex::split(arguments).is_none() {
        return Err("Los argumentos tienen comillas sin cerrar.".into());
    }
    let extension = path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    if !path.is_file() || !["sh", "appimage"].contains(&extension.as_str()) {
        return Err("Indica un archivo .sh o .AppImage existente.".into());
    }
    let cwd = if cwd.trim().is_empty() {
        path.parent()
            .unwrap_or(std::path::Path::new("."))
            .to_path_buf()
    } else {
        expand_user_path(cwd.trim())
    };
    if !cwd.is_dir() {
        return Err("El directorio de trabajo no existe.".into());
    }
    let path = path.canonicalize().map_err(|error| error.to_string())?;
    let cwd = cwd.canonicalize().map_err(|error| error.to_string())?;
    Ok((
        path.to_string_lossy().into_owned(),
        arguments.trim().into(),
        cwd.to_string_lossy().into_owned(),
    ))
}

fn validate_image_path(value: &str) -> Result<String, String> {
    if value.trim().is_empty() {
        return Ok(String::new());
    }
    let path = expand_user_path(value.trim());
    validate_image_file(&path)
        .map_err(|error| format!("No se pudo abrir la imagen {}: {error}", path.display()))?;
    path.canonicalize()
        .map(|path| path.to_string_lossy().into_owned())
        .map_err(|error| error.to_string())
}

fn expand_user_path(value: &str) -> std::path::PathBuf {
    if value == "~" || value.starts_with("~/") {
        if let Some(home) = std::env::var_os("HOME") {
            return std::path::PathBuf::from(home).join(value.strip_prefix("~/").unwrap_or(""));
        }
    }
    std::path::PathBuf::from(value)
}

fn xdg_user_dir(home: &std::path::Path, variable: &str, fallback: &str) -> Option<PathBuf> {
    let configured = std::fs::read_to_string(home.join(".config/user-dirs.dirs"))
        .ok()
        .and_then(|contents| {
            contents.lines().find_map(|line| {
                let (name, value) = line.split_once('=')?;
                (name.trim() == variable).then(|| value.trim().trim_matches('"').to_owned())
            })
        });
    if let Some(value) = configured {
        let home_text = home.to_string_lossy();
        let value = value
            .replace("${HOME}", &home_text)
            .replace("$HOME", &home_text);
        let path = expand_user_path(&value);
        if path.is_dir() {
            return Some(path);
        }
    }
    let fallback = home.join(fallback);
    fallback.is_dir().then_some(fallback)
}

fn metadata_text(metadata: &Map<String, Value>, key: &str) -> String {
    metadata
        .get(key)
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(Value::as_str)
                .collect::<Vec<_>>()
                .join(", ")
        })
        .or_else(|| metadata.get(key).and_then(Value::as_str).map(str::to_owned))
        .unwrap_or_default()
}

fn image(path: Option<&str>) -> Image {
    let Some(path) = path.map(clean_image_path) else {
        return Image::default();
    };
    let Ok(metadata) = std::fs::metadata(Path::new(&path)) else {
        return Image::default();
    };
    let modified = metadata
        .modified()
        .ok()
        .and_then(|time| time.duration_since(std::time::UNIX_EPOCH).ok())
        .map_or(0, |time| time.as_nanos());
    let cache_key = format!("{path}\0{modified}\0{}", metadata.len());
    thread_local! {
        static CACHE: RefCell<std::collections::HashMap<String, Image>> = RefCell::new(std::collections::HashMap::new());
        static ORDER: RefCell<std::collections::VecDeque<String>> = RefCell::new(std::collections::VecDeque::new());
    }
    if let Some(image) = CACHE.with(|cache| cache.borrow().get(&cache_key).cloned()) {
        return image;
    }
    if let Ok(decoded) = decode_image(std::path::Path::new(path)) {
        let pixels = decoded.thumbnail(480, 720).into_rgba8();
        let image = Image::from_rgba8(
            slint::SharedPixelBuffer::<slint::Rgba8Pixel>::clone_from_slice(
                pixels.as_raw(),
                pixels.width(),
                pixels.height(),
            ),
        );
        cache_image(&cache_key, image.clone(), &CACHE, &ORDER);
        return image;
    }
    if let Ok(image) = Image::load_from_path(std::path::Path::new(path)) {
        cache_image(&cache_key, image.clone(), &CACHE, &ORDER);
        image
    } else {
        Image::default()
    }
}

fn scan_import_provider(
    library: &mut Library,
    provider: &str,
    cancel: &AtomicBool,
) -> Result<(usize, usize), String> {
    let providers: &[&str] = match provider {
        "steam" => &["steam"],
        "faugus" => &["faugus"],
        "heroic" => &["heroic"],
        "recomp" => &["recomp"],
        "all" => &["steam", "faugus", "heroic", "recomp"],
        _ => return Err("Origen no válido.".into()),
    };
    let mut result = (0usize, 0usize);
    for source in providers {
        if cancel.load(Ordering::Acquire) {
            break;
        }
        let (added, total) = match *source {
            "steam" => library.scan_steam(),
            "faugus" => library.scan_faugus(),
            "heroic" => library.scan_heroic(),
            _ => library.scan_recomp(),
        }
        .map_err(|error| error.to_string())?;
        result.0 += added;
        result.1 += total;
    }
    if providers.contains(&"heroic") {
        let mut artwork_updates = Vec::new();
        for game in library
            .games()
            .into_iter()
            .filter(|game| game.kind() == "heroic")
        {
            if cancel.load(Ordering::Acquire) {
                break;
            }
            let Some(artwork) = game.data().get("heroic_artwork").and_then(Value::as_object) else {
                continue;
            };
            let mut updated = Map::new();
            for field in ["cover", "square_cover", "banner", "logo"] {
                if game.field(field).is_some_and(|path| !path.is_empty()) {
                    continue;
                }
                let Some(url) = artwork.get(field).and_then(Value::as_str) else {
                    continue;
                };
                if let Ok(path) = crate::artwork::download_custom(
                    url,
                    &library.data_dir().join("covers"),
                    &format!("{}-{field}", game.id()),
                    Some(cancel),
                ) {
                    updated.insert(field.to_owned(), Value::String(path));
                }
            }
            if !updated.is_empty() {
                artwork_updates.push((game.id().to_owned(), updated));
            }
        }
        if !artwork_updates.is_empty() {
            library
                .update_games(&artwork_updates)
                .map_err(|error| error.to_string())?;
        }
    }
    Ok(result)
}

fn screensaver_paths(settings: &Value, games: &[Game]) -> Vec<String> {
    if settings.get("screensaver_source").and_then(Value::as_str) == Some("application") {
        let value = settings
            .get("screensaver_background")
            .and_then(Value::as_str)
            .unwrap_or("bundled:6.png");
        let path = if let Some(file) = value.strip_prefix("bundled:") {
            let source = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../assets/backgrounds");
            let executable = std::env::current_exe().ok();
            std::env::var_os("ESTANTE_ASSET_DIR")
                .map(PathBuf::from)
                .into_iter()
                .flat_map(|path| [path.join("backgrounds"), path])
                .chain(executable.into_iter().flat_map(|path| {
                    let parent = path.parent().unwrap_or_else(|| std::path::Path::new(""));
                    [
                        parent.join("assets/backgrounds"),
                        parent.join("../share/estante/assets/backgrounds"),
                        parent.join("../share/estante/backgrounds"),
                    ]
                }))
                .chain([source.clone()])
                .map(|directory| directory.join(file))
                .find(|path| path.is_file())
                .unwrap_or_else(|| source.join(file))
                .to_string_lossy()
                .into_owned()
        } else {
            expand_user_path(clean_image_path(value))
                .to_string_lossy()
                .into_owned()
        };
        return PathBuf::from(&path)
            .is_file()
            .then_some(path)
            .into_iter()
            .collect();
    }
    let mut paths = Vec::new();
    for game in games {
        if let Some(path) = game
            .field("banner")
            .or_else(|| game.field("cover"))
            .filter(|path| PathBuf::from(path).is_file())
            && !paths.iter().any(|existing| existing == path)
        {
            paths.push(path.to_owned());
        }
    }
    paths
}

fn screensaver_slide(settings: &Value) -> Duration {
    let value = settings
        .get("screensaver_slide_value")
        .and_then(Value::as_u64)
        .unwrap_or(15)
        .max(1);
    let multiplier = if settings
        .get("screensaver_slide_unit")
        .and_then(Value::as_str)
        == Some("minutes")
    {
        60
    } else {
        1
    };
    Duration::from_secs(value.saturating_mul(multiplier))
}

fn screensaver_idle(settings: &Value) -> Duration {
    let value = settings
        .get("screensaver_idle_value")
        .and_then(Value::as_u64)
        .unwrap_or(5)
        .max(1);
    let multiplier = if settings
        .get("screensaver_idle_unit")
        .and_then(Value::as_str)
        == Some("seconds")
    {
        1
    } else {
        60
    };
    Duration::from_secs(value.saturating_mul(multiplier))
}

fn cache_image(
    path: &str,
    image: Image,
    cache: &'static std::thread::LocalKey<RefCell<std::collections::HashMap<String, Image>>>,
    order: &'static std::thread::LocalKey<RefCell<std::collections::VecDeque<String>>>,
) {
    cache.with(|cache| {
        let mut cache = cache.borrow_mut();
        if cache.len() >= 256 {
            order.with(|order| {
                if let Some(oldest) = order.borrow_mut().pop_front() {
                    cache.remove(&oldest);
                }
            });
        }
        cache.insert(path.to_owned(), image);
    });
    order.with(|order| order.borrow_mut().push_back(path.to_owned()));
}

fn decode_image(path: &std::path::Path) -> Result<image::DynamicImage, image::ImageError> {
    decode_raster_image(path).or_else(|raster_error| {
        rasterize_svg(path, ROW_IMAGE_MAX_WIDTH, ROW_IMAGE_MAX_HEIGHT)
            .map(image::DynamicImage::ImageRgba8)
            .ok_or(raster_error)
    })
}

fn validate_image_file(path: &std::path::Path) -> Result<(), image::ImageError> {
    decode_raster_image(path)
        .map(|_| ())
        .or_else(|raster_error| rasterize_svg(path, 1, 1).map(|_| ()).ok_or(raster_error))
}

fn decode_raster_image(path: &std::path::Path) -> Result<image::DynamicImage, image::ImageError> {
    if path
        .extension()
        .and_then(|extension| extension.to_str())
        .is_some_and(|extension| extension.eq_ignore_ascii_case("wbmp"))
    {
        return decode_wbmp(path);
    }
    if path
        .extension()
        .and_then(|extension| extension.to_str())
        .is_some_and(|extension| extension.eq_ignore_ascii_case("xbm"))
    {
        return decode_xbm(path);
    }
    if path
        .extension()
        .and_then(|extension| extension.to_str())
        .is_some_and(|extension| extension.eq_ignore_ascii_case("xpm"))
    {
        return decode_xpm(path);
    }
    if path
        .extension()
        .and_then(|extension| extension.to_str())
        .is_some_and(|extension| extension.eq_ignore_ascii_case("icns"))
    {
        return decode_icns(path);
    }
    let mut reader = image::ImageReader::open(path)?;
    if path
        .extension()
        .and_then(|extension| extension.to_str())
        .is_some_and(|extension| extension.eq_ignore_ascii_case("cur"))
    {
        reader.set_format(image::ImageFormat::Ico);
    } else {
        reader = reader.with_guessed_format()?;
    }
    let mut decoder = reader.into_decoder()?;
    let orientation = decoder
        .orientation()
        .unwrap_or(image::metadata::Orientation::NoTransforms);
    let mut decoded = image::DynamicImage::from_decoder(decoder)?;
    decoded.apply_orientation(orientation);
    Ok(decoded)
}

fn decode_scaled_jpeg(
    path: &std::path::Path,
    max_width: u32,
    max_height: u32,
) -> Option<image::DynamicImage> {
    use std::io::{Read, Seek, SeekFrom};

    let mut file = std::io::BufReader::new(std::fs::File::open(path).ok()?);
    let mut signature = [0; 2];
    file.read_exact(&mut signature).ok()?;
    if signature != [0xff, 0xd8] {
        return None;
    }
    file.seek(SeekFrom::Start(0)).ok()?;

    let mut decoder = jpeg_decoder::Decoder::new(file);
    decoder.read_info().ok()?;
    let info = decoder.info()?;
    if !matches!(
        info.pixel_format,
        jpeg_decoder::PixelFormat::L8 | jpeg_decoder::PixelFormat::RGB24
    ) {
        return None;
    }
    let orientation_reader = image::ImageReader::open(path)
        .ok()?
        .with_guessed_format()
        .ok()?;
    let orientation = orientation_reader
        .into_decoder()
        .ok()?
        .orientation()
        .unwrap_or(image::metadata::Orientation::NoTransforms);
    let swaps_axes = matches!(
        orientation,
        image::metadata::Orientation::Rotate90
            | image::metadata::Orientation::Rotate270
            | image::metadata::Orientation::Rotate90FlipH
            | image::metadata::Orientation::Rotate270FlipH
    );
    let (display_width, display_height) = if swaps_axes {
        (u32::from(info.height), u32::from(info.width))
    } else {
        (u32::from(info.width), u32::from(info.height))
    };
    if display_width <= max_width && display_height <= max_height {
        return None;
    }
    let (requested_width, requested_height) = if swaps_axes {
        (max_height, max_width)
    } else {
        (max_width, max_height)
    };
    let (width, height) = decoder
        .scale(
            u16::try_from(requested_width).ok()?,
            u16::try_from(requested_height).ok()?,
        )
        .ok()?;
    let pixels = decoder.decode().ok()?;
    let decoded = match decoder.info()?.pixel_format {
        jpeg_decoder::PixelFormat::L8 => {
            image::GrayImage::from_raw(u32::from(width), u32::from(height), pixels)
                .map(image::DynamicImage::ImageLuma8)
        }
        jpeg_decoder::PixelFormat::RGB24 => {
            image::RgbImage::from_raw(u32::from(width), u32::from(height), pixels)
                .map(image::DynamicImage::ImageRgb8)
        }
        _ => None,
    }?;
    let mut decoded = decoded;
    decoded.apply_orientation(orientation);
    Some(decoded)
}

fn decode_scaled_png(
    path: &std::path::Path,
    max_width: u32,
    max_height: u32,
) -> Option<image::DynamicImage> {
    use std::io::BufReader;

    let file = std::fs::File::open(path).ok()?;
    let mut signature = [0; 8];
    std::io::Read::read_exact(&mut BufReader::new(file), &mut signature).ok()?;
    if signature != [137, 80, 78, 71, 13, 10, 26, 10] {
        return None;
    }

    let mut decoder = png::Decoder::new(BufReader::new(std::fs::File::open(path).ok()?));
    decoder.set_transformations(png::Transformations::EXPAND);
    let mut reader = decoder.read_info().ok()?;
    let (source_width, source_height, interlaced) = {
        let info = reader.info();
        (info.width, info.height, info.interlaced)
    };
    let (color_type, bit_depth) = reader.output_color_type();
    if !matches!(bit_depth, png::BitDepth::Eight | png::BitDepth::Sixteen) {
        return None;
    }
    if !matches!(
        color_type,
        png::ColorType::Grayscale
            | png::ColorType::GrayscaleAlpha
            | png::ColorType::Rgb
            | png::ColorType::Rgba
    ) {
        return None;
    }

    let orientation = image::ImageReader::open(path)
        .ok()?
        .with_guessed_format()
        .ok()?
        .into_decoder()
        .ok()?
        .orientation()
        .unwrap_or(image::metadata::Orientation::NoTransforms);
    let swaps_axes = matches!(
        orientation,
        image::metadata::Orientation::Rotate90
            | image::metadata::Orientation::Rotate270
            | image::metadata::Orientation::Rotate90FlipH
            | image::metadata::Orientation::Rotate270FlipH
    );
    let (display_width, display_height) = if swaps_axes {
        (source_height, source_width)
    } else {
        (source_width, source_height)
    };
    if display_width <= max_width && display_height <= max_height {
        return None;
    }
    let (target_width, target_height) = if swaps_axes {
        (max_height, max_width)
    } else {
        (max_width, max_height)
    };
    let scale = (target_width as f64 / source_width as f64)
        .min(target_height as f64 / source_height as f64)
        .min(1.0);
    let width = (source_width as f64 * scale)
        .round()
        .clamp(1.0, target_width as f64) as u32;
    let height = (source_height as f64 * scale)
        .round()
        .clamp(1.0, target_height as f64) as u32;
    let step_x = source_width as f64 / width as f64;
    let step_y = source_height as f64 / height as f64;
    let output = if interlaced {
        let mut accumulated = area_accumulators(width, height)?;
        let passes = [
            (0, 0, 8, 8),
            (4, 0, 8, 8),
            (0, 4, 4, 8),
            (2, 0, 4, 4),
            (0, 2, 2, 4),
            (1, 0, 2, 2),
            (0, 1, 1, 2),
        ];
        for (x_offset, y_offset, x_stride, y_stride) in passes {
            let samples = source_width.saturating_sub(x_offset).div_ceil(x_stride);
            let lines = source_height.saturating_sub(y_offset).div_ceil(y_stride);
            if samples == 0 {
                continue;
            }
            for line in 0..lines {
                let row = reader.next_interlaced_row().ok()??;
                let source_y = y_offset.checked_add(line.checked_mul(y_stride)?)?;
                for sample_x in 0..samples {
                    let source_x = x_offset.checked_add(sample_x.checked_mul(x_stride)?)?;
                    let pixel =
                        png_row_pixel_for_depth(row.data(), sample_x, color_type, bit_depth)?;
                    accumulate_area_pixel(
                        &mut accumulated,
                        width,
                        height,
                        step_x,
                        step_y,
                        source_x,
                        source_y,
                        pixel,
                    )?;
                }
            }
        }
        if reader.next_interlaced_row().ok()?.is_some() {
            return None;
        }
        area_accumulators_to_image(&accumulated, width, height, step_x, step_y)?
    } else {
        let mut output = image::RgbaImage::new(width, height);
        let mut current_y = 0;
        let mut current = vec![[0.0; 4]; width as usize];
        let mut next = current.clone();

        for source_y in 0..source_height {
            let row = reader.next_row().ok()??;
            let row = row.data();
            let source_y0 = f64::from(source_y);
            let source_y1 = source_y0 + 1.0;
            let first_y = (source_y0 / step_y).floor() as u32;
            let last_y = ((source_y1 / step_y).ceil() as u32)
                .saturating_sub(1)
                .min(height - 1);
            for output_y in first_y..=last_y {
                let accumulator = if output_y == current_y {
                    &mut current
                } else if output_y == current_y + 1 {
                    &mut next
                } else {
                    return None;
                };
                let output_y0 = f64::from(output_y) * step_y;
                let output_y1 = f64::from(output_y + 1) * step_y;
                let weight_y = (output_y1.min(source_y1) - output_y0.max(source_y0)).max(0.0);
                for output_x in 0..width {
                    let output_x0 = f64::from(output_x) * step_x;
                    let output_x1 = f64::from(output_x + 1) * step_x;
                    for source_x in
                        output_x0.floor() as u32..(output_x1.ceil() as u32).min(source_width)
                    {
                        let weight_x = (output_x1.min(f64::from(source_x + 1))
                            - output_x0.max(f64::from(source_x)))
                        .max(0.0);
                        let weight = weight_x * weight_y;
                        let pixel = png_row_pixel_for_depth(row, source_x, color_type, bit_depth)?;
                        let opacity = f64::from(pixel[3]) / 255.0;
                        let accumulated = &mut accumulator[output_x as usize];
                        accumulated[3] += opacity * weight;
                        for channel in 0..3 {
                            accumulated[channel] += f64::from(pixel[channel]) * opacity * weight;
                        }
                    }
                }
            }
            while current_y < height && f64::from(current_y + 1) * step_y <= source_y1 + 1e-9 {
                let area = step_x * step_y;
                for output_x in 0..width {
                    let accumulated = current[output_x as usize];
                    let mut pixel = [0; 4];
                    pixel[3] = (accumulated[3] * 255.0 / area).round().clamp(0.0, 255.0) as u8;
                    for channel in 0..3 {
                        pixel[channel] = if accumulated[3] > 0.0 {
                            (accumulated[channel] / accumulated[3])
                                .round()
                                .clamp(0.0, 255.0) as u8
                        } else {
                            0
                        };
                    }
                    output.put_pixel(output_x, current_y, image::Rgba(pixel));
                }
                current_y += 1;
                std::mem::swap(&mut current, &mut next);
                next.fill([0.0; 4]);
            }
        }
        if current_y != height {
            return None;
        }
        output
    };
    if reader.finish().is_err() {
        return None;
    }
    let mut decoded = image::DynamicImage::ImageRgba8(output);
    decoded.apply_orientation(orientation);
    Some(decoded)
}

fn png_row_pixel(row: &[u8], x: u32, color_type: png::ColorType) -> Option<[u8; 4]> {
    let x = x as usize;
    Some(match color_type {
        png::ColorType::Grayscale => {
            let value = *row.get(x)?;
            [value, value, value, 255]
        }
        png::ColorType::GrayscaleAlpha => {
            let offset = x.checked_mul(2)?;
            let value = *row.get(offset)?;
            [value, value, value, *row.get(offset + 1)?]
        }
        png::ColorType::Rgb => {
            let offset = x.checked_mul(3)?;
            [
                *row.get(offset)?,
                *row.get(offset + 1)?,
                *row.get(offset + 2)?,
                255,
            ]
        }
        png::ColorType::Rgba => {
            let offset = x.checked_mul(4)?;
            [
                *row.get(offset)?,
                *row.get(offset + 1)?,
                *row.get(offset + 2)?,
                *row.get(offset + 3)?,
            ]
        }
        _ => return None,
    })
}

fn png_row_pixel_for_depth(
    row: &[u8],
    x: u32,
    color_type: png::ColorType,
    bit_depth: png::BitDepth,
) -> Option<[u8; 4]> {
    match bit_depth {
        png::BitDepth::Eight => png_row_pixel(row, x, color_type),
        png::BitDepth::Sixteen => {
            let channels = match color_type {
                png::ColorType::Grayscale => 1,
                png::ColorType::GrayscaleAlpha => 2,
                png::ColorType::Rgb => 3,
                png::ColorType::Rgba => 4,
                _ => return None,
            };
            let offset = (x as usize).checked_mul(channels * 2)?;
            let sample = |channel: usize| {
                let byte = offset.checked_add(channel.checked_mul(2)?)?;
                let bytes = [*row.get(byte)?, *row.get(byte + 1)?];
                Some(((u32::from(u16::from_be_bytes(bytes)) + 128) / 257) as u8)
            };
            Some(match channels {
                1 => {
                    let value = sample(0)?;
                    [value, value, value, 255]
                }
                2 => {
                    let value = sample(0)?;
                    [value, value, value, sample(1)?]
                }
                3 => [sample(0)?, sample(1)?, sample(2)?, 255],
                4 => [sample(0)?, sample(1)?, sample(2)?, sample(3)?],
                _ => return None,
            })
        }
        _ => None,
    }
}

fn area_accumulators(width: u32, height: u32) -> Option<Vec<[f64; 4]>> {
    let pixel_count = (width as usize).checked_mul(height as usize)?;
    let mut accumulated = Vec::new();
    accumulated.try_reserve_exact(pixel_count).ok()?;
    accumulated.resize(pixel_count, [0.0; 4]);
    Some(accumulated)
}

fn accumulate_area_pixel(
    accumulated: &mut [[f64; 4]],
    width: u32,
    height: u32,
    step_x: f64,
    step_y: f64,
    source_x: u32,
    source_y: u32,
    pixel: [u8; 4],
) -> Option<()> {
    let source_x0 = f64::from(source_x);
    let source_y0 = f64::from(source_y);
    let source_x1 = source_x0 + 1.0;
    let source_y1 = source_y0 + 1.0;
    let first_x = (source_x0 / step_x).floor() as u32;
    let last_x = ((source_x1 / step_x).ceil() as u32)
        .saturating_sub(1)
        .min(width - 1);
    let first_y = (source_y0 / step_y).floor() as u32;
    let last_y = ((source_y1 / step_y).ceil() as u32)
        .saturating_sub(1)
        .min(height - 1);
    let opacity = f64::from(pixel[3]) / 255.0;
    for output_y in first_y..=last_y {
        let output_y0 = f64::from(output_y) * step_y;
        let output_y1 = f64::from(output_y + 1) * step_y;
        let weight_y = (output_y1.min(source_y1) - output_y0.max(source_y0)).max(0.0);
        for output_x in first_x..=last_x {
            let output_x0 = f64::from(output_x) * step_x;
            let output_x1 = f64::from(output_x + 1) * step_x;
            let weight_x = (output_x1.min(source_x1) - output_x0.max(source_x0)).max(0.0);
            let weight = weight_x * weight_y;
            let index = (output_y as usize)
                .checked_mul(width as usize)?
                .checked_add(output_x as usize)?;
            let sums = accumulated.get_mut(index)?;
            sums[3] += opacity * weight;
            for channel in 0..3 {
                sums[channel] += f64::from(pixel[channel]) * opacity * weight;
            }
        }
    }
    Some(())
}

fn area_accumulators_to_image(
    accumulated: &[[f64; 4]],
    width: u32,
    height: u32,
    step_x: f64,
    step_y: f64,
) -> Option<image::RgbaImage> {
    let pixel_count = (width as usize).checked_mul(height as usize)?;
    if accumulated.len() != pixel_count {
        return None;
    }
    let area = step_x * step_y;
    let mut output = image::RgbaImage::new(width, height);
    for output_y in 0..height {
        for output_x in 0..width {
            let sums = accumulated[output_y as usize * width as usize + output_x as usize];
            let mut pixel = [0; 4];
            pixel[3] = (sums[3] * 255.0 / area).round().clamp(0.0, 255.0) as u8;
            for channel in 0..3 {
                pixel[channel] = if sums[3] > 0.0 {
                    (sums[channel] / sums[3]).round().clamp(0.0, 255.0) as u8
                } else {
                    0
                };
            }
            output.put_pixel(output_x, output_y, image::Rgba(pixel));
        }
    }
    Some(output)
}

fn decode_scaled_tiff(
    path: &std::path::Path,
    max_width: u32,
    max_height: u32,
) -> Option<image::DynamicImage> {
    use std::io::{BufReader, Read};

    let mut signature = [0; 4];
    BufReader::new(std::fs::File::open(path).ok()?)
        .read_exact(&mut signature)
        .ok()?;
    if ![*b"II*\0", *b"MM\0*", *b"II+\0", *b"MM\0+"].contains(&signature) {
        return None;
    }

    let mut limits = tiff::decoder::Limits::default();
    limits.decoding_buffer_size = 64 * 1024 * 1024;
    let mut decoder = tiff::decoder::Decoder::new(BufReader::new(std::fs::File::open(path).ok()?))
        .ok()?
        .with_limits(limits);
    let (source_width, source_height) = decoder.dimensions().ok()?;
    let orientation = decoder
        .find_tag_unsigned::<u16>(tiff::tags::Tag::Orientation)
        .ok()
        .flatten()
        .and_then(|value| u8::try_from(value).ok())
        .and_then(image::metadata::Orientation::from_exif)
        .unwrap_or(image::metadata::Orientation::NoTransforms);
    let (channels, bit_depth) = match decoder.colortype().ok()? {
        tiff::ColorType::Gray(bits) if matches!(bits, 8 | 16 | 32) => (1, bits),
        tiff::ColorType::GrayA(bits) if matches!(bits, 8 | 16 | 32) => (2, bits),
        tiff::ColorType::RGB(bits) if matches!(bits, 8 | 16 | 32) => (3, bits),
        tiff::ColorType::RGBA(bits) if matches!(bits, 8 | 16 | 32) => (4, bits),
        _ => return None,
    };
    let sample_type = decoder
        .image_coding_unit_layout(tiff::decoder::TiffCodingUnit(0))
        .ok()?
        .sample_type?;
    if !matches!(
        (bit_depth, sample_type),
        (8, tiff::decoder::DecodingSampleType::U8)
            | (8, tiff::decoder::DecodingSampleType::I8)
            | (16, tiff::decoder::DecodingSampleType::U16)
            | (16, tiff::decoder::DecodingSampleType::I16)
            | (16, tiff::decoder::DecodingSampleType::F16)
            | (32, tiff::decoder::DecodingSampleType::F32)
    ) {
        return None;
    }
    let chunk_type = decoder.get_chunk_type();
    let (chunk_width, chunk_height) = decoder.chunk_dimensions();
    if chunk_width == 0
        || chunk_height == 0
        || (chunk_type == tiff::decoder::ChunkType::Strip && chunk_width != source_width)
    {
        return None;
    }
    let chunks_across = source_width.div_ceil(chunk_width);
    let chunks_down = source_height.div_ceil(chunk_height);
    let spatial_chunks = chunks_across.checked_mul(chunks_down)?;
    let chunk_count = match chunk_type {
        tiff::decoder::ChunkType::Strip => decoder.strip_count().ok()?,
        tiff::decoder::ChunkType::Tile => decoder.tile_count().ok()?,
    };
    let planar_chunk_count = spatial_chunks.checked_mul(channels as u32)?;
    let planes = if chunk_count == spatial_chunks {
        1
    } else if chunk_count == planar_chunk_count {
        channels
    } else {
        return None;
    };
    let swaps_axes = matches!(
        orientation,
        image::metadata::Orientation::Rotate90
            | image::metadata::Orientation::Rotate270
            | image::metadata::Orientation::Rotate90FlipH
            | image::metadata::Orientation::Rotate270FlipH
    );
    let (display_width, display_height) = if swaps_axes {
        (source_height, source_width)
    } else {
        (source_width, source_height)
    };
    // image's TIFF decoder rejects floating-point grayscale even when no downscaling is needed.
    let requires_custom_color_conversion =
        matches!(
            sample_type,
            tiff::decoder::DecodingSampleType::I8
                | tiff::decoder::DecodingSampleType::I16
                | tiff::decoder::DecodingSampleType::F16
        ) || (sample_type == tiff::decoder::DecodingSampleType::F32 && channels <= 2);
    if display_width <= max_width
        && display_height <= max_height
        && !requires_custom_color_conversion
    {
        return None;
    }
    let (target_width, target_height) = if swaps_axes {
        (max_height, max_width)
    } else {
        (max_width, max_height)
    };
    let scale = (target_width as f64 / source_width as f64)
        .min(target_height as f64 / source_height as f64)
        .min(1.0);
    let width = (source_width as f64 * scale)
        .round()
        .clamp(1.0, target_width as f64) as u32;
    let height = (source_height as f64 * scale)
        .round()
        .clamp(1.0, target_height as f64) as u32;
    let step_x = f64::from(source_width) / f64::from(width);
    let step_y = f64::from(source_height) / f64::from(height);
    if chunk_type == tiff::decoder::ChunkType::Tile {
        let mut accumulated = area_accumulators(width, height)?;
        for tile_index in 0..spatial_chunks {
            let tile_x = (tile_index % chunks_across).checked_mul(chunk_width)?;
            let tile_y = (tile_index / chunks_across).checked_mul(chunk_height)?;
            let (tile_data_width, tile_data_height) = decoder.chunk_data_dimensions(tile_index);
            if tile_data_width != chunk_width.min(source_width - tile_x)
                || tile_data_height != chunk_height.min(source_height - tile_y)
            {
                return None;
            }
            let (chunk_pixels, layout) = read_tiff_coding_unit(
                &mut decoder,
                tile_index,
                planes,
                channels,
                sample_type,
                tile_data_width,
                tile_data_height,
            )?;
            for local_y in 0..tile_data_height {
                for local_x in 0..tile_data_width {
                    let source_x = tile_x.checked_add(local_x)?;
                    let source_y = tile_y.checked_add(local_y)?;
                    accumulate_area_pixel(
                        &mut accumulated,
                        width,
                        height,
                        step_x,
                        step_y,
                        source_x,
                        source_y,
                        tiff_coding_unit_pixel(&chunk_pixels, &layout, channels, local_x, local_y)?,
                    )?;
                }
            }
        }
        let output = area_accumulators_to_image(&accumulated, width, height, step_x, step_y)?;
        let mut decoded = image::DynamicImage::ImageRgba8(output);
        decoded.apply_orientation(orientation);
        return Some(decoded);
    }
    let strip_height = chunk_height;
    let mut output = image::RgbaImage::new(width, height);
    let mut current_y = 0;
    let mut current = vec![[0.0; 4]; width as usize];
    let mut next = current.clone();

    for chunk_index in 0..spatial_chunks {
        let (chunk_width, chunk_height) = decoder.chunk_data_dimensions(chunk_index);
        if chunk_width != source_width {
            return None;
        }
        let (chunk_pixels, layout) = read_tiff_coding_unit(
            &mut decoder,
            chunk_index,
            planes,
            channels,
            sample_type,
            chunk_width,
            chunk_height,
        )?;
        let chunk_y = chunk_index.checked_mul(strip_height)?;
        if chunk_y.checked_add(chunk_height)? > source_height {
            return None;
        }
        for local_y in 0..chunk_height {
            let source_y = chunk_y + local_y;
            let source_y0 = f64::from(source_y);
            let source_y1 = source_y0 + 1.0;
            let first_y = (source_y0 / step_y).floor() as u32;
            let last_y = ((source_y1 / step_y).ceil() as u32)
                .saturating_sub(1)
                .min(height - 1);
            for output_y in first_y..=last_y {
                let accumulator = if output_y == current_y {
                    &mut current
                } else if output_y == current_y + 1 {
                    &mut next
                } else {
                    return None;
                };
                let output_y0 = f64::from(output_y) * step_y;
                let output_y1 = f64::from(output_y + 1) * step_y;
                let weight_y = (output_y1.min(source_y1) - output_y0.max(source_y0)).max(0.0);
                for output_x in 0..width {
                    let output_x0 = f64::from(output_x) * step_x;
                    let output_x1 = f64::from(output_x + 1) * step_x;
                    for source_x in
                        output_x0.floor() as u32..(output_x1.ceil() as u32).min(source_width)
                    {
                        let weight_x = (output_x1.min(f64::from(source_x + 1))
                            - output_x0.max(f64::from(source_x)))
                        .max(0.0);
                        let weight = weight_x * weight_y;
                        let pixel = tiff_coding_unit_pixel(
                            &chunk_pixels,
                            &layout,
                            channels,
                            source_x,
                            local_y,
                        )?;
                        let opacity = f64::from(pixel[3]) / 255.0;
                        let accumulated = &mut accumulator[output_x as usize];
                        accumulated[3] += opacity * weight;
                        for channel in 0..3 {
                            accumulated[channel] += f64::from(pixel[channel]) * opacity * weight;
                        }
                    }
                }
            }
            while current_y < height && f64::from(current_y + 1) * step_y <= source_y1 + 1e-9 {
                let area = step_x * step_y;
                for output_x in 0..width {
                    let accumulated = current[output_x as usize];
                    let mut pixel = [0; 4];
                    pixel[3] = (accumulated[3] * 255.0 / area).round().clamp(0.0, 255.0) as u8;
                    for channel in 0..3 {
                        pixel[channel] = if accumulated[3] > 0.0 {
                            (accumulated[channel] / accumulated[3])
                                .round()
                                .clamp(0.0, 255.0) as u8
                        } else {
                            0
                        };
                    }
                    output.put_pixel(output_x, current_y, image::Rgba(pixel));
                }
                current_y += 1;
                std::mem::swap(&mut current, &mut next);
                next.fill([0.0; 4]);
            }
        }
    }
    if current_y != height {
        return None;
    }
    let mut decoded = image::DynamicImage::ImageRgba8(output);
    decoded.apply_orientation(orientation);
    Some(decoded)
}

fn read_tiff_coding_unit<R: std::io::Read + std::io::Seek>(
    decoder: &mut tiff::decoder::Decoder<R>,
    chunk_index: u32,
    planes: usize,
    channels: usize,
    sample_type: tiff::decoder::DecodingSampleType,
    width: u32,
    height: u32,
) -> Option<(Vec<u8>, tiff::decoder::BufferLayoutPreference)> {
    if decoder.chunk_data_dimensions(chunk_index) != (width, height) {
        return None;
    }
    let layout = decoder
        .image_coding_unit_layout(tiff::decoder::TiffCodingUnit(chunk_index))
        .ok()?;
    if layout.planes != planes
        || (planes != 1 && planes != channels)
        || layout.sample_type != Some(sample_type)
        || layout.complete_len > 64 * 1024 * 1024
    {
        return None;
    }
    let mut pixels = Vec::new();
    pixels.try_reserve_exact(layout.complete_len).ok()?;
    pixels.resize(layout.complete_len, 0);
    decoder
        .read_coding_unit_bytes(tiff::decoder::TiffCodingUnit(chunk_index), &mut pixels)
        .ok()?;
    Some((pixels, layout))
}

fn tiff_coding_unit_pixel(
    data: &[u8],
    layout: &tiff::decoder::BufferLayoutPreference,
    channels: usize,
    x: u32,
    y: u32,
) -> Option<[u8; 4]> {
    let sample_type = layout.sample_type?;
    let bytes_per_sample = match sample_type {
        tiff::decoder::DecodingSampleType::U8 | tiff::decoder::DecodingSampleType::I8 => 1,
        tiff::decoder::DecodingSampleType::U16
        | tiff::decoder::DecodingSampleType::I16
        | tiff::decoder::DecodingSampleType::F16 => 2,
        tiff::decoder::DecodingSampleType::F32 => 4,
        _ => return None,
    };
    let row_offset = (y as usize).checked_mul(layout.row_stride?.get())?;
    let mut samples = [0; 4];
    let sample_at = |offset: usize| -> Option<u8> {
        let end = offset.checked_add(bytes_per_sample)?;
        let bytes = data.get(offset..end)?;
        Some(match sample_type {
            tiff::decoder::DecodingSampleType::U8 | tiff::decoder::DecodingSampleType::I8 => {
                *bytes.first()?
            }
            tiff::decoder::DecodingSampleType::U16 | tiff::decoder::DecodingSampleType::I16 => {
                let value = u16::from_ne_bytes(bytes.try_into().ok()?);
                ((u32::from(value) + 128) / 257) as u8
            }
            tiff::decoder::DecodingSampleType::F16 => {
                (f16_to_f32(u16::from_ne_bytes(bytes.try_into().ok()?)).clamp(0.0, 1.0) * 255.0)
                    .round() as u8
            }
            tiff::decoder::DecodingSampleType::F32 => {
                (f32::from_ne_bytes(bytes.try_into().ok()?)
                    .clamp(0.0, 1.0)
                    .mul_add(255.0, 0.0)
                    .round()) as u8
            }
            _ => return None,
        })
    };
    if layout.planes == 1 {
        let start = row_offset.checked_add(
            (x as usize)
                .checked_mul(channels)?
                .checked_mul(bytes_per_sample)?,
        )?;
        for (channel, sample) in samples.iter_mut().take(channels).enumerate() {
            *sample = sample_at(start.checked_add(channel.checked_mul(bytes_per_sample)?)?)?;
        }
    } else {
        if layout.planes != channels {
            return None;
        }
        let sample_offset = row_offset.checked_add((x as usize).checked_mul(bytes_per_sample)?)?;
        let plane_stride = layout.plane_stride?.get();
        for (channel, sample) in samples.iter_mut().take(channels).enumerate() {
            let offset = channel
                .checked_mul(plane_stride)?
                .checked_add(sample_offset)?;
            *sample = sample_at(offset)?;
        }
    }
    Some(match channels {
        1 => [samples[0], samples[0], samples[0], 255],
        2 => [samples[0], samples[0], samples[0], samples[1]],
        3 => [samples[0], samples[1], samples[2], 255],
        4 => [samples[0], samples[1], samples[2], samples[3]],
        _ => return None,
    })
}

fn f16_to_f32(bits: u16) -> f32 {
    let sign = if bits & 0x8000 == 0 { 1.0 } else { -1.0 };
    let exponent = i32::from((bits >> 10) & 0x1f);
    let fraction = f32::from(bits & 0x03ff);
    match exponent {
        0 => sign * fraction * 2.0_f32.powi(-24),
        0x1f if fraction == 0.0 => sign * f32::INFINITY,
        0x1f => f32::NAN,
        _ => sign * (1.0 + fraction / 1024.0) * 2.0_f32.powi(exponent - 15),
    }
}

fn decode_wbmp(path: &std::path::Path) -> Result<image::DynamicImage, image::ImageError> {
    use std::io::{Error, ErrorKind};

    let bytes = std::fs::read(path)?;
    let invalid = || image::ImageError::IoError(Error::new(ErrorKind::InvalidData, "invalid WBMP"));
    if bytes.get(..2) != Some(&[0, 0][..]) {
        return Err(invalid());
    }
    let mut offset = 2;
    let width = read_wbmp_integer(&bytes, &mut offset).ok_or_else(invalid)?;
    let height = read_wbmp_integer(&bytes, &mut offset).ok_or_else(invalid)?;
    if width == 0 || height == 0 {
        return Err(invalid());
    }
    let row_bytes = width.checked_add(7).ok_or_else(invalid)? / 8;
    let data_bytes = (row_bytes as usize)
        .checked_mul(height as usize)
        .ok_or_else(invalid)?;
    let end = offset.checked_add(data_bytes).ok_or_else(invalid)?;
    let data = bytes.get(offset..end).ok_or_else(invalid)?;
    let rgba_bytes = (width as usize)
        .checked_mul(height as usize)
        .and_then(|pixels| pixels.checked_mul(4))
        .ok_or_else(invalid)?;
    let mut rgba = Vec::new();
    rgba.try_reserve_exact(rgba_bytes).map_err(|_| invalid())?;
    for y in 0..height as usize {
        let row = &data[y * row_bytes as usize..][..row_bytes as usize];
        for x in 0..width as usize {
            let pixel = if row[x / 8] & (0x80 >> (x % 8)) != 0 {
                [255, 255, 255, 255]
            } else {
                [0, 0, 0, 255]
            };
            rgba.extend_from_slice(&pixel);
        }
    }
    image::RgbaImage::from_raw(width, height, rgba)
        .map(image::DynamicImage::ImageRgba8)
        .ok_or_else(invalid)
}

fn read_wbmp_integer(bytes: &[u8], offset: &mut usize) -> Option<u32> {
    let mut value = 0_u32;
    for _ in 0..5 {
        let byte = *bytes.get(*offset)?;
        *offset += 1;
        value = value
            .checked_mul(128)?
            .checked_add(u32::from(byte & 0x7f))?;
        if byte & 0x80 == 0 {
            return Some(value);
        }
    }
    None
}

// shortcut: rejects a first JP2 variant to match Qt without a JP2 plugin; decode if that changes.
fn decode_icns(path: &std::path::Path) -> Result<image::DynamicImage, image::ImageError> {
    use std::io::{Error, ErrorKind};

    let bytes = std::fs::read(path)?;
    let invalid = || image::ImageError::IoError(Error::new(ErrorKind::InvalidData, "invalid ICNS"));
    let header = bytes.get(..8).ok_or_else(invalid)?;
    let end = u32::from_be_bytes(header[4..8].try_into().map_err(|_| invalid())?) as usize;
    if &header[..4] != b"icns" || end < 8 || end > bytes.len() {
        return Err(invalid());
    }
    let mut chunks = Vec::new();
    let mut containers = vec![(&bytes[8..end], 0_usize)];
    while let Some((container, offset)) = containers.last().copied() {
        if offset == container.len() {
            containers.pop();
            continue;
        }
        let header_end = offset.checked_add(8).ok_or_else(invalid)?;
        let chunk_header = container.get(offset..header_end).ok_or_else(invalid)?;
        let kind: [u8; 4] = chunk_header[..4].try_into().map_err(|_| invalid())?;
        let chunk_size =
            u32::from_be_bytes(chunk_header[4..8].try_into().map_err(|_| invalid())?) as usize;
        if chunk_size < 8 {
            return Err(invalid());
        }
        let chunk_end = offset.checked_add(chunk_size).ok_or_else(invalid)?;
        if chunk_end > container.len() {
            return Err(invalid());
        }
        let payload = &container[header_end..chunk_end];
        containers.last_mut().unwrap().1 = chunk_end;
        if matches!(&kind, b"tile" | b"over" | b"open" | b"drop" | b"odrp") {
            containers.push((payload, 0));
        } else {
            chunks.push((kind, payload));
        }
    }

    for (kind, payload) in &chunks {
        if payload.starts_with(b"\x89PNG\r\n\x1a\n") {
            let reader = image::ImageReader::with_format(
                std::io::Cursor::new(payload),
                image::ImageFormat::Png,
            );
            let mut decoder = reader.into_decoder().map_err(|_| invalid())?;
            let orientation = decoder
                .orientation()
                .unwrap_or(image::metadata::Orientation::NoTransforms);
            let mut image = image::DynamicImage::from_decoder(decoder).map_err(|_| invalid())?;
            image.apply_orientation(orientation);
            return Ok(image);
        }
        if payload.starts_with(b"\0\0\0\x0cjP  \r\n\x87\n") {
            return Err(invalid());
        }
        let (width, mask_kind, depth) = match kind {
            b"is32" => (16, *b"s8mk", 32),
            b"il32" => (32, *b"l8mk", 32),
            b"ih32" => (48, *b"h8mk", 32),
            b"it32" => (128, *b"t8mk", 32),
            b"ics4" => (16, *b"s8mk", 4),
            b"ics8" => (16, *b"s8mk", 8),
            b"icl4" => (32, *b"l8mk", 4),
            b"icl8" => (32, *b"l8mk", 8),
            b"ich4" => (48, *b"h8mk", 4),
            b"ich8" => (48, *b"h8mk", 8),
            b"ict4" => (128, *b"t8mk", 4),
            b"ict8" => (128, *b"t8mk", 8),
            b"ics#" => (16, *b"s8mk", 1),
            b"icl#" => (32, *b"l8mk", 1),
            b"ich#" => (48, *b"h8mk", 1),
            b"ict#" => (128, *b"t8mk", 1),
            _ => continue,
        };
        let external_mask = chunks
            .iter()
            .find(|(candidate, _)| *candidate == mask_kind)
            .map(|(_, data)| *data);
        let decoded = match depth {
            32 => decode_icns_rle24(payload, external_mask, width),
            1 => decode_icns_mono(payload, width),
            4 | 8 => decode_icns_palette(payload, external_mask, width, depth),
            _ => None,
        };
        if let Some(image) = decoded {
            return Ok(image);
        }
        return Err(invalid());
    }
    Err(invalid())
}

fn decode_icns_rle24(data: &[u8], alpha: Option<&[u8]>, size: u32) -> Option<image::DynamicImage> {
    let pixels = (size as usize).checked_mul(size as usize)?;
    if alpha.is_some_and(|alpha| alpha.len() < pixels) {
        return None;
    }
    let mut offset = usize::from(data.starts_with(&[0, 0, 0, 0])) * 4;
    let mut channels = Vec::with_capacity(3);
    for _ in 0..3 {
        let mut channel = Vec::with_capacity(pixels);
        while channel.len() < pixels {
            let packet = *data.get(offset)?;
            offset += 1;
            if packet < 128 {
                let count = usize::from(packet) + 1;
                let end = offset.checked_add(count)?;
                channel.extend_from_slice(data.get(offset..end)?);
                offset = end;
            } else {
                let count = usize::from(packet - 125).min(pixels - channel.len());
                let value = *data.get(offset)?;
                offset += 1;
                channel.resize(channel.len().checked_add(count)?, value);
            }
        }
        channels.push(channel);
    }
    let mut rgba = Vec::with_capacity(pixels.checked_mul(4)?);
    for index in 0..pixels {
        rgba.extend_from_slice(&[
            channels[0][index],
            channels[1][index],
            channels[2][index],
            alpha.map_or(255, |mask| mask[index]),
        ]);
    }
    image::RgbaImage::from_raw(size, size, rgba).map(image::DynamicImage::ImageRgba8)
}

fn decode_icns_palette(
    data: &[u8],
    alpha: Option<&[u8]>,
    size: u32,
    depth: u8,
) -> Option<image::DynamicImage> {
    let palette = icns_palette(depth)?;
    let pixels = (size as usize).checked_mul(size as usize)?;
    let image_bytes = pixels.checked_mul(usize::from(depth))?.checked_div(8)?;
    if data.len() < image_bytes || alpha.is_some_and(|mask| mask.len() < pixels) {
        return None;
    }
    let mut rgba = Vec::new();
    rgba.try_reserve_exact(pixels.checked_mul(4)?).ok()?;
    for index in 0..pixels {
        let color_index = match depth {
            4 if index % 2 == 0 => data[index / 2] >> 4,
            4 => data[index / 2] & 0x0f,
            8 => data[index],
            _ => return None,
        } as usize;
        let [red, green, blue] = *palette.get(color_index)?;
        rgba.extend_from_slice(&[red, green, blue, alpha.map_or(255, |mask| mask[index])]);
    }
    image::RgbaImage::from_raw(size, size, rgba).map(image::DynamicImage::ImageRgba8)
}

fn decode_icns_mono(data: &[u8], size: u32) -> Option<image::DynamicImage> {
    let pixels = (size as usize).checked_mul(size as usize)?;
    let plane_bytes = pixels.checked_add(7)?.checked_div(8)?;
    if data.len() < plane_bytes.checked_mul(2)? {
        return None;
    }
    let (bitmap, mask) = data.split_at(plane_bytes);
    let mut rgba = Vec::new();
    rgba.try_reserve_exact(pixels.checked_mul(4)?).ok()?;
    for index in 0..pixels {
        let bit = 0x80 >> (index % 8);
        let color = if bitmap[index / 8] & bit == 0 { 255 } else { 0 };
        let alpha = if mask[index / 8] & bit == 0 { 0 } else { 255 };
        rgba.extend_from_slice(&[color, color, color, alpha]);
    }
    image::RgbaImage::from_raw(size, size, rgba).map(image::DynamicImage::ImageRgba8)
}

fn icns_palette(depth: u8) -> Option<&'static [[u8; 3]]> {
    static PALETTES: std::sync::OnceLock<[Vec<[u8; 3]>; 2]> = std::sync::OnceLock::new();
    let palettes = PALETTES.get_or_init(|| {
        let mut palettes = [Vec::with_capacity(16), Vec::with_capacity(256)];
        let mut palette_index = 0;
        for line in include_str!("../ui/icns_palette.txt").lines() {
            match line {
                "[4]" => palette_index = 0,
                "[8]" => palette_index = 1,
                color if color.len() == 6 => {
                    if let Ok(color) = u32::from_str_radix(color, 16) {
                        palettes[palette_index].push([
                            (color >> 16) as u8,
                            (color >> 8) as u8,
                            color as u8,
                        ]);
                    }
                }
                _ => {}
            }
        }
        palettes
    });
    match depth {
        4 => Some(&palettes[0]),
        8 => Some(&palettes[1]),
        _ => None,
    }
}

fn decode_xbm(path: &std::path::Path) -> Result<image::DynamicImage, image::ImageError> {
    use std::io::{Error, ErrorKind};

    let source = std::fs::read_to_string(path)?;
    let source = strip_c_comments(&source);
    let invalid = || image::ImageError::IoError(Error::new(ErrorKind::InvalidData, "invalid XBM"));
    let define = |suffix: &str| {
        source.lines().find_map(|line| {
            let mut parts = line.split_whitespace();
            (parts.next() == Some("#define") && parts.next()?.ends_with(suffix))
                .then(|| parts.next()?.parse::<u32>().ok())
                .flatten()
        })
    };
    let width = define("_width").ok_or_else(invalid)?;
    let height = define("_height").ok_or_else(invalid)?;
    if width == 0 || height == 0 {
        return Err(invalid());
    }
    let bits_index = source.find("_bits").ok_or_else(invalid)?;
    let declaration_start = source[..bits_index].rfind("static").unwrap_or(0);
    let short_rows = source[declaration_start..bits_index]
        .split_whitespace()
        .any(|word| word == "short");
    let array_start = bits_index + source[bits_index..].find('{').ok_or_else(invalid)? + 1;
    let array_end = array_start + source[array_start..].find('}').ok_or_else(invalid)?;
    let mut data = Vec::new();
    for token in source[array_start..array_end].split(|ch: char| ch == ',' || ch.is_whitespace()) {
        if token.is_empty() {
            continue;
        }
        let token = token.trim_end_matches(|ch| matches!(ch, 'u' | 'U' | 'l' | 'L'));
        let value = if let Some(hex) = token
            .strip_prefix("0x")
            .or_else(|| token.strip_prefix("0X"))
        {
            u16::from_str_radix(hex, 16).map_err(|_| invalid())?
        } else {
            token.parse::<i32>().map_err(|_| invalid())? as u16
        };
        if short_rows {
            data.extend_from_slice(&value.to_le_bytes());
        } else {
            data.push(value as u8);
        }
    }
    let row_bytes = if short_rows {
        width.checked_add(15).ok_or_else(invalid)? / 16 * 2
    } else {
        width.checked_add(7).ok_or_else(invalid)? / 8
    } as usize;
    let data_bytes = row_bytes.checked_mul(height as usize).ok_or_else(invalid)?;
    if data.len() < data_bytes {
        return Err(invalid());
    }
    let rgba_bytes = (width as usize)
        .checked_mul(height as usize)
        .and_then(|pixels| pixels.checked_mul(4))
        .ok_or_else(invalid)?;
    let mut rgba = Vec::new();
    rgba.try_reserve_exact(rgba_bytes).map_err(|_| invalid())?;
    for y in 0..height as usize {
        let row = &data[y * row_bytes..][..row_bytes];
        for x in 0..width as usize {
            let black = row[x / 8] & (1 << (x % 8)) != 0;
            let pixel = if black {
                [0, 0, 0, 255]
            } else {
                [255, 255, 255, 255]
            };
            rgba.extend_from_slice(&pixel);
        }
    }
    image::RgbaImage::from_raw(width, height, rgba)
        .map(image::DynamicImage::ImageRgba8)
        .ok_or_else(invalid)
}

fn strip_c_comments(source: &str) -> String {
    let mut result = String::with_capacity(source.len());
    let mut chars = source.chars().peekable();
    let (mut in_string, mut escaped) = (false, false);
    while let Some(ch) = chars.next() {
        if in_string {
            result.push(ch);
            if escaped {
                escaped = false;
            } else if ch == '\\' {
                escaped = true;
            } else if ch == '"' {
                in_string = false;
            }
        } else if ch == '"' {
            in_string = true;
            result.push(ch);
        } else if ch == '/' && chars.peek() == Some(&'*') {
            chars.next();
            while let Some(ch) = chars.next() {
                if ch == '*' && chars.peek() == Some(&'/') {
                    chars.next();
                    break;
                }
                if ch == '\n' {
                    result.push('\n');
                }
            }
        } else if ch == '/' && chars.peek() == Some(&'/') {
            chars.next();
            for ch in chars.by_ref() {
                if ch == '\n' {
                    result.push('\n');
                    break;
                }
            }
        } else {
            result.push(ch);
        }
    }
    result
}

fn decode_xpm(path: &std::path::Path) -> Result<image::DynamicImage, image::ImageError> {
    use std::io::{Error, ErrorKind};

    let source = std::fs::read_to_string(path)?;
    let invalid = || image::ImageError::IoError(Error::new(ErrorKind::InvalidData, "invalid XPM"));
    let strings = if let Some(source) = source.trim_start().strip_prefix("! XPM2") {
        source
            .lines()
            .filter(|line| !line.trim().is_empty())
            .map(str::to_owned)
            .collect::<Vec<_>>()
    } else {
        read_xpm_strings(&strip_c_comments(&source)).ok_or_else(invalid)?
    };
    let mut values = strings.first().ok_or_else(invalid)?.split_whitespace();
    let width = values
        .next()
        .and_then(|value| value.parse::<u32>().ok())
        .ok_or_else(invalid)?;
    let height = values
        .next()
        .and_then(|value| value.parse::<u32>().ok())
        .ok_or_else(invalid)?;
    let color_count = values
        .next()
        .and_then(|value| value.parse::<usize>().ok())
        .ok_or_else(invalid)?;
    let chars_per_pixel = values
        .next()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|value| *value > 0)
        .ok_or_else(invalid)?;
    if width == 0 || height == 0 {
        return Err(invalid());
    }
    let row_bytes = (width as usize)
        .checked_mul(chars_per_pixel)
        .ok_or_else(invalid)?;
    let needed_strings = color_count
        .checked_add(height as usize)
        .and_then(|count| count.checked_add(1))
        .ok_or_else(invalid)?;
    if strings.len() < needed_strings {
        return Err(invalid());
    }

    let mut colors = std::collections::HashMap::with_capacity(color_count);
    for line in &strings[1..=color_count] {
        if line.len() < chars_per_pixel {
            return Err(invalid());
        }
        let key = line.as_bytes()[..chars_per_pixel].to_vec();
        let definition = line.get(chars_per_pixel..).ok_or_else(invalid)?;
        let color = parse_xpm_color(definition).ok_or_else(invalid)?;
        colors.insert(key, color);
    }

    let rgba_bytes = row_bytes
        .checked_mul(height as usize)
        .and_then(|pixels| pixels.checked_mul(4))
        .ok_or_else(invalid)?;
    let mut rgba = Vec::new();
    rgba.try_reserve_exact(rgba_bytes).map_err(|_| invalid())?;
    for row in &strings[color_count + 1..needed_strings] {
        let bytes = row.as_bytes();
        if bytes.len() < row_bytes {
            return Err(invalid());
        }
        for key in bytes[..row_bytes].chunks_exact(chars_per_pixel) {
            rgba.extend_from_slice(&colors.get(key).ok_or_else(invalid)?.0);
        }
    }
    image::RgbaImage::from_raw(width, height, rgba)
        .map(image::DynamicImage::ImageRgba8)
        .ok_or_else(invalid)
}

fn read_xpm_strings(source: &str) -> Option<Vec<String>> {
    let bytes = source.as_bytes();
    let mut strings = Vec::new();
    let mut offset = 0;
    while offset < bytes.len() {
        if bytes[offset] != b'"' {
            offset += 1;
            continue;
        }
        offset += 1;
        let mut value = Vec::new();
        let mut closed = false;
        while offset < bytes.len() {
            let byte = bytes[offset];
            offset += 1;
            match byte {
                b'"' => {
                    closed = true;
                    break;
                }
                b'\\' => {
                    let escape = *bytes.get(offset)?;
                    offset += 1;
                    match escape {
                        b'\n' => {}
                        b'\r' if bytes.get(offset) == Some(&b'\n') => offset += 1,
                        b'0'..=b'7' => {
                            let mut octal = u16::from(escape - b'0');
                            for _ in 0..2 {
                                if let Some(next @ b'0'..=b'7') = bytes.get(offset).copied() {
                                    octal = octal * 8 + u16::from(next - b'0');
                                    offset += 1;
                                } else {
                                    break;
                                }
                            }
                            value.push(octal as u8);
                        }
                        b'x' => {
                            let start = offset;
                            let mut hex = 0_u16;
                            while let Some(next) = bytes.get(offset).copied() {
                                let Some(digit) = (next as char).to_digit(16) else {
                                    break;
                                };
                                hex = hex.checked_mul(16)?.checked_add(digit as u16)?;
                                offset += 1;
                            }
                            if offset == start {
                                return None;
                            }
                            value.push(hex as u8);
                        }
                        b'a' => value.push(7),
                        b'b' => value.push(8),
                        b'f' => value.push(12),
                        b'n' => value.push(b'\n'),
                        b'r' => value.push(b'\r'),
                        b't' => value.push(b'\t'),
                        b'v' => value.push(11),
                        other => value.push(other),
                    }
                }
                _ => value.push(byte),
            }
        }
        if !closed {
            return None;
        }
        strings.push(String::from_utf8(value).ok()?);
    }
    Some(strings)
}

fn parse_xpm_color(definition: &str) -> Option<image::Rgba<u8>> {
    let mut fields: Vec<(&str, String)> = Vec::new();
    let mut current = None;
    for token in definition.split_whitespace() {
        if matches!(token, "c" | "g" | "g4" | "m" | "s") {
            current = Some(token);
            fields.push((token, String::new()));
        } else if current.is_some() {
            let value = &mut fields.last_mut()?.1;
            if !value.is_empty() {
                value.push(' ');
            }
            value.push_str(token);
        }
    }
    for key in ["c", "g", "g4", "m", "s"] {
        if let Some((_, value)) = fields.iter().find(|(field, _)| *field == key) {
            let value = value.trim();
            if value.eq_ignore_ascii_case("none") || value.eq_ignore_ascii_case("transparent") {
                return Some(image::Rgba([0, 0, 0, 0]));
            }
            if let Some(hex) = value.strip_prefix('#') {
                if ![3, 6, 9, 12].contains(&hex.len()) {
                    return None;
                }
                let component_digits = hex.len() / 3;
                let max = (1_u32 << (component_digits * 4)) - 1;
                let mut rgb = [0; 3];
                for (index, component) in rgb.iter_mut().enumerate() {
                    let start = index * component_digits;
                    let value =
                        u32::from_str_radix(&hex[start..start + component_digits], 16).ok()?;
                    *component = ((value * 255 + max / 2) / max) as u8;
                }
                return Some(image::Rgba([rgb[0], rgb[1], rgb[2], 255]));
            }
            let normalized = normalize_xpm_color_name(value);
            if let Some(rgb) = xpm_named_color(&normalized) {
                return Some(image::Rgba([rgb[0], rgb[1], rgb[2], 255]));
            }
        }
    }
    None
}

fn normalize_xpm_color_name(name: &str) -> String {
    name.chars()
        .filter(|ch| ch.is_ascii_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect()
}

fn xpm_named_color(name: &str) -> Option<[u8; 3]> {
    if let Some(level) = name
        .strip_prefix("gray")
        .or_else(|| name.strip_prefix("grey"))
        .and_then(|level| level.parse::<u8>().ok())
        .filter(|level| *level <= 100)
    {
        let value = (u16::from(level) * 255 / 100) as u8;
        return Some([value; 3]);
    }
    match name {
        "green" => return Some([0, 255, 0]),
        "gray" | "grey" => return Some([190, 190, 190]),
        "maroon" => return Some([176, 48, 96]),
        "purple" => return Some([160, 32, 240]),
        _ => {}
    }
    Some(xpm_color_names().get(name).copied().unwrap_or([0, 0, 0]))
}

fn xpm_color_names() -> &'static std::collections::HashMap<String, [u8; 3]> {
    static COLORS: std::sync::OnceLock<std::collections::HashMap<String, [u8; 3]>> =
        std::sync::OnceLock::new();
    COLORS.get_or_init(|| {
        let mut colors = std::collections::HashMap::new();
        for entry in include_str!("../ui/xpm_colors.txt").lines() {
            if let Some((name, value)) = entry.split_once('=')
                && let Ok(value) = u32::from_str_radix(value, 16)
            {
                colors.insert(
                    name.to_owned(),
                    [(value >> 16) as u8, (value >> 8) as u8, value as u8],
                );
            }
        }
        for path in [
            "/usr/share/X11/rgb.txt",
            "/etc/X11/rgb.txt",
            "/usr/lib/X11/rgb.txt",
            "/usr/X11R6/lib/X11/rgb.txt",
        ] {
            if let Ok(contents) = std::fs::read_to_string(path) {
                for line in contents
                    .lines()
                    .filter(|line| !line.trim_start().starts_with('!'))
                {
                    let mut parts = line.split_whitespace();
                    let (Some(red), Some(green), Some(blue)) =
                        (parts.next(), parts.next(), parts.next())
                    else {
                        continue;
                    };
                    let (Ok(red), Ok(green), Ok(blue)) =
                        (red.parse::<u8>(), green.parse::<u8>(), blue.parse::<u8>())
                    else {
                        continue;
                    };
                    let name = parts.collect::<String>();
                    if !name.is_empty() {
                        colors.insert(normalize_xpm_color_name(&name), [red, green, blue]);
                    }
                }
                break;
            }
        }
        colors
    })
}

struct ArtworkBrowserEntry {
    name: String,
    path: String,
    directory: bool,
}

fn load_artwork_browser_items(
    folder: &std::path::Path,
) -> Result<Vec<ArtworkBrowserEntry>, String> {
    let mut items = Vec::new();
    for entry in std::fs::read_dir(folder).map_err(|error| error.to_string())? {
        let Ok(entry) = entry else {
            continue;
        };
        let name = entry.file_name().to_string_lossy().into_owned();
        if name.starts_with('.') {
            continue;
        }
        let path = entry.path();
        let Ok(metadata) = entry.metadata() else {
            continue;
        };
        let directory = metadata.is_dir();
        if !directory
            && !matches!(
                path.extension()
                    .and_then(|extension| extension.to_str())
                    .map(str::to_ascii_lowercase)
                    .as_deref(),
                Some(
                    "bmp"
                        | "cur"
                        | "gif"
                        | "icns"
                        | "ico"
                        | "jfif"
                        | "jpg"
                        | "jpeg"
                        | "pbm"
                        | "pgm"
                        | "png"
                        | "ppm"
                        | "svg"
                        | "svgz"
                        | "tga"
                        | "tif"
                        | "tiff"
                        | "wbmp"
                        | "webp"
                        | "xbm"
                        | "xpm"
                )
            )
        {
            continue;
        }
        items.push(ArtworkBrowserEntry {
            name,
            path: path.to_string_lossy().into_owned(),
            directory,
        });
    }
    items.sort_by(|left, right| {
        right
            .directory
            .cmp(&left.directory)
            .then_with(|| left.name.to_lowercase().cmp(&right.name.to_lowercase()))
    });
    Ok(items)
}

fn group_artwork_browser_items(
    items: Vec<ArtworkBrowserItem>,
    columns: usize,
) -> Vec<ArtworkBrowserRow> {
    items
        .chunks(columns.clamp(2, 3))
        .map(|items| ArtworkBrowserRow {
            items: ModelRc::new(VecModel::from(items.to_vec())),
        })
        .collect()
}

fn flatten_artwork_browser_rows(rows: &ModelRc<ArtworkBrowserRow>) -> Vec<ArtworkBrowserItem> {
    (0..rows.row_count())
        .filter_map(|index| rows.row_data(index))
        .flat_map(|row| {
            (0..row.items.row_count()).filter_map(move |index| row.items.row_data(index))
        })
        .collect()
}

fn background_viewport_size(size: (u32, u32), scale_factor: f32) -> (u32, u32) {
    let scale = scale_factor.max(0.1);
    (
        (size.0.max(1) as f32 * scale).round().max(1.0) as u32,
        (size.1.max(1) as f32 * scale).round().max(1.0) as u32,
    )
}

fn background_sizes(viewport: (u32, u32)) -> ((u32, u32), (u32, u32)) {
    let (width, height) = (viewport.0.max(1), viewport.1.max(1));
    let scale = (2560.0 / width as f32).min(1440.0 / height as f32).min(1.0);
    (
        (
            (width as f32 * scale).round().max(1.0) as u32,
            (height as f32 * scale).round().max(1.0) as u32,
        ),
        (width.min(2560), height.min(1440)),
    )
}

fn background_pixels(
    game: &Game,
    split: &str,
    blur: i32,
    position: &str,
    size: (u32, u32),
    global: Option<String>,
    fill_mode: String,
    fallback_color: [u8; 3],
) -> Option<image::RgbaImage> {
    let Some(primary_path) = global.as_deref().or_else(|| game.field("banner")) else {
        return None;
    };
    let (size, decode_size) = background_sizes(size);
    let primary_path = clean_image_path(primary_path);
    let secondary_path = if global.is_some() {
        None
    } else {
        game.field("banner_secondary")
            .or_else(|| game.field("secondary"))
            .map(clean_image_path)
    };
    let sample_dominant = fill_mode == "dominant"
        && position != "full"
        && (split == "single" || secondary_path.is_none());
    let mut dominant_sample = None;
    let paired_pixels = secondary_path.and_then(|secondary| {
        (split != "single").then(|| {
            compose_slint_background_pair(
                primary_path,
                secondary,
                split,
                position,
                &fill_mode,
                blur,
                fallback_color,
                size,
            )
        })?
    });
    let paired = paired_pixels.is_some();
    let mut pixels = paired_pixels.or_else(|| {
        load_background_pixels(
            primary_path,
            sample_dominant,
            &mut dominant_sample,
            decode_size,
        )
    });
    let Some(mut pixels) = pixels.take() else {
        return None;
    };
    if blur > 0 && !paired {
        pixels = blur_background_image(&pixels, blur);
    }
    if position != "full" && (split == "single" || secondary_path.is_none()) {
        pixels = positioned_background(
            &pixels,
            position,
            size,
            &fill_mode,
            blur,
            dominant_sample.as_ref(),
        );
    }
    Some(pixels)
}

fn blur_background_image(pixels: &image::RgbaImage, radius: i32) -> image::RgbaImage {
    let radius = radius.clamp(0, 40);
    if radius == 0 {
        return pixels.clone();
    }
    let amount = radius as f32 / 40.0;
    let lod = (amount * 40.0 / 64.0).sqrt() * 1.2 - 0.2;
    let centers = [0.1_f32, 0.3, 0.5, 0.7, 0.9, 1.1];
    let mut weights = centers.map(|center| (1.0 - (lod - center).abs() * 2.0).clamp(0.0, 1.0));
    let weight_sum: f32 = weights.iter().sum();
    weights.iter_mut().for_each(|weight| *weight /= weight_sum);

    // Qt MultiEffect builds five half-size blur layers, then mixes all six levels.
    let first_size = |size: u32| ((size as f32 / 16.0).ceil() * 8.0) as u32;
    let mut levels = vec![pixels.clone()];
    for layer in 0..5 {
        let source = levels.last().unwrap();
        let (width, height) = if layer == 0 {
            (first_size(pixels.width()), first_size(pixels.height()))
        } else {
            (source.width().div_ceil(2), source.height().div_ceil(2))
        };
        let offset = (1.0 / width as f32, 1.0 / height as f32);
        levels.push(image::RgbaImage::from_fn(width, height, |x, y| {
            let u = (x as f32 + 0.5) / width as f32;
            let v = (y as f32 + 0.5) / height as f32;
            let samples = [
                (u + offset.0, v + offset.1 * 0.33),
                (u + offset.0 * 0.33, v - offset.1),
                (u - offset.0 * 0.33, v + offset.1),
                (u - offset.0, v - offset.1 * 0.33),
            ];
            let mut color = [0.0_f32; 4];
            for (sample_u, sample_v) in samples {
                let sample = sample_rgba_texture(source, sample_u, sample_v);
                for channel in 0..4 {
                    color[channel] += sample[channel] * 0.25;
                }
            }
            image::Rgba(color.map(|channel| channel.round().clamp(0.0, 255.0) as u8))
        }));
    }

    image::RgbaImage::from_fn(pixels.width(), pixels.height(), |x, y| {
        let u = (x as f32 + 0.5) / pixels.width() as f32;
        let v = (y as f32 + 0.5) / pixels.height() as f32;
        let mut color = [0.0_f32; 4];
        for (level, weight) in levels.iter().zip(weights) {
            let sample = sample_rgba_texture(level, u, v);
            for channel in 0..4 {
                color[channel] += sample[channel] * weight;
            }
        }
        image::Rgba(color.map(|channel| channel.round().clamp(0.0, 255.0) as u8))
    })
}

fn sample_rgba_texture(pixels: &image::RgbaImage, u: f32, v: f32) -> [f32; 4] {
    let x = (u * pixels.width() as f32 - 0.5).clamp(0.0, pixels.width().saturating_sub(1) as f32);
    let y = (v * pixels.height() as f32 - 0.5).clamp(0.0, pixels.height().saturating_sub(1) as f32);
    let x0 = x.floor() as u32;
    let y0 = y.floor() as u32;
    let x1 = (x0 + 1).min(pixels.width() - 1);
    let y1 = (y0 + 1).min(pixels.height() - 1);
    let tx = x - x0 as f32;
    let ty = y - y0 as f32;
    let top_left = pixels.get_pixel(x0, y0).0;
    let top_right = pixels.get_pixel(x1, y0).0;
    let bottom_left = pixels.get_pixel(x0, y1).0;
    let bottom_right = pixels.get_pixel(x1, y1).0;
    let mut color = [0.0; 4];
    for channel in 0..4 {
        let top = top_left[channel] as f32 * (1.0 - tx) + top_right[channel] as f32 * tx;
        let bottom = bottom_left[channel] as f32 * (1.0 - tx) + bottom_right[channel] as f32 * tx;
        color[channel] = top * (1.0 - ty) + bottom * ty;
    }
    color
}

fn compose_slint_background_pair(
    primary_path: &str,
    secondary_path: &str,
    split: &str,
    position: &str,
    fill_mode: &str,
    blur: i32,
    fallback_color: [u8; 3],
    size: (u32, u32),
) -> Option<image::RgbaImage> {
    let primary_source = decode_image(std::path::Path::new(primary_path)).ok();
    let secondary_source = decode_image(std::path::Path::new(secondary_path)).ok();
    if primary_source.is_none() && secondary_source.is_none() {
        return None;
    }
    let split = match split {
        "horizontal" | "vertical" | "diagonal" => split,
        _ => "diagonal",
    };
    let (width, height) = (size.0.max(1), size.1.max(1));
    let band = (width.min(height) as f32 * 0.12).min(128.0).max(1.0);
    let (region_width, region_height) = match split {
        "vertical" => ((width as f32 / 2.0 + band / 2.0).round() as u32, height),
        "horizontal" => (width, (height as f32 / 2.0 + band / 2.0).round() as u32),
        _ => (width, height),
    };
    let secondary_offset = match split {
        "vertical" => width.saturating_sub(region_width),
        "horizontal" => height.saturating_sub(region_height),
        _ => 0,
    };
    let make_region = |source: Option<&image::DynamicImage>| {
        let Some(source) = source else {
            let fallback = image::RgbaImage::from_pixel(
                region_width,
                region_height,
                image::Rgba([fallback_color[0], fallback_color[1], fallback_color[2], 255]),
            );
            return (fallback.clone(), fallback);
        };
        let hero = blur_background_image(
            &resize_background_crop(source, region_width, region_height, position),
            blur,
        );
        let fill = background_fill_region(
            source,
            region_width,
            region_height,
            position,
            fill_mode,
            blur,
            fallback_color,
        );
        (hero, fill)
    };
    let (primary, primary_fill) = make_region(primary_source.as_ref());
    let (secondary, secondary_fill) = make_region(secondary_source.as_ref());
    if primary_source.is_none() {
        let secondary_composited = composite_background_region(&secondary, &secondary_fill);
        return Some(image::RgbaImage::from_fn(width, height, |x, y| {
            let (inside, source_x, source_y) = match split {
                "vertical" => (
                    x >= secondary_offset,
                    x.saturating_sub(secondary_offset).min(region_width - 1),
                    y.min(region_height - 1),
                ),
                "horizontal" => (
                    y >= secondary_offset,
                    x.min(region_width - 1),
                    y.saturating_sub(secondary_offset).min(region_height - 1),
                ),
                _ => (true, x, y),
            };
            if inside {
                *secondary_composited.get_pixel(source_x, source_y)
            } else {
                image::Rgba([fallback_color[0], fallback_color[1], fallback_color[2], 255])
            }
        }));
    }
    let normalizer = ((1.0 / width as f32).powi(2) + (1.0 / height as f32).powi(2)).sqrt();
    let over = |background: [u8; 4], foreground: [u8; 4], coverage: f32| {
        let alpha = foreground[3] as f32 / 255.0 * coverage;
        let inverse = 1.0 - alpha;
        [
            (foreground[0] as f32 * alpha + background[0] as f32 * inverse).round() as u8,
            (foreground[1] as f32 * alpha + background[1] as f32 * inverse).round() as u8,
            (foreground[2] as f32 * alpha + background[2] as f32 * inverse).round() as u8,
            255,
        ]
    };

    Some(image::RgbaImage::from_fn(width, height, |x, y| {
        let (
            primary_x,
            primary_y,
            secondary_x,
            secondary_y,
            primary_inside,
            secondary_inside,
            distance,
        ) = match split {
            "horizontal" => (
                x.min(region_width - 1),
                y.min(region_height - 1),
                x.min(region_width - 1),
                y.saturating_sub(secondary_offset).min(region_height - 1),
                y < region_height,
                y >= secondary_offset,
                y as f32 - height as f32 / 2.0,
            ),
            "vertical" => (
                x.min(region_width - 1),
                y.min(region_height - 1),
                x.saturating_sub(secondary_offset).min(region_width - 1),
                y.min(region_height - 1),
                x < region_width,
                x >= secondary_offset,
                x as f32 - width as f32 / 2.0,
            ),
            "diagonal" => (
                x,
                y,
                x,
                y,
                true,
                true,
                (x as f32 / width as f32 + y as f32 / height as f32 - 1.0) / normalizer,
            ),
            _ => (x, y, x, y, true, false, -band),
        };
        let linear_mask = (0.5 - distance / band).clamp(0.0, 1.0);
        // Qt MultiEffect uses thresholdMin 0.5 and spreadAtMin 0.5 here.
        let smooth_mask = ((linear_mask - 0.25) / 0.5).clamp(0.0, 1.0);
        let mix = smooth_mask * smooth_mask * (3.0 - 2.0 * smooth_mask);
        let mut pixel = [fallback_color[0], fallback_color[1], fallback_color[2], 255];
        if position != "full" {
            if secondary_inside {
                pixel = over(
                    pixel,
                    secondary_fill.get_pixel(secondary_x, secondary_y).0,
                    1.0,
                );
            }
            if primary_inside {
                pixel = over(pixel, primary_fill.get_pixel(primary_x, primary_y).0, mix);
            }
        }
        if secondary_inside {
            pixel = over(pixel, secondary.get_pixel(secondary_x, secondary_y).0, 1.0);
        }
        if primary_inside {
            pixel = over(pixel, primary.get_pixel(primary_x, primary_y).0, mix);
        }
        image::Rgba(pixel)
    }))
}

fn resize_background_crop(
    source: &image::DynamicImage,
    width: u32,
    height: u32,
    position: &str,
) -> image::RgbaImage {
    use image::imageops::FilterType;
    let (source_width, source_height) = (source.width(), source.height());
    let target_ratio = width as f64 / height as f64;
    let source_ratio = source_width as f64 / source_height as f64;
    let (x, y, crop_width, crop_height) = if source_ratio > target_ratio {
        let crop_width = (source_height as f64 * target_ratio)
            .round()
            .clamp(1.0, source_width as f64) as u32;
        (
            (source_width - crop_width) / 2,
            0,
            crop_width,
            source_height,
        )
    } else {
        let crop_height = (source_width as f64 / target_ratio)
            .round()
            .clamp(1.0, source_height as f64) as u32;
        let overflow_y = source_height - crop_height;
        let y = match position {
            "top" => 0,
            "lower" => overflow_y,
            _ => overflow_y / 2,
        };
        (0, y, source_width, crop_height)
    };
    source
        .crop_imm(x, y, crop_width, crop_height)
        .resize_exact(width, height, FilterType::Lanczos3)
        .into_rgba8()
}

fn background_fill_region(
    source: &image::DynamicImage,
    width: u32,
    height: u32,
    position: &str,
    fill_mode: &str,
    blur: i32,
    fallback_color: [u8; 3],
) -> image::RgbaImage {
    if position == "full" {
        return image::RgbaImage::from_pixel(
            width,
            height,
            image::Rgba([fallback_color[0], fallback_color[1], fallback_color[2], 255]),
        );
    }
    if fill_mode == "dominant" {
        let sample = source.thumbnail(64, 64).into_rgba8();
        let color = dominant_color(&sample);
        return image::RgbaImage::from_pixel(
            width,
            height,
            image::Rgba([color[0], color[1], color[2], 255]),
        );
    }

    let expanded_width = width.saturating_add(96);
    let expanded_height = height.saturating_add(96);
    let expanded = resize_background_crop(source, expanded_width, expanded_height, position);
    let blurred = blur_background_image(&expanded, blur);
    image::imageops::crop_imm(&blurred, 48, 48, width, height).to_image()
}

fn composite_background_region(
    hero: &image::RgbaImage,
    fill: &image::RgbaImage,
) -> image::RgbaImage {
    image::RgbaImage::from_fn(hero.width(), hero.height(), |x, y| {
        let foreground = hero.get_pixel(x, y).0;
        let background = fill.get_pixel(x, y).0;
        let alpha = foreground[3] as f32 / 255.0;
        image::Rgba([
            (foreground[0] as f32 * alpha + background[0] as f32 * (1.0 - alpha)).round() as u8,
            (foreground[1] as f32 * alpha + background[1] as f32 * (1.0 - alpha)).round() as u8,
            (foreground[2] as f32 * alpha + background[2] as f32 * (1.0 - alpha)).round() as u8,
            255,
        ])
    })
}

fn load_background_pixels(
    path: &str,
    sample_dominant: bool,
    dominant_sample: &mut Option<image::RgbaImage>,
    size: (u32, u32),
) -> Option<image::RgbaImage> {
    let source = decode_image(std::path::Path::new(path)).ok()?;
    if sample_dominant {
        *dominant_sample = Some(source.thumbnail(64, 64).into_rgba8());
    }
    Some(source.thumbnail(size.0.max(1), size.1.max(1)).into_rgba8())
}

fn positioned_background(
    pixels: &image::RgbaImage,
    position: &str,
    size: (u32, u32),
    fill_mode: &str,
    blur: i32,
    dominant_sample: Option<&image::RgbaImage>,
) -> image::RgbaImage {
    use image::imageops::{FilterType, overlay};
    let (width, height) = size;
    let source = image::DynamicImage::ImageRgba8(pixels.clone());
    let mut filler = if fill_mode == "dominant" {
        let sample = dominant_sample
            .cloned()
            .unwrap_or_else(|| source.thumbnail(64, 64).into_rgba8());
        let color = dominant_color(&sample);
        image::RgbaImage::from_pixel(
            width,
            height,
            image::Rgba([color[0], color[1], color[2], 255]),
        )
    } else {
        let fill = source
            .resize_to_fill(width, height, FilterType::Triangle)
            .into_rgba8();
        blur_background_image(&fill, blur)
    };
    let mut hero = source
        .resize(width, height, FilterType::Lanczos3)
        .into_rgba8();
    let hero_height = hero.height();
    for (_, y, pixel) in hero.enumerate_pixels_mut() {
        let progress = y as f32 / hero_height.max(1) as f32;
        let progress = if position == "lower" {
            1. - progress
        } else {
            progress
        };
        let stops = [(0., 1.), (0.45, 1.), (0.65, 0.85), (0.82, 0.35), (1., 0.)];
        let alpha = stops
            .windows(2)
            .find(|pair| progress <= pair[1].0)
            .map(|pair| {
                let t = (progress - pair[0].0) / (pair[1].0 - pair[0].0);
                pair[0].1 + t * (pair[1].1 - pair[0].1)
            })
            .unwrap_or(0.);
        pixel.0[3] = (pixel.0[3] as f32 * alpha) as u8;
    }
    overlay(
        &mut filler,
        &hero,
        i64::from((width - hero.width()) / 2),
        if position == "lower" {
            i64::from(height - hero.height())
        } else {
            0
        },
    );
    filler
}

fn dominant_color(sample: &image::RgbaImage) -> [u8; 3] {
    let mut histogram = [[0u32; 5]; 8 * 8 * 8];
    for (position, pixel) in sample.pixels().enumerate() {
        if pixel[3] < 128 {
            continue;
        }
        let bin = (usize::from(pixel[0] / 32) << 6)
            | (usize::from(pixel[1] / 32) << 3)
            | usize::from(pixel[2] / 32);
        let bucket = &mut histogram[bin];
        if bucket[0] == 0 {
            bucket[4] = position as u32 + 1;
        }
        bucket[0] += 1;
        bucket[1] += u32::from(pixel[0]);
        bucket[2] += u32::from(pixel[1]);
        bucket[3] += u32::from(pixel[2]);
    }

    let mut dominant = None;
    for (bin, bucket) in histogram.iter().enumerate() {
        if bucket[0] == 0 {
            continue;
        }
        if dominant.is_none_or(|(_, current): (usize, &[u32; 5])| {
            bucket[0] > current[0] || (bucket[0] == current[0] && bucket[4] < current[4])
        }) {
            dominant = Some((bin, bucket));
        }
    }
    let Some((_, bucket)) = dominant else {
        return [32, 32, 32];
    };
    [
        rounded_average(bucket[1], bucket[0]),
        rounded_average(bucket[2], bucket[0]),
        rounded_average(bucket[3], bucket[0]),
    ]
}

fn rounded_average(sum: u32, count: u32) -> u8 {
    let quotient = sum / count;
    let remainder = sum % count;
    let round_up = remainder * 2 > count || (remainder * 2 == count && quotient % 2 == 1);
    (quotient + u32::from(round_up)) as u8
}

fn clean_image_path(path: &str) -> &str {
    path.strip_prefix("file://").unwrap_or(path)
}

fn parse_color(value: &str) -> slint::Color {
    let hex = value.strip_prefix('#').unwrap_or(value);
    if valid_color(value) {
        if let Ok(argb) = u32::from_str_radix(hex, 16) {
            return slint::Color::from_argb_encoded(if hex.len() == 6 {
                argb | 0xff000000
            } else {
                argb
            });
        }
    }
    slint::Color::from_rgb_u8(255, 255, 255)
}

fn update_system_clock(window: &ListWindow) {
    let now = chrono::Local::now();
    let format = match window.get_date_format().as_str() {
        "mdy" => "%m/%d/%Y",
        "ymd" => "%Y-%m-%d",
        _ => "%d/%m/%Y",
    };
    window.set_status_time(now.format("%H:%M").to_string().into());
    window.set_status_date(now.format(format).to_string().into());
}

fn update_battery_status(window: &ListWindow) {
    if let Some(status) = crate::power::read_battery_status() {
        window.set_battery_percentage(i32::from(status.percentage));
        window.set_battery_charging(status.charging);
        window.set_battery_full(status.full);
        window.set_battery_present(true);
    } else {
        window.set_battery_present(false);
    }
}

fn chrono_utc_now() -> String {
    let seconds = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs() as i64;
    let days = seconds.div_euclid(86_400);
    let day_seconds = seconds.rem_euclid(86_400);
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let day_of_era = z - era * 146_097;
    let year_of_era =
        (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let mut year = year_of_era + era * 400;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let month_prime = (5 * day_of_year + 2) / 153;
    let day = day_of_year - (153 * month_prime + 2) / 5 + 1;
    let month = month_prime + if month_prime < 10 { 3 } else { -9 };
    year += i64::from(month <= 2);
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z",
        day_seconds / 3600,
        (day_seconds % 3600) / 60,
        day_seconds % 60
    )
}

fn setting_choice<'a>(
    settings: &'a Value,
    key: &str,
    default: &'a str,
    choices: &[&str],
) -> &'a str {
    settings
        .get(key)
        .and_then(Value::as_str)
        .filter(|value| choices.contains(value))
        .unwrap_or(default)
}

fn setting_number(settings: &Value, key: &str, default: i32, min: i32, max: i32) -> i32 {
    settings
        .get(key)
        .and_then(Value::as_f64)
        .filter(|value| value.is_finite())
        .map(|value| value.round().clamp(f64::from(min), f64::from(max)) as i32)
        .unwrap_or(default)
}

fn nested_number(
    settings: &Value,
    object: &str,
    key: &str,
    default: i32,
    min: i32,
    max: i32,
) -> i32 {
    settings
        .get(object)
        .and_then(|values| values.get(key))
        .and_then(Value::as_f64)
        .filter(|value| value.is_finite())
        .map(|value| value.round().clamp(f64::from(min), f64::from(max)) as i32)
        .unwrap_or(default)
}

fn nested_choice<'a>(
    settings: &'a Value,
    object: &str,
    key: &str,
    default: &'a str,
    choices: &[&str],
) -> &'a str {
    settings
        .get(object)
        .and_then(|values| values.get(key))
        .and_then(Value::as_str)
        .filter(|value| choices.contains(value))
        .unwrap_or(default)
}

fn nested_bool(settings: &Value, object: &str, key: &str, default: bool) -> bool {
    settings
        .get(object)
        .and_then(|values| values.get(key))
        .and_then(Value::as_bool)
        .unwrap_or(default)
}

fn nested_ring_number(ring: Option<&Value>, key: &str, default: i32, min: i32, max: i32) -> i32 {
    ring.and_then(|ring| ring.get(key))
        .and_then(Value::as_f64)
        .filter(|value| value.is_finite())
        .map(|value| value.round().clamp(f64::from(min), f64::from(max)) as i32)
        .unwrap_or(default)
}

fn valid_color(value: &str) -> bool {
    let value = value.strip_prefix('#').unwrap_or(value);
    matches!(value.len(), 6 | 8) && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn keyboard_keys(window: &ListWindow, row: i32) -> ModelRc<slint::SharedString> {
    match row {
        0 => window.get_keyboard_keys_0(),
        1 => window.get_keyboard_keys_1(),
        2 => window.get_keyboard_keys_2(),
        3 => window.get_keyboard_keys_3(),
        _ => window.get_keyboard_keys_4(),
    }
}
