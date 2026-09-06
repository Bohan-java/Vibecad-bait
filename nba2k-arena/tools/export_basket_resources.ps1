#requires -Version 5.1
<#
.SYNOPSIS
Read and verify four existing NBA 2K26 basket resources into a NEW local folder.
.DESCRIPTION
Windows x64, PowerShell 5.1/7. No download, installation, game launch or import.
The game is opened read-only. Existing files and directories are never replaced.
This release received static review on macOS; it has NOT been run on Windows.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $GameRoot,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string] $OutputDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'This exporter supports Windows only. Nothing was exported.'
}
if (-not [Environment]::Is64BitProcess) {
    throw 'Use 64-bit PowerShell; the existing Oodle DLL is win64.'
}

# C# uses only APIs available in .NET Framework 4.5+ and modern .NET.
# A fixed helper type also prevents a repeated call from silently replacing it.
if ($null -ne ('NBA2KBasketExportV1.Exporter' -as [type])) {
    throw 'This helper is already loaded. Open a fresh PowerShell session to run again.'
}

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;

namespace NBA2KBasketExportV1 {
    public static class Exporter {
        private sealed class Item {
            internal string Basename, Name, Container, ContainerPath, Codec;
            internal int Expected, Line;
            internal long Offset, StoredSize;
            internal uint TrailerCrc;
            internal string StoredSha, PayloadSha, DecodedSha;
            internal byte[] Decoded;
            internal Item(string name, int size) { Basename = name; Expected = size; }
        }

        private static readonly uint[] CrcTable = BuildCrcTable();
        private const int MaxStoredBytes = 64 * 1024 * 1024;

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
        private static extern IntPtr LoadLibraryExW(string name, IntPtr reserved, uint flags);
        [DllImport("kernel32.dll", CharSet = CharSet.Ansi, ExactSpelling = true, SetLastError = true)]
        private static extern IntPtr GetProcAddress(IntPtr module, string name);
        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool FreeLibrary(IntPtr module);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
        private static extern IntPtr CreateFileW(string path, uint access, uint share,
            IntPtr security, uint disposition, uint flags, IntPtr template);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
        private static extern uint GetFinalPathNameByHandleW(IntPtr file, StringBuilder path,
            uint size, uint flags);
        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool CloseHandle(IntPtr handle);

