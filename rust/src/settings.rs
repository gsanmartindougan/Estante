use serde_json::{Map, Value};

#[derive(Clone, Debug)]
pub enum Kind {
    Bool,
    Number(u64, u64),
    Choice(&'static [(&'static str, &'static str)]),
    Text,
    Secret,
    Background,
}

#[derive(Clone, Debug)]
pub struct Spec {
    pub path: Vec<&'static str>,
    pub label: &'static str,
    pub default: Value,
    pub kind: Kind,
}

const LAYOUTS: &[(&str, &str)] = &[
    ("Lista", "list"),
    ("Cuadrícula", "grid"),
    ("Carrusel", "carousel"),
    ("Sense", "ps5"),
];
const UNITS: &[(&str, &str)] = &[("Segundos", "seconds"), ("Minutos", "minutes")];

fn add(
    rows: &mut Vec<Spec>,
    path: &[&'static str],
    label: &'static str,
    default: Value,
    kind: Kind,
) {
    rows.push(Spec {
        path: path.to_vec(),
        label,
        default,
        kind,
    });
}
fn text(rows: &mut Vec<Spec>, key: &'static str, label: &'static str, default: &'static str) {
    add(
        rows,
        &[key],
        label,
        Value::String(default.into()),
        Kind::Text,
    );
}
fn secret(rows: &mut Vec<Spec>, key: &'static str, label: &'static str) {
    add(
        rows,
        &[key],
        label,
        Value::String(String::new()),
        Kind::Secret,
    );
}
fn boolean(rows: &mut Vec<Spec>, key: &'static str, label: &'static str, default: bool) {
    add(rows, &[key], label, Value::Bool(default), Kind::Bool);
}
fn choice(
    rows: &mut Vec<Spec>,
    key: &'static str,
    label: &'static str,
    default: &'static str,
    values: &'static [(&'static str, &'static str)],
) {
    add(
        rows,
        &[key],
        label,
        Value::String(default.into()),
        Kind::Choice(values),
    );
}
fn number(
    rows: &mut Vec<Spec>,
    key: &'static str,
    label: &'static str,
    default: u64,
    min: u64,
    max: u64,
) {
    add(
        rows,
        &[key],
        label,
        Value::from(default),
        Kind::Number(min, max),
    );
}

pub fn specs() -> Vec<Spec> {
    let mut rows = Vec::new();
    choice(
        &mut rows,
        "layout",
        "Presentación de la biblioteca",
        "grid",
        LAYOUTS,
    );
    choice(
        &mut rows,
        "ui_color_mode",
        "Colores de la interfaz",
        "pastel",
        &[("Tonos pastel", "pastel"), ("Tema del sistema", "system")],
    );
    choice(
        &mut rows,
        "language",
        "Idioma",
        "system",
        &[("Sistema", "system"), ("Español", "es"), ("English", "en")],
    );
    choice(
        &mut rows,
        "controller_type",
        "Tipo de mando",
        "xbox",
        &[("Sony", "sony"), ("Xbox", "xbox"), ("Nintendo", "nintendo")],
    );
    choice(
        &mut rows,
        "onscreen_keyboard",
        "Teclado en pantalla",
        "auto",
        &[
            ("Automático", "auto"),
            ("Sistema", "system"),
            ("COSMIC OSK", "cosmic"),
            ("KDE / Maliit", "kde"),
            ("Teclado de Estante", "builtin"),
            ("Desactivado", "disabled"),
        ],
    );
    boolean(
        &mut rows,
        "keyboard_fallback",
        "Usar teclado de Estante si falla el del sistema",
        true,
    );
    boolean(
        &mut rows,
        "start_fullscreen",
        "Iniciar a pantalla completa",
        true,
    );
    boolean(
        &mut rows,
        "close_steam_on_exit",
        "Cerrar Steam al salir",
        false,
    );
    boolean(
        &mut rows,
        "start_heroic_on_start",
        "Abrir Heroic al iniciar",
        false,
    );
    boolean(
        &mut rows,
        "close_heroic_on_exit",
        "Cerrar Heroic al salir",
        false,
    );
    boolean(
        &mut rows,
        "close_faugus_on_exit",
        "Cerrar Faugus al salir",
        false,
    );
    boolean(
        &mut rows,
        "start_faugus_on_start",
        "Abrir Faugus al iniciar",
        false,
    );
    boolean(
        &mut rows,
        "start_steam_on_start",
        "Abrir Steam al iniciar",
        false,
    );
    boolean(
        &mut rows,
        "show_session_history",
        "Mostrar historial de sesiones",
        true,
    );
    boolean(
        &mut rows,
        "check_updates_on_start",
        "Buscar actualizaciones al iniciar",
        false,
    );
    choice(
        &mut rows,
        "playing_behavior",
        "Mientras se juega",
        "none",
        &[
            ("Mantener abierto", "none"),
            ("Ocultar y restaurar", "hide"),
            ("Salvapantallas", "screensaver"),
            ("Bandeja del sistema", "tray"),
        ],
    );
    choice(
        &mut rows,
        "background_source",
        "Origen del fondo",
        "game",
        &[("Fondo del juego", "game"), ("Fondo global", "global")],
    );
    text(
        &mut rows,
        "global_background",
        "Fondo global · ruta o bundled:6.png",
        "bundled:6.png",
    );
    choice(
        &mut rows,
        "background_fill",
        "Relleno del fondo",
        "blur",
        &[("Desenfoque", "blur"), ("Color dominante", "dominant")],
    );
    secret(&mut rows, "steamgriddb_key", "Clave de SteamGridDB");
    text(&mut rows, "igdb_client_id", "IGDB Client ID", "");
    secret(&mut rows, "igdb_client_secret", "IGDB Client Secret");
    boolean(
        &mut rows,
        "screensaver_enabled",
        "Activar salvapantallas",
        false,
    );
    number(
        &mut rows,
        "screensaver_idle_value",
        "Inactividad antes de activar",
        5,
        1,
        60,
    );
    choice(
        &mut rows,
        "screensaver_idle_unit",
        "Unidad de inactividad",
        "minutes",
        UNITS,
    );
    number(
        &mut rows,
        "screensaver_slide_value",
        "Intervalo entre fondos",
        15,
        1,
        60,
    );
    choice(
        &mut rows,
        "screensaver_slide_unit",
        "Unidad del intervalo",
        "seconds",
        UNITS,
    );
    number(
        &mut rows,
        "screensaver_dim",
        "Oscurecimiento del salvapantallas (%)",
        35,
        0,
        100,
    );
    choice(
        &mut rows,
        "screensaver_source",
        "Fondos del salvapantallas",
        "games",
        &[
            ("Juegos", "games"),
            ("Fondo de la aplicación", "application"),
        ],
    );
    add(
        &mut rows,
        &["screensaver_background"],
        "Fondo del salvapantallas",
        Value::String("bundled:6.png".into()),
        Kind::Background,
    );

    const MODES: &[(&str, &str)] = &[
        ("list", "Lista"),
        ("grid", "Cuadrícula"),
        ("carousel", "Carrusel"),
        ("ps5", "Sense"),
    ];
    for (mode, label) in MODES {
        boolean(&mut rows, "minimal_views", label, false);
        rows.last_mut().unwrap().path = vec!["minimal_views", mode];
        for (key, title, default, max) in [
            ("background_dim", "Oscurecimiento del fondo (%)", 50, 100),
            ("background_blur", "Desenfoque del fondo (px)", 0, 40),
            ("cover_radii", "Redondeado de carátula", 12, 40),
        ] {
            number(&mut rows, key, title, default, 0, max);
            rows.last_mut().unwrap().path = vec![key, mode];
        }
        choice_nested(
            &mut rows,
            "cover_formats",
            mode,
            "Formato de carátula",
            if *mode == "ps5" { "square" } else { "portrait" },
            &[("Vertical", "portrait"), ("Cuadrado", "square")],
        );
        choice_nested(
            &mut rows,
            "hero_positions",
            mode,
            "Posición del fondo",
            "full",
            &[("Completo", "full"), ("Arriba", "top"), ("Abajo", "lower")],
        );
        boolean(
            &mut rows,
            "show_launcher_details",
            "Mostrar datos del lanzador",
            true,
        );
        rows.last_mut().unwrap().path = vec!["show_launcher_details", mode];
    }
    for (key, label, default, min, max) in [
        ("list_zoom", "Tamaño de logos en lista", 100, 50, 200),
        (
            "list_focus_zoom",
            "Ampliación del logo seleccionado",
            150,
            100,
            250,
        ),
        (
            "list_cover_zoom",
            "Tamaño de carátula en lista",
            100,
            50,
            175,
        ),
        ("carousel_zoom", "Ampliación del carrusel", 100, 100, 175),
        ("grid_zoom", "Tamaño de cuadrícula", 100, 50, 200),
        ("ps5_focus_size", "Tamaño de selección Sense", 250, 104, 320),
    ] {
        number(&mut rows, key, label, default, min, max);
    }
    choice(
        &mut rows,
        "list_side",
        "Posición de lista",
        "bottom",
        &[
            ("Izquierda", "left"),
            ("Derecha", "right"),
            ("Arriba", "top"),
            ("Abajo", "bottom"),
        ],
    );
    number(&mut rows, "grid_page_size", "Juegos por página", 10, 1, 100);
    choice(
        &mut rows,
        "carousel_position",
        "Posición del carrusel",
        "top",
        &[("Arriba", "top"), ("Abajo", "bottom")],
    );
    boolean(&mut rows, "ps5_motion", "Animación Sense", true);
    rows
}

fn choice_nested(
    rows: &mut Vec<Spec>,
    key: &'static str,
    mode: &'static str,
    label: &'static str,
    default: &'static str,
    values: &'static [(&'static str, &'static str)],
) {
    add(
        rows,
        &[key, mode],
        label,
        Value::String(default.into()),
        Kind::Choice(values),
    );
}
pub fn initialize(settings: &mut Value) {
    if !settings.is_object() {
        *settings = Value::Object(Map::new());
    }
    for spec in specs() {
        let mut current = &*settings;
        let exists = spec.path.iter().all(|key| {
            if let Some(next) = current.get(*key) {
                current = next;
                true
            } else {
                false
            }
        });
        if !exists {
            let path = spec
                .path
                .iter()
                .map(|part| (*part).to_owned())
                .collect::<Vec<_>>();
            let _ = insert_default(settings, &path, spec.default);
        }
    }
    settings["background_splits"] = serde_json::json!({
        "list": "single",
        "grid": "single",
        "carousel": "single",
        "ps5": "single"
    });
}

fn insert_default(settings: &mut Value, path: &[String], value: Value) {
    let mut current = settings;
    for key in &path[..path.len() - 1] {
        if !current.get(key).is_some_and(Value::is_object) {
            current[key] = Value::Object(Map::new());
        }
        current = current.get_mut(key).unwrap();
    }
    if current.get(&path[path.len() - 1]).is_none() {
        current[path[path.len() - 1].as_str()] = value;
    }
}

#[cfg(test)]
mod tests {
    use super::initialize;
    use serde_json::json;

    #[test]
    fn old_per_view_background_splits_are_forced_to_one_background() {
        let mut settings = json!({
            "background_splits": {
                "list": "horizontal",
                "grid": "vertical",
                "carousel": "diagonal",
                "ps5": "horizontal"
            }
        });
        initialize(&mut settings);
        for view in ["list", "grid", "carousel", "ps5"] {
            assert_eq!(settings["background_splits"][view], "single");
        }
    }
}

pub fn read<'a>(settings: &'a Value, spec: &Spec) -> Option<&'a Value> {
    let mut value = settings;
    for key in &spec.path {
        let Some(next) = value.get(*key) else {
            return None;
        };
        value = next;
    }
    Some(value)
}

