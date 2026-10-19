"""Independent view appearance with compatibility for legacy global ring settings."""
VIEW_NAMES = {'grid': 'Grid', 'carousel': 'Carousel', 'ps5': 'Sense'}


def cover_format_for(settings, view):
    default = 'square' if view == 'ps5' else 'portrait'
    value = settings.get('cover_formats', {}).get(view, default)
    return value if value in ('square', 'portrait') else default


def cover_size_for(settings, view):
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
