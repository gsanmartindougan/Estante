use super::*;
use slint::platform::{
    PlatformError, WindowAdapter,
    software_renderer::{MinimalSoftwareWindow, RepaintBufferType},
};
use std::path::{Path, PathBuf};

static TEST_TIME: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
static TEST_FIXTURE_SEQUENCE: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

type UiEvent = Box<dyn FnOnce() + Send>;
struct SoftwarePlatform(Rc<MinimalSoftwareWindow>, mpsc::Sender<UiEvent>);
struct EventProxy(mpsc::Sender<UiEvent>);

impl slint::platform::EventLoopProxy for EventProxy {
    fn invoke_from_event_loop(&self, event: UiEvent) -> Result<(), slint::EventLoopError> {
        self.0
            .send(event)
            .map_err(|_| slint::EventLoopError::EventLoopTerminated)
    }
    fn quit_event_loop(&self) -> Result<(), slint::EventLoopError> {
        Ok(())
    }
}

impl slint::platform::Platform for SoftwarePlatform {
    fn new_event_loop_proxy(&self) -> Option<Box<dyn slint::platform::EventLoopProxy>> {
        Some(Box::new(EventProxy(self.1.clone())))
    }
    fn duration_since_start(&self) -> Duration {
        Duration::from_millis(TEST_TIME.load(std::sync::atomic::Ordering::Relaxed))
    }
    fn create_window_adapter(&self) -> Result<Rc<dyn WindowAdapter>, PlatformError> {
        Ok(self.0.clone())
    }
}

fn fixture() -> PathBuf {
    let root = std::env::temp_dir().join(format!(
        "estante-slint-check-{}-{}",
        std::process::id(),
        TEST_FIXTURE_SEQUENCE.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    ));
    std::fs::create_dir_all(&root).unwrap();
    let cover = root.join("cover.png");
    let banner = root.join("banner.png");
    image::RgbaImage::from_fn(240, 360, |x, y| {
        image::Rgba([32 + (x / 2) as u8, 50 + (y / 3) as u8, 128, 255])
    })
    .save(&cover)
    .unwrap();
    image::RgbaImage::from_fn(1280, 720, |x, y| {
        image::Rgba([20 + (x / 8) as u8, 30 + (y / 5) as u8, 80, 255])
    })
    .save(&banner)
    .unwrap();
    let logo = root.join("logo.png");
    image::RgbaImage::from_fn(320, 90, |x, y| {
        image::Rgba([
            90,
            209,
            255,
            if (12..308).contains(&x) && (12..78).contains(&y) {
                255
            } else {
                0
            },
        ])
    })
    .save(&logo)
    .unwrap();
    let titles = [
        "Árbol del tiempo",
        "Celeste",
        "Doom",
        "Elden Ring",
        "Fábula",
        "Hollow Knight",
        "Portal",
        "Stardew Valley",
        "The Witcher",
        "Zelda",
        "2 mundos",
        "Ōkami",
    ];
    let games = titles.iter().enumerate().map(|(i, title)| json!({
        "id": format!("local:{i}"), "kind": "local", "title": title,
        "path": "/missing/game.sh", "arguments": "", "cwd": "",
        "cover": cover, "banner": banner,
        "logo": if *title == "Celeste" { Some(logo.clone()) } else if *title == "2 mundos" { Some(root.join("missing-logo.png")) } else { None },
        "categories": if i % 2 == 0 { vec!["Favoritos"] } else { vec!["Aventura"] },
        "metadata": {"description":"Una aventura para explorar mundos y descubrir historias. Esta descripción permite comprobar el espacio de lectura de la ficha.", "developers":["Estudio de prueba"],"genres":["Aventura","Exploración"],"platforms":["Linux"], "release_date":"2025-01-01"}
    })).collect::<Vec<_>>();
    std::fs::write(
        root.join("library.json"),
        serde_json::to_vec(
            &json!({"games":games,"overrides":{},"faugus":[],"source_categories_initialized":true}),
        )
        .unwrap(),
    )
    .unwrap();
    std::fs::write(
        root.join("settings.json"),
        br#"{"list_side":"left","start_fullscreen":false,"background_dim":{"list":40}}"#,
    )
    .unwrap();
    root
}

fn snapshot(adapter: &MinimalSoftwareWindow, folder: &Path, name: &str, width: u32, height: u32) {
    adapter.set_size(slint::PhysicalSize::new(width, height));
    adapter.request_redraw();
    let mut pixels = slint::SharedPixelBuffer::<slint::Rgb8Pixel>::new(width, height);
    adapter.draw_if_needed(|renderer| {
        renderer.render(pixels.make_mut_slice(), width as usize);
    });
    TEST_TIME.fetch_add(200, std::sync::atomic::Ordering::Relaxed);
    slint::platform::update_timers_and_animations();
    adapter.request_redraw();
    assert!(adapter.draw_if_needed(|renderer| {
        renderer.render(pixels.make_mut_slice(), width as usize);
    }));
    assert!(pixels.as_bytes().iter().any(|value| *value > 100));
    image::save_buffer(
        folder.join(format!("{name}.png")),
        pixels.as_bytes(),
        width,
        height,
        image::ColorType::Rgb8,
    )
    .unwrap();
}

fn wait_for_visible_row_images(window: &ListWindow, events: &mpsc::Receiver<UiEvent>) {
    let deadline = Instant::now() + Duration::from_secs(10);
    loop {
        let games = window.get_games();
        let count = games.row_count();
        if count == 0 {
            return;
        }
        let selected = window.get_selected_index().clamp(0, count as i32 - 1) as usize;
        let radius = (window.get_visible_image_radius().max(0) as usize).min(count / 2);
        let ready = (-(radius as isize)..=radius as isize).all(|offset| {
            let index = (selected as isize + offset).rem_euclid(count as isize) as usize;
            games
                .row_data(index)
                .is_some_and(|row| row.list_image.size().width > 0)
        });
        if ready {
            return;
        }
        events
            .recv_timeout(deadline.saturating_duration_since(Instant::now()))
            .expect("visible artwork must reach the software-rendered UI")();
    }
}

fn click(window: &ListWindow, x: f32, y: f32) {
    use slint::platform::{PointerEventButton, WindowEvent};
    let position = slint::LogicalPosition::new(x, y);
    window
        .window()
        .dispatch_event(WindowEvent::PointerMoved { position });
    window.window().dispatch_event(WindowEvent::PointerPressed {
        position,
        button: PointerEventButton::Left,
    });
    window
        .window()
        .dispatch_event(WindowEvent::PointerReleased {
            position,
            button: PointerEventButton::Left,
        });
    slint::platform::update_timers_and_animations();
}

fn press_control_shortcut(window: &ListWindow, key: &str) {
    use slint::platform::WindowEvent;
    let control: slint::SharedString = slint::platform::Key::Control.into();
    let text = slint::SharedString::from(key);
    window.window().dispatch_event(WindowEvent::KeyPressed {
        text: control.clone(),
    });
    window
        .window()
        .dispatch_event(WindowEvent::KeyPressed { text: text.clone() });
    window
        .window()
        .dispatch_event(WindowEvent::KeyReleased { text });
    window
        .window()
        .dispatch_event(WindowEvent::KeyReleased { text: control });
    slint::platform::update_timers_and_animations();
}

fn prepare_local_game(root: &Path) -> String {
    let executable = root.join("test-game.sh");
    std::fs::write(&executable, "#!/bin/sh\nexec sleep 2\n").unwrap();
    let mut library = Library::open(root);
    let game = library
        .games()
        .into_iter()
        .find(|game| game.title() == "2 mundos")
        .unwrap();
    let game_id = game.id().to_owned();
    let mut changes = game.data().clone();
    changes.insert("path".into(), json!(executable));
    let long_description = "Una aventura para explorar mundos y descubrir historias. ".repeat(20);
    changes.insert("description".into(), json!(long_description.clone()));
    changes.insert("synopsis".into(), json!(long_description));
    library.update_game(&game_id, &changes).unwrap();
    game_id
}

fn native_snapshot(window: &ListWindow, root: &Path, name: &str) {
    let pixels = window.window().take_snapshot().unwrap();
    image::save_buffer(
        root.join(name),
        pixels.as_bytes(),
        pixels.width(),
        pixels.height(),
        image::ColorType::Rgba8,
    )
    .unwrap();
}

fn capture_native_sides(
    weak: slint::Weak<ListWindow>,
    root: PathBuf,
    sides: &'static [&'static str],
    deadline: Instant,
    done: impl FnOnce() + 'static,
) {
    let Some((side, remaining)) = sides.split_first() else {
        done();
        return;
    };
    if weak.unwrap().get_selected_background_image().size().width == 0 {
        assert!(
            Instant::now() < deadline,
            "el fondo de Lista debe cargarse antes de la captura nativa"
        );
        slint::Timer::single_shot(Duration::from_millis(100), move || {
            capture_native_sides(weak, root, sides, deadline, done);
        });
        return;
    }
    weak.unwrap().set_list_side((*side).into());
    let name = format!("native-{side}.png");
    slint::Timer::single_shot(Duration::from_millis(475), move || {
        native_snapshot(&weak.unwrap(), &root, &name);
        capture_native_sides(weak, root, remaining, deadline, done);
    });
}

fn capture_native_background_splits(
    weak: slint::Weak<ListWindow>,
    root: PathBuf,
    splits: &'static [&'static str],
    deadline: Instant,
    done: impl FnOnce() + 'static,
) {
    let Some((split, remaining)) = splits.split_first() else {
        done();
        return;
    };
    let window = weak.unwrap();
    let previous = window.window().take_snapshot().unwrap().as_bytes().to_vec();
    window.set_background_split((*split).into());
    wait_native_background_split(weak, root, split, remaining, previous, deadline, done);
}

fn wait_native_background_split(
    weak: slint::Weak<ListWindow>,
    root: PathBuf,
    split: &'static str,
    remaining: &'static [&'static str],
    previous: Vec<u8>,
    deadline: Instant,
    done: impl FnOnce() + 'static,
) {
    let window = weak.unwrap();
    let pixels = window.window().take_snapshot().unwrap();
    if pixels.as_bytes() == previous.as_slice() {
        assert!(
            Instant::now() < deadline,
            "la división {split} del fondo debe actualizar la captura nativa"
        );
        slint::Timer::single_shot(Duration::from_millis(100), move || {
            wait_native_background_split(weak, root, split, remaining, previous, deadline, done);
        });
        return;
    }
    let name = format!("native-background-{split}.png");
    image::save_buffer(
        root.join(&name),
        pixels.as_bytes(),
        pixels.width(),
        pixels.height(),
        image::ColorType::Rgba8,
    )
    .unwrap();
    slint::Timer::single_shot(Duration::from_millis(475), move || {
        capture_native_background_splits(
            weak,
            root,
            remaining,
            Instant::now() + Duration::from_secs(20),
            done,
        );
    });
}

#[test]
fn carousel_render_indices_wrap_and_stay_bounded() {
    assert_eq!(
        visible_carousel_indices(0, 10_000, 2),
        [0, 1, 2, 9_998, 9_999]
    );
    assert_eq!(visible_carousel_indices(5, 10, 2), [3, 4, 5, 6, 7]);
    assert_eq!(visible_carousel_indices(99, 2, 99), [0, 1]);
    assert!(visible_carousel_indices(0, 0, 4).is_empty());
}

#[test]
fn details_cover_settings_can_select_the_game_logo() {
    let adapter = MinimalSoftwareWindow::new(RepaintBufferType::NewBuffer);
    let (tx, _events) = mpsc::channel();
    slint::platform::set_platform(Box::new(SoftwarePlatform(adapter.clone(), tx))).unwrap();
    let root = fixture();
    let (window, _timer) = build_window(Library::open(&root), false, None).unwrap();
    window.show().unwrap();
    adapter.set_size(slint::PhysicalSize::new(1280, 800));
    window.set_showing_settings(true);
    window.set_settings_section(1);
    let portrait = Image::load_from_path(&root.join("cover.png")).unwrap();
    let logo = Image::load_from_path(&root.join("logo.png")).unwrap();
    window.set_selected_cover_portrait(portrait.clone());
    window.set_selected_cover_logo(logo.clone());
    window.set_selected_cover(portrait);

    let details_cover_label = if window.get_english_ui() {
        "Details cover"
    } else {
        "Carátula de la ficha"
    };
    let _details_cover = i_slint_backend_testing::ElementHandle::find_by_accessible_label(
        &window,
        details_cover_label,
    )
    .next()
    .expect("the List settings should expose the details-cover group");
    let logo_label = if window.get_english_ui() {
        "Logo"
    } else {
        "Logotipo"
    };
    let logo_radio =
        i_slint_backend_testing::ElementHandle::find_by_accessible_label(&window, logo_label)
            .find(|item| {
                item.accessible_role() == Some(i_slint_backend_testing::AccessibleRole::RadioButton)
            })
            .expect("details-cover settings should expose a Logo format option");
    logo_radio.invoke_accessible_default_action();

    assert_eq!(window.get_cover_format(), "logo");
    assert_eq!(window.get_selected_cover().size(), logo.size());
}

#[test]
fn list_settings_cards_preserve_controls_and_focus_navigation() {
    let adapter = MinimalSoftwareWindow::new(RepaintBufferType::NewBuffer);
    let (tx, _events) = mpsc::channel();
    slint::platform::set_platform(Box::new(SoftwarePlatform(adapter.clone(), tx))).unwrap();
    let root = fixture();
    let (window, _timer) = build_window(Library::open(&root), false, None).unwrap();
    window.show().unwrap();
    adapter.set_size(slint::PhysicalSize::new(1436, 1900));
    window.set_showing_settings(true);
    window.set_settings_section(1);
    slint::platform::update_timers_and_animations();
    snapshot(&adapter, &root, "list-settings-cards", 1436, 1900);
    let labels = if window.get_english_ui() {
        [
            "List position",
            "Background image",
            "Hero position",
            "Background split",
            "Carousel artwork",
            "Game information",
            "Presentation",
            "Details cover",
            "Selection ring",
            "Logos",
            "Portrait covers (2:3)",
            "Square covers (1:1)",
            "Portrait (2:3)",
            "Square (1:1)",
            "Logo",
            "Launcher details",
            "Show game information",
            "Minimal presentation",
            "Show details cover",
            "Selection border",
            "Border color",
        ]
    } else {
        [
            "Posición de la lista",
            "Imagen de fondo",
            "Posición del hero",
            "División de los fondos",
            "Imagen del carrusel",
            "Información del juego",
            "Presentación",
            "Carátula de la ficha",
            "Anillo de selección",
            "Logos",
            "Carátulas verticales (2:3)",
            "Carátulas cuadradas (1:1)",
            "Vertical (2:3)",
            "Cuadrado (1:1)",
            "Logotipo",
            "Datos del lanzador",
            "Mostrar información del juego",
            "Presentación mínima",
            "Mostrar carátula de la ficha",
            "Borde de selección",
            "Color del borde",
        ]
    };
    for label in labels {
        assert!(
            i_slint_backend_testing::ElementHandle::find_by_accessible_label(&window, label)
                .next()
                .is_some(),
            "List settings must expose `{label}`"
        );
    }

    let sliders = if window.get_english_ui() {
        [
            "Selected item zoom",
            "Cover corner radius",
            "Corner radius",
            "Cover size",
            "Border width",
            "Border radius",
        ]
    } else {
        [
            "Ampliación seleccionada",
            "Redondeado de carátulas",
            "Redondeado",
            "Tamaño de carátula",
            "Grosor del borde",
            "Radio del borde",
        ]
    };
    for label in sliders {
        assert!(
            i_slint_backend_testing::ElementHandle::find_by_accessible_label(&window, label).any(
                |item| {
                    item.accessible_role() == Some(i_slint_backend_testing::AccessibleRole::Slider)
                }
            ),
            "List settings must expose slider `{label}`"
        );
    }
    let checks = if window.get_english_ui() {
        [
            "Launcher details",
            "Show game information",
            "Minimal presentation",
            "Show details cover",
            "Selection border",
        ]
    } else {
        [
            "Datos del lanzador",
            "Mostrar información del juego",
            "Presentación mínima",
            "Mostrar carátula de la ficha",
            "Borde de selección",
        ]
    };
    for label in checks {
        assert!(
            i_slint_backend_testing::ElementHandle::find_by_accessible_label(&window, label).any(
                |item| {
                    item.accessible_role()
                        == Some(i_slint_backend_testing::AccessibleRole::Checkbox)
                }
            ),
            "List settings must expose checkbox `{label}`"
        );
    }

    window.invoke_focus_settings_sidebar();
    handle_action(&window, "right");
    assert_eq!(window.get_settings_focus_target(), 0);
    let mut visited = [false; 9];
    for _ in 0..80 {
        let target = window.get_settings_focus_target();
        if (0..9).contains(&target) {
            visited[target as usize] = true;
        }
        if target == -2 {
            break;
        }
        handle_action(&window, "down");
    }
    assert_eq!(
        visited, [true; 9],
        "Tab navigation must reach all nine focus units"
    );

    window.invoke_focus_settings_content();
    handle_action(&window, "right");
    assert_eq!(
        window.get_settings_focus_target(),
        5,
        "D-pad right from List position must enter the top of the opposite column"
    );
    handle_action(&window, "left");
    assert!(
        [0, 1].contains(&window.get_settings_focus_target()),
        "D-pad left must return to the nearest layout/background group, got {}",
        window.get_settings_focus_target()
    );

    window.invoke_focus_settings_content();
    for _ in 0..12 {
        if window.get_settings_focus_target() == 1 {
            break;
        }
        handle_action(&window, "down");
    }
    assert_eq!(window.get_settings_focus_target(), 1);
    handle_action(&window, "right");
    assert_eq!(window.get_settings_focus_target(), 6);
    handle_action(&window, "left");
    assert_eq!(window.get_settings_focus_target(), 1);
}

#[test]
fn list_carousel_uses_fixed_enlarged_artwork_scale() {
    let adapter = MinimalSoftwareWindow::new(RepaintBufferType::NewBuffer);
    let (tx, _events) = mpsc::channel();
    slint::platform::set_platform(Box::new(SoftwarePlatform(adapter.clone(), tx))).unwrap();
    let root = fixture();
    let mut settings = Library::open(&root).settings().unwrap();
    settings["list_zoom"] = json!(50);
    Library::save_settings_at(&root, &settings).unwrap();
    let (window, _timer) = build_window(Library::open(&root), false, None).unwrap();
    window.show().unwrap();
    adapter.set_size(slint::PhysicalSize::new(1280, 800));
    slint::platform::update_timers_and_animations();
    window.set_selected_index(1);
    window.set_color_theme("combination-143".into());
    window.set_ring_enabled(false);
    let high_res_cover_path = root.join("high-res-cover.png");
    image::RgbaImage::from_fn(960, 1440, |x, y| {
        if x % 96 < 4 || y % 144 < 4 {
            image::Rgba([230, 185, 112, 255])
        } else {
            image::Rgba([24 + (x / 12) as u8, 36 + (y / 16) as u8, 92, 255])
        }
    })
    .save(&high_res_cover_path)
    .unwrap();
    let (list_max_width, list_max_height, _, _) = row_image_bounds(&window);
    let mut image_cache = HashMap::new();
    let mut image_cache_order = std::collections::VecDeque::new();
    let mut image_cache_bytes = 0;
    let cover_pixels = row_image_pixels(
        Some(high_res_cover_path.to_str().unwrap()),
        list_max_width,
        list_max_height,
        false,
        &mut image_cache,
        &mut image_cache_order,
        &mut image_cache_bytes,
    )
    .unwrap();
    assert_eq!(cover_pixels.height, list_max_height);
    assert!(cover_pixels.width <= list_max_width);
    let cover_image = row_pixels_to_image(&cover_pixels);
    let logo_image = Image::load_from_path(&root.join("logo.png")).unwrap();
    window.set_selected_cover_logo(logo_image.clone());
    assert_eq!(window.get_selected_cover_logo().size(), logo_image.size());
    window.set_cover_format("logo".into());
    assert_eq!(window.get_cover_format(), "logo");
    window.set_selected_cover(logo_image.clone());
    assert_eq!(
        window.get_selected_cover().size(),
        logo_image.size(),
        "logo format should use the selected game's logo image"
    );
    window.set_cover_format("portrait".into());
    let games = window.get_games();
    let rows = games
        .as_any()
        .downcast_ref::<VecModel<GameRow>>()
        .expect("fixture games use the mutable UI model");
    for index in 0..rows.row_count() {
        let mut row = rows.row_data(index).unwrap();
        row.list_image = cover_image.clone();
        row.list_is_logo = false;
        rows.set_row_data(index, row);
    }
    let mut logo_row = rows.row_data(1).unwrap();
    logo_row.list_image = logo_image.clone();
    logo_row.list_is_logo = true;
    rows.set_row_data(1, logo_row);
    window.set_visible_game_indices(ModelRc::new(VecModel::from(
        (0..rows.row_count() as i32).collect::<Vec<_>>(),
    )));
    slint::platform::update_timers_and_animations();
    let artwork_bounds = row_image_bounds(&window);
    let (_, vertical_list_height, _, _) = artwork_bounds;
    assert!(
        window.get_list_artwork_scale() >= 150,
        "the artwork scale is a fixed enlarged value"
    );
    assert_eq!(
        Library::open(&root).settings().unwrap()["list_zoom"],
        50,
        "a legacy slider value does not change the fixed artwork scale"
    );
    assert!(
        !ui_settings_snapshot(&window)
            .as_object()
            .unwrap()
            .contains_key("list_zoom"),
        "the removed artwork-size slider is no longer saved"
    );
    assert!(vertical_list_height > 0);
    snapshot(&adapter, &root, "focus-shadow-logo", 1280, 800);
    eprintln!(
        "Logo shadow render: {}",
        root.join("focus-shadow-logo.png").display()
    );

    window.set_selected_index(0);
    let mut cover_row = rows.row_data(0).unwrap();
    cover_row.list_image = cover_image.clone();
    cover_row.list_is_logo = false;
    rows.set_row_data(0, cover_row);
    snapshot(&adapter, &root, "focus-shadow-cover", 1280, 800);
    eprintln!(
        "Cover shadow render: {}",
        root.join("focus-shadow-cover.png").display()
    );

    window.set_list_side("bottom".into());
    window.set_selected_index(0);
    slint::platform::update_timers_and_animations();
    let visible_indices = window.get_visible_game_indices();
    assert_eq!(
        window.get_visible_image_radius(),
        3,
        "the bottom wheel should show three games on each side of the selection"
    );
    let (_, horizontal_list_height, _, _) = row_image_bounds(&window);
    assert!(
        horizontal_list_height >= 380,
        "the horizontal carousel needs enough height to render larger artwork"
    );
    assert_eq!(
        vertical_list_height, horizontal_list_height,
        "the focused cover should retain its horizontal size when the carousel moves to the side"
    );
    assert_eq!(visible_indices.row_count(), 7);
    for position in 0..visible_indices.row_count() {
        let index = visible_indices.row_data(position).unwrap() as usize;
        let mut row = rows.row_data(index).unwrap();
        row.list_image = if row.id == "local:1" {
            logo_image.clone()
        } else {
            cover_image.clone()
        };
        rows.set_row_data(index, row);
    }
    snapshot(&adapter, &root, "wheel-more-neighbors", 1920, 1440);
    eprintln!(
        "Wheel with more neighbors: {}",
        root.join("wheel-more-neighbors.png").display()
    );
    window.set_list_side("left".into());
    slint::platform::update_timers_and_animations();
    snapshot(&adapter, &root, "wheel-side-covers", 1920, 1440);
    eprintln!(
        "Wheel with side covers: {}",
        root.join("wheel-side-covers.png").display()
    );
}

