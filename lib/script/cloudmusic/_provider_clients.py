"""Shared lazy provider client access helpers for cloudmusic internals."""


def get_qqmusic_provider_client():
    from lib.script.qqmusic import get_qqmusic_client

    return get_qqmusic_client()


def get_kugou_provider_client():
    from lib.script.kugou import get_kugou_client

    return get_kugou_client()
