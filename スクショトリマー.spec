# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['server.py'],
    pathex=[],
    binaries=[],
    datas=[('index.html', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'setuptools', 'pkg_resources',
        'tkinter', '_tkinter',
        'unittest', 'test', 'distutils',
        'pydoc', 'doctest',
        'xmlrpc',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='スクショトリマー',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon=['icon.ico'],  # アイコンを差し替えるときは、ここのコメントを外す
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='スクショトリマー',
)
