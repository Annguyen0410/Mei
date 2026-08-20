/* Dependency-free ZIP writer (STORE method, no compression) + CRC32.
 *
 * Purpose: the Mei bridge extension exports a multi-window workspace as a
 * real .zip folder so Mei's Import Center can accept a single ZIP instead of
 * a pile of JSON files. STORE (method 0) keeps the format simple and readable
 * by every unzip tool while the JSON payload itself stays small.
 *
 * Works in both the extension (browser global) and Node (module.exports) so
 * the same code is exercised by the test suite.
 */
(function (root) {
  "use strict";

  var CRC_TABLE = (function () {
    var table = new Uint32Array(256);
    for (var n = 0; n < 256; n++) {
      var c = n;
      for (var k = 0; k < 8; k++) {
        c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      }
      table[n] = c >>> 0;
    }
    return table;
  })();

  function crc32(bytes) {
    var crc = 0xffffffff;
    for (var i = 0; i < bytes.length; i++) {
      crc = CRC_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
    }
    return (crc ^ 0xffffffff) >>> 0;
  }

  function toBytes(value) {
    if (value instanceof Uint8Array) return value;
    // UTF-8 encode plain strings (handles Vietnamese / any Unicode).
    if (typeof TextEncoder !== "undefined") {
      return new TextEncoder().encode(String(value));
    }
    return new Uint8Array(unescape(encodeURIComponent(String(value)))
      .split("")
      .map(function (ch) { return ch.charCodeAt(0); }));
  }

  function concat(parts) {
    var total = 0;
    for (var i = 0; i < parts.length; i++) total += parts[i].length;
    var out = new Uint8Array(total);
    var offset = 0;
    for (var j = 0; j < parts.length; j++) {
      out.set(parts[j], offset);
      offset += parts[j].length;
    }
    return out;
  }

  function u16(value) {
    return new Uint8Array([value & 0xff, (value >>> 8) & 0xff]);
  }

  function u32(value) {
    return new Uint8Array([
      value & 0xff,
      (value >>> 8) & 0xff,
      (value >>> 16) & 0xff,
      (value >>> 24) & 0xff,
    ]);
  }

  function dosDateTime(date) {
    var d = date || new Date();
    var time = (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1);
    var day = ((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate();
    return { time: time & 0xffff, date: day & 0xffff };
  }

  /**
   * Build a ZIP archive (STORE) from a list of {name, data} entries.
   * Returns a Uint8Array. Throws on duplicate names.
   */
  function createZip(entries) {
    var dt = dosDateTime();
    var localParts = [];
    var centralParts = [];
    var offset = 0;
    var seen = Object.create(null);

    entries.forEach(function (entry) {
      var name = String(entry.name || "");
      if (!name) throw new Error("ZIP entry requires a name");
      if (seen[name]) throw new Error("Duplicate ZIP entry: " + name);
      seen[name] = true;

      var nameBytes = toBytes(name);
      var data = toBytes(entry.data == null ? "" : entry.data);
      var crc = crc32(data);

      var localHeader = concat([
        u32(0x04034b50),
        u16(20),            // version needed to extract
        u16(0x0800),        // UTF-8 flag
        u16(0),             // STORE
        u16(dt.time),
        u16(dt.date),
        u32(crc),
        u32(data.length),   // compressed size
        u32(data.length),   // uncompressed size
        u16(nameBytes.length),
        u16(0),             // extra field length
        nameBytes,
      ]);

      localParts.push(localHeader, data);

      centralParts.push(concat([
        u32(0x02014b50),
        u16(20),            // version made by
        u16(20),            // version needed
        u16(0x0800),
        u16(0),             // STORE
        u16(dt.time),
        u16(dt.date),
        u32(crc),
        u32(data.length),
        u32(data.length),
        u16(nameBytes.length),
        u16(0),             // extra
        u16(0),             // comment
        u16(0),             // disk number
        u16(0),             // internal attrs
        u32(0),             // external attrs
        u32(offset),        // offset of local header
        nameBytes,
      ]));

      offset += localHeader.length + data.length;
    });

    var central = concat(centralParts);
    var end = concat([
      u32(0x06054b50),
      u16(0),
      u16(0),
      u16(entries.length),
      u16(entries.length),
      u32(central.length),
      u32(offset),
      u16(0),
    ]);

    return concat(localParts.concat([central, end]));
  }

  var api = {
    crc32: crc32,
    createZip: createZip,
    toBytes: toBytes,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    root.MeiZip = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
