"""Build OLE property-set byte streams by hand, for tier-1 tests.

Shared by the parser tests and the viewing-transform tests. Both need to feed
the parser bytes in exactly the encoding the archive uses; a second,
subtly-different copy of this builder would let one of them pass against a
format that does not occur in any real file.
"""

from __future__ import annotations

import struct


def build_propset_bytes(
    fmtid_hex: str,
    properties: list[tuple[int, int, bytes]],  # (pid, type_code, raw_bytes_after_type)
) -> bytes:
    """A valid single-section OLE property set containing `properties`."""
    fmtid_bytes = bytes.fromhex(fmtid_hex)
    assert len(fmtid_bytes) == 16

    # Section layout:
    # cb_section (4B) + cprops (4B) + cprops * (pid (4B) + off (4B)) + prop payloads
    cprops = len(properties)
    hdr_size = 8 + cprops * 8

    prop_entries: list[tuple[int, int, bytes]] = []
    current_off = hdr_size
    for pid, type_code, payload in properties:
        # Each property starts with dwType (4B) followed by payload
        full_val = struct.pack("<I", type_code) + payload
        prop_entries.append((pid, current_off, full_val))
        current_off += len(full_val)

    cb_section = current_off
    section_bytes = bytearray(struct.pack("<II", cb_section, cprops))
    for pid, off, _ in prop_entries:
        section_bytes.extend(struct.pack("<II", pid, off))
    for _, _, full_val in prop_entries:
        section_bytes.extend(full_val)

    # Stream layout:
    # wByteOrder (2B) + wFormat (2B) + dwOSVer (4B) + clsid (16B) + cSections (4B)
    # + fmtid (16B) + dwOffset (4B) + section_bytes
    sec_offset = 28 + 20
    header = bytearray()
    header.extend(struct.pack("<HHI", 0xFFFE, 0, 0x00020004))
    header.extend(b"\x00" * 16)  # CLSID
    header.extend(struct.pack("<I", 1))  # 1 section
    header.extend(fmtid_bytes)
    header.extend(struct.pack("<I", sec_offset))
    header.extend(section_bytes)

    return bytes(header)