#[test]
#[ignore = "requires a native display and an isolated test process"]
fn native_list_window() {
    let root = fixture();
    let game_id = prepare_local_game(&root);
    let primary = root.join("composite-primary.png");
    let secondary = root.join("composite-secondary.png");
    image::RgbaImage::from_fn(1280, 720, |x, y| {
        let red = if x / 20 % 2 == 0 { 220 } else { 120 };
        image::Rgba([red, 24, 36, if y < 360 { 255 } else { 0 }])
    })
    .save(&primary)
    .unwrap();
    image::RgbaImage::from_fn(1280, 720, |x, y| {
        let blue = if x / 20 % 2 == 0 { 224 } else { 128 };
        image::Rgba([24, 72, blue, if y < 360 { 255 } else { 0 }])
    })
    .save(&secondary)
    .unwrap();
    let mut library: Value =
        serde_json::from_slice(&std::fs::read(root.join("library.json")).unwrap()).unwrap();
    for game in library["games"].as_array_mut().unwrap() {
        game["banner"] = json!(primary);
        game["banner_secondary"] = json!(secondary);
    }
    std::fs::write(
        root.join("library.json"),
        serde_json::to_vec(&library).unwrap(),
    )
    .unwrap();
    let mut settings: Value =
        serde_json::from_slice(&std::fs::read(root.join("settings.json")).unwrap()).unwrap();
    settings["background_splits"] = json!({"list": "diagonal"});
    settings["background_blur"] = json!({"list": 20});
    settings["background_fill"] = json!("dominant");
    settings["hero_positions"] = json!({"list": "top"});
    std::fs::write(
        root.join("settings.json"),
        serde_json::to_vec(&settings).unwrap(),
    )
    .unwrap();
    let (window, _timer) = build_window(Library::open(&root), false, None).unwrap();
    window.set_list_side("bottom".into());
    window.set_color_scheme(slint::language::ColorScheme::Dark);
    window.show().unwrap();
    let weak = window.as_weak();
    let captures = root.clone();
    let launched_id = game_id.clone();
    let settings_opened = Rc::new(std::cell::Cell::new(false));
    let opened = settings_opened.clone();
    capture_native_sides(
        window.as_weak(),
        root.clone(),
        &["left", "right", "top", "bottom"],
        Instant::now() + Duration::from_secs(10),
        move || {
            let window = weak.unwrap();
            let size = window
                .window()
                .size()
                .to_logical(window.window().scale_factor());
            window.set_list_side("right".into());
            slint::platform::update_timers_and_animations();
            let before_scroll = window.window().take_snapshot().unwrap();
            let position = slint::LogicalPosition::new(size.width * 0.45, size.height * 0.61);
            let mut scrolled = false;
            for delta_y in [400.0, -800.0] {
                window
                    .window()
                    .dispatch_event(slint::platform::WindowEvent::PointerScrolled {
                        position,
                        delta_x: 0.0,
                        delta_y,
                    });
                slint::platform::update_timers_and_animations();
                if window.window().take_snapshot().unwrap().as_bytes() != before_scroll.as_bytes() {
                    scrolled = true;
                    break;
                }
            }
            assert!(
                scrolled,
                "the detail panel must scroll with the wheel when its scrollbar is hidden"
            );
            click(&window, 392., size.height - 48.);
            opened.set(window.get_showing_settings());
            window.set_settings_section(1);
            native_snapshot(&window, &captures, "native-list-settings.png");
            handle_action(&window, "right");
            assert_eq!(window.get_settings_focus_target(), 0);
            handle_action(&window, "confirm");
            native_snapshot(&window, &captures, "native-list-position-open.png");
            handle_action(&window, "down");
            handle_action(&window, "confirm");
            assert_eq!(window.get_list_side(), "left");
            handle_action(&window, "down");
            handle_action(&window, "confirm");
            assert_eq!(window.get_list_side(), "right");
            handle_action(&window, "right");
            assert_eq!(window.get_settings_focus_target(), 7);
            handle_action(&window, "left");
            assert_eq!(window.get_settings_focus_target(), 1);
            for (side, y) in [
                ("left", 280.),
                ("right", 320.),
                ("top", 360.),
                ("bottom", 400.),
            ] {
                click(&window, 335., y);
                assert_eq!(window.get_list_side(), side);
            }
            click(&window, size.width - 132., size.height - 122.);
            assert_eq!(
                Library::open(&captures).settings().unwrap()["list_side"],
                "bottom"
            );
            window.invoke_back();
            let index = window
                .get_games()
                .iter()
                .position(|row| row.id == game_id)
                .unwrap();
            window.set_selected_index(index as i32);
            window.set_cover_format("square".into());
            window.invoke_play_selected();
            for (delay, name) in [
                (110, "native-launch.png"),
                (900, "native-launch-settled.png"),
            ] {
                let weak = window.as_weak();
                let captures = captures.clone();
                slint::Timer::single_shot(Duration::from_millis(delay), move || {
                    native_snapshot(&weak.unwrap(), &captures, name);
                });
            }
            slint::Timer::single_shot(Duration::from_secs(3), || slint::quit_event_loop().unwrap());
        },
    );
    slint::run_event_loop().unwrap();
    assert!(settings_opened.get());
    assert!(
        !window.get_game_session_active(),
        "{}",
        window.get_save_message()
    );
    assert_eq!(Library::open(&root).session_count(&launched_id), 1);
    eprintln!("Capturas nativas: {}", root.display());
    for limit in [2, 1, 0] {
        window.invoke_search_changed(
            match limit {
                2 => "do",
                1 => "Portal",
                _ => "absent",
            }
            .into(),
        );
        let count = window.get_games().row_count();
        assert_eq!(count, limit);
        for side in ["left", "right", "top", "bottom"] {
            window.set_list_side(side.into());
            if count > 0 {
                window.set_selected_index(count as i32 - 1);
                handle_action(&window, "right");
                assert_eq!(window.get_selected_index(), 0);
                handle_action(&window, "left");
                assert_eq!(window.get_selected_index(), count as i32 - 1);
            } else {
                assert_eq!(window.get_visible_game_indices().row_count(), 0);
                handle_action(&window, "confirm");
                assert!(window.get_showing_settings());
                assert_eq!(window.get_settings_section(), 3);
                window.invoke_back();
            }
        }
    }
    window.hide().unwrap();
}

#[test]
#[ignore = "requires a native display and an isolated test process"]
fn native_list_global_background() {
    let root = fixture();
    let global = root.join("global-background.png");
    image::RgbaImage::from_fn(1280, 720, |x, y| {
        let green = if (x / 24 + y / 24) % 2 == 0 { 220 } else { 110 };
        image::Rgba([24, green, 48, 255])
    })
    .save(&global)
    .unwrap();
    let mut settings: Value =
        serde_json::from_slice(&std::fs::read(root.join("settings.json")).unwrap()).unwrap();
    settings["background_source"] = json!("global");
    settings["global_background"] = json!(global.to_string_lossy().to_string());
    settings["background_splits"] = json!({"list": "single"});
    settings["background_blur"] = json!({"list": 0});
    settings["background_dim"] = json!({"list": 0});
    settings["hero_positions"] = json!({"list": "full"});
    settings["language"] = json!("en");
    std::fs::write(
        root.join("settings.json"),
        serde_json::to_vec(&settings).unwrap(),
    )
    .unwrap();
    let (window, _timer) = build_window(Library::open(&root), false, None).unwrap();
    window.set_list_side("right".into());
    window.set_color_scheme(slint::language::ColorScheme::Dark);
    window.show().unwrap();
    let weak = window.as_weak();
    let captures = root.clone();
    capture_native_sides(
        window.as_weak(),
        root.clone(),
        &["right"],
        Instant::now() + Duration::from_secs(10),
        move || {
            assert!(weak.unwrap().get_selected_background_image().size().width > 0);
            slint::Timer::single_shot(Duration::from_millis(100), || {
                slint::quit_event_loop().unwrap();
            });
        },
    );
    slint::run_event_loop().unwrap();
    window.hide().unwrap();
    eprintln!("Captura de fondo global: {}", captures.display());
}

#[test]
#[ignore = "requires a native display and an isolated test process"]
fn native_list_background_splits() {
    let root = fixture();
    let primary = root.join("split-primary.png");
    let secondary = root.join("split-secondary.png");
    image::RgbaImage::from_pixel(1280, 720, image::Rgba([220, 24, 36, 255]))
        .save(&primary)
        .unwrap();
    image::RgbaImage::from_pixel(1280, 720, image::Rgba([24, 72, 224, 255]))
        .save(&secondary)
        .unwrap();
    let mut library: Value =
        serde_json::from_slice(&std::fs::read(root.join("library.json")).unwrap()).unwrap();
    for game in library["games"].as_array_mut().unwrap() {
        game["banner"] = json!(primary);
        game["banner_secondary"] = json!(secondary);
    }
    std::fs::write(
        root.join("library.json"),
        serde_json::to_vec(&library).unwrap(),
    )
    .unwrap();
    let mut settings: Value =
        serde_json::from_slice(&std::fs::read(root.join("settings.json")).unwrap()).unwrap();
    settings["background_splits"] = json!({"list": "diagonal"});
    settings["background_blur"] = json!({"list": 0});
    settings["background_dim"] = json!({"list": 0});
    settings["hero_positions"] = json!({"list": "full"});
    settings["language"] = json!("en");
    std::fs::write(
        root.join("settings.json"),
        serde_json::to_vec(&settings).unwrap(),
    )
    .unwrap();
    let (window, _timer) = build_window(Library::open(&root), false, None).unwrap();
    window.set_list_side("right".into());
    window.set_color_scheme(slint::language::ColorScheme::Dark);
    window.show().unwrap();
    let weak = window.as_weak();
    let root_for_splits = root.clone();
    capture_native_sides(
        weak.clone(),
        root.clone(),
        &["right"],
        Instant::now() + Duration::from_secs(10),
        move || {
            capture_native_background_splits(
                weak,
                root_for_splits,
                &["horizontal", "vertical", "diagonal"],
                Instant::now() + Duration::from_secs(10),
                || slint::quit_event_loop().unwrap(),
            );
        },
    );
    slint::run_event_loop().unwrap();
    window.hide().unwrap();
    eprintln!("Capturas de divisiones nativas: {}", root.display());
}

#[test]
fn editor_focus_navigation_follows_visible_controls() {
    assert_eq!(editor_focus_neighbor(0, "right", false, false), Some(1));
    assert_eq!(editor_focus_neighbor(0, "down", false, false), Some(3));
    assert_eq!(editor_focus_neighbor(4, "down", false, false), Some(8));
    assert_eq!(editor_focus_neighbor(4, "down", true, true), Some(6));
    assert_eq!(editor_focus_neighbor(13, "right", false, false), Some(14));
    assert_eq!(editor_focus_neighbor(14, "left", false, false), Some(13));
    assert_eq!(editor_focus_neighbor(2, "up", false, false), Some(15));
    assert_eq!(editor_focus_neighbor(0, "left", false, false), None);

    assert_eq!(
        editor_subpage_focus_neighbor("manual", 2, "down", 0, true),
        Some(3)
    );
    assert_eq!(
        editor_subpage_focus_neighbor("manual", 10, "right", 0, true),
        Some(11)
    );
    assert_eq!(
        editor_subpage_focus_neighbor("manual", 11, "left", 0, true),
        Some(10)
    );
    assert_eq!(
        editor_subpage_focus_neighbor("manual", 3, "right", 0, true),
        None
    );

    assert_eq!(
        editor_subpage_focus_neighbor("categories", 6, "right", 5, true),
        Some(7)
    );
    assert_eq!(
        editor_subpage_focus_neighbor("categories", 8, "left", 5, true),
        Some(7)
    );
    assert_eq!(
        editor_subpage_focus_neighbor("categories", 8, "up", 5, true),
        Some(6)
    );

    assert_eq!(
        editor_subpage_focus_neighbor("execution", 2, "down", 0, true),
        Some(3)
    );
    assert_eq!(
        editor_subpage_focus_neighbor("execution", 3, "right", 0, true),
        None
    );
    assert_eq!(
        editor_subpage_focus_neighbor("execution", 5, "down", 0, true),
        Some(6)
    );
    assert_eq!(
        editor_subpage_focus_neighbor("execution", 7, "left", 0, false),
        Some(6)
    );
    assert_eq!(
        editor_subpage_focus_neighbor("execution", 7, "up", 0, false),
        Some(1)
    );

    assert_eq!(artwork_focus_neighbor(2, "right", false), Some(3));
    assert_eq!(artwork_focus_neighbor(9, "right", false), Some(10));
    assert_eq!(artwork_focus_neighbor(10, "down", false), Some(12));
    assert_eq!(artwork_focus_neighbor(12, "left", false), Some(11));
    assert_eq!(artwork_result_focus_neighbor(0, 5, 2, "down"), Some(2));
    assert_eq!(artwork_result_focus_neighbor(3, 5, 2, "down"), Some(4));
    assert_eq!(artwork_result_focus_neighbor(4, 5, 2, "down"), None);
}

