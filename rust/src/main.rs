mod artwork;
mod category_icons;
mod controls;
mod importers;
mod launchers;
mod metadata;
mod model;
mod scraping;
mod settings;
mod supervisor;
mod system_keyboard;
mod updates;

use artwork::ArtworkOption;
use iced::widget::{checkbox, column, container, row, scrollable, stack, text, text_input};
use iced::{Alignment, Element, Length, Size, Subscription, Task};
use metadata::MetadataOption;
use model::{Game, Library};
use serde_json::{Map, Value, json};
use std::{collections::HashMap, fs, path::PathBuf, process::Child};
use std::{
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, AtomicU64, Ordering},
    },
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

static SETTINGS_WRITE_LOCK: Mutex<()> = Mutex::new(());
const MIN_BACKGROUND_DECODE_SIZE: (u32, u32) = (2560, 1440);
const MAX_BACKGROUND_DECODE_SIZE: (u32, u32) = (3840, 2160);
const PREFETCH_BACKGROUND_DECODE_SIZE: (u32, u32) = (1280, 1440);

fn active_background_decode_size(width: f32, height: f32) -> (u32, u32) {
    (
        width.ceil().clamp(
            MIN_BACKGROUND_DECODE_SIZE.0 as f32,
            MAX_BACKGROUND_DECODE_SIZE.0 as f32,
        ) as u32,
        height.ceil().clamp(
            MIN_BACKGROUND_DECODE_SIZE.1 as f32,
            MAX_BACKGROUND_DECODE_SIZE.1 as f32,
        ) as u32,
    )
}

fn button<'a>(content: impl Into<Element<'a, Message>>) -> iced::widget::Button<'a, Message> {
    iced::widget::button(content).style(|theme, status| {
        let alpha = match status {
            iced::widget::button::Status::Active => 0.09,
            iced::widget::button::Status::Hovered => 0.16,
            iced::widget::button::Status::Pressed => 0.22,
            iced::widget::button::Status::Disabled => 0.04,
        };
        iced::widget::button::Style {
            background: Some(iced::Background::Color(iced::Color::from_rgba(
                0.86, 0.90, 0.97, alpha,
            ))),
            text_color: theme.extended_palette().background.base.text,
            border: iced::Border {
                color: theme
                    .extended_palette()
                    .primary
                    .base
                    .color
                    .scale_alpha(0.30),
                width: 1.0,
                radius: 12.0.into(),
            },
            ..Default::default()
        }
    })
}

fn focus_plate<'a>(focus: f32, width: f32, color: iced::Color) -> Element<'a, Message> {
    container(text(""))
        .width(Length::Fixed(width))
        .height(Length::Fixed(4.0 * focus))
        .style(move |_| iced::widget::container::Style {
            background: Some(iced::Background::Color(color)),
            ..Default::default()
        })
        .into()
}

fn parse_focus_color(value: &str) -> Option<iced::Color> {
    let value = value.trim();
    if let Some(hex) = value.strip_prefix('#') {
        if hex.len() != 6 && hex.len() != 8 {
            return None;
        }
        let channel = |start| u8::from_str_radix(&hex[start..start + 2], 16).ok();
        return Some(iced::Color::from_rgba8(
            channel(0)?,
            channel(2)?,
            channel(4)?,
            if hex.len() == 8 {
                channel(6)? as f32 / 255.0
            } else {
                1.0
            },
        ));
    }
    let components = value
        .strip_prefix("rgba(")
        .or_else(|| value.strip_prefix("rgb("))?
        .strip_suffix(')')?
        .split(',')
        .map(|part| part.trim().parse::<f32>().ok())
        .collect::<Option<Vec<_>>>()?;
    if components.len() < 3 {
        return None;
    }
    let alpha = components.get(3).copied().unwrap_or(1.0).clamp(0.0, 1.0);
    Some(iced::Color::from_rgba8(
        components[0].round().clamp(0.0, 255.0) as u8,
        components[1].round().clamp(0.0, 255.0) as u8,
        components[2].round().clamp(0.0, 255.0) as u8,
        alpha,
    ))
}

fn selection_ring(settings: &Value, layout: &str) -> (bool, iced::Color, f32, f32) {
    let mode = settings
        .get("selection_rings")
        .and_then(|rings| rings.get(layout));
    let value = |key: &str| {
        mode.and_then(|ring| ring.get(key))
            .or_else(|| settings.get(key))
    };
    let enabled = value("focus_ring_enabled")
        .and_then(Value::as_bool)
        .unwrap_or(true);
    let color = value("focus_ring_color")
        .and_then(Value::as_str)
        .and_then(parse_focus_color)
        .unwrap_or(iced::Color::WHITE);
    let width = value("focus_ring_width")
        .and_then(Value::as_u64)
        .unwrap_or(3)
        .min(12) as f32;
    let radius = value("focus_ring_radius")
        .and_then(Value::as_u64)
        .unwrap_or(18)
        .min(50) as f32;
    (enabled, color, width, radius)
}

struct AppExecutor(tokio::runtime::Runtime);

impl iced::executor::Executor for AppExecutor {
    fn new() -> Result<Self, iced::futures::io::Error> {
        tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .max_blocking_threads(4)
            .enable_all()
            .build()
            .map(Self)
    }

    fn spawn(&self, future: impl std::future::Future<Output = ()> + Send + 'static) {
        let _ = self.0.spawn(future);
    }

    fn block_on<T>(&self, future: impl std::future::Future<Output = T>) -> T {
        self.0.block_on(future)
    }

    fn enter<R>(&self, f: impl FnOnce() -> R) -> R {
        let _guard = self.0.enter();
        f()
    }
}

#[cfg(all(target_os = "linux", target_env = "gnu"))]
unsafe extern "C" {
    fn mallopt(param: i32, value: i32) -> i32;
    fn malloc_trim(pad: usize) -> i32;
}

fn configure_native_allocator() {
    #[cfg(all(target_os = "linux", target_env = "gnu"))]
    if std::env::var("ESTANTE_NATIVE_ALLOCATOR").as_deref() != Ok("0")
        && std::env::var_os("MALLOC_MMAP_THRESHOLD_").is_none()
        && std::env::var_os("MALLOC_TRIM_THRESHOLD_").is_none()
        && !std::env::var("GLIBC_TUNABLES")
            .unwrap_or_default()
            .contains("glibc.malloc.")
    {
        // Keep glibc from raising its mmap threshold after decoding large artwork.
        unsafe {
            mallopt(-3, 128 * 1024);
            mallopt(-1, 128 * 1024);
        }
    }
}

fn trim_native_heap() {
    #[cfg(all(target_os = "linux", target_env = "gnu"))]
    unsafe {
        malloc_trim(0);
    }
}

fn main() -> iced::Result {
    let arguments = std::env::args().collect::<Vec<_>>();
    if let Some(index) = arguments
        .iter()
        .position(|argument| argument == "--supervisor-session")
    {
        let Some(path) = arguments.get(index + 1) else {
            eprintln!("Falta el archivo de sesión del supervisor.");
            std::process::exit(2);
        };
        if let Err(error) = supervisor::run(PathBuf::from(path).as_path()) {
            eprintln!("Estante supervisor: {error}");
            std::process::exit(1);
        }
        return Ok(());
    }
    if arguments
        .iter()
        .any(|argument| argument == "--version" || argument == "-V")
    {
        println!("Estante {} (Rust/iced)", env!("CARGO_PKG_VERSION"));
        return Ok(());
    }
    configure_native_allocator();
    iced::application(App::new, App::update, App::view)
        .executor::<AppExecutor>()
        .title("Estante")
        .theme(|_: &App| {
            iced::Theme::custom(
                "Estante",
                iced::theme::Palette {
                    background: iced::Color::from_rgb(0.06, 0.055, 0.055),
                    text: iced::Color::from_rgb(0.91, 0.89, 0.89),
                    primary: iced::Color::from_rgb(0.43, 0.19, 0.19),
                    success: iced::Color::from_rgb(0.20, 0.42, 0.32),
                    warning: iced::Color::from_rgb(0.62, 0.43, 0.19),
                    danger: iced::Color::from_rgb(0.67, 0.25, 0.24),
                },
            )
        })
        .window_size(Size::new(1180.0, 760.0))
        .subscription(App::subscription)
        .run()
}

fn take_resume_file() -> Option<Value> {
    let path = std::env::var_os("ESTANTE_RESUME_FILE").map(PathBuf::from)?;
    let value = serde_json::from_slice::<Value>(&fs::read(&path).ok()?).ok()?;
    if !value.is_object() {
        return None;
    }
    let _ = fs::remove_file(path);
    Some(value)
}

