"""Installed/source entry point for the Qt frontend."""
import sys

if sys.argv[1:] == ['--version']:
    from version import __version__
    print('Estante ' + __version__)
elif sys.argv[1:] == ['--self-test']:
    import ssl
    import tempfile
    from pathlib import Path
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtGui import QImage, QImageReader
    from PySide6.QtSvg import QSvgRenderer
    from qt_app.main import LibraryController
    app=QCoreApplication([])
    with tempfile.TemporaryDirectory() as folder:
        image=QImage(8,8,QImage.Format.Format_RGB32); image.fill(0xff556677)
        for extension in ('png','jpg','webp'):
            path=Path(folder)/('image.'+extension)
            assert image.save(str(path)), extension+' encoder unavailable'
            assert not QImageReader(str(path)).read().isNull(), extension+' decoder unavailable'
    assert QSvgRenderer(b'<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><rect width="8" height="8"/></svg>').isValid()
    assert 'gi.repository.Gtk' not in sys.modules
    ssl.create_default_context()
    print('Qt: Python, Qt Quick, PNG/JPEG/WebP, SVG, SSL and GTK-free imports OK')
else:
    from qt_app.main import main
    raise SystemExit(main())