#[test]
fn list_runtime_and_snapshots() {
    let adapter = MinimalSoftwareWindow::new(RepaintBufferType::NewBuffer);
    let (tx, events) = mpsc::channel();
    slint::platform::set_platform(Box::new(SoftwarePlatform(adapter.clone(), tx))).unwrap();
    let root = fixture();
    let game_id = prepare_local_game(&root);
    let (window, _timer) = build_window(Library::open(&root), false, None).unwrap();
    window.set_color_scheme(slint::language::ColorScheme::Dark);
    window.show().unwrap();
    assert!(
        window.get_show_game_information(),
        "game information should remain visible by default"
    );
    assert_eq!(window.get_games().row_count(), 12);
    adapter.set_size(slint::PhysicalSize::new(1280, 800));
    slint::platform::update_timers_and_animations();
    window.invoke_selection_changed(window.get_selected_index());
    let rendered_indices = window.get_visible_game_indices();
    assert!(
        rendered_indices
            .iter()
            .any(|index| index == window.get_selected_index())
    );
    assert!(rendered_indices.row_count() <= (2 * window.get_visible_image_radius() + 1) as usize);
    window.invoke_focus_library();
    assert!(!window.get_text_input_focused());
    handle_action(&window, "save");
    assert!(
        window.get_showing_editor(),
        "the gamepad save button opens Edit"
    );
    handle_action(&window, "back");
    assert!(
        !window.get_showing_editor(),
        "the gamepad back button cancels Edit"
    );
    window.invoke_focus_library();
    press_control_shortcut(&window, "f");
    assert!(
        window.get_text_input_focused(),
        "Ctrl+F should focus library search"
    );
    window.invoke_focus_library();
    let deadline = Instant::now() + Duration::from_secs(10);
    while window.get_selected_background_image().size().width == 0 {
        events
            .recv_timeout(deadline.saturating_duration_since(Instant::now()))
            .expect("selected banner must reach the UI")();
    }
    let selected_index = window.get_selected_index() as usize;
    while window
        .get_games()
        .row_data(selected_index)
        .unwrap()
        .list_image
        .size()
        .width
        == 0
    {
        events
            .recv_timeout(deadline.saturating_duration_since(Instant::now()))
            .expect("selected list artwork must reach the UI")();
    }
    let selected_row = window.get_games().row_data(selected_index).unwrap();
    assert!(
        window.get_selected_cover().size().width > 0,
        "the detail panel must receive the selected cover after its image loads"
    );
    let list_label = if window.get_english_ui() {
        "Game list"
    } else {
        "Lista de juegos"
    };
    let accessible_list =
        i_slint_backend_testing::ElementHandle::find_by_accessible_label(&window, list_label)
            .next()
            .expect("screen readers must discover the game list");
    assert_eq!(
        accessible_list.accessible_role(),
        Some(i_slint_backend_testing::AccessibleRole::List)
    );
    assert_eq!(accessible_list.accessible_item_count(), Some(12));
    let original_language = window.get_language();
    window.set_language(if window.get_english_ui() { "es" } else { "en" }.into());
    let alternate_list_label = if window.get_english_ui() {
        "Game list"
    } else {
        "Lista de juegos"
    };
    assert_eq!(
        accessible_list.accessible_label().as_deref(),
        Some(alternate_list_label)
    );
    window.set_language(original_language);
    let mut accessible_item_indices = Vec::new();
    let mut accessible_selected_count = 0;
    let mut accessible_image_count = 0;
    accessible_list.visit_descendants(|item| {
        if item.accessible_role() == Some(i_slint_backend_testing::AccessibleRole::ListItem) {
            assert_eq!(item.accessible_item_selectable(), Some(true));
            let index = item.accessible_item_index().unwrap();
            let expected_label = window.get_games().row_data(index as usize).unwrap().title;
            assert_eq!(
                item.accessible_label().as_deref(),
                Some(expected_label.as_str())
            );
            accessible_item_indices.push(index);
            accessible_selected_count += usize::from(item.accessible_item_selected() == Some(true));
        } else if item.accessible_role() == Some(i_slint_backend_testing::AccessibleRole::Image) {
            accessible_image_count += 1;
        }
        std::ops::ControlFlow::<()>::Continue(())
    });
    accessible_item_indices.sort_unstable();
    assert_eq!(accessible_item_indices, (0..12).collect::<Vec<_>>());
    assert_eq!(accessible_selected_count, 1);
    assert_eq!(
        accessible_image_count, 0,
        "decorative list artwork must not create unlabeled screen reader entries"
    );
    let accessible_selection = i_slint_backend_testing::ElementHandle::find_by_accessible_label(
        &window,
        selected_row.title.as_str(),
    )
    .find(|item| {
        item.accessible_role() == Some(i_slint_backend_testing::AccessibleRole::ListItem)
            && item.accessible_item_selected() == Some(true)
    })
    .expect("screen readers must identify the selected game");
    assert_eq!(
        accessible_selection.accessible_item_index(),
        Some(selected_index)
    );
    accessible_selection.invoke_accessible_default_action();
    assert_eq!(window.get_selected_index() as usize, selected_index);
    let offscreen_index = (selected_index + 6) % 12;
    let offscreen_selection = i_slint_backend_testing::ElementHandle::find_by_accessible_label(
        &window,
        window
            .get_games()
            .row_data(offscreen_index)
            .unwrap()
            .title
            .as_str(),
    )
    .find(|item| {
        item.accessible_role() == Some(i_slint_backend_testing::AccessibleRole::ListItem)
            && item.accessible_item_index() == Some(offscreen_index)
    })
    .expect("screen readers must reach games outside the rendered rows");
    offscreen_selection.invoke_accessible_default_action();
    assert_eq!(window.get_selected_index() as usize, offscreen_index);
    assert_eq!(offscreen_selection.accessible_item_selected(), Some(true));
    assert_eq!(accessible_selection.accessible_item_selected(), Some(false));
    window.set_selected_index(selected_index as i32);
    let detail_cover_deadline = Instant::now() + Duration::from_secs(10);
    while window.get_selected_cover().size().width == 0 {
        events
            .recv_timeout(detail_cover_deadline.saturating_duration_since(Instant::now()))
            .expect("the detail cover must reload after changing the selected game")();
    }
    let list_position = accessible_list.absolute_position();
    let list_size = accessible_list.size();
    let list_center = slint::LogicalPosition::new(
        list_position.x + list_size.width / 2.0,
        list_position.y + list_size.height / 2.0,
    );
    for _ in 0..2 {
        window
            .window()
            .dispatch_event(slint::platform::WindowEvent::PointerScrolled {
                position: list_center,
                delta_x: 0.0,
                delta_y: -12.0,
            });
    }
    assert_eq!(
        window.get_selected_index() as usize,
        (selected_index + 1) % 12
    );
    window
        .window()
        .dispatch_event(slint::platform::WindowEvent::PointerScrolled {
            position: list_center,
            delta_x: 0.0,
            delta_y: 24.0,
        });
    assert_eq!(window.get_selected_index() as usize, selected_index);
    assert_eq!(selected_row.title, "2 mundos");
    assert!(!selected_row.list_is_logo);
    let original_image_width = selected_row.list_image.size().width;
    assert!(original_image_width > 0);
    assert!(selected_row.cover_image.size().width > 0);
    assert!(selected_row.cover_image.size().width <= 240);
    window.invoke_search_changed("2".into());
    assert_eq!(window.get_games().row_count(), 1);
    assert_eq!(
        window
            .get_games()
            .row_data(0)
            .unwrap()
            .list_image
            .size()
            .width,
        original_image_width
    );
    window.invoke_search_changed("".into());
    assert_eq!(window.get_games().row_count(), 12);
    let detail_cover_deadline = Instant::now() + Duration::from_secs(10);
    while window.get_selected_cover().size().width == 0 {
        events
            .recv_timeout(detail_cover_deadline.saturating_duration_since(Instant::now()))
            .expect("the detail cover must reload after restoring the library")();
    }
    snapshot(&adapter, &root, "list-small-default", 800, 600);
    let resized_cover_deadline = Instant::now() + Duration::from_secs(10);
    while window.get_selected_cover().size().width == 0 {
        events
            .recv_timeout(resized_cover_deadline.saturating_duration_since(Instant::now()))
            .expect("the resized detail cover must reach the UI")();
    }
    snapshot(&adapter, &root, "list-small-default", 800, 600);
    adapter.set_size(slint::PhysicalSize::new(1280, 800));
    window.set_session_title(selected_row.title.clone());
    window.set_session_cover(selected_row.cover_image.clone());
    assert_eq!(window.get_launch_eased_progress(), 0.0);
    window.set_launching_game(true);
    for (step, expected) in [(70, 0.0625), (70, 0.5), (70, 0.9375), (70, 1.0)] {
        TEST_TIME.fetch_add(step, std::sync::atomic::Ordering::Relaxed);
        slint::platform::update_timers_and_animations();
        assert!((window.get_launch_eased_progress() - expected).abs() < 0.001);
    }
    assert!(!window.get_library_active());
    window.set_game_session_active(true);
    window.set_launching_game(false);
    slint::platform::update_timers_and_animations();
    assert_eq!(window.get_launch_eased_progress(), 0.0);
    assert!(!window.get_library_active());
    window.set_search_query("keep".into());
    window.set_focus_library_request(false);
    window
        .window()
        .dispatch_event(slint::platform::WindowEvent::KeyPressed {
            text: slint::platform::Key::Escape.into(),
        });
    assert_eq!(window.get_search_query(), "keep");
    assert!(!window.get_focus_library_request());
    window.set_search_query("".into());
    handle_action(&window, "right");
    assert_eq!(window.get_selected_index() as usize, selected_index);
    window.set_selected_index((selected_index + 1) as i32);
    assert_eq!(window.get_session_title(), "2 mundos");
    snapshot(&adapter, &root, "playing-screen", 1280, 800);
    snapshot(&adapter, &root, "playing-screen-small", 800, 600);
    window.set_selected_index(selected_index as i32);
    adapter.set_size(slint::PhysicalSize::new(1280, 800));
    window.set_game_session_active(false);
    assert!(window.get_library_active());
    window.invoke_preview_screensaver();
    let screensaver_deadline = Instant::now() + Duration::from_secs(10);
    while !window.get_screensaver_active() || window.get_screensaver_image().size().width == 0 {
        assert!(
            Instant::now() < screensaver_deadline,
            "screensaver image must load"
        );
        TEST_TIME.fetch_add(20, std::sync::atomic::Ordering::Relaxed);
        slint::platform::update_timers_and_animations();
        while let Ok(event) = events.try_recv() {
            event();
        }
        std::thread::sleep(Duration::from_millis(1));
    }
    assert_eq!(window.get_screensaver_image().size().width, 1280);
    window.invoke_dismiss_screensaver();
    assert!(!window.get_screensaver_active());
    window.set_screensaver_image(slint::Image::default());
    window.set_screensaver_dim(0);
    window.set_screensaver_active(true);
    let mut screensaver_fallback = slint::SharedPixelBuffer::<slint::Rgb8Pixel>::new(1280, 800);
    adapter.request_redraw();
    assert!(adapter.draw_if_needed(|renderer| {
        renderer.render(screensaver_fallback.make_mut_slice(), 1280);
    }));
    let fallback_pixel = (100 * 1280 + 100) * 3;
    assert_eq!(
        &screensaver_fallback.as_bytes()[fallback_pixel..fallback_pixel + 3],
        &[21, 21, 21],
        "the screensaver must use Qt's #151515 fallback when artwork is unavailable"
    );
    window.set_screensaver_active(false);
    window.set_screensaver_dim(35);
    window.set_search_query("2 mundos".into());
    window.invoke_search_changed("2 mundos".into());
    assert_eq!(window.get_games().row_count(), 1);
    assert_eq!(
        window
            .get_games()
            .row_data(0)
            .unwrap()
            .list_image
            .size()
            .width,
        original_image_width,
        "Filtering must keep the selected artwork visible"
    );
    window.set_search_query("".into());
    window.invoke_search_changed("".into());
    assert!(
        window
            .get_games()
            .row_data(window.get_selected_index() as usize)
            .unwrap()
            .list_image
            .size()
            .width
            > 0,
        "Restoring the library must reuse artwork for the retained selection"
    );
    window.set_search_query("2 mundos".into());
    window.invoke_search_changed("2 mundos".into());
    handle_action(&window, "back");
    assert!(
        window.get_search_query().is_empty(),
        "gamepad Back clears search"
    );
    window.set_search_query("2 mundos".into());
    window.invoke_search_changed("2 mundos".into());
    press_control_shortcut(&window, "f");
    assert!(window.get_text_input_focused());
    send_key(&window, slint::platform::Key::Escape, false);
    slint::platform::update_timers_and_animations();
    assert!(window.get_search_query().is_empty());
    assert_eq!(window.get_games().row_count(), 12);
    assert!(!window.get_text_input_focused());
    window.set_focus_zoom(250);
    slint::platform::update_timers_and_animations();
    while window
        .get_games()
        .row_data(selected_index)
        .unwrap()
        .list_image
        .size()
        .width
        == original_image_width
    {
        events
            .recv_timeout(deadline.saturating_duration_since(Instant::now()))
            .expect("zoomed list artwork must reach the UI")();
    }
    let zoomed_image_width = window
        .get_games()
        .row_data(selected_index)
        .unwrap()
        .list_image
        .size()
        .width;
    assert!(zoomed_image_width > original_image_width);
    window.set_focus_zoom(150);
    slint::platform::update_timers_and_animations();
    while window
        .get_games()
        .row_data(selected_index)
        .unwrap()
        .list_image
        .size()
        .width
        != original_image_width
    {
        events
            .recv_timeout(deadline.saturating_duration_since(Instant::now()))
            .expect("restored list artwork size must reach the UI")();
    }
    for side in ["left", "right", "top", "bottom"] {
        window.set_list_side(side.into());
        snapshot(&adapter, &root, side, 1280, 800);
    }
    window.set_list_side("left".into());
    slint::platform::update_timers_and_animations();
    snapshot(&adapter, &root, "list-dragging-start", 1280, 800);
    let drag_start_index = window.get_selected_index();
    let drag_start = slint::LogicalPosition::new(220., 380.);
    let drag_end = slint::LogicalPosition::new(220., 460.);
    use slint::platform::{PointerEventButton, WindowEvent};
    window.window().dispatch_event(WindowEvent::PointerMoved {
        position: drag_start,
    });
    window.window().dispatch_event(WindowEvent::PointerPressed {
        position: drag_start,
        button: PointerEventButton::Left,
    });
    window
        .window()
        .dispatch_event(WindowEvent::PointerMoved { position: drag_end });
    slint::platform::update_timers_and_animations();
    assert_eq!(
        window.get_selected_index(),
        drag_start_index,
        "dragging should move the path without committing selection yet"
    );
    snapshot(&adapter, &root, "list-dragging", 1280, 800);
    window
        .window()
        .dispatch_event(WindowEvent::PointerReleased {
            position: drag_end,
            button: PointerEventButton::Left,
        });
    slint::platform::update_timers_and_animations();
    assert_eq!(
        window.get_selected_index(),
        (drag_start_index - 1).rem_euclid(window.get_games().row_count() as i32),
        "release should commit the closest dragged game"
    );
    let selected = window
        .get_games()
        .iter()
        .position(|row| row.id == game_id)
        .unwrap();
    window.set_selected_index(selected as i32);
    window.set_cover_format("square".into());
    let games = window.get_games();
    let rows = games.as_any().downcast_ref::<VecModel<GameRow>>().unwrap();
    let mut row = rows.row_data(selected).unwrap();
    row.cover_image = Image::default();
    row.square_cover_image = Image::default();
    rows.set_row_data(selected, row);
    window.invoke_play_selected();
    assert_eq!(window.get_session_cover().size().width, 0);
    let other = (selected + 1) % rows.row_count();
    window.set_selected_index(other as i32);
    window.invoke_selection_changed(other as i32);
    window.set_selected_index(selected as i32);
    window.invoke_selection_changed(selected as i32);
    let cover_deadline = Instant::now() + Duration::from_secs(10);
    while window.get_session_cover().size().width == 0 {
        events
            .recv_timeout(cover_deadline.saturating_duration_since(Instant::now()))
            .expect("la portada de la partida debe llegar del worker")();
    }
    assert!(window.get_launching_game());
    assert!(
        window.get_game_session_active(),
        "{}",
        window.get_save_message()
    );
    handle_library_action(&window, "exit", false);
    assert!(
        window.get_save_message().contains("espera a que termine")
            || window.get_save_message().contains("wait for it to finish"),
        "controller exit must respect the active game session: {}",
        window.get_save_message()
    );
    snapshot(&adapter, &root, "launch-transition", 1280, 800);
    let deadline = Instant::now() + Duration::from_secs(12);
    while window.get_game_session_active() {
        assert!(Instant::now() < deadline, "temporary game did not finish");
        thread::sleep(Duration::from_millis(25));
        TEST_TIME.fetch_add(25, std::sync::atomic::Ordering::Relaxed);
        slint::platform::update_timers_and_animations();
    }
    assert!(!window.get_launching_game());
    let library = Library::open(&root);
    assert_eq!(library.session_count(&game_id), 1);
    assert_eq!(window.get_selected_index(), selected as i32);
    window.set_cover_format("portrait".into());
    window.set_showing_settings(true);
    window.set_settings_section(3);
    snapshot(&adapter, &root, "scan", 1280, 800);
    window.set_settings_section(1);
    snapshot(&adapter, &root, "list-settings", 1280, 800);
    let close = i_slint_backend_testing::ElementHandle::find_by_accessible_label(&window, "Close")
        .next()
        .expect("settings should expose its close button");
    assert!(close.absolute_position().y > 680.);
    for label in ["Save appearance", "Guardar apariencia"] {
        assert!(
            i_slint_backend_testing::ElementHandle::find_by_accessible_label(&window, label)
                .next()
                .is_none(),
            "settings should not expose a Save button ({label})"
        );
    }
    snapshot(&adapter, &root, "list-settings-tall", 1232, 1404);
    adapter.set_size(slint::PhysicalSize::new(1280, 800));
    window.set_list_side("bottom".into());
    assert_eq!(window.get_settings_focus_target(), -1);
    window.invoke_focus_settings_sidebar();
    slint::platform::update_timers_and_animations();
    assert!(window.get_settings_sidebar_focused());
    handle_action(&window, "right");
    slint::platform::update_timers_and_animations();
    assert_eq!(window.get_settings_focus_target(), 0);
    assert!(!window.get_settings_sidebar_focused());
    let position_header_y = window.get_settings_focus_y();
    handle_action(&window, "confirm");
    handle_action(&window, "down");
    assert_eq!(window.get_settings_focus_target(), 0);
    assert_ne!(
        window.get_settings_focus_y(),
        position_header_y,
        "tab navigation should focus and report the radio option"
    );
    handle_action(&window, "confirm");
    assert_eq!(window.get_list_side(), "left");
    for (direction, side) in [
        ("down", "right"),
        ("down", "top"),
        ("down", "bottom"),
        ("up", "top"),
        ("up", "right"),
        ("up", "left"),
    ] {
        handle_action(&window, direction);
        assert_eq!(window.get_settings_focus_target(), 0);
        handle_action(&window, "confirm");
        assert_eq!(window.get_list_side(), side);
    }
    handle_action(&window, "right");
    assert_eq!(window.get_settings_focus_target(), 6);
    handle_action(&window, "left");
    assert_eq!(window.get_settings_focus_target(), 0);
    click(&window, 500., 240.);
    for (x, y, expected_target) in [
        (500., 392., 2),
        (500., 468., 3),
        (500., 544., 4),
        (1000., 316., 6),
    ] {
        click(&window, x, y);
        handle_action(&window, "down");
        assert_eq!(
            window.get_settings_focus_target(),
            expected_target,
            "D-pad should reach each expanded settings group"
        );
        click(&window, x, y);
    }
    click(&window, 500., 544.);
    let focus_zoom_slider_label = if window.get_english_ui() {
        "Selected item zoom"
    } else {
        "Ampliación seleccionada"
    };
    window
        .window()
        .dispatch_event(slint::platform::WindowEvent::PointerScrolled {
            position: slint::LogicalPosition::new(1200., 640.),
            delta_x: 0.0,
            delta_y: -600.0,
        });
    slint::platform::update_timers_and_animations();
    let focus_zoom_slider = i_slint_backend_testing::ElementHandle::find_by_accessible_label(
        &window,
        focus_zoom_slider_label,
    )
    .find(|item| item.accessible_role() == Some(i_slint_backend_testing::AccessibleRole::Slider))
    .expect("selected item zoom must expose an accessible slider");
    let old_focus_zoom = window.get_focus_zoom();
    focus_zoom_slider.invoke_accessible_increment_action();
    assert_eq!(window.get_focus_zoom(), old_focus_zoom + 1);
    focus_zoom_slider.invoke_accessible_decrement_action();
    assert_eq!(window.get_focus_zoom(), old_focus_zoom);
    click(&window, 150., 288.);
    click(&window, 500., 544.);
    click(&window, 500., 316.);
    handle_action(&window, "down");
    assert_eq!(window.get_settings_focus_target(), 1);
    assert!(window.get_settings_slider_focused());
    snapshot(&adapter, &root, "background-controls", 1280, 800);
    let old_dim = window.get_dim();
    click(&window, 634., 389.);
    assert_ne!(
        window.get_dim(),
        old_dim,
        "The dimming slider must respond to pointer input"
    );
    assert!(window.get_settings_slider_focused());
    let dim_before_gamepad = window.get_dim();
    handle_action(&window, "confirm");
    assert!(window.get_settings_slider_adjusting());
    handle_action(&window, "left");
    assert_eq!(window.get_dim(), dim_before_gamepad - 1);
    snapshot(&adapter, &root, "gamepad-slider-adjusting", 1280, 800);
    handle_action(&window, "back");
    assert!(!window.get_settings_slider_adjusting());
    handle_action(&window, "left");
    assert!(!window.get_settings_slider_focused());
    click(&window, 1000., 390.);
    snapshot(&adapter, &root, "covers-controls", 1280, 800);
    let logo_label = if window.get_english_ui() {
        "Logo"
    } else {
        "Logotipo"
    };
    let logo_radio =
        i_slint_backend_testing::ElementHandle::find_by_accessible_label(&window, logo_label)
            .find(|item| {
                item.accessible_role() == Some(i_slint_backend_testing::AccessibleRole::RadioButton)
            })
            .expect("the details-cover settings should expose a Logo option");
    logo_radio.invoke_accessible_default_action();
    assert_eq!(window.get_cover_format(), "logo");
    window.set_cover_format("square".into());
    click(&window, 634., 389.);
    window.set_settings_focus_y(240.);
    handle_action(&window, "right");
    assert_eq!(window.get_settings_focus_target(), 7);
    assert!(!window.get_settings_slider_focused());
    handle_action(&window, "confirm");
    assert_eq!(window.get_cover_format(), "portrait");
    click(&window, 1000., 390.);
    click(&window, 1000., 468.);
    click(&window, 634., 389.);
    assert!(window.get_settings_slider_focused());
    assert_eq!(window.get_settings_focus_target(), 1);
    window.set_settings_focus_y(600.);
    handle_action(&window, "right");
    snapshot(&adapter, &root, "ring-spatial-focus", 1280, 800);
    assert_eq!(window.get_settings_focus_target(), 8);
    assert!(
        window.get_settings_slider_focused(),
        "horizontal navigation must focus the nearest slider in an expanded group (focus y: {})",
        window.get_settings_focus_y()
    );
    assert_ne!(window.get_settings_focus_y(), 600.);
    let ring_before = window.get_ring_enabled();
    click(&window, 850., 497.);
    assert_ne!(window.get_ring_enabled(), ring_before);
    snapshot(&adapter, &root, "selection-ring-control", 1280, 800);
    let launcher_details_before = window.get_launcher_details();
    click(&window, 150., 288.);
    click(&window, 1000., 240.);
    handle_action(&window, "down");
    assert_eq!(window.get_settings_focus_target(), 5);
    handle_action(&window, "confirm");
    assert_eq!(window.get_launcher_details(), !launcher_details_before);
    snapshot(&adapter, &root, "launcher-details-control", 1280, 800);
    let launcher_details_focus_y = window.get_settings_focus_y();
    handle_action(&window, "down");
    assert_eq!(window.get_settings_focus_target(), 5);
    assert!(window.get_settings_focus_y() > launcher_details_focus_y);
    handle_action(&window, "confirm");
    assert!(!window.get_show_game_information());
    assert!(
        !window.get_minimal(),
        "the hidden card must not imply minimal presentation"
    );
    let selected_game = window
        .get_games()
        .row_data(window.get_selected_index() as usize)
        .unwrap();
    assert!(
        selected_game.cover_path != "" || selected_game.square_cover_path != "",
        "the selected game must still have a cover while its information is hidden"
    );
    snapshot(&adapter, &root, "game-information-hidden", 1280, 800);
    handle_action(&window, "save");
    assert_eq!(
        Library::open(&root).settings().unwrap()["show_game_information"]["list"],
        false
    );
    window.set_showing_settings(false);
    slint::platform::update_timers_and_animations();
    snapshot(&adapter, &root, "game-information-hidden", 1280, 800);
    window.set_show_game_information(true);
    window.set_showing_settings(true);
    window.set_settings_section(1);
    handle_action(&window, "save");
    let minimal_before = window.get_minimal();
    let presentation_label = if window.get_english_ui() {
        "Presentation"
    } else {
        "Presentación"
    };
    let presentation = i_slint_backend_testing::ElementHandle::find_by_accessible_label(
        &window,
        presentation_label,
    )
    .next()
    .expect("settings should expose the presentation group");
    presentation.invoke_accessible_default_action();
    let minimal_label = if window.get_english_ui() {
        "Minimal presentation"
    } else {
        "Presentación mínima"
    };
    let minimal =
        i_slint_backend_testing::ElementHandle::find_by_accessible_label(&window, minimal_label)
            .next()
            .expect("settings should expose the minimal presentation control");
    minimal.invoke_accessible_default_action();
    assert_eq!(window.get_minimal(), !minimal_before);
    snapshot(&adapter, &root, "minimal-presentation-control", 1280, 800);
    window.set_settings_section(2);
    window.set_category_edit_index(1);
    slint::platform::update_timers_and_animations();
    window.invoke_refresh_members();
    let member = window.get_category_members().row_data(0).unwrap();
    let category = window.get_managed_category();
    window.invoke_manage_category(
        if member.checked { "leave" } else { "join" }.into(),
        category.clone(),
        member.id.clone(),
    );
    let updated = Library::open(&root)
        .games()
        .into_iter()
        .find(|g| g.id() == member.id.as_str())
        .unwrap();
    assert_eq!(
        updated.categories().contains(&category.to_string()),
        !member.checked
    );
    window.invoke_manage_category(
        if member.checked { "join" } else { "leave" }.into(),
        category.clone(),
        member.id,
    );
    window.invoke_manage_category(
        "icon".into(),
        category.clone(),
        root.join("cover.png").to_str().unwrap().into(),
    );
    assert!(Library::open(&root).category_icon_path(&category).is_some());
    window.invoke_manage_category("clear-icon".into(), category.clone(), "".into());
    window.invoke_manage_category("primary".into(), category, "".into());
    window.invoke_manage_category("primary".into(), "".into(), "".into());
    assert!(Library::open(&root).primary_category().is_none());
    window.set_settings_section(0);
    snapshot(&adapter, &root, "settings", 1280, 800);
    assert_eq!(window.get_language(), "system");
    window.invoke_clear_settings_focus_target();
    handle_action(&window, "right");
    assert_eq!(window.get_settings_focus_target(), 0);
    handle_action(&window, "confirm");
    handle_action(&window, "down");
    handle_action(&window, "confirm");
    assert!(
        window.get_combo_popup_open(),
        "A should open the focused select"
    );
    handle_action(&window, "down");
    assert_eq!(window.get_language(), "es");
    assert!(window.get_combo_popup_open());
    handle_action(&window, "confirm");
    assert_eq!(window.get_language(), "es");
    assert!(!window.get_combo_popup_open());
    handle_action(&window, "confirm");
    assert!(window.get_combo_popup_open());
    handle_action(&window, "right");
    assert_eq!(window.get_language(), "en");
    assert!(window.get_combo_popup_open());
    handle_action(&window, "back");
    assert!(!window.get_combo_popup_open());
    window.set_language("system".into());
    window.set_showing_settings(false);
    window.invoke_begin_edit();
    let original_index = window.get_selected_index();
    let game_count = window.get_games().row_count() as i32;
    assert!(game_count > 1);
    window.set_artwork_game_id("stale-game-id".into());
    window.invoke_cancel_edit();
    window.set_selected_index((original_index + 1).rem_euclid(game_count));
    window.invoke_begin_edit();
    assert!(window.get_artwork_game_id().is_empty());
    assert_eq!(window.get_artwork_query(), window.get_edit_title());
    window.invoke_cancel_edit();
    window.set_selected_index(original_index);
    window.invoke_begin_edit();
    handle_action(&window, "right");
    assert_eq!(window.get_editor_focus_target(), 1);
    handle_action(&window, "down");
    assert_eq!(window.get_editor_focus_target(), 4);
    handle_action(&window, "left");
    assert_eq!(window.get_editor_focus_target(), 3);
    window.set_editor_focus_target(0);
    window.set_editor_focus_serial(window.get_editor_focus_serial().wrapping_add(1));
    snapshot(&adapter, &root, "editor", 1280, 800);
    for (page, name) in [
        ("manual", "editor-manual"),
        ("categories", "editor-categories"),
        ("execution", "editor-execution"),
    ] {
        window.set_editor_page(page.into());
        snapshot(&adapter, &root, name, 1280, 800);
        match page {
            "manual" => {
                assert_eq!(
                    window.get_editor_focus_target(),
                    2,
                    "manual starts on title"
                );
                handle_action(&window, "down");
                assert_eq!(
                    window.get_editor_focus_target(),
                    3,
                    "D-pad moves to next field"
                );
                for _ in 0..6 {
                    handle_action(&window, "down");
                }
                assert_eq!(
                    window.get_editor_focus_target(),
                    9,
                    "D-pad traverses the whole form"
                );
                handle_action(&window, "down");
                assert_eq!(window.get_editor_focus_target(), 10, "D-pad reaches Cancel");
                handle_action(&window, "right");
                assert_eq!(
                    window.get_editor_focus_target(),
                    10,
                    "D-pad must not reach an invisible Save control"
                );
                handle_action(&window, "up");
                assert_eq!(
                    window.get_editor_focus_target(),
                    9,
                    "D-pad returns from Cancel to the final field"
                );
                slint::platform::update_timers_and_animations();
                snapshot(&adapter, &root, "editor-manual-dpad-synopsis", 1280, 800);
                assert!(
                    window.get_text_input_focused(),
                    "the synopsis must receive focus from the D-pad"
                );
                handle_action(&window, "confirm");
                assert!(
                    window.get_keyboard_visible(),
                    "A opens the focused text field"
                );
                handle_action(&window, "back");
                assert!(!window.get_keyboard_visible());
            }
            "categories" => {
                let category_count = window.get_edit_category_choices().row_count();
                assert_eq!(
                    window.get_editor_focus_target(),
                    category_count as i32 + 2,
                    "D-pad starts on Cancel; no Save control is present"
                );
                if category_count > 0 {
                    handle_action(&window, "up");
                    assert_eq!(
                        window.get_editor_focus_target(),
                        category_count as i32 + 1,
                        "D-pad returns from Cancel to the last category"
                    );
                    handle_action(&window, "right");
                    assert_eq!(
                        window.get_editor_focus_target(),
                        category_count as i32 + 2,
                        "D-pad reaches Cancel laterally"
                    );
                    handle_action(&window, "right");
                    assert_eq!(
                        window.get_editor_focus_target(),
                        category_count as i32 + 2,
                        "D-pad must not reach an invisible Save control"
                    );
                }
            }
            "execution" => {
                assert_eq!(
                    window.get_editor_focus_target(),
                    2,
                    "local execution starts on its title"
                );
                handle_action(&window, "down");
                assert_eq!(
                    window.get_editor_focus_target(),
                    3,
                    "D-pad moves to executable path"
                );
                handle_action(&window, "down");
                assert_eq!(
                    window.get_editor_focus_target(),
                    4,
                    "D-pad reaches arguments"
                );
                handle_action(&window, "down");
                assert_eq!(
                    window.get_editor_focus_target(),
                    5,
                    "D-pad reaches working directory"
                );
                handle_action(&window, "down");
                assert_eq!(
                    window.get_editor_focus_target(),
                    6,
                    "D-pad reaches Cancel after the form"
                );
                handle_action(&window, "right");
                assert_eq!(
                    window.get_editor_focus_target(),
                    6,
                    "D-pad must not reach an invisible Save control"
                );
                handle_action(&window, "up");
                assert_eq!(
                    window.get_editor_focus_target(),
                    5,
                    "D-pad returns from Cancel to the last execution field"
                );
            }
            _ => unreachable!(),
        }
    }
    window.set_showing_artwork(false);
    window.set_showing_editor(false);
    window.set_edit_is_local(false);
    window.set_showing_editor(true);
    window.set_editor_page("execution".into());
    snapshot(&adapter, &root, "editor-execution-managed", 1280, 800);
    assert_eq!(
        window.get_editor_focus_target(),
        6,
        "managed game editor focuses Cancel without a Save control"
    );
    window.set_edit_is_local(true);
    window.set_editor_page("overview".into());
    window.set_showing_editor(false);
    window.invoke_focus_search();
    slint::platform::update_timers_and_animations();
    window.set_keyboard_visible(true);
    snapshot(&adapter, &root, "keyboard", 1280, 800);
    window.invoke_type_key("ñ".into());
    handle_action(&window, "page_next");
    handle_action(&window, "page_previous");
    assert!(
        window.get_search_query().is_empty(),
        "Pending keyboard edits must stay in the draft"
    );
    handle_action(&window, "back");
    slint::platform::update_timers_and_animations();
    assert!(window.get_search_query().is_empty());
    window.set_keyboard_visible(true);
    slint::platform::update_timers_and_animations();
    window.invoke_type_key("Portal".into());
    handle_action(&window, "save");
    slint::platform::update_timers_and_animations();
    assert_eq!(window.get_search_query(), "Portal");
    assert_eq!(window.get_games().row_count(), 1);
    window.set_search_query("".into());
    window.invoke_search_changed("".into());
    check_filters_and_editing(&window, &root);
    window.invoke_begin_edit();
    window.set_showing_editor(false);
    window.set_showing_artwork(false);
    window.set_text_input_focused(false);
    window.set_showing_artwork(true);
    slint::platform::update_timers_and_animations();
    assert_eq!(
        window.get_artwork_navigation_target(),
        9,
        "artwork opens on search"
    );
    snapshot(&adapter, &root, "artwork-open-focus", 1280, 800);
    assert!(
        window.get_text_input_focused(),
        "the artwork query receives focus"
    );
    snapshot(&adapter, &root, "artwork-empty", 1280, 800);
    handle_action(&window, "left");
    assert_eq!(
        window.get_artwork_navigation_target(),
        8,
        "left moves from query to provider"
    );
    handle_action(&window, "left");
    assert_eq!(
        window.get_artwork_navigation_target(),
        7,
        "left reaches artwork field"
    );
    handle_action(&window, "right");
    assert_eq!(
        window.get_artwork_navigation_target(),
        8,
        "right returns to provider"
    );
    handle_action(&window, "confirm");
    assert!(
        window.get_combo_popup_open(),
        "A opens the focused artwork select"
    );
    handle_action(&window, "back");
    assert!(!window.get_combo_popup_open());
    let first = ArtworkRequest::start(&window).unwrap();
    assert!(first.matches(&window));
    let second = ArtworkRequest::start(&window).unwrap();
    assert!(
        !first.matches(&window),
        "An older search must not replace a newer one"
    );
    assert!(second.matches(&window));
    window.set_artwork_query("Otra consulta".into());
    assert!(!second.matches(&window));
    snapshot(&adapter, &root, "artwork-query", 1280, 800);
    window.set_artwork_provider("steamgriddb".into());
    assert_eq!(window.get_artwork_result_columns(), 2);
    window.set_artwork_results(ModelRc::new(VecModel::from(vec![
        ArtworkRow {
            name: "Bloodborne".into(),
            preview: Image::default(),
            game_choice: true,
        },
        ArtworkRow {
            name: "Bloodborne Kart".into(),
            preview: Image::default(),
            game_choice: true,
        },
        ArtworkRow {
            name: "Bloodborne: The Old Hunters Edition".into(),
            preview: Image::default(),
            game_choice: true,
        },
    ])));
    window.set_text_input_focused(false);
    window.set_artwork_results_focus_index(0);
    window.set_artwork_results_focus_serial(
        window.get_artwork_results_focus_serial().wrapping_add(1),
    );
    snapshot(&adapter, &root, "artwork-game-choices", 1280, 800);
    handle_action(&window, "right");
    assert_eq!(window.get_artwork_results_focus_index(), 1);
    handle_action(&window, "down");
    assert_eq!(window.get_artwork_results_focus_index(), 2);
    handle_action(&window, "left");
    assert_eq!(window.get_artwork_results_focus_index(), 1);
    handle_action(&window, "up");
    assert_eq!(window.get_artwork_results_focus_index(), -1);
    handle_action(&window, "down");
    assert_eq!(window.get_artwork_results_focus_index(), 0);
    handle_action(&window, "down");
    assert_eq!(window.get_artwork_results_focus_index(), 2);
    handle_action(&window, "down");
    assert_eq!(window.get_artwork_results_focus_index(), -1);
    assert_eq!(
        window.get_artwork_navigation_target(),
        11,
        "last result reaches Back to editor"
    );
    handle_action(&window, "right");
    assert_eq!(
        window.get_artwork_navigation_target(),
        12,
        "footer actions navigate laterally"
    );
    handle_action(&window, "up");
    assert_eq!(
        window.get_artwork_results_focus_index(),
        2,
        "footer returns to last result"
    );

    window.set_artwork_browsing(true);
    window.set_artwork_browser_item_count(5);
    window.set_artwork_browser_columns(3);
    window.set_artwork_navigation_target(3);
    window.set_artwork_browser_toolbar_focus_index(3);
    window.set_artwork_browser_focus_index(-1);
    handle_action(&window, "right");
    assert_eq!(
        window.get_artwork_browser_toolbar_focus_index(),
        4,
        "browser toolbar moves laterally"
    );
    handle_action(&window, "left");
    assert_eq!(window.get_artwork_browser_toolbar_focus_index(), 3);
    handle_action(&window, "down");
    assert_eq!(
        window.get_artwork_browser_focus_index(),
        0,
        "browser toolbar enters the image grid"
    );
    handle_action(&window, "right");
    assert_eq!(window.get_artwork_browser_focus_index(), 1);
    handle_action(&window, "down");
    assert_eq!(window.get_artwork_browser_focus_index(), 4);
    handle_action(&window, "down");
    assert_eq!(
        window.get_artwork_navigation_target(),
        11,
        "browser grid reaches footer actions"
    );
    handle_action(&window, "right");
    assert_eq!(window.get_artwork_navigation_target(), 12);
    handle_action(&window, "up");
    assert_eq!(window.get_artwork_browser_focus_index(), 4);
    window.set_artwork_browsing(false);
    window.set_artwork_results(ModelRc::new(VecModel::from(
        ["Bloodborne 1", "Bloodborne 2", "Bloodborne 3"]
            .into_iter()
            .map(|name| ArtworkRow {
                name: name.into(),
                preview: image(Some(root.join("cover.png").to_str().unwrap())),
                game_choice: false,
            })
            .collect::<Vec<_>>(),
    )));
    window.set_artwork_results_focus_index(0);
    window.set_artwork_results_focus_serial(
        window.get_artwork_results_focus_serial().wrapping_add(1),
    );
    snapshot(&adapter, &root, "artwork-preview", 1280, 800);
    let changed_game = ArtworkRequest::start(&window).unwrap();
    window.set_edit_id("local:different".into());
    assert!(!changed_game.matches(&window));
    window.invoke_back();
    slint::platform::update_timers_and_animations();
    assert!(!changed_game.matches(&window));
    assert!(window.get_showing_editor());
    assert_eq!(window.get_artwork_results().row_count(), 0);
    window.set_showing_editor(false);
    window.set_showing_artwork(true);
    snapshot(&adapter, &root, "artwork-close-button", 1280, 800);
    click(&window, 1244., 36.);
    assert!(!window.get_showing_artwork());
    assert!(!window.get_showing_editor());
    window.set_showing_activity(true);
    let games = window.get_games();
    let rows = games.as_any().downcast_ref::<VecModel<GameRow>>().unwrap();
    let history = (0..60)
        .map(|index| format!("Sesión {index:02} · 2025-01-01 · 60 min · salida 0"))
        .collect::<Vec<_>>()
        .join("\n");
    for index in 0..rows.row_count() {
        let mut game = rows.row_data(index).unwrap();
        game.activity_history = history.clone().into();
        rows.set_row_data(index, game);
    }
    let activity_index = window.get_selected_index() as usize;
    assert_eq!(
        rows.row_data(activity_index)
            .unwrap()
            .activity_history
            .as_str(),
        history
    );
    slint::platform::update_timers_and_animations();
    let render = || {
        let mut pixels = slint::SharedPixelBuffer::<slint::Rgb8Pixel>::new(1280, 800);
        adapter.request_redraw();
        assert!(adapter.draw_if_needed(|renderer| {
            renderer.render(pixels.make_mut_slice(), 1280);
        }));
        pixels.as_bytes().to_vec()
    };
    snapshot(&adapter, &root, "activity-back-button", 1280, 800);
    let before_scroll = render();
    let title_visible = (26..50).any(|y| {
        (700..820).any(|x| {
            let pixel = (y * 1280 + x) * 3;
            before_scroll[pixel..pixel + 3]
                .iter()
                .all(|channel| *channel > 180)
        })
    });
    assert!(
        title_visible,
        "the activity title must remain visible above history"
    );
    window
        .window()
        .dispatch_event(slint::platform::WindowEvent::PointerScrolled {
            position: slint::LogicalPosition::new(900., 420.),
            delta_x: 0.0,
            delta_y: -600.0,
        });
    slint::platform::update_timers_and_animations();
    let after_scroll = render();
    snapshot(&adapter, &root, "activity-scrolled", 1280, 800);
    let header_bytes = 1280 * 96 * 3;
    assert_eq!(
        &before_scroll[..header_bytes],
        &after_scroll[..header_bytes],
        "scrolling session history must keep the activity header fixed"
    );
    assert!(
        before_scroll != after_scroll,
        "the session history should scroll when it exceeds the activity panel"
    );
    let first_row_changed = (234..258).any(|y| {
        (660..850).any(|x| {
            let pixel = (y * 1280 + x) * 3;
            before_scroll[pixel..pixel + 3] != after_scroll[pixel..pixel + 3]
        })
    });
    assert!(
        first_row_changed,
        "scrolling must reveal different session entries, not just move the scrollbar"
    );
    click(&window, 678., 36.);
    assert!(!window.get_showing_activity());
    assert!(window.get_showing_editor());
    window.set_showing_editor(false);
    window.set_showing_activity(true);
    snapshot(&adapter, &root, "activity-close-button", 1280, 800);
    click(&window, 1244., 36.);
    assert!(!window.get_showing_activity());
    assert!(!window.get_showing_editor());
    window.invoke_begin_edit();
    window.set_confirming_remove(true);
    window.set_edit_title("No debe guardarse".into());
    slint::platform::update_timers_and_animations();
    let confirming_game_id = window.get_edit_id().to_string();
    assert_ne!(
        Library::open(&root)
            .games()
            .into_iter()
            .find(|game| game.id() == confirming_game_id)
            .unwrap()
            .metadata()["title"],
        "No debe guardarse",
        "confirming a removal must prevent editor autosave"
    );
    assert!(window.get_showing_editor());
    window.invoke_back();
    assert!(!window.get_confirming_remove());
    window.invoke_back();
    // Exercise the actual toolbar hit target, after restoring its library state.
    window.set_showing_settings(false);
    snapshot(&adapter, &root, "library-restored", 1280, 800);
    window.set_controller_input_active(true);
    click(&window, 392., 748.);
    assert!(
        window.get_showing_settings(),
        "The toolbar must open appearance settings"
    );
    assert!(
        !window.get_controller_input_active(),
        "mouse use on the toolbar must switch the hints back to mouse and keyboard"
    );
    let original_language = window.get_language();
    let original_controller_type = window.get_controller_type();
    window.set_language("en".into());
    window.set_controller_input_active(true);
    window.set_controller_type("nintendo".into());
    assert!(
        !window
            .get_settings_input_hint()
            .to_ascii_lowercase()
            .contains("save")
    );
    window.set_controller_type("xbox".into());
    assert!(
        !window
            .get_settings_input_hint()
            .to_ascii_lowercase()
            .contains("save")
    );
    window.set_controller_input_active(false);
    assert!(
        !window
            .get_settings_input_hint()
            .to_ascii_lowercase()
            .contains("save")
    );
    window.set_language(original_language);
    window.set_controller_type(original_controller_type);
    assert_eq!(window.get_color_theme().as_str(), "default");
    let ui_color_mode_before_edit = ui_settings_snapshot(&window)["ui_color_mode"].clone();
    let persisted_before_edit = Library::open(&root).settings().unwrap();
    let mut external_settings = persisted_before_edit.clone();
    external_settings["language"] = json!("en");
    external_settings["background_dim"]["grid"] = json!(33);
    Library::save_settings_at(&root, &external_settings).unwrap();
    window.set_color_theme("combination-176".into());
    slint::platform::update_timers_and_animations();
    assert_eq!(
        Library::open(&root).settings().unwrap()["ui_theme"],
        "combination-176",
        "changing a setting should persist before closing Settings"
    );
    let color_theme_snapshot = ui_settings_snapshot(&window);
    assert_eq!(color_theme_snapshot["ui_theme"], "combination-176");
    assert_eq!(
        color_theme_snapshot["ui_color_mode"],
        ui_color_mode_before_edit
    );
    window.set_focus_zoom(180);
    window.set_list_side("top".into());
    window.set_dim(61);
    window.set_blur(13);
    window.set_hero_position("lower".into());
    window.set_background_split("diagonal".into());
    window.set_minimal(true);
    window.set_launcher_details(false);
    window.set_cover_format("square".into());
    window.set_cover_radius(17);
    window.set_cover_zoom(123);
    window.set_ring_enabled(false);
    window.set_ring_color_text("#80402010".into());
    window.set_ring_width(5);
    window.set_ring_radius(23);
    slint::platform::update_timers_and_animations();
    window.set_settings_section(2);
    window.set_category_name("Temporal".into());
    window.invoke_manage_category("add".into(), "Temporal".into(), "".into());
    assert!(
        window
            .get_categories()
            .iter()
            .any(|category| category.as_str() == "Temporal")
    );
    let library_before_close = Library::open(&root);
    let games_before_close = library_before_close.games();
    let categories_before_close = library_before_close.categories(&games_before_close);
    assert!(
        categories_before_close
            .iter()
            .any(|category| category == "Temporal")
    );
    window.invoke_back();
    assert!(!window.get_showing_settings());
    assert_eq!(window.get_color_theme().as_str(), "combination-176");
    assert_eq!(window.get_focus_zoom(), 180);
    assert_eq!(window.get_list_side().as_str(), "top");
    assert_eq!(window.get_dim(), 61);
    assert_eq!(window.get_blur(), 13);
    assert_eq!(window.get_hero_position().as_str(), "lower");
    assert_eq!(window.get_background_split().as_str(), "diagonal");
    assert!(window.get_minimal());
    assert!(!window.get_ring_enabled());
    assert_eq!(window.get_ring_color_text().as_str(), "#80402010");
    let saved_settings = Library::open(&root).settings().unwrap();
    assert_eq!(
        saved_settings["list_zoom"],
        persisted_before_edit["list_zoom"]
    );
    assert_eq!(saved_settings["list_focus_zoom"], 180);
    assert_eq!(saved_settings["list_side"], "top");
    assert_eq!(saved_settings["background_dim"]["list"], 61);
    assert_eq!(saved_settings["background_blur"]["list"], 13);
    assert_eq!(saved_settings["hero_positions"]["list"], "lower");
    assert_eq!(saved_settings["background_splits"]["list"], "diagonal");
    assert_eq!(saved_settings["minimal_views"]["list"], true);
    assert_eq!(saved_settings["show_launcher_details"]["list"], false);
    assert_eq!(saved_settings["cover_formats"]["list"], "square");
    assert_eq!(saved_settings["cover_radii"]["list"], 17);
    assert_eq!(saved_settings["list_cover_zoom"], 123);
    assert_eq!(
        saved_settings["selection_rings"]["list"]["focus_ring_enabled"],
        false
    );
    assert_eq!(
        saved_settings["selection_rings"]["list"]["focus_ring_color"],
        "#80402010"
    );
    assert_eq!(
        saved_settings["selection_rings"]["list"]["focus_ring_width"],
        5
    );
    assert_eq!(
        saved_settings["selection_rings"]["list"]["focus_ring_radius"],
        23
    );
    assert_eq!(saved_settings["language"], "en");
    assert_eq!(saved_settings["ui_theme"], "combination-176");
    assert_eq!(
        saved_settings.get("ui_color_mode"),
        persisted_before_edit.get("ui_color_mode")
    );
    assert_eq!(saved_settings["background_dim"]["grid"], 33);
    window.set_cover_format("logo".into());
    assert_eq!(
        Library::open(&root).settings().unwrap()["cover_formats"]["list"],
        "logo",
        "the Logo details-cover format should persist as soon as it changes"
    );
    window.set_color_theme("default".into());
    assert_eq!(
        Library::open(&root).settings().unwrap()["ui_theme"],
        "default"
    );
    window.invoke_back();
    window.set_settings_section(2);
    window.set_picking_category_icon(true);
    window.set_showing_artwork(true);
    window.set_artwork_browsing(false);
    window.invoke_back();
    assert!(window.get_showing_settings());
    assert!(!window.get_showing_artwork());
    assert!(!window.get_picking_category_icon());
    window.invoke_back();
    window.set_save_message("".into());
    for (name, width, height) in [("small", 800, 600), ("wide", 1920, 1080)] {
        snapshot(&adapter, &root, name, width, height);
        wait_for_visible_row_images(&window, &events);
        snapshot(&adapter, &root, name, width, height);
    }
    snapshot(&adapter, &root, "dock-alphabet", 1280, 800);
    let initial = window.get_letter_index();
    let initials = window.get_letters().row_count() as i32;
    click(&window, 544., 748.);
    assert_eq!(
        window.get_letter_index(),
        (initial - 1).rem_euclid(initials)
    );
    click(&window, 586., 748.);
    assert_eq!(window.get_letter_index(), initial);

    snapshot(&adapter, &root, "dock-compact", 800, 600);
    window.invoke_focus_library();
    handle_action(&window, "confirm");
    slint::platform::update_timers_and_animations();
    assert!(window.get_gamepad_toolbar_focus());
    assert_eq!(window.get_gamepad_toolbar_index(), 0);
    for expected in [1, 2, 3, 5, 6, 7, 8, 9] {
        handle_action(&window, "right");
        slint::platform::update_timers_and_animations();
        assert_eq!(window.get_gamepad_toolbar_index(), expected);
    }
    handle_action(&window, "up");
    assert!(!window.get_gamepad_toolbar_focus());
    window.invoke_focus_search();
    slint::platform::update_timers_and_animations();
    assert_eq!(window.get_gamepad_toolbar_index(), 5);
    window.invoke_focus_dock_entry();
    slint::platform::update_timers_and_animations();
    assert_eq!(window.get_gamepad_toolbar_index(), 0);
    window.invoke_focus_library();
    window.invoke_search_changed("Portal revisado".into());
    assert_eq!(window.get_games().row_count(), 1);
    window.set_selected_index(0);
    window.invoke_begin_edit();
    window.set_edit_title("Borrador descartado".into());
    snapshot(&adapter, &root, "editor-close-button", 1280, 800);
    click(&window, 1244., 36.);
    assert!(!window.get_showing_editor());
    assert_eq!(
        Library::open(&root)
            .games()
            .into_iter()
            .find(|game| game.title() == "Portal")
            .unwrap()
            .metadata()["title"],
        "Cambio externo"
    );
    window.invoke_begin_edit();
    let removed_id = window.get_edit_id().to_string();
    snapshot(&adapter, &root, "editor-before-remove", 1280, 800);
    click(&window, 1100., 656.);
    assert!(window.get_confirming_remove());
    snapshot(&adapter, &root, "remove-confirmation", 1280, 800);
    assert!(
        Library::open(&root)
            .games()
            .iter()
            .any(|game| game.id() == removed_id)
    );
    window.window().dispatch_event(WindowEvent::KeyPressed {
        text: slint::platform::Key::RightArrow.into(),
    });
    assert_eq!(window.get_remove_focus_index(), 1);
    window.window().dispatch_event(WindowEvent::KeyPressed {
        text: slint::platform::Key::LeftArrow.into(),
    });
    assert_eq!(window.get_remove_focus_index(), 0);
    send_key(&window, slint::platform::Key::Tab, false);
    assert_eq!(window.get_remove_focus_index(), 1);
    send_key(&window, slint::platform::Key::Tab, true);
    assert_eq!(window.get_remove_focus_index(), 0);
    handle_action(&window, "confirm");
    assert!(!window.get_confirming_remove());
    assert!(
        Library::open(&root)
            .games()
            .iter()
            .any(|game| game.id() == removed_id)
    );
    click(&window, 1100., 656.);
    assert!(window.get_confirming_remove());
    click(&window, 866., 365.);
    assert!(!window.get_confirming_remove());
    assert!(
        Library::open(&root)
            .games()
            .iter()
            .any(|game| game.id() == removed_id)
    );
    click(&window, 1100., 656.);
    assert!(window.get_confirming_remove());
    handle_action(&window, "right");
    snapshot(&adapter, &root, "remove-gamepad-right", 1280, 800);
    handle_action(&window, "confirm");
    assert!(
        !Library::open(&root)
            .games()
            .iter()
            .any(|game| game.id() == removed_id)
    );
    assert!(!window.get_showing_editor());
    assert_eq!(window.get_games().row_count(), 0);
    handle_action(&window, "confirm");
    assert!(window.get_showing_settings());
    assert_eq!(
        window.get_settings_section(),
        3,
        "confirming with an empty library must open the scan/import section, as in Qt"
    );
    window.invoke_back();
    window.set_showing_artwork(true);
    slint::platform::update_timers_and_animations();
    window.set_artwork_importing(true);
    window.set_showing_artwork(false);
    slint::platform::update_timers_and_animations();
    assert!(!window.get_artwork_importing());
    window.hide().unwrap();
    eprintln!("Slint snapshots: {}", root.display());
}

