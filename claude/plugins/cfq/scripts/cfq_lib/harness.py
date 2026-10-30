"""Harness-specific policy projection for the shared CFQ CLI."""

import os


def codex():
    return os.environ.get("CFQ_HARNESS") == "codex"


def current_model():
    return os.environ.get("CFQ_MODEL", "")


def model_list(settings, kind):
    if not codex():
        return settings[kind]
    key = "codex" + kind[0].upper() + kind[1:]
    configured = settings.get(key) or []
    if configured:
        return configured
    if kind == "orchestratorModels":
        return model_list(settings, "implModels")
    return [current_model()] if current_model() else []


def explore_model(settings, kind):
    if not codex():
        return settings[kind]
    key = "codex" + kind[0].upper() + kind[1:]
    return settings.get(key) or current_model()