        // Exact 14-argument ABI used by scripts/read_game_resource.py.
        [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
        private delegate IntPtr OodleDecompress(
            IntPtr source, IntPtr sourceSize, IntPtr destination, IntPtr destinationSize,
            int fuzzSafe, int checkCrc, int verbosity, IntPtr decodeBuffer,
            IntPtr decodeBufferSize, IntPtr callback, IntPtr callbackUserData,
            IntPtr decoderMemory, IntPtr decoderMemorySize, int threadPhase);

        private static uint[] BuildCrcTable() {
            uint[] table = new uint[256];
            for (uint i = 0; i < 256; i++) {
                uint c = i;
                for (int j = 0; j < 8; j++) c = (c & 1) != 0 ? 0xedb88320U ^ (c >> 1) : c >> 1;
                table[i] = c;
            }
            return table;
        }
        private static uint Crc32(byte[] bytes) {
            uint c = 0xffffffffU;
            foreach (byte b in bytes) c = CrcTable[(c ^ b) & 255] ^ (c >> 8);
            return ~c;
        }
        private static uint Adler32(byte[] bytes) {
            uint a = 1, b = 0;
            foreach (byte value in bytes) { a = (a + value) % 65521; b = (b + a) % 65521; }
            return (b << 16) | a;
        }
        private static uint ReadU32LE(byte[] bytes, int at) {
            return (uint)bytes[at] | ((uint)bytes[at + 1] << 8) |
                ((uint)bytes[at + 2] << 16) | ((uint)bytes[at + 3] << 24);
        }
        private static string Hash(byte[] bytes) {
            using (SHA256 h = SHA256.Create()) return Hex(h.ComputeHash(bytes));
        }
        private static string Hex(byte[] bytes) {
            return BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant();
        }

        // Reject UNC, mapped network drives, ADS, device paths, symlinks and
        // junctions. The latter is intentionally conservative: use real paths.
        private static string LocalAbsolute(string path) {
            if (path.Length < 3 || !char.IsLetter(path[0]) || path[1] != ':' ||
                (path[2] != '\\' && path[2] != '/'))
                throw new IOException("Use an absolute local drive path: " + path);
            if (path.IndexOf(':', 2) >= 0 || path.IndexOfAny(new char[] { '*', '?', '<', '>', '|', '"' }) >= 0)
                throw new IOException("Unsupported path syntax: " + path);
            string full = Path.GetFullPath(path);
            foreach (string segment in full.Substring(3).Split(new char[] { '\\', '/' }, StringSplitOptions.RemoveEmptyEntries))
                if (segment.EndsWith(".") || segment.EndsWith(" "))
                    throw new IOException("Trailing-dot/space path aliases are not supported: " + path);
            DriveInfo drive = new DriveInfo(Path.GetPathRoot(full));
            if (drive.DriveType == DriveType.Network || drive.DriveType == DriveType.Unknown ||
                drive.DriveType == DriveType.NoRootDirectory)
                throw new IOException("A local, available drive is required: " + path);
            if (full.Length > Path.GetPathRoot(full).Length)
                full = full.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            NoReparsePoints(full);
            return full;
        }
        private static string PhysicalDirectory(string path) {
            // Zero desired access: resolve identity only, never open for writes.
            IntPtr handle = CreateFileW(path, 0, 7, IntPtr.Zero, 3, 0x02000000, IntPtr.Zero);
            if (handle == new IntPtr(-1))
                throw new IOException("Cannot resolve directory identity; Windows error " + Marshal.GetLastWin32Error());
            try {
                StringBuilder name = new StringBuilder(32768);
                // VOLUME_NAME_GUID + FILE_NAME_NORMALIZED handles 8.3 and SUBST
                // aliases without relying on the textual spelling of a drive.
                uint count = GetFinalPathNameByHandleW(handle, name, (uint)name.Capacity, 1);
                if (count == 0 || count >= name.Capacity)
                    throw new IOException("Cannot resolve physical local directory; Windows error " + Marshal.GetLastWin32Error());
                return name.ToString().TrimEnd('\\', '/');
            } finally { CloseHandle(handle); }
        }
        private static void NoReparsePoints(string path) {
            string part = path;
            while (!String.IsNullOrEmpty(part)) {
                if (File.Exists(part) || Directory.Exists(part)) {
                    FileAttributes attrs = File.GetAttributes(part);
                    if ((attrs & FileAttributes.ReparsePoint) != 0)
                        throw new IOException("Symlink/junction/reparse path is not supported: " + part);
                }
                string parent = Path.GetDirectoryName(part);
                if (String.Equals(part, parent, StringComparison.OrdinalIgnoreCase)) break;
                part = parent;
            }
        }
        private static bool Inside(string path, string root) {
            return String.Equals(path, root, StringComparison.OrdinalIgnoreCase) ||
                path.StartsWith(root.TrimEnd('\\', '/') + "\\", StringComparison.OrdinalIgnoreCase);
        }
        private static string InGame(string game, string relative) {
            if (String.IsNullOrEmpty(relative) || Path.IsPathRooted(relative) || relative.IndexOf(':') >= 0)
                throw new IOException("Manifest container must be game-relative: " + relative);
            string[] parts = relative.Replace('/', '\\').Split('\\');
            foreach (string part in parts) {
                if (part.Length == 0 || part == "." || part == ".." || part.EndsWith(".") || part.EndsWith(" "))
                    throw new IOException("Unsafe container path: " + relative);
            }
            string full = LocalAbsolute(Path.Combine(game, relative.Replace('/', '\\')));
            if (!Inside(full, game)) throw new IOException("Container leaves game root: " + relative);
            return full;
        }

        // Strict single-record CSV, including quoted fields and escaped quotes.
        // Multi-line quoted fields are not accepted by this manifest format.
        private static string[] CsvLine(string line, int number) {
            List<string> cells = new List<string>();
            int at = 0;
            while (true) {
                StringBuilder field = new StringBuilder();
                if (at < line.Length && line[at] == '"') {
                    at++;
                    bool closed = false;
                    while (at < line.Length) {
                        char ch = line[at++];
                        if (ch != '"') { field.Append(ch); continue; }
                        if (at < line.Length && line[at] == '"') { field.Append('"'); at++; }
                        else { closed = true; break; }
                    }
                    if (!closed || (at < line.Length && line[at] != ','))
                        throw new InvalidDataException("Malformed CSV at line " + number);
                } else {
                    while (at < line.Length && line[at] != ',') {
                        if (line[at] == '"') throw new InvalidDataException("Malformed CSV at line " + number);
                        field.Append(line[at++]);
                    }
                }
                cells.Add(field.ToString());
                if (at == line.Length) break;
                at++; // comma, including a final empty field
            }
            if (cells.Count != 4) throw new InvalidDataException("Expected four CSV fields at line " + number);
            return cells.ToArray();
        }
        private static long DecimalInt(string value, int line) {
            long result;
            if (!Int64.TryParse(value, NumberStyles.None, CultureInfo.InvariantCulture, out result))
                throw new InvalidDataException("Invalid nonnegative decimal integer at manifest line " + line);
            return result;
        }
        private static string ReadManifest(string game, Item[] items) {
            string path = InGame(game, "manifest");
            Dictionary<string, Item> wanted = new Dictionary<string, Item>(StringComparer.OrdinalIgnoreCase);
            foreach (Item item in items) wanted.Add(item.Basename, item);
            using (FileStream fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read)) {
                using (StreamReader reader = new StreamReader(fs, new UTF8Encoding(false, true), true, 4096, true)) {
                    string line; int lineNumber = 0; bool firstRecord = true;
                    while ((line = reader.ReadLine()) != null) {
                        lineNumber++;
                        if (line.Length == 0) continue;
                        string[] cell = CsvLine(line, lineNumber);
                        if (firstRecord && String.Equals(cell[0], "name", StringComparison.OrdinalIgnoreCase) &&
                            String.Equals(cell[1], "container", StringComparison.OrdinalIgnoreCase) &&
                            String.Equals(cell[2], "offset", StringComparison.OrdinalIgnoreCase) &&
                            String.Equals(cell[3], "size", StringComparison.OrdinalIgnoreCase)) {
                            firstRecord = false; continue;
                        }
                        firstRecord = false;
                        string normalized = cell[0].Replace('\\', '/');
                        string basename = normalized.Substring(normalized.LastIndexOf('/') + 1);
                        Item found;
                        if (!wanted.TryGetValue(basename, out found)) continue;
                        if (found.Name != null)
                            throw new InvalidDataException("Duplicate basename in manifest: " + found.Basename);
                        found.Name = cell[0]; found.Container = cell[1]; found.Line = lineNumber;
                        found.Offset = DecimalInt(cell[2], lineNumber);
                        found.StoredSize = DecimalInt(cell[3], lineNumber);
                        if (found.StoredSize < 25 || found.StoredSize > MaxStoredBytes)
                            throw new InvalidDataException("Stored size outside allowed VCZ range: " + found.Basename);
                        found.ContainerPath = InGame(game, found.Container);
                    }
                }
                foreach (Item item in items)
                    if (item.Name == null) throw new FileNotFoundException("Missing exact basename in manifest: " + item.Basename);
                fs.Position = 0;
                using (SHA256 h = SHA256.Create()) return Hex(h.ComputeHash(fs));
            }
        }
        private static byte[] ReadRange(Item item) {
            NoReparsePoints(item.ContainerPath);
            using (FileStream fs = new FileStream(item.ContainerPath, FileMode.Open, FileAccess.Read, FileShare.Read)) {
                // Subtraction avoids offset+size overflow.
                if (item.Offset > fs.Length || item.StoredSize > fs.Length - item.Offset)
                    throw new InvalidDataException("Manifest range is outside container: " + item.Basename);
                fs.Seek(item.Offset, SeekOrigin.Begin);
                byte[] raw = new byte[(int)item.StoredSize];
                int done = 0;
                while (done < raw.Length) {
                    int got = fs.Read(raw, done, raw.Length - done);
                    if (got == 0) throw new EndOfStreamException("Short exact-range read: " + item.Basename);
                    done += got;
                }
                return raw;
            }
        }

