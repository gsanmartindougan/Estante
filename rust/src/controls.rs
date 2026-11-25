use std::collections::{BTreeMap, BTreeSet};
use std::ffi::{CString, c_char, c_int, c_void};
use std::time::{Duration, Instant};

#[derive(Default)]
pub struct Repeater {
    held: BTreeSet<&'static str>,
    deadlines: BTreeMap<&'static str, Instant>,
}

impl Repeater {
    pub fn update(&mut self, pressed: BTreeSet<&'static str>, now: Instant) -> Vec<&'static str> {
        let mut actions = Vec::new();
        for action in &pressed {
            match self.deadlines.get(action) {
                None => {
                    actions.push(*action);
                    self.deadlines
                        .insert(action, now + Duration::from_millis(400));
                }
                Some(deadline)
                    if matches!(
                        *action,
                        "left" | "right" | "up" | "down" | "page_previous" | "page_next"
                    ) && now >= *deadline =>
                {
                    actions.push(*action);
                    self.deadlines
                        .insert(action, now + Duration::from_millis(130));
                }
                _ => (),
            }
        }
        self.held = pressed;
        self.deadlines.retain(|key, _| self.held.contains(key));
        actions
    }
}

#[derive(Default)]
pub struct BumperChord {
    held: BTreeSet<&'static str>,
    chord: bool,
}

impl BumperChord {
    pub fn update(&mut self, pressed: &BTreeSet<&'static str>) -> Vec<&'static str> {
        let bumpers = pressed
            .intersection(&BTreeSet::from(["page_previous", "page_next"]))
            .copied()
            .collect::<BTreeSet<_>>();
        let mut actions = Vec::new();
        if bumpers.len() == 2 && !self.chord {
            self.chord = true;
            actions.push("appearance");
        }
        if bumpers.is_empty() {
            if !self.chord {
                actions.extend(self.held.iter().copied());
            }
            self.chord = false;
        }
        self.held = bumpers;
        actions
    }
}

type Init = unsafe extern "C" fn(u32) -> c_int;
type Quit = unsafe extern "C" fn(u32);
type NumJoysticks = unsafe extern "C" fn() -> c_int;
type IsController = unsafe extern "C" fn(c_int) -> c_int;
type OpenController = unsafe extern "C" fn(c_int) -> *mut c_void;
type CloseController = unsafe extern "C" fn(*mut c_void);
type Attached = unsafe extern "C" fn(*mut c_void) -> c_int;
type Button = unsafe extern "C" fn(*mut c_void, c_int) -> u8;
type Axis = unsafe extern "C" fn(*mut c_void, c_int) -> i16;
type Update = unsafe extern "C" fn();
type PumpEvents = unsafe extern "C" fn();
type Hint = unsafe extern "C" fn(*const c_char, *const c_char) -> c_int;

const GAMEPAD_BUTTON_ACTIONS: [(c_int, &str); 14] = [
    (0, "confirm"),
    (1, "back"),
    (2, "play"),
    (3, "save"),
    (4, "search"),
    (6, "menu"),
    (7, "left_stick"),
    (8, "right_stick"),
    (9, "page_previous"),
    (10, "page_next"),
    (11, "up"),
    (12, "down"),
    (13, "left"),
    (14, "right"),
];

#[link(name = "dl")]
unsafe extern "C" {
    fn dlopen(filename: *const c_char, flags: c_int) -> *mut c_void;
    fn dlsym(handle: *mut c_void, symbol: *const c_char) -> *mut c_void;
    fn dlclose(handle: *mut c_void) -> c_int;
}

pub struct Gamepad {
    library: *mut c_void,
    controller: *mut c_void,
    quit: Quit,
    num_joysticks: NumJoysticks,
    is_controller: IsController,
    open_controller: OpenController,
    close_controller: CloseController,
    attached: Attached,
    button: Button,
    axis: Axis,
    update_sdl: Update,
    pump_events: PumpEvents,
    repeater: Repeater,
    bumpers: BumperChord,
    sticks: BumperChord,
    scan_at: Instant,
    neutral_ready: bool,
    cursor_axis: (i16, i16),
    scroll_axis: (i16, i16),
}

impl Gamepad {
    pub fn open() -> Result<Self, String> {
        let library = ["libSDL2-2.0.so.0", "libSDL2.so"]
            .iter()
            .filter_map(|path| CString::new(*path).ok())
            .find_map(|path| {
                // SAFETY: dlopen receives a valid nul-terminated library name.
                let handle = unsafe { dlopen(path.as_ptr(), 2) };
                (!handle.is_null()).then_some(handle)
            })
            .ok_or_else(|| "Instala SDL2 para usar un mando.".to_owned())?;
        macro_rules! symbol {
            ($name:literal, $kind:ty) => {{
                let name = CString::new($name).expect("static symbol name");
                // SAFETY: the symbol is checked before casting to the matching SDL signature.
                let pointer = unsafe { dlsym(library, name.as_ptr()) };
                if pointer.is_null() {
                    // SAFETY: library was returned by dlopen above.
                    unsafe { dlclose(library) };
                    return Err(format!("SDL2 no ofrece {}.", $name));
                }
                // SAFETY: SDL exports each symbol with this declared C signature.
                unsafe { std::mem::transmute::<*mut c_void, $kind>(pointer) }
            }};
        }
        let init = symbol!("SDL_InitSubSystem", Init);
        let quit = symbol!("SDL_QuitSubSystem", Quit);
        let num_joysticks = symbol!("SDL_NumJoysticks", NumJoysticks);
        let is_controller = symbol!("SDL_IsGameController", IsController);
        let open_controller = symbol!("SDL_GameControllerOpen", OpenController);
        let close_controller = symbol!("SDL_GameControllerClose", CloseController);
        let attached = symbol!("SDL_GameControllerGetAttached", Attached);
        let button = symbol!("SDL_GameControllerGetButton", Button);
        let axis = symbol!("SDL_GameControllerGetAxis", Axis);
        let update_sdl = symbol!("SDL_GameControllerUpdate", Update);
        let pump_events = symbol!("SDL_PumpEvents", PumpEvents);
        let set_hint: Hint = symbol!("SDL_SetHint", Hint);
        // SAFETY: SDL subsystem and hint APIs accept the constants and valid strings below.
        unsafe {
            set_hint(
                c"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS".as_ptr(),
                c"1".as_ptr(),
            );
            if init(0x2000) < 0 {
                dlclose(library);
                return Err("No se pudo iniciar la lectura del mando con SDL2.".into());
            }
        }
        Ok(Self {
            library,
            controller: std::ptr::null_mut(),
            quit,
            num_joysticks,
            is_controller,
            open_controller,
            close_controller,
            attached,
            button,
            axis,
            update_sdl,
            pump_events,
            repeater: Repeater::default(),
            bumpers: BumperChord::default(),
            sticks: BumperChord::default(),
            scan_at: Instant::now(),
            neutral_ready: false,
            cursor_axis: (0, 0),
            scroll_axis: (0, 0),
        })
    }

