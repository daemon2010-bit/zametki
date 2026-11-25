# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('zametki/ui/icons_svg', 'zametki/ui/icons_svg')],   # векторные иконки кнопок
    hiddenimports=['qrcode'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PIL', 'numpy', 'matplotlib', 'scipy', 'tkinter', 'qrcode.image.pil', 'PySide6.QtNetwork', 'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuickWidgets', 'PySide6.QtQmlModels', 'PySide6.QtSvgWidgets', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets', 'PySide6.QtPositioning', 'PySide6.QtLocation', 'PySide6.QtBluetooth', 'PySide6.QtNfc', 'PySide6.QtSerialPort', 'PySide6.QtSensors', 'PySide6.QtWebChannel', 'PySide6.QtWebSockets', 'PySide6.QtTest', 'PySide6.QtDesigner', 'PySide6.QtUiTools', 'PySide6.QtSql', 'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.Qt3DCore', 'PySide6.Qt3DRender', 'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets', 'PySide6.QtRemoteObjects', 'PySide6.QtScxml', 'PySide6.QtStateMachine', 'PySide6.QtTextToSpeech', 'PySide6.QtXml'],
    noarchive=False,
    optimize=0,
)

# Убираем неиспользуемые тяжёлые DLL PySide6 (OpenGL/QML/Quick/PDFium/Network/Direct2D)
_DROP_BINS = (
    'opengl32sw.dll',
    'qt6quick.dll',
    'qt6qml.dll',
    'qt6qmlmodels.dll',
    'qt6qmlmeta.dll',
    'qt6qmlworkerscript.dll',
    'qt6pdf.dll',
    'qt6opengl.dll',
    'qt6network.dll',
    'qdirect2d.dll',
    'qpdf.dll',
)
a.binaries = [b for b in a.binaries if not any(k in b[0].lower() for k in _DROP_BINS)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Заметки',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon='zametki/ui/app.ico',
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
