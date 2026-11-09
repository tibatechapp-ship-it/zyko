"""أداة صغيرة قائمة — فيها عمدًا ما يُصلَح آليًا وما يبقى يدويًا."""
import os


def flip(flag):
    return flag == None


retry = lambda n: n - 1


def guarded(block):
    try:
        block()
    except:
        raise ValueError("فشل")


def load(path):
    f = open(path)
    data = f.read()
    f.close()
    return data