#[derive(Debug, Clone)]
enum Message {
    Search(String),
    Category(Option<String>),
    RemoveCategory(String),
    CategoryName(String),
    AddCategory,
    RenameCategoryStart(String),
    RenameCategorySave,
    MoveCategory(String, isize),
    SetPrimaryCategory(Option<String>),
    ToggleCategoryGames(String),
    CategoryGamesQuery(String),
    SetCategoryGame(String, String, bool),
    CategoryIconQuery(String),
    CategoryIconProvider(String),
    CategoryIconTarget(Option<String>),
    SearchCategoryIcons,
    CategoryIconsSearched(Result<Vec<category_icons::IconOption>, String>),
    CategoryIconPage(isize),
    ChooseCategoryIcon(category_icons::IconOption, Option<String>),
    CategoryIconDownloaded(Result<(category_icons::IconOption, PathBuf, Option<String>), String>),
    CategoryIconLocalPath(String),
    UseLocalCategoryIcon,
    ClearCategoryIcon,
    Select(String),
    Back,
    ChangeLayout(String),
    Launch(String),
    PollSession,
    WindowReady(Option<iced::window::Id>),
    WindowResized(Size),
    MouseWheel { x: f32, y: f32 },
    WindowFocus(bool),
    ProcessesPolled(Result<Vec<u32>, String>),
    SupervisorPrepared(Result<PathBuf, String>),
    ScanImports,
    ScanFinished(Result<(usize, usize), String>),
    ScanProvider(String),
    ScanProviderFinished(Result<(String, usize, usize), String>),
    AddLocal,
    CancelLocal,
    LocalTitle(String),
    LocalPath(String),
    LocalArguments(String),
    LocalWorkingDirectory(String),
    SaveLocal,
    LayoutSaved(u64, Result<(), String>),
    AskRemove(String),
    ConfirmRemove,
    CancelRemove,
    RestoreImports,
    Scrape(bool),
    CancelScrape,
    ScrapeFinished(Result<(usize, usize, Vec<String>), String>),
    Settings,
    SettingsSection(String),
    PreviewScreensaver,
    Exit,
    SetSettingPath(Vec<String>, Value),
    SearchArtwork(String, String),
    ArtworkSearchFinished(Result<Vec<ArtworkOption>, String>),
    ChooseArtwork(ArtworkOption),
    ArtworkDownloaded(Result<(String, String, String, String), String>),
    FetchSteamMetadata(String),
    SteamMetadataFetched(Result<(String, Map<String, Value>), String>),
    SearchWikidata,
    WikidataSearchFinished(Result<Vec<MetadataOption>, String>),
    ChooseWikidata(MetadataOption),
    WikidataFetched(Result<(String, Map<String, Value>), String>),
    ImagesLoaded(u64, Option<String>, Vec<LoadedImage>),
    AnimationTick,
    Activity,
    IdleTick,
    PollGamepad,
    ControllerAction(&'static str),
    KeyboardText(String),
    KeyboardInsert(String),
    KeyboardCommand(&'static str),
    OpenKeyboard(KeyboardTarget),
    SystemKeyboardOpened(KeyboardTarget, bool, Result<String, String>),
    SystemKeyboardHidden(Result<(), String>),
    CheckUpdates,
    UpdateChecked(Result<Option<updates::Release>, String>),
    InstallUpdate(updates::Release),
    UpdateInstalled(Result<String, String>),
    StartLaunchers,
    LaunchersStarted(Result<Vec<String>, String>),
    PollLaunchers,
    LaunchersPolled(Result<Vec<String>, String>),
    ManageLauncher(String, bool),
    LauncherActionFinished(String, bool, Result<String, String>),
    Edit(String),
    EditField(EditorField, String),
    SaveEdit,
    CancelEdit,
    BrowseImage(EditorField),
    ImageDirectoryLoaded(PathBuf, Result<Vec<(PathBuf, bool)>, String>),
    ImageBrowserSelect(usize),
    ImageBrowserOpen(usize),
    ImageBrowserParent,
    ImageBrowserPlace(PathBuf),
    ImageBrowserUse,
    ImageBrowserCancel,
}

#[derive(Debug, Clone, Copy)]
enum EditorField {
    Title,
    Categories,
    Description,
    Synopsis,
    ReleaseDate,
    Developers,
    Publishers,
    Genres,
    Platforms,
    LocalPath,
    Arguments,
    WorkingDirectory,
    Cover,
    SquareCover,
    Logo,
    Banner,
    BannerSecondary,
}

#[derive(Debug, Clone)]
struct LoadedImage {
    path: String,
    bytes: Vec<u8>,
    blurred_bytes: Option<Vec<u8>>,
    blur_radius: u64,
}

#[derive(Default)]
struct EditDraft {
    id: String,
    title: String,
    categories: String,
    description: String,
    synopsis: String,
    release_date: String,
    developers: String,
    publishers: String,
    genres: String,
    platforms: String,
    local_path: String,
    arguments: String,
    cwd: String,
    cover: String,
    square_cover: String,
    logo: String,
    banner: String,
    banner_secondary: String,
    steamgriddb_id: String,
    metadata_entity_id: String,
    metadata_source: String,
}

struct ImageBrowser {
    field: EditorField,
    directory: PathBuf,
    entries: Vec<(PathBuf, bool)>,
    selected: Option<usize>,
    error: Option<String>,
}

struct VirtualKeyboard {
    target: KeyboardTarget,
    value: String,
    cursor: usize,
    row: usize,
    column: usize,
    uppercase: bool,
    symbols: bool,
}

#[derive(Debug, Clone, Copy)]
enum KeyboardTarget {
    Search,
    CategoryName,
    LocalTitle,
    LocalPath,
    LocalArguments,
    LocalWorkingDirectory,
    Editor(EditorField),
}

struct RunningSession {
    id: String,
    game: Game,
    token: String,
    launcher_pid: u32,
    child: Child,
    child_code: Option<Option<i32>>,
    started: Instant,
    started_at: String,
    observed: bool,
    timed_out: bool,
    polling: bool,
    behavior_applied: bool,
}

struct FocusTransition {
    from: usize,
    to: usize,
    started: Instant,
}

struct App {
    library: Library,
    games: Vec<Game>,
    categories: Vec<String>,
    category_name: String,
    category_rename_target: Option<String>,
    category_games_open: Option<String>,
    category_games_query: String,
    category_icon_query: String,
    category_icon_provider: String,
    category_icon_target: Option<String>,
    category_icon_path: String,
    category_icon_results: Vec<category_icons::IconOption>,
    category_icon_page: usize,
    category_icons_searching: bool,
    query: String,
    category: Option<String>,
    selected: Option<String>,
    cursor: usize,
    gamepad: Option<controls::Gamepad>,
    window_id: Option<iced::window::Id>,
    window_width: f32,
    window_height: f32,
    grid_columns: usize,
    window_focused: bool,
    session_hidden: bool,
    virtual_keyboard: Option<VirtualKeyboard>,
    external_keyboard_provider: Option<String>,
    update_release: Option<updates::Release>,
    update_status: Option<String>,
    update_checking: bool,
    update_installing: bool,
    page: usize,
    notice: Option<String>,
    running: Option<RunningSession>,
    scanning: bool,
    scraping: bool,
    scrape_cancel: Arc<AtomicBool>,
    add_open: bool,
    local_title: String,
    local_path: String,
    local_arguments: String,
    local_cwd: String,
    settings: Value,
    layout: String,
    pending_remove: Option<String>,
    editor: Option<EditDraft>,
    image_browser: Option<ImageBrowser>,
    images: HashMap<String, iced::widget::image::Handle>,
    background_images: HashMap<String, iced::widget::image::Handle>,
    displayed_background_key: Option<String>,
    background_transition: Option<(String, Instant)>,
    prefetch_image_paths: Vec<String>,
    prefetch_background_paths: Vec<String>,
    page_transition_pending: bool,
    focus_transition: Option<FocusTransition>,
    layout_transition_started: Option<Instant>,
    pending_background_refresh: Option<Instant>,
    pending_composite: Option<(String, String, String)>,
    settings_open: bool,
    menu_open: bool,
    settings_section: String,
    artwork_field: String,
    artwork_results: Vec<ArtworkOption>,
    artwork_searching: bool,
    metadata_results: Vec<MetadataOption>,
    metadata_searching: bool,
    image_generation: u64,
    image_generation_signal: Arc<AtomicU64>,
    layout_save_generation: u64,
    layout_save_signal: Arc<AtomicU64>,
    image_paths: Vec<String>,
    images_dirty: bool,
    last_activity: Instant,
    last_slide: Instant,
    screensaver_active: bool,
    screensaver_index: usize,
    screensaver_paths: Vec<String>,
    screensaver_previous_path: Option<String>,
    screensaver_transition_started: Option<Instant>,
    launcher_states: HashMap<String, String>,
    launcher_pending: HashMap<String, (bool, Instant)>,
    launcher_busy: bool,
}

impl App {
    fn load_image_directory(directory: PathBuf) -> Task<Message> {
        let result_directory = directory.clone();
        Task::perform(
            async move {
                tokio::task::spawn_blocking(move || {
                    let mut entries = fs::read_dir(&directory)
                        .map_err(|error| error.to_string())?
                        .filter_map(Result::ok)
                        .filter_map(|entry| {
                            let path = entry.path();
                            let is_dir = path.is_dir();
                            let is_image = is_supported_image_path(&path);
                            (is_dir || is_image).then_some((path, is_dir))
                        })
                        .collect::<Vec<_>>();
                    entries.sort_by_key(|(path, is_dir)| {
                        (
                            !is_dir,
                            path.file_name()
                                .unwrap_or_default()
                                .to_string_lossy()
                                .to_lowercase(),
                        )
                    });
                    Ok(entries)
                })
                .await
                .map_err(|error| error.to_string())
                .and_then(|result| result)
            },
            move |result| Message::ImageDirectoryLoaded(result_directory, result),
        )
    }

    fn new() -> (Self, Task<Message>) {
        let library = Library::open_default();
        let games = library.games();
        let categories = library.categories(&games);
        let resume = take_resume_file();
        let saved_category = resume
            .as_ref()
            .and_then(|state| state.get("category"))
            .and_then(Value::as_str)
            .filter(|category| categories.iter().any(|value| value == category))
            .map(str::to_owned);
        let initial_category =
            saved_category.or_else(|| library.primary_category().map(str::to_owned));
        let mut notice = library.load_error().map(str::to_owned);
        let mut settings = match library.settings() {
            Ok(settings) => settings,
            Err(error) => {
                notice.get_or_insert_with(|| format!("No se pudieron leer los ajustes: {error}"));
                Value::Object(Map::new())
            }
        };
        settings::initialize(&mut settings);
        let layout = settings
            .get("layout")
            .and_then(Value::as_str)
            .filter(|value| ["list", "grid", "carousel", "ps5"].contains(value))
            .unwrap_or("grid")
            .to_owned();
        let mut app = Self {
            library,
            games,
            categories,
            category_name: String::new(),
            category_rename_target: None,
            category_games_open: None,
            category_games_query: String::new(),
            category_icon_query: String::new(),
            category_icon_provider: "bootstrap".into(),
            category_icon_target: None,
            category_icon_path: String::new(),
            category_icon_results: Vec::new(),
            category_icon_page: 0,
            category_icons_searching: false,
            query: resume
                .as_ref()
                .and_then(|state| state.get("query"))
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_owned(),
            category: initial_category,
            selected: resume
                .as_ref()
                .and_then(|state| state.get("selected"))
                .and_then(Value::as_str)
                .map(str::to_owned),
            cursor: resume
                .as_ref()
                .and_then(|state| state.get("cursor"))
                .and_then(Value::as_u64)
                .unwrap_or_default() as usize,
            gamepad: controls::Gamepad::open().ok(),
            window_id: None,
            window_width: 1180.0,
            window_height: 800.0,
            grid_columns: 3,
            window_focused: true,
            session_hidden: false,
            virtual_keyboard: None,
            external_keyboard_provider: None,
            update_release: None,
            update_status: None,
            update_checking: false,
            update_installing: false,
            page: 0,
            notice,
            running: None,
            scanning: false,
            scraping: false,
            scrape_cancel: Arc::new(AtomicBool::new(false)),
            add_open: false,
            local_title: String::new(),
            local_path: String::new(),
            local_arguments: String::new(),
            local_cwd: String::new(),
            settings,
            layout,
            pending_remove: None,
            editor: None,
            image_browser: None,
            images: HashMap::new(),
            background_images: HashMap::new(),
            displayed_background_key: None,
            background_transition: None,
            prefetch_image_paths: Vec::new(),
            prefetch_background_paths: Vec::new(),
            page_transition_pending: false,
            focus_transition: None,
            layout_transition_started: None,
            pending_background_refresh: None,
            pending_composite: None,
            settings_open: false,
            menu_open: false,
            settings_section: "global".into(),
            artwork_field: "cover".into(),
            artwork_results: Vec::new(),
            artwork_searching: false,
            metadata_results: Vec::new(),
            metadata_searching: false,
            image_generation: 0,
            image_generation_signal: Arc::new(AtomicU64::new(0)),
            layout_save_generation: 0,
            layout_save_signal: Arc::new(AtomicU64::new(0)),
            image_paths: Vec::new(),
            images_dirty: false,
            last_activity: Instant::now(),
            last_slide: Instant::now(),
            screensaver_active: false,
            screensaver_index: 0,
            screensaver_paths: Vec::new(),
            screensaver_previous_path: None,
            screensaver_transition_started: None,
            launcher_states: HashMap::new(),
            launcher_pending: HashMap::new(),
            launcher_busy: false,
        };
        let filtered_count = app.filtered().len();
        app.cursor = if filtered_count == 0 {
            0
        } else {
            app.cursor.min(filtered_count - 1)
        };
        if app
            .selected
            .as_ref()
            .is_some_and(|id| !app.games.iter().any(|game| game.id() == id))
        {
            app.selected = None;
        }
        app.page = app.cursor / app.page_size();
        app.grid_columns = app.columns_for_width(app.window_width);
        app.refresh_images();
        app.images_dirty = false;
        let update_check = if app
            .settings
            .get("check_updates_on_start")
            .and_then(Value::as_bool)
            == Some(true)
        {
            Task::done(Message::CheckUpdates)
        } else {
            Task::none()
        };
        let start_launchers = if ["steam", "faugus", "heroic"].iter().any(|name| {
            app.settings
                .get(format!("start_{name}_on_start"))
                .and_then(Value::as_bool)
                == Some(true)
        }) {
            Task::done(Message::StartLaunchers)
        } else {
            Task::none()
        };
        let task = Task::batch([
            app.image_loading_task(),
            iced::window::latest().map(Message::WindowReady),
            update_check,
            start_launchers,
        ]);
        (app, task)
    }

    fn subscription(&self) -> Subscription<Message> {
        let session = if self.running.is_some() {
            iced::time::every(Duration::from_millis(500)).map(|_| Message::PollSession)
        } else {
            Subscription::none()
        };
        let activity = iced::event::listen_with(|event, status, _| {
            if status == iced::event::Status::Captured {
                return Some(Message::Activity);
            }
            match event {
                iced::Event::Keyboard(iced::keyboard::Event::KeyPressed {
                    key,
                    modifiers,
                    text,
                    ..
                }) => {
                    let action = match key.as_ref() {
                        iced::keyboard::key::Key::Named(iced::keyboard::key::Named::ArrowLeft) => {
                            "left"
                        }
                        iced::keyboard::key::Key::Named(iced::keyboard::key::Named::ArrowRight) => {
                            "right"
                        }
                        iced::keyboard::key::Key::Named(iced::keyboard::key::Named::ArrowUp) => {
                            "up"
                        }
                        iced::keyboard::key::Key::Named(iced::keyboard::key::Named::ArrowDown) => {
                            "down"
                        }
                        iced::keyboard::key::Key::Named(iced::keyboard::key::Named::Enter) => {
                            "confirm"
                        }
                        iced::keyboard::key::Key::Named(iced::keyboard::key::Named::Space) => {
                            "play"
                        }
                        iced::keyboard::key::Key::Named(iced::keyboard::key::Named::Escape) => {
                            "back"
                        }
                        iced::keyboard::key::Key::Named(iced::keyboard::key::Named::PageUp) => {
                            "page_previous"
                        }
                        iced::keyboard::key::Key::Named(iced::keyboard::key::Named::PageDown) => {
                            "page_next"
                        }
                        iced::keyboard::key::Key::Character("f") if modifiers.control() => "search",
                        iced::keyboard::key::Key::Character("m") if modifiers.control() => "menu",
                        iced::keyboard::key::Key::Named(iced::keyboard::key::Named::Tab)
                            if modifiers.control() =>
                        {
                            "appearance"
                        }
                        _ => {
                            return text
                                .map(|text| Message::KeyboardText(text.to_string()))
                                .or(Some(Message::Activity));
                        }
                    };
                    Some(Message::ControllerAction(action))
                }
                iced::Event::Mouse(iced::mouse::Event::WheelScrolled { delta }) => {
                    let (x, y) = match delta {
                        iced::mouse::ScrollDelta::Lines { x, y }
                        | iced::mouse::ScrollDelta::Pixels { x, y } => (x, y),
                    };
                    Some(Message::MouseWheel { x, y })
                }
                iced::Event::Keyboard(_) | iced::Event::Mouse(_) => Some(Message::Activity),
                iced::Event::Window(iced::window::Event::Focused) => {
                    Some(Message::WindowFocus(true))
                }
                iced::Event::Window(iced::window::Event::Unfocused) => {
                    Some(Message::WindowFocus(false))
                }
                iced::Event::Window(iced::window::Event::Resized(size)) => {
                    Some(Message::WindowResized(size))
                }
                _ => None,
            }
        });
        let gamepad = self
            .gamepad
            .as_ref()
            .map_or_else(Subscription::none, |gamepad| {
                let interval = if gamepad.is_connected() { 16 } else { 250 };
                iced::time::every(Duration::from_millis(interval)).map(|_| Message::PollGamepad)
            });
        let screensaver_enabled = self.screensaver_active
            || self
                .settings
                .get("screensaver_enabled")
                .and_then(Value::as_bool)
                == Some(true);
        let idle = if screensaver_enabled {
            iced::time::every(Duration::from_secs(1)).map(|_| Message::IdleTick)
        } else {
            Subscription::none()
        };
        let animation = if self.focus_transition.is_some()
            || self.layout_transition_started.is_some()
            || self.background_transition.is_some()
            || self.pending_background_refresh.is_some()
            || self.screensaver_previous_path.is_some()
        {
            iced::time::every(Duration::from_millis(16)).map(|_| Message::AnimationTick)
        } else {
            Subscription::none()
        };
        let launcher_status = if self.settings_open {
            iced::time::every(Duration::from_secs(3)).map(|_| Message::PollLaunchers)
        } else {
            Subscription::none()
        };
        Subscription::batch([session, activity, gamepad, idle, animation, launcher_status])
    }

    fn update(&mut self, message: Message) -> Task<Message> {
        match message {
            Message::Search(query) => {
                self.query = query;
                self.page = 0;
                self.set_cursor(0);
                self.refresh_images();
            }
            Message::Category(category) => {
                self.category = category;
                self.menu_open = false;
                self.page = 0;
                self.set_cursor(0);
                self.refresh_images();
            }
            Message::CategoryName(name) => self.category_name = name,
            Message::AddCategory => match self.library.add_category(&self.category_name) {
                Ok(()) => {
                    self.categories = self.library.categories(&self.games);
                    self.category_name.clear();
                    self.notice = Some("Categoría añadida.".into());
                }
                Err(error) => self.notice = Some(error.to_string()),
            },
            Message::RenameCategoryStart(name) => {
                if name.is_empty() {
                    self.category_rename_target = None;
                    self.category_name.clear();
                } else {
                    self.category_rename_target = Some(name.clone());
                    self.category_name = name;
                }
            }
            Message::RenameCategorySave => {
                if let Some(previous) = self.category_rename_target.take() {
                    match self.library.rename_category(&previous, &self.category_name) {
                        Ok(()) => {
                            self.games = self.library.games();
                            self.categories = self.library.categories(&self.games);
                            if self.category.as_deref() == Some(&previous) {
                                self.category = Some(self.category_name.trim().to_owned());
                            }
                            self.category_name.clear();
                            self.notice = Some("Categoría renombrada.".into());
                            self.refresh_images();
                        }
                        Err(error) => {
                            self.category_rename_target = Some(previous);
                            self.notice = Some(error.to_string());
                        }
                    }
                }
            }
            Message::MoveCategory(name, step) => {
                match self.library.move_category(&name, step, &self.games) {
                    Ok(()) => {
                        self.categories = self.library.categories(&self.games);
                        self.notice = Some("Orden de categorías actualizado.".into());
                    }
                    Err(error) => self.notice = Some(error.to_string()),
                }
            }
            Message::SetPrimaryCategory(name) => {
                match self
                    .library
                    .set_primary_category(name.as_deref(), &self.games)
                {
                    Ok(()) => {
                        self.notice = Some("Categoría principal guardada.".into());
                    }
                    Err(error) => self.notice = Some(error.to_string()),
                }
            }
            Message::ToggleCategoryGames(name) => {
                self.category_games_open =
                    (self.category_games_open.as_deref() != Some(&name)).then_some(name);
                self.category_games_query.clear();
            }
            Message::CategoryGamesQuery(query) => self.category_games_query = query,
            Message::SetCategoryGame(category, id, selected) => {
                match self.library.set_category_member(&category, &id, selected) {
                    Ok(()) => {
                        self.games = self.library.games();
                        self.categories = self.library.categories(&self.games);
                        self.notice = Some("Categoría guardada.".into());
                        self.refresh_images();
                    }
                    Err(error) => self.notice = Some(error.to_string()),
                }
            }
            Message::CategoryIconQuery(query) => self.category_icon_query = query,
            Message::CategoryIconProvider(provider) => {
                self.category_icon_provider = provider;
                self.category_icon_results.clear();
                self.category_icon_page = 0;
            }
            Message::CategoryIconTarget(category) => {
                self.category_icon_path = self
                    .library
                    .category_icon_path(category.as_deref().unwrap_or_default())
                    .map(|path| path.to_string_lossy().into_owned())
                    .unwrap_or_default();
                self.category_icon_target = category;
                self.refresh_images();
            }
            Message::SearchCategoryIcons => {
                if self.category_icons_searching {
                    return Task::none();
                }
                self.category_icons_searching = true;
                self.category_icon_page = 0;
                let provider = self.category_icon_provider.clone();
                let query = self.category_icon_query.clone();
                let cache = self.library.category_icons_dir();
                return Task::perform(
                    async move {
                        tokio::task::spawn_blocking(move || {
                            category_icons::search(&provider, &query, &cache)
                        })
                        .await
                        .map_err(|error| error.to_string())
                        .and_then(|result| result)
                    },
                    Message::CategoryIconsSearched,
                );
            }
            Message::CategoryIconsSearched(result) => {
                self.category_icons_searching = false;
                match result {
                    Ok(results) => {
                        self.notice = Some(format!("{} iconos encontrados.", results.len()));
                        self.category_icon_results = results;
                    }
                    Err(error) => self.notice = Some(error),
                }
            }
            Message::CategoryIconPage(step) => {
                let pages = self.category_icon_results.len().div_ceil(12);
                if pages > 0 {
                    self.category_icon_page = (self.category_icon_page as isize + step)
                        .clamp(0, pages as isize - 1)
                        as usize;
                }
            }
            Message::ChooseCategoryIcon(option, category) => {
                let cache = self.library.category_icons_dir();
                return Task::perform(
                    async move {
                        tokio::task::spawn_blocking(move || {
                            category_icons::download(&option, &cache)
                                .map(|path| (option, path, category))
                        })
                        .await
                        .map_err(|error| error.to_string())
                        .and_then(|result| result)
                    },
                    Message::CategoryIconDownloaded,
                );
            }
            Message::CategoryIconDownloaded(result) => match result {
                Ok((option, path, category)) => {
                    let credit = serde_json::json!({
                        "name": option.name,
                        "source": option.source,
                        "author": option.author,
                        "license": option.license,
                        "provider": option.provider,
                    });
                    match self.library.import_category_icon(
                        category.as_deref(),
                        &path,
                        Some(credit),
                    ) {
                        Ok(()) => {
                            self.category_icon_path = path.to_string_lossy().into_owned();
                            self.notice = Some("Icono guardado.".into());
                            self.refresh_images();
                        }
                        Err(error) => self.notice = Some(error.to_string()),
                    }
                }
                Err(error) => self.notice = Some(error),
            },
            Message::CategoryIconLocalPath(path) => self.category_icon_path = path,
            Message::UseLocalCategoryIcon => {
                let path = PathBuf::from(self.category_icon_path.trim());
                match self.library.import_category_icon(
                    self.category_icon_target.as_deref(),
                    &path,
                    None,
                ) {
                    Ok(()) => {
                        self.category_icon_path = self
                            .library
                            .category_icon_path(
                                self.category_icon_target.as_deref().unwrap_or_default(),
                            )
                            .map(|path| path.to_string_lossy().into_owned())
                            .unwrap_or_default();
                        self.notice = Some("Icono local guardado.".into());
                        self.refresh_images();
                    }
                    Err(error) => self.notice = Some(error.to_string()),
                }
            }
            Message::ClearCategoryIcon => {
                match self
                    .library
                    .clear_category_icon(self.category_icon_target.as_deref())
                {
                    Ok(()) => {
                        self.category_icon_path.clear();
                        self.notice = Some("Icono eliminado.".into());
                        self.refresh_images();
                    }
                    Err(error) => self.notice = Some(error.to_string()),
                }
            }
            Message::RemoveCategory(name) => match self.library.remove_category(&name) {
                Ok(()) => {
                    self.games = self.library.games();
                    self.categories = self.library.categories(&self.games);
                    if self.category.as_deref() == Some(&name) {
                        self.category = None;
                        self.page = 0;
                        self.set_cursor(0);
                    }
                    self.refresh_images();
                    self.notice = Some(format!("Categoría «{name}» eliminada."));
                }
                Err(error) => self.notice = Some(error.to_string()),
            },
            Message::Select(id) => {
                if let Some(index) = self.filtered().iter().position(|game| game.id() == id) {
                    self.set_cursor(index);
                    self.page = index / self.page_size();
                    self.refresh_images();
                }
            }
            Message::WindowReady(id) => self.window_id = id,
            Message::WindowResized(size) => {
                let previous_background_size =
                    active_background_decode_size(self.window_width, self.window_height);
                self.window_width = size.width;
                self.window_height = size.height;
                self.grid_columns = self.columns_for_width(size.width);
                if active_background_decode_size(size.width, size.height)
                    != previous_background_size
                {
                    self.pending_background_refresh =
                        Some(Instant::now() + Duration::from_millis(200));
                }
            }
            Message::MouseWheel { x, y } => {
                let amount = if y.abs() >= x.abs() { y } else { x };
                if matches!(self.layout.as_str(), "list" | "carousel") && amount != 0.0 {
                    self.apply_controller_action(if amount > 0.0 { "down" } else { "up" });
                } else {
                    self.last_activity = Instant::now();
                }
            }
            Message::WindowFocus(focused) => self.window_focused = focused,
            Message::Back => {
                if let Some(provider) = self.external_keyboard_provider.take() {
                    return Task::perform(
                        async move {
                            tokio::task::spawn_blocking(move || system_keyboard::hide(&provider))
                                .await
                                .map_err(|error| error.to_string())
                                .and_then(|result| result)
                        },
                        Message::SystemKeyboardHidden,
                    );
                }
                self.selected = None;
                self.editor = None;
                self.refresh_images();
            }
            Message::PollGamepad => {
                let actions = self
                    .gamepad
                    .as_mut()
                    .map(|gamepad| gamepad.poll(self.window_focused))
                    .unwrap_or_default();
                for action in actions {
                    if action == "exit" {
                        return Task::done(Message::ControllerAction(action));
                    }
                    self.apply_controller_action(action);
                }
            }
            Message::ControllerAction("back" | "exit")
                if self.external_keyboard_provider.is_some() =>
            {
                let provider = self.external_keyboard_provider.take().unwrap();
                return Task::perform(
                    async move {
                        tokio::task::spawn_blocking(move || system_keyboard::hide(&provider))
                            .await
                            .map_err(|error| error.to_string())
                            .and_then(|result| result)
                    },
                    Message::SystemKeyboardHidden,
                );
            }
            Message::ControllerAction("exit")
                if self.virtual_keyboard.is_some()
                    || self.menu_open
                    || self.selected.is_some()
                    || self.settings_open
                    || self.add_open
                    || self.editor.is_some() =>
            {
                self.apply_controller_action("back");
            }
            Message::ControllerAction("exit") => return iced::exit(),
            Message::ControllerAction(action) => self.apply_controller_action(action),
            Message::KeyboardText(text) => {
                self.last_activity = Instant::now();
                if let Some(keyboard) = self.virtual_keyboard.as_mut() {
                    insert_at_cursor(&mut keyboard.value, &mut keyboard.cursor, &text);
                }
            }
            Message::KeyboardInsert(text) => self.keyboard_command(&format!("insert:{text}")),
            Message::KeyboardCommand(command) => self.keyboard_command(command),
            Message::OpenKeyboard(target) => return self.request_keyboard(target),
            Message::SystemKeyboardOpened(target, fallback, result) => match result {
                Ok(provider) if provider == "builtin" => self.open_keyboard(target),
                Ok(provider) => {
                    self.external_keyboard_provider = Some(provider.clone());
                    self.notice = Some(match provider.as_str() {
                        "cosmic" => "Solicitud enviada a COSMIC OSK. Pulsa Volver para regresar a Estante.".into(),
                        "kde" => "Teclado virtual de KWin activado. Pulsa Volver para regresar a Estante.".into(),
                        _ => "Teclado del sistema abierto.".into(),
                    });
                }
                Err(error) if fallback => {
                    self.notice = Some(format!(
                        "{error}\nSe usará el teclado de Estante como alternativa."
                    ));
                    self.open_keyboard(target);
                }
                Err(error) => self.notice = Some(error),
            },
            Message::SystemKeyboardHidden(result) => {
                if let Err(error) = result {
                    self.notice =
                        Some(format!("No se pudo cerrar el teclado del sistema: {error}"));
                }
            }
            Message::CheckUpdates => {
                if self.update_checking || self.update_installing {
                    return Task::none();
                }
                self.update_checking = true;
                self.update_status = Some("Buscando versiones públicas…".into());
                return Task::perform(
                    async {
                        tokio::task::spawn_blocking(updates::latest_release)
                            .await
                            .map_err(|error| error.to_string())
                            .and_then(|result| result)
                    },
                    Message::UpdateChecked,
                );
            }
            Message::UpdateChecked(result) => {
                self.update_checking = false;
                match result {
                    Ok(Some(release)) => {
                        self.update_status = Some(if updates::appimage_path().is_some() {
                            format!(
                                "Versión {} disponible. Descarga verificada lista para instalar.",
                                release.version
                            )
                        } else {
                            format!("Versión {} disponible: {}", release.version, release.url)
                        });
                        self.update_release = Some(release);
                    }
                    Ok(None) => {
                        self.update_release = None;
                        self.update_status = Some("Estante está actualizado.".into());
                    }
                    Err(error) => {
                        self.update_release = None;
                        self.update_status = Some(format!("No se pudo comprobar: {error}"));
                    }
                }
            }
            Message::InstallUpdate(release) => {
                if self.update_installing || self.update_checking {
                    return Task::none();
                }
                let Some(path) = updates::appimage_path() else {
                    self.update_status =
                        Some("La actualización integrada solo funciona desde el AppImage.".into());
                    return Task::none();
                };
                self.update_installing = true;
                self.update_status = Some("Descargando y verificando la actualización…".into());
                return Task::perform(
                    async move {
                        tokio::task::spawn_blocking(move || {
                            updates::install_appimage(&release, &path)
                        })
                        .await
                        .map_err(|error| error.to_string())
                        .and_then(|result| result)
                    },
                    Message::UpdateInstalled,
                );
            }
            Message::UpdateInstalled(result) => {
                self.update_installing = false;
                self.update_status = Some(match result {
                    Ok(version) => {
                        self.update_release = None;
                        format!(
                            "Estante {version} instalado. Cierra y vuelve a abrir la aplicación."
                        )
                    }
                    Err(error) => format!("No se instaló la actualización: {error}"),
                })
            }
            Message::StartLaunchers => {
                let settings = self.settings.clone();
                return Task::perform(
                    async move {
                        tokio::task::spawn_blocking(move || launchers::start_configured(&settings))
                            .await
                            .map_err(|error| error.to_string())
                    },
                    Message::LaunchersStarted,
                );
            }
            Message::PollLaunchers => {
                return Task::perform(
                    async {
                        tokio::task::spawn_blocking(launchers::running_clients)
                            .await
                            .map(|result| {
                                result
                                    .map(|clients| clients.into_iter().map(str::to_owned).collect())
                            })
                            .map_err(|error| error.to_string())
                            .and_then(|result| result.map_err(|error| error.to_string()))
                    },
                    Message::LaunchersPolled,
                );
            }
            Message::LaunchersPolled(result) => match result {
                Ok(running) => {
                    for client in ["steam", "faugus", "heroic"] {
                        let open = running.iter().any(|name| name == client);
                        let state = if let Some((opening, deadline)) =
                            self.launcher_pending.get(client).copied()
                        {
                            let target_reached = open == opening;
                            if target_reached {
                                self.launcher_pending.remove(client);
                                if open { "open" } else { "closed" }
                            } else if Instant::now() >= deadline {
                                self.launcher_pending.remove(client);
                                "timeout"
                            } else if opening {
                                "opening"
                            } else {
                                "closing"
                            }
                        } else if open {
                            "open"
                        } else if matches!(
                            self.launcher_states.get(client).map(String::as_str),
                            Some("error" | "missing" | "timeout")
                        ) {
                            self.launcher_states
                                .get(client)
                                .map(String::as_str)
                                .unwrap_or("closed")
                        } else {
                            "closed"
                        };
                        self.launcher_states.insert(client.into(), state.into());
                    }
                }
                Err(error) => {
                    self.notice = Some(format!("No se pudo consultar lanzadores: {error}"))
                }
            },
            Message::ManageLauncher(client, opening) => {
                if self.launcher_busy {
                    return Task::none();
                }
                self.launcher_busy = true;
                self.launcher_states.insert(
                    client.clone(),
                    if opening { "opening" } else { "closing" }.into(),
                );
                self.launcher_pending.insert(
                    client.clone(),
                    (opening, Instant::now() + Duration::from_secs(45)),
                );
                let action_client = client.clone();
                return Task::perform(
                    async move {
                        tokio::task::spawn_blocking(move || {
                            launchers::operate(&action_client, opening).map(|()| {
                                format!(
                                    "{} {}.",
                                    action_client,
                                    if opening { "abierto" } else { "cerrado" }
                                )
                            })
                        })
                        .await
                        .map_err(|error| error.to_string())
                        .and_then(|result| result)
                    },
                    move |result| Message::LauncherActionFinished(client, opening, result),
                );
            }
            Message::LauncherActionFinished(client, opening, result) => {
                self.launcher_busy = false;
                self.notice = Some(result.unwrap_or_else(|error| {
                    self.launcher_pending.remove(&client);
                    let state = if error.contains("No se encontró")
                        || error.contains("No está instalado")
                    {
                        "missing"
                    } else {
                        "error"
                    };
                    self.launcher_states.insert(client.clone(), state.into());
                    format!("No se pudo gestionar el lanzador: {error}")
                }));
                if self.launcher_pending.contains_key(&client) {
                    self.launcher_states
                        .insert(client, if opening { "opening" } else { "closing" }.into());
                }
                return Task::done(Message::PollLaunchers);
            }
            Message::LaunchersStarted(result) => match result {
                Ok(issues) if !issues.is_empty() => {
                    self.notice = Some(format!(
                        "No se iniciaron algunos lanzadores: {}",
                        issues.join(" · ")
                    ))
                }
                Err(error) => {
                    self.notice = Some(format!("No se pudieron iniciar los lanzadores: {error}"))
                }
                _ => (),
            },
            Message::Launch(id) => self.launch(id),
            Message::PollSession => {
                let Some(session) = self.running.as_mut() else {
                    return Task::none();
                };
                if session.polling {
                    return Task::none();
                }
                if session.child_code.is_none() {
                    match session.child.try_wait() {
                        Ok(Some(status)) => session.child_code = Some(status.code()),
                        Ok(None) => (),
                        Err(error) => {
                            self.running = None;
                            self.notice = Some(format!("No se pudo observar el proceso: {error}"));
                            self.refresh_images();
                            return Task::none();
                        }
                    }
                }
                session.polling = true;
                let game = session.game.clone();
                let launcher_pid = session.launcher_pid;
                let token = session.token.clone();
                return Task::perform(
                    async move {
                        tokio::task::spawn_blocking(move || {
                            Library::matching_game_processes(&game, launcher_pid, &token)
                        })
                        .await
                        .map_err(|error| error.to_string())
                    },
                    Message::ProcessesPolled,
                );
            }
            Message::ProcessesPolled(result) => {
                let processes = match result {
                    Ok(processes) => processes,
                    Err(error) => {
                        self.running = None;
                        self.notice = Some(format!("No se pudo observar el proceso: {error}"));
                        self.refresh_images();
                        if self.session_hidden {
                            self.session_hidden = false;
                            if let Some(id) = self.window_id {
                                return iced::window::minimize(id, false);
                            }
                        }
                        return Task::none();
                    }
                };
                let (start_behavior, finished) = {
                    let Some(session) = self.running.as_mut() else {
                        return Task::none();
                    };
                    session.polling = false;
                    let was_observed = session.observed;
                    session.observed |= !processes.is_empty();
                    let start_behavior =
                        !was_observed && session.observed && !session.behavior_applied;
                    session.behavior_applied |= start_behavior;
                    let external = matches!(session.game.kind(), "steam" | "heroic");
                    if external
                        && !session.observed
                        && session.started.elapsed() >= Duration::from_secs(90)
                    {
                        session.timed_out = true;
                    }
                    let timeout =
                        session.timed_out && session.child_code.is_some() && processes.is_empty();
                    let done = session.child_code.is_some()
                        && processes.is_empty()
                        && (!external || session.observed || timeout);
                    let finished = done.then(|| {
                        (
                            session.id.clone(),
                            session.started.elapsed().as_secs(),
                            session.started_at.clone(),
                            session.child_code.flatten(),
                            timeout,
                        )
                    });
                    (start_behavior, finished)
                };
                if start_behavior {
                    match self.playing_behavior() {
                        "screensaver" => {
                            self.activate_screensaver();
                        }
                        "hide" => {
                            let Some(session) = self.running.as_ref() else {
                                return Task::none();
                            };
                            let handoff = supervisor::Handoff {
                                game_id: session.id.clone(),
                                launcher_pid: session.launcher_pid,
                                token: session.token.clone(),
                                root: self.library.data_dir().to_path_buf(),
                                started_at: session.started_at.clone(),
                                started_uptime: supervisor::uptime_seconds().unwrap_or_default()
                                    - session.started.elapsed().as_secs_f64(),
                                restore: json!({
                                    "query": self.query,
                                    "category": self.category,
                                    "selected": self.selected,
                                    "cursor": self.cursor,
                                }),
                            };
                            return Task::perform(
                                async move {
                                    match tokio::task::spawn_blocking(move || {
                                        supervisor::prepare(handoff)
                                    })
                                    .await
                                    {
                                        Ok(result) => result,
                                        Err(error) => Err(error.to_string()),
                                    }
                                },
                                Message::SupervisorPrepared,
                            );
                        }
                        "tray" => {
                            if let Some(id) = self.window_id {
                                self.session_hidden = true;
                                return iced::window::minimize(id, true);
                            }
                        }
                        _ => (),
                    }
                }
                if let Some((id, seconds, started_at, code, timeout)) = finished {
                    self.running = None;
                    self.screensaver_active = false;
                    if timeout {
                        self.notice =
                            Some("No se detectó el proceso del juego en 90 segundos.".into());
                    } else {
                        self.notice = Some("Partida finalizada; actividad guardada.".into());
                        if let Err(error) =
                            self.library.record_session(&id, seconds, &started_at, code)
                        {
                            self.notice = Some(format!("No se pudo guardar la actividad: {error}"));
                        }
                    }
                    if self.session_hidden {
                        self.session_hidden = false;
                        if let Some(id) = self.window_id {
                            self.refresh_images();
                            return iced::window::minimize(id, false);
                        }
                    }
                    self.refresh_images();
                }
            }
            Message::SupervisorPrepared(result) => match result {
                Ok(folder) => match fs::write(folder.join("handoff"), []) {
                    Ok(()) => return iced::exit(),
                    Err(error) => {
                        let _ = fs::write(folder.join("cancel"), []);
                        self.notice = Some(format!(
                            "No se pudo cerrar Estante durante la partida: {error}"
                        ));
                    }
                },
                Err(error) => {
                    self.notice = Some(format!(
                        "No se pudo cerrar Estante durante la partida: {error}"
                    ));
                }
            },
            Message::ScanImports => {
                if self.scanning {
                    return Task::none();
                }
                self.scanning = true;
                self.notice = Some("Buscando juegos de Steam y Faugus…".into());
                return Task::perform(
                    async {
                        tokio::task::spawn_blocking(|| {
                            let mut library = Library::open_default();
                            let (steam_added, steam_total) = library.scan_steam()?;
                            let (faugus_added, faugus_total) = library.scan_faugus()?;
                            let (heroic_added, heroic_total) = library.scan_heroic()?;
                            Ok::<_, std::io::Error>((
                                steam_added + faugus_added + heroic_added,
                                steam_total + faugus_total + heroic_total,
                            ))
                        })
                        .await
                        .map_err(|error| error.to_string())
                        .and_then(|result| result.map_err(|error| error.to_string()))
                    },
                    Message::ScanFinished,
                );
            }
            Message::ScanFinished(result) => {
                self.scanning = false;
                match result {
                    Ok((added, total)) => {
                        self.library = Library::open_default();
                        self.games = self.library.games();
                        self.categories = self.library.categories(&self.games);
                        self.refresh_images();
                        self.notice = Some(format!(
                            "Escaneo terminado: {added} nuevos; {total} encontrados."
                        ));
                    }
                    Err(error) => {
                        self.notice = Some(format!("No se pudo escanear la biblioteca: {error}"))
                    }
                }
            }
            Message::ScanProvider(source) => {
                if self.scanning || !["steam", "faugus", "heroic"].contains(&source.as_str()) {
                    return Task::none();
                }
                self.scanning = true;
                self.notice = Some(format!("Buscando juegos de {}…", source));
                return Task::perform(
                    async move {
                        tokio::task::spawn_blocking(move || {
                            let mut library = Library::open_default();
                            let (added, total) = match source.as_str() {
                                "steam" => library.scan_steam(),
                                "faugus" => library.scan_faugus(),
                                "heroic" => library.scan_heroic(),
                                _ => unreachable!(),
                            }?;
                            Ok::<_, std::io::Error>((source, added, total))
                        })
                        .await
                        .map_err(|error| error.to_string())
                        .and_then(|result| result.map_err(|error| error.to_string()))
                    },
                    Message::ScanProviderFinished,
                );
            }
            Message::ScanProviderFinished(result) => {
                self.scanning = false;
                match result {
                    Ok((source, added, total)) => {
                        self.library = Library::open_default();
                        self.games = self.library.games();
                        self.categories = self.library.categories(&self.games);
                        self.refresh_images();
                        self.notice = Some(format!(
                            "{}: {added} juegos nuevos de {total} encontrados.",
                            source
                        ));
                    }
                    Err(error) => self.notice = Some(format!("No se pudo escanear: {error}")),
                }
            }
            Message::Scrape(replace) => {
                if self.scraping {
                    return Task::none();
                }
                self.scraping = true;
                self.scrape_cancel.store(false, Ordering::Relaxed);
                self.notice = Some(
                    if replace {
                        "Reemplazando datos disponibles…"
                    } else {
                        "Completando datos que faltan…"
                    }
                    .into(),
                );
                let root = self.library.data_dir().to_path_buf();
                let key = self
                    .settings
                    .get("steamgriddb_key")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_owned();
                let language =
                    if self.settings.get("language").and_then(Value::as_str) == Some("es") {
                        "es"
                    } else {
                        "en"
                    }
                    .to_owned();
                let cancelled = self.scrape_cancel.clone();
                return Task::perform(
                    async move {
                        tokio::task::spawn_blocking(move || {
                            scraping::run(root, key, language, replace, cancelled)
                        })
                        .await
                        .map_err(|error| error.to_string())
                        .and_then(|result| result)
                    },
                    Message::ScrapeFinished,
                );
            }
            Message::CancelScrape => {
                self.scrape_cancel.store(true, Ordering::Relaxed);
                self.notice = Some("Cancelando después de la consulta actual…".into());
            }
            Message::ScrapeFinished(result) => {
                self.scraping = false;
                match result {
                    Ok((updated, errors, messages)) => {
                        self.library = self.library.reload();
                        self.games = self.library.games();
                        self.categories = self.library.categories(&self.games);
                        self.refresh_images();
                        self.notice = Some(format!(
                            "Scraping: {updated} juegos actualizados · {errors} errores. {}",
                            messages.join(" · ")
                        ));
                    }
                    Err(error) => self.notice = Some(format!("Falló el scraping: {error}")),
                }
            }
            Message::AddLocal => {
                self.menu_open = false;
                self.add_open = true;
            }
            Message::CancelLocal => self.add_open = false,
            Message::LocalTitle(value) => self.local_title = value,
            Message::LocalPath(value) => self.local_path = value,
            Message::LocalArguments(value) => self.local_arguments = value,
            Message::LocalWorkingDirectory(value) => self.local_cwd = value,
            Message::SaveLocal => {
                match self.library.add_local(
                    &self.local_title,
                    &self.local_path,
                    &self.local_arguments,
                    &self.local_cwd,
                ) {
                    Ok(()) => {
                        self.games = self.library.games();
                        self.categories = self.library.categories(&self.games);
                        self.refresh_images();
                        self.local_title.clear();
                        self.local_path.clear();
                        self.local_arguments.clear();
                        self.local_cwd.clear();
                        self.add_open = false;
                        self.notice = Some("Juego local añadido.".into());
                    }
                    Err(error) => self.notice = Some(error.to_string()),
                }
            }
            Message::LayoutSaved(generation, result) => {
                if generation == self.layout_save_generation {
                    if let Err(error) = result {
                        self.notice = Some(format!("No se pudieron guardar los ajustes: {error}"));
                    }
                }
            }
            Message::Settings => {
                self.menu_open = false;
                self.settings_open = !self.settings_open;
                if self.settings_open {
                    self.refresh_images();
                    return Task::done(Message::PollLaunchers);
                }
                self.refresh_images();
            }
            Message::ChangeLayout(layout) => {
                self.menu_open = false;
                return self.change_layout(layout);
            }
            Message::Exit => return iced::exit(),
            Message::SettingsSection(section) => {
                if [
                    "global",
                    "scan",
                    "categories",
                    "list",
                    "grid",
                    "carousel",
                    "ps5",
                ]
                .contains(&section.as_str())
                {
                    self.settings_section = section;
                    self.refresh_images();
                }
            }
            Message::PreviewScreensaver => {
                self.activate_screensaver();
            }
            Message::SetSettingPath(path, value) => {
                if path == ["layout"] {
                    if let Some(layout) = value.as_str() {
                        return self.change_layout(layout.to_owned());
                    }
                }
                let mut next = self.settings.clone();
                match settings::update(&mut next, &path, value.clone()) {
                    Ok(()) => match self.library.save_settings(&next) {
                        Ok(()) => {
                            self.settings = next;
                            self.grid_columns = self.columns_for_width(self.window_width);
                            if path == ["layout"] {
                                self.layout = value.as_str().unwrap_or("grid").to_owned();
                                self.refresh_images();
                            } else if (self.screensaver_active || self.settings_open)
                                && path
                                    .first()
                                    .is_some_and(|key| key.starts_with("screensaver_"))
                            {
                                self.refresh_images();
                            } else if path.first().is_some_and(|key| key == "background_blur") {
                                self.refresh_images();
                            }
                            self.notice = None;
                        }
                        Err(error) => {
                            self.notice =
                                Some(format!("No se pudieron guardar los ajustes: {error}"))
                        }
                    },
                    Err(error) => self.notice = Some(error),
                }
            }
            Message::SearchArtwork(field, provider) => {
                let Some(editor) = self.editor.as_ref() else {
                    return Task::none();
                };
                self.artwork_field = field.clone();
                self.artwork_searching = true;
                self.artwork_results.clear();
                let title = editor.title.clone();
                let settings = self.settings.clone();
                return Task::perform(
                    async move {
                        tokio::task::spawn_blocking(move || match provider.as_str() {
                            "igdb" => artwork::search_igdb(
                                settings
                                    .get("igdb_client_id")
                                    .and_then(Value::as_str)
                                    .unwrap_or_default(),
                                settings
                                    .get("igdb_client_secret")
                                    .and_then(Value::as_str)
                                    .unwrap_or_default(),
                                &title,
                            ),
                            _ => artwork::search(
                                settings
                                    .get("steamgriddb_key")
                                    .and_then(Value::as_str)
                                    .unwrap_or_default(),
                                &title,
                                &field,
                            ),
                        })
                        .await
                        .map_err(|error| error.to_string())
                        .and_then(|result| result)
                    },
                    Message::ArtworkSearchFinished,
                );
            }
            Message::ArtworkSearchFinished(result) => {
                self.artwork_searching = false;
                match result {
                    Ok(rows) => {
                        self.artwork_results = rows;
                        self.notice = Some(format!(
                            "{} imágenes encontradas.",
                            self.artwork_results.len()
                        ));
                    }
                    Err(error) => self.notice = Some(error),
                }
            }
            Message::ChooseArtwork(option) => {
                let field = self.artwork_field.clone();
                let root = self.library.artwork_cache_dir();
                return Task::perform(
                    async move {
                        tokio::task::spawn_blocking(move || {
                            artwork::download(&option, &root)
                                .map(|path| (field, path, option.game_id, option.provider))
                        })
                        .await
                        .map_err(|error| error.to_string())
                        .and_then(|result| result)
                    },
                    Message::ArtworkDownloaded,
                );
            }
            Message::ArtworkDownloaded(result) => match result {
                Ok((field, path, game_id, provider)) => {
                    if let Some(editor) = self.editor.as_mut() {
                        match field.as_str() {
                            "cover" => editor.cover = path,
                            "square_cover" => editor.square_cover = path,
                            "logo" => editor.logo = path,
                            "banner" => editor.banner = path,
                            "banner_secondary" => editor.banner_secondary = path,
                            _ => (),
                        }
                        if provider == "steamgriddb" {
                            editor.steamgriddb_id = game_id;
                        }
                    }
                    self.artwork_results.clear();
                    self.notice =
                        Some("Imagen descargada; guarda la ficha para aplicar el cambio.".into());
                }
                Err(error) => self.notice = Some(error),
            },
            Message::FetchSteamMetadata(id) => {
                let Some(game) = self.games.iter().find(|game| game.id() == id) else {
                    return Task::none();
                };
                let Some(app_id) = game.field("steam_appid").map(str::to_owned) else {
                    self.notice = Some("Este juego no tiene un ID de Steam.".into());
                    return Task::none();
                };
                return Task::perform(
                    async move {
                        tokio::task::spawn_blocking(move || {
                            metadata::steam(&app_id).map(|metadata| (id, metadata))
                        })
                        .await
                        .map_err(|error| error.to_string())
                        .and_then(|result| result)
                    },
                    Message::SteamMetadataFetched,
                );
            }
            Message::SteamMetadataFetched(result) => {
                match result {
                    Ok((id, fetched)) => {
                        if let Some(game) = self.games.iter().find(|game| game.id() == id) {
                            let mut data = game.data().clone();
                            let mut metadata = game.metadata().clone();
                            for (key, value) in fetched {
                                if metadata.get(&key).is_none_or(Value::is_null)
                                    || metadata.get(&key).is_some_and(|value| {
                                        value.as_str().is_some_and(str::is_empty)
                                    })
                                {
                                    metadata.insert(key, value);
                                }
                            }
                            data.insert("metadata".into(), Value::Object(metadata));
                            match self.library.update_game(&id, &data) {
                                Ok(()) => {
                                    self.games = self.library.games();
                                    self.categories = self.library.categories(&self.games);
                                    self.notice = Some("Ficha de Steam completada sin reemplazar datos existentes.".into());
                                }
                                Err(error) => self.notice = Some(error.to_string()),
                            }
                        }
                    }
                    Err(error) => self.notice = Some(error),
                }
            }
            Message::SearchWikidata => {
                let Some(editor) = self.editor.as_ref() else {
                    return Task::none();
                };
                let title = editor.title.clone();
                let language = match self.settings.get("language").and_then(Value::as_str) {
                    Some("es") => "es",
                    _ => "en",
                }
                .to_owned();
                self.metadata_searching = true;
                self.metadata_results.clear();
                return Task::perform(
                    async move {
                        tokio::task::spawn_blocking(move || {
                            metadata::wikidata_search(&title, &language)
                        })
                        .await
                        .map_err(|error| error.to_string())
                        .and_then(|result| result)
                    },
                    Message::WikidataSearchFinished,
                );
            }
            Message::WikidataSearchFinished(result) => {
                self.metadata_searching = false;
                match result {
                    Ok(results) => {
                        self.notice = Some(format!(
                            "{} coincidencias en Wikidata; selecciona la ficha correcta.",
                            results.len()
                        ));
                        self.metadata_results = results;
                    }
                    Err(error) => self.notice = Some(error),
                }
            }
            Message::ChooseWikidata(option) => {
                let language = match self.settings.get("language").and_then(Value::as_str) {
                    Some("es") => "es",
                    _ => "en",
                }
                .to_owned();
                let cache = self.library.metadata_cache_dir();
                return Task::perform(
                    async move {
                        let id = option.id;
                        tokio::task::spawn_blocking(move || {
                            metadata::wikidata_fetch(&id, &language, &cache)
                                .map(|result| (id, result))
                        })
                        .await
                        .map_err(|error| error.to_string())
                        .and_then(|result| result)
                    },
                    Message::WikidataFetched,
                );
            }
            Message::WikidataFetched(result) => match result {
                Ok((_id, fetched)) => {
                    if let Some(editor) = self.editor.as_mut() {
                        let string = |key: &str| {
                            fetched
                                .get(key)
                                .and_then(Value::as_str)
                                .unwrap_or_default()
                                .to_owned()
                        };
                        let list = |key: &str| {
                            fetched
                                .get(key)
                                .and_then(Value::as_array)
                                .into_iter()
                                .flatten()
                                .filter_map(Value::as_str)
                                .collect::<Vec<_>>()
                                .join(", ")
                        };
                        if !string("title").is_empty() {
                            editor.title = string("title");
                        }
                        editor.description = string("description");
                        editor.synopsis = editor.description.clone();
                        editor.release_date = string("release_date");
                        editor.developers = list("developers");
                        editor.publishers = list("publishers");
                        editor.genres = list("genres");
                        editor.platforms = list("platforms");
                        editor.metadata_entity_id = string("entity_id");
                        editor.metadata_source = string("source");
                    }
                    self.metadata_results.clear();
                    self.notice =
                        Some("Ficha de Wikidata cargada; guarda para aplicar los datos.".into());
                }
                Err(error) => self.notice = Some(error),
            },
            Message::ImagesLoaded(generation, background_key, images) => {
                if generation == self.image_generation {
                    for image in images {
                        if let Some(bytes) = image.blurred_bytes {
                            self.background_images.insert(
                                blur_cache_key(&image.path, image.blur_radius),
                                iced::widget::image::Handle::from_bytes(bytes),
                            );
                        }
                        self.images.insert(
                            image.path.clone(),
                            iced::widget::image::Handle::from_bytes(image.bytes),
                        );
                    }
                    if self.page_transition_pending {
                        self.layout_transition_started = Some(Instant::now());
                        self.page_transition_pending = false;
                    }
                    if !matches!(
                        background_key.as_deref(),
                        Some("__covers__" | "__prefetch__")
                    ) {
                        let next_background = background_key
                            .filter(|key| self.images.contains_key(key))
                            .or_else(|| {
                                self.background_path()
                                    .filter(|key| self.images.contains_key(key))
                            });
                        if let (Some(previous), Some(next)) = (
                            self.displayed_background_key.as_ref(),
                            next_background.as_ref(),
                        ) && previous != next
                        {
                            self.background_transition = Some((previous.clone(), Instant::now()));
                        }
                        self.displayed_background_key = next_background;
                    }
                    let current_slide = self.background_path();
                    if self.screensaver_active
                        && self.screensaver_previous_path.is_some()
                        && self.screensaver_transition_started.is_none()
                        && current_slide
                            .as_ref()
                            .is_some_and(|path| self.images.contains_key(path))
                    {
                        self.screensaver_transition_started = Some(Instant::now());
                    }
                }
            }
            Message::AnimationTick => {
                if self.focus_transition.as_ref().is_some_and(|transition| {
                    transition.started.elapsed() >= Duration::from_millis(160)
                }) {
                    self.focus_transition = None;
                }
                if self
                    .layout_transition_started
                    .is_some_and(|started| started.elapsed() >= Duration::from_millis(180))
                {
                    self.layout_transition_started = None;
                }
                if self
                    .background_transition
                    .as_ref()
                    .is_some_and(|(_, started)| started.elapsed() >= Duration::from_millis(240))
                {
                    self.background_transition = None;
                }
                if self
                    .pending_background_refresh
                    .is_some_and(|due| Instant::now() >= due)
                {
                    self.pending_background_refresh = None;
                    self.refresh_images();
                }
                if self
                    .screensaver_transition_started
                    .is_some_and(|started| started.elapsed() >= Duration::from_millis(500))
                {
                    self.screensaver_previous_path = None;
                    self.screensaver_transition_started = None;
                    self.refresh_images();
                }
            }
            Message::Activity => {
                self.last_activity = Instant::now();
                if self.screensaver_active
                    && !(self.running.is_some() && self.playing_behavior() == "screensaver")
                {
                    self.screensaver_active = false;
                    self.screensaver_paths.clear();
                    self.screensaver_previous_path = None;
                    self.screensaver_transition_started = None;
                    self.refresh_images();
                }
            }
            Message::IdleTick => {
                let enabled = self
                    .settings
                    .get("screensaver_enabled")
                    .and_then(Value::as_bool)
                    .unwrap_or(false);
                let idle_value = self
                    .settings
                    .get("screensaver_idle_value")
                    .and_then(Value::as_u64)
                    .unwrap_or(5);
                let idle_scale = if self
                    .settings
                    .get("screensaver_idle_unit")
                    .and_then(Value::as_str)
                    == Some("seconds")
                {
                    1
                } else {
                    60
                };
                let idle = Duration::from_secs(idle_value.saturating_mul(idle_scale));
                if enabled
                    && self.running.is_none()
                    && !self.screensaver_active
                    && self.last_activity.elapsed() >= idle
                {
                    self.activate_screensaver();
                } else if self.screensaver_active {
                    let slide_value = self
                        .settings
                        .get("screensaver_slide_value")
                        .and_then(Value::as_u64)
                        .unwrap_or(15);
                    let slide_scale = if self
                        .settings
                        .get("screensaver_slide_unit")
                        .and_then(Value::as_str)
                        == Some("minutes")
                    {
                        60
                    } else {
                        1
                    };
                    if self.last_slide.elapsed()
                        >= Duration::from_secs(slide_value.saturating_mul(slide_scale))
                    {
                        let previous = self.background_path();
                        self.screensaver_index =
                            (self.screensaver_index + 1) % self.screensaver_paths.len().max(1);
                        let next = self.background_path();
                        self.screensaver_previous_path =
                            previous.filter(|path| next.as_ref().is_some_and(|next| next != path));
                        self.screensaver_transition_started = None;
                        self.last_slide = Instant::now();
                        self.refresh_images();
                    }
                }
            }
            Message::AskRemove(id) => self.pending_remove = Some(id),
            Message::CancelRemove => self.pending_remove = None,
            Message::ConfirmRemove => {
                if let Some(id) = self.pending_remove.take() {
                    match self.library.remove_game(&id) {
                        Ok(()) => {
                            self.games = self.library.games();
                            self.categories = self.library.categories(&self.games);
                            self.refresh_images();
                            self.selected = None;
                            self.notice = Some("Juego retirado de Estante.".into());
                        }
                        Err(error) => {
                            self.notice = Some(format!("No se pudo retirar el juego: {error}"))
                        }
                    }
                }
            }
            Message::RestoreImports => match self.library.restore_excluded_imports() {
                Ok(count) => {
                    self.games = self.library.games();
                    self.categories = self.library.categories(&self.games);
                    self.refresh_images();
                    self.notice = Some(format!("Se restauraron {count} juegos."));
                }
                Err(error) => {
                    self.notice = Some(format!("No se pudieron restaurar los juegos: {error}"))
                }
            },
            Message::Edit(id) => {
                self.menu_open = false;
                self.start_edit(id);
            }
            Message::BrowseImage(field) => {
                let directory = self
                    .editor
                    .as_ref()
                    .and_then(|editor| editor_image_field(editor, field))
                    .map(PathBuf::from)
                    .map(|path| {
                        if path.is_dir() {
                            path
                        } else {
                            path.parent().unwrap_or(&path).to_path_buf()
                        }
                    })
                    .filter(|path| path.is_dir())
                    .or_else(|| {
                        std::env::var_os("HOME").map(|home| PathBuf::from(home).join("Pictures"))
                    })
                    .filter(|path| path.is_dir())
                    .or_else(|| std::env::var_os("HOME").map(PathBuf::from))
                    .unwrap_or_else(|| PathBuf::from("/"));
                self.image_browser = Some(ImageBrowser {
                    field,
                    directory: directory.clone(),
                    entries: Vec::new(),
                    selected: None,
                    error: None,
                });
                return Self::load_image_directory(directory);
            }
            Message::ImageDirectoryLoaded(directory, result) => {
                if let Some(browser) = self.image_browser.as_mut()
                    && browser.directory == directory
                {
                    match result {
                        Ok(entries) => {
                            browser.entries = entries;
                            browser.selected =
                                browser.entries.iter().position(|(_, is_dir)| !is_dir);
                            browser.error = None;
                        }
                        Err(error) => browser.error = Some(error),
                    }
                    self.refresh_images();
                }
            }
            Message::ImageBrowserSelect(index) => {
                if let Some(browser) = self.image_browser.as_mut()
                    && browser
                        .entries
                        .get(index)
                        .is_some_and(|(_, is_dir)| !is_dir)
                {
                    browser.selected = Some(index);
                    self.refresh_images();
                }
            }
            Message::ImageBrowserOpen(index) => {
                if let Some(browser) = self.image_browser.as_mut()
                    && let Some(path) = browser
                        .entries
                        .get(index)
                        .filter(|(_, is_dir)| *is_dir)
                        .map(|(path, _)| path.clone())
                {
                    browser.directory = path.clone();
                    browser.entries.clear();
                    browser.selected = None;
                    return Self::load_image_directory(path);
                }
            }
            Message::ImageBrowserParent => {
                if let Some(browser) = self.image_browser.as_mut()
                    && let Some(parent) = browser.directory.parent().map(PathBuf::from)
                {
                    browser.directory = parent.clone();
                    browser.entries.clear();
                    browser.selected = None;
                    return Self::load_image_directory(parent);
                }
            }
            Message::ImageBrowserPlace(directory) => {
                if directory.is_dir()
                    && let Some(browser) = self.image_browser.as_mut()
                {
                    browser.directory = directory.clone();
                    browser.entries.clear();
                    browser.selected = None;
                    browser.error = None;
                    return Self::load_image_directory(directory);
                }
            }
            Message::ImageBrowserUse => {
                if let Some(browser) = self.image_browser.take()
                    && let Some((path, false)) = browser
                        .selected
                        .and_then(|index| browser.entries.get(index))
                    && let Some(editor) = self.editor.as_mut()
                {
                    set_editor_field(editor, browser.field, path.to_string_lossy().into_owned());
                    self.refresh_images();
                }
            }
            Message::ImageBrowserCancel => {
                self.image_browser = None;
                self.refresh_images();
            }
            Message::EditField(field, value) => {
                if let Some(editor) = self.editor.as_mut() {
                    match field {
                        EditorField::Title => editor.title = value,
                        EditorField::Categories => editor.categories = value,
                        EditorField::Description => editor.description = value,
                        EditorField::Synopsis => editor.synopsis = value,
                        EditorField::ReleaseDate => editor.release_date = value,
                        EditorField::Developers => editor.developers = value,
                        EditorField::Publishers => editor.publishers = value,
                        EditorField::Genres => editor.genres = value,
                        EditorField::Platforms => editor.platforms = value,
                        EditorField::LocalPath => editor.local_path = value,
                        EditorField::Arguments => editor.arguments = value,
                        EditorField::WorkingDirectory => editor.cwd = value,
                        EditorField::Cover => editor.cover = value,
                        EditorField::SquareCover => editor.square_cover = value,
                        EditorField::Logo => editor.logo = value,
                        EditorField::Banner => editor.banner = value,
                        EditorField::BannerSecondary => editor.banner_secondary = value,
                    }
                }
            }
            Message::SaveEdit => {
                if let Some(editor) = self.editor.take() {
                    if let Some(game) = self.games.iter().find(|game| game.id() == editor.id) {
                        let mut data = game.data().clone();
                        data.insert(
                            "title".into(),
                            Value::String(editor.title.trim().to_owned()),
                        );
                        data.insert(
                            "categories".into(),
                            Value::Array(split_values(&editor.categories)),
                        );
                        for (key, value) in [
                            ("cover", editor.cover.as_str()),
                            ("square_cover", editor.square_cover.as_str()),
                            ("logo", editor.logo.as_str()),
                            ("banner", editor.banner.as_str()),
                            ("banner_secondary", editor.banner_secondary.as_str()),
                        ] {
                            data.insert(key.into(), Value::String(value.trim().to_owned()));
                        }
                        if game.kind() == "local" {
                            for (key, value) in [
                                ("path", editor.local_path.as_str()),
                                ("arguments", editor.arguments.as_str()),
                                ("cwd", editor.cwd.as_str()),
                            ] {
                                data.insert(key.into(), Value::String(value.trim().to_owned()));
                            }
                        }
                        data.insert(
                            "steamgriddb_id".into(),
                            Value::String(editor.steamgriddb_id.clone()),
                        );
                        let mut metadata = game.metadata().clone();
                        for (key, value) in [
                            ("description", editor.description.as_str()),
                            ("synopsis", editor.synopsis.as_str()),
                            ("release_date", editor.release_date.as_str()),
                        ] {
                            metadata.insert(key.into(), Value::String(value.trim().to_owned()));
                        }
                        for (key, value) in [
                            ("developers", editor.developers.as_str()),
                            ("publishers", editor.publishers.as_str()),
                            ("genres", editor.genres.as_str()),
                            ("platforms", editor.platforms.as_str()),
                        ] {
                            metadata.insert(key.into(), Value::Array(split_values(&value)));
                        }
                        if !editor.metadata_entity_id.is_empty() {
                            metadata.insert(
                                "entity_id".into(),
                                Value::String(editor.metadata_entity_id.clone()),
                            );
                            metadata.insert(
                                "source".into(),
                                Value::String(editor.metadata_source.clone()),
                            );
                        }
                        data.insert("metadata".into(), Value::Object(metadata));
                        match self.library.update_game(&editor.id, &data) {
                            Ok(()) => {
                                self.games = self.library.games();
                                self.categories = self.library.categories(&self.games);
                                self.refresh_images();
                                self.notice = Some("Ficha guardada.".into());
                            }
                            Err(error) => {
                                self.editor = Some(editor);
                                self.notice = Some(format!("No se pudo guardar la ficha: {error}"));
                            }
                        }
                    }
                }
            }
            Message::CancelEdit => self.editor = None,
        }
        if self.images_dirty {
            self.images_dirty = false;
            return self.image_loading_task();
        }
        Task::none()
    }

    fn change_layout(&mut self, layout: String) -> Task<Message> {
        if !["list", "grid", "carousel", "ps5"].contains(&layout.as_str()) || layout == self.layout
        {
            return Task::none();
        }
        let mut settings = self.settings.clone();
        if let Some(object) = settings.as_object_mut() {
            object.insert("layout".into(), Value::String(layout.clone()));
        } else {
            settings = Value::Object(Map::from_iter([("layout".into(), Value::String(layout))]));
        }
        self.settings = settings.clone();
        self.layout = settings["layout"].as_str().unwrap_or("grid").to_owned();
        self.layout_transition_started = Some(Instant::now());
        self.grid_columns = self.columns_for_width(self.window_width);
        self.refresh_images();
        self.notice = None;
        self.layout_save_generation = self.layout_save_generation.wrapping_add(1);
        self.layout_save_signal
            .store(self.layout_save_generation, Ordering::Relaxed);
        Self::save_layout_task(
            self.layout_save_generation,
            self.library.data_dir().to_path_buf(),
            settings,
            self.layout_save_signal.clone(),
        )
    }

    fn save_layout_task(
        generation: u64,
        root: PathBuf,
        settings: Value,
        current_generation: Arc<AtomicU64>,
    ) -> Task<Message> {
        Task::perform(
            async move {
                tokio::task::spawn_blocking(move || {
                    let _guard = SETTINGS_WRITE_LOCK
                        .lock()
                        .unwrap_or_else(|poisoned| poisoned.into_inner());
                    if current_generation.load(Ordering::Relaxed) != generation {
                        return Ok(());
                    }
                    Library::save_settings_at(root, &settings).map_err(|error| error.to_string())
                })
                .await
                .unwrap_or_else(|error| Err(error.to_string()))
            },
            move |result| Message::LayoutSaved(generation, result),
        )
    }

    fn set_cursor(&mut self, cursor: usize) {
        if cursor != self.cursor {
            self.focus_transition = if self.layout == "ps5"
                && self.settings.get("ps5_motion").and_then(Value::as_bool) == Some(false)
            {
                None
            } else {
                Some(FocusTransition {
                    from: self.cursor,
                    to: cursor,
                    started: Instant::now(),
                })
            };
            self.cursor = cursor;
        }
    }

    fn focus_weight(&self, index: usize) -> f32 {
        let Some(transition) = &self.focus_transition else {
            return if index == self.cursor { 1.0 } else { 0.0 };
        };
        let progress = ease_progress(transition.started.elapsed(), Duration::from_millis(160));
        if index == transition.from {
            1.0 - progress
        } else if index == transition.to {
            progress
        } else {
            0.0
        }
    }

    fn layout_opacity(&self) -> f32 {
        self.layout_transition_started.map_or(1.0, |started| {
            ease_progress(started.elapsed(), Duration::from_millis(180))
        })
    }

    fn filtered(&self) -> Vec<&Game> {
        let query = normalize_search(self.query.trim());
        self.games
            .iter()
            .filter(|game| {
                self.category
                    .as_ref()
                    .is_none_or(|category| game.categories().iter().any(|item| item == category))
            })
            .filter(|game| {
                query.is_empty()
                    || normalize_search(game.title()).contains(&query)
                    || game
                        .metadata()
                        .get("title")
                        .and_then(Value::as_str)
                        .is_some_and(|title| normalize_search(title).contains(&query))
                    || game
                        .categories()
                        .iter()
                        .any(|item| normalize_search(item).contains(&query))
            })
            .collect()
    }

    fn apply_controller_action(&mut self, action: &'static str) {
        self.last_activity = Instant::now();
        if self.virtual_keyboard.is_some() {
            match action {
                "back" => self.virtual_keyboard = None,
                "save" | "menu" => self.keyboard_command("done"),
                "page_previous" => self.keyboard_command("erase"),
                "page_next" => self.keyboard_command("space"),
                "confirm" => {
                    let keyboard = self.virtual_keyboard.as_ref().unwrap();
                    if keyboard.row < 5 {
                        if let Some(character) =
                            self.keyboard_rows()[keyboard.row].get(keyboard.column)
                        {
                            self.keyboard_command(&format!("insert:{character}"));
                        }
                    } else {
                        let command = ["case", "symbols", "space", "erase", "done"]
                            .get(keyboard.column)
                            .copied()
                            .unwrap_or("done");
                        self.keyboard_command(command);
                    }
                }
                "left" | "right" | "up" | "down" => {
                    let row = self.virtual_keyboard.as_ref().unwrap().row;
                    let lengths = self
                        .keyboard_rows()
                        .iter()
                        .map(Vec::len)
                        .chain([5])
                        .collect::<Vec<_>>();
                    let keyboard = self.virtual_keyboard.as_mut().unwrap();
                    match action {
                        "left" => keyboard.column = keyboard.column.saturating_sub(1),
                        "right" => {
                            keyboard.column =
                                (keyboard.column + 1).min(lengths[row].saturating_sub(1))
                        }
                        "up" => keyboard.row = keyboard.row.saturating_sub(1),
                        "down" => keyboard.row = (keyboard.row + 1).min(5),
                        _ => (),
                    }
                    keyboard.column = keyboard.column.min(lengths[keyboard.row].saturating_sub(1));
                }
                _ => (),
            }
            return;
        }
        if self.screensaver_active {
            if !(self.running.is_some() && self.playing_behavior() == "screensaver") {
                self.screensaver_active = false;
                self.screensaver_paths.clear();
                self.screensaver_previous_path = None;
                self.screensaver_transition_started = None;
                self.last_activity = Instant::now();
                self.refresh_images();
            }
            return;
        }
        if action == "back" {
            if self.menu_open {
                self.menu_open = false;
            } else if self.pending_remove.is_some() {
                self.pending_remove = None;
            } else if self.editor.is_some() {
                self.editor = None;
            } else if self.settings_open {
                self.settings_open = false;
            } else if self.add_open {
                self.add_open = false;
            } else {
                self.selected = None;
            }
            return;
        }
        if action == "search" {
            let target = if self.editor.is_some() {
                KeyboardTarget::Editor(EditorField::Title)
            } else if self.add_open {
                KeyboardTarget::LocalTitle
            } else {
                KeyboardTarget::Search
            };
            self.open_keyboard(target);
            return;
        }
        if action == "menu" {
            self.menu_open = !self.menu_open;
            return;
        }
        if self.editor.is_some() || self.settings_open || self.add_open || self.running.is_some() {
            return;
        }
        if let Some(id) = self.selected.clone() {
            match action {
                "play" => self.launch(id),
                "save" => self.start_edit(id),
                _ => (),
            }
            return;
        }
        match action {
            "appearance_settings" => {
                self.settings_section = self.layout.clone();
                self.settings_open = true;
            }
            "appearance" => {
                self.layout = match self.layout.as_str() {
                    "list" => "grid",
                    "grid" => "carousel",
                    "carousel" => "ps5",
                    _ => "list",
                }
                .to_owned();
                self.grid_columns = self.columns_for_width(self.window_width);
                let mut next = self.settings.clone();
                if let Some(object) = next.as_object_mut() {
                    object.insert("layout".into(), Value::String(self.layout.clone()));
                }
                if let Err(error) = self.library.save_settings(&next) {
                    self.notice = Some(format!("No se pudieron guardar los ajustes: {error}"));
                } else {
                    self.settings = next;
                    self.grid_columns = self.columns_for_width(self.window_width);
                    self.refresh_images();
                }
            }
            "page_previous" if self.layout == "grid" => self.page_by(-1),
            "page_next" if self.layout == "grid" => self.page_by(1),
            "page_previous" => self.letter_by(-1),
            "page_next" => self.letter_by(1),
            "letter_previous" => self.letter_by(-1),
            "letter_next" => self.letter_by(1),
            "grid_page_previous" if self.layout == "grid" => self.page_by(-1),
            "grid_page_next" if self.layout == "grid" => self.page_by(1),
            "category_previous" | "category_next" if !self.categories.is_empty() => {
                let current = self.category.as_ref().and_then(|selected| {
                    self.categories
                        .iter()
                        .position(|category| category == selected)
                });
                let next = match (current, action == "category_next") {
                    (None, true) => Some(0),
                    (None, false) => Some(self.categories.len() - 1),
                    (Some(index), true) if index + 1 < self.categories.len() => Some(index + 1),
                    (Some(_), true) => None,
                    (Some(index), false) if index > 0 => Some(index - 1),
                    (Some(_), false) => None,
                };
                self.category = next.map(|index| self.categories[index].clone());
                self.set_cursor(0);
                self.page = 0;
                self.refresh_images();
            }
            "left" | "up" | "right" | "down" => {
                let total = self.filtered().len();
                if total > 0 {
                    let next_cursor =
                        cursor_target(self.cursor, total, &self.layout, action, self.grid_columns);
                    let next_cursor = next_cursor.unwrap_or(self.cursor);
                    self.set_cursor(next_cursor);
                    let page = self.cursor / self.page_size();
                    let page_changed = page != self.page;
                    if page_changed {
                        self.page = page;
                        self.page_transition_pending = true;
                    }
                    if page_changed {
                        self.refresh_images();
                    } else {
                        self.pending_background_refresh =
                            Some(Instant::now() + Duration::from_millis(90));
                    }
                }
            }
            "confirm" => {
                if let Some(game) = self.filtered().get(self.cursor) {
                    self.selected = Some(game.id().to_owned());
                    self.menu_open = false;
                    self.refresh_images();
                }
            }
            "play" => {
                if let Some(game) = self.filtered().get(self.cursor) {
                    self.launch(game.id().to_owned());
                }
            }
            "save" => {
                if let Some(game) = self.filtered().get(self.cursor) {
                    self.start_edit(game.id().to_owned());
                }
            }
            _ => (),
        }
    }

    fn keyboard_command(&mut self, command: &str) {
        if command == "done" {
            if let Some(keyboard) = self.virtual_keyboard.take() {
                match keyboard.target {
                    KeyboardTarget::Search => {
                        self.query = keyboard.value;
                        self.page = 0;
                        self.set_cursor(0);
                        self.refresh_images();
                    }
                    KeyboardTarget::LocalTitle => self.local_title = keyboard.value,
                    KeyboardTarget::CategoryName => self.category_name = keyboard.value,
                    KeyboardTarget::LocalPath => self.local_path = keyboard.value,
                    KeyboardTarget::LocalArguments => self.local_arguments = keyboard.value,
                    KeyboardTarget::LocalWorkingDirectory => self.local_cwd = keyboard.value,
                    KeyboardTarget::Editor(field) => {
                        if let Some(editor) = self.editor.as_mut() {
                            set_editor_field(editor, field, keyboard.value);
                        }
                    }
                }
            }
            return;
        }
        let Some(keyboard) = self.virtual_keyboard.as_mut() else {
            return;
        };
        match command {
            "case" => {
                keyboard.uppercase = !keyboard.uppercase;
                keyboard.symbols = false;
            }
            "symbols" => keyboard.symbols = !keyboard.symbols,
            "space" => insert_at_cursor(&mut keyboard.value, &mut keyboard.cursor, " "),
            "erase" => erase_before_cursor(&mut keyboard.value, &mut keyboard.cursor),
            "cursorLeft" => move_cursor(&keyboard.value, &mut keyboard.cursor, -1),
            "cursorRight" => move_cursor(&keyboard.value, &mut keyboard.cursor, 1),
            "newline" => insert_at_cursor(&mut keyboard.value, &mut keyboard.cursor, "\n"),
            insert if insert.starts_with("insert:") => {
                if let Some(character) = insert.strip_prefix("insert:") {
                    insert_at_cursor(&mut keyboard.value, &mut keyboard.cursor, character);
                }
            }
            _ => (),
        }
    }

    fn request_keyboard(&mut self, target: KeyboardTarget) -> Task<Message> {
        let mode = self
            .settings
            .get("onscreen_keyboard")
            .and_then(Value::as_str)
            .unwrap_or("auto")
            .to_owned();
        if mode == "builtin" {
            self.open_keyboard(target);
            return Task::none();
        }
        if mode == "disabled" {
            self.notice = Some(
                "El teclado en pantalla está desactivado. Puedes cambiarlo en Ajustes.".into(),
            );
            return Task::none();
        }
        let fallback = self
            .settings
            .get("keyboard_fallback")
            .and_then(Value::as_bool)
            .unwrap_or(true);
        Task::perform(
            async move {
                tokio::task::spawn_blocking(move || system_keyboard::open(&mode))
                    .await
                    .map_err(|error| error.to_string())
                    .and_then(|result| result)
            },
            move |result| Message::SystemKeyboardOpened(target, fallback, result),
        )
    }

    fn open_keyboard(&mut self, target: KeyboardTarget) {
        let value = match target {
            KeyboardTarget::Search => self.query.clone(),
            KeyboardTarget::CategoryName => self.category_name.clone(),
            KeyboardTarget::LocalTitle => self.local_title.clone(),
            KeyboardTarget::LocalPath => self.local_path.clone(),
            KeyboardTarget::LocalArguments => self.local_arguments.clone(),
            KeyboardTarget::LocalWorkingDirectory => self.local_cwd.clone(),
            KeyboardTarget::Editor(field) => self
                .editor
                .as_ref()
                .map(|editor| editor_field(editor, field))
                .unwrap_or_default(),
        };
        self.virtual_keyboard = Some(VirtualKeyboard {
            target,
            cursor: value.len(),
            value,
            row: 1,
            column: 0,
            uppercase: false,
            symbols: false,
        });
    }

    fn keyboard_rows(&self) -> Vec<Vec<char>> {
        let symbols = self
            .virtual_keyboard
            .as_ref()
            .is_some_and(|keyboard| keyboard.symbols);
        let uppercase = self
            .virtual_keyboard
            .as_ref()
            .is_some_and(|keyboard| keyboard.uppercase);
        let rows = if symbols {
            [
                "1234567890",
                "@#€$%&*+-=",
                "()[]{}/\\",
                ".,:;!?_~^|",
                "'\"`©®™…°§",
            ]
        } else if uppercase {
            [
                "1234567890",
                "QWERTYUIOP",
                "ASDFGHJKLÑ",
                "ZXCVBNM",
                "ÁÉÍÓÚÜÑ¿¡",
            ]
        } else {
            [
                "1234567890",
                "qwertyuiop",
                "asdfghjklñ",
                "zxcvbnm",
                "áéíóúüñ¿¡",
            ]
        };
        rows.into_iter().map(|row| row.chars().collect()).collect()
    }

    fn keyboard_view(&self) -> Element<'_, Message> {
        let keyboard = self
            .virtual_keyboard
            .as_ref()
            .expect("keyboard view only when open");
        let rows = self.keyboard_rows();
        let (confirm, save, bumpers) =
            match self.settings.get("controller_type").and_then(Value::as_str) {
                Some("sony") => ("×", "△", "L1/R1"),
                Some("nintendo") => ("B", "X", "L/R"),
                _ => ("A", "Y", "LB/RB"),
            };
        let keys = rows.iter().enumerate().fold(
            column![].spacing(8),
            |column, (row_index, characters)| {
                let offset = (10 - characters.len()) / 2;
                let line = characters.iter().enumerate().fold(
                    row![].spacing(6),
                    |line, (column_index, character)| {
                        let selected = keyboard.row == row_index && keyboard.column == column_index;
                        line.push(keyboard_key_button(
                            character.to_string(),
                            selected,
                            false,
                            1,
                            Message::KeyboardInsert(character.to_string()),
                        ))
                    },
                );
                let line = if offset > 0 {
                    row![
                        container(text("")).width(Length::FillPortion(offset as u16)),
                        line.width(Length::FillPortion(characters.len() as u16)),
                        container(text("")).width(Length::FillPortion(offset as u16)),
                    ]
                    .spacing(6)
                } else {
                    line
                };
                column.push(line.width(Length::Fill))
            },
        );
        let actions = [
            ("ABC", "case", 1),
            ("#+=", "symbols", 1),
            ("←", "cursorLeft", 1),
            ("Espacio", "space", 3),
            ("→", "cursorRight", 1),
            ("⌫", "erase", 1),
            ("Listo", "done", 2),
        ];
        let commands = actions
            .into_iter()
            .enumerate()
            .fold(
                row![].spacing(6),
                |line, (index, (label, command, weight))| {
                    line.push(keyboard_key_button(
                        label.into(),
                        keyboard.row == 5 && keyboard.column == index,
                        command == "done",
                        weight,
                        Message::KeyboardCommand(command),
                    ))
                },
            )
            .width(Length::Fill);
        let header = row![
            text("Teclado de Estante").size(22).width(Length::Fill),
            button("Cancelar").on_press(Message::ControllerAction("back")),
            button("Listo").on_press(Message::ControllerAction("save")),
        ]
        .spacing(10)
        .align_y(Alignment::Center);
        let input = container(
            text(if keyboard.value.is_empty() {
                "Escribe aquí…".to_owned()
            } else {
                keyboard.value.clone()
            })
            .size(20),
        )
        .width(Length::Fill)
        .padding([12, 16])
        .style(|_| iced::widget::container::Style {
            background: Some(iced::Background::Color(iced::Color::from_rgba(
                0.08, 0.07, 0.08, 0.72,
            ))),
            border: iced::Border {
                color: iced::Color::from_rgba(1.0, 1.0, 1.0, 0.10),
                width: 1.0,
                radius: 10.0.into(),
            },
            ..Default::default()
        });
        container(
            column![
                header,
                input,
                keys,
                commands,
                text(format!(
                    "Mando: cruceta para elegir · {confirm} para escribir · {save} para listo · {bumpers} borrar / espacio"
                ))
                .size(13),
            ]
            .spacing(12),
        )
        .width(Length::Fill)
        .max_width(1060.0)
        .padding(20)
        .style(|_| iced::widget::container::Style {
            background: Some(iced::Background::Color(iced::Color::from_rgba(
                0.19, 0.17, 0.18, 0.98,
            ))),
            border: iced::Border {
                color: iced::Color::from_rgba(1.0, 1.0, 1.0, 0.10),
                width: 1.0,
                radius: 20.0.into(),
            },
            ..Default::default()
        })
        .into()
    }

    fn page_by(&mut self, direction: isize) {
        let total = self.filtered().len();
        let page_size = self.page_size();
        let pages = total.div_ceil(page_size).max(1);
        let current_page = self.cursor / page_size;
        self.page = (current_page as isize + direction).rem_euclid(pages as isize) as usize;
        if self.page != current_page {
            self.page_transition_pending = true;
        }
        let start = self.page * page_size;
        let page_len = total.saturating_sub(start).min(page_size);
        let offset = self
            .cursor
            .saturating_sub(current_page * page_size)
            .min(page_len.saturating_sub(1));
        self.set_cursor(if total == 0 { 0 } else { start + offset });
        self.refresh_images();
    }

    fn letter_by(&mut self, direction: isize) {
        let filtered = self.filtered();
        let titles = filtered
            .iter()
            .map(|game| game.title().to_owned())
            .collect::<Vec<_>>();
        let current = self.cursor;
        drop(filtered);
        let title_refs = titles.iter().map(String::as_str).collect::<Vec<_>>();
        if let Some(index) = alphabet_target(&title_refs, current, direction) {
            self.page = index / self.page_size();
            self.set_cursor(index);
            self.refresh_images();
        }
    }

    fn launch(&mut self, id: String) {
        if let Some(game) = self.games.iter().find(|game| game.id() == id) {
            match self.library.launch(game) {
                Ok((child, token)) => {
                    self.notice = Some(format!("Iniciado: {}", game.title()));
                    let launcher_pid = child.id();
                    self.running = Some(RunningSession {
                        id,
                        game: game.clone(),
                        token,
                        launcher_pid,
                        child,
                        child_code: None,
                        started: Instant::now(),
                        started_at: iso_now(),
                        observed: false,
                        timed_out: false,
                        polling: false,
                        behavior_applied: false,
                    });
                    self.refresh_images();
                }
                Err(error) => self.notice = Some(error.to_string()),
            }
        }
    }

    fn start_edit(&mut self, id: String) {
        if let Some(game) = self.games.iter().find(|game| game.id() == id) {
            let metadata = game.metadata();
            let value = |key: &str| {
                metadata
                    .get(key)
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_owned()
            };
            let list = |key: &str| {
                metadata
                    .get(key)
                    .and_then(Value::as_array)
                    .into_iter()
                    .flatten()
                    .filter_map(Value::as_str)
                    .collect::<Vec<_>>()
                    .join(", ")
            };
            self.editor = Some(EditDraft {
                id,
                title: game.title().to_owned(),
                categories: game.categories().join(", "),
                description: value("description"),
                synopsis: value("synopsis"),
                release_date: value("release_date"),
                developers: list("developers"),
                publishers: list("publishers"),
                genres: list("genres"),
                platforms: list("platforms"),
                local_path: game.field("path").unwrap_or_default().to_owned(),
                arguments: game.field("arguments").unwrap_or_default().to_owned(),
                cwd: game.field("cwd").unwrap_or_default().to_owned(),
                cover: game.field("cover").unwrap_or_default().to_owned(),
                square_cover: game.field("square_cover").unwrap_or_default().to_owned(),
                logo: game.field("logo").unwrap_or_default().to_owned(),
                banner: game.field("banner").unwrap_or_default().to_owned(),
                banner_secondary: game
                    .field("banner_secondary")
                    .unwrap_or_default()
                    .to_owned(),
                steamgriddb_id: game.field("steamgriddb_id").unwrap_or_default().to_owned(),
                metadata_entity_id: value("entity_id"),
                metadata_source: value("source"),
            });
            self.refresh_images();
        }
    }

    fn background_path(&self) -> Option<String> {
        if self.screensaver_active {
            return self.screensaver_paths.get(self.screensaver_index).cloned();
        }
        if self
            .settings
            .get("background_source")
            .and_then(Value::as_str)
            == Some("global")
        {
            let value = self.settings.get("global_background")?.as_str()?;
            if let Some(file) = value.strip_prefix("bundled:") {
                return Some(format!(
                    "{}/assets/backgrounds/{file}",
                    env!("CARGO_MANIFEST_DIR")
                ));
            }
            return Some(value.strip_prefix("~/").map_or_else(
                || value.to_owned(),
                |tail| format!("{}/{tail}", std::env::var("HOME").unwrap_or_default()),
            ));
        }
        self.selected
            .as_ref()
            .and_then(|id| self.games.iter().find(|game| game.id() == id))
            .or_else(|| self.filtered().get(self.cursor).copied())
            .and_then(|game| game.field("banner"))
            .filter(|path| !path.is_empty())
            .map(str::to_owned)
    }

    fn activate_screensaver(&mut self) {
        let paths: Vec<String> = if self
            .settings
            .get("screensaver_source")
            .and_then(Value::as_str)
            == Some("application")
        {
            let value = self
                .settings
                .get("screensaver_background")
                .and_then(Value::as_str)
                .unwrap_or("bundled:6.png");
            let path = resolve_background_setting(value);
            PathBuf::from(&path)
                .is_file()
                .then_some(path)
                .into_iter()
                .collect()
        } else {
            let mut seen = std::collections::HashSet::new();
            self.games
                .iter()
                .filter_map(|game| game.field("banner").or_else(|| game.field("cover")))
                .filter(|path| {
                    !path.is_empty() && PathBuf::from(path).is_file() && seen.insert(*path)
                })
                .map(str::to_owned)
                .collect()
        };
        if paths.is_empty() {
            self.screensaver_active = false;
            self.screensaver_paths.clear();
            self.screensaver_previous_path = None;
            self.screensaver_transition_started = None;
            self.last_activity = Instant::now();
            return;
        }
        self.screensaver_paths = paths;
        self.screensaver_index = 0;
        self.screensaver_active = true;
        self.screensaver_previous_path = None;
        self.screensaver_transition_started = None;
        self.last_activity = Instant::now();
        self.last_slide = Instant::now();
        self.focus_transition = None;
        self.refresh_images();
    }

    fn background_secondary_path(&self) -> Option<String> {
        if self.screensaver_active
            || self
                .settings
                .get("background_source")
                .and_then(Value::as_str)
                == Some("global")
            || self
                .settings
                .get("background_splits")
                .and_then(|rows| rows.get(&self.layout))
                .and_then(Value::as_str)
                == Some("single")
        {
            return None;
        }
        self.selected
            .as_ref()
            .and_then(|id| self.games.iter().find(|game| game.id() == id))
            .or_else(|| self.filtered().get(self.cursor).copied())
            .and_then(|game| game.field("banner_secondary"))
            .filter(|path| !path.is_empty())
            .map(str::to_owned)
    }

    fn background_composite_spec(&self) -> Option<(String, String, String)> {
        let primary = self.background_path()?;
        let secondary = self.background_secondary_path()?;
        let split = self
            .settings
            .get("background_splits")
            .and_then(|rows| rows.get(&self.layout))
            .and_then(Value::as_str)
            .unwrap_or("single");
        (!matches!(split, "single")).then(|| (primary, secondary, split.to_owned()))
    }

    fn background_render_key(&self) -> Option<String> {
        self.background_composite_spec()
            .map(|(primary, secondary, split)| {
                background_composite_key(&primary, &secondary, &split)
            })
            .or_else(|| self.background_path())
    }

    fn refresh_images(&mut self) {
        self.pending_background_refresh = None;
        let filtered = self.filtered();
        let page_size = self.page_size();
        let pages = filtered.len().div_ceil(page_size).max(1);
        let page = self.page.min(pages - 1);
        let mut visible = if self.screensaver_active {
            self.screensaver_previous_path
                .iter()
                .cloned()
                .collect::<std::collections::HashSet<_>>()
        } else if let Some(session) = &self.running {
            self.cover_path(&session.game)
                .filter(|path| !path.is_empty())
                .map(|path| [path.to_owned()].into_iter().collect())
                .unwrap_or_default()
        } else if matches!(self.layout.as_str(), "list" | "carousel") {
            nearby_indices(filtered.len(), self.cursor, 5)
                .into_iter()
                .flat_map(|index| {
                    let game = filtered[index];
                    [
                        (self.layout == "list")
                            .then(|| game.field("logo"))
                            .flatten(),
                        self.cover_path(game),
                    ]
                    .into_iter()
                    .flatten()
                    .filter(|path| !path.is_empty())
                    .map(str::to_owned)
                    .collect::<Vec<_>>()
                })
                .collect::<std::collections::HashSet<_>>()
        } else if self.layout == "ps5" {
            forward_indices(filtered.len(), self.cursor, 10)
                .into_iter()
                .filter_map(|index| self.cover_path(filtered[index]))
                .filter(|path| !path.is_empty())
                .map(str::to_owned)
                .collect::<std::collections::HashSet<_>>()
        } else {
            filtered
                .iter()
                .skip(page * page_size)
                .take(page_size)
                .filter_map(|game| self.cover_path(game))
                .filter(|path| !path.is_empty())
                .map(str::to_owned)
                .collect::<std::collections::HashSet<_>>()
        };
        if !self.screensaver_active
            && self.running.is_none()
            && self.layout == "list"
            && let Some(path) = filtered
                .get(self.cursor)
                .and_then(|game| self.cover_path(game))
                .filter(|path| !path.is_empty())
        {
            visible.insert(path.to_owned());
        }
        if self.running.is_none()
            && self.layout == "grid"
            && let Some(path) = filtered
                .get(self.cursor)
                .and_then(|game| game.field("logo"))
                .filter(|path| !path.is_empty())
        {
            visible.insert(path.to_owned());
        }
        let (prefetch, prefetch_backgrounds) = if !self.screensaver_active && self.running.is_none()
        {
            let indices = match self.layout.as_str() {
                "grid" => [((page + pages - 1) % pages), ((page + 1) % pages)]
                    .into_iter()
                    .filter(|adjacent_page| *adjacent_page != page)
                    .flat_map(|adjacent_page| {
                        (adjacent_page * page_size
                            ..(adjacent_page * page_size + page_size).min(filtered.len()))
                            .collect::<Vec<_>>()
                    })
                    .collect::<Vec<_>>(),
                "list" | "carousel" => nearby_indices(filtered.len(), self.cursor, 15),
                "ps5" => nearby_indices(filtered.len(), self.cursor, 21),
                _ => Vec::new(),
            };
            let background_indices = nearby_indices(filtered.len(), self.cursor, 3);
            let mut assets = std::collections::HashSet::new();
            let mut backgrounds = std::collections::HashSet::new();
            let game_backgrounds = self
                .settings
                .get("background_source")
                .and_then(Value::as_str)
                != Some("global");
            let secondary_enabled = self
                .settings
                .get("background_splits")
                .and_then(|rows| rows.get(&self.layout))
                .and_then(Value::as_str)
                != Some("single");
            for index in indices {
                let game = filtered[index];
                for path in [
                    (self.layout == "list")
                        .then(|| game.field("logo"))
                        .flatten(),
                    self.cover_path(game),
                ]
                .into_iter()
                .flatten()
                .filter(|path| !path.is_empty())
                {
                    if !visible.contains(path) {
                        assets.insert(path.to_owned());
                    }
                }
            }
            if game_backgrounds {
                for index in background_indices {
                    if index == self.cursor {
                        continue;
                    }
                    let game = filtered[index];
                    if let Some(path) = game.field("banner").filter(|path| !path.is_empty()) {
                        backgrounds.insert(path.to_owned());
                    }
                    if secondary_enabled
                        && let Some(path) = game
                            .field("banner_secondary")
                            .filter(|path| !path.is_empty())
                    {
                        backgrounds.insert(path.to_owned());
                    }
                }
            }
            if let Some(current) = self.background_path() {
                backgrounds.remove(&current);
            }
            (assets, backgrounds)
        } else {
            (
                std::collections::HashSet::new(),
                std::collections::HashSet::new(),
            )
        };
        drop(filtered);
        self.page = page;
        if !self.screensaver_active && self.running.is_none() {
            if let Some(path) = self
                .library
                .category_icon_path(self.category.as_deref().unwrap_or_default())
            {
                visible.insert(path.to_string_lossy().into_owned());
            }
            if let Some(path) = self
                .library
                .category_icon_path(self.category_icon_target.as_deref().unwrap_or_default())
            {
                visible.insert(path.to_string_lossy().into_owned());
            }
            if let Some(editor) = &self.editor {
                visible.extend(
                    [editor.banner.as_str(), editor.cover.as_str()]
                        .into_iter()
                        .filter(|path| !path.is_empty())
                        .map(str::to_owned),
                );
            }
            if let Some(path) = self.image_browser.as_ref().and_then(|browser| {
                browser
                    .selected
                    .and_then(|index| browser.entries.get(index))
                    .map(|(path, _)| path)
            }) {
                visible.insert(path.to_string_lossy().into_owned());
            }
        }
        let background = (self.running.is_none())
            .then(|| self.background_path())
            .flatten();
        if let Some(previous) = self.screensaver_previous_path.as_ref() {
            visible.insert(previous.clone());
        }
        if let Some(path) = background.as_ref() {
            visible.insert(path.clone());
        }
        if self.settings_open
            && self.settings_section == "global"
            && self
                .settings
                .get("screensaver_source")
                .and_then(Value::as_str)
                == Some("application")
        {
            if let Some(value) = self
                .settings
                .get("screensaver_background")
                .and_then(Value::as_str)
            {
                visible.insert(resolve_background_setting(value));
            }
        }
        let composite = (self.running.is_none())
            .then(|| self.background_composite_spec())
            .flatten();
        if let Some((primary, secondary, _)) = composite.as_ref() {
            visible.insert(primary.clone());
            visible.insert(secondary.clone());
        }
        let composite_key = composite
            .as_ref()
            .map(|(primary, secondary, split)| background_composite_key(primary, secondary, split));
        let render_key = composite_key.clone().or_else(|| background.clone());
        let blur_radius = self.background_blur();
        let blur_key = render_key
            .as_ref()
            .filter(|_| blur_radius > 0)
            .map(|path| blur_cache_key(path, blur_radius));
        let displayed_background = self.displayed_background_key.as_deref();
        let transition_blur_key = self
            .background_transition
            .as_ref()
            .filter(|_| blur_radius > 0)
            .map(|(path, _)| blur_cache_key(path, blur_radius));
        self.background_images.retain(|key, _| {
            Some(key) == blur_key.as_ref()
                || Some(key) == transition_blur_key.as_ref()
                || prefetch_backgrounds
                    .iter()
                    .any(|path| blur_cache_key(path, blur_radius) == *key)
        });
        let mut retained = visible.clone();
        retained.extend(prefetch.iter().cloned());
        retained.extend(prefetch_backgrounds.iter().cloned());
        if let Some((path, _)) = &self.background_transition {
            retained.insert(path.clone());
        }
        self.images.retain(|path, _| {
            retained.contains(path)
                || composite_key.as_deref() == Some(path.as_str())
                || displayed_background == Some(path.as_str())
        });
        self.prefetch_image_paths = prefetch
            .into_iter()
            .filter(|path| !self.images.contains_key(path))
            .collect();
        self.prefetch_background_paths = prefetch_backgrounds
            .into_iter()
            .filter(|path| {
                !self.images.contains_key(path)
                    || blur_radius > 0
                        && !self
                            .background_images
                            .contains_key(&blur_cache_key(path, blur_radius))
            })
            .collect();
        self.image_paths = visible
            .into_iter()
            .filter(|path| {
                !self.images.contains_key(path)
                    || render_key.as_deref() == Some(path.as_str())
                        && blur_key
                            .as_ref()
                            .is_some_and(|key| !self.background_images.contains_key(key))
            })
            .collect();
        let compose = composite.filter(|_| {
            composite_key
                .as_ref()
                .is_some_and(|key| !self.images.contains_key(key))
                || blur_key
                    .as_ref()
                    .is_some_and(|key| !self.background_images.contains_key(key))
        });
        self.image_generation = self.image_generation.wrapping_add(1);
        self.image_generation_signal
            .store(self.image_generation, Ordering::Relaxed);
        self.images_dirty = true;
        self.pending_composite = compose;
    }

    fn image_loading_task(&mut self) -> Task<Message> {
        let mut paths = self.image_paths.clone();
        let background_decode_size =
            active_background_decode_size(self.window_width, self.window_height);
        let composite = self.background_composite_spec();
        let composite_key = composite
            .as_ref()
            .map(|(primary, secondary, split)| background_composite_key(primary, secondary, split));
        let mut background_paths = Vec::new();
        for path in self.background_path().into_iter().chain(
            composite
                .iter()
                .flat_map(|(primary, secondary, _)| [primary.clone(), secondary.clone()]),
        ) {
            if paths.contains(&path) && !background_paths.contains(&path) {
                background_paths.push(path);
            }
        }
        paths.retain(|path| {
            !background_paths.contains(path) && composite_key.as_ref() != Some(path)
        });
        let prefetch_backgrounds = std::mem::take(&mut self.prefetch_background_paths);
        Task::batch([
            Self::load_images_task(
                self.image_generation,
                paths,
                Some("__covers__".into()),
                None,
                Vec::new(),
                0,
                self.cover_decode_size(),
                background_decode_size,
                self.image_generation_signal.clone(),
            ),
            Self::load_images_task(
                self.image_generation,
                background_paths,
                self.background_render_key(),
                self.pending_composite.take(),
                Vec::new(),
                self.background_blur(),
                self.cover_decode_size(),
                background_decode_size,
                self.image_generation_signal.clone(),
            ),
            Self::load_images_task(
                self.image_generation,
                std::mem::take(&mut self.prefetch_image_paths),
                Some("__prefetch__".into()),
                None,
                Vec::new(),
                0,
                self.cover_decode_size(),
                background_decode_size,
                self.image_generation_signal.clone(),
            ),
            Self::load_images_task(
                self.image_generation,
                prefetch_backgrounds.clone(),
                Some("__prefetch__".into()),
                None,
                prefetch_backgrounds,
                self.background_blur(),
                self.cover_decode_size(),
                PREFETCH_BACKGROUND_DECODE_SIZE,
                self.image_generation_signal.clone(),
            ),
        ])
    }

    fn load_images_task(
        generation: u64,
        paths: Vec<String>,
        background: Option<String>,
        composite: Option<(String, String, String)>,
        additional_background_paths: Vec<String>,
        blur_radius: u64,
        cover_decode_size: (u32, u32),
        background_decode_size: (u32, u32),
        current_generation: Arc<AtomicU64>,
    ) -> Task<Message> {
        let background_key = composite
            .as_ref()
            .map(|(primary, secondary, split)| background_composite_key(primary, secondary, split))
            .or_else(|| background.clone());
        Task::perform(
            async move {
                tokio::task::spawn_blocking(move || {
                    let loaded = (|| {
                        let mut loaded = Vec::new();
                        for path in paths {
                            if !image_generation_is_current(generation, &current_generation) {
                                return Vec::new();
                            }
                            let Ok(bytes) = fs::read(&path) else {
                                continue;
                            };
                            let Ok(decoded) = image::load_from_memory(&bytes) else {
                                continue;
                            };
                            if !image_generation_is_current(generation, &current_generation) {
                                return Vec::new();
                            }
                            let is_background = background.as_deref() == Some(path.as_str())
                                || additional_background_paths.contains(&path)
                                || composite.as_ref().is_some_and(|(primary, secondary, _)| {
                                    primary == &path || secondary == &path
                                });
                            let (max_width, max_height) = if is_background {
                                background_decode_size
                            } else {
                                cover_decode_size
                            };
                            let resized = decoded.thumbnail(max_width, max_height).into_rgba8();
                            let blurred_bytes = if blur_radius > 0
                                && (background.as_deref() == Some(path.as_str())
                                    || additional_background_paths.contains(&path))
                            {
                                encode_image(&image::imageops::blur(&resized, blur_radius as f32))
                            } else {
                                None
                            };
                            let Some(bytes) = encode_image(&resized) else {
                                continue;
                            };
                            loaded.push(LoadedImage {
                                path,
                                bytes,
                                blurred_bytes,
                                blur_radius,
                            });
                        }
                        if !image_generation_is_current(generation, &current_generation) {
                            return Vec::new();
                        }
                        if let Some((primary, secondary, split)) = composite {
                            if let Some(pixels) = compose_background_pair(
                                &primary,
                                &secondary,
                                &split,
                                background_decode_size,
                            ) {
                                if !image_generation_is_current(generation, &current_generation) {
                                    return Vec::new();
                                }
                                let key = background_composite_key(&primary, &secondary, &split);
                                let blurred_bytes = (blur_radius > 0)
                                    .then(|| {
                                        encode_image(&image::imageops::blur(
                                            &pixels,
                                            blur_radius as f32,
                                        ))
                                    })
                                    .flatten();
                                let Some(bytes) = encode_image(&pixels) else {
                                    return loaded;
                                };
                                loaded.push(LoadedImage {
                                    path: key,
                                    bytes,
                                    blurred_bytes,
                                    blur_radius,
                                });
                            }
                        }
                        loaded
                    })();
                    trim_native_heap();
                    loaded
                })
                .await
                .unwrap_or_default()
            },
            move |images| Message::ImagesLoaded(generation, background_key, images),
        )
    }

    fn page_size(&self) -> usize {
        if self.layout == "carousel" {
            5
        } else {
            self.settings
                .get("grid_page_size")
                .and_then(Value::as_u64)
                .filter(|value| (1..=100).contains(value))
                .unwrap_or(10) as usize
        }
    }

    fn columns_for_width(&self, width: f32) -> usize {
        let zoom = self
            .settings
            .get("grid_zoom")
            .and_then(Value::as_u64)
            .unwrap_or(100)
            .clamp(50, 200) as f32
            / 100.0;
        let minimal = self
            .settings
            .get("minimal_views")
            .and_then(|modes| modes.get("grid"))
            .and_then(Value::as_bool)
            == Some(true);
        grid_columns_for_width(width, zoom, minimal, self.page_size())
    }

    fn cover_decode_size(&self) -> (u32, u32) {
        (520, 806)
    }

    fn cover_path<'a>(&self, game: &'a Game) -> Option<&'a str> {
        let square = self
            .settings
            .get("cover_formats")
            .and_then(|formats| formats.get(&self.layout))
            .and_then(Value::as_str)
            == Some("square");
        if square {
            game.field("square_cover")
                .filter(|path| !path.is_empty())
                .or_else(|| game.field("cover").filter(|path| !path.is_empty()))
        } else {
            game.field("cover").filter(|path| !path.is_empty())
        }
    }

    fn background_blur(&self) -> u64 {
        if self.screensaver_active {
            return 0;
        }
        self.settings
            .get("background_blur")
            .and_then(|rows| rows.get(&self.layout))
            .and_then(Value::as_u64)
            .unwrap_or(0)
    }

    fn playing_behavior(&self) -> &'static str {
        match self
            .settings
            .get("playing_behavior")
            .and_then(Value::as_str)
        {
            Some("none") => "none",
            Some("hide") => "hide",
            Some("screensaver") => "screensaver",
            Some("tray") => "tray",
            _ if self
                .settings
                .get("hide_while_playing")
                .and_then(Value::as_bool)
                == Some(true) =>
            {
                "hide"
            }
            _ => "none",
        }
    }

    fn view(&self) -> Element<'_, Message> {
        let content = self.main_view();
        if self.virtual_keyboard.is_some() {
            let shade = button(text(""))
                .width(Length::Fill)
                .height(Length::Fill)
                .on_press(Message::Activity)
                .style(|_, _| iced::widget::button::Style {
                    background: Some(iced::Background::Color(iced::Color::from_rgba(
                        0.0, 0.0, 0.0, 0.38,
                    ))),
                    text_color: iced::Color::TRANSPARENT,
                    ..Default::default()
                });
            let dialog = container(self.keyboard_view())
                .width(Length::Fill)
                .height(Length::Fill)
                .center_x(Length::Fill)
                .align_y(Alignment::End)
                .padding([12, 24]);
            stack![content, shade, dialog].into()
        } else {
            content
        }
    }

    fn main_view(&self) -> Element<'_, Message> {
        if self.screensaver_active {
            return self.screensaver_view();
        }
        if let Some(session) = self.running.as_ref() {
            return self.playing_view(session);
        }
        if self.image_browser.is_some() {
            return self.image_browser_view();
        }
        if self.settings_open {
            return self.with_background(self.settings_screen());
        }
        if let Some(editor) = &self.editor {
            return self.with_background(self.editor_view(editor));
        }
        if let Some(id) = &self.selected {
            if let Some(game) = self.games.iter().find(|game| game.id() == id) {
                return self.with_background(self.game_view(game));
            }
        }

        let filtered = self.filtered();
        let browser_width = self.window_width;
        let page_size = self.page_size();
        let pages = filtered.len().div_ceil(page_size).max(1);
        let page = self.page.min(pages - 1);
        let start = page * page_size;
        let page_games = filtered
            .iter()
            .skip(start)
            .take(page_size)
            .copied()
            .collect::<Vec<_>>();
        let list_side = self
            .settings
            .get("list_side")
            .and_then(Value::as_str)
            .unwrap_or("left");
        let horizontal_list = self.layout == "list" && matches!(list_side, "top" | "bottom");
        let list_zoom = self
            .settings
            .get("list_zoom")
            .and_then(Value::as_u64)
            .unwrap_or(100)
            .clamp(50, 200) as f32
            / 100.0;
        let list_focus_zoom = self
            .settings
            .get("list_focus_zoom")
            .and_then(Value::as_u64)
            .unwrap_or(150)
            .clamp(100, 250) as f32
            / 100.0;
        let list_transition = (self.layout == "list")
            .then_some(self.focus_transition.as_ref())
            .flatten()
            .filter(|transition| filtered.len() > 1 && transition.from != transition.to);
        let list_phase = list_transition.map_or(self.cursor as f32, |transition| {
            wrapped_cursor_phase(
                transition.from,
                transition.to,
                ease_progress(transition.started.elapsed(), Duration::from_millis(160)),
                filtered.len(),
            )
        });
        let list_games = if self.layout == "list" {
            nearby_indices(
                filtered.len(),
                list_transition.map_or(self.cursor, |transition| transition.from),
                if list_transition.is_some() { 7 } else { 5 },
            )
            .into_iter()
            .map(|index| (index, filtered[index]))
            .collect::<Vec<_>>()
        } else {
            Vec::new()
        };
        let carousel_transition = (self.layout == "carousel")
            .then_some(self.focus_transition.as_ref())
            .flatten()
            .filter(|transition| filtered.len() > 1 && transition.from != transition.to);
        let carousel_phase = carousel_transition.map_or(self.cursor as f32, |transition| {
            wrapped_cursor_phase(
                transition.from,
                transition.to,
                ease_progress(transition.started.elapsed(), Duration::from_millis(160)),
                filtered.len(),
            )
        });
        let carousel_games = if self.layout == "carousel" {
            nearby_indices(
                filtered.len(),
                carousel_transition.map_or(self.cursor, |transition| transition.from),
                if carousel_transition.is_some() { 7 } else { 5 },
            )
            .into_iter()
            .map(|index| (index, filtered[index]))
            .collect::<Vec<_>>()
        } else {
            Vec::new()
        };
        let ps5_transition = (self.layout == "ps5")
            .then_some(self.focus_transition.as_ref())
            .flatten()
            .filter(|transition| transition.from != transition.to);
        let ps5_phase = ps5_transition.map_or(self.cursor as f32, |transition| {
            transition.from as f32
                + (transition.to as f32 - transition.from as f32)
                    * ease_progress(transition.started.elapsed(), Duration::from_millis(160))
        });
        let ps5_games = if self.layout == "ps5" {
            let start = ps5_transition
                .map_or(self.cursor, |transition| transition.from)
                .saturating_sub(if ps5_transition.is_some() { 1 } else { 0 });
            forward_indices(
                filtered.len(),
                start,
                if ps5_transition.is_some() { 12 } else { 10 },
            )
            .into_iter()
            .map(|index| (index, filtered[index]))
            .collect::<Vec<_>>()
        } else {
            Vec::new()
        };
        let cards: Element<'_, Message> = match self.layout.as_str() {
            "list" if horizontal_list => {
                let main_extent = (browser_width - 40.0).max(1.0);
                let cross_extent = ((self.window_height - 200.0) * 0.35 - 32.0).max(1.0);
                let mut positioned = list_games
                    .iter()
                    .filter_map(|(index, game)| {
                        let phase_offset = wrapped_cover_offset(*index, list_phase, filtered.len());
                        if phase_offset.abs() > if list_transition.is_some() { 2.6 } else { 2.5 } {
                            return None;
                        }
                        let (cross, main) = list_arc_position(
                            phase_offset,
                            filtered.len(),
                            main_extent,
                            cross_extent,
                            300.0 * list_zoom,
                            list_focus_zoom,
                            list_side == "bottom",
                        );
                        Some((*index, *game, main, cross, phase_offset.abs()))
                    })
                    .collect::<Vec<_>>();
                positioned.sort_by(|a, b| b.4.total_cmp(&a.4));
                let layers = positioned
                    .into_iter()
                    .map(|(index, game, main, cross, _)| {
                        let shift_x = main;
                        let shift_y = cross;
                        container(self.game_card(game, self.focus_weight(index)))
                            .width(Length::Fill)
                            .height(Length::Fill)
                            .center_x(Length::Fill)
                            .center_y(Length::Fill)
                            .padding(iced::Padding {
                                left: (shift_x * 2.0).max(0.0),
                                right: (-shift_x * 2.0).max(0.0),
                                top: (shift_y * 2.0).max(0.0),
                                bottom: (-shift_y * 2.0).max(0.0),
                            })
                            .into()
                    })
                    .collect::<Vec<Element<'_, Message>>>();
                container(stack(layers))
                    .width(Length::Fill)
                    .height(Length::Fill)
                    .clip(true)
                    .into()
            }
            "list" => {
                let main_extent = (self.window_height - 200.0).max(1.0);
                let cross_extent = (browser_width * 0.35).max(1.0);
                let mut positioned = list_games
                    .iter()
                    .filter_map(|(index, game)| {
                        let phase_offset = wrapped_cover_offset(*index, list_phase, filtered.len());
                        if phase_offset.abs() > if list_transition.is_some() { 2.6 } else { 2.5 } {
                            return None;
                        }
                        let (cross, main) = list_arc_position(
                            phase_offset,
                            filtered.len(),
                            main_extent,
                            cross_extent,
                            160.0 * list_zoom,
                            list_focus_zoom,
                            list_side == "right",
                        );
                        Some((*index, *game, main, cross, phase_offset.abs()))
                    })
                    .collect::<Vec<_>>();
                positioned.sort_by(|a, b| b.4.total_cmp(&a.4));
                let layers = positioned
                    .into_iter()
                    .map(|(index, game, main, cross, _)| {
                        let shift_x = cross;
                        let shift_y = main;
                        container(self.game_card(game, self.focus_weight(index)))
                            .width(Length::Fill)
                            .height(Length::Fill)
                            .center_x(Length::Fill)
                            .center_y(Length::Fill)
                            .padding(iced::Padding {
                                left: (shift_x * 2.0).max(0.0),
                                right: (-shift_x * 2.0).max(0.0),
                                top: (shift_y * 2.0).max(0.0),
                                bottom: (-shift_y * 2.0).max(0.0),
                            })
                            .into()
                    })
                    .collect::<Vec<Element<'_, Message>>>();
                container(stack(layers))
                    .width(Length::Fill)
                    .height(Length::Fill)
                    .clip(true)
                    .into()
            }
            "carousel" => {
                let zoom = self
                    .settings
                    .get("carousel_zoom")
                    .and_then(Value::as_f64)
                    .map(|value| value as f32 / 100.0)
                    .unwrap_or(1.0)
                    .clamp(0.5, 2.0);
                let strip_height = (self.window_height * 0.40).clamp(220.0, 420.0);
                let cover_width = 280.0_f32
                    .min(strip_height * 0.70 / zoom)
                    .min(browser_width * 0.24 / zoom)
                    * zoom;
                let stride = cover_width + 46.0;
                let mut positioned = carousel_games
                    .iter()
                    .filter_map(|(index, game)| {
                        let offset = wrapped_cover_offset(*index, carousel_phase, filtered.len());
                        (offset.abs()
                            <= if carousel_transition.is_some() {
                                2.6
                            } else {
                                2.5
                            })
                        .then_some((*index, *game, offset))
                    })
                    .collect::<Vec<_>>();
                positioned.sort_by(|a, b| b.2.abs().total_cmp(&a.2.abs()));
                let cards = positioned
                    .into_iter()
                    .map(|(index, game, offset)| {
                        let shift = offset * stride;
                        container(self.game_card(game, self.focus_weight(index)))
                            .width(Length::Fill)
                            .height(Length::Fill)
                            .center_x(Length::Fill)
                            .center_y(Length::Fill)
                            .padding(iced::Padding {
                                left: (shift * 2.0).max(0.0),
                                right: (-shift * 2.0).max(0.0),
                                ..iced::Padding::ZERO
                            })
                            .into()
                    })
                    .collect::<Vec<Element<'_, Message>>>();
                container(stack(cards))
                    .width(Length::Fill)
                    .height(Length::Fill)
                    .clip(true)
                    .into()
            }
            "ps5" => {
                let focus_size = self
                    .settings
                    .get("ps5_focus_size")
                    .and_then(Value::as_f64)
                    .map(|value| value as f32)
                    .unwrap_or(250.0)
                    .clamp(104.0, 320.0);
                let mut positioned = ps5_games
                    .iter()
                    .filter_map(|(index, game)| {
                        let offset = *index as f32 - ps5_phase;
                        if offset < -1.2 || offset > 10.0 {
                            return None;
                        }
                        let focus = self.focus_weight(*index);
                        let card_width = 160.0 + (focus_size - 120.0) * focus;
                        let left = ps5_card_left(offset, focus_size + 12.0, 132.0);
                        let center_shift = left + card_width / 2.0 - browser_width / 2.0;
                        Some((*index, *game, center_shift, offset))
                    })
                    .collect::<Vec<_>>();
                positioned.sort_by(|a, b| b.3.total_cmp(&a.3));
                let layers = positioned
                    .into_iter()
                    .map(|(index, game, shift, _)| {
                        container(self.game_card(game, self.focus_weight(index)))
                            .width(Length::Fill)
                            .height(Length::Fill)
                            .center_x(Length::Fill)
                            .center_y(Length::Fill)
                            .padding(iced::Padding {
                                left: (shift * 2.0).max(0.0),
                                right: (-shift * 2.0).max(0.0),
                                ..iced::Padding::ZERO
                            })
                            .into()
                    })
                    .collect::<Vec<Element<'_, Message>>>();
                container(stack(layers))
                    .width(Length::Fill)
                    .height(Length::Fill)
                    .clip(true)
                    .into()
            }
            _ => self.grid_cards(page_games, start),
        };
        let minimal_view = self
            .settings
            .get("minimal_views")
            .and_then(|modes| modes.get(&self.layout))
            .and_then(Value::as_bool)
            == Some(true);
        let grid_page_controls: Element<'_, Message> = if self.layout == "grid" {
            container(text(format!(
                "Página {} / {}",
                if filtered.is_empty() { 0 } else { page + 1 },
                pages
            )))
            .width(Length::Fill)
            .height(Length::Fixed(28.0))
            .center_x(Length::Fill)
            .into()
        } else {
            text("").into()
        };
        let grid_heading: Element<'_, Message> = if let Some(game) = filtered.get(self.cursor) {
            if let Some(logo) = game
                .field("logo")
                .and_then(|path| self.images.get(path))
                .cloned()
            {
                iced::widget::image::Image::new(logo)
                    .width(Length::Fill)
                    .height(Length::Fixed(80.0))
                    .content_fit(iced::ContentFit::Contain)
                    .into()
            } else {
                text(game.title()).size(26).into()
            }
        } else {
            text("Tu próxima aventura empieza aquí").size(24).into()
        };
        let details = self.selection_summary(&filtered);
        let game_browser: Element<'_, Message> = if self.layout == "grid" {
            column![scrollable(cards).height(Length::Fill), grid_page_controls,]
                .height(Length::Fill)
                .into()
        } else {
            cards
        };
        let information: Element<'_, Message> = if minimal_view {
            text("").into()
        } else if self.layout == "grid" {
            column![
                container(grid_heading)
                    .width(Length::Fill)
                    .height(Length::Fixed(84.0))
                    .center_x(Length::Fill)
                    .center_y(Length::Fill),
                summary_panel(details, Length::Fill, Length::Fill),
            ]
            .spacing(12)
            .height(Length::Fill)
            .into()
        } else {
            summary_panel(details, Length::Fill, Length::Fill)
        };
        let current_cover: Element<'_, Message> = filtered
            .get(self.cursor)
            .and_then(|game| self.cover_path(game))
            .and_then(|path| self.images.get(path))
            .cloned()
            .map(|handle| {
                iced::widget::image::Image::new(handle)
                    .width(Length::Fixed(210.0))
                    .height(Length::Fixed((self.window_height * 0.36).clamp(190.0, 340.0)))
                    .content_fit(iced::ContentFit::Contain)
                    .into()
            })
            .unwrap_or_else(|| text("").into());
        let hero_details: Element<'_, Message> = if self.layout == "ps5" {
            let title = filtered
                .get(self.cursor)
                .map(|game| game.title())
                .unwrap_or("Tu próxima aventura empieza aquí");
            column![
                text(title).size(34),
                information,
            ]
            .spacing(12)
            .into()
        } else {
            information
        };
        let hero_content: Element<'_, Message> = if matches!(self.layout.as_str(), "list" | "carousel") {
            hero_details
        } else {
            row![
                container(current_cover)
                    .width(Length::Fixed(230.0))
                    .height(Length::Fill)
                    .center_x(Length::Fill)
                    .center_y(Length::Fill),
                container(hero_details)
                    .width(Length::Fill)
                    .height(Length::Fill)
                    .center_y(Length::Fill),
            ]
            .spacing(28)
            .align_y(Alignment::Center)
            .into()
        };
        let hero = container(column![
            text("ESTANTE  /  BIBLIOTECA").size(13),
            container(text(""))
                .width(Length::Fill)
                .height(Length::Fixed(1.0))
                .style(|_| iced::widget::container::Style {
                    background: Some(iced::Background::Color(iced::Color::from_rgba(
                        1.0, 1.0, 1.0, 0.18,
                    ))),
                    ..Default::default()
                }),
            container(hero_content)
                .width(Length::Fill)
                .height(Length::Fill)
                .center_y(Length::Fill),
        ]
        .spacing(12))
        .width(Length::Fill)
        .height(Length::FillPortion(6))
        .padding([24, 52]);
        let shelf = container(column![
            text("TU BIBLIOTECA").size(14),
            game_browser,
        ]
        .spacing(12))
        .width(Length::Fill)
        .height(Length::FillPortion(4))
        .padding([16, 52])
        .style(|_| iced::widget::container::Style {
            background: Some(iced::Background::Color(iced::Color::from_rgb(
                0.035, 0.065, 0.085,
            ))),
            ..Default::default()
        });
        let gallery: Element<'_, Message> = column![hero, shelf]
            .width(Length::Fill)
            .height(Length::Fill)
            .into();

        let content: Element<'_, Message> = if self.add_open {
            let form = column![
                text("Añadir juego local").size(28),
                text("Acepta scripts .sh y AppImages. Las rutas pueden empezar por ~/.").size(13),
                text_input("Nombre del juego", &self.local_title)
                    .on_input(Message::LocalTitle)
                    .padding(10),
                button("⌨ Nombre").on_press(Message::OpenKeyboard(KeyboardTarget::LocalTitle)),
                text_input("Ruta del .sh o .AppImage", &self.local_path)
                    .on_input(Message::LocalPath)
                    .padding(10),
                button("⌨ Ruta").on_press(Message::OpenKeyboard(KeyboardTarget::LocalPath)),
                text_input("Argumentos (opcional)", &self.local_arguments)
                    .on_input(Message::LocalArguments)
                    .padding(10),
                button("⌨ Argumentos")
                    .on_press(Message::OpenKeyboard(KeyboardTarget::LocalArguments)),
                text_input("Directorio de trabajo (opcional)", &self.local_cwd)
                    .on_input(Message::LocalWorkingDirectory)
                    .padding(10),
                button("⌨ Directorio")
                    .on_press(Message::OpenKeyboard(KeyboardTarget::LocalWorkingDirectory)),
                row![
                    button("Guardar").on_press(Message::SaveLocal),
                    button("Cancelar").on_press(Message::CancelLocal)
                ]
                .spacing(10),
                self.notice.as_deref().map(text).unwrap_or_else(|| text("")),
            ]
            .spacing(14)
            .padding(24);
            let panel = container(form)
                .width(Length::Fixed(620.0))
                .height(Length::Fixed(
                    (self.window_height - 120.0).clamp(420.0, 680.0),
                ))
                .style(|_| iced::widget::container::Style {
                    background: Some(iced::Background::Color(iced::Color::from_rgb(
                        0.12, 0.10, 0.10,
                    ))),
                    border: iced::Border {
                        color: iced::Color::from_rgba(1.0, 1.0, 1.0, 0.10),
                        width: 1.0,
                        radius: 24.0.into(),
                    },
                    ..Default::default()
                });
            let scrim = container(text(""))
                .width(Length::Fill)
                .height(Length::Fill)
                .style(|_| iced::widget::container::Style {
                    background: Some(iced::Background::Color(iced::Color::from_rgba(
                        0.0, 0.0, 0.0, 0.45,
                    ))),
                    ..Default::default()
                });
            stack![
                scrim,
                container(panel)
                    .width(Length::Fill)
                    .height(Length::Fill)
                    .center_x(Length::Fill)
                    .center_y(Length::Fill),
            ]
            .width(Length::Fill)
            .height(Length::Fill)
            .into()
        } else {
            let mut categories = row![button("Todos").on_press(Message::Category(None))].spacing(8);
            for category in &self.categories {
                let label = if self.category.as_deref() == Some(category) {
                    format!("✓ {category}")
                } else {
                    category.clone()
                };
                categories = categories
                    .push(button(text(label)).on_press(Message::Category(Some(category.clone()))));
            }
            let categories = scrollable(categories)
                .direction(scrollable::Direction::Horizontal(
                    scrollable::Scrollbar::new(),
                ))
                .height(Length::Fixed(44.0));
            let views = row![
                button(if self.layout == "list" {
                    "✓ Lista"
                } else {
                    "Lista"
                })
                .on_press(Message::ChangeLayout("list".into())),
                button(if self.layout == "grid" {
                    "✓ Grid"
                } else {
                    "Grid"
                })
                .on_press(Message::ChangeLayout("grid".into())),
                button(if self.layout == "carousel" {
                    "✓ Carrusel"
                } else {
                    "Carrusel"
                })
                .on_press(Message::ChangeLayout("carousel".into())),
                button(if self.layout == "ps5" {
                    "✓ Sense"
                } else {
                    "Sense"
                })
                .on_press(Message::ChangeLayout("ps5".into())),
            ]
            .spacing(8);
            let edit = filtered
                .get(self.cursor)
                .map(|game| Message::Edit(game.id().to_owned()));
            let menu = column![
                row![
                    text("Menú").size(26),
                    iced::widget::Space::new().width(Length::Fill),
                    button("Cerrar · Y").on_press(Message::ControllerAction("menu")),
                ]
                .align_y(Alignment::Center),
                text("Buscar").size(15),
                row![
                    text_input("Título, plataforma o etiqueta", &self.query)
                        .on_input(Message::Search)
                        .padding(10)
                        .width(Length::Fill),
                    button("⌨").on_press(Message::ControllerAction("search")),
                ]
                .spacing(8),
                text("Categorías · LB / RB para cambiar").size(15),
                categories,
                text("Apariencia / vista").size(15),
                views,
                row![
                    button("Ajustes").on_press(Message::Settings),
                    button("Añadir juego").on_press(Message::AddLocal),
                    button("Editar ficha").on_press_maybe(edit),
                ]
                .spacing(8),
            ]
            .spacing(12)
            .padding(20);
            let menu = container(menu)
                .width(Length::Fixed(self.window_width.clamp(400.0, 700.0) - 40.0))
                .style(|_| iced::widget::container::Style {
                    background: Some(iced::Background::Color(iced::Color::from_rgb(
                        0.10, 0.14, 0.20,
                    ))),
                    border: iced::Border {
                        radius: 18.0.into(),
                        ..Default::default()
                    },
                    ..Default::default()
                });
            let menu_layer = stack![
                button(text(""))
                    .width(Length::Fill)
                    .height(Length::Fill)
                    .on_press(Message::ControllerAction("menu"))
                    .style(|_, _| iced::widget::button::Style {
                        background: Some(iced::Background::Color(iced::Color::from_rgba(
                            0.0, 0.0, 0.0, 0.62,
                        ))),
                        text_color: iced::Color::TRANSPARENT,
                        ..Default::default()
                    }),
                container(menu)
                    .width(Length::Fill)
                    .height(Length::Fill)
                    .center_x(Length::Fill)
                    .center_y(Length::Fill),
            ]
            .width(Length::Fill)
            .height(Length::Fill);
            let mut category_labels = vec!["Todos".to_owned()];
            category_labels.extend(self.categories.iter().cloned());
            let category_index = self
                .category
                .as_ref()
                .and_then(|category| category_labels.iter().position(|label| label == category))
                .unwrap_or(0);
            let footer = container(
                row![
                    controller_prompt(
                        "A",
                        "Detalles",
                        "confirm",
                        iced::Color::from_rgb(0.20, 0.76, 0.49)
                    ),
                    controller_prompt(
                        "X",
                        "Jugar",
                        "play",
                        iced::Color::from_rgb(0.08, 0.56, 0.97)
                    ),
                    controller_category_prompt(&category_labels, category_index),
                    controller_prompt("Y", "Menú", "menu", iced::Color::from_rgb(0.96, 0.78, 0.24)),
                    controller_prompt(
                        "B",
                        "Salir",
                        "exit",
                        iced::Color::from_rgb(0.91, 0.34, 0.36)
                    ),
                ]
                .spacing(18)
                .align_y(Alignment::Center),
            )
            .width(Length::Fill)
            .padding([8, 24])
            .style(|_| iced::widget::container::Style {
                background: Some(iced::Background::Color(iced::Color::from_rgb(
                    0.035, 0.065, 0.085,
                ))),
                ..Default::default()
            });
            let main: Element<'_, Message> = if let Some(notice) =
                self.notice.as_deref().filter(|notice| !notice.is_empty())
            {
                column![gallery, text(notice), footer]
                    .spacing(0)
                    .height(Length::Fill)
                    .into()
            } else {
                column![gallery, footer]
                    .spacing(0)
                    .height(Length::Fill)
                    .into()
            };
            if self.menu_open {
                stack![main, menu_layer]
                    .width(Length::Fill)
                    .height(Length::Fill)
                    .into()
            } else {
                main.into()
            }
        };
        container(self.with_background(content))
            .width(Length::Fill)
            .height(Length::Fill)
            .into()
    }

    fn game_view<'a>(&'a self, game: &'a Game) -> Element<'a, Message> {
        let cover: Element<'a, Message> = self
            .cover_path(game)
            .and_then(|path| self.images.get(path).cloned())
            .map(|handle| {
                iced::widget::image::Image::new(handle)
                    .height(Length::Fixed(360.0))
                    .into()
            })
            .unwrap_or_else(|| text("").into());
        let categories = game.categories().join(" · ");
        let show_launcher_details = self
            .settings
            .get("show_launcher_details")
            .and_then(|rows| rows.get(&self.layout))
            .and_then(Value::as_bool)
            .unwrap_or(true);
        let launcher_info: Element<'a, Message> = if show_launcher_details {
            column![
                text(format!(
                    "Lanzamiento: {}",
                    game.field("path")
                        .or_else(|| game.field("install"))
                        .unwrap_or("integrado")
                ))
                .size(12),
                text(format!("Proveedor: {}", game.kind_label())).size(12),
            ]
            .spacing(3)
            .into()
        } else {
            text("").into()
        };
        let metadata = game.metadata();
        let description = metadata
            .get("description")
            .or_else(|| metadata.get("synopsis"))
            .and_then(|value| value.as_str())
            .unwrap_or("Sin descripción.");
        let seconds = if game.kind() == "faugus" {
            game.data()
                .get("playtime")
                .and_then(Value::as_u64)
                .unwrap_or_else(|| self.library.session_seconds(game.id()))
        } else {
            self.library.session_seconds(game.id())
        };
        let history: Element<'a, Message> = if self
            .settings
            .get("show_session_history")
            .and_then(Value::as_bool)
            .unwrap_or(true)
        {
            column![
                text(format!(
                    "{} sesiones registradas",
                    self.library.session_count(game.id())
                ))
                .size(13),
                text(format!("Tiempo total: {}", format_duration(seconds))).size(13),
                self.library
                    .session_history(game.id())
                    .into_iter()
                    .take(5)
                    .fold(
                        column![text("Sesiones recientes").size(14)].spacing(4),
                        |rows, session| {
                            let started = session
                                .get("started")
                                .and_then(Value::as_str)
                                .unwrap_or("Fecha desconocida");
                            let seconds =
                                session.get("seconds").and_then(Value::as_u64).unwrap_or(0);
                            let failed = session
                                .get("exit_code")
                                .and_then(Value::as_i64)
                                .is_some_and(|code| code != 0);
                            rows.push(
                                text(format!(
                                    "{started} · {}{}",
                                    format_duration(seconds),
                                    if failed { " · salida con error" } else { "" }
                                ))
                                .size(12),
                            )
                        }
                    ),
            ]
            .spacing(4)
            .into()
        } else {
            text("").into()
        };
        let remove_prompt: Element<'a, Message> =
            if self.pending_remove.as_deref() == Some(game.id()) {
                row![
                    text("¿Retirar este juego?"),
                    button("Confirmar").on_press(Message::ConfirmRemove),
                    button("Cancelar").on_press(Message::CancelRemove),
                ]
                .spacing(10)
                .into()
            } else {
                text("").into()
            };
        container(
            column![
                button("← Biblioteca").on_press(Message::Back),
                cover,
                text(game.title()).size(38),
                text(format!("{} · {}", game.kind_label(), categories)).size(15),
                text(description).size(17),
                history,
                launcher_info,
                text(format!(
                    "Desarrolladores: {}",
                    metadata
                        .get("developers")
                        .and_then(Value::as_array)
                        .map(|values| values
                            .iter()
                            .filter_map(Value::as_str)
                            .collect::<Vec<_>>()
                            .join(", "))
                        .unwrap_or_default()
                ))
                .size(13),
                text(format!(
                    "Fecha de lanzamiento: {}",
                    metadata
                        .get("release_date")
                        .and_then(Value::as_str)
                        .unwrap_or("—")
                ))
                .size(13),
                button("Jugar").on_press(Message::Launch(game.id().to_owned())),
                if game.field("steam_appid").is_some() {
                    button("Completar ficha desde Steam")
                        .on_press(Message::FetchSteamMetadata(game.id().to_owned()))
                } else {
                    button("Completar ficha desde Steam").on_press_maybe(None)
                },
                button("Editar ficha").on_press(Message::Edit(game.id().to_owned())),
                button("Quitar de Estante…").on_press(Message::AskRemove(game.id().to_owned())),
                remove_prompt,
                self.notice.as_deref().map(text).unwrap_or_else(|| text("")),
            ]
            .spacing(18)
            .padding(24),
        )
        .width(Length::Fill)
        .height(Length::Fill)
        .into()
    }

    fn selection_summary<'a>(&'a self, games: &[&'a Game]) -> Element<'a, Message> {
        if self
            .settings
            .get("minimal_views")
            .and_then(|modes| modes.get(&self.layout))
            .and_then(Value::as_bool)
            == Some(true)
        {
            return text("").into();
        }
        let Some(game) = games.get(self.cursor) else {
            return column![
                text("TU BIBLIOTECA")
                    .size(12)
                    .color(iced::Color::from_rgb(1.0, 0.62, 0.64)),
                text("Tu próxima aventura empieza aquí").size(32),
            ]
            .spacing(14)
            .into();
        };
        let show_details = self
            .settings
            .get("show_launcher_details")
            .and_then(|modes| modes.get(&self.layout))
            .and_then(Value::as_bool)
            .unwrap_or(true);
        let metadata = game.metadata();
        let credits = [
            ("Desarrolladores", "developers"),
            ("Editores", "publishers"),
            ("Plataformas", "platforms"),
            ("Géneros", "genres"),
            ("Lanzamiento", "release_date"),
        ]
        .into_iter()
        .filter_map(|(label, key)| {
            let value = metadata.get(key)?;
            let values = value
                .as_array()
                .map(|values| {
                    values
                        .iter()
                        .filter_map(Value::as_str)
                        .collect::<Vec<_>>()
                        .join(", ")
                })
                .or_else(|| value.as_str().map(str::to_owned))
                .unwrap_or_default();
            (!values.is_empty()).then(|| format!("{label}: {values}"))
        })
        .collect::<Vec<_>>();
        let summary = metadata
            .get("description")
            .or_else(|| metadata.get("synopsis"))
            .and_then(Value::as_str)
            .filter(|value| !value.trim().is_empty())
            .unwrap_or("Sin sinopsis disponible.");
        let seconds = if game.kind() == "faugus" {
            game.data()
                .get("playtime")
                .and_then(Value::as_u64)
                .unwrap_or_else(|| self.library.session_seconds(game.id()))
        } else {
            self.library.session_seconds(game.id())
        };
        let show_history = self
            .settings
            .get("show_session_history")
            .and_then(Value::as_bool)
            .unwrap_or(true);
        let launcher = if show_details {
            format!(
                "{} · {}",
                game.kind_label(),
                game.field("path")
                    .or_else(|| game.field("install"))
                    .unwrap_or("integrado")
            )
        } else {
            String::new()
        };
        let information_width = self.window_width;
        if self.layout == "list" {
            let cover_zoom = self
                .settings
                .get("list_cover_zoom")
                .and_then(Value::as_f64)
                .map(|value| (value as f32 / 100.0).clamp(0.5, 1.75))
                .unwrap_or(1.0);
            let vertical = matches!(
                self.settings.get("list_side").and_then(Value::as_str),
                Some("left" | "right") | None
            );
            let hero_width = (information_width - 48.0).max(1.0);
            let cover_width =
                (260.0 * cover_zoom).min(hero_width * if vertical { 0.65 } else { 0.28 });
            let cover_height = list_detail_cover_height(self.window_height, cover_width, vertical);
            let cover: Element<'a, Message> = self
                .cover_path(game)
                .and_then(|path| self.images.get(path))
                .cloned()
                .map(|handle| {
                    iced::widget::image::Image::new(handle)
                        .width(Length::Fixed(cover_width))
                        .height(Length::Fixed(cover_height))
                        .content_fit(iced::ContentFit::Contain)
                        .into()
                })
                .unwrap_or_else(|| text("").into());
            let info = column![
                text("TU BIBLIOTECA")
                    .size(14)
                    .color(iced::Color::from_rgb(1.0, 0.62, 0.64)),
                text(game.title()).size(34),
                text(launcher).size(15),
                text(summary).size(16),
                text(game.categories().join(" · ")).size(15),
                column(credits.into_iter().map(|line| text(line).size(14).into())).spacing(2),
                if show_history {
                    text(format!(
                        "Tiempo jugado: {} · Sesiones: {} · Última vez: {}",
                        format_duration(seconds),
                        self.library.session_count(game.id()),
                        game.data()
                            .get("last_played")
                            .and_then(Value::as_str)
                            .unwrap_or("Sin datos")
                    ))
                    .size(14)
                } else {
                    text("").size(14)
                },
            ]
            .spacing(14);
            return row![cover, info]
                .spacing(32)
                .align_y(Alignment::Center)
                .into();
        }
        if self.layout == "carousel" {
            let cover_zoom = self
                .settings
                .get("list_cover_zoom")
                .and_then(Value::as_f64)
                .map(|value| value as f32 / 100.0)
                .unwrap_or(1.0)
                .clamp(0.5, 2.0);
            let group_width = (information_width - 48.0).max(1.0);
            let cover_width = (260.0_f32 * cover_zoom).min(group_width * 0.28);
            let cover: Element<'a, Message> = self
                .cover_path(game)
                .and_then(|path| self.images.get(path))
                .cloned()
                .map(|handle| {
                    iced::widget::image::Image::new(handle)
                        .width(Length::Fixed(cover_width))
                        .height(Length::Fixed((cover_width * 1.5).min(500.0)))
                        .content_fit(iced::ContentFit::Contain)
                        .into()
                })
                .unwrap_or_else(|| text("").into());
            let heading: Element<'a, Message> = game
                .field("logo")
                .and_then(|path| self.images.get(path))
                .cloned()
                .map(|handle| {
                    iced::widget::image::Image::new(handle)
                        .width(Length::Fixed(360.0))
                        .height(Length::Fixed(80.0))
                        .content_fit(iced::ContentFit::Contain)
                        .into()
                })
                .unwrap_or_else(|| text(game.title()).size(30).into());
            let info = column![
                heading,
                text("TU BIBLIOTECA")
                    .size(14)
                    .color(iced::Color::from_rgb(1.0, 0.62, 0.64)),
                text(format!(
                    "Tiempo jugado: {} · Sesiones: {} · Última vez: {}",
                    format_duration(seconds),
                    self.library.session_count(game.id()),
                    game.data()
                        .get("last_played")
                        .and_then(Value::as_str)
                        .unwrap_or("Sin datos")
                ))
                .size(14),
                text(launcher).size(15),
                text(summary).size(16),
                text(game.categories().join(" · ")).size(15),
                column(credits.into_iter().map(|line| text(line).size(14).into())).spacing(2),
            ]
            .spacing(12);
            return row![cover, info]
                .spacing(40)
                .align_y(Alignment::Center)
                .into();
        }
        if self.layout == "grid" {
            let genres = metadata
                .get("genres")
                .map(|value| match value {
                    Value::Array(values) => values
                        .iter()
                        .filter_map(Value::as_str)
                        .collect::<Vec<_>>()
                        .join(" · "),
                    Value::String(value) => value.clone(),
                    _ => String::new(),
                })
                .unwrap_or_default();
            let details = credits
                .into_iter()
                .filter(|line| !line.starts_with("Géneros:"))
                .collect::<Vec<_>>();
            column![
                text("TU BIBLIOTECA")
                    .size(14)
                    .color(iced::Color::from_rgb(1.0, 0.62, 0.64)),
                text(format!(
                    "Tiempo jugado: {} · Sesiones: {} · Última vez: {}",
                    format_duration(seconds),
                    self.library.session_count(game.id()),
                    game.data()
                        .get("last_played")
                        .and_then(Value::as_str)
                        .unwrap_or("Sin datos")
                ))
                .size(14),
                text(launcher).size(15),
                text(summary).size(16),
                text(genres).size(15),
                column(details.into_iter().map(|line| text(line).size(14).into())).spacing(2),
            ]
            .spacing(14)
            .into()
        } else {
            column![
                text("TU BIBLIOTECA")
                    .size(14)
                    .color(iced::Color::from_rgb(1.0, 0.62, 0.64)),
                text(game.title()).size(34),
                text(launcher).size(15),
                text(summary).size(16),
                text(game.categories().join(" · ")).size(15),
                column(credits.into_iter().map(|line| text(line).size(14).into())).spacing(2),
                if show_history {
                    text(format!(
                        "Tiempo jugado: {} · Sesiones: {} · Última vez: {}",
                        format_duration(seconds),
                        self.library.session_count(game.id()),
                        game.data()
                            .get("last_played")
                            .and_then(Value::as_str)
                            .unwrap_or("Sin datos")
                    ))
                    .size(14)
                } else {
                    text("").size(14)
                },
            ]
            .spacing(12)
            .into()
        }
    }

    fn grid_cards<'a>(&'a self, games: Vec<&'a Game>, start: usize) -> Element<'a, Message> {
        let zoom = self
            .settings
            .get("grid_zoom")
            .and_then(Value::as_u64)
            .unwrap_or(100)
            .clamp(50, 200) as f32
            / 100.0;
        let cell_width = (180.0 * zoom).clamp(140.0, 260.0);
        let columns = self.columns_for_width(self.window_width);
        let cell_height = cell_width
            * if self
                .settings
                .get("cover_formats")
                .and_then(|formats| formats.get("grid"))
                .and_then(Value::as_str)
                == Some("square")
            {
                1.1
            } else {
                1.55
            };
        games
            .chunks(columns)
            .enumerate()
            .fold(column![].spacing(16), |column, (row_index, row_games)| {
                let row = row_games.iter().enumerate().fold(
                    row![].spacing(16),
                    |row, (column_index, game)| {
                        row.push(self.grid_card(
                            game,
                            self.focus_weight(start + row_index * columns + column_index),
                            cell_width - 16.0,
                            cell_height - 16.0,
                        ))
                    },
                );
                column.push(container(row).width(Length::Fill).center_x(Length::Fill))
            })
            .width(Length::Fill)
            .height(Length::Shrink)
            .into()
    }

    fn grid_card<'a>(
        &'a self,
        game: &'a Game,
        focus: f32,
        width: f32,
        height: f32,
    ) -> Element<'a, Message> {
        let (ring_enabled, ring_color, ring_width, ring_radius) =
            selection_ring(&self.settings, "grid");
        let image_radius = self
            .settings
            .get("cover_radii")
            .and_then(|modes| modes.get("grid"))
            .and_then(Value::as_u64)
            .unwrap_or(12) as f32;
        let layout_opacity = self.layout_opacity();
        let inner_width = (width - 16.0).max(1.0);
        let inner_height = (height - 22.0).max(1.0);
        let image: Element<'a, Message> = self
            .cover_path(game)
            .and_then(|path| self.images.get(path))
            .cloned()
            .map(|handle| {
                iced::widget::image::Image::new(handle)
                    .width(Length::Fixed(inner_width))
                    .height(Length::Fixed(inner_height))
                    .content_fit(iced::ContentFit::Contain)
                    .border_radius(image_radius)
                    .opacity(layout_opacity)
                    .into()
            })
            .unwrap_or_else(|| text(game.title()).size(14).into());
        let image: Element<'a, Message> = stack![
            image,
            container(text(""))
                .width(Length::Fill)
                .height(Length::Fill)
                .style(move |_| iced::widget::container::Style {
                    background: Some(iced::Background::Color(iced::Color::from_rgba(
                        0.0,
                        0.0,
                        0.0,
                        0.35 * (1.0 - focus),
                    ))),
                    ..Default::default()
                }),
        ]
        .into();
        let body = column![
            container(image)
                .width(Length::Fill)
                .height(Length::Fixed(inner_height))
                .center_x(Length::Fill)
                .center_y(Length::Fill),
            focus_plate(
                if ring_enabled { focus } else { 0.0 },
                inner_width,
                ring_color
            ),
        ]
        .spacing(2);
        button(body)
            .width(Length::Fixed(width))
            .height(Length::Fixed(height))
            .padding(8)
            .clip(true)
            .style(move |_, _| iced::widget::button::Style {
                background: None,
                text_color: iced::Color::WHITE,
                border: iced::Border {
                    color: ring_color
                        .scale_alpha(0.92 * focus * if ring_enabled { 1.0 } else { 0.0 }),
                    width: ring_width * focus * if ring_enabled { 1.0 } else { 0.0 },
                    radius: ring_radius.into(),
                },
                ..Default::default()
            })
            .on_press(Message::Select(game.id().to_owned()))
            .into()
    }

    fn with_background<'a>(&'a self, content: Element<'a, Message>) -> Element<'a, Message> {
        let path = self.background_path();
        let composite = self.background_composite_spec();
        let requested_key = composite
            .as_ref()
            .map(|(primary, secondary, split)| background_composite_key(primary, secondary, split));
        let requested_key = requested_key.or_else(|| path.clone());
        let render_key = self
            .displayed_background_key
            .clone()
            .or_else(|| requested_key.clone());
        let rendering_requested = render_key == requested_key;
        let handle = render_key.as_ref().and_then(|key| {
            if self.background_blur() > 0 {
                self.background_images
                    .get(&blur_cache_key(key, self.background_blur()))
                    .cloned()
            } else {
                None
            }
            .or_else(|| self.images.get(key).cloned())
            .or_else(|| {
                if rendering_requested {
                    path.as_ref()
                        .and_then(|path| self.images.get(path).cloned())
                } else {
                    None
                }
            })
        });
        if let Some(handle) = handle {
            let composited = render_key
                .as_deref()
                .is_some_and(|key| key.starts_with("composite:"));
            let secondary = rendering_requested
                .then(|| self.background_secondary_path())
                .flatten()
                .and_then(|path| self.images.get(&path).cloned());
            let split = self
                .settings
                .get("background_splits")
                .and_then(|rows| rows.get(&self.layout))
                .and_then(Value::as_str)
                .unwrap_or("single");
            let dim = if self.screensaver_active {
                0.0
            } else {
                self.settings
                    .get("background_dim")
                    .and_then(|rows| rows.get(&self.layout))
                    .and_then(Value::as_u64)
                    .unwrap_or(0) as f32
                    / 100.0
            };
            let minimal = self
                .settings
                .get("minimal_views")
                .and_then(|rows| rows.get(&self.layout))
                .and_then(Value::as_bool)
                == Some(true);
            let position = if minimal {
                "full"
            } else {
                self.settings
                    .get("hero_positions")
                    .and_then(|rows| rows.get(&self.layout))
                    .and_then(Value::as_str)
                    .unwrap_or("full")
            };
            let hero = || {
                iced::widget::image::Image::new(handle.clone())
                    .width(Length::Fill)
                    .height(Length::Fill)
                    .content_fit(iced::ContentFit::Cover)
            };
            let background: Element<'a, Message> = if composited {
                hero().into()
            } else if let Some(secondary) = secondary {
                let second = iced::widget::image::Image::new(secondary)
                    .width(Length::Fill)
                    .height(Length::Fill)
                    .content_fit(iced::ContentFit::Cover);
                match split {
                    "horizontal" => column![
                        hero().height(Length::FillPortion(1)),
                        second.height(Length::FillPortion(1)),
                    ]
                    .width(Length::Fill)
                    .height(Length::Fill)
                    .into(),
                    "vertical" => row![
                        hero().width(Length::FillPortion(1)),
                        second.width(Length::FillPortion(1)),
                    ]
                    .width(Length::Fill)
                    .height(Length::Fill)
                    .into(),
                    _ => match position {
                        "top" => column![hero(), container(text("")).height(Length::Fill)].into(),
                        "lower" => column![container(text("")).height(Length::Fill), hero()].into(),
                        _ => hero().into(),
                    },
                }
            } else {
                if matches!(position, "top" | "lower") {
                    let reverse = position == "lower";
                    stack![
                        hero(),
                        container(text(""))
                            .width(Length::Fill)
                            .height(Length::Fill)
                            .style(move |_| iced::widget::container::Style {
                                background: Some(iced::Background::Gradient(
                                    iced::Gradient::Linear(
                                        iced::gradient::Linear::new(iced::Radians(if reverse {
                                            -std::f32::consts::FRAC_PI_2
                                        } else {
                                            std::f32::consts::FRAC_PI_2
                                        }))
                                        .add_stop(
                                            0.0,
                                            iced::Color::from_rgba(
                                                0.0,
                                                0.0,
                                                0.0,
                                                if reverse { 0.85 } else { 0.0 }
                                            )
                                        )
                                        .add_stop(
                                            0.45,
                                            iced::Color::from_rgba(
                                                0.0,
                                                0.0,
                                                0.0,
                                                if reverse { 0.85 } else { 0.0 }
                                            )
                                        )
                                        .add_stop(0.7, iced::Color::from_rgba(0.0, 0.0, 0.0, 0.55))
                                        .add_stop(
                                            1.0,
                                            iced::Color::from_rgba(
                                                0.0,
                                                0.0,
                                                0.0,
                                                if reverse { 0.0 } else { 0.92 }
                                            )
                                        ),
                                    ),
                                )),
                                ..Default::default()
                            }),
                    ]
                    .into()
                } else {
                    hero().into()
                }
            };
            let old_background = self
                .background_transition
                .as_ref()
                .filter(|(previous, _)| previous != render_key.as_deref().unwrap_or_default())
                .and_then(|(previous, started)| {
                    let handle = if self.background_blur() > 0 {
                        self.background_images
                            .get(&blur_cache_key(previous, self.background_blur()))
                    } else {
                        None
                    }
                    .or_else(|| self.images.get(previous))
                    .cloned()?;
                    let opacity =
                        1.0 - ease_progress(started.elapsed(), Duration::from_millis(240));
                    Some(
                        iced::widget::image::Image::new(handle)
                            .width(Length::Fill)
                            .height(Length::Fill)
                            .content_fit(iced::ContentFit::Cover)
                            .opacity(opacity),
                    )
                });
            let background: Element<'a, Message> = if let Some(old_background) = old_background {
                stack![background, old_background].into()
            } else {
                background
            };
            let dim_layer = container(text(""))
                .width(Length::Fill)
                .height(Length::Fill)
                .style(move |_| iced::widget::container::Style {
                    background: Some(iced::Background::Color(iced::Color::from_rgba(
                        0.0, 0.0, 0.0, dim,
                    ))),
                    ..Default::default()
                });
            stack![background, dim_layer, content].into()
        } else {
            content
        }
    }

    fn playing_view<'a>(&'a self, session: &'a RunningSession) -> Element<'a, Message> {
        let cover: Element<'_, Message> = self
            .cover_path(&session.game)
            .and_then(|path| self.images.get(path).cloned())
            .map(|handle| {
                iced::widget::image(handle)
                    .width(Length::Fixed(
                        self.window_width.mul_add(0.3, 0.0).min(240.0),
                    ))
                    .height(Length::Fixed(
                        self.window_height.mul_add(0.5, 0.0).min(360.0),
                    ))
                    .content_fit(iced::ContentFit::Contain)
                    .into()
            })
            .unwrap_or_else(|| iced::widget::Space::new().height(Length::Fixed(1.0)).into());
        container(
            column![
                cover,
                text("Jugando").size(18),
                text(session.game.title()).size(28),
                text("La biblioteca se restaurará cuando termine el juego.").size(14),
            ]
            .align_x(Alignment::Center)
            .spacing(20)
            .width(Length::Fixed((self.window_width - 64.0).min(500.0))),
        )
        .width(Length::Fill)
        .height(Length::Fill)
        .center_x(Length::Fill)
        .center_y(Length::Fill)
        .style(|_| iced::widget::container::Style {
            background: Some(iced::Background::Color(iced::Color::from_rgb(
                0.06, 0.055, 0.055,
            ))),
            ..Default::default()
        })
        .into()
    }

    fn screensaver_view(&self) -> Element<'_, Message> {
        let progress = self
            .screensaver_transition_started
            .map(|started| ease_progress(started.elapsed(), Duration::from_millis(500)))
            .unwrap_or(0.0);
        let previous = self
            .screensaver_previous_path
            .as_ref()
            .and_then(|path| self.images.get(path))
            .cloned()
            .map(|handle| {
                iced::widget::image::Image::new(handle)
                    .width(Length::Fill)
                    .height(Length::Fill)
                    .content_fit(iced::ContentFit::Cover)
                    .opacity(1.0 - progress)
            });
        let current = self
            .background_path()
            .and_then(|path| self.images.get(&path))
            .cloned()
            .map(|handle| {
                iced::widget::image::Image::new(handle)
                    .width(Length::Fill)
                    .height(Length::Fill)
                    .content_fit(iced::ContentFit::Cover)
                    .opacity(if self.screensaver_previous_path.is_some() {
                        progress
                    } else {
                        1.0
                    })
            });
        let mut layers = vec![
            container(text(""))
                .width(Length::Fill)
                .height(Length::Fill)
                .into(),
        ];
        if let Some(image) = previous {
            layers.push(image.into());
        }
        if let Some(image) = current {
            layers.push(image.into());
        }
        let dim = self
            .settings
            .get("screensaver_dim")
            .and_then(Value::as_u64)
            .unwrap_or(35) as f32
            / 100.0;
        layers.push(
            container(text(""))
                .width(Length::Fill)
                .height(Length::Fill)
                .style(move |_| iced::widget::container::Style {
                    background: Some(iced::Background::Color(iced::Color::from_rgba(
                        0.0, 0.0, 0.0, dim,
                    ))),
                    ..Default::default()
                })
                .into(),
        );
        stack(layers).into()
    }

    fn settings_screen(&self) -> Element<'_, Message> {
        let sections = [
            ("global", "Globales"),
            ("scan", "Escaneo y scraping"),
            ("categories", "Categorías"),
            ("list", "Lista"),
            ("grid", "Grid"),
            ("carousel", "Carrusel"),
            ("ps5", "Sense"),
        ];
        let navigation = sections.iter().fold(
            column![
                text("Ajustes de Estante").size(22),
                button("← Biblioteca")
                    .width(Length::Fill)
                    .on_press(Message::Settings)
            ]
            .spacing(8),
            |row, (key, label)| {
                row.push(
                    button(text(if self.settings_section == *key {
                        format!("✓ {label}")
                    } else {
                        (*label).to_owned()
                    }))
                    .on_press(Message::SettingsSection((*key).to_owned())),
                )
            },
        );
        let specs = settings::specs();
        let visible_specs = specs
            .iter()
            .filter(|spec| settings::group(&spec.path) == self.settings_section)
            .collect::<Vec<_>>();
        let mut rows = (0..2)
            .map(|side| {
                visible_specs
                    .iter()
                    .enumerate()
                    .filter(|(index, _)| index % 2 == side)
                    .fold(column![].spacing(12), |column, (_, spec)| {
                        column.push(self.setting_control(spec))
                    })
            })
            .collect::<Vec<_>>();
        let rows_left = rows.remove(0);
        let rows_right = rows.remove(0);
        let update_controls: Element<'_, Message> = if self.settings_section == "global" {
            column![
                text("Actualizaciones").size(18),
                button(if self.update_checking {
                    "Comprobando…"
                } else {
                    "Comprobar actualizaciones"
                })
                .on_press_maybe(
                    (!self.update_checking && !self.update_installing)
                        .then_some(Message::CheckUpdates)
                ),
                self.update_status
                    .as_deref()
                    .map(text)
                    .unwrap_or_else(|| text("")),
                button(if self.update_installing {
                    "Instalando…"
                } else {
                    "Descargar e instalar"
                })
                .on_press_maybe(
                    self.update_release
                        .clone()
                        .filter(|_| updates::appimage_path().is_some()
                            && !self.update_installing
                            && !self.update_checking)
                        .map(Message::InstallUpdate)
                ),
            ]
            .spacing(8)
            .into()
        } else {
            text("").into()
        };
        let screensaver_controls: Element<'_, Message> = if self.settings_section == "global" {
            button("Probar salvapantallas")
                .on_press(Message::PreviewScreensaver)
                .into()
        } else {
            text("").into()
        };
        let launcher_controls: Element<'_, Message> = if self.settings_section == "global" {
            [
                ("steam", "Steam"),
                ("faugus", "Faugus"),
                ("heroic", "Heroic"),
            ]
            .into_iter()
            .fold(
                column![text("Lanzadores").size(18)].spacing(8),
                |column, (key, name)| {
                    let state = self.launcher_states.get(key).map(String::as_str);
                    column.push(
                        row![
                            text(format!(
                                "{name}: {}",
                                match state {
                                    Some("open") => "Abierto",
                                    Some("closed") => "Cerrado",
                                    Some("opening") => "Abriendo…",
                                    Some("closing") => "Cerrando…",
                                    Some("missing") => "No instalado",
                                    Some("error") => "Error",
                                    Some("timeout") => "Tiempo de espera agotado",
                                    _ => "Comprobando…",
                                }
                            ))
                            .width(Length::FillPortion(1)),
                            button(if self.launcher_busy {
                                "Procesando…"
                            } else if state == Some("open") {
                                "Cerrar"
                            } else {
                                "Abrir"
                            })
                            .on_press_maybe(
                                (!self.launcher_busy
                                    && matches!(
                                        state,
                                        Some("open" | "closed" | "error" | "timeout" | "missing")
                                    ))
                                .then(|| {
                                    Message::ManageLauncher(key.into(), state != Some("open"))
                                })
                            ),
                        ]
                        .spacing(8)
                        .width(Length::Fill),
                    )
                },
            )
            .into()
        } else {
            text("").into()
        };
        let library_controls: Element<'_, Message> = if self.settings_section == "global" {
            column![
                text("Biblioteca").size(18),
                row![
                    button(if self.scraping {
                        "Cancelar scraping"
                    } else {
                        "Completar datos"
                    })
                    .on_press(if self.scraping {
                        Message::CancelScrape
                    } else {
                        Message::Scrape(false)
                    }),
                    button(if self.scraping {
                        "Procesando…"
                    } else {
                        "Reemplazar datos"
                    })
                    .on_press_maybe((!self.scraping).then_some(Message::Scrape(true))),
                    button("Restaurar excluidos").on_press(Message::RestoreImports),
                ]
                .spacing(8),
            ]
            .spacing(8)
            .into()
        } else {
            text("").into()
        };
        let category_controls: Element<'_, Message> = if self.settings_section == "categories" {
            let primary = self.library.primary_category();
            let primary_choices = std::iter::once(None)
                .chain(self.categories.iter().map(|name| Some(name.as_str())))
                .fold(row![].spacing(6), |choices, name| {
                    let selected = primary == name;
                    choices.push(
                        button(text(if selected {
                            format!("✓ {}", name.unwrap_or("Todos"))
                        } else {
                            name.unwrap_or("Todos").to_owned()
                        }))
                        .on_press(Message::SetPrimaryCategory(name.map(str::to_owned))),
                    )
                });
            let icon_targets = std::iter::once(None)
                .chain(self.categories.iter().map(|name| Some(name.as_str())))
                .fold(row![].spacing(6), |choices, name| {
                    choices.push(
                        button(text(if self.category_icon_target.as_deref() == name {
                            format!("✓ {}", name.unwrap_or("Todos"))
                        } else {
                            name.unwrap_or("Todos").to_owned()
                        }))
                        .on_press(Message::CategoryIconTarget(name.map(str::to_owned))),
                    )
                });
            let icon_results = self
                .category_icon_results
                .iter()
                .skip(self.category_icon_page * 12)
                .take(12)
                .fold(column![].spacing(4), |rows, option| {
                    rows.push(
                        button(text(format!(
                            "{} · {} · {}",
                            option.name, option.author, option.license
                        )))
                        .width(Length::Fill)
                        .on_press(Message::ChooseCategoryIcon(
                            option.clone(),
                            self.category_icon_target.clone(),
                        )),
                    )
                });
            let icon_preview: Element<'_, Message> = self
                .images
                .get(&self.category_icon_path)
                .cloned()
                .map(|handle| {
                    iced::widget::image(handle)
                        .width(Length::Fixed(64.0))
                        .height(Length::Fixed(64.0))
                        .into()
                })
                .unwrap_or_else(|| text("Sin icono asignado").into());
            let game_rows: Element<'_, Message> = if let Some(category) = &self.category_games_open
            {
                let query = normalize_search(&self.category_games_query);
                let rows = self
                    .games
                    .iter()
                    .filter(|game| {
                        let title = game
                            .metadata()
                            .get("title")
                            .and_then(Value::as_str)
                            .unwrap_or_else(|| game.title());
                        query.is_empty() || normalize_search(title).contains(&query)
                    })
                    .fold(column![].spacing(4), |rows, game| {
                        let member = game.categories().iter().any(|name| name == category);
                        let title = game
                            .metadata()
                            .get("title")
                            .and_then(Value::as_str)
                            .unwrap_or_else(|| game.title());
                        rows.push(
                            button(text(format!("{} {title}", if member { "☑" } else { "☐" })))
                                .width(Length::Fill)
                                .on_press(Message::SetCategoryGame(
                                    category.clone(),
                                    game.id().to_owned(),
                                    !member,
                                )),
                        )
                    });
                column![
                    text(format!("Juegos de «{category}»")).size(16),
                    text_input("Buscar juegos…", &self.category_games_query)
                        .on_input(Message::CategoryGamesQuery)
                        .padding(8),
                    scrollable(rows).height(Length::Fixed(260.0)),
                ]
                .spacing(8)
                .into()
            } else {
                text("").into()
            };
            column![
                text("Categorías").size(18),
                text("Elige la categoría que se abre al iniciar y administra su orden y nombre.")
                    .size(13),
                text("Categoría principal").size(15),
                scrollable(primary_choices).direction(scrollable::Direction::Horizontal(
                    scrollable::Scrollbar::new(),
                )),
                row![
                    text_input(
                        if self.category_rename_target.is_some() {
                            "Nuevo nombre"
                        } else {
                            "Nueva categoría"
                        },
                        &self.category_name,
                    )
                    .on_input(Message::CategoryName)
                    .padding(8)
                    .width(Length::Fixed(300.0)),
                    button("Teclado").on_press(Message::OpenKeyboard(KeyboardTarget::CategoryName)),
                    button(if self.category_rename_target.is_some() {
                        "Guardar nombre"
                    } else {
                        "Añadir categoría"
                    })
                    .on_press(if self.category_rename_target.is_some() {
                        Message::RenameCategorySave
                    } else {
                        Message::AddCategory
                    }),
                    button("Cancelar").on_press_maybe(
                        self.category_rename_target
                            .as_ref()
                            .map(|_| Message::RenameCategoryStart(String::new()))
                    ),
                ]
                .spacing(8),
                self.categories.iter().enumerate().fold(
                    column![].spacing(6),
                    |rows, (index, category)| {
                        rows.push(row![
                            text(category).width(Length::Fill),
                            button(text(format!(
                                "Juegos ({})",
                                self.games
                                    .iter()
                                    .filter(|game| game
                                        .categories()
                                        .iter()
                                        .any(|name| name == category))
                                    .count()
                            )))
                            .on_press(Message::ToggleCategoryGames(category.clone())),
                            button("↑").on_press_maybe(
                                (index > 0).then(|| Message::MoveCategory(category.clone(), -1))
                            ),
                            button("↓").on_press_maybe(
                                (index + 1 < self.categories.len())
                                    .then(|| Message::MoveCategory(category.clone(), 1))
                            ),
                            button("Renombrar")
                                .on_press(Message::RenameCategoryStart(category.clone())),
                            button("Eliminar").on_press(Message::RemoveCategory(category.clone())),
                        ])
                    }
                ),
                game_rows,
                text("Iconos de categorías").size(18),
                text("Iconos para").size(14),
                scrollable(icon_targets).direction(scrollable::Direction::Horizontal(
                    scrollable::Scrollbar::new(),
                )),
                icon_preview,
                row![
                    text_input("Ruta de icono local", &self.category_icon_path)
                        .on_input(Message::CategoryIconLocalPath)
                        .padding(8)
                        .width(Length::Fill),
                    button("Usar icono local").on_press(Message::UseLocalCategoryIcon),
                    button("Quitar icono").on_press(Message::ClearCategoryIcon),
                ]
                .spacing(8),
                row![
                    button(if self.category_icon_provider == "bootstrap" {
                        "✓ Bootstrap Icons"
                    } else {
                        "Bootstrap Icons"
                    })
                    .on_press(Message::CategoryIconProvider("bootstrap".into())),
                    button(if self.category_icon_provider == "iconify" {
                        "✓ Iconify"
                    } else {
                        "Iconify"
                    })
                    .on_press(Message::CategoryIconProvider("iconify".into())),
                    button(if self.category_icon_provider == "simpleicons" {
                        "✓ Simple Icons"
                    } else {
                        "Simple Icons"
                    })
                    .on_press(Message::CategoryIconProvider("simpleicons".into())),
                    text_input("Buscar icono en inglés", &self.category_icon_query)
                        .on_input(Message::CategoryIconQuery)
                        .padding(8)
                        .width(Length::Fill),
                    button(if self.category_icons_searching {
                        "Buscando…"
                    } else {
                        "Buscar iconos"
                    })
                    .on_press_maybe(
                        (!self.category_icons_searching).then_some(Message::SearchCategoryIcons)
                    ),
                ]
                .spacing(8),
                row![
                    text(format!(
                        "{} iconos · página {} de {}",
                        self.category_icon_results.len(),
                        self.category_icon_page + 1,
                        self.category_icon_results.len().div_ceil(12).max(1)
                    ))
                    .width(Length::Fill),
                    button("Anterior").on_press_maybe(
                        (self.category_icon_page > 0).then_some(Message::CategoryIconPage(-1))
                    ),
                    button("Siguiente").on_press_maybe(
                        (self.category_icon_page + 1
                            < self.category_icon_results.len().div_ceil(12))
                        .then_some(Message::CategoryIconPage(1))
                    ),
                ]
                .spacing(8),
                icon_results,
            ]
            .spacing(12)
            .into()
        } else {
            text("").into()
        };
        let provider_controls: Element<'_, Message> = if self.settings_section == "scan" {
            column![
                text("Escanear proveedor").size(18),
                row![
                    button("Steam").on_press_maybe(
                        (!self.scanning).then(|| Message::ScanProvider("steam".into()))
                    ),
                    button("Faugus").on_press_maybe(
                        (!self.scanning).then(|| Message::ScanProvider("faugus".into()))
                    ),
                    button("Heroic").on_press_maybe(
                        (!self.scanning).then(|| Message::ScanProvider("heroic".into()))
                    ),
                    button("Todos")
                        .on_press_maybe((!self.scanning).then_some(Message::ScanImports)),
                ]
                .spacing(8)
            ]
            .spacing(8)
            .into()
        } else {
            text("").into()
        };
        let (title, description) = match self.settings_section.as_str() {
            "global" => (
                "Ajustes globales",
                "Preferencias generales, controles y apariencia de la biblioteca.",
            ),
            "scan" => ("Escaneo y scraping", "Configura y ejecuta los proveedores."),
            "categories" => ("Categorías", "Organiza tus juegos en categorías."),
            "list" => ("Lista", "Ajustes de esta apariencia."),
            "grid" => ("Grid", "Ajustes de esta apariencia."),
            "carousel" => ("Carrusel", "Ajustes de esta apariencia."),
            _ => ("Sense", "Ajustes de esta apariencia."),
        };
        let right_content = column![
            text(title).size(24),
            text(description).size(14),
            scrollable(
                column![
                    row![
                        rows_left.width(Length::Fill),
                        rows_right.width(Length::Fill),
                    ]
                    .spacing(16)
                    .width(Length::Fill),
                    screensaver_controls,
                    update_controls,
                    launcher_controls,
                    provider_controls,
                    category_controls,
                    library_controls,
                    self.notice.as_deref().map(text).unwrap_or_else(|| text("")),
                ]
                .spacing(18)
                .width(Length::Fill),
            )
            .height(Length::Fill),
        ]
        .spacing(16)
        .width(Length::Fill)
        .height(Length::Fill);
        let panel = container(
            row![
                scrollable(navigation)
                    .width(Length::Fixed(196.0))
                    .height(Length::Fill),
                right_content,
            ]
            .spacing(28)
            .height(Length::Fill),
        )
        .width(Length::Fixed(
            (self.window_width - 64.0).clamp(600.0, 1440.0),
        ))
        .height(Length::Fixed((self.window_height - 64.0).max(300.0)))
        .padding(24)
        .style(|_| iced::widget::container::Style {
            background: Some(iced::Background::Color(iced::Color::from_rgb(
                0.12, 0.10, 0.10,
            ))),
            border: iced::Border {
                color: iced::Color::from_rgba(1.0, 1.0, 1.0, 0.10),
                width: 1.0,
                radius: 24.0.into(),
            },
            ..Default::default()
        });
        let scrim = container(text(""))
            .width(Length::Fill)
            .height(Length::Fill)
            .style(|_| iced::widget::container::Style {
                background: Some(iced::Background::Color(iced::Color::from_rgba(
                    0.0, 0.0, 0.0, 0.45,
                ))),
                ..Default::default()
            });
        stack![
            scrim,
            container(panel)
                .width(Length::Fill)
                .height(Length::Fill)
                .center_x(Length::Fill)
                .center_y(Length::Fill),
        ]
        .width(Length::Fill)
        .height(Length::Fill)
        .into()
    }

    fn setting_control<'a>(&'a self, spec: &settings::Spec) -> Element<'a, Message> {
        let value = settings::read(&self.settings, spec).expect("settings defaults initialized");
        let path = spec
            .path
            .iter()
            .map(|part| (*part).to_owned())
            .collect::<Vec<_>>();
        let input: Element<'a, Message> = match &spec.kind {
            settings::Kind::Bool => {
                let enabled = value.as_bool().unwrap_or(false);
                checkbox(enabled)
                    .label(spec.label)
                    .size(19)
                    .spacing(10)
                    .on_toggle(move |enabled| {
                        Message::SetSettingPath(path.clone(), Value::Bool(enabled))
                    })
                    .width(Length::Fill)
                    .into()
            }
            settings::Kind::Number(min, _) => {
                text_input("", &value.as_u64().unwrap_or(*min).to_string())
                    .on_input(move |input| {
                        Message::SetSettingPath(
                            path.clone(),
                            input.parse::<u64>().map(Value::from).unwrap_or(Value::Null),
                        )
                    })
                    .padding(8)
                    .into()
            }
            settings::Kind::Choice(options) => {
                let selected = value.as_str().unwrap_or_default();
                let choices = options
                    .iter()
                    .fold(row![].spacing(6), |row, (label, choice)| {
                        row.push(
                            button(text(if *choice == selected {
                                format!("✓ {label}")
                            } else {
                                (*label).to_owned()
                            }))
                            .on_press(Message::SetSettingPath(
                                path.clone(),
                                Value::String((*choice).to_owned()),
                            )),
                        )
                    });
                scrollable(choices)
                    .direction(scrollable::Direction::Horizontal(
                        scrollable::Scrollbar::new(),
                    ))
                    .into()
            }
            settings::Kind::Secret => text_input(spec.label, value.as_str().unwrap_or_default())
                .secure(true)
                .on_input(move |input| Message::SetSettingPath(path.clone(), Value::String(input)))
                .padding(8)
                .into(),
            settings::Kind::Background => {
                let selected = value.as_str().unwrap_or_default();
                let preview_path = resolve_background_setting(selected);
                let preview: Element<'a, Message> =
                    if let Some(handle) = self.images.get(&preview_path).cloned() {
                        iced::widget::image(handle)
                            .width(Length::Fixed(480.0))
                            .height(Length::Fixed(270.0))
                            .into()
                    } else {
                        text("Vista previa al cargar…").into()
                    };
                let choices = (1..=6).fold(row![].spacing(6), |row, index| {
                    let background = format!("bundled:{index}.png");
                    row.push(
                        button(text(if selected == background {
                            format!("✓ Fondo {index}")
                        } else {
                            format!("Fondo {index}")
                        }))
                        .on_press(Message::SetSettingPath(
                            path.clone(),
                            Value::String(background),
                        )),
                    )
                });
                column![
                    text_input(spec.label, selected)
                        .on_input(move |input| {
                            Message::SetSettingPath(path.clone(), Value::String(input))
                        })
                        .padding(8),
                    scrollable(choices).direction(scrollable::Direction::Horizontal(
                        scrollable::Scrollbar::new(),
                    )),
                    preview,
                ]
                .spacing(6)
                .into()
            }
            settings::Kind::Text => text_input(spec.label, value.as_str().unwrap_or_default())
                .on_input(move |input| Message::SetSettingPath(path.clone(), Value::String(input)))
                .padding(8)
                .into(),
        };
        if matches!(&spec.kind, settings::Kind::Bool) {
            input
        } else {
            column![text(spec.label).size(15), input]
                .spacing(5)
                .width(Length::Fill)
                .into()
        }
    }

    fn image_browser_view(&self) -> Element<'_, Message> {
        let Some(browser) = self.image_browser.as_ref() else {
            return text("").into();
        };
        let entries = browser.entries.iter().enumerate().fold(
            column![].spacing(4),
            |list, (index, (path, is_dir))| {
                let label = path.file_name().unwrap_or_default().to_string_lossy();
                list.push(
                    button(text(format!(
                        "{} {label}",
                        if *is_dir { "📁" } else { "🖼" }
                    )))
                    .width(Length::Fill)
                    .on_press(if *is_dir {
                        Message::ImageBrowserOpen(index)
                    } else {
                        Message::ImageBrowserSelect(index)
                    }),
                )
            },
        );
        let preview: Element<'_, Message> = browser
            .selected
            .and_then(|index| browser.entries.get(index))
            .and_then(|(path, _)| self.images.get(&path.to_string_lossy().into_owned()))
            .cloned()
            .map(|handle| {
                iced::widget::image(handle)
                    .width(Length::Fill)
                    .height(Length::Fixed(360.0))
                    .into()
            })
            .unwrap_or_else(|| text("Selecciona una imagen para previsualizarla.").into());
        let places = std::env::var_os("HOME")
            .map(PathBuf::from)
            .into_iter()
            .flat_map(|home| {
                [
                    ("Inicio", home.clone()),
                    ("Imágenes", home.join("Pictures")),
                    ("Descargas", home.join("Downloads")),
                ]
            })
            .filter(|(_, path)| path.is_dir())
            .fold(
                column![text("LUGARES").size(12)].spacing(6),
                |list, (name, path)| {
                    list.push(
                        button(name)
                            .width(Length::Fill)
                            .on_press(Message::ImageBrowserPlace(path)),
                    )
                },
            );
        let selected_info = browser
            .selected
            .and_then(|index| browser.entries.get(index))
            .and_then(|(path, is_dir)| (!is_dir).then_some(path))
            .and_then(|path| {
                fs::metadata(path)
                    .ok()
                    .map(|metadata| (path, metadata.len()))
            });
        let panel = container(
            column![
                row![
                    text("Elegir imagen del equipo")
                        .size(22)
                        .width(Length::Fill),
                    button("↑").on_press(Message::ImageBrowserParent),
                    button("Volver").on_press(Message::ImageBrowserCancel),
                ]
                .spacing(8),
                text(browser.directory.to_string_lossy().to_string()).size(13),
                text(format!(
                    "{} elementos · PNG, JPEG, WebP",
                    browser.entries.iter().filter(|(_, is_dir)| !is_dir).count()
                ))
                .size(12),
                browser
                    .error
                    .as_deref()
                    .map(text)
                    .unwrap_or_else(|| text("")),
                row![
                    places.width(Length::Fixed(145.0)).height(Length::Fill),
                    scrollable(entries)
                        .width(Length::Fixed(300.0))
                        .height(Length::Fill),
                    column![
                        container(preview)
                            .width(Length::Fill)
                            .height(Length::Fixed(340.0))
                            .center_x(Length::Fill)
                            .center_y(Length::Fill),
                        selected_info
                            .map(|(path, bytes)| column![
                                text(
                                    path.file_name()
                                        .unwrap_or_default()
                                        .to_string_lossy()
                                        .to_string()
                                )
                                .size(15),
                                text(format!("{:.1} KiB", bytes as f64 / 1024.0)).size(13),
                            ]
                            .spacing(4))
                            .unwrap_or_else(|| column![text("Selecciona una imagen")]),
                    ]
                    .spacing(10)
                    .width(Length::Fill),
                ]
                .spacing(16)
                .height(Length::Fill),
                row![
                    button("Cancelar").on_press(Message::ImageBrowserCancel),
                    button("Usar imagen")
                        .on_press_maybe(browser.selected.map(|_| Message::ImageBrowserUse)),
                ]
                .spacing(8),
            ]
            .spacing(12)
            .padding(20),
        )
        .width(Length::Fixed(
            (self.window_width * 0.82).clamp(680.0, 1100.0),
        ))
        .height(Length::Fixed((self.window_height * 0.86).max(480.0)))
        .style(|_| iced::widget::container::Style {
            background: Some(iced::Background::Color(iced::Color::from_rgb(
                0.12, 0.10, 0.10,
            ))),
            border: iced::Border {
                color: iced::Color::from_rgba(1.0, 1.0, 1.0, 0.10),
                width: 1.0,
                radius: 18.0.into(),
            },
            ..Default::default()
        });
        stack![
            container(text(""))
                .width(Length::Fill)
                .height(Length::Fill)
                .style(|_| iced::widget::container::Style {
                    background: Some(iced::Background::Color(iced::Color::from_rgba(
                        0.0, 0.0, 0.0, 0.55,
                    ))),
                    ..Default::default()
                }),
            container(panel)
                .width(Length::Fill)
                .height(Length::Fill)
                .center_x(Length::Fill)
                .center_y(Length::Fill),
        ]
        .width(Length::Fill)
        .height(Length::Fill)
        .into()
    }

    fn editor_view<'a>(&'a self, draft: &'a EditDraft) -> Element<'a, Message> {
        let fields = [
            (EditorField::Title, "Nombre"),
            (EditorField::Categories, "Categorías"),
            (EditorField::Description, "Descripción"),
            (EditorField::Synopsis, "Sinopsis"),
            (EditorField::ReleaseDate, "Fecha"),
            (EditorField::Developers, "Desarrolladores"),
            (EditorField::Publishers, "Editores"),
            (EditorField::Genres, "Géneros"),
            (EditorField::Platforms, "Plataformas"),
            (EditorField::LocalPath, "Ejecutable"),
            (EditorField::Arguments, "Argumentos"),
            (EditorField::WorkingDirectory, "Directorio"),
            (EditorField::Cover, "Carátula"),
            (EditorField::SquareCover, "Cuadrada"),
            (EditorField::Logo, "Logo"),
            (EditorField::Banner, "Banner"),
            (EditorField::BannerSecondary, "Fondo"),
        ];
        let keyboard_buttons = fields
            .into_iter()
            .fold(row![].spacing(6), |row, (field, label)| {
                row.push(
                    button(label).on_press(Message::OpenKeyboard(KeyboardTarget::Editor(field))),
                )
            });
        let is_local = self
            .games
            .iter()
            .find(|game| game.id() == draft.id)
            .is_some_and(|game| game.kind() == "local");
        let execution: Element<'a, Message> = if is_local {
            column![
                text("Ejecución").size(18),
                text_input("Ejecutable .sh o .AppImage", &draft.local_path)
                    .on_input(|value| Message::EditField(EditorField::LocalPath, value))
                    .padding(10),
                button("⌨ Ejecutable").on_press(Message::OpenKeyboard(KeyboardTarget::Editor(
                    EditorField::LocalPath
                ))),
                text_input("Argumentos", &draft.arguments)
                    .on_input(|value| Message::EditField(EditorField::Arguments, value))
                    .padding(10),
                button("⌨ Argumentos").on_press(Message::OpenKeyboard(KeyboardTarget::Editor(
                    EditorField::Arguments
                ))),
                text_input("Directorio de trabajo", &draft.cwd)
                    .on_input(|value| Message::EditField(EditorField::WorkingDirectory, value))
                    .padding(10),
                button("⌨ Directorio").on_press(Message::OpenKeyboard(KeyboardTarget::Editor(
                    EditorField::WorkingDirectory
                ))),
            ]
            .spacing(8)
            .into()
        } else {
            column![
                text("Ejecución").size(18),
                text("Steam, Faugus y Heroic mantienen la configuración de ejecución en sus aplicaciones.")
                    .size(13),
            ]
            .into()
        };
        let category_selector = self
            .categories
            .iter()
            .filter(|name| name.as_str() != "Todos")
            .fold(row![].spacing(8), |row, category| {
                let selected = draft
                    .categories
                    .split(',')
                    .any(|value| value.trim() == category);
                row.push(
                    button(text(if selected {
                        format!("✓ {category}")
                    } else {
                        category.clone()
                    }))
                    .on_press(Message::EditField(
                        EditorField::Categories,
                        toggle_comma_value(&draft.categories, category),
                    )),
                )
            });
        let banner_preview: Element<'a, Message> = self
            .images
            .get(&draft.banner)
            .cloned()
            .map(|handle| {
                iced::widget::image::Image::new(handle)
                    .width(Length::Fill)
                    .height(Length::Fixed(160.0))
                    .content_fit(iced::ContentFit::Cover)
                    .into()
            })
            .unwrap_or_else(|| text("").into());
        let cover_preview: Element<'a, Message> = self
            .images
            .get(&draft.cover)
            .cloned()
            .map(|handle| {
                iced::widget::image::Image::new(handle)
                    .width(Length::Fixed(86.0))
                    .height(Length::Fixed(128.0))
                    .content_fit(iced::ContentFit::Contain)
                    .into()
            })
            .unwrap_or_else(|| text("").into());
        let preview = stack![
            banner_preview,
            container(cover_preview)
                .width(Length::Fill)
                .height(Length::Fill)
                .padding(16)
                .align_x(Alignment::Start)
                .align_y(Alignment::End),
        ]
        .height(Length::Fixed(160.0));
        let editor_content = column![
            preview,
            scrollable(keyboard_buttons).direction(scrollable::Direction::Horizontal(
                scrollable::Scrollbar::new()
            )),
            text_input("Nombre del juego", &draft.title)
                .on_input(|value| Message::EditField(EditorField::Title, value))
                .padding(10),
            text_input("Categorías separadas por comas", &draft.categories)
                .on_input(|value| Message::EditField(EditorField::Categories, value))
                .padding(10),
            scrollable(category_selector).direction(scrollable::Direction::Horizontal(
                scrollable::Scrollbar::new(),
            )),
            text_input("Descripción", &draft.description)
                .on_input(|value| Message::EditField(EditorField::Description, value))
                .padding(10),
            text_input("Sinopsis", &draft.synopsis)
                .on_input(|value| Message::EditField(EditorField::Synopsis, value))
                .padding(10),
            text_input("Fecha de lanzamiento", &draft.release_date)
                .on_input(|value| Message::EditField(EditorField::ReleaseDate, value))
                .padding(10),
            text_input("Desarrolladores", &draft.developers)
                .on_input(|value| Message::EditField(EditorField::Developers, value))
                .padding(10),
            text_input("Editores", &draft.publishers)
                .on_input(|value| Message::EditField(EditorField::Publishers, value))
                .padding(10),
            text_input("Géneros", &draft.genres)
                .on_input(|value| Message::EditField(EditorField::Genres, value))
                .padding(10),
            text_input("Plataformas", &draft.platforms)
                .on_input(|value| Message::EditField(EditorField::Platforms, value))
                .padding(10),
            execution,
            button(if self.metadata_searching {
                "Buscando en Wikidata…"
            } else {
                "Buscar ficha en Wikidata"
            })
            .on_press_maybe((!self.metadata_searching).then_some(Message::SearchWikidata)),
            self.metadata_results
                .iter()
                .fold(column![].spacing(4), |column, option| {
                    column.push(
                        button(text(format!(
                            "{} · {} · {}",
                            option.id, option.name, option.description
                        )))
                        .on_press(Message::ChooseWikidata(option.clone())),
                    )
                }),
            row![
                text_input("Ruta de carátula", &draft.cover)
                    .on_input(|value| Message::EditField(EditorField::Cover, value))
                    .padding(10),
                button("Elegir…").on_press(Message::BrowseImage(EditorField::Cover)),
            ]
            .spacing(8),
            button(if self.artwork_searching && self.artwork_field == "cover" {
                "Buscando…"
            } else {
                "Buscar carátulas"
            })
            .on_press_maybe(
                (!self.artwork_searching)
                    .then_some(Message::SearchArtwork("cover".into(), "steamgriddb".into()))
            ),
            row![
                text_input("Ruta de carátula cuadrada", &draft.square_cover)
                    .on_input(|value| Message::EditField(EditorField::SquareCover, value))
                    .padding(10),
                button("Elegir…").on_press(Message::BrowseImage(EditorField::SquareCover)),
            ]
            .spacing(8),
            button("Buscar carátulas cuadradas").on_press(Message::SearchArtwork(
                "square_cover".into(),
                "steamgriddb".into()
            )),
            row![
                text_input("Ruta de logo", &draft.logo)
                    .on_input(|value| Message::EditField(EditorField::Logo, value))
                    .padding(10),
                button("Elegir…").on_press(Message::BrowseImage(EditorField::Logo)),
            ]
            .spacing(8),
            button("Buscar logos")
                .on_press(Message::SearchArtwork("logo".into(), "steamgriddb".into())),
            row![
                text_input("Ruta de banner", &draft.banner)
                    .on_input(|value| Message::EditField(EditorField::Banner, value))
                    .padding(10),
                button("Elegir…").on_press(Message::BrowseImage(EditorField::Banner)),
            ]
            .spacing(8),
            row![
                button("Buscar banners · SteamGridDB").on_press(Message::SearchArtwork(
                    "banner".into(),
                    "steamgriddb".into()
                )),
                button("Buscar fondos 16:9 · IGDB")
                    .on_press(Message::SearchArtwork("banner".into(), "igdb".into())),
            ]
            .spacing(8),
            row![
                text_input("Ruta de banner secundario", &draft.banner_secondary)
                    .on_input(|value| Message::EditField(EditorField::BannerSecondary, value))
                    .padding(10),
                button("Elegir…").on_press(Message::BrowseImage(EditorField::BannerSecondary)),
            ]
            .spacing(8),
            button("Buscar banners secundarios").on_press(Message::SearchArtwork(
                "banner_secondary".into(),
                "steamgriddb".into()
            )),
            button("Buscar fondos IGDB 16:9").on_press(Message::SearchArtwork(
                "banner_secondary".into(),
                "igdb".into()
            )),
            self.artwork_results
                .iter()
                .fold(column![].spacing(4), |column, option| {
                    column.push(
                        button(text(format!("{} · {}", option.id, option.name)))
                            .on_press(Message::ChooseArtwork(option.clone())),
                    )
                }),
            row![
                button("Guardar").on_press(Message::SaveEdit),
                button("Cancelar").on_press(Message::CancelEdit)
            ]
            .spacing(10),
            self.notice.as_deref().map(text).unwrap_or_else(|| text("")),
        ]
        .spacing(12)
        .padding(20);
        let panel = container(
            column![
                row![
                    text("Editar · ").size(18),
                    text(&draft.title).size(18).width(Length::Fill),
                    button("×").on_press(Message::CancelEdit),
                ]
                .align_y(Alignment::Center),
                scrollable(editor_content).height(Length::Fill),
            ]
            .spacing(12)
            .padding(20),
        )
        .width(Length::Fixed(
            (self.window_width * 0.55).clamp(640.0, 900.0),
        ))
        .height(Length::Fill)
        .style(|_| iced::widget::container::Style {
            background: Some(iced::Background::Color(iced::Color::from_rgb(
                0.12, 0.10, 0.10,
            ))),
            border: iced::Border {
                color: iced::Color::from_rgba(1.0, 1.0, 1.0, 0.10),
                width: 1.0,
                radius: 0.0.into(),
            },
            ..Default::default()
        });
        let scrim = container(text(""))
            .width(Length::Fill)
            .height(Length::Fill)
            .style(|_| iced::widget::container::Style {
                background: Some(iced::Background::Color(iced::Color::from_rgba(
                    0.0, 0.0, 0.0, 0.35,
                ))),
                ..Default::default()
            });
        stack![
            scrim,
            row![
                iced::widget::Space::new()
                    .width(Length::Fill)
                    .height(Length::Fill),
                panel,
            ]
            .width(Length::Fill)
            .height(Length::Fill),
        ]
        .width(Length::Fill)
        .height(Length::Fill)
        .into()
    }

    fn game_card<'a>(&self, game: &'a Game, focus: f32) -> Element<'a, Message> {
        let browser_width = self.window_width;
        let focus_amount = focus.clamp(0.0, 1.0);
        let (ring_enabled, ring_color, ring_width, ring_radius) =
            selection_ring(&self.settings, &self.layout);
        let ring_focus = if ring_enabled { focus_amount } else { 0.0 };
        let layout_opacity = self.layout_opacity();
        let selected = focus_amount >= 0.5;
        let setting = |key: &str, fallback: f32| {
            self.settings
                .get(key)
                .and_then(Value::as_f64)
                .map(|value| value as f32 / 100.0)
                .unwrap_or(fallback)
        };
        let mode_setting = |key: &str, fallback: f32| {
            self.settings
                .get(key)
                .and_then(|rows| rows.get(&self.layout))
                .and_then(Value::as_f64)
                .map(|value| value as f32)
                .unwrap_or(fallback)
        };
        let format = self
            .settings
            .get("cover_formats")
            .and_then(|rows| rows.get(&self.layout))
            .and_then(Value::as_str)
            .unwrap_or(if self.layout == "ps5" {
                "square"
            } else {
                "portrait"
            });
        let cover_radius = self
            .settings
            .get("cover_radii")
            .and_then(|modes| modes.get(&self.layout))
            .and_then(Value::as_u64)
            .unwrap_or(12)
            .min(40) as f32;
        let zoom = match self.layout.as_str() {
            "list" => setting("list_zoom", 1.0),
            "carousel" => setting("carousel_zoom", 1.0),
            "grid" => setting("grid_zoom", 1.0),
            _ => 1.0,
        }
        .clamp(0.5, 2.0);
        let list_vertical = matches!(
            self.settings.get("list_side").and_then(Value::as_str),
            Some("left" | "right") | None
        );
        let list_focus_zoom = setting("list_focus_zoom", 1.5).clamp(1.0, 2.5);
        let (base_width, base_height) = match self.layout.as_str() {
            "list" => {
                let count = self.games.len().clamp(1, 5);
                let span = count + usize::from(count % 2 == 0);
                let available = if list_vertical {
                    self.window_height * 0.60
                } else {
                    browser_width * 0.96
                };
                let requested = (if list_vertical { 160.0 } else { 300.0 }) * zoom;
                let normal = ((available - 32.0 * span as f32)
                    / (span as f32 - 1.0 + list_focus_zoom))
                    .clamp(1.0, requested);
                if list_vertical {
                    (
                        (browser_width * 0.72 / list_focus_zoom).min(360.0 * zoom),
                        normal,
                    )
                } else {
                    let strip_height = ((self.window_height - 200.0) * 0.35 - 32.0).max(80.0);
                    (
                        normal,
                        (strip_height * 0.72 / list_focus_zoom).min(normal * 1.5),
                    )
                }
            }
            "carousel" => {
                let strip_height = (self.window_height * 0.40).clamp(220.0, 420.0);
                (
                    280.0_f32
                        .min(strip_height * 0.70 / zoom)
                        .min(browser_width * 0.24 / zoom),
                    (strip_height - 12.0) / zoom,
                )
            }
            "ps5" => (120.0, 180.0),
            _ => (156.0, 234.0),
        };
        let (base_width, base_height) = if format == "square" && self.layout == "carousel" {
            (base_width, base_width)
        } else {
            (base_width, base_height)
        };
        let mut cover_width = base_width;
        let mut cover_height = base_height;
        if self.layout == "list" {
            let scale = 1.0 + (list_focus_zoom - 1.0) * focus_amount;
            cover_width *= scale;
            cover_height *= scale;
        } else if self.layout == "ps5" {
            let focus_size = mode_setting("ps5_focus_size", 250.0).clamp(104.0, 320.0);
            cover_width = 120.0 + (focus_size - 120.0) * focus_amount;
            let minimal = self
                .settings
                .get("minimal_views")
                .and_then(|modes| modes.get("ps5"))
                .and_then(Value::as_bool)
                == Some(true);
            cover_height = if minimal {
                280.0
            } else {
                (self.window_height * 0.25).min(260.0).max(80.0)
            };
        } else {
            cover_width *= zoom;
            cover_height *= zoom;
        }
        let artwork_path = if self.layout == "list" {
            game.field("logo")
                .filter(|path| !path.is_empty())
                .or_else(|| self.cover_path(game))
        } else {
            self.cover_path(game)
        };
        let artwork = artwork_path.and_then(|path| self.images.get(path)).cloned();
        let show_launcher_details = self
            .settings
            .get("show_launcher_details")
            .and_then(|rows| rows.get(&self.layout))
            .and_then(Value::as_bool)
            .unwrap_or(true);
        let details = column![
            text(if selected {
                format!("▶ {}", game.title())
            } else {
                game.title().to_owned()
            })
            .size(20),
            if show_launcher_details {
                text(game.kind_label()).size(13)
            } else {
                text("").size(13)
            }
        ]
        .spacing(6);
        let body: Element<'_, Message> = if self.layout == "list" {
            if let Some(handle) = artwork {
                column![
                    iced::widget::image::Image::new(handle)
                        .width(Length::Fixed(cover_width))
                        .height(Length::Fixed(cover_height))
                        .content_fit(iced::ContentFit::Contain)
                        .border_radius(cover_radius)
                        .opacity(layout_opacity * if selected { 1.0 } else { 0.65 }),
                    focus_plate(ring_focus, cover_width, ring_color)
                ]
                .spacing(5)
                .into()
            } else {
                container(text(game.title()).size(16))
                    .width(Length::Fixed(cover_width))
                    .height(Length::Fixed(cover_height))
                    .center_x(Length::Fill)
                    .center_y(Length::Fill)
                    .into()
            }
        } else if self.layout == "ps5" {
            if let Some(handle) = artwork {
                column![
                    iced::widget::image::Image::new(handle)
                        .width(Length::Fixed(cover_width))
                        .height(Length::Fixed(cover_height))
                        .content_fit(iced::ContentFit::Contain)
                        .border_radius(cover_radius)
                        .opacity(layout_opacity * if selected { 1.0 } else { 0.65 }),
                    focus_plate(ring_focus, cover_width, ring_color),
                ]
                .spacing(5)
                .into()
            } else {
                container(text(game.title()).size(16))
                    .width(Length::Fixed(cover_width))
                    .height(Length::Fixed(cover_height))
                    .center_x(Length::Fill)
                    .center_y(Length::Fill)
                    .into()
            }
        } else if self.layout == "carousel" {
            if let Some(handle) = artwork {
                let scale = 0.5 + 0.5 * focus_amount;
                container(
                    column![
                        iced::widget::image::Image::new(handle)
                            .width(Length::Fixed(cover_width * scale))
                            .height(Length::Fixed(cover_height * scale))
                            .content_fit(iced::ContentFit::Contain)
                            .border_radius(cover_radius)
                            .opacity(layout_opacity * if selected { 1.0 } else { 0.65 }),
                        focus_plate(ring_focus, cover_width, ring_color),
                    ]
                    .spacing(5),
                )
                .width(Length::Fixed(cover_width))
                .height(Length::Fixed(cover_height + 9.0))
                .center_x(Length::Fill)
                .center_y(Length::Fill)
                .into()
            } else {
                container(text(game.title()).size(16))
                    .width(Length::Fixed(cover_width))
                    .height(Length::Fixed(cover_height))
                    .center_x(Length::Fill)
                    .center_y(Length::Fill)
                    .into()
            }
        } else if let Some(handle) = artwork {
            column![
                iced::widget::image::Image::new(handle)
                    .width(Length::Fixed(cover_width))
                    .height(Length::Fixed(cover_height))
                    .content_fit(iced::ContentFit::Cover)
                    .border_radius(cover_radius)
                    .opacity(layout_opacity),
                focus_plate(ring_focus, cover_width, ring_color),
                details
            ]
            .spacing(5)
            .into()
        } else {
            details.into()
        };
        let width = match self.layout.as_str() {
            "list" => Length::Fixed(cover_width + 8.0),
            "carousel" => Length::Fixed(cover_width + 28.0),
            "ps5" => Length::Fixed(cover_width + 40.0),
            _ => Length::Fixed(cover_width + 32.0),
        };
        button(body)
            .width(width)
            .padding(if self.layout == "list" { 4 } else { 14 })
            .style(move |_, _| iced::widget::button::Style {
                background: (focus_amount > 0.0).then_some(iced::Background::Color(
                    iced::Color::from_rgba(0.035, 0.055, 0.085, 0.52 * focus_amount),
                )),
                text_color: iced::Color::WHITE,
                border: iced::Border {
                    color: ring_color.scale_alpha(0.92 * ring_focus),
                    width: ring_width * ring_focus,
                    radius: ring_radius.into(),
                },
                ..Default::default()
            })
            .on_press(Message::Select(game.id().to_owned()))
            .into()
    }
}