fn assert_no_editor_save_buttons(window: &ListWindow) {
    for label in ["Save", "Save categories", "Guardar", "Guardar categorías"] {
        assert!(
            i_slint_backend_testing::ElementHandle::find_by_accessible_label(window, label)
                .next()
                .is_none(),
            "the game editor should not expose a Save button ({label})"
        );
    }
}

fn check_filters_and_editing(window: &ListWindow, root: &Path) {
    macro_rules! edit_and_flush {
        ($change:expr) => {{
            $change;
            slint::platform::update_timers_and_animations();
        }};
    }
    assert!(!window.get_letters().iter().any(|letter| letter == "Todos"));
    window.invoke_letter_changed("P".into());
    assert_eq!(
        window.get_games().row_count(),
        12,
        "Letters jump without filtering"
    );
    assert_eq!(
        window
            .get_games()
            .row_data(window.get_selected_index() as usize)
            .unwrap()
            .title,
        "Portal"
    );
    window.invoke_search_changed("arbol".into());
    assert_eq!(window.get_games().row_count(), 1);
    assert_eq!(
        window.get_games().row_data(0).unwrap().title,
        "Árbol del tiempo"
    );
    window.invoke_search_changed("".into());
    assert_eq!(
        window
            .get_games()
            .row_data(window.get_selected_index() as usize)
            .unwrap()
            .title,
        "Árbol del tiempo"
    );
    window.invoke_category_changed("Aventura".into());
    assert_eq!(window.get_games().row_count(), 6);
    window.invoke_category_changed("Todos".into());
    window.invoke_letter_changed("P".into());
    click(window, 190., 748.);
    assert!(window.get_showing_editor());
    slint::platform::update_timers_and_animations();
    assert_eq!(window.get_editor_page(), "overview");
    let edit_id = window.get_edit_id().to_string();
    let index = window.get_selected_index();
    handle_action(window, "right");
    handle_action(window, "play");
    assert_eq!(
        window.get_selected_index(),
        index,
        "Modal navigation must not move the library"
    );
    edit_and_flush!(window.set_edit_title("Portal revisado".into()));
    let saved_title = Library::open(root)
        .games()
        .into_iter()
        .find(|game| game.id() == edit_id)
        .unwrap();
    assert_eq!(saved_title.metadata()["title"], "Portal revisado");
    assert!(window.get_showing_editor());
    edit_and_flush!(window.set_edit_description("Descripción revisada".into()));
    let saved_description = Library::open(root)
        .games()
        .into_iter()
        .find(|game| game.id() == edit_id)
        .unwrap();
    assert_eq!(saved_description.metadata()["title"], "Portal revisado");
    assert_eq!(
        saved_description.metadata()["description"],
        "Descripción revisada"
    );
    edit_and_flush!(window.set_edit_synopsis("Sinopsis revisada".into()));
    edit_and_flush!(window.set_edit_release_date("29/02/2024".into()));
    edit_and_flush!(window.set_edit_developers("Estudio nuevo, Invitado, Invitado".into()));
    edit_and_flush!(window.set_edit_genres("Puzles, Aventura, Puzles".into()));
    edit_and_flush!(window.set_edit_platforms("Linux, Steam Deck".into()));
    edit_and_flush!(window.set_edit_metadata_source("manual-test".into()));
    edit_and_flush!(window.set_edit_entity_id("Q12345".into()));
    edit_and_flush!(window.set_edit_steam_appid("480".into()));
    edit_and_flush!(window.set_edit_categories("Favoritos, Aventura".into()));
    edit_and_flush!(window.set_edit_cover(root.join("banner.png").display().to_string().into()));
    edit_and_flush!(
        window.set_edit_square_cover(root.join("cover.png").display().to_string().into())
    );
    edit_and_flush!(window.set_edit_logo(root.join("logo.png").display().to_string().into()));
    edit_and_flush!(window.set_edit_banner(root.join("cover.png").display().to_string().into()));
    edit_and_flush!(
        window.set_edit_secondary_background(root.join("banner.png").display().to_string().into())
    );
    edit_and_flush!(window.set_edit_path(root.join("test-game.sh").display().to_string().into()));
    edit_and_flush!(window.set_edit_arguments("--profile 'two words'".into()));
    edit_and_flush!(window.set_edit_cwd(root.display().to_string().into()));
    // Simulate a concurrent change to an unrelated metadata field.
    let original = Library::open(root)
        .games()
        .into_iter()
        .find(|game| game.id() == edit_id)
        .unwrap();
    let mut concurrent = original.data().clone();
    concurrent.get_mut("metadata").unwrap()["publishers"] = json!(["Distribuidor nuevo"]);
    Library::open(root)
        .update_game(&edit_id, &concurrent)
        .unwrap();
    // Persisting another editor field must preserve this concurrent, untouched field.
    edit_and_flush!(window.set_edit_synopsis("Sinopsis revisada después".into()));
    // The selected row is not the identity of an open editing draft.
    window.set_selected_index(0);
    assert!(
        window.get_showing_editor(),
        "autosaving editor fields must not close the editor"
    );
    assert_no_editor_save_buttons(window);
    let saved = Library::open(root)
        .games()
        .into_iter()
        .find(|game| game.id() == edit_id)
        .unwrap();
    assert_eq!(saved.title(), "Portal");
    assert_eq!(saved.metadata()["title"], "Portal revisado");
    assert_eq!(saved.metadata()["description"], "Descripción revisada");
    assert_eq!(saved.metadata()["synopsis"], "Sinopsis revisada después");
    assert_eq!(saved.metadata()["manually_edited"], true);
    assert_eq!(saved.metadata()["release_date"], "2024-02-29");
    assert_eq!(
        saved.metadata()["developers"],
        json!(["Estudio nuevo", "Invitado"])
    );
    assert_eq!(saved.metadata()["genres"], json!(["Puzles", "Aventura"]));
    assert_eq!(
        saved.metadata()["platforms"],
        json!(["Linux", "Steam Deck"])
    );
    assert_eq!(saved.metadata()["source"], "manual-test");
    assert_eq!(saved.metadata()["entity_id"], "Q12345");
    assert_eq!(saved.metadata()["steam_appid"], "480");
    assert_eq!(
        saved
            .categories()
            .iter()
            .map(String::as_str)
            .collect::<Vec<_>>(),
        vec!["Favoritos", "Aventura"]
    );
    assert_eq!(
        saved.metadata()["publishers"],
        json!(["Distribuidor nuevo"])
    );
    assert_eq!(
        saved.field("cover"),
        root.join("banner.png").canonicalize().unwrap().to_str()
    );
    assert_eq!(
        saved.field("square_cover"),
        root.join("cover.png").canonicalize().unwrap().to_str()
    );
    assert_eq!(
        saved.field("logo"),
        root.join("logo.png").canonicalize().unwrap().to_str()
    );
    assert_eq!(
        saved.field("banner"),
        root.join("cover.png").canonicalize().unwrap().to_str()
    );
    assert_eq!(
        saved.field("banner_secondary"),
        root.join("banner.png").canonicalize().unwrap().to_str()
    );
    assert_eq!(
        saved.field("path"),
        root.join("test-game.sh").canonicalize().unwrap().to_str()
    );
    assert_eq!(saved.field("arguments"), Some("--profile 'two words'"));
    assert_eq!(saved.field("cwd"), root.canonicalize().unwrap().to_str());
    window.invoke_back();
    assert!(!window.get_showing_editor());
    let after_back = Library::open(root)
        .games()
        .into_iter()
        .find(|game| game.id() == edit_id)
        .unwrap();
    assert_eq!(after_back.metadata()["title"], "Portal revisado");
    assert_eq!(
        after_back.metadata()["synopsis"],
        "Sinopsis revisada después"
    );
    window.invoke_search_changed("Portal revisado".into());
    assert_eq!(window.get_games().row_count(), 1);
    window.invoke_begin_edit();
    assert_eq!(window.get_edit_id(), edit_id);
    assert!(!window.get_edit_banner().is_empty());
    assert!(!window.get_edit_secondary_background().is_empty());
    assert!(!window.get_artwork_importing());
    assert!(window.get_showing_editor());
    assert_eq!(window.get_editor_page(), "overview");
    for page in ["manual", "categories", "execution"] {
        window.set_editor_page(page.into());
        assert_no_editor_save_buttons(window);
        window.invoke_back();
        assert_eq!(window.get_editor_page(), "overview");
    }
    window.invoke_swap_edit_backgrounds();
    assert!(!window.get_showing_artwork());
    assert!(window.get_showing_editor());
    assert_eq!(
        window.get_edit_banner(),
        root.join("banner.png").display().to_string()
    );
    assert_eq!(
        window.get_edit_secondary_background(),
        root.join("cover.png").display().to_string()
    );
    let swapped = Library::open(root)
        .games()
        .into_iter()
        .find(|game| game.id() == edit_id)
        .unwrap();
    assert_eq!(
        swapped.field("banner"),
        root.join("banner.png").canonicalize().unwrap().to_str()
    );
    assert_eq!(
        swapped.field("banner_secondary"),
        root.join("cover.png").canonicalize().unwrap().to_str()
    );
    window.invoke_back();
    assert!(!window.get_showing_editor());
    window.invoke_begin_edit();
    window.set_showing_editor(false);
    window.set_showing_activity(true);
    assert!(window.get_showing_activity());
    press_control_shortcut(window, "s");
    assert!(
        window.get_showing_activity(),
        "Ctrl+S must not close the read-only Activity page"
    );
    window.invoke_back();
    assert!(window.get_showing_editor());
    window.invoke_cancel_edit();
    window.invoke_begin_edit();
    window.set_showing_editor(false);
    window.set_showing_artwork(true);
    window.set_artwork_browsing(true);
    assert_no_editor_save_buttons(window);
    window.set_artwork_browser_toolbar_focus_index(4);
    window.set_artwork_browser_toolbar_focus_serial(
        window
            .get_artwork_browser_toolbar_focus_serial()
            .wrapping_add(1),
    );
    assert_no_editor_save_buttons(window);
    window.invoke_back();
    assert!(!window.get_artwork_browsing());
    assert!(window.get_showing_artwork());
    window.invoke_back();
    assert!(!window.get_showing_artwork());
    assert!(window.get_showing_editor());
    window.invoke_begin_edit();
    window.set_showing_editor(false);
    window.set_showing_artwork(true);
    window.invoke_clear_artwork("cover".into());
    slint::platform::update_timers_and_animations();
    assert_eq!(window.get_edit_cover(), "");
    assert!(window.get_showing_editor());
    let cleared = Library::open(root)
        .games()
        .into_iter()
        .find(|game| game.id() == edit_id)
        .unwrap();
    assert_eq!(cleared.field("cover"), Some(""));
    window.invoke_back();
    assert!(!window.get_showing_editor());
    assert_eq!(
        Library::open(root)
            .games()
            .into_iter()
            .find(|game| game.id() == edit_id)
            .unwrap()
            .field("cover"),
        Some("")
    );
    window.invoke_search_changed("Portal revisado".into());
    window.invoke_begin_edit();
    edit_and_flush!(window.set_edit_title("Portal actualizado".into()));
    assert_eq!(
        Library::open(root)
            .games()
            .into_iter()
            .find(|game| game.id() == edit_id)
            .unwrap()
            .metadata()["title"],
        "Portal actualizado"
    );
    window.set_editor_page("manual".into());
    window.invoke_back();
    slint::platform::update_timers_and_animations();
    assert!(window.get_showing_editor());
    assert_eq!(window.get_editor_page(), "overview");
    window.invoke_back();
    slint::platform::update_timers_and_animations();
    assert!(!window.get_showing_editor());
    assert_eq!(
        Library::open(root)
            .games()
            .into_iter()
            .find(|game| game.id() == edit_id)
            .unwrap()
            .metadata()["title"],
        "Portal actualizado"
    );
    window.invoke_search_changed("Portal actualizado".into());
    assert_eq!(
        window.get_games().row_count(),
        1,
        "Search must include the edited display title"
    );
    window.invoke_begin_edit();
    edit_and_flush!(window.set_edit_title("Cambio local".into()));
    let mut concurrent = Library::open(root)
        .games()
        .into_iter()
        .find(|game| game.id() == edit_id)
        .unwrap()
        .data()
        .clone();
    concurrent.get_mut("metadata").unwrap()["title"] = json!("Cambio externo");
    Library::open(root)
        .update_game(&edit_id, &concurrent)
        .unwrap();
    edit_and_flush!(window.set_edit_description("Descripción después del cambio externo".into()));
    assert!(window.get_showing_editor());
    window.invoke_back();
    let after_concurrent_update = Library::open(root)
        .games()
        .into_iter()
        .find(|game| game.id() == edit_id)
        .unwrap();
    assert_eq!(
        after_concurrent_update.metadata()["title"],
        "Cambio externo"
    );
    assert_eq!(
        after_concurrent_update.metadata()["description"],
        "Descripción después del cambio externo"
    );
    window.invoke_search_changed("".into());
    window.set_save_message("".into());

    window.set_minimal(false);
    window.set_hero_position("lower".into());
    window.set_background_split("diagonal".into());
    window.set_dim(61);
    window.set_blur(13);
    let background_updates = Rc::new(std::cell::Cell::new(0));
    let observed_updates = background_updates.clone();
    window.on_background_config_changed(move |_, _| {
        observed_updates.set(observed_updates.get() + 1);
    });
    window.set_minimal(true);
    assert_eq!(
        background_updates.get(),
        0,
        "minimal presentation must not request a background update"
    );
    assert_eq!(window.get_hero_position(), "lower");
    assert_eq!(window.get_background_split(), "diagonal");
    assert_eq!(window.get_dim(), 61);
    assert_eq!(window.get_blur(), 13);
}

