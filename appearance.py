"""Independent view appearance with compatibility for legacy global ring settings."""
VIEW_NAMES = {'grid': 'Grid', 'carousel': 'Carousel', 'ps5': 'Sense', 'list': 'Lista'}


def cover_format_for(settings, view):
    default = 'square' if view == 'ps5' else 'portrait'
    value = settings.get('cover_formats', {}).get(view, default)
    return value if value in ('square', 'portrait') else default


def list_side_for(settings):
    side = settings.get('list_side', 'left')
    return side if side in ('left', 'right', 'top', 'bottom') else 'left'


def list_navigation(settings):
    side = list_side_for(settings)
    horizontal = side in ('top', 'bottom')
    return (('left', 'right') if horizontal else ('up', 'down'),
            {'left': 'right', 'right': 'left', 'top': 'down', 'bottom': 'up'}[side],
            {'left': 'left', 'right': 'right', 'top': 'up', 'bottom': 'down'}[side])


def list_cover_size(settings):
    zoom = max(.5, min(1.75, float(settings.get('list_cover_zoom', 100)) / 100))
    width, height = (220, 220) if cover_format_for(settings, 'list') == 'square' else (180, 270)
    return round(width * zoom), round(height * zoom)


def cover_size_for(settings, view):
    if view == 'list':
        zoom = max(.5, min(2, float(settings.get('list_zoom', 100)) / 100))
        return round(300 * zoom), round(100 * zoom)
    width = {'grid': 156, 'carousel': 192, 'ps5': 104}[view]
    height = width if cover_format_for(settings, view) == 'square' else round(width * 1.5)
    if view == 'grid':
        zoom = max(.5, min(2, float(settings.get('grid_zoom', 100)) / 100))
        return round(width * zoom), round(height * zoom)
    return width, height
RING_DEFAULTS = {'focus_ring_enabled': True, 'focus_ring_color': '#ffffff',
                 'focus_ring_width': 3, 'focus_ring_radius': 18}


def ring_for(settings, view):
    legacy = {key: settings.get(key, value) for key, value in RING_DEFAULTS.items()}
    return {**legacy, **settings.get('selection_rings', {}).get(view, {})}


def cover_radius_for(settings, view):
    return max(0, min(40, int(settings.get('cover_radii', {}).get(view, 12))))


def with_ring(settings, view, ring):
    # Seed untouched views from their existing appearance, then update only this view.
    rings = {mode: ring_for(settings, mode) for mode in VIEW_NAMES}
    rings[view] = {**rings[view], **ring}
    return {**settings, 'selection_rings': rings}


def hero_position_for(settings, view):
    position = settings.get('hero_positions', {}).get(view, settings.get('hero_position', 'top'))
    return position if position in ('top', 'lower', 'full') else 'top'


def grid_page(games, selected=None, size=12):
    """Bound grid widgets while preserving selection across filters and edits."""
    index = next((i for i, game in enumerate(games) if game['id'] == selected), 0)
    page = index // size
    return games[page * size:(page + 1) * size], page, max(1, (len(games) + size - 1) // size)