fn cursor_target(
    cursor: usize,
    total: usize,
    layout: &str,
    action: &str,
    grid_columns: usize,
) -> Option<usize> {
    if total == 0 {
        return None;
    }
    let step = match (layout, action) {
        ("grid", "up") => -(grid_columns as isize),
        ("grid", "down") => grid_columns as isize,
        ("ps5", "up") => -2,
        ("ps5", "down") => 2,
        (_, "left" | "up") => -1,
        _ => 1,
    };
    let target = cursor as isize + step;
    Some(if matches!(layout, "list" | "carousel") {
        target.rem_euclid(total as isize) as usize
    } else {
        target.clamp(0, total as isize - 1) as usize
    })
}

fn grid_columns_for_width(width: f32, zoom: f32, minimal: bool, page_size: usize) -> usize {
    let cell_width = (180.0 * zoom.clamp(0.5, 2.0)).clamp(140.0, 260.0);
    let content_width = (width - 48.0).max(0.0);
    let grid_width = if minimal {
        content_width
    } else {
        ((content_width - 20.0).max(0.0) * 0.68).floor()
    };
    (((grid_width - 16.0).max(cell_width) / cell_width).floor() as usize)
        .max(1)
        .min(page_size)
}

fn list_detail_cover_height(window_height: f32, cover_width: f32, vertical_list: bool) -> f32 {
    let body_height = (window_height - 200.0).max(200.0);
    if vertical_list {
        (body_height * 0.52 - 64.0).max(1.0).min(cover_width * 1.5)
    } else {
        (body_height * 0.65 - 92.0)
            .max(1.0)
            .min((cover_width * 1.5).min(500.0))
    }
}

