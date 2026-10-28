"""Select the native or built-in keyboard without configuring the desktop."""
MODES = ('auto', 'system', 'cosmic', 'kde', 'builtin', 'disabled')


def provider(mode='auto', *, desktop='', cosmic=False, kde=False, wayland=False):
    if mode not in MODES: mode='auto'
    if mode!='auto': return mode
    if cosmic and 'cosmic' in desktop.lower(): return 'cosmic'
    if kde: return 'kde'
    if cosmic and wayland: return 'cosmic'
    return 'system'


def cosmic_connection_supported(services, portal_xml='', libei_socket=''):
    """COSMIC OSK needs its compositor's EI endpoint, LIBEI_SOCKET or RemoteDesktop EIS."""
    if libei_socket or 'com.system76.CosmicComp' in services: return True
    from xml.etree import ElementTree
    try:
        root=ElementTree.fromstring(portal_xml)
    except ElementTree.ParseError:
        return False
    return any(interface.get('name')=='org.freedesktop.portal.RemoteDesktop'
               and any(method.get('name')=='ConnectToEIS' for method in interface.findall('method'))
               for interface in root.findall('interface'))
