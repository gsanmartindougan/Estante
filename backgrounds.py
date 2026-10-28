"""Geometry and GTK snapshot composition for two independent backgrounds."""
from pathlib import Path
import gi
gi.require_version('Gdk', '4.0')
gi.require_version('Graphene', '1.0')
gi.require_version('Gsk', '4.0')
from gi.repository import Gdk, Graphene, Gsk

SPLIT_MODES = ('single', 'horizontal', 'vertical', 'diagonal')


BUNDLED_BACKGROUNDS = tuple(sorted((Path(__file__).resolve().parent / 'assets/backgrounds').glob('*')))
DEFAULT_BACKGROUND = 'bundled:6.png'
# Preserve selections saved before the bundled files were numbered.
_BACKGROUND_ALIASES = {'wallhaven-0q5jmr_2560x1440.png': '1.png', 'wallhaven-wqr35p_2560x1440.png': '2.png', 'wallhaven-493jw8_2560x1440.png': '3.png', 'wallhaven-mdglyk_2560x1440.png': '4.png', 'wallhaven-1po36w_2560x1440.png': '5.png', 'wallhaven-dgx11m_2560x1440.png': '6.png', 'pexels-francesco-ungaro-13216333.jpg': '6.png', '7.jpg': '6.png'}


def resolve_background(value):
    if value.startswith('bundled:'):
        name = value.removeprefix('bundled:')
        name = _BACKGROUND_ALIASES.get(name, name)
        return str(next((path for path in BUNDLED_BACKGROUNDS if path.name == name), ''))
    return value


def initial_background_settings(settings, first_run=False):
    if first_run:
        return {**settings, 'background_source': 'global', 'global_background': DEFAULT_BACKGROUND}
    return settings


def background_assets(settings, game, view=None):
    if settings.get('background_source', 'game') == 'global':
        return resolve_background(settings.get('global_background', '')), ''
    secondary = game.get('banner_secondary', '')
    if view is not None and background_split_for(settings, view) == 'single':
        secondary = ''
    return game.get('banner', ''), secondary


def background_split_for(settings, view):
    mode = settings.get('background_splits', {}).get(view, 'single')
    return mode if mode in SPLIT_MODES else 'single'


def split_regions(width, height, mode):
    if mode == 'horizontal':
        return ((0, 0, width, height / 2), (0, height / 2, width, height / 2))
    if mode == 'vertical':
        return ((0, 0, width / 2, height), (width / 2, 0, width / 2, height))
    return ((0, 0, width, height), (0, 0, width, height))


def crop_bounds(texture, region, overscan=1, position='full'):
    x, y, width, height = region
    scale = max(width / texture.get_width(), height / texture.get_height()) * overscan
    image_width, image_height = texture.get_width() * scale, texture.get_height() * scale
    image_y = y if position == 'top' else (y + height - image_height if position == 'lower' else y + (height - image_height) / 2)
    return Graphene.Rect().init(x + (width - image_width) / 2, image_y, image_width, image_height)


def diagonal_axis(width, height):
    # The middle stop follows x/width + y/height = 1, including non-square canvases.
    denominator = width * width + height * height
    return (2 * width * height * height / denominator, 2 * width * width * height / denominator)


def alpha_stops(values):
    stops = []
    for offset, alpha in values:
        color = Gdk.RGBA()
        color.parse(f'rgba(255,255,255,{alpha})')
        stop = Gsk.ColorStop()
        stop.offset, stop.color = offset, color
        stops.append(stop)
    return stops


def paint_split(snapshot, width, height, mode, draw):
    if width <= 0 or height <= 0:
        return
    if mode not in ('horizontal', 'vertical', 'diagonal'):
        draw(0, (0, 0, width, height))
        return
    bounds = Graphene.Rect().init(0, 0, width, height)
    blend = min(128, min(width, height) * .12)
    regions = split_regions(width, height, mode)
    if mode == 'horizontal':
        end = (0, height)
        regions = ((0, 0, width, height / 2 + blend / 2),
                   (0, height / 2 - blend / 2, width, height / 2 + blend / 2))
    elif mode == 'vertical':
        end = (width, 0)
        regions = ((0, 0, width / 2 + blend / 2, height),
                   (width / 2 - blend / 2, 0, width / 2 + blend / 2, height))
    else:
        end = diagonal_axis(width, height)
    distance = (end[0] ** 2 + end[1] ** 2) ** .5
    half_band = blend / distance / 2
    # Keep the second image opaque underneath the fade. Fading both layers
    # separately would leave a dark, partially transparent line at the seam.
    snapshot.push_clip(Graphene.Rect().init(*regions[1]))
    draw(1, regions[1])
    snapshot.pop()
    values = [(0, 1)]
    for index in range(17):
        progress = index / 16
        opacity = 1 - progress * progress * (3 - 2 * progress)
        values.append((.5 - half_band + progress * 2 * half_band, opacity))
    values.append((1, 0))
    snapshot.push_mask(Gsk.MaskMode.ALPHA)
    snapshot.append_linear_gradient(bounds, Graphene.Point().init(0, 0),
                                    Graphene.Point().init(*end), alpha_stops(values))
    snapshot.pop()
    draw(0, regions[0])
    snapshot.pop()


def paint_hero_pair(snapshot, textures, width, height, position, mode):
    if width <= 0 or height <= 0:
        return
    # Each image owns its half of the application, rather than half of a
    # panoramic strip. The hero position only controls cropping within that area.
    paint_split(snapshot, width, height, mode,
                lambda index, region: snapshot.append_texture(
                    textures[index], crop_bounds(textures[index], region, position=position)))