fn list_arc_position(
    position: f32,
    count: usize,
    main_extent: f32,
    cross_extent: f32,
    requested_extent: f32,
    focus_zoom: f32,
    reverse: bool,
) -> (f32, f32) {
    if position == 0.0 || count < 2 {
        return (0.0, 0.0);
    }
    let visible = count.min(5);
    let span = visible + usize::from(visible % 2 == 0);
    let normal = ((main_extent - 32.0 * span as f32) / (span as f32 - 1.0 + focus_zoom))
        .clamp(1.0, requested_extent);
    let bend = ((cross_extent * 0.14) - 8.0).max(0.0).min(normal * 0.6);
    let distance = normal * (focus_zoom + 1.0) / 2.0 + 32.0;
    let half_span = (normal * (span as f32 - 1.0 + focus_zoom) + 32.0 * span as f32) / 2.0;
    let direction = if reverse { 1.0 } else { -1.0 };
    (
        direction * bend * (position * distance / half_span).powi(2),
        position * distance,
    )
}

fn ps5_card_left(offset: f32, selected_extent: f32, normal_stride: f32) -> f32 {
    if offset < -1.0 {
        -selected_extent + (offset + 1.0) * normal_stride
    } else if offset <= 1.0 {
        offset * selected_extent
    } else {
        selected_extent + (offset - 1.0) * normal_stride
    }
}