#[test]
fn validates_dates_and_qt_colors() {
    assert_eq!(normalize_date("29/02/2024").unwrap(), "2024-02-29");
    assert_eq!(normalize_date("2025-12-31").unwrap(), "2025-12-31");
    for invalid in [
        "29/02/2023",
        "2024-13-01",
        "2024-04-31",
        "0000-01-01",
        "2024/01-01",
    ] {
        assert!(normalize_date(invalid).is_err(), "{invalid}");
    }
    let color = parse_color("#80402010");
    assert_eq!(
        (color.alpha(), color.red(), color.green(), color.blue()),
        (128, 64, 32, 16)
    );
    assert_eq!(parse_color("#402010").alpha(), 255);
    assert_eq!(
        parse_color("€aaaaa"),
        slint::Color::from_rgb_u8(255, 255, 255)
    );
    assert!(!valid_color("€aaaaa"));
}

#[test]
fn decodes_downloaded_images_without_extension() {
    let path = std::env::temp_dir().join(format!("estante-image-{}.img", std::process::id()));
    image::RgbaImage::from_pixel(8, 8, image::Rgba([20, 40, 80, 255]))
        .save_with_format(&path, image::ImageFormat::Png)
        .unwrap();
    assert_eq!(decode_image(&path).unwrap().width(), 8);
    assert_eq!(
        validate_image_path(path.to_str().unwrap()).unwrap(),
        path.to_string_lossy()
    );
    std::fs::remove_file(path).unwrap();
}

#[test]
fn decodes_exif_oriented_artwork_like_qt() {
    let path = std::env::temp_dir().join(format!("estante-exif-image-{}.jpg", std::process::id()));
    image::RgbImage::from_pixel(16, 8, image::Rgb([20, 40, 80]))
        .save_with_format(&path, image::ImageFormat::Jpeg)
        .unwrap();
    let encoded = std::fs::read(&path).unwrap();
    let exif = [
        b'E', b'x', b'i', b'f', 0, 0, b'I', b'I', 42, 0, 8, 0, 0, 0, 1, 0, 0x12, 0x01, 3, 0, 1, 0,
        0, 0, 6, 0, 0, 0, 0, 0, 0, 0,
    ];
    let segment_length = (exif.len() + 2) as u16;
    let mut jpeg = encoded[..2].to_vec();
    jpeg.extend_from_slice(&[0xff, 0xe1]);
    jpeg.extend_from_slice(&segment_length.to_be_bytes());
    jpeg.extend_from_slice(&exif);
    jpeg.extend_from_slice(&encoded[2..]);
    std::fs::write(&path, jpeg).unwrap();

    let decoded = decode_image(&path).unwrap();
    assert_eq!((decoded.width(), decoded.height()), (8, 16));
    let thumbnail = decode_scaled_jpeg(&path, 4, 8).unwrap();
    assert_eq!((thumbnail.width(), thumbnail.height()), (4, 8));
    std::fs::remove_file(path).unwrap();
}

#[test]
fn jpeg_thumbnail_decodes_at_reduced_resolution() {
    let path =
        std::env::temp_dir().join(format!("estante-jpeg-thumbnail-{}.jpg", std::process::id()));
    image::RgbImage::from_pixel(1280, 720, image::Rgb([20, 40, 80]))
        .save_with_format(&path, image::ImageFormat::Jpeg)
        .unwrap();
    let thumbnail = decode_scaled_jpeg(&path, 160, 90).unwrap();
    assert_eq!((thumbnail.width(), thumbnail.height()), (160, 90));
    std::fs::remove_file(path).unwrap();
}

#[test]
fn png_thumbnail_matches_the_area_filter() {
    let path =
        std::env::temp_dir().join(format!("estante-png-thumbnail-{}.png", std::process::id()));
    let source = image::RgbaImage::from_fn(17, 9, |x, y| {
        image::Rgba([
            (x * 17) as u8,
            (y * 29) as u8,
            ((x + y) * 11) as u8,
            ((x * 13 + y * 7) % 256) as u8,
        ])
    });
    source.save(&path).unwrap();
    let expected = scale_dynamic_raster(image::DynamicImage::ImageRgba8(source), 4, 3);
    let actual = decode_scaled_png(&path, 4, 3).unwrap().into_rgba8();
    assert_eq!(actual, expected);
    std::fs::remove_file(path).unwrap();
    assert_eq!(
        png_row_pixel(&[42], 0, png::ColorType::Grayscale),
        Some([42, 42, 42, 255])
    );
    assert_eq!(
        png_row_pixel(&[42, 120], 0, png::ColorType::GrayscaleAlpha),
        Some([42, 42, 42, 120])
    );
    assert_eq!(
        png_row_pixel(&[1, 2, 3], 0, png::ColorType::Rgb),
        Some([1, 2, 3, 255])
    );
}