        // DeflateStream on both supported runtimes accepts RAW DEFLATE. Strip
        // the zlib wrapper explicitly and verify its big-endian Adler-32.
        private static bool TryZlib(byte[] payload, int expected, out byte[] output) {
            output = null;
            if (payload.Length < 6 || (payload[0] & 15) != 8 || (payload[0] >> 4) > 7 ||
                (((int)payload[0] << 8) | payload[1]) % 31 != 0 || (payload[1] & 32) != 0)
                return false;
            try {
                byte[] decoded = new byte[expected];
                using (MemoryStream source = new MemoryStream(payload, 2, payload.Length - 6, false))
                using (DeflateStream deflate = new DeflateStream(source, CompressionMode.Decompress)) {
                    int done = 0;
                    while (done < decoded.Length) {
                        int got = deflate.Read(decoded, done, decoded.Length - done);
                        if (got == 0) throw new InvalidDataException("Short zlib output");
                        done += got;
                    }
                    if (deflate.ReadByte() != -1) throw new InvalidDataException("Oversized zlib output");
                }
                int at = payload.Length - 4;
                uint adler = ((uint)payload[at] << 24) | ((uint)payload[at + 1] << 16) |
                    ((uint)payload[at + 2] << 8) | payload[at + 3];
                if (Adler32(decoded) != adler) throw new InvalidDataException("zlib Adler-32 mismatch");
                output = decoded; return true;
            } catch (InvalidDataException) { return false; }
              catch (IOException) { return false; }
        }
        private static byte[] DecodeOodle(byte[] payload, int expected, string dll) {
            NoReparsePoints(dll);
            // Search dependencies only in the DLL directory and System32.
            IntPtr module = LoadLibraryExW(dll, IntPtr.Zero, 0x00000900);
            if (module == IntPtr.Zero)
                throw new IOException("Cannot load existing win64 Oodle DLL; Windows error " + Marshal.GetLastWin32Error());
            GCHandle source = default(GCHandle), destination = default(GCHandle);
            try {
                IntPtr address = GetProcAddress(module, "OodleLZ_Decompress");
                if (address == IntPtr.Zero) throw new EntryPointNotFoundException("OodleLZ_Decompress");
                OodleDecompress decode = (OodleDecompress)Marshal.GetDelegateForFunctionPointer(address, typeof(OodleDecompress));
                byte[] output = new byte[expected];
                source = GCHandle.Alloc(payload, GCHandleType.Pinned);
                destination = GCHandle.Alloc(output, GCHandleType.Pinned);
                long actual = decode(source.AddrOfPinnedObject(), new IntPtr(payload.Length),
                    destination.AddrOfPinnedObject(), new IntPtr(expected), 1, 0, 0,
                    IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero,
                    IntPtr.Zero, 3).ToInt64();
                if (actual != expected)
                    throw new InvalidDataException("Oodle returned " + actual + " bytes; expected " + expected);
                return output;
            } finally {
                if (source.IsAllocated) source.Free();
                if (destination.IsAllocated) destination.Free();
                FreeLibrary(module);
            }
        }
        private static void Decode(Item item, string game, ref string dllSha) {
            byte[] raw = ReadRange(item);
            if (raw[0] != 0x1f || raw[1] != 0x8b || raw[12] != 'V' || raw[13] != 'C' ||
                raw[14] != 'Z' || raw[15] != 0)
                throw new InvalidDataException("Expected verified VCZ wrapper: " + item.Basename);
            uint size = ReadU32LE(raw, raw.Length - 4);
            item.TrailerCrc = ReadU32LE(raw, raw.Length - 8);
            if (size != (uint)item.Expected)
                throw new InvalidDataException("VCZ decoded-size mismatch: " + item.Basename);
            byte[] payload = new byte[raw.Length - 24];
            Buffer.BlockCopy(raw, 16, payload, 0, payload.Length);
            item.StoredSha = Hash(raw); item.PayloadSha = Hash(payload);
            byte[] decoded;
            if (TryZlib(payload, item.Expected, out decoded)) item.Codec = "zlib";
            else {
                string dll = InGame(game, "data/oodle/oo2core_9_win64.dll");
                // Hold read-only/non-write-sharing access while loading/calling.
                using (FileStream lockFile = new FileStream(dll, FileMode.Open, FileAccess.Read, FileShare.Read)) {
                    string thisSha;
                    using (SHA256 h = SHA256.Create()) thisSha = Hex(h.ComputeHash(lockFile));
                    if (dllSha != null && thisSha != dllSha) throw new IOException("Oodle DLL changed during export");
                    dllSha = thisSha;
                    decoded = DecodeOodle(payload, item.Expected, dll);
                }
                item.Codec = "oodle-existing-game-dll";
            }
            if (decoded.Length != item.Expected || Crc32(decoded) != item.TrailerCrc)
                throw new InvalidDataException("Decoded size or VCZ CRC-32 mismatch: " + item.Basename);
            item.Decoded = decoded; item.DecodedSha = Hash(decoded);
        }