fn background_composite_key(primary: &str, secondary: &str, split: &str) -> String {
    format!("composite:{split}:{primary}:{secondary}")
}

fn resolve_background_setting(value: &str) -> String {
    if let Some(file) = value.strip_prefix("bundled:") {
        let source = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../assets/backgrounds");
        let executable = std::env::current_exe().ok();
        return std::env::var_os("ESTANTE_ASSET_DIR")
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
            .into_owned();
    }
    value.strip_prefix("~/").map_or_else(
        || value.to_owned(),
        |tail| format!("{}/{tail}", std::env::var("HOME").unwrap_or_default()),
    )
}

#[cfg(test)]
mod background_setting_tests {
    use super::{active_background_decode_size, resolve_background_setting};
    use std::path::Path;

    #[test]
    fn bundled_backgrounds_resolve_from_the_build_assets() {
        let path = resolve_background_setting("bundled:1.png");
        assert!(path.ends_with("assets/backgrounds/1.png"));
        assert!(Path::new(&path).is_file());
    }

    #[test]
    fn active_background_resolution_tracks_large_windows_with_a_memory_cap() {
        assert_eq!(active_background_decode_size(1180.0, 800.0), (2560, 1440));
        assert_eq!(active_background_decode_size(3440.0, 1440.0), (3440, 1440));
        assert_eq!(active_background_decode_size(5120.0, 2880.0), (3840, 2160));
    }
}