    pub fn poll(&mut self, active: bool, cursor_mode: bool) -> Vec<&'static str> {
        // SAFETY: controller and SDL function pointers belong to this initialized instance.
        unsafe {
            (self.pump_events)();
            (self.update_sdl)();
            if !self.controller.is_null() && (self.attached)(self.controller) == 0 {
                (self.close_controller)(self.controller);
                self.controller = std::ptr::null_mut();
                self.neutral_ready = false;
            }
            if self.controller.is_null() && Instant::now() >= self.scan_at {
                self.scan_at = Instant::now() + Duration::from_millis(250);
                for index in 0..(self.num_joysticks)() {
                    if (self.is_controller)(index) != 0 {
                        self.controller = (self.open_controller)(index);
                        if !self.controller.is_null() {
                            self.neutral_ready = false;
                            break;
                        }
                    }
                }
            }
            let mut pressed = BTreeSet::new();
            self.cursor_axis = (0, 0);
            self.scroll_axis = (0, 0);
            if !self.controller.is_null() {
                for (index, action) in GAMEPAD_BUTTON_ACTIONS {
                    if (self.button)(self.controller, index) != 0 {
                        pressed.insert(action);
                    }
                }
                let x = (self.axis)(self.controller, 0);
                let y = (self.axis)(self.controller, 1);
                self.scroll_axis = (
                    (self.axis)(self.controller, 2),
                    (self.axis)(self.controller, 3),
                );
                for (axis, action) in [(4, "category_previous"), (5, "category_next")] {
                    if (self.axis)(self.controller, axis) > 16_000 {
                        pressed.insert(action);
                    }
                }
                self.cursor_axis = (x, y);
                if !cursor_mode && i32::from(x).abs().max(i32::from(y).abs()) > 16_000 {
                    pressed.insert(if i32::from(x).abs() > i32::from(y).abs() {
                        if x > 0 { "right" } else { "left" }
                    } else if y > 0 {
                        "down"
                    } else {
                        "up"
                    });
                }
            }
            if !active {
                self.cursor_axis = (0, 0);
                self.scroll_axis = (0, 0);
                self.neutral_ready = false;
                self.repeater.update(BTreeSet::new(), Instant::now());
                self.bumpers.update(&BTreeSet::new());
                self.sticks.update(&BTreeSet::new());
                return Vec::new();
            }
            if !self.neutral_ready {
                self.neutral_ready = pressed.is_empty();
                pressed.clear();
            }
            let mut regular = pressed.clone();
            regular.retain(|action| {
                !matches!(
                    *action,
                    "page_previous" | "page_next" | "left_stick" | "right_stick"
                )
            });
            let mut actions = self.repeater.update(regular, Instant::now());
            actions.extend(self.bumpers.update(&pressed));
            let stick_pressed = pressed
                .iter()
                .filter_map(|action| match *action {
                    "left_stick" => Some("page_previous"),
                    "right_stick" => Some("page_next"),
                    _ => None,
                })
                .collect::<BTreeSet<_>>();
            actions.extend(self.sticks.update(&stick_pressed).into_iter().map(
                |action| match action {
                    "page_previous" => "grid_page_previous",
                    "page_next" => "grid_page_next",
                    _ => "appearance_settings",
                },
            ));
            actions
        }
    }

