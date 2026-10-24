"""Developer hook: load QML dropped into %LOCALAPPDATA%/Falcon Design Space/falconmods/dev/ at runtime.

Only installed with `patcher.py install --dev`. Lets you run QML/JS inside the running app
(results go to the app log via console.log) without repacking resources. Each script must get a
new file name (see tools/devrun.sh).
"""

ID = "dev_hook"
DEV = True
DESCRIPTION = "Runtime loader for falconmods/dev/*.qml (development only)"

PATCHES = [
    {
        "rcc": "qml.rcc",
        "file": "FalconModsDevHook.qml",
        "new_file": True,
        "source": "qml/FalconModsDevHook.qml",
    },
    {
        "rcc": "qml.rcc",
        "file": "main.qml",
        "find": "    InducedLoginPopup {\n        id: inducedLoginPopup\n    }\n}",
        "replace": (
            "    InducedLoginPopup {\n        id: inducedLoginPopup\n    }\n\n"
            "    // FalconMods dev hook\n"
            "    FalconModsDevHook {}\n"
            "}"
        ),
    },
]
