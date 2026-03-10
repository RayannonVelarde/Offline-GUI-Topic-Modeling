import sys
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Offline Transcription App")

        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout()
        central.setLayout(main_layout)

        # Left panel
        left_panel = QFrame()
        left_layout = QVBoxLayout()
        left_panel.setLayout(left_layout)

        left_layout.addWidget(QLabel("Transcription"))

        nav = QListWidget()
        nav.addItems(["Home", "Files", "Jobs", "Settings", "Export"])
        left_layout.addWidget(nav)

        # Center panel
        center_panel = QFrame()
        center_layout = QVBoxLayout()
        center_panel.setLayout(center_layout)

        center_layout.addWidget(QLabel("Transcription Home"))
        center_layout.addWidget(QLabel("Upload audio files for transcription and translation"))

        upload_box = QLabel("Drag & drop audio files here")
        upload_box.setAlignment(Qt.AlignCenter)
        upload_box.setMinimumHeight(150)
        center_layout.addWidget(upload_box)

        add_btn = QPushButton("Add files")
        center_layout.addWidget(add_btn)

        table = QTableWidget(3, 3)
        table.setHorizontalHeaderLabels(["Filename", "Duration", "Status"])

        table.setItem(0, 0, QTableWidgetItem("interview_01.mp3"))
        table.setItem(0, 1, QTableWidgetItem("12:34"))
        table.setItem(0, 2, QTableWidgetItem("Pending"))

        table.setItem(1, 0, QTableWidgetItem("meeting_notes.wav"))
        table.setItem(1, 1, QTableWidgetItem("45:12"))
        table.setItem(1, 2, QTableWidgetItem("Processing"))

        table.setItem(2, 0, QTableWidgetItem("podcast_ep5.m4a"))
        table.setItem(2, 1, QTableWidgetItem("1:23:45"))
        table.setItem(2, 2, QTableWidgetItem("Complete"))

        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)

        center_layout.addWidget(table)

        start_btn = QPushButton("Start Job")
        center_layout.addWidget(start_btn, alignment=Qt.AlignRight)

        # Right panel
        right_panel = QFrame()
        right_layout = QVBoxLayout()
        right_panel.setLayout(right_layout)

        right_layout.addWidget(QLabel("Job Queue"))
        right_layout.addWidget(QLabel("interview_01.mp3 - 75%"))
        right_layout.addWidget(QLabel("meeting_notes.wav - 45%"))
        right_layout.addWidget(QLabel("podcast_ep5.m4a - 100%"))

        right_layout.addWidget(QLabel("Log Output"))

        log_box = QTextEdit()
        log_box.setReadOnly(True)
        log_box.setPlainText(
            "[14:32:01] Started processing\n"
            "[14:32:12] Detected language: English\n"
            "[14:32:45] meeting_notes.wav added to queue\n"
            "[14:30:22] podcast_ep5.m4a completed successfully"
        )
        right_layout.addWidget(log_box)

        # Add panels to main layout
        main_layout.addWidget(left_panel, 1)
        main_layout.addWidget(center_panel, 4)
        main_layout.addWidget(right_panel, 2)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())