#[cfg(test)]
mod grid_navigation_tests {
    use super::{
        cursor_target, grid_columns_for_width, wrapped_cover_offset, wrapped_cursor_phase,
    };

    #[test]
    fn grid_navigation_uses_the_rendered_gallery_columns() {
        let columns = grid_columns_for_width(1180.0, 1.0, false, 10);
        assert_eq!(columns, 4);
        assert_eq!(cursor_target(0, 10, "grid", "down", columns), Some(4));
        assert_eq!(cursor_target(4, 10, "grid", "down", columns), Some(8));
        assert_eq!(cursor_target(8, 10, "grid", "down", columns), Some(9));
        assert_eq!(cursor_target(9, 10, "grid", "up", columns), Some(5));
        assert_eq!(cursor_target(3, 10, "grid", "right", columns), Some(4));
        assert_eq!(cursor_target(9, 20, "grid", "down", columns), Some(13));
        assert_eq!(cursor_target(13, 20, "grid", "up", columns), Some(9));
    }

    #[test]
    fn grid_columns_follow_wide_compact_and_minimal_layouts() {
        assert_eq!(grid_columns_for_width(1920.0, 1.0, false, 10), 6);
        assert_eq!(grid_columns_for_width(1180.0, 1.0, true, 10), 6);
        assert_eq!(grid_columns_for_width(1180.0, 2.0, false, 10), 2);
        assert_eq!(grid_columns_for_width(1180.0, 1.0, false, 1), 1);
    }

