fn main() {
    let configuration =
        slint_build::CompilerConfiguration::new().with_debug_info(cfg!(debug_assertions));
    slint_build::compile_with_config("ui/list.slint", configuration)
        .expect("could not compile Slint UI");
}
