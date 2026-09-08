from __future__ import annotations
import pytest
try:
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication
except Exception:
    QThread = None; QApplication = None

@pytest.fixture(autouse=True)
def _drain_qthreads():
    yield
    if QApplication is None or QApplication.instance() is None:
        return
    app = QApplication.instance()
    seen = set()
    try:
        widgets = list(app.topLevelWidgets())
    except RuntimeError:
        widgets = []
    for w in widgets:
        try:
            threads = w.findChildren(QThread)
        except RuntimeError:
            continue
        for t in threads:
            if id(t) in seen:
                continue
            seen.add(id(t))
            try:
                if t.isRunning():
                    t.quit()
                    t.wait(3000)
            except RuntimeError:
                pass
