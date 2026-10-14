"""Caixas de mensagem e de entrada de texto do Qt com a casca nova das janelas.

O programa chama `QMessageBox.warning/information/question/critical` em cerca
de 200 pontos e `QInputDialog.getText/getMultiLineText/getItem` em 7, e os
testes fazem patch nessas funcoes no modulo que as importa. Para nao tocar em
nenhuma chamada nem em nenhum teste, `install_message_boxes()` troca as
funcoes estaticas, uma vez no inicio do programa, por versoes que montam a
mesma caixa do Qt em Python, instalam a casca e devolvem o mesmo resultado.

Por que nao um filtro de eventos, como o dos menus: a caixa criada pela funcao
estatica do Qt so pode ter a moldura trocada quando ja esta sendo exibida, e
trocar as marcas da janela nesse momento a deixa invisivel (conferido).

Com a chave da casca desligada as versoes novas chamam as originais.
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QInputDialog, QLineEdit, QMessageBox

from app.ui.components.window_shell import install_message_shell, window_shell_enabled

_originals: dict[str, object] = {}

# O programa nao instala a traducao do Qt, entao os botoes padrao saiam em
# ingles. Como a caixa agora e montada aqui, o rotulo e dado em portugues.
_BUTTON_LABELS = {
    QMessageBox.Ok: "OK",
    QMessageBox.Yes: "Sim",
    QMessageBox.No: "Não",
    QMessageBox.Cancel: "Cancelar",
    QMessageBox.Close: "Fechar",
    QMessageBox.Save: "Salvar",
    QMessageBox.Discard: "Descartar",
    QMessageBox.Apply: "Aplicar",
    QMessageBox.Retry: "Tentar novamente",
    QMessageBox.Ignore: "Ignorar",
    QMessageBox.Abort: "Interromper",
    QMessageBox.YesToAll: "Sim para todos",
    QMessageBox.NoToAll: "Não para todos",
}


def _translate_buttons(box: QMessageBox) -> None:
    for standard, label in _BUTTON_LABELS.items():
        button = box.button(standard)
        if button is not None:
            button.setText(label)


def _show_message(name: str, icon, parent, title, text, buttons, default_button):
    if not window_shell_enabled():
        return _originals[name](parent, title, text, buttons, default_button)
    box = QMessageBox(icon, title, text, buttons, parent)
    if default_button != QMessageBox.NoButton:
        box.setDefaultButton(default_button)
    _translate_buttons(box)
    install_message_shell(box)
    try:
        if box.exec() == -1:
            return QMessageBox.Cancel
        clicked = box.clickedButton()
        return box.standardButton(clicked) if clicked is not None else QMessageBox.NoButton
    finally:
        box.deleteLater()


def _information(parent, title, text, buttons=QMessageBox.Ok, defaultButton=QMessageBox.NoButton):  # noqa: N803 (nome do Qt)
    return _show_message("QMessageBox.information", QMessageBox.Information, parent, title, text, buttons, defaultButton)


def _warning(parent, title, text, buttons=QMessageBox.Ok, defaultButton=QMessageBox.NoButton):  # noqa: N803
    return _show_message("QMessageBox.warning", QMessageBox.Warning, parent, title, text, buttons, defaultButton)


def _critical(parent, title, text, buttons=QMessageBox.Ok, defaultButton=QMessageBox.NoButton):  # noqa: N803
    return _show_message("QMessageBox.critical", QMessageBox.Critical, parent, title, text, buttons, defaultButton)


def _question(parent, title, text, buttons=QMessageBox.Yes | QMessageBox.No, defaultButton=QMessageBox.NoButton):  # noqa: N803
    return _show_message("QMessageBox.question", QMessageBox.Question, parent, title, text, buttons, defaultButton)


def _input(parent, title, label, flags, input_method_hints) -> QInputDialog:
    dialog = QInputDialog(parent) if flags is None else QInputDialog(parent, flags)
    dialog.setWindowTitle(title)
    dialog.setLabelText(label)
    if input_method_hints is not None:
        dialog.setInputMethodHints(input_method_hints)
    return dialog


def _finish_input(dialog: QInputDialog) -> tuple[str, bool]:
    dialog.setOkButtonText("OK")
    dialog.setCancelButtonText("Cancelar")
    install_message_shell(dialog)
    try:
        accepted = dialog.exec() == QDialog.Accepted
        return (dialog.textValue() if accepted else ""), accepted
    finally:
        dialog.deleteLater()


def _get_text(parent, title, label, echo=QLineEdit.Normal, text="", flags=None, inputMethodHints=None):  # noqa: N803
    if not window_shell_enabled():
        return _call_original("QInputDialog.getText", parent, title, label, echo, text, flags=flags, inputMethodHints=inputMethodHints)
    dialog = _input(parent, title, label, flags, inputMethodHints)
    dialog.setTextEchoMode(echo)
    dialog.setTextValue(text)
    return _finish_input(dialog)


def _get_multi_line_text(parent, title, label, text="", flags=None, inputMethodHints=None):  # noqa: N803
    if not window_shell_enabled():
        return _call_original("QInputDialog.getMultiLineText", parent, title, label, text, flags=flags, inputMethodHints=inputMethodHints)
    dialog = _input(parent, title, label, flags, inputMethodHints)
    dialog.setOption(QInputDialog.UsePlainTextEditForTextInput, True)
    dialog.setTextValue(text)
    return _finish_input(dialog)


def _get_item(parent, title, label, items, current=0, editable=True, flags=None, inputMethodHints=None):  # noqa: N803
    if not window_shell_enabled():
        return _call_original("QInputDialog.getItem", parent, title, label, items, current, editable, flags=flags, inputMethodHints=inputMethodHints)
    items = list(items)
    dialog = _input(parent, title, label, flags, inputMethodHints)
    dialog.setComboBoxItems(items)
    dialog.setComboBoxEditable(editable)
    if 0 <= current < len(items):
        dialog.setTextValue(items[current])
    return _finish_input(dialog)


def _call_original(name: str, *args, flags=None, inputMethodHints=None):  # noqa: N803
    extra = {}
    if flags is not None:
        extra["flags"] = flags
    if inputMethodHints is not None:
        extra["inputMethodHints"] = inputMethodHints
    return _originals[name](*args, **extra)


_REPLACEMENTS = {
    "QMessageBox.information": (QMessageBox, "information", _information),
    "QMessageBox.warning": (QMessageBox, "warning", _warning),
    "QMessageBox.critical": (QMessageBox, "critical", _critical),
    "QMessageBox.question": (QMessageBox, "question", _question),
    "QInputDialog.getText": (QInputDialog, "getText", _get_text),
    "QInputDialog.getMultiLineText": (QInputDialog, "getMultiLineText", _get_multi_line_text),
    "QInputDialog.getItem": (QInputDialog, "getItem", _get_item),
}


def install_message_boxes() -> None:
    """Troca as funcoes estaticas uma vez por processo (chamar de novo nao faz nada)."""
    if _originals:
        return
    for name, (owner, attribute, replacement) in _REPLACEMENTS.items():
        _originals[name] = getattr(owner, attribute)
        setattr(owner, attribute, staticmethod(replacement))


def uninstall_message_boxes() -> None:
    """Devolve as funcoes originais do Qt (usado nos testes)."""
    for name, (owner, attribute, _replacement) in _REPLACEMENTS.items():
        if name in _originals:
            setattr(owner, attribute, _originals[name])
    _originals.clear()