    #[test]
    fn list_and_carousel_navigation_wrap_at_both_ends() {
        for layout in ["list", "carousel"] {
            assert_eq!(cursor_target(0, 4, layout, "left", 1), Some(3));
            assert_eq!(cursor_target(0, 4, layout, "up", 1), Some(3));
            assert_eq!(cursor_target(3, 4, layout, "right", 1), Some(0));
            assert_eq!(cursor_target(3, 4, layout, "down", 1), Some(0));
            assert_eq!(cursor_target(0, 1, layout, "left", 1), Some(0));
        }
        assert_eq!(cursor_target(0, 4, "grid", "left", 1), Some(0));
        assert_eq!(cursor_target(3, 4, "ps5", "right", 1), Some(3));
    }

    #[test]
    fn carousel_phase_takes_the_short_wrapped_route() {
        assert_eq!(wrapped_cursor_phase(4, 0, 0.5, 5), 4.5);
        assert_eq!(wrapped_cursor_phase(0, 4, 0.5, 5), 4.5);
        assert_eq!(wrapped_cursor_phase(0, 4, 1.0, 5), 4.0);
        assert_eq!(wrapped_cover_offset(0, 4.5, 5), 0.5);
        assert_eq!(wrapped_cover_offset(4, 4.5, 5), -0.5);
    }
}

