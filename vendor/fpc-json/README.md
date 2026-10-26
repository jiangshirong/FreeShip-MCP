# fcl-json scanner compatibility patch

Source: Free Pascal 3.2.2, `packages/fcl-json/src/jsonscanner.pp`.
Original copyright and library license notices are retained.

The scanner decodes consecutive JSON Unicode escape pairs through a four-byte
short-string buffer. Two non-surrogate BMP characters can require six UTF-8
bytes, so this buffer truncates valid strings. The local copy changes only
`S : String[4]` to `S : String[6]` and is selected by the engine unit search path.
No geometry or numerical calculation code is changed.

`PATCH.json` records normalized original/patched source hashes. The corresponding
source distribution includes this patched unit and the original compiler sources.