#[test]
fn sixteen_bit_png_thumbnail_matches_the_area_filter() {
    let path = std::env::temp_dir().join(format!(
        "estante-png16-thumbnail-{}.png",
        std::process::id()
    ));
    let source = image::ImageBuffer::from_fn(17, 9, |x, y| {
        image::Rgba([
            (x * 4011) as u16,
            (y * 7001) as u16,
            ((x + y) * 3021) as u16,
            ((x * 4001 + y * 7003) % 65536) as u16,
        ])
    });
    image::DynamicImage::ImageRgba16(source)
        .save_with_format(&path, image::ImageFormat::Png)
        .unwrap();

    let expected = scale_dynamic_raster(decode_raster_image(&path).unwrap(), 4, 3);
    let actual = decode_scaled_png(&path, 4, 3).unwrap().into_rgba8();
    assert_eq!(actual, expected);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn adam7_png_thumbnail_matches_the_area_filter() {
    let path = std::env::temp_dir().join(format!(
        "estante-adam7-thumbnail-{}.png",
        std::process::id()
    ));
    std::fs::write(&path, include_bytes!("../testdata/adam7-thumbnail.png")).unwrap();

    let expected = scale_dynamic_raster(decode_raster_image(&path).unwrap(), 4, 3);
    let actual = decode_scaled_png(&path, 4, 3).unwrap().into_rgba8();
    assert_eq!(actual, expected);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn stripped_tiff_thumbnail_matches_the_area_filter() {
    let path =
        std::env::temp_dir().join(format!("estante-tiff-thumbnail-{}.tif", std::process::id()));
    std::fs::write(
        &path,
        include_bytes!("../testdata/tiff-strips-thumbnail.tif"),
    )
    .unwrap();

    let expected = scale_dynamic_raster(decode_raster_image(&path).unwrap(), 4, 3);
    let actual = decode_scaled_tiff(&path, 4, 3).unwrap().into_rgba8();
    assert_eq!(actual, expected);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn tiled_tiff_thumbnail_matches_the_area_filter() {
    let path = std::env::temp_dir().join(format!(
        "estante-tiff-tiles-thumbnail-{}.tif",
        std::process::id()
    ));
    std::fs::write(
        &path,
        include_bytes!("../testdata/tiff-tiles-thumbnail.tif"),
    )
    .unwrap();

    let expected = scale_dynamic_raster(decode_raster_image(&path).unwrap(), 4, 3);
    let actual = decode_scaled_tiff(&path, 4, 3).unwrap().into_rgba8();
    assert_eq!(actual, expected);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn planar_tiff_thumbnails_match_the_area_filter() {
    let reference = std::env::temp_dir().join(format!(
        "estante-tiff-planar-reference-{}.png",
        std::process::id()
    ));
    std::fs::write(
        &reference,
        include_bytes!("../testdata/adam7-thumbnail.png"),
    )
    .unwrap();
    let expected = scale_dynamic_raster(decode_raster_image(&reference).unwrap(), 4, 3);
    for (index, fixture) in [
        include_bytes!("../testdata/tiff-planar-strips-thumbnail.tif").as_slice(),
        include_bytes!("../testdata/tiff-planar-tiles-thumbnail.tif").as_slice(),
    ]
    .into_iter()
    .enumerate()
    {
        let path = std::env::temp_dir().join(format!(
            "estante-tiff-planar-thumbnail-{}-{index}.tif",
            std::process::id()
        ));
        std::fs::write(&path, fixture).unwrap();
        let full_decode = scale_dynamic_raster(decode_raster_image(&path).unwrap(), 4, 3);
        assert_eq!(full_decode, expected);
        let actual = decode_scaled_tiff(&path, 4, 3).unwrap().into_rgba8();
        assert_eq!(actual, expected);
        std::fs::remove_file(path).unwrap();
    }
    std::fs::remove_file(reference).unwrap();
}

#[test]
fn sixteen_bit_tiff_thumbnails_match_the_area_filter() {
    let path = std::env::temp_dir().join(format!(
        "estante-tiff-16bit-thumbnail-{}.tif",
        std::process::id()
    ));
    let pixels = image::ImageBuffer::<image::Rgba<u16>, Vec<u16>>::from_fn(17, 9, |x, y| {
        image::Rgba([
            (x * 4097) as u16,
            (y * 7281) as u16,
            ((x + y) * 2731) as u16,
            ((x * 5003 + y * 3217) % 65536) as u16,
        ])
    });
    let mut encoder =
        tiff::encoder::TiffEncoder::new(std::fs::File::create(&path).unwrap()).unwrap();
    encoder
        .new_image::<tiff::encoder::colortype::RGBA16>(17, 9)
        .unwrap()
        .write_data(&pixels.into_raw())
        .unwrap();
    drop(encoder);

    let expected = scale_dynamic_raster(decode_raster_image(&path).unwrap(), 4, 3);
    let actual = decode_scaled_tiff(&path, 4, 3).unwrap().into_rgba8();
    assert_eq!(actual, expected);
    std::fs::remove_file(path).unwrap();

    let path = std::env::temp_dir().join(format!(
        "estante-tiff-16bit-planar-tiles-{}.tif",
        std::process::id()
    ));
    std::fs::write(
        &path,
        include_bytes!("../testdata/tiff-planar-tiles-16bit-thumbnail.tif"),
    )
    .unwrap();
    let expected = scale_dynamic_raster(decode_raster_image(&path).unwrap(), 4, 3);
    let actual = decode_scaled_tiff(&path, 4, 3).unwrap().into_rgba8();
    assert_eq!(actual, expected);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn float_tiff_thumbnails_match_the_area_filter() {
    let path = std::env::temp_dir().join(format!(
        "estante-tiff-float-thumbnail-{}.tif",
        std::process::id()
    ));
    let pixels = image::ImageBuffer::<image::Rgba<f32>, Vec<f32>>::from_fn(17, 9, |x, y| {
        image::Rgba([
            x as f32 / 16.0,
            y as f32 / 8.0,
            ((x + y) % 17) as f32 / 16.0,
            ((x * 3 + y * 5) % 17) as f32 / 16.0,
        ])
    });
    let mut encoder =
        tiff::encoder::TiffEncoder::new(std::fs::File::create(&path).unwrap()).unwrap();
    encoder
        .new_image::<tiff::encoder::colortype::RGBA32Float>(17, 9)
        .unwrap()
        .write_data(&pixels.into_raw())
        .unwrap();
    drop(encoder);

    let expected = scale_dynamic_raster(decode_raster_image(&path).unwrap(), 4, 3);
    let actual = decode_scaled_tiff(&path, 4, 3).unwrap().into_rgba8();
    assert_eq!(actual, expected);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn grayscale_float_tiff_decodes_with_and_without_scaling() {
    let path = std::env::temp_dir().join(format!(
        "estante-tiff-gray-float-thumbnail-{}.tif",
        std::process::id()
    ));
    let samples = (0..9)
        .flat_map(|y| (0..17).map(move |x| (x + y) as f32 / 24.0))
        .collect::<Vec<_>>();
    let mut encoder =
        tiff::encoder::TiffEncoder::new(std::fs::File::create(&path).unwrap()).unwrap();
    encoder
        .new_image::<tiff::encoder::colortype::Gray32Float>(17, 9)
        .unwrap()
        .write_data(&samples)
        .unwrap();
    drop(encoder);

    let expected_full =
        image::load_from_memory(include_bytes!("../testdata/tiff-gray32f-qt-reference.png"))
            .unwrap()
            .into_rgba8();
    assert_eq!(expected_full.dimensions(), (17, 9));
    let full = decode_scaled_tiff(&path, 64, 64).unwrap().into_rgba8();
    assert_eq!(full, expected_full);
    let expected_thumbnail =
        scale_dynamic_raster(image::DynamicImage::ImageRgba8(expected_full), 4, 3);
    let thumbnail = decode_scaled_tiff(&path, 4, 3).unwrap().into_rgba8();
    assert_eq!(thumbnail, expected_thumbnail);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn scaled_signed_and_half_float_tiffs_match_qt() {
    for (name, fixture, full_reference, thumbnail_reference) in [
        (
            "i8",
            include_bytes!("../testdata/tiff-gray-i8-qt.tif").as_slice(),
            include_bytes!("../testdata/tiff-gray-i8-qt-full.png").as_slice(),
            include_bytes!("../testdata/tiff-gray-i8-qt-thumbnail.png").as_slice(),
        ),
        (
            "i16",
            include_bytes!("../testdata/tiff-gray-i16-qt.tif").as_slice(),
            include_bytes!("../testdata/tiff-gray-i16-qt-full.png").as_slice(),
            include_bytes!("../testdata/tiff-gray-i16-qt-thumbnail.png").as_slice(),
        ),
        (
            "f16",
            include_bytes!("../testdata/tiff-gray-f16-qt.tif").as_slice(),
            include_bytes!("../testdata/tiff-gray-f16-qt-full.png").as_slice(),
            include_bytes!("../testdata/tiff-gray-f16-qt-thumbnail.png").as_slice(),
        ),
    ] {
        let path = std::env::temp_dir().join(format!(
            "estante-tiff-gray-{name}-{}.tif",
            std::process::id()
        ));
        std::fs::write(&path, fixture).unwrap();
        for (width, height, reference) in [(4, 4, full_reference), (2, 2, thumbnail_reference)] {
            let expected = image::load_from_memory(reference).unwrap().into_rgba8();
            let actual = decode_scaled_tiff(&path, width, height)
                .unwrap()
                .into_rgba8();
            if width == 4 && height == 4 {
                assert_eq!(actual, expected, "{name} TIFF at native size");
            } else {
                let max_delta = actual
                    .pixels()
                    .zip(expected.pixels())
                    .flat_map(|(actual, expected)| {
                        actual
                            .0
                            .into_iter()
                            .zip(expected.0)
                            .map(|(actual, expected)| actual.abs_diff(expected))
                    })
                    .max()
                    .unwrap_or(0);
                assert!(
                    max_delta <= 1,
                    "{name} TIFF thumbnail differs by {max_delta}"
                );
            }
        }
        std::fs::remove_file(path).unwrap();
    }
}

#[test]
fn indexed_png_thumbnail_preserves_expanded_palette_alpha() {
    let path = std::env::temp_dir().join(format!("estante-indexed-png-{}.png", std::process::id()));
    let file = std::fs::File::create(&path).unwrap();
    let mut encoder = png::Encoder::new(std::io::BufWriter::new(file), 17, 9);
    encoder.set_color(png::ColorType::Indexed);
    encoder.set_depth(png::BitDepth::Eight);
    encoder.set_palette(vec![20, 40, 80, 120, 160, 200, 255, 128, 0]);
    encoder.set_trns(vec![255, 128, 0]);
    let mut writer = encoder.write_header().unwrap();
    let indices = (0..17 * 9)
        .map(|index| (index % 3) as u8)
        .collect::<Vec<_>>();
    writer.write_image_data(&indices).unwrap();
    drop(writer);

    let expected = scale_dynamic_raster(decode_raster_image(&path).unwrap(), 4, 3);
    let actual = decode_scaled_png(&path, 4, 3).unwrap().into_rgba8();
    assert_eq!(actual, expected);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn trimmed_png_logo_is_scaled_to_the_logo_bound_before_cropping() {
    let path = std::env::temp_dir().join(format!("estante-large-logo-{}.png", std::process::id()));
    let source = image::RgbaImage::from_fn(3000, 1600, |x, y| {
        if (1400..1600).contains(&x) && (700..900).contains(&y) {
            image::Rgba([200, 120, 40, 255])
        } else {
            image::Rgba([0, 0, 0, 0])
        }
    });
    source.save(&path).unwrap();
    drop(source);
    let bounded = decode_scaled_png(&path, ROW_IMAGE_MAX_WIDTH, ROW_IMAGE_MAX_HEIGHT).unwrap();
    assert_eq!((bounded.width(), bounded.height()), (2560, 1365));
    let expected = row_image_from_raster(decode_raster_image(&path).unwrap(), 100, 100, true);

    let mut cache = HashMap::new();
    let mut order = std::collections::VecDeque::new();
    let mut cache_bytes = 0;
    let logo = row_image_pixels(
        Some(path.to_str().unwrap()),
        100,
        100,
        true,
        &mut cache,
        &mut order,
        &mut cache_bytes,
    )
    .unwrap();
    assert_eq!((logo.width, logo.height), (expected.width, expected.height));
    assert_eq!(logo.rgba, expected.rgba);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn artwork_browser_decodes_common_formats_and_svgz() {
    let folder = std::env::temp_dir().join(format!("estante-image-formats-{}", std::process::id()));
    std::fs::create_dir_all(&folder).unwrap();
    let rgb = image::RgbImage::from_pixel(4, 3, image::Rgb([20, 40, 80]));
    for (extension, format) in [
        ("bmp", image::ImageFormat::Bmp),
        ("gif", image::ImageFormat::Gif),
        ("jfif", image::ImageFormat::Jpeg),
        ("jpeg", image::ImageFormat::Jpeg),
        ("jpg", image::ImageFormat::Jpeg),
        ("ppm", image::ImageFormat::Pnm),
        ("tga", image::ImageFormat::Tga),
        ("tif", image::ImageFormat::Tiff),
        ("tiff", image::ImageFormat::Tiff),
        ("webp", image::ImageFormat::WebP),
    ] {
        let path = folder.join(format!("fixture.{extension}"));
        rgb.save_with_format(&path, format).unwrap();
        let decoded = decode_image(&path).unwrap();
        assert_eq!((decoded.width(), decoded.height()), (4, 3), "{extension}");
    }

    let png_path = folder.join("fixture.png");
    image::RgbaImage::from_pixel(4, 3, image::Rgba([20, 40, 80, 255]))
        .save(&png_path)
        .unwrap();
    let png = std::fs::read(png_path).unwrap();
    let largest_png_path = folder.join("largest.png");
    image::RgbImage::from_pixel(5, 3, image::Rgb([80, 40, 20]))
        .save(&largest_png_path)
        .unwrap();
    let largest_png = std::fs::read(largest_png_path).unwrap();
    let mut icns = b"icns\0\0\0\0".to_vec();
    for (kind, image) in [(b"icp4", &png), (b"ic10", &largest_png)] {
        icns.extend_from_slice(kind);
        icns.extend_from_slice(&((image.len() + 8) as u32).to_be_bytes());
        icns.extend_from_slice(image);
    }
    let total_size = (icns.len() as u32).to_be_bytes();
    icns[4..8].copy_from_slice(&total_size);
    let icns_path = folder.join("fixture.icns");
    std::fs::write(&icns_path, &icns).unwrap();
    let decoded_icns = decode_image(&icns_path).unwrap().to_rgba8();
    assert_eq!(decoded_icns.dimensions(), (4, 3));
    assert_eq!(decoded_icns.get_pixel(0, 0).0, [20, 40, 80, 255]);

    let mut nested_icon = b"icp4\0\0\0\0".to_vec();
    nested_icon[4..8].copy_from_slice(&((png.len() + 8) as u32).to_be_bytes());
    nested_icon.extend_from_slice(&png);
    let mut nested_icns = b"icns\0\0\0\0".to_vec();
    for (kind, payload) in [(*b"tile", nested_icon.as_slice()), (*b"ic10", &largest_png)] {
        nested_icns.extend_from_slice(&kind);
        nested_icns.extend_from_slice(&((payload.len() + 8) as u32).to_be_bytes());
        nested_icns.extend_from_slice(payload);
    }
    let nested_size = (nested_icns.len() as u32).to_be_bytes();
    nested_icns[4..8].copy_from_slice(&nested_size);
    let nested_path = folder.join("nested.icns");
    std::fs::write(&nested_path, nested_icns).unwrap();
    let nested = decode_image(&nested_path).unwrap().to_rgba8();
    assert_eq!(nested.dimensions(), (4, 3));
    assert_eq!(nested.get_pixel(0, 0).0, [20, 40, 80, 255]);

    let mut jp2_first_icns = b"icns\0\0\0\0".to_vec();
    for (kind, payload) in [
        (*b"ic07", &b"\0\0\0\x0cjP  \r\n\x87\n"[..]),
        (*b"icp6", &png[..]),
    ] {
        jp2_first_icns.extend_from_slice(&kind);
        jp2_first_icns.extend_from_slice(&((payload.len() + 8) as u32).to_be_bytes());
        jp2_first_icns.extend_from_slice(payload);
    }
    let jp2_first_size = (jp2_first_icns.len() as u32).to_be_bytes();
    jp2_first_icns[4..8].copy_from_slice(&jp2_first_size);
    let jp2_first_path = folder.join("jp2-first.icns");
    std::fs::write(&jp2_first_path, jp2_first_icns).unwrap();
    assert!(decode_image(&jp2_first_path).is_err());

    let truncated_icns_path = folder.join("truncated.icns");
    let invalid_size = (icns.len() as u32) + 1;
    icns[4..8].copy_from_slice(&invalid_size.to_be_bytes());
    std::fs::write(&truncated_icns_path, icns).unwrap();
    assert!(decode_image(&truncated_icns_path).is_err());
    let mut legacy_icns = b"icns\0\0\0\0".to_vec();
    let mut rle_rgb = Vec::new();
    for color in [20_u8, 40, 60] {
        rle_rgb.extend_from_slice(&[0xff, color, 0xfb, color]);
    }
    for (kind, data) in [
        (*b"is32", rle_rgb),
        (*b"s8mk", {
            let mut alpha = vec![255; 16 * 16];
            alpha[0] = 128;
            alpha
        }),
    ] {
        legacy_icns.extend_from_slice(&kind);
        legacy_icns.extend_from_slice(&((data.len() + 8) as u32).to_be_bytes());
        legacy_icns.extend_from_slice(&data);
    }
    let legacy_size = (legacy_icns.len() as u32).to_be_bytes();
    legacy_icns[4..8].copy_from_slice(&legacy_size);
    let legacy_icns_path = folder.join("legacy.icns");
    std::fs::write(&legacy_icns_path, &legacy_icns).unwrap();
    let legacy = decode_image(&legacy_icns_path).unwrap().to_rgba8();
    assert_eq!(legacy.dimensions(), (16, 16));
    assert_eq!(legacy.get_pixel(0, 0).0, [20, 40, 60, 128]);
    assert_eq!(legacy.get_pixel(15, 15).0, [20, 40, 60, 255]);
    assert!(decode_icns_rle24(&[0xff, 20, 0xfb, 20], None, 16).is_none());
    for (kind, depth, data) in [
        (
            *b"ics4",
            4,
            (0..128)
                .map(|index| (((index % 16) << 4) | ((index + 1) % 16)) as u8)
                .collect::<Vec<_>>(),
        ),
        (*b"ics8", 8, (0..256).map(|index| index as u8).collect()),
    ] {
        let mut palette_icns = b"icns\0\0\0\0".to_vec();
        let mut alpha = vec![255; 16 * 16];
        alpha[0] = 128;
        for (chunk, bytes) in [(kind, data), (*b"s8mk", alpha)] {
            palette_icns.extend_from_slice(&chunk);
            palette_icns.extend_from_slice(&((bytes.len() + 8) as u32).to_be_bytes());
            palette_icns.extend_from_slice(&bytes);
        }
        let size = (palette_icns.len() as u32).to_be_bytes();
        palette_icns[4..8].copy_from_slice(&size);
        let path = folder.join(format!("palette-{depth}.icns"));
        std::fs::write(&path, palette_icns).unwrap();
        let decoded = decode_image(&path).unwrap().to_rgba8();
        assert_eq!(decoded.dimensions(), (16, 16));
        assert_eq!(decoded.get_pixel(0, 0).0, [255, 255, 255, 128]);
        assert_eq!(
            decoded.get_pixel(1, 0).0,
            if depth == 4 {
                [252, 243, 5, 255]
            } else {
                [255, 255, 204, 255]
            }
        );
    }
    let mut mono = vec![0xaa; 32];
    mono.extend([0xf0; 32]);
    let mut mono_icns = b"icns\0\0\0\0".to_vec();
    mono_icns.extend_from_slice(b"ics#");
    mono_icns.extend_from_slice(&((mono.len() + 8) as u32).to_be_bytes());
    mono_icns.extend_from_slice(&mono);
    let mono_size = (mono_icns.len() as u32).to_be_bytes();
    mono_icns[4..8].copy_from_slice(&mono_size);
    let mono_path = folder.join("mono.icns");
    std::fs::write(&mono_path, mono_icns).unwrap();
    let mono = decode_image(&mono_path).unwrap().to_rgba8();
    assert_eq!(mono.get_pixel(0, 0).0, [0, 0, 0, 255]);
    assert_eq!(mono.get_pixel(1, 0).0, [255, 255, 255, 255]);
    assert_eq!(mono.get_pixel(4, 0).0, [0, 0, 0, 0]);
    let mut nested_icon = b"icp4".to_vec();
    nested_icon.extend_from_slice(&((png.len() + 8) as u32).to_be_bytes());
    nested_icon.extend_from_slice(&png);
    let mut variant = b"tile".to_vec();
    variant.extend_from_slice(&((nested_icon.len() + 8) as u32).to_be_bytes());
    variant.extend_from_slice(&nested_icon);
    let mut nested_icns = b"icns".to_vec();
    nested_icns.extend_from_slice(&((variant.len() + 8) as u32).to_be_bytes());
    nested_icns.extend_from_slice(&variant);
    let nested_path = folder.join("nested.icns");
    std::fs::write(&nested_path, nested_icns).unwrap();
    let nested = decode_image(&nested_path).unwrap().to_rgba8();
    assert_eq!(nested.dimensions(), (4, 3));
    assert_eq!(nested.get_pixel(0, 0).0, [20, 40, 80, 255]);
    for (extension, contents) in [
        ("pbm", &b"P1\n4 3\n0 1 0 1 1 0 1 0 0 1 0 1\n"[..]),
        (
            "pgm",
            &b"P2\n4 3\n255\n0 85 170 255 255 170 85 0 0 85 170 255\n"[..],
        ),
    ] {
        let path = folder.join(format!("fixture.{extension}"));
        std::fs::write(&path, contents).unwrap();
        let decoded = decode_image(&path).unwrap();
        assert_eq!((decoded.width(), decoded.height()), (4, 3), "{extension}");
    }
    let wbmp_path = folder.join("fixture.wbmp");
    std::fs::write(
        &wbmp_path,
        [0, 0, 4, 3, 0b1010_0000, 0b0110_0000, 0b1000_0000],
    )
    .unwrap();
    let wbmp = decode_image(&wbmp_path).unwrap().to_rgba8();
    assert_eq!(wbmp.get_pixel(0, 0).0, [255, 255, 255, 255]);
    assert_eq!(wbmp.get_pixel(1, 0).0, [0, 0, 0, 255]);
    assert_eq!(wbmp.get_pixel(2, 1).0, [255, 255, 255, 255]);
    let truncated_wbmp = folder.join("truncated.wbmp");
    std::fs::write(&truncated_wbmp, [0, 0, 0x80, 0x80]).unwrap();
    assert!(decode_image(&truncated_wbmp).is_err());
    let mut wide_wbmp = vec![0, 0, 0x81, 0x02, 1];
    wide_wbmp.extend([0; 17]);
    let wide_wbmp_path = folder.join("wide.wbmp");
    std::fs::write(&wide_wbmp_path, wide_wbmp).unwrap();
    assert_eq!(decode_image(&wide_wbmp_path).unwrap().width(), 130);
    let xbm_path = folder.join("fixture.xbm");
    std::fs::write(
        &xbm_path,
        "/* XBM */\n#define fixture_width 4\n#define fixture_height 2\nstatic unsigned char fixture_bits[] = { 0x05, 0x02 };\n",
    )
    .unwrap();
    let xbm = decode_image(&xbm_path).unwrap().to_rgba8();
    assert_eq!(xbm.get_pixel(0, 0).0, [0, 0, 0, 255]);
    assert_eq!(xbm.get_pixel(1, 0).0, [255, 255, 255, 255]);
    assert_eq!(xbm.get_pixel(1, 1).0, [0, 0, 0, 255]);
    let truncated_xbm = folder.join("truncated.xbm");
    std::fs::write(
        &truncated_xbm,
        "#define fixture_width 2\n#define fixture_height 1\nstatic char fixture_bits[] = { };\n",
    )
    .unwrap();
    assert!(decode_image(&truncated_xbm).is_err());
    let xpm_path = folder.join("fixture.xpm");
    std::fs::write(
        &xpm_path,
        "/* XPM */\nstatic const char *fixture[] = {\n\"3 2 3 1\",\n\"  c None\",\n\". c #f00\",\n\"x c navy\",\n\".x \",\n\" x.\",\n};\n",
    )
    .unwrap();
    let xpm = decode_image(&xpm_path).unwrap().to_rgba8();
    assert_eq!(xpm.dimensions(), (3, 2));
    assert_eq!(xpm.get_pixel(0, 0).0, [255, 0, 0, 255]);
    assert_eq!(xpm.get_pixel(1, 0).0, [0, 0, 128, 255]);
    assert_eq!(xpm.get_pixel(2, 0).0, [0, 0, 0, 0]);
    let color_names_path = folder.join("color-names.xpm");
    std::fs::write(
        &color_names_path,
        "/* XPM */\nstatic char *x[] = {\n\"2 1 2 1\",\n\"a c green\",\n\"b c gray50\",\n\"ab\",\n};\n",
    )
    .unwrap();
    let color_names = decode_image(&color_names_path).unwrap().to_rgba8();
    assert_eq!(color_names.get_pixel(0, 0).0, [0, 255, 0, 255]);
    assert_eq!(color_names.get_pixel(1, 0).0, [127, 127, 127, 255]);
    let x11_names_path = folder.join("x11-names.xpm");
    std::fs::write(
        &x11_names_path,
        "/* XPM */\nstatic char *x[] = {\n\"2 1 2 1\",\n\"a c blue1\",\n\"b c lightgoldenrod\",\n\"ab\",\n};\n",
    )
    .unwrap();
    let x11_names = decode_image(&x11_names_path).unwrap().to_rgba8();
    assert_eq!(x11_names.get_pixel(0, 0).0, [0, 0, 255, 255]);
    assert_eq!(x11_names.get_pixel(1, 0).0, [238, 221, 130, 255]);
    let cpp_path = folder.join("cpp.xpm");
    std::fs::write(
        &cpp_path,
        "/* XPM */\nstatic char *x[] = {\n\"2 1 2 2\",\n\"/* c None\",\n\"!! c #123456\",\n\"/*!!\",\n};\n",
    )
    .unwrap();
    let cpp = decode_image(&cpp_path).unwrap().to_rgba8();
    assert_eq!(cpp.get_pixel(0, 0).0, [0, 0, 0, 0]);
    assert_eq!(cpp.get_pixel(1, 0).0, [0x12, 0x34, 0x56, 255]);
    let xpm2_path = folder.join("plain.xpm");
    std::fs::write(&xpm2_path, "! XPM2\n2 1 2 1\n. c #00ff00\nx c None\n.x\n").unwrap();
    let xpm2 = decode_image(&xpm2_path).unwrap().to_rgba8();
    assert_eq!(xpm2.get_pixel(0, 0).0, [0, 255, 0, 255]);
    assert_eq!(xpm2.get_pixel(1, 0).0, [0, 0, 0, 0]);
    for (extension, kind) in [("ico", 1_u16), ("cur", 2_u16)] {
        let mut icon = vec![0, 0];
        icon.extend_from_slice(&kind.to_le_bytes());
        icon.extend_from_slice(&1_u16.to_le_bytes());
        icon.extend_from_slice(&[4, 3, 0, 0]);
        let (planes, bits_per_pixel) = if kind == 1 { (1_u16, 32_u16) } else { (0, 0) };
        icon.extend_from_slice(&planes.to_le_bytes());
        icon.extend_from_slice(&bits_per_pixel.to_le_bytes());
        icon.extend_from_slice(&(png.len() as u32).to_le_bytes());
        icon.extend_from_slice(&22_u32.to_le_bytes());
        icon.extend_from_slice(&png);
        let path = folder.join(format!("fixture.{extension}"));
        std::fs::write(&path, icon).unwrap();
        let decoded = decode_image(&path).unwrap();
        assert_eq!((decoded.width(), decoded.height()), (4, 3), "{extension}");
    }

    let svg = b"<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"2\" height=\"3\"><rect width=\"2\" height=\"3\" fill=\"#f00\"/></svg>";
    std::fs::write(folder.join("fixture.svg"), svg).unwrap();
    std::fs::write(
        folder.join("fixture.svgz"),
        [
            31, 139, 8, 0, 0, 0, 0, 0, 2, 255, 109, 204, 73, 14, 128, 32, 12, 64, 209, 171, 144,
            186, 167, 13, 236, 12, 112, 25, 101, 74, 112, 8, 52, 214, 227, 171, 123, 215, 255, 229,
            187, 113, 101, 117, 111, 109, 31, 30, 10, 243, 57, 35, 138, 136, 22, 171, 143, 158,
            209, 16, 17, 190, 2, 148, 212, 149, 139, 7, 3, 170, 196, 154, 11, 123, 176, 16, 92,
            143, 11, 255, 38, 149, 106, 107, 30, 166, 68, 4, 24, 220, 247, 8, 15, 62, 194, 37, 143,
            107, 0, 0, 0,
        ],
    )
    .unwrap();
    for extension in ["svg", "svgz"] {
        let path = folder.join(format!("fixture.{extension}"));
        let decoded = decode_image(&path).unwrap();
        assert_eq!((decoded.width(), decoded.height()), (2, 3), "{extension}");
        assert_eq!(
            validate_image_path(path.to_str().unwrap()).unwrap(),
            path.canonicalize().unwrap().to_string_lossy(),
            "{extension}"
        );
    }

    let visible = load_artwork_browser_items(&folder)
        .unwrap()
        .into_iter()
        .filter(|item| !item.directory)
        .map(|item| {
            PathBuf::from(item.path)
                .extension()
                .unwrap()
                .to_string_lossy()
                .into_owned()
        })
        .collect::<std::collections::HashSet<_>>();
    for extension in [
        "bmp", "cur", "gif", "icns", "ico", "jfif", "jpeg", "jpg", "pbm", "pgm", "png", "ppm",
        "svg", "svgz", "tga", "tif", "tiff", "wbmp", "webp", "xbm", "xpm",
    ] {
        assert!(
            visible.contains(extension),
            "{extension} must be selectable"
        );
    }
    std::fs::remove_dir_all(folder).unwrap();
}

#[test]
fn reducing_dynamic_rasters_matches_the_rgba_area_filter() {
    let rgba = image::RgbaImage::from_fn(17, 9, |x, y| {
        image::Rgba([
            (x * 17) as u8,
            (y * 29) as u8,
            ((x + y) * 11) as u8,
            ((x * 13 + y * 7) % 256) as u8,
        ])
    });
    let expected = scale_row_raster(rgba.clone(), 4, 3);
    let actual = scale_dynamic_raster(image::DynamicImage::ImageRgba8(rgba), 4, 3);
    assert_eq!(actual, expected);

    let rgb = image::RgbImage::from_fn(17, 9, |x, y| {
        image::Rgb([(x * 17) as u8, (y * 29) as u8, ((x + y) * 11) as u8])
    });
    let expected = scale_row_raster(
        image::DynamicImage::ImageRgb8(rgb.clone()).into_rgba8(),
        4,
        3,
    );
    let actual = scale_dynamic_raster(image::DynamicImage::ImageRgb8(rgb), 4, 3);
    assert_eq!(actual, expected);

    let rgba16 = image::ImageBuffer::<image::Rgba<u16>, Vec<u16>>::from_fn(17, 9, |x, y| {
        image::Rgba([
            (x * 4097) as u16,
            (y * 7281) as u16,
            ((x + y) * 2731) as u16,
            ((x * 5003 + y * 3217) % 65536) as u16,
        ])
    });
    let expected = scale_row_raster(
        image::DynamicImage::ImageRgba16(rgba16.clone()).into_rgba8(),
        4,
        3,
    );
    let actual = scale_dynamic_raster(image::DynamicImage::ImageRgba16(rgba16), 4, 3);
    assert_eq!(actual, expected);
}

#[test]
fn list_artwork_is_downscaled_and_reused_in_the_worker_cache() {
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!("estante-row-image-{nonce}.png"));
    image::RgbaImage::from_pixel(1600, 800, image::Rgba([20, 40, 80, 255]))
        .save(&path)
        .unwrap();
    let mut cache = HashMap::new();
    let mut order = std::collections::VecDeque::new();
    let mut cache_bytes = 0;
    let first = row_image_pixels(
        Some(path.to_str().unwrap()),
        480,
        720,
        false,
        &mut cache,
        &mut order,
        &mut cache_bytes,
    )
    .unwrap();
    assert_eq!((first.width, first.height), (480, 240));
    let cached = row_image_pixels(
        Some(path.to_str().unwrap()),
        480,
        720,
        false,
        &mut cache,
        &mut order,
        &mut cache_bytes,
    )
    .unwrap();
    assert!(std::sync::Arc::ptr_eq(&first, &cached));
    image::RgbaImage::from_pixel(1600, 400, image::Rgba([90, 80, 70, 255]))
        .save(&path)
        .unwrap();
    let refreshed = row_image_pixels(
        Some(path.to_str().unwrap()),
        480,
        720,
        false,
        &mut cache,
        &mut order,
        &mut cache_bytes,
    )
    .unwrap();
    assert_eq!((refreshed.width, refreshed.height), (480, 120));
    assert_eq!(&refreshed.rgba[..4], &[90, 80, 70, 255]);
    let large_path = std::env::temp_dir().join(format!("estante-row-large-{nonce}.png"));
    image::RgbaImage::from_pixel(3200, 1600, image::Rgba([12, 34, 56, 255]))
        .save(&large_path)
        .unwrap();
    let bounded = row_image_pixels(
        Some(large_path.to_str().unwrap()),
        4096,
        4096,
        false,
        &mut cache,
        &mut order,
        &mut cache_bytes,
    )
    .unwrap();
    assert_eq!((bounded.width, bounded.height), (2560, 1280));
    std::fs::remove_file(large_path).unwrap();
    let alpha_path = std::env::temp_dir().join(format!("estante-row-alpha-{nonce}.png"));
    let mut alpha_edge = image::RgbaImage::new(4, 1);
    for (x, pixel) in [
        [255, 0, 0, 0],
        [0, 0, 255, 255],
        [0, 0, 255, 255],
        [255, 0, 0, 0],
    ]
    .into_iter()
    .enumerate()
    {
        alpha_edge.put_pixel(x as u32, 0, image::Rgba(pixel));
    }
    alpha_edge.save(&alpha_path).unwrap();
    let scaled_alpha = row_image_pixels(
        Some(alpha_path.to_str().unwrap()),
        2,
        1,
        false,
        &mut cache,
        &mut order,
        &mut cache_bytes,
    )
    .unwrap();
    assert_eq!((scaled_alpha.width, scaled_alpha.height), (2, 1));
    assert_eq!(&scaled_alpha.rgba[..3], &[0, 0, 255]);
    assert!((127..=128).contains(&scaled_alpha.rgba[3]));
    std::fs::remove_file(alpha_path).unwrap();
    let svg_path = std::env::temp_dir().join(format!("estante-row-image-{nonce}.svg"));
    std::fs::write(
        &svg_path,
        r##"<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="800" viewBox="0 0 1600 800"><rect width="1600" height="800" fill="#142850" fill-opacity="0.5"/></svg>"##,
    )
    .unwrap();
    let svg = row_image_pixels(
        Some(svg_path.to_str().unwrap()),
        480,
        720,
        false,
        &mut cache,
        &mut order,
        &mut cache_bytes,
    )
    .expect("SVG artwork should be rasterized in the worker");
    assert_eq!((svg.width, svg.height), (480, 240));
    assert_eq!(&svg.rgba[..3], &[20, 40, 80]);
    assert!((127..=128).contains(&svg.rgba[3]));
    std::fs::remove_file(path).unwrap();
    std::fs::remove_file(svg_path).unwrap();
}

#[test]
fn list_logos_trim_transparent_canvas_and_keep_visible_pixels() {
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!("estante-row-logo-{nonce}.png"));
    let mut logo = image::RgbaImage::from_pixel(8, 6, image::Rgba([0, 0, 0, 0]));
    logo.put_pixel(2, 1, image::Rgba([12, 34, 56, 64]));
    logo.put_pixel(4, 4, image::Rgba([78, 90, 123, 255]));
    logo.save(&path).unwrap();
    assert_eq!(
        trim_transparent_logo_canvas(decode_image(&path).unwrap().into_rgba8()).dimensions(),
        (3, 4)
    );
    let mut cache = HashMap::new();
    let mut order = std::collections::VecDeque::new();
    let mut cache_bytes = 0;
    let trimmed = row_image_pixels(
        Some(path.to_str().unwrap()),
        8,
        6,
        true,
        &mut cache,
        &mut order,
        &mut cache_bytes,
    )
    .unwrap();
    assert_eq!((trimmed.width, trimmed.height), (3, 4));
    assert_eq!(&trimmed.rgba[..4], &[12, 34, 56, 64]);

    let untrimmed = row_image_pixels(
        Some(path.to_str().unwrap()),
        8,
        6,
        false,
        &mut cache,
        &mut order,
        &mut cache_bytes,
    )
    .unwrap();
    assert_eq!((untrimmed.width, untrimmed.height), (8, 6));
    assert!(!std::sync::Arc::ptr_eq(&trimmed, &untrimmed));

    let svg_path = std::env::temp_dir().join(format!("estante-row-logo-{nonce}.svg"));
    std::fs::write(
        &svg_path,
        r##"<svg xmlns="http://www.w3.org/2000/svg" width="3200" height="1600" viewBox="0 0 3200 1600"><rect x="400" y="200" width="2400" height="800" fill="#0c2238"/></svg>"##,
    )
    .unwrap();
    let trimmed_svg = row_image_pixels(
        Some(svg_path.to_str().unwrap()),
        480,
        720,
        true,
        &mut cache,
        &mut order,
        &mut cache_bytes,
    )
    .unwrap();
    assert_eq!((trimmed_svg.width, trimmed_svg.height), (480, 160));
    assert_eq!(&trimmed_svg.rgba[..4], &[12, 34, 56, 255]);

    let transparent = image::RgbaImage::from_pixel(3, 2, image::Rgba([0, 0, 0, 0]));
    assert_eq!(
        trim_transparent_logo_canvas(transparent).dimensions(),
        (3, 2)
    );
    std::fs::remove_file(path).unwrap();
    std::fs::remove_file(svg_path).unwrap();
}

#[test]
fn numeric_settings_accept_qt_floats_and_clamp() {
    let settings = json!({"list_zoom": 123.6, "background_dim": {"list": 130.0}});
    assert_eq!(setting_number(&settings, "list_zoom", 100, 50, 200), 124);
    assert_eq!(
        nested_number(&settings, "background_dim", "list", 78, 0, 100),
        100
    );
}

#[test]
fn dominant_background_color_matches_qt_bucket_selection() {
    let tied_buckets = image::RgbaImage::from_fn(4, 1, |x, _| match x {
        0 => image::Rgba([100, 31, 7, 255]),
        1 => image::Rgba([101, 31, 7, 255]),
        _ => image::Rgba([0, 0, 240, 255]),
    });
    assert_eq!(dominant_color(&tied_buckets), [100, 31, 7]);

    let alpha_threshold = image::RgbaImage::from_fn(4, 1, |x, _| match x {
        0 => image::Rgba([100, 31, 7, 255]),
        1 => image::Rgba([101, 31, 7, 255]),
        2 => image::Rgba([102, 31, 7, 128]),
        _ => image::Rgba([0, 240, 0, 127]),
    });
    assert_eq!(dominant_color(&alpha_threshold), [101, 31, 7]);
    assert_eq!(
        dominant_color(&image::RgbaImage::from_pixel(
            1,
            1,
            image::Rgba([255, 0, 0, 127])
        )),
        [32, 32, 32]
    );
}

#[test]
fn background_crop_keeps_position_and_center_alignment() {
    let tall = image::DynamicImage::ImageRgba8(image::RgbaImage::from_fn(100, 200, |_, y| {
        image::Rgba([y as u8, 0, 0, 255])
    }));
    for (position, expected) in [("top", 10), ("full", 60), ("lower", 110)] {
        let cropped = resize_background_crop(&tall, 100, 100, position);
        assert_eq!(cropped.dimensions(), (100, 100));
        assert_eq!(cropped.get_pixel(50, 10)[0], expected);
    }

    let wide = image::DynamicImage::ImageRgba8(image::RgbaImage::from_fn(200, 100, |x, _| {
        image::Rgba([x as u8, 0, 0, 255])
    }));
    let cropped = resize_background_crop(&wide, 100, 100, "full");
    assert_eq!(cropped.get_pixel(10, 50)[0], 60);
}

#[test]
fn positioned_background_preserves_hero_alignment() {
    let source = image::RgbaImage::from_fn(160, 40, |_, y| {
        if y < 20 {
            image::Rgba([240, 10, 10, 255])
        } else {
            image::Rgba([10, 10, 240, 255])
        }
    });
    let top = positioned_background(&source, "top", (160, 120), "blur", 0, None);
    let lower = positioned_background(&source, "lower", (160, 120), "blur", 0, None);
    assert_eq!(top.dimensions(), (160, 120));
    assert!(top.get_pixel(80, 0)[0] > 230);
    assert!(lower.get_pixel(80, 119)[2] > 230);
    assert_ne!(top, lower);
}

#[test]
fn background_sizes_follow_qt_pixel_bounds() {
    assert_eq!(background_viewport_size((1280, 800), 2.0), (2560, 1600));
    assert_eq!(background_sizes((1920, 1080)), ((1920, 1080), (1920, 1080)));
    assert_eq!(background_sizes((1280, 800)), ((1280, 800), (1280, 800)));
    assert_eq!(background_sizes((2560, 1600)), ((2304, 1440), (2560, 1440)));
    assert_eq!(background_sizes((3840, 2160)), ((2560, 1440), (2560, 1440)));
    assert_eq!(background_sizes((3440, 1440)), ((2560, 1072), (2560, 1440)));

    let path = std::env::temp_dir().join(format!(
        "estante-slint-background-size-{}.png",
        std::process::id()
    ));
    image::RgbaImage::from_pixel(3200, 32, image::Rgba([1, 2, 3, 255]))
        .save(&path)
        .unwrap();
    let decoded =
        load_background_pixels(&path.to_string_lossy(), false, &mut None, (2560, 1440)).unwrap();
    assert_eq!(decoded.dimensions(), (2560, 26));
    std::fs::remove_file(path).unwrap();
}

#[test]
fn split_backgrounds_blend_at_the_seam_and_keep_the_missing_side_fallback() {
    let root = std::env::temp_dir().join(format!("estante-slint-split-{}", std::process::id()));
    std::fs::create_dir_all(&root).unwrap();
    let primary_path = root.join("primary.png");
    let secondary_path = root.join("secondary.png");
    image::RgbaImage::from_pixel(100, 80, image::Rgba([255, 0, 0, 255]))
        .save(&primary_path)
        .unwrap();
    image::RgbaImage::from_pixel(100, 80, image::Rgba([0, 0, 255, 255]))
        .save(&secondary_path)
        .unwrap();

    for split in ["vertical", "horizontal", "diagonal"] {
        let pixels = compose_slint_background_pair(
            primary_path.to_str().unwrap(),
            secondary_path.to_str().unwrap(),
            split,
            "full",
            "blur",
            0,
            [21, 22, 23],
            (100, 80),
        )
        .unwrap();
        assert_eq!(*pixels.get_pixel(5, 5), image::Rgba([255, 0, 0, 255]));
        assert_eq!(*pixels.get_pixel(95, 75), image::Rgba([0, 0, 255, 255]));
        let (primary, secondary) = match split {
            "horizontal" => (pixels.get_pixel(50, 10), pixels.get_pixel(50, 70)),
            "vertical" => (pixels.get_pixel(10, 40), pixels.get_pixel(90, 40)),
            _ => (pixels.get_pixel(5, 5), pixels.get_pixel(95, 75)),
        };
        assert!(
            primary[0] > 240 && primary[2] < 16,
            "{split} primary region"
        );
        assert!(
            secondary[2] > 240 && secondary[0] < 16,
            "{split} secondary region"
        );
        let seam = pixels.get_pixel(50, 40);
        assert!((127..=128).contains(&seam[0]));
        assert_eq!(seam[1], 0);
        assert!((127..=128).contains(&seam[2]));
        if split == "vertical" {
            for (x, expected_red) in [
                (47, 255),
                (48, 250),
                (49, 203),
                (50, 128),
                (51, 52),
                (52, 5),
                (53, 0),
            ] {
                assert!(
                    pixels.get_pixel(x, 40)[0].abs_diff(expected_red) <= 1,
                    "Qt mask at x={x}"
                );
            }
        }
    }

    let fallback = compose_slint_background_pair(
        root.join("missing.png").to_str().unwrap(),
        secondary_path.to_str().unwrap(),
        "vertical",
        "full",
        "blur",
        0,
        [21, 22, 23],
        (100, 80),
    )
    .unwrap();
    assert_eq!(*fallback.get_pixel(10, 40), image::Rgba([21, 22, 23, 255]));
    assert_eq!(*fallback.get_pixel(90, 40), image::Rgba([0, 0, 255, 255]));
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn transparent_primary_reveals_the_secondary_layer() {
    let root = std::env::temp_dir().join(format!(
        "estante-slint-transparent-background-{}",
        std::process::id()
    ));
    std::fs::create_dir_all(&root).unwrap();
    let primary = root.join("primary.png");
    let secondary = root.join("secondary.png");
    image::RgbaImage::from_pixel(100, 80, image::Rgba([255, 0, 0, 0]))
        .save(&primary)
        .unwrap();
    image::RgbaImage::from_pixel(100, 80, image::Rgba([0, 0, 255, 255]))
        .save(&secondary)
        .unwrap();

    for position in ["full", "top"] {
        for (split, transparent, visible_secondary) in [
            ("horizontal", Some((50, 5)), (50, 75)),
            ("vertical", Some((5, 40)), (95, 40)),
            ("diagonal", None, (5, 5)),
        ] {
            let pixels = compose_slint_background_pair(
                primary.to_str().unwrap(),
                secondary.to_str().unwrap(),
                split,
                position,
                "blur",
                0,
                [21, 22, 23],
                (100, 80),
            )
            .unwrap();
            if let Some(point) = transparent {
                assert_eq!(
                    *pixels.get_pixel(point.0, point.1),
                    image::Rgba([21, 22, 23, 255])
                );
            }
            assert_eq!(
                *pixels.get_pixel(visible_secondary.0, visible_secondary.1),
                image::Rgba([0, 0, 255, 255])
            );
            if split == "diagonal" {
                assert_eq!(*pixels.get_pixel(95, 75), image::Rgba([0, 0, 255, 255]));
            }
        }
    }

    let half_alpha = root.join("half-alpha-primary.png");
    image::RgbaImage::from_pixel(100, 80, image::Rgba([255, 0, 0, 128]))
        .save(&half_alpha)
        .unwrap();
    let pixels = compose_slint_background_pair(
        half_alpha.to_str().unwrap(),
        secondary.to_str().unwrap(),
        "diagonal",
        "full",
        "blur",
        0,
        [21, 22, 23],
        (100, 80),
    )
    .unwrap();
    assert_eq!(*pixels.get_pixel(5, 5), image::Rgba([128, 0, 127, 255]));
    assert_eq!(*pixels.get_pixel(50, 40), image::Rgba([64, 0, 191, 255]));

    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn paired_background_blur_applies_to_the_hero_images() {
    let root = std::env::temp_dir().join(format!("estante-slint-pair-blur-{}", std::process::id()));
    std::fs::create_dir_all(&root).unwrap();
    let primary_path = root.join("primary.png");
    let secondary_path = root.join("secondary.png");
    image::RgbaImage::from_fn(100, 80, |x, _| {
        if x % 2 == 0 {
            image::Rgba([255, 0, 0, 255])
        } else {
            image::Rgba([0, 255, 0, 255])
        }
    })
    .save(&primary_path)
    .unwrap();
    image::RgbaImage::from_fn(100, 80, |x, _| {
        if x % 2 == 0 {
            image::Rgba([0, 0, 255, 255])
        } else {
            image::Rgba([255, 255, 255, 255])
        }
    })
    .save(&secondary_path)
    .unwrap();

    let render = |blur| {
        compose_slint_background_pair(
            primary_path.to_str().unwrap(),
            secondary_path.to_str().unwrap(),
            "vertical",
            "full",
            "blur",
            blur,
            [21, 22, 23],
            (100, 80),
        )
        .unwrap()
    };
    let sharp = render(0);
    let blurred = render(8);
    assert_ne!(sharp, blurred);
    assert_eq!(sharp.dimensions(), blurred.dimensions());
    std::fs::remove_dir_all(root).unwrap();
}

#[test]
fn background_blur_matches_qt_multieffect_pyramid_shape() {
    let solid = image::RgbaImage::from_pixel(65, 65, image::Rgba([40, 80, 120, 255]));
    assert_eq!(blur_background_image(&solid, 0), solid);
    assert_eq!(blur_background_image(&solid, 20), solid);

    let edge = image::RgbaImage::from_fn(65, 65, |x, _| {
        let shade = if x < 32 { 10 } else { 240 };
        image::Rgba([shade, shade, shade, 255])
    });
    let blurred = blur_background_image(&edge, 20);
    assert_eq!(blurred.dimensions(), edge.dimensions());
    let shades = [27, 30, 32, 35, 38].map(|x| blurred.get_pixel(x, 32)[0]);
    assert!(shades.windows(2).all(|pair| pair[0] < pair[1]));
    assert!(blurred.pixels().all(|pixel| pixel[3] == 255));
}

#[test]
fn stale_background_results_are_ignored() {
    let generation = AtomicU64::new(8);
    assert!(background_request_is_current(&generation, 8));
    assert!(!background_request_is_current(&generation, 7));
}

#[test]
fn settings_changes_are_saved_immediately_and_preserved_on_close() {
    let adapter = MinimalSoftwareWindow::new(RepaintBufferType::NewBuffer);
    let (tx, _events) = mpsc::channel();
    slint::platform::set_platform(Box::new(SoftwarePlatform(adapter, tx))).unwrap();
    let root = fixture();
    let (window, _timer) = build_window(Library::open(&root), false, None).unwrap();
    window.show().unwrap();

    window.set_showing_settings(true);
    window.set_settings_section(1);
    let save_labels = ["Save appearance", "Guardar apariencia"];
    for label in save_labels {
        assert!(
            i_slint_backend_testing::ElementHandle::find_by_accessible_label(&window, label)
                .next()
                .is_none(),
            "settings should not show a Save button ({label})"
        );
    }

    window.set_list_side("top".into());
    slint::platform::update_timers_and_animations();
    let after_side_change = Library::open(&root).settings().unwrap();
    assert_eq!(
        after_side_change["list_side"],
        "top",
        "autosave state: showing={}, restoring={}, ring={}, status={}",
        window.get_showing_settings(),
        window.get_settings_restoring(),
        window.get_ring_color_text(),
        window.get_save_message()
    );
    window.set_focus_zoom(190);
    slint::platform::update_timers_and_animations();
    let after_zoom_change = Library::open(&root).settings().unwrap();
    assert_eq!(after_zoom_change["list_side"], "top");
    assert_eq!(after_zoom_change["list_focus_zoom"], 190);

    window.invoke_back();
    assert!(!window.get_showing_settings());
    window.set_showing_settings(true);
    assert_eq!(window.get_list_side().as_str(), "top");
    assert_eq!(window.get_focus_zoom(), 190);

    macro_rules! assert_autosaved {
        ($change:expr, $pointer:literal, $expected:expr) => {{
            $change;
            slint::platform::update_timers_and_animations();
            let settings = Library::open(&root).settings().unwrap();
            let expected = json!($expected);
            assert_eq!(
                settings.pointer($pointer),
                Some(&expected),
                "setting {} must persist immediately",
                $pointer
            );
        }};
    }

    assert_autosaved!(window.set_list_side("right".into()), "/list_side", "right");
    assert_autosaved!(window.set_pastel_theme(false), "/ui_color_mode", "system");
    assert_autosaved!(
        window.set_color_theme("combination-176".into()),
        "/ui_theme",
        "combination-176"
    );
    assert_autosaved!(
        window.set_playing_behavior("hide".into()),
        "/playing_behavior",
        "hide"
    );
    assert_autosaved!(
        window.set_start_steam_on_start(true),
        "/start_steam_on_start",
        true
    );
    assert_autosaved!(window.set_start_fullscreen(true), "/start_fullscreen", true);
    assert_autosaved!(
        window.set_start_faugus_on_start(true),
        "/start_faugus_on_start",
        true
    );
    assert_autosaved!(
        window.set_start_heroic_on_start(true),
        "/start_heroic_on_start",
        true
    );
    assert_autosaved!(
        window.set_close_steam_on_exit(true),
        "/close_steam_on_exit",
        true
    );
    assert_autosaved!(
        window.set_close_faugus_on_exit(true),
        "/close_faugus_on_exit",
        true
    );
    assert_autosaved!(
        window.set_close_heroic_on_exit(true),
        "/close_heroic_on_exit",
        true
    );
    assert_autosaved!(
        window.set_controller_type("nintendo".into()),
        "/controller_type",
        "nintendo"
    );
    assert_autosaved!(
        window.set_onscreen_keyboard("system".into()),
        "/onscreen_keyboard",
        "system"
    );
    assert_autosaved!(window.set_language("en".into()), "/language", "en");
    assert_autosaved!(
        window.set_keyboard_fallback(false),
        "/keyboard_fallback",
        false
    );
    assert_autosaved!(
        window.set_check_updates_on_start(true),
        "/check_updates_on_start",
        true
    );
    assert_autosaved!(
        window.set_steamgriddb_key("grid-key".into()),
        "/steamgriddb_key",
        "grid-key"
    );
    assert_autosaved!(
        window.set_igdb_client_id("client-id".into()),
        "/igdb_client_id",
        "client-id"
    );
    assert_autosaved!(
        window.set_igdb_client_secret("client-secret".into()),
        "/igdb_client_secret",
        "client-secret"
    );
    assert_autosaved!(
        window.set_show_session_history(false),
        "/show_session_history",
        false
    );
    assert_autosaved!(
        window.set_screensaver_enabled(true),
        "/screensaver_enabled",
        true
    );
    assert_autosaved!(
        window.set_screensaver_idle_value(9),
        "/screensaver_idle_value",
        9
    );
    assert_autosaved!(
        window.set_screensaver_idle_unit("hours".into()),
        "/screensaver_idle_unit",
        "hours"
    );
    assert_autosaved!(
        window.set_screensaver_slide_value(45),
        "/screensaver_slide_value",
        45
    );
    assert_autosaved!(
        window.set_screensaver_slide_unit("minutes".into()),
        "/screensaver_slide_unit",
        "minutes"
    );
    assert_autosaved!(window.set_screensaver_dim(42), "/screensaver_dim", 42);
    let saver_background = root.join("cover.png").display().to_string();
    assert_autosaved!(
        window.set_screensaver_background(saver_background.clone().into()),
        "/screensaver_background",
        saver_background.clone()
    );
    assert_autosaved!(
        window.set_screensaver_source("application".into()),
        "/screensaver_source",
        "application"
    );
    assert_autosaved!(window.set_focus_zoom(180), "/list_focus_zoom", 180);
    assert_autosaved!(window.set_cover_zoom(125), "/list_cover_zoom", 125);
    assert_autosaved!(
        window.set_list_artwork("square".into()),
        "/list_artwork",
        "square"
    );
    assert_autosaved!(
        window.set_list_artwork_radius(20),
        "/list_artwork_radius",
        20
    );
    assert_autosaved!(
        window.set_background_source("global".into()),
        "/background_source",
        "global"
    );
    let global_background = root.join("banner.png").display().to_string();
    assert_autosaved!(
        window.set_global_background(global_background.clone().into()),
        "/global_background",
        global_background
    );
    assert_autosaved!(
        window.set_background_fill("dominant".into()),
        "/background_fill",
        "dominant"
    );
    assert_autosaved!(
        window.set_hero_position("top".into()),
        "/hero_positions/list",
        "top"
    );
    assert_autosaved!(
        window.set_background_split("horizontal".into()),
        "/background_splits/list",
        "horizontal"
    );
    assert_autosaved!(window.set_dim(55), "/background_dim/list", 55);
    assert_autosaved!(window.set_blur(8), "/background_blur/list", 8);
    assert_autosaved!(window.set_minimal(true), "/minimal_views/list", true);
    assert_autosaved!(
        window.set_launcher_details(false),
        "/show_launcher_details/list",
        false
    );
    assert_autosaved!(
        window.set_show_game_information(false),
        "/show_game_information/list",
        false
    );
    assert_autosaved!(
        window.set_show_detail_cover(false),
        "/show_detail_cover/list",
        false
    );
    assert_autosaved!(
        window.set_cover_format("square".into()),
        "/cover_formats/list",
        "square"
    );
    assert_autosaved!(window.set_cover_radius(24), "/cover_radii/list", 24);
    assert_autosaved!(
        window.set_ring_enabled(false),
        "/selection_rings/list/focus_ring_enabled",
        false
    );
    assert_autosaved!(
        window.set_ring_color_text("#aabbcc".into()),
        "/selection_rings/list/focus_ring_color",
        "#aabbcc"
    );
    assert_autosaved!(
        window.set_ring_width(8),
        "/selection_rings/list/focus_ring_width",
        8
    );
    assert_autosaved!(
        window.set_ring_radius(24),
        "/selection_rings/list/focus_ring_radius",
        24
    );

    window.set_settings_section(2);
    window.set_category_name("Autosave category".into());
    window.invoke_manage_category("add".into(), "Autosave category".into(), "".into());
    let categories_library = Library::open(&root);
    assert!(
        categories_library
            .categories(&categories_library.games())
            .iter()
            .any(|category| category == "Autosave category")
    );

    window.invoke_back();
    assert!(!window.get_showing_settings());
    let after_close = Library::open(&root).settings().unwrap();
    assert_eq!(after_close["list_side"], "right");
    assert_eq!(after_close["list_focus_zoom"], 180);
}

#[test]
fn game_editor_fields_autosave_without_save_buttons() {
    let adapter = MinimalSoftwareWindow::new(RepaintBufferType::NewBuffer);
    let (tx, _events) = mpsc::channel();
    slint::platform::set_platform(Box::new(SoftwarePlatform(adapter, tx))).unwrap();
    let root = fixture();

    let original_executable = root.join("original-game.sh");
    let edited_executable = root.join("edited-game.sh");
    std::fs::write(&original_executable, "#!/bin/sh\nexit 0\n").unwrap();
    std::fs::write(&edited_executable, "#!/bin/sh\nexit 0\n").unwrap();
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(&original_executable, std::fs::Permissions::from_mode(0o755)).unwrap();
    std::fs::set_permissions(&edited_executable, std::fs::Permissions::from_mode(0o755)).unwrap();
    let library_path = root.join("library.json");
    let mut library_data: Value =
        serde_json::from_slice(&std::fs::read(&library_path).unwrap()).unwrap();
    for game in library_data["games"].as_array_mut().unwrap() {
        game["path"] = json!(original_executable.display().to_string());
        game["cwd"] = json!(root.display().to_string());
    }
    std::fs::write(&library_path, serde_json::to_vec(&library_data).unwrap()).unwrap();

    let (window, _timer) = build_window(Library::open(&root), false, None).unwrap();
    window.show().unwrap();
    window.invoke_begin_edit();
    slint::platform::update_timers_and_animations();
    assert!(window.get_showing_editor());
    assert_no_editor_save_buttons(&window);
    let game_id = window.get_edit_id().to_string();

    macro_rules! assert_editor_autosaved {
        ($change:expr, $pointer:literal, $expected:expr) => {{
            $change;
            slint::platform::update_timers_and_animations();
            let game = Library::open(&root)
                .games()
                .into_iter()
                .find(|game| game.id() == game_id)
                .expect("edited game remains in the library");
            let saved = Value::Object(game.data().clone());
            let expected = json!($expected);
            assert_eq!(
                saved.pointer($pointer),
                Some(&expected),
                "editor field {} must persist immediately; status={}, input={}",
                $pointer,
                window.get_save_message(),
                window.get_edit_path()
            );
        }};
    }

    assert_editor_autosaved!(
        window.set_edit_title("Autosaved title".into()),
        "/metadata/title",
        "Autosaved title"
    );
    assert_editor_autosaved!(
        window.set_edit_description("Autosaved description".into()),
        "/metadata/description",
        "Autosaved description"
    );
    assert_editor_autosaved!(
        window.set_edit_synopsis("Autosaved synopsis".into()),
        "/metadata/synopsis",
        "Autosaved synopsis"
    );
    assert_editor_autosaved!(
        window.set_edit_release_date("29/02/2024".into()),
        "/metadata/release_date",
        "2024-02-29"
    );
    assert_editor_autosaved!(
        window.set_edit_developers("Studio A, Studio B, Studio A".into()),
        "/metadata/developers",
        ["Studio A", "Studio B"]
    );
    assert_editor_autosaved!(
        window.set_edit_publishers("Publisher A".into()),
        "/metadata/publishers",
        ["Publisher A"]
    );
    assert_editor_autosaved!(
        window.set_edit_genres("Puzzle, Adventure".into()),
        "/metadata/genres",
        ["Puzzle", "Adventure"]
    );
    assert_editor_autosaved!(
        window.set_edit_platforms("Linux, Steam Deck".into()),
        "/metadata/platforms",
        ["Linux", "Steam Deck"]
    );
    assert_editor_autosaved!(
        window.set_edit_metadata_source("manual-test".into()),
        "/metadata/source",
        "manual-test"
    );
    assert_editor_autosaved!(
        window.set_edit_entity_id("Q12345".into()),
        "/metadata/entity_id",
        "Q12345"
    );
    assert_editor_autosaved!(
        window.set_edit_steam_appid("480".into()),
        "/metadata/steam_appid",
        "480"
    );
    assert_editor_autosaved!(
        window.set_edit_categories("Favoritos, Aventura".into()),
        "/categories",
        ["Favoritos", "Aventura"]
    );

    let banner = root
        .join("banner.png")
        .canonicalize()
        .unwrap()
        .display()
        .to_string();
    let cover = root
        .join("cover.png")
        .canonicalize()
        .unwrap()
        .display()
        .to_string();
    let logo = root
        .join("logo.png")
        .canonicalize()
        .unwrap()
        .display()
        .to_string();
    assert_editor_autosaved!(
        window.set_edit_cover(banner.clone().into()),
        "/cover",
        banner
    );
    assert_editor_autosaved!(
        window.set_edit_square_cover(cover.clone().into()),
        "/square_cover",
        cover
    );
    assert_editor_autosaved!(window.set_edit_logo(logo.clone().into()), "/logo", logo);
    assert_editor_autosaved!(
        window.set_edit_banner(cover.clone().into()),
        "/banner",
        cover
    );
    assert_editor_autosaved!(
        window.set_edit_secondary_background(banner.clone().into()),
        "/banner_secondary",
        banner
    );

    let executable = edited_executable
        .canonicalize()
        .unwrap()
        .display()
        .to_string();
    assert_editor_autosaved!(
        window.set_edit_path(edited_executable.display().to_string().into()),
        "/path",
        executable
    );
    assert_editor_autosaved!(
        window.set_edit_arguments("--version".into()),
        "/arguments",
        "--version"
    );
    let working_directory = root.join("working-directory");
    std::fs::create_dir_all(&working_directory).unwrap();
    let working_directory = working_directory
        .canonicalize()
        .unwrap()
        .display()
        .to_string();
    assert_editor_autosaved!(
        window.set_edit_cwd(working_directory.clone().into()),
        "/cwd",
        working_directory
    );

    window.invoke_back();
    slint::platform::update_timers_and_animations();
    assert!(!window.get_showing_editor());
    let saved = Library::open(&root)
        .games()
        .into_iter()
        .find(|game| game.id() == game_id)
        .unwrap();
    assert_eq!(saved.metadata()["title"], "Autosaved title");
    window.hide().unwrap();
}

#[test]
fn saving_changed_settings_preserves_external_values() {
    let baseline = json!({
        "language": "system",
        "list_zoom": 100,
        "background_dim": {"list": 78}
    });
    let current = json!({
        "language": "system",
        "list_zoom": 130,
        "background_dim": {"list": 78}
    });
    let mut disk = json!({
        "language": "en",
        "list_zoom": 100,
        "background_dim": {"list": 52, "grid": 33}
    });

    merge_changed_settings(&mut disk, &baseline, &current);

    assert_eq!(disk["language"], "en");
    assert_eq!(disk["list_zoom"], 130);
    assert_eq!(disk["background_dim"]["list"], 52);
    assert_eq!(disk["background_dim"]["grid"], 33);
}

#[test]
fn svg_filters_images_and_text_track_qt_reference() {
    let source = Path::new(env!("CARGO_MANIFEST_DIR")).join("testdata/svg-features-qt.svg");
    let actual = rasterize_svg(&source, 128, 80).unwrap();
    let expected =
        image::load_from_memory(include_bytes!("../testdata/svg-features-qt-reference.png"))
            .unwrap()
            .into_rgba8();
    assert_eq!(actual.dimensions(), (128, 80));

    for background in [[20_u8; 3], [240_u8; 3]] {
        for (rows, tolerance) in [(0..45, 2.5), (45..80, 4.0)] {
            // Text metrics vary with system fonts, so its region allows more antialiasing error.
            assert!(svg_region_error(&actual, &expected, 0..90, rows, background) <= tolerance);
        }
    }
    assert!((50..76).any(|y| (0..90).any(|x| actual.get_pixel(x, y).0[3] > 0)));
}

fn svg_region_error(
    actual: &image::RgbaImage,
    expected: &image::RgbaImage,
    x_range: std::ops::Range<u32>,
    y_range: std::ops::Range<u32>,
    background: [u8; 3],
) -> f64 {
    let mut absolute_error = 0_u64;
    for y in y_range.clone() {
        for x in x_range.clone() {
            let actual_pixel = actual.get_pixel(x, y).0;
            let expected_pixel = expected.get_pixel(x, y).0;
            for channel in 0..3 {
                let actual = (u32::from(actual_pixel[channel]) * u32::from(actual_pixel[3])
                    + u32::from(background[channel]) * (255 - u32::from(actual_pixel[3]))
                    + 127)
                    / 255;
                let expected = (u32::from(expected_pixel[channel]) * u32::from(expected_pixel[3])
                    + u32::from(background[channel]) * (255 - u32::from(expected_pixel[3]))
                    + 127)
                    / 255;
                absolute_error += u64::from(actual.abs_diff(expected));
            }
        }
    }
    absolute_error as f64
        / ((x_range.end - x_range.start) * (y_range.end - y_range.start) * 3) as f64
}

#[test]
fn svg_noto_sans_bold_and_italic_track_qt_reference() {
    let source = Path::new(env!("CARGO_MANIFEST_DIR")).join("testdata/svg-noto-sans-qt.svg");
    let actual = rasterize_svg(&source, 128, 80).unwrap();
    let expected =
        image::load_from_memory(include_bytes!("../testdata/svg-noto-sans-qt-reference.png"))
            .unwrap()
            .into_rgba8();
    assert_eq!(actual.dimensions(), (128, 80));

    for background in [[20, 20, 20], [240, 240, 240]] {
        for rows in [4..38, 36..70] {
            let error = svg_region_error(&actual, &expected, 0..128, rows, background);
            assert!(
                error <= 4.0,
                "Noto Sans SVG error on {background:?}: {error}"
            );
        }
    }
}

#[test]
fn svg_color_matrix_and_drop_shadow_track_qt_reference() {
    let source =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("testdata/svg-filter-primitives-qt.svg");
    let actual = rasterize_svg(&source, 220, 90).unwrap();
    let svgz = rasterize_svg(
        &Path::new(env!("CARGO_MANIFEST_DIR")).join("testdata/svg-filter-primitives-qt.svgz"),
        220,
        90,
    )
    .unwrap();
    let expected = image::load_from_memory(include_bytes!(
        "../testdata/svg-filter-primitives-qt-reference.png"
    ))
    .unwrap()
    .into_rgba8();
    assert_eq!(actual.dimensions(), (220, 90));
    assert_eq!(actual, svgz, "SVG and SVGZ rasterization must match");

    for background in [[20, 20, 20], [240, 240, 240]] {
        for (x_range, y_range) in [(8..68, 8..72), (78..138, 8..72), (144..216, 6..72)] {
            let error = svg_region_error(&actual, &expected, x_range, y_range, background);
            assert!(error <= 4.0, "SVG filter error on {background:?}: {error}");
        }
    }
}

#[test]
#[ignore = "set ESTANTE_TEST_LIBRARY to a real profile; this opens it read-only"]
fn slint_loads_the_real_library_in_software_renderer() {
    let root = PathBuf::from(
        std::env::var_os("ESTANTE_TEST_LIBRARY").expect("ESTANTE_TEST_LIBRARY is required"),
    );
    let library = Library::open(&root);
    assert!(library.load_error().is_none(), "real library must load");
    let expected_ids = library
        .games()
        .iter()
        .map(|game| game.id().to_owned())
        .collect::<std::collections::HashSet<_>>();
    assert!(!expected_ids.is_empty(), "real library must contain games");

    let adapter = MinimalSoftwareWindow::new(RepaintBufferType::NewBuffer);
    let (tx, events) = mpsc::channel();
    slint::platform::set_platform(Box::new(SoftwarePlatform(adapter.clone(), tx))).unwrap();
    let (window, _timer) = build_window(library, false, None).unwrap();
    window.show().unwrap();
    window.invoke_category_changed("Todos".into());
    assert_eq!(window.get_games().row_count(), expected_ids.len());
    assert!(
        (0..window.get_games().row_count()).all(|index| {
            window
                .get_games()
                .row_data(index)
                .is_some_and(|row| expected_ids.contains(row.id.as_str()))
        }),
        "Slint rows must come from the real library"
    );

    let capture_root =
        std::env::temp_dir().join(format!("estante-real-library-smoke-{}", std::process::id()));
    std::fs::create_dir_all(&capture_root).unwrap();
    snapshot(&adapter, &capture_root, "real-library", 1280, 800);
    window.hide().unwrap();
    drop(events);
    std::fs::remove_dir_all(capture_root).unwrap();
}
