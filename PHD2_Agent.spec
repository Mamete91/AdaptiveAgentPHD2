# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'tomli',
        'uvicorn',
        'fastapi',
        'scipy',
        'scipy.ndimage',
        'scipy.ndimage._filters',
        'scipy.ndimage._measurements',
        'numpy',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Dipendenze SOLO-BUILD, mai importate a runtime dall'Agente: reportlab e
    # matplotlib servono a generare il PDF del manuale (matplotlib solo per i
    # font DejaVu). Senza questa esclusione PyInstaller le trova comunque e le
    # imbarca: +44 MB di pacchetto spedito agli utenti per codice mai eseguito.
    excludes=[
        'matplotlib', 'reportlab', 'PIL', 'pytest', 'tkinter',
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
    name='PHD2_Agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # §58 — agente in BACKGROUND (exe GUI-subsystem, nessuna console DOS): la finestra
    # veniva chiusa per errore dai beta tester (= kill dell'agente). Log completo su
    # logs/agent.log (§56); viewer sicuro: Mostra_Log.bat; stop pulito: Arresta.bat.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',   # §26: metadata Windows (Adaptive Agent for PHD2 v2.2)
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PHD2_Agent',
)
