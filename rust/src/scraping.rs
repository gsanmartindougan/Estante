use crate::{metadata, model::Library};
use serde_json::{Map, Value};
use std::{
    path::PathBuf,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
};

pub fn run(
    root: PathBuf,
    steamgriddb_key: String,
    language: String,
    replace: bool,
    cancelled: Arc<AtomicBool>,
    fields: &[&str],
    include_info: bool,
) -> Result<(usize, usize, Vec<String>), String> {
    let source = Library::open(&root);
    if let Some(error) = source.load_error() {
        return Err(error.to_owned());
    }
    let originals = source.games();
    let artwork_cache = source.artwork_cache_dir();
    let metadata_cache = source.metadata_cache_dir();
    let mut results = Vec::with_capacity(originals.len());
    let mut errors = Vec::new();
    let mut error_count = 0;
    for game in originals {
        if cancelled.load(Ordering::Relaxed) {
            break;
        }
        let (patch, issues) = metadata::scrape_game(
            game.title(),
            game.data(),
            &steamgriddb_key,
            &artwork_cache,
            &metadata_cache,
            replace,
            &language,
            fields,
            include_info,
        );
        error_count += issues.len();
        for issue in issues.into_iter().take(5usize.saturating_sub(errors.len())) {
            errors.push(format!("{}: {issue}", game.title()));
        }
        if !patch.is_empty() {
            results.push((game.id().to_owned(), game.data().clone(), patch));
        }
    }
    let was_cancelled = cancelled.load(Ordering::Relaxed);

    // Re-read before commit: a manual edit made during scraping wins field by field.
    let mut current_library = Library::open(&root);
    if let Some(error) = current_library.load_error() {
        return Err(error.to_owned());
    }
    let current = current_library
        .games()
        .into_iter()
        .map(|game| (game.id().to_owned(), game.data().clone()))
        .collect::<std::collections::HashMap<_, _>>();
    let mut updates: Vec<(String, Map<String, Value>)> = Vec::new();
    for (id, original, patch) in results {
        let Some(latest) = current.get(&id) else {
            continue;
        };
        let mut merged = latest.clone();
        for (field, value) in patch {
            if field == "metadata" {
                let Some(patch_metadata) = value.as_object() else {
                    continue;
                };
                if original.get("metadata") == latest.get("metadata") {
                    merged.insert(field, value);
                } else if let (Some(before), Some(after)) = (
                    original.get("metadata").and_then(Value::as_object),
                    merged.get_mut("metadata").and_then(Value::as_object_mut),
                ) {
                    for (key, value) in patch_metadata {
                        if before.get(key) == after.get(key) {
                            after.insert(key.clone(), value.clone());
                        }
                    }
                }
            } else if latest.get(&field) == original.get(&field) {
                merged.insert(field, value);
            }
        }
        if &merged != latest {
            updates.push((id, merged));
        }
    }
    let updated = updates.len();
    if updated > 0 {
        current_library
            .update_games(&updates)
            .map_err(|error| error.to_string())?;
    }
    if was_cancelled {
        errors.push("Scraping cancelado; se guardaron los resultados completados.".into());
    }
    Ok((updated, error_count, errors))
}
