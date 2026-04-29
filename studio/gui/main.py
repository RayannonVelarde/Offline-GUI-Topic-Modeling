# main entry point

import os
import sys

# Ensure Qt finds the macOS "cocoa" platform plugin (fixes "Could not find the Qt platform plugin cocoa" when run from some terminals)
if sys.platform == "darwin":
    if not os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH", "").strip():
        import site
        for s in site.getsitepackages():
            platforms = os.path.join(s, "PySide6", "Qt", "plugins", "platforms")
            if os.path.isdir(platforms):
                os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = platforms
                break

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings
from stylesheet import THEME_LIGHT, get_stylesheet
from main_window import MainWindow


if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Load persisted theme (LIGHT by default).
    settings = QSettings("OfflineGUI", "TopicModelingTranscription")
    theme = settings.value("ui/theme", THEME_LIGHT)
    app.setStyleSheet(get_stylesheet(theme))

    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())
