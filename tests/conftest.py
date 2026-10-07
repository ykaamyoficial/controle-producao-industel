"""Higiene de Qt entre testes da suite Desktop (PySide6 + unittest).

Por que isto existe
-------------------
Com PySide6 6.11 / Python 3.14 a suite morria com "Segmentation fault" /
heap corruption (0xC0000374, exit 127/139) em pontos aleatorios. A causa NAO e
o teste em que o crash aparece: e uma arvore de widgets que virou lixo ciclico
em algum teste anterior (ex.: um MagicMock de `QTimer.singleShot` que guarda
`dialog.refresh`, ou `self.x = lambda: self...`) e que so e destruida mais
tarde, pelo coletor ciclico do Python.

Nesse caminho (tp_clear do Shiboken) os wrappers de `QLayoutItem`
(`QWidgetItem`/`QSpacerItem`) criados quando um widget e adicionado a um layout
ainda nao instalado (`box = QVBoxLayout(); box.addWidget(w);
layout.addLayout(box)`, padrao usado por KpiCard e por quase toda tela) podem
ser deletados pelo Python e de novo pelo `QLayout` do Qt: double free. Se o
crash acontece ou nao depende da ordem de enderecos dos wrappers, por isso
variava a cada execucao e mudava de teste.

Quando o proprio Qt destroi a arvore primeiro (deleteLater), os wrappers sao
invalidados em ordem e o coletor do Python nao deleta mais nada em C++. Entao,
ao fim de cada teste:

1. drena os QThreads filhos dos widgets (quit + wait);
2. destroi pelo Qt os top-level widgets criados durante o teste;
3. so entao roda o coletor ciclico (que fica desligado durante o corpo do
   teste, para nao destruir widgets no meio de um teste, fora de ordem).

Nada aqui altera timeout, pula teste ou relaxa assercao.
"""
from __future__ import annotations

import gc
import warnings

import pytest

try:
    import shiboken6
    from PySide6.QtCore import QCoreApplication, QEvent, QThread
    from PySide6.QtWidgets import QApplication
except Exception:  # pragma: no cover - ambiente sem Qt
    shiboken6 = None
    QCoreApplication = QEvent = QThread = QApplication = None

_THREAD_WAIT_MS = 5000


def _app():
    if QApplication is None:
        return None
    app = QApplication.instance()
    return app if isinstance(app, QApplication) else None


def _top_level_widgets(app) -> list:
    try:
        return [w for w in app.topLevelWidgets() if shiboken6.isValid(w)]
    except RuntimeError:
        return []


def _cpp_id(obj) -> int:
    return shiboken6.getCppPointer(obj)[0]


def _flush_deferred_deletes() -> None:
    # Entrega apenas os deleteLater pendentes (sem processEvents(): timers e
    # eventos de janela de um teste ja encerrado nao precisam rodar).
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _deliver_queued_calls(rounds: int = 3) -> None:
    # Entrega, enquanto os widgets do teste ainda existem, as chamadas ja
    # enfileiradas por ele (sinais queued de workers e QTimer.singleShot(0, ...)).
    # No PySide um singleShot(0, obj.metodo) dispara mesmo depois de `obj` ser
    # destruido; se ficasse pendente rodaria no processEvents() do teste
    # seguinte, sobre um widget ja deletado. Descartar em vez de entregar
    # (removePostedEvents) nao serve: tambem apaga chamadas internas do Qt
    # (ex.: QAnimationTimer.startAnimations) e as animacoes param de rodar.
    # Algumas rodadas porque um callback costuma agendar o proximo.
    for _ in range(rounds):
        QCoreApplication.sendPostedEvents(None, QEvent.MetaCall)


def _stop_threads(widget) -> bool:
    """Para os QThreads filhos de `widget`. False se algum continuar rodando."""
    try:
        threads = widget.findChildren(QThread)
    except RuntimeError:
        return True
    all_stopped = True
    for thread in threads:
        try:
            if not shiboken6.isValid(thread) or not thread.isRunning():
                continue
            thread.quit()
            if not thread.wait(_THREAD_WAIT_MS):
                all_stopped = False
        except RuntimeError:
            continue
    return all_stopped


def _destroy_widgets(app, keep: frozenset[int]) -> None:
    doomed = []
    for widget in _top_level_widgets(app):
        try:
            if _cpp_id(widget) in keep:
                # Widget de setUpClass/modulo: so drena as threads, nao destroi.
                _stop_threads(widget)
                continue
            if not _stop_threads(widget):
                # Destruir o dono de um QThread em execucao aborta o processo
                # ("QThread: Destroyed while thread is still running").
                warnings.warn(
                    f"QThread ainda em execucao apos {_THREAD_WAIT_MS} ms em "
                    f"{type(widget).__name__}; widget nao foi destruido no teardown.",
                    RuntimeWarning,
                    stacklevel=1,
                )
                continue
            doomed.append(widget)
        except RuntimeError:
            continue
    _deliver_queued_calls()
    _flush_deferred_deletes()
    for widget in doomed:
        try:
            if shiboken6.isValid(widget):
                widget.deleteLater()
        except RuntimeError:
            continue
    del doomed
    _flush_deferred_deletes()


@pytest.fixture(scope="session", autouse=True)
def _qt_session_cleanup():
    yield
    app = _app()
    if app is None:
        return
    # Fim da sessao: destroi tambem o que foi criado em setUpClass/modulo,
    # antes do gc.collect() final do proprio pytest.
    _destroy_widgets(app, frozenset())
    gc.collect()


@pytest.fixture(autouse=True)
def _qt_test_hygiene():
    app = _app()
    keep = frozenset(_cpp_id(w) for w in _top_level_widgets(app)) if app is not None else frozenset()
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        yield
        app = _app()
        if app is not None:
            _destroy_widgets(app, keep)
    finally:
        gc.collect()
        if gc_was_enabled:
            gc.enable()
