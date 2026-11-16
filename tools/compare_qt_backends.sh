#!/usr/bin/env bash
set -uo pipefail

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(dirname -- "$script_dir")
python_bin="$repo_root/.venv-qt/bin/python"
appimage=${ESTANTE_APPIMAGE-}
wait_seconds=${1:-30}
app_pid=
log_file=
opengl_rss_kib=
opengl_pss_kib=
opengl_anon_kib=
vulkan_rss_kib=
vulkan_pss_kib=
vulkan_anon_kib=

if [[ -n "$appimage" ]]; then
    appimage=$(realpath -e -- "$appimage") || {
        echo "No encuentro el AppImage indicado en ESTANTE_APPIMAGE." >&2
        exit 1
    }
    if [[ ! -x "$appimage" ]]; then
        echo "El AppImage no es ejecutable: $appimage" >&2
        exit 1
    fi
elif [[ ! -x "$python_bin" ]]; then
    echo "No encuentro el Python del proyecto: $python_bin" >&2
    exit 1
fi

if [[ ! "$wait_seconds" =~ ^[0-9]+$ ]] || (( wait_seconds < 1 )); then
    echo "Uso: $0 [segundos_de_espera]" >&2
    exit 2
fi

cd "$repo_root" || exit 1

cleanup() {
    if [[ -n "$app_pid" ]] && kill -0 "$app_pid" 2>/dev/null; then
        kill -TERM "$app_pid" 2>/dev/null || true
        wait "$app_pid" 2>/dev/null || true
    fi
    if [[ -n "$log_file" ]]; then
        rm -f -- "$log_file"
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

app_running() {
    local process_state
    process_state=$(ps -o stat= -p "$app_pid" 2>/dev/null) || return 1
    [[ -n "$process_state" && "$process_state" != Z* ]]
}

run_sample() {
    local backend=$1
    local second=0
    local rss_kib=
    local pss_kib=
    local anon_kib=
    local status=0

    log_file=$(mktemp "/tmp/estante-${backend}.XXXXXX.log") || return 1
    echo
    echo "Iniciando Estante con Qt Quick / $backend."
    if [[ -n "$appimage" ]]; then
        QSG_RHI_BACKEND="$backend" QSG_INFO=1 "$appimage" >"$log_file" 2>&1 &
    else
        QSG_RHI_BACKEND="$backend" QSG_INFO=1 "$python_bin" qt_app/__main__.py >"$log_file" 2>&1 &
    fi
    app_pid=$!

    # Detect startup failures early, before waiting for the measurement interval.
    for ((second=0; second<5; second++)); do
        if ! app_running; then
            wait "$app_pid" || status=$?
            app_pid=
            echo "Estante terminó al iniciar ($backend, código $status)." >&2
            cat "$log_file" >&2
            return 1
        fi
        sleep 1
    done

    echo "Deja la misma biblioteca visible y no navegues durante $wait_seconds s..."
    for ((second=0; second<wait_seconds; second++)); do
        if ! app_running; then
            wait "$app_pid" || status=$?
            app_pid=
            echo "Estante se cerró antes de tomar la muestra ($backend, código $status)." >&2
            cat "$log_file" >&2
            return 1
        fi
        sleep 1
    done

    if [[ ! -r "/proc/$app_pid/smaps_rollup" ]]; then
        echo "No puedo leer /proc/$app_pid/smaps_rollup." >&2
        return 1
    fi

    read -r rss_kib pss_kib anon_kib < <(
        awk '
            /^Rss:/ { rss=$2 }
            /^Pss:/ { pss=$2 }
            /^Anonymous:/ { anon=$2 }
            END { if (rss && pss && anon) print rss, pss, anon }
        ' "/proc/$app_pid/smaps_rollup"
    )
    if [[ -z "$rss_kib" || -z "$pss_kib" || -z "$anon_kib" ]]; then
        echo "No pude leer Rss, Pss y Anonymous para el PID $app_pid." >&2
        return 1
    fi

    printf '\n%s — PID %s — %d s\n' "$backend" "$app_pid" "$wait_seconds"
    awk -v rss="$rss_kib" -v pss="$pss_kib" -v anon="$anon_kib" 'BEGIN {
        printf "  Rss:       %8.1f MiB\n", rss/1024
        printf "  Pss:       %8.1f MiB\n", pss/1024
        printf "  Anonymous: %8.1f MiB\n", anon/1024
    }'
    echo "Mapas anónimos mayores:"
    awk '
        function flush_map() {
            if (map != "" && anon > 0) printf "%10d kB  rss=%10d kB  %s\n", anon, rss, map
        }
        /^[[:xdigit:]]+-[[:xdigit:]]+ / { flush_map(); map=$0; anon=0; rss=0 }
        /^Rss:/ { rss=$2 }
        /^Anonymous:/ { anon=$2 }
        END { flush_map() }
    ' "/proc/$app_pid/smaps" | sort -nr | head -10
    echo "Backend reportado por Qt:"
    grep -Ei 'RHI|Vulkan|OpenGL' "$log_file" | head -8 || true

    if [[ "$backend" == opengl ]]; then
        opengl_rss_kib=$rss_kib
        opengl_pss_kib=$pss_kib
        opengl_anon_kib=$anon_kib
    else
        vulkan_rss_kib=$rss_kib
        vulkan_pss_kib=$pss_kib
        vulkan_anon_kib=$anon_kib
    fi

    echo "Cierra Estante normalmente para iniciar la siguiente prueba."
    wait "$app_pid" || status=$?
    app_pid=
    rm -f -- "$log_file"
    log_file=
}

echo "Comparación Qt Quick: OpenGL frente a Vulkan"
echo "Usa la misma pantalla y biblioteca en ambas pruebas."
echo "Cierra Estante antes de empezar. Espera: $wait_seconds s por backend."
if [[ -n "$appimage" ]]; then
    echo "Ejecutable medido: $appimage"
else
    echo "Ejecutable medido: $python_bin (entorno de desarrollo)"
fi

run_sample opengl || exit $?
run_sample vulkan || exit $?

echo
echo "Comparación terminada. Los valores están en MiB y proceden de smaps_rollup."
awk -v orss="$opengl_rss_kib" -v opss="$opengl_pss_kib" -v oanon="$opengl_anon_kib" \
    -v vrss="$vulkan_rss_kib" -v vpss="$vulkan_pss_kib" -v vanon="$vulkan_anon_kib" 'BEGIN {
    printf "\n%-12s %10s %10s %12s\n", "Backend", "Rss MiB", "Pss MiB", "Anonymous MiB"
    printf "%-12s %10.1f %10.1f %12.1f\n", "OpenGL", orss/1024, opss/1024, oanon/1024
    printf "%-12s %10.1f %10.1f %12.1f\n", "Vulkan", vrss/1024, vpss/1024, vanon/1024
    printf "%-12s %10.1f %10.1f %12.1f\n", "Vulkan-OpenGL", (vrss-orss)/1024, (vpss-opss)/1024, (vanon-oanon)/1024
}'
echo "En la última fila, un valor negativo significa menos memoria con Vulkan."
