use std::{env, process::Command};

pub fn resolve(mode: &str, desktop: &str, cosmic: bool, kde: bool, wayland: bool) -> &'static str {
    match mode {
        "cosmic" => "cosmic",
        "kde" => "kde",
        "system" => "system",
        "builtin" => "builtin",
        "disabled" => "disabled",
        _ if cosmic && desktop.to_lowercase().contains("cosmic") => "cosmic",
        _ if kde => "kde",
        _ if cosmic && wayland => "cosmic",
        _ => "system",
    }
}

pub fn open(mode: &str) -> Result<String, String> {
    let cosmic_installed = program_exists("cosmic-osk");
    let kde_available = kwin_available();
    let provider = resolve(
        mode,
        &env::var("XDG_CURRENT_DESKTOP").unwrap_or_default(),
        cosmic_installed,
        kde_available,
        env::var_os("WAYLAND_DISPLAY").is_some(),
    );
    match provider {
        "cosmic" => {
            if !cosmic_installed {
                return Err("No está instalado cosmic-osk.".into());
            }
            if !env::var_os("LIBEI_SOCKET").is_some_and(|socket| !socket.is_empty())
                && !cosmic_service_available()
                && !portal_supports_eis()
            {
                return Err("COSMIC OSK requiere un compositor/portal con soporte EIS; la sesión actual no lo anuncia.".into());
            }
            command("cosmic-osk", &["show"])?;
            Ok("cosmic".into())
        }
        "kde" => {
            if !kwin_available() {
                return Err("KWin no ofrece un teclado virtual activo. Activa Plasma Keyboard/Maliit en los ajustes de Plasma Wayland.".into());
            }
            busctl(&[
                "call",
                "org.kde.KWin",
                "/VirtualKeyboard",
                "org.kde.kwin.VirtualKeyboard",
                "forceActivate",
                "",
            ])?;
            Ok("kde".into())
        }
        "builtin" => Ok("builtin".into()),
        "disabled" => Err("El teclado en pantalla está desactivado.".into()),
        _ => Err("El compositor no expone un método de entrada nativo genérico; usa COSMIC OSK, KDE/Maliit o el teclado de Estante.".into()),
    }
}

pub fn hide(provider: &str) -> Result<(), String> {
    match provider {
        "cosmic" if program_exists("cosmic-osk") => command("cosmic-osk", &["hide"]),
        "kde" if kwin_available() => busctl(&[
            "set-property",
            "org.kde.KWin",
            "/VirtualKeyboard",
            "org.kde.kwin.VirtualKeyboard",
            "active",
            "b",
            "false",
        ]),
        _ => Ok(()),
    }
}

fn program_exists(program: &str) -> bool {
    env::var_os("PATH").is_some_and(|paths| {
        env::split_paths(&paths).any(|directory| directory.join(program).is_file())
    })
}

fn command(program: &str, args: &[&str]) -> Result<(), String> {
    let output = Command::new(program)
        .args(args)
        .output()
        .map_err(|error| format!("No se pudo iniciar {program}: {error}"))?;
    if output.status.success() {
        Ok(())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_owned())
    }
}

fn busctl(args: &[&str]) -> Result<(), String> {
    let output = Command::new("busctl")
        .arg("--user")
        .args(args)
        .output()
        .map_err(|error| format!("No se pudo consultar D-Bus: {error}"))?;
    if output.status.success() {
        Ok(())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).trim().to_owned())
    }
}

fn kwin_available() -> bool {
    let output = Command::new("busctl")
        .args([
            "--user",
            "get-property",
            "org.kde.KWin",
            "/VirtualKeyboard",
            "org.kde.kwin.VirtualKeyboard",
            "available",
        ])
        .output();
    output.is_ok_and(|output| {
        output.status.success() && String::from_utf8_lossy(&output.stdout).trim() == "b true"
    })
}

fn cosmic_service_available() -> bool {
    Command::new("busctl")
        .args(["--user", "--list"])
        .output()
        .is_ok_and(|output| {
            output.status.success()
                && String::from_utf8_lossy(&output.stdout).contains("com.system76.CosmicComp")
        })
}

fn portal_supports_eis() -> bool {
    Command::new("busctl")
        .args([
            "--user",
            "call",
            "org.freedesktop.portal.Desktop",
            "/org/freedesktop/portal/desktop",
            "org.freedesktop.DBus.Introspectable",
            "Introspect",
            "",
        ])
        .output()
        .is_ok_and(|output| {
            output.status.success()
                && String::from_utf8_lossy(&output.stdout).contains("ConnectToEIS")
        })
}

#[cfg(test)]
mod tests {
    use super::resolve;

    #[test]
    fn automatic_keyboard_selection_matches_desktop_support() {
        assert_eq!(resolve("auto", "COSMIC", true, false, true), "cosmic");
        assert_eq!(resolve("auto", "KDE", true, true, true), "kde");
        assert_eq!(resolve("auto", "GNOME", true, false, true), "cosmic");
        assert_eq!(resolve("auto", "GNOME", false, false, true), "system");
        assert_eq!(resolve("builtin", "COSMIC", true, true, true), "builtin");
    }
}