    pub fn is_connected(&self) -> bool {
        !self.controller.is_null()
    }

    pub fn cursor_axis(&self) -> (f32, f32) {
        (
            normalize_stick_axis(self.cursor_axis.0),
            normalize_stick_axis(self.cursor_axis.1),
        )
    }

    pub fn scroll_axis(&self) -> (f32, f32) {
        (
            normalize_stick_axis(self.scroll_axis.0),
            normalize_stick_axis(self.scroll_axis.1),
        )
    }
}

fn normalize_stick_axis(axis: i16) -> f32 {
    let value = f32::from(axis) / f32::from(i16::MAX);
    if value.abs() < 0.18 {
        0.0
    } else {
        value.signum() * (value.abs() - 0.18) / 0.82
    }
}

impl Drop for Gamepad {
    fn drop(&mut self) {
        // SAFETY: resources are released once and only while their library is still loaded.
        unsafe {
            if !self.controller.is_null() {
                (self.close_controller)(self.controller);
            }
            (self.quit)(0x2000);
            dlclose(self.library);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{BumperChord, GAMEPAD_BUTTON_ACTIONS, Gamepad, dlsym};
    use std::{
        collections::BTreeSet,
        ffi::{c_int, c_void},
        time::Instant,
    };

    #[test]
    fn sdl_buttons_match_qt_gamepad_actions() {
        assert_eq!(
            GAMEPAD_BUTTON_ACTIONS,
            [
                (0, "confirm"),
                (1, "back"),
                (2, "play"),
                (3, "save"),
                (4, "search"),
                (6, "menu"),
                (7, "left_stick"),
                (8, "right_stick"),
                (9, "page_previous"),
                (10, "page_next"),
                (11, "up"),
                (12, "down"),
                (13, "left"),
                (14, "right"),
            ]
        );
    }

    #[test]
    fn shoulder_buttons_keep_their_letter_actions() {
        let mut bumpers = BumperChord::default();
        for (action, expected) in [
            ("page_previous", "page_previous"),
            ("page_next", "page_next"),
        ] {
            assert!(bumpers.update(&BTreeSet::from([action])).is_empty());
            assert_eq!(bumpers.update(&BTreeSet::new()), vec![expected]);
        }
    }

    #[test]
    fn pressing_both_shoulders_keeps_the_chord_action() {
        let mut bumpers = BumperChord::default();
        assert!(
            bumpers
                .update(&BTreeSet::from(["page_previous", "page_next"]))
                .contains(&"appearance")
        );
        assert!(bumpers.update(&BTreeSet::new()).is_empty());
    }

    #[test]
    fn detects_a_controller_connected_after_startup() {
        type AttachVirtual = unsafe extern "C" fn(c_int, c_int, c_int, c_int) -> c_int;
        type DetachVirtual = unsafe extern "C" fn(c_int) -> c_int;
        type GetJoystick = unsafe extern "C" fn(*mut c_void) -> *mut c_void;
        type SetVirtualButton = unsafe extern "C" fn(*mut c_void, c_int, u8) -> c_int;

        let Ok(mut gamepad) = Gamepad::open() else {
            return;
        };
        gamepad.poll(false, false);
        if gamepad.is_connected() {
            return;
        }
        // SAFETY: optional SDL test symbols are checked and cast to their documented signatures.
        let (attach, detach, get_joystick, set_button): (
            AttachVirtual,
            DetachVirtual,
            Option<GetJoystick>,
            Option<SetVirtualButton>,
        ) = unsafe {
            let attach = dlsym(gamepad.library, c"SDL_JoystickAttachVirtual".as_ptr());
            let detach = dlsym(gamepad.library, c"SDL_JoystickDetachVirtual".as_ptr());
            if attach.is_null() || detach.is_null() {
                return;
            }
            let get_joystick = dlsym(gamepad.library, c"SDL_GameControllerGetJoystick".as_ptr());
            let set_button = dlsym(gamepad.library, c"SDL_JoystickSetVirtualButton".as_ptr());
            (
                std::mem::transmute(attach),
                std::mem::transmute(detach),
                (!get_joystick.is_null()).then(|| std::mem::transmute(get_joystick)),
                (!set_button.is_null()).then(|| std::mem::transmute(set_button)),
            )
        };
        let index = unsafe { attach(1, 6, 15, 1) };
        assert!(index >= 0, "SDL must attach a virtual game controller");
        let deadline = Instant::now() + std::time::Duration::from_secs(2);
        while !gamepad.is_connected() && Instant::now() < deadline {
            gamepad.poll(false, false);
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        if let (Some(get_joystick), Some(set_button)) = (get_joystick, set_button) {
            gamepad.poll(true, false);
            let joystick = unsafe { get_joystick(gamepad.controller) };
            assert!(!joystick.is_null());
            assert_eq!(unsafe { set_button(joystick, 0, 1) }, 0);
            assert!(gamepad.poll(true, false).contains(&"confirm"));
            unsafe { set_button(joystick, 0, 0) };
        }
        unsafe { detach(index) };
        assert!(
            gamepad.is_connected(),
            "a newly attached controller is detected"
        );
    }
}
