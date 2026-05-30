"""
Genera version_info.txt da phd2_agent/__about__.py per PyInstaller.

Eseguito automaticamente da build_dist.py prima di richiamare lo .spec.
I metadata risultanti compaiono nelle Proprieta' Windows dell'.exe
(click destro -> Proprieta' -> Dettagli).
"""
from phd2_agent.__about__ import (
    __project_name__, __version__, __version_tuple__,
    __author__, __copyright__,
)

VS_TEMPLATE = """\
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({v0}, {v1}, {v2}, {v3}),
    prodvers=({v0}, {v1}, {v2}, {v3}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [
          StringStruct(u'CompanyName',      u'{author}'),
          StringStruct(u'FileDescription',  u'{project}'),
          StringStruct(u'FileVersion',      u'{ver}'),
          StringStruct(u'InternalName',     u'PHD2_Agent'),
          StringStruct(u'LegalCopyright',   u'{copyright}'),
          StringStruct(u'OriginalFilename', u'PHD2_Agent.exe'),
          StringStruct(u'ProductName',      u'{project}'),
          StringStruct(u'ProductVersion',   u'{ver}'),
        ]
      )
    ]),
    VarFileInfo([VarStruct(u'Translation', [0x0409, 1200])])
  ]
)
"""


def write_version_info(path: str = "version_info.txt") -> None:
    v0, v1, v2, v3 = __version_tuple__
    content = VS_TEMPLATE.format(
        v0=v0, v1=v1, v2=v2, v3=v3,
        author=__author__,
        project=__project_name__,
        ver=__version__,
        copyright=__copyright__,
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


if __name__ == "__main__":
    write_version_info()
    print("version_info.txt generato.")