pub fn update(settings: &mut Value, path: &[String], value: Value) -> Result<(), String> {
    let spec = specs()
        .into_iter()
        .find(|spec| {
            spec.path
                .iter()
                .map(|key| *key)
                .eq(path.iter().map(String::as_str))
        })
        .ok_or_else(|| "Ajuste desconocido.".to_owned())?;
    match spec.kind {
        Kind::Bool if !value.is_boolean() => return Err("El ajuste debe ser booleano.".into()),
        Kind::Number(min, max) => {
            value
                .as_u64()
                .filter(|number| (*number >= min) && (*number <= max))
                .ok_or_else(|| format!("El valor debe estar entre {min} y {max}."))?;
        }
        Kind::Choice(choices) => {
            if !value
                .as_str()
                .is_some_and(|chosen| choices.iter().any(|(_, item)| *item == chosen))
            {
                return Err("Opción no válida.".into());
            }
        }
        Kind::Text | Kind::Secret | Kind::Background => {
            if !value.as_str().is_some_and(|text| !text.contains('\0')) {
                return Err("Texto no válido.".into());
            }
        }
        Kind::Bool => (),
    }
    if !settings.is_object() {
        *settings = Value::Object(Map::new());
    }
    let mut current = settings;
    for key in &path[..path.len() - 1] {
        if !current.get(key).is_some_and(Value::is_object) {
            current[key] = Value::Object(Map::new());
        }
        current = current.get_mut(key).unwrap();
    }
    current[path[path.len() - 1].as_str()] = value;
    Ok(())
}

pub fn group(path: &[&str]) -> &'static str {
    if matches!(
        path.get(1).copied(),
        Some("list" | "grid" | "carousel" | "ps5")
    ) {
        return match path[1] {
            "list" => "list",
            "grid" => "grid",
            "carousel" => "carousel",
            _ => "ps5",
        };
    }
    match path.first().copied().unwrap_or("") {
        "steamgriddb_key" | "igdb_client_id" | "igdb_client_secret" => "scan",
        "list_side" | "list_zoom" | "list_focus_zoom" | "list_cover_zoom" => "list",
        "grid_page_size" | "grid_zoom" => "grid",
        "carousel_position" | "carousel_zoom" => "carousel",
        "ps5_motion" | "ps5_focus_size" => "ps5",
        _ => "global",
    }
}
