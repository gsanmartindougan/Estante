mod artwork;
mod category_icons;
mod connectivity;
mod controls;
mod importers;
mod launchers;
mod metadata;
mod model;
mod power;
mod scraping;
mod slint_ui;
mod supervisor;
mod system_keyboard;
mod updates;

use icu_casemap::CaseMapper;
use serde_json::Value;
use std::{
    fs,
    path::{Path, PathBuf},
};

use unicode_normalization::{UnicodeNormalization, char::canonical_combining_class};

#[cfg(all(target_os = "linux", target_env = "gnu"))]
unsafe extern "C" {
    fn mallopt(param: i32, value: i32) -> i32;
}

fn main() {
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
        return;
    }
    if arguments
        .iter()
        .any(|argument| argument == "--version" || argument == "-V")
    {
        println!("Estante {} (Rust/Slint)", env!("CARGO_PKG_VERSION"));
        return;
    }
    configure_native_allocator();
    if let Err(error) = slint_ui::run() {
        eprintln!("Estante Slint: {error}");
        std::process::exit(1);
    }
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

pub(crate) fn take_resume_file() -> Option<Value> {
    let path = std::env::var_os("ESTANTE_RESUME_FILE").map(PathBuf::from)?;
    let value = serde_json::from_slice::<Value>(&fs::read(&path).ok()?).ok()?;
    if !value.is_object() {
        return None;
    }
    let _ = fs::remove_file(path);
    Some(value)
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
                let parent = path.parent().unwrap_or_else(|| Path::new(""));
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

fn normalize_search(value: &str) -> String {
    CaseMapper::new()
        .fold_string(value)
        .nfkd()
        .filter(|character| canonical_combining_class(*character) == 0)
        .collect()
}

fn title_initial(title: &str) -> char {
    normalize_search(title.trim())
        .chars()
        .next()
        .filter(char::is_ascii_alphabetic)
        .map(|character| character.to_ascii_uppercase())
        .unwrap_or('#')
}