#[cfg(test)]
mod focus_ring_tests {
    use super::{parse_focus_color, selection_ring};
    use serde_json::json;

    #[test]
    fn focus_ring_reads_per_view_settings_and_rgb_colors() {
        let settings = json!({
            "selection_rings": {
                "ps5": {
                    "focus_ring_enabled": false,
                    "focus_ring_color": "rgb(255, 128, 32)",
                    "focus_ring_width": 7,
                    "focus_ring_radius": 22
                }
            }
        });
        let (enabled, color, width, radius) = selection_ring(&settings, "ps5");
        assert!(!enabled);
        assert_eq!(
            (color.r, color.g, color.b),
            (1.0, 128.0 / 255.0, 32.0 / 255.0)
        );
        assert_eq!((width, radius), (7.0, 22.0));
    }

    #[test]
    fn focus_colors_support_alpha_hex_and_reject_invalid_values() {
        let color = parse_focus_color("#33669980").unwrap();
        assert_eq!(
            (color.r, color.g, color.b),
            (
                0x33 as f32 / 255.0,
                0x66 as f32 / 255.0,
                0x99 as f32 / 255.0
            )
        );
        assert!((color.a - 128.0 / 255.0).abs() < 0.001);
        assert!(parse_focus_color("not-a-color").is_none());
    }
}

#[cfg(test)]
mod ps5_motion_tests {
    use super::ps5_card_left;

    #[test]
    fn selected_slot_slides_by_focus_extent_then_regular_spacing() {
        assert_eq!(ps5_card_left(0.0, 262.0, 132.0), 0.0);
        assert_eq!(ps5_card_left(0.5, 262.0, 132.0), 131.0);
        assert_eq!(ps5_card_left(1.0, 262.0, 132.0), 262.0);
        assert_eq!(ps5_card_left(2.0, 262.0, 132.0), 394.0);
        assert_eq!(ps5_card_left(-1.0, 262.0, 132.0), -262.0);
    }
}

#[cfg(test)]
mod list_layout_tests {
    use super::{list_arc_position, list_detail_cover_height};

    #[test]
    fn detail_cover_fits_both_list_compositions() {
        assert!((list_detail_cover_height(760.0, 260.0, true) - 227.2).abs() < 0.1);
        assert!((list_detail_cover_height(760.0, 260.0, false) - 272.0).abs() < 0.1);
        assert!(list_detail_cover_height(400.0, 260.0, true) < 260.0 * 1.5);
        assert!(list_detail_cover_height(1440.0, 260.0, false) <= 500.0);
    }

    #[test]
    fn list_arc_is_centered_symmetric_and_reverses_by_side() {
        let left = list_arc_position(-1.0, 5, 900.0, 420.0, 160.0, 1.5, false);
        assert_eq!(
            list_arc_position(0.0, 5, 900.0, 420.0, 160.0, 1.5, false),
            (0.0, 0.0)
        );
        assert!(left.0 < 0.0 && left.1 < 0.0);
        assert_eq!(
            list_arc_position(1.0, 5, 900.0, 420.0, 160.0, 1.5, false),
            (left.0, -left.1)
        );
        assert_eq!(
            list_arc_position(-1.0, 5, 900.0, 420.0, 160.0, 1.5, true),
            (-left.0, left.1)
        );
    }
}

fn nearby_indices(total: usize, selected: usize, limit: usize) -> Vec<usize> {
    let count = total.min(limit);
    if count == 0 {
        return Vec::new();
    }
    let selected = selected % total;
    let before = count / 2;
    (0..count)
        .map(|offset| (selected + total + offset - before) % total)
        .collect()
}

fn wrapped_cursor_phase(from: usize, to: usize, progress: f32, total: usize) -> f32 {
    if total == 0 {
        return 0.0;
    }
    let from = from % total;
    let to = to % total;
    let forward = (to + total - from) % total;
    let delta = if forward > total / 2 {
        forward as f32 - total as f32
    } else {
        forward as f32
    };
    (from as f32 + delta * progress.clamp(0.0, 1.0)).rem_euclid(total as f32)
}

fn wrapped_cover_offset(index: usize, phase: f32, total: usize) -> f32 {
    if total == 0 {
        return 0.0;
    }
    (index as f32 - phase + total as f32 / 2.0).rem_euclid(total as f32) - total as f32 / 2.0
}

fn forward_indices(total: usize, selected: usize, limit: usize) -> Vec<usize> {
    (selected.min(total)..total.min(selected.saturating_add(limit))).collect()
}

fn toggle_comma_value(values: &str, value: &str) -> String {
    let mut values = values
        .split(',')
        .map(str::trim)
        .filter(|item| !item.is_empty())
        .map(str::to_owned)
        .collect::<Vec<_>>();
    if let Some(index) = values.iter().position(|item| item == value) {
        values.remove(index);
    } else {
        values.push(value.to_owned());
    }
    values.join(", ")
}

fn encode_image(image: &image::RgbaImage) -> Option<Vec<u8>> {
    let mut bytes = Vec::new();
    image::codecs::webp::WebPEncoder::new_lossless(&mut bytes)
        .encode(
            image.as_raw(),
            image.width(),
            image.height(),
            image::ExtendedColorType::Rgba8,
        )
        .ok()?;
    Some(bytes)
}

fn compose_background_pair(
    primary: &str,
    secondary: &str,
    split: &str,
    size: (u32, u32),
) -> Option<image::RgbaImage> {
    use image::imageops::FilterType;
    let (width, height) = size;
    let (region_width, region_height) = match split {
        "horizontal" => (width, height / 2),
        "vertical" => (width / 2, height),
        _ => (width, height),
    };
    let primary = image::load_from_memory(&fs::read(primary).ok()?)
        .ok()?
        .resize_to_fill(region_width, region_height, FilterType::Lanczos3)
        .into_rgba8();
    let secondary = image::load_from_memory(&fs::read(secondary).ok()?)
        .ok()?
        .resize_to_fill(region_width, region_height, FilterType::Lanczos3)
        .into_rgba8();
    let band = (height.min(width) as f32 * 0.12).min(128.0).max(1.0);
    let normalizer = ((1.0 / width as f32).powi(2) + (1.0 / height as f32).powi(2)).sqrt();
    Some(image::RgbaImage::from_fn(width, height, |x, y| {
        let distance = match split {
            "horizontal" => y as f32 - height as f32 / 2.0,
            "vertical" => x as f32 - width as f32 / 2.0,
            "diagonal" => (x as f32 / width as f32 + y as f32 / height as f32 - 1.0) / normalizer,
            _ => return *primary.get_pixel(x, y),
        };
        let mix = (0.5 - distance / band).clamp(0.0, 1.0);
        let (primary_x, primary_y, secondary_x, secondary_y) = match split {
            "horizontal" => (
                x,
                y.min(height / 2 - 1),
                x,
                y.saturating_sub(height / 2).min(height / 2 - 1),
            ),
            "vertical" => (
                x.min(width / 2 - 1),
                y,
                x.saturating_sub(width / 2).min(width / 2 - 1),
                y,
            ),
            _ => (x, y, x, y),
        };
        let a = primary.get_pixel(primary_x, primary_y).0;
        let b = secondary.get_pixel(secondary_x, secondary_y).0;
        image::Rgba([
            (a[0] as f32 * mix + b[0] as f32 * (1.0 - mix)).round() as u8,
            (a[1] as f32 * mix + b[1] as f32 * (1.0 - mix)).round() as u8,
            (a[2] as f32 * mix + b[2] as f32 * (1.0 - mix)).round() as u8,
            255,
        ])
    }))
}

fn format_duration(seconds: u64) -> String {
    let hours = seconds / 3600;
    let minutes = seconds % 3600 / 60;
    if hours > 0 {
        format!("{hours} h {minutes} min")
    } else {
        format!("{minutes} min")
    }
}

fn blur_cache_key(path: &str, radius: u64) -> String {
    format!("{path}#blur={radius}")
}

fn image_generation_is_current(generation: u64, current: &AtomicU64) -> bool {
    current.load(Ordering::Relaxed) == generation
}

fn ease_progress(elapsed: Duration, duration: Duration) -> f32 {
    let progress = (elapsed.as_secs_f32() / duration.as_secs_f32()).clamp(0.0, 1.0);
    progress * progress * (3.0 - 2.0 * progress)
}

fn keyboard_key_button(
    label: String,
    selected: bool,
    suggested: bool,
    width: u16,
    message: Message,
) -> Element<'static, Message> {
    button(text(label).size(19))
        .width(Length::FillPortion(width))
        .height(Length::Fixed(48.0))
        .padding([8, 4])
        .style(move |_, status| {
            let highlighted = selected || suggested;
            let hovered = status == iced::widget::button::Status::Hovered
                || status == iced::widget::button::Status::Pressed;
            iced::widget::button::Style {
                background: Some(iced::Background::Color(if highlighted {
                    iced::Color::from_rgb(0.82, 0.44, 0.39)
                } else if hovered {
                    iced::Color::from_rgb(0.40, 0.36, 0.36)
                } else {
                    iced::Color::from_rgb(0.30, 0.28, 0.29)
                })),
                text_color: iced::Color::WHITE,
                border: iced::Border {
                    color: if selected {
                        iced::Color::from_rgb(1.0, 0.84, 0.80)
                    } else {
                        iced::Color::from_rgba(1.0, 1.0, 1.0, 0.10)
                    },
                    width: if selected { 2.0 } else { 1.0 },
                    radius: 10.0.into(),
                },
                ..Default::default()
            }
        })
        .on_press(message)
        .into()
}

fn insert_at_cursor(value: &mut String, cursor: &mut usize, inserted: &str) {
    value.insert_str(*cursor, inserted);
    *cursor += inserted.len();
}

fn erase_before_cursor(value: &mut String, cursor: &mut usize) {
    if let Some((start, _)) = value[..*cursor].char_indices().next_back() {
        value.drain(start..*cursor);
        *cursor = start;
    }
}

fn move_cursor(value: &str, cursor: &mut usize, direction: isize) {
    if direction < 0 {
        *cursor = value[..*cursor]
            .char_indices()
            .next_back()
            .map_or(0, |(index, _)| index);
    } else {
        *cursor = value[*cursor..]
            .char_indices()
            .nth(1)
            .map_or(value.len(), |(offset, _)| *cursor + offset);
    }
}

fn normalize_search(value: &str) -> String {
    value
        .chars()
        .filter(|character| !('\u{0300}'..='\u{036f}').contains(character))
        .flat_map(char::to_lowercase)
        .map(|character| match character {
            'á' | 'à' | 'â' | 'ä' | 'ã' | 'å' => 'a',
            'é' | 'è' | 'ê' | 'ë' => 'e',
            'í' | 'ì' | 'î' | 'ï' => 'i',
            'ó' | 'ò' | 'ô' | 'ö' | 'õ' => 'o',
            'ú' | 'ù' | 'û' | 'ü' => 'u',
            'ñ' => 'n',
            'ç' => 'c',
            character => character,
        })
        .collect()
}

fn controller_badge(label: &'static str, color: iced::Color) -> Element<'static, Message> {
    container(text(label).size(11))
        .width(Length::Fixed(26.0))
        .height(Length::Fixed(26.0))
        .center_x(Length::Fixed(26.0))
        .center_y(Length::Fixed(26.0))
        .style(move |_| iced::widget::container::Style {
            background: Some(iced::Background::Color(color)),
            border: iced::Border {
                radius: 13.0.into(),
                ..Default::default()
            },
            text_color: Some(iced::Color::WHITE),
            ..Default::default()
        })
        .into()
}

fn controller_prompt(
    badge: &'static str,
    label: &'static str,
    action: &'static str,
    color: iced::Color,
) -> Element<'static, Message> {
    let message = if action == "exit" {
        Message::Exit
    } else {
        Message::ControllerAction(action)
    };
    button(
        row![controller_badge(badge, color), text(label).size(14)]
            .spacing(8)
            .align_y(Alignment::Center),
    )
    .padding([4, 6])
    .style(|_, status| iced::widget::button::Style {
        background: (status == iced::widget::button::Status::Hovered).then_some(
            iced::Background::Color(iced::Color::from_rgba(1.0, 1.0, 1.0, 0.08)),
        ),
        text_color: iced::Color::WHITE,
        border: iced::Border {
            radius: 8.0.into(),
            ..Default::default()
        },
        ..Default::default()
    })
    .on_press(message)
    .into()
}

fn controller_category_prompt(labels: &[String], current: usize) -> Element<'static, Message> {
    let bumper = iced::Color::from_rgb(0.20, 0.27, 0.36);
    let previous = (current + labels.len() - 1) % labels.len();
    let next = (current + 1) % labels.len();
    row![
        button(controller_badge("LB", bumper))
            .on_press(Message::ControllerAction("category_previous")),
        category_chip(&labels[previous], false),
        category_chip(&labels[current], true),
        category_chip(&labels[next], false),
        button(controller_badge("RB", bumper)).on_press(Message::ControllerAction("category_next")),
    ]
    .spacing(3)
    .align_y(Alignment::Center)
    .into()
}

fn category_chip(label: &str, current: bool) -> Element<'static, Message> {
    let limit = if current { 12 } else { 8 };
    let mut chars = label.chars();
    let mut label = chars.by_ref().take(limit).collect::<String>();
    if chars.next().is_some() {
        label.push('…');
    }
    let color = if current {
        iced::Color::from_rgba(0.95, 0.97, 1.0, 1.0)
    } else {
        iced::Color::from_rgba(0.78, 0.83, 0.91, 0.64)
    };
    container(text(label).size(if current { 12 } else { 10 }).color(color))
        .width(Length::Fixed(if current { 92.0 } else { 66.0 }))
        .height(Length::Fixed(30.0))
        .center_x(Length::Fixed(if current { 92.0 } else { 66.0 }))
        .center_y(Length::Fixed(30.0))
        .style(move |_| iced::widget::container::Style {
            background: Some(iced::Background::Color(if current {
                iced::Color::from_rgba(0.36, 0.56, 0.76, 0.22)
            } else {
                iced::Color::from_rgba(1.0, 1.0, 1.0, 0.045)
            })),
            border: iced::Border {
                color: iced::Color::from_rgba(0.78, 0.86, 0.96, if current { 0.24 } else { 0.08 }),
                width: 1.0,
                radius: 15.0.into(),
            },
            ..Default::default()
        })
        .into()
}

fn title_initial(title: &str) -> char {
    normalize_search(title.trim())
        .chars()
        .next()
        .filter(char::is_ascii_alphabetic)
        .map(|character| character.to_ascii_uppercase())
        .unwrap_or('#')
}

fn alphabet_target(titles: &[&str], current: usize, direction: isize) -> Option<usize> {
    if titles.is_empty() {
        return None;
    }
    let current = current.min(titles.len() - 1);
    let initial = title_initial(titles[current]);
    let mut letters = titles
        .iter()
        .map(|title| title_initial(title))
        .collect::<Vec<_>>();
    letters.sort_unstable();
    letters.dedup();
    if letters.len() == 1 {
        return Some(current);
    }
    let current_letter = letters.iter().position(|letter| *letter == initial)?;
    let step = direction.signum();
    let target = (current_letter as isize + step).rem_euclid(letters.len() as isize) as usize;
    titles
        .iter()
        .position(|title| title_initial(title) == letters[target])
}

#[cfg(test)]
mod alphabet_navigation_tests {
    use super::{
        alphabet_target, forward_indices, nearby_indices, title_initial, toggle_comma_value,
    };

    #[test]
    fn letter_steps_follow_populated_initials_and_wrap() {
        let titles = ["Éclair", "Halo", "Zelda"];
        assert_eq!(title_initial(titles[0]), 'E');
        assert_eq!(title_initial("42: The Game"), '#');
        assert_eq!(alphabet_target(&titles, 0, 1), Some(1));
        assert_eq!(alphabet_target(&titles, 0, -1), Some(2));
        assert_eq!(alphabet_target(&["Alpha", "Another"], 1, 1), Some(1));
        assert_eq!(alphabet_target(&[], 0, 1), None);
    }

    #[test]
    fn list_window_centers_selection_and_wraps_without_duplicates() {
        assert_eq!(nearby_indices(8, 4, 5), vec![2, 3, 4, 5, 6]);
        assert_eq!(nearby_indices(4, 0, 5), vec![2, 3, 0, 1]);
        assert_eq!(nearby_indices(0, 0, 5), Vec::<usize>::new());
    }

    #[test]
    fn ps5_strip_starts_at_selection_and_stops_at_library_end() {
        assert_eq!(forward_indices(8, 5, 4), vec![5, 6, 7]);
        assert_eq!(forward_indices(8, 0, 3), vec![0, 1, 2]);
        assert_eq!(forward_indices(0, 0, 10), Vec::<usize>::new());
    }

    #[test]
    fn category_toggle_preserves_other_values() {
        assert_eq!(toggle_comma_value("RPG, Acción", "Acción"), "RPG");
        assert_eq!(toggle_comma_value("RPG", "Aventura"), "RPG, Aventura");
    }
}

#[cfg(test)]
mod image_browser_tests {
    use super::is_supported_image_path;
    use std::path::Path;

    #[test]
    fn image_browser_accepts_qt_formats_case_insensitively() {
        for extension in ["png", "JPG", "jpeg", "WebP"] {
            assert!(is_supported_image_path(Path::new(&format!(
                "cover.{extension}"
            ))));
        }
        assert!(!is_supported_image_path(Path::new("cover.gif")));
        assert!(!is_supported_image_path(Path::new("notes.txt")));
    }
}

fn summary_panel<'a>(
    details: Element<'a, Message>,
    height: Length,
    width: Length,
) -> Element<'a, Message> {
    container(scrollable(details).height(Length::Fill))
        .width(width)
        .height(height)
        .padding(22)
        .into()
}

#[cfg(test)]
mod image_generation_tests {
    use super::{
        ease_progress, erase_before_cursor, image_generation_is_current, insert_at_cursor,
        move_cursor, normalize_search,
    };
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::time::Duration;

    #[test]
    fn stale_image_generation_is_cancelled() {
        let current = AtomicU64::new(4);
        assert!(image_generation_is_current(4, &current));
        current.store(5, Ordering::Relaxed);
        assert!(!image_generation_is_current(4, &current));
        assert!(image_generation_is_current(5, &current));
    }

    #[test]
    fn animation_easing_clamps_and_reaches_endpoints() {
        let duration = Duration::from_millis(180);
        assert_eq!(ease_progress(Duration::ZERO, duration), 0.0);
        assert_eq!(ease_progress(duration, duration), 1.0);
        assert_eq!(ease_progress(duration * 2, duration), 1.0);
        assert!((ease_progress(duration / 2, duration) - 0.5).abs() < 0.001);
    }

    #[test]
    fn search_normalizes_case_and_common_accents() {
        assert_eq!(normalize_search("Pokémon: Édition"), "pokemon: edition");
    }

    #[test]
    fn keyboard_cursor_edits_utf8_at_the_selected_position() {
        let mut value = "aé".to_owned();
        let mut cursor = value.len();
        move_cursor(&value, &mut cursor, -1);
        insert_at_cursor(&mut value, &mut cursor, "ñ");
        assert_eq!(value, "añé");
        erase_before_cursor(&mut value, &mut cursor);
        assert_eq!(value, "aé");
        assert_eq!(cursor, 1);
        move_cursor(&value, &mut cursor, 1);
        assert_eq!(cursor, value.len());
    }
}


fn editor_field(editor: &EditDraft, field: EditorField) -> String {
    match field {
        EditorField::Title => editor.title.clone(),
        EditorField::Categories => editor.categories.clone(),
        EditorField::Description => editor.description.clone(),
        EditorField::Synopsis => editor.synopsis.clone(),
        EditorField::ReleaseDate => editor.release_date.clone(),
        EditorField::Developers => editor.developers.clone(),
        EditorField::Publishers => editor.publishers.clone(),
        EditorField::Genres => editor.genres.clone(),
        EditorField::Platforms => editor.platforms.clone(),
        EditorField::LocalPath => editor.local_path.clone(),
        EditorField::Arguments => editor.arguments.clone(),
        EditorField::WorkingDirectory => editor.cwd.clone(),
        EditorField::Cover => editor.cover.clone(),
        EditorField::SquareCover => editor.square_cover.clone(),
        EditorField::Logo => editor.logo.clone(),
        EditorField::Banner => editor.banner.clone(),
        EditorField::BannerSecondary => editor.banner_secondary.clone(),
    }
}

fn editor_image_field(editor: &EditDraft, field: EditorField) -> Option<&str> {
    match field {
        EditorField::Cover => Some(&editor.cover),
        EditorField::SquareCover => Some(&editor.square_cover),
        EditorField::Logo => Some(&editor.logo),
        EditorField::Banner => Some(&editor.banner),
        EditorField::BannerSecondary => Some(&editor.banner_secondary),
        _ => None,
    }
}

fn is_supported_image_path(path: &std::path::Path) -> bool {
    path.extension()
        .and_then(|ext| ext.to_str())
        .is_some_and(|ext| {
            matches!(
                ext.to_ascii_lowercase().as_str(),
                "png" | "jpg" | "jpeg" | "webp"
            )
        })
}

fn set_editor_field(editor: &mut EditDraft, field: EditorField, value: String) {
    match field {
        EditorField::Title => editor.title = value,
        EditorField::Categories => editor.categories = value,
        EditorField::Description => editor.description = value,
        EditorField::Synopsis => editor.synopsis = value,
        EditorField::ReleaseDate => editor.release_date = value,
        EditorField::Developers => editor.developers = value,
        EditorField::Publishers => editor.publishers = value,
        EditorField::Genres => editor.genres = value,
        EditorField::Platforms => editor.platforms = value,
        EditorField::LocalPath => editor.local_path = value,
        EditorField::Arguments => editor.arguments = value,
        EditorField::WorkingDirectory => editor.cwd = value,
        EditorField::Cover => editor.cover = value,
        EditorField::SquareCover => editor.square_cover = value,
        EditorField::Logo => editor.logo = value,
        EditorField::Banner => editor.banner = value,
        EditorField::BannerSecondary => editor.banner_secondary = value,
    }
}

fn iso_now() -> String {
    let seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs() as i64;
    let days = seconds.div_euclid(86_400);
    let day_seconds = seconds.rem_euclid(86_400);
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 }.div_euclid(146_097);
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
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}+00:00",
        day_seconds / 3_600,
        day_seconds % 3_600 / 60,
        day_seconds % 60
    )
}

fn split_values(value: &str) -> Vec<Value> {
    let mut seen = std::collections::HashSet::new();
    value
        .split(',')
        .map(str::trim)
        .filter(|item| !item.is_empty() && seen.insert((*item).to_owned()))
        .map(|item| Value::String(item.to_owned()))
        .collect()
}
