# -*- coding: utf-8 -*-
"""Doc tuy chon cua addon.

Tach thanh module rieng, khong import module nao khac cua addon, de bat cu cho
nao cung dung duoc ma khong so vong import — `__init__` giu lop
`SRP_Preferences` con lai import gan het moi thu.

Ly do co cong tac `verbose`: addon nay do rat nhieu (ban kinh nhan cau, sai so
khop cau, do gian canh, ty le cam xuong/lui...) va truoc gio in het ra console
kem bao cao. So do la vo gia luc dung addon, nhung voi nguoi CHI DUNG no de rig
nhan vat thi la nhieu — ho mo console ra thay mot bai so lieu va tuong may hong.
"""

import bpy

PACKAGE = __package__


def get():
    addon = bpy.context.preferences.addons.get(PACKAGE)
    return addon.preferences if addon is not None else None


def verbose():
    """Co hien so lieu ky thuat khong. Mac dinh KHONG."""
    return bool(getattr(get(), "verbose", False))


def log(*parts):
    """print() chi khi bat so lieu ky thuat."""
    if verbose():
        print(*parts)


def detail(message):
    """Phan duoi cua mot bao cao: chi gan vao khi bat so lieu ky thuat.

    Dung de `self.report()` van noi duoc viec da lam ("Da dung 56 shape key")
    ma khong keo theo mot day so do ("| nua rong mieng 0.0509 | khe moi ...").
    """
    return message if verbose() else ""