        private static string Json(string value) {
            if (value == null) return "null";
            StringBuilder b = new StringBuilder("\"");
            foreach (char c in value) {
                if (c == '\\' || c == '"') { b.Append('\\'); b.Append(c); }
                else if (c < 32) b.Append("\\u" + ((int)c).ToString("x4", CultureInfo.InvariantCulture));
                else b.Append(c);
            }
            return b.Append('"').ToString();
        }
        private static string Metadata(Item[] items, string manifestSha, string dllSha) {
            StringBuilder b = new StringBuilder();
            b.Append("{\n  \"format\": \"nba2k-basket-resource-export-v1\",\n");
            b.Append("  \"created_utc\": " + Json(DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture)) + ",\n");
            b.Append("  \"exporter_release_validation\": \"static_review_on_macOS_only_before_handoff\",\n");
            b.Append("  \"local_export_validation\": \"all_four_exact_names_sizes_and_CRC32_passed\",\n");
            b.Append("  \"game_files_opened_read_only\": true,\n  \"game_started\": false,\n");
            b.Append("  \"manifest_sha256\": " + Json(manifestSha) + ",\n");
            b.Append("  \"oodle_dll_sha256_if_used\": " + Json(dllSha) + ",\n");
            b.Append("  \"cache_suffix_note\": \"Outputs are decoded bytes despite the original .gz suffix.\",\n");
            b.Append("  \"resources\": [\n");
            for (int i = 0; i < items.Length; i++) {
                Item t = items[i];
                b.Append("    {\"output\":" + Json(t.Basename) + ",\"manifest_name\":" + Json(t.Name));
                b.Append(",\"manifest_line\":" + t.Line.ToString(CultureInfo.InvariantCulture));
                b.Append(",\"container\":" + Json(t.Container));
                b.Append(",\"offset\":" + t.Offset.ToString(CultureInfo.InvariantCulture));
                b.Append(",\"stored_size\":" + t.StoredSize.ToString(CultureInfo.InvariantCulture));
                b.Append(",\"decoded_size\":" + t.Expected.ToString(CultureInfo.InvariantCulture));
                b.Append(",\"codec\":" + Json(t.Codec));
                b.Append(",\"trailer_and_decoded_crc32\":" + Json(t.TrailerCrc.ToString("x8", CultureInfo.InvariantCulture)));
                b.Append(",\"stored_sha256\":" + Json(t.StoredSha) + ",\"payload_sha256\":" + Json(t.PayloadSha));
                b.Append(",\"decoded_sha256\":" + Json(t.DecodedSha) + "}" + (i + 1 == items.Length ? "\n" : ",\n"));
            }
            return b.Append("  ]\n}\n").ToString();
        }
        private static void WriteNew(string path, byte[] bytes) {
            using (FileStream fs = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None)) {
                fs.Write(bytes, 0, bytes.Length); fs.Flush(true);
            }
        }

        public static string Run(string gameRoot, string outputDirectory) {
            if (Environment.OSVersion.Platform != PlatformID.Win32NT || !Environment.Is64BitProcess)
                throw new PlatformNotSupportedException("Windows 64-bit process required");
            if (Crc32(Encoding.ASCII.GetBytes("123456789")) != 0xcbf43926U)
                throw new InvalidOperationException("CRC-32 self-check failed");
            string game = LocalAbsolute(gameRoot);
            if (!Directory.Exists(game)) throw new DirectoryNotFoundException(game);
            string output = LocalAbsolute(outputDirectory);
            if (Inside(output, game)) throw new IOException("Output must be outside the game directory");
            if (Directory.Exists(output) || File.Exists(output))
                throw new IOException("Output path already exists; choose a new directory");
            string parent = Path.GetDirectoryName(output);
            if (String.IsNullOrEmpty(parent) || !Directory.Exists(parent))
                throw new DirectoryNotFoundException("Output parent must already exist: " + parent);
            string physicalGame = PhysicalDirectory(game), physicalParent = PhysicalDirectory(parent);
            if (Inside(physicalParent, physicalGame))
                throw new IOException("Output resolves inside the game directory, possibly through a path alias");

            Item[] items = new Item[] {
                new Item("IndexBuffer.2faa94a692eecb55.gz", 1340664),
                new Item("VertexBuffer.396eff6e2f806326.gz", 363992),
                new Item("VertexBuffer.c7008f082a4e24dd.gz", 181996),
                new Item("VertexBuffer.8d2e607c050161de.gz", 1091976)
            };
            string manifestSha = ReadManifest(game, items), dllSha = null;
            // Validate every resource before creating an export directory.
            foreach (Item item in items) Decode(item, game, ref dllSha);

            NoReparsePoints(parent);
            if (!String.Equals(physicalParent, PhysicalDirectory(parent), StringComparison.OrdinalIgnoreCase))
                throw new IOException("Output parent changed during validation");
            string staging = output + ".partial-" + Guid.NewGuid().ToString("N");
            if (Directory.Exists(staging) || File.Exists(staging)) throw new IOException("Staging collision");
            Directory.CreateDirectory(staging);
            try {
                foreach (Item item in items) WriteNew(Path.Combine(staging, item.Basename), item.Decoded);
                WriteNew(Path.Combine(staging, "basket_resources.metadata.json"),
                    new UTF8Encoding(false).GetBytes(Metadata(items, manifestSha, dllSha)));
                NoReparsePoints(parent);
                if (!String.Equals(physicalParent, PhysicalDirectory(parent), StringComparison.OrdinalIgnoreCase))
                    throw new IOException("Output parent changed during export");
                // Directory.Move fails if the destination exists: no replacement.
                Directory.Move(staging, output);
            } catch (Exception ex) {
                // Do not delete anything, even after a failure. The uniquely named
                // partial directory is never reported as a completed export.
                throw new IOException("Export write failed. Any partial files remain at " + staging, ex);
            }
            return output;
        }
    }
}
'@

$completedDirectory = [NBA2KBasketExportV1.Exporter]::Run($GameRoot, $OutputDirectory)
Write-Host ('Verified all four resources. Export complete: ' + $completedDirectory)
Write-Host 'The .gz files contain decoded bytes. No game files were modified.'
