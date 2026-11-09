"""GUI for updating the G-Bible project version and an optional AppImage.

Run with: python3 tools/version_update.py
AppImage editing requires squashfs-tools (unsquashfs and mksquashfs).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import threading
from pathlib import Path
from queue import Empty, Queue


VERSION_LINE = re.compile(
    r"(?m)^[ \t]*__version__[ \t]*=[ \t]*(['\"])([^'\"]+)\1[ \t]*$"
)
VERSION_FORMAT = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:[-+][0-9A-Za-z.-]+)?$"
)
APPIMAGE_EXT = ".AppImage"


class UpdateError(RuntimeError):
    """Raised when the selected project or AppImage cannot be updated safely."""


def validate_version(version: str) -> str:
    version = version.strip()
    if not VERSION_FORMAT.fullmatch(version):
        raise UpdateError("Enter a version such as 1.2.3 or 1.2.3-beta.1.")
    return version


def find_project_version(project: Path) -> tuple[Path, str]:
    path = project / "gbible" / "__init__.py"
    if not path.is_file():
        raise UpdateError(f"That folder does not look like a G-Bible project: {path}")
    text = path.read_text(encoding="utf-8")
    matches = list(VERSION_LINE.finditer(text))
    if len(matches) != 1:
        raise UpdateError(f"Could not identify one version in {path}.")
    return path, matches[0].group(2)


def project_changes(project: Path, version: str) -> tuple[str, dict[Path, bytes]]:
    version_file, old_version = find_project_version(project)
    text = version_file.read_text(encoding="utf-8")
    updated, count = VERSION_LINE.subn(
        lambda _match: f'__version__ = "{version}"', text
    )
    if count != 1:
        raise UpdateError(f"Could not update the version in {version_file}.")
    changes = {version_file: updated.encode("utf-8")}

    readme = project / "README.md"
    if readme.is_file():
        original = readme.read_text(encoding="utf-8")
        # Replace exact old-version references without changing longer numbers
        # such as 10.9.6 when the old version is 0.9.6.
        boundary = re.compile(
            rf"(?<![0-9A-Za-z]){re.escape(old_version)}(?![0-9A-Za-z-])"
        )
        updated_readme = boundary.sub(lambda _match: version, original)
        if updated_readme != original:
            changes[readme] = updated_readme.encode("utf-8")
    return old_version, changes


def image_output_path(image: Path, version: str) -> Path:
    if not image.name.lower().endswith(APPIMAGE_EXT.lower()):
        raise UpdateError("Select a file whose name ends in .AppImage.")
    stem = image.name[:-len(APPIMAGE_EXT)]
    suffix = re.search(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$", stem)
    if suffix:
        stem = stem[:suffix.start()] + version
    else:
        stem = f"{stem}-{version}"
    return image.with_name(stem + APPIMAGE_EXT)


def image_payload_offset(image: Path) -> int:
    with image.open("rb") as stream:
        header = stream.read(64)
        if (
            len(header) < 52
            or header[:4] != b"\x7fELF"
            or header[5] != 1
            or header[8:11] != b"AI\x02"
        ):
            raise UpdateError("Select a supported little-endian AppImage Type 2 file.")
        if header[4] == 2:
            if len(header) < 64:
                raise UpdateError("The AppImage ELF header is incomplete.")
            section_offset = struct.unpack_from("<Q", header, 40)[0]
            section_size, section_count = struct.unpack_from("<HH", header, 58)
        elif header[4] == 1:
            section_offset = struct.unpack_from("<I", header, 32)[0]
            section_size, section_count = struct.unpack_from("<HH", header, 46)
        else:
            raise UpdateError("The AppImage uses an unsupported ELF format.")
        offset = section_offset + section_size * section_count
        stream.seek(offset)
        if stream.read(4) != b"hsqs":
            raise UpdateError("Could not locate the AppImage SquashFS filesystem.")
        return offset


def parse_asar(data: bytes) -> tuple[dict, bytes]:
    if len(data) < 16:
        raise UpdateError("The AppImage contains an invalid app.asar archive.")
    outer_size, header_size, _inner_size, json_size = struct.unpack_from("<IIII", data)
    payload_start = 8 + header_size
    if (
        outer_size != 4
        or header_size < 8
        or payload_start > len(data)
        or 16 + json_size > payload_start
    ):
        raise UpdateError("The AppImage contains an invalid app.asar header.")
    try:
        header = json.loads(data[16:16 + json_size].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UpdateError("The AppImage app.asar header is unreadable.") from error
    if not isinstance(header, dict) or not isinstance(header.get("files"), dict):
        raise UpdateError("The AppImage app.asar has no file table.")
    return header, data[payload_start:]


def serialize_asar(header: dict, payload: bytes) -> bytes:
    json_data = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    padded_json = json_data + b"\0" * (-len(json_data) % 4)
    pickle = struct.pack("<II", 4 + len(padded_json), len(json_data)) + padded_json
    return struct.pack("<II", 4, len(pickle)) + pickle + payload


def _asar_entries(files: dict, parent: str = ""):
    for name, entry in files.items():
        path = f"{parent}/{name}" if parent else name
        if not isinstance(entry, dict):
            raise UpdateError(f"Invalid app.asar entry for {path}.")
        if "files" in entry:
            yield from _asar_entries(entry["files"], path)
        elif "offset" in entry and "size" in entry:
            yield path, entry


def _refresh_integrity(entry: dict, data: bytes) -> None:
    integrity = entry.get("integrity")
    if not integrity:
        return
    if str(integrity.get("algorithm", "SHA256")).lower().replace("-", "") != "sha256":
        raise UpdateError("The AppImage uses an unsupported app.asar integrity algorithm.")
    block_size = int(integrity.get("blockSize", 4 * 1024 * 1024))
    if block_size <= 0:
        raise UpdateError("The AppImage contains an invalid app.asar integrity block size.")
    integrity["hash"] = hashlib.sha256(data).hexdigest()
    integrity["blocks"] = [
        hashlib.sha256(data[index:index + block_size]).hexdigest()
        for index in range(0, len(data), block_size)
    ] or [hashlib.sha256(b"").hexdigest()]


def update_asar(data: bytes, old_version: str, new_version: str) -> bytes:
    header, payload = parse_asar(data)
    entries = list(_asar_entries(header["files"]))
    packages = [entry for name, entry in entries if name == "package.json"]
    if len(packages) != 1:
        raise UpdateError("The AppImage app.asar must contain a root package.json.")
    package_entry = packages[0]
    package_start = int(package_entry["offset"])
    package_data = payload[package_start:package_start + int(package_entry["size"])]
    try:
        package = json.loads(package_data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UpdateError("The AppImage package.json is unreadable.") from error
    package_version = package.get("version")
    if not isinstance(package_version, str):
        raise UpdateError("The AppImage package.json has no version string.")
    source_versions = sorted({old_version, package_version}, key=len, reverse=True)

    rebuilt = bytearray()
    cursor = 0
    indexed = []
    for path, entry in entries:
        start = int(entry["offset"])
        end = start + int(entry["size"])
        if start < 0 or end < start or end > len(payload):
            raise UpdateError(f"Invalid app.asar file range for {path}.")
        content = payload[start:end]
        changed = content
        if b"\0" not in content:
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                pass
            else:
                for source_version in source_versions:
                    pattern = re.compile(
                        rf"(?<![0-9A-Za-z]){re.escape(source_version)}"
                        rf"(?![0-9A-Za-z-])"
                    )
                    text = pattern.sub(lambda _match: new_version, text)
                changed = text.encode("utf-8")
        indexed.append((start, end, entry, content, changed))

    for start, end, entry, original, changed in sorted(indexed, key=lambda item: item[0]):
        if start < cursor:
            raise UpdateError("Overlapping file entries were found in app.asar.")
        rebuilt.extend(payload[cursor:start])
        entry["offset"] = str(len(rebuilt))
        entry["size"] = len(changed)
        if changed != original:
            _refresh_integrity(entry, changed)
        rebuilt.extend(changed)
        cursor = end
    rebuilt.extend(payload[cursor:])
    return serialize_asar(header, bytes(rebuilt))


def _run(command: list[str], description: str) -> str:
    try:
        result = subprocess.run(command, check=True, text=True, capture_output=True)
    except FileNotFoundError as error:
        raise UpdateError(
            "AppImage editing requires squashfs-tools. Install it with "
            "`sudo apt install squashfs-tools`."
        ) from error
    except subprocess.CalledProcessError as error:
        details = (error.stderr or error.stdout or "").strip()
        raise UpdateError(f"{description}{': ' + details if details else ''}") from error
    return result.stdout + result.stderr


def build_appimage(source: Path, new_version: str, destination: Path) -> str:
    """Build a version-updated AppImage without modifying the source image."""
    for tool in ("unsquashfs", "mksquashfs"):
        if shutil.which(tool) is None:
            raise UpdateError(
                "AppImage editing requires squashfs-tools. Install it with "
                "`sudo apt install squashfs-tools`."
            )
    offset = image_payload_offset(source)
    with tempfile.TemporaryDirectory(prefix=".gbible-version-", dir=source.parent) as temp:
        work = Path(temp)
        squashfs = work / "source.squashfs"
        with source.open("rb") as original, squashfs.open("wb") as target:
            original.seek(offset)
            shutil.copyfileobj(original, target, length=1024 * 1024)

        details = _run(["unsquashfs", "-s", str(squashfs)], "Could not read the AppImage")
        compression = re.search(r"(?im)^Compression\s+(\S+)", details)
        block_size = re.search(r"(?im)^Block size\s+(\d+)", details)
        if not compression or not block_size:
            raise UpdateError("Could not read the AppImage compression settings.")

        app = work / "app"
        _run(
            ["unsquashfs", "-no-progress", "-d", str(app), str(squashfs)],
            "Could not extract the AppImage",
        )
        project = app / "resources" / "g-bible"
        version_file, old_version = find_project_version(project)
        source_text = version_file.read_text(encoding="utf-8")
        updated, count = VERSION_LINE.subn(
            lambda _match: f'__version__ = "{new_version}"', source_text
        )
        if count != 1:
            raise UpdateError("Could not update the version embedded in the AppImage.")
        version_file.write_text(updated, encoding="utf-8")

        readme = project / "README.md"
        if readme.is_file():
            old_readme = readme.read_text(encoding="utf-8")
            boundary = re.compile(
                rf"(?<![0-9A-Za-z]){re.escape(old_version)}(?![0-9A-Za-z-])"
            )
            readme.write_text(
                boundary.sub(lambda _match: new_version, old_readme), encoding="utf-8"
            )

        desktop = app / "g-bible.desktop"
        if not desktop.is_file():
            raise UpdateError("The AppImage does not contain g-bible.desktop.")
        desktop_text, changed = re.subn(
            r"(?m)^X-AppImage-Version=.*$",
            f"X-AppImage-Version={new_version}",
            desktop.read_text(encoding="utf-8"),
        )
        if changed != 1:
            raise UpdateError("Could not update the AppImage desktop version metadata.")
        desktop.write_text(desktop_text, encoding="utf-8")

        archive = app / "resources" / "app.asar"
        if not archive.is_file():
            raise UpdateError("The AppImage does not contain resources/app.asar.")
        archive.write_bytes(update_asar(archive.read_bytes(), old_version, new_version))

        rebuilt = work / "updated.squashfs"
        _run(
            [
                "mksquashfs", str(app), str(rebuilt), "-noappend", "-all-root",
                "-no-progress", "-comp", compression.group(1).lower(),
                "-b", block_size.group(1),
            ],
            "Could not rebuild the AppImage filesystem",
        )
        _run(["unsquashfs", "-s", str(rebuilt)], "The rebuilt AppImage is invalid")

        with source.open("rb") as original, destination.open("wb") as output:
            remaining = offset
            while remaining:
                chunk = original.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise UpdateError("The AppImage source was unexpectedly truncated.")
                output.write(chunk)
                remaining -= len(chunk)
            with rebuilt.open("rb") as filesystem:
                shutil.copyfileobj(filesystem, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(destination, stat.S_IMODE(source.stat().st_mode) | 0o111)
    return old_version


def _stage_files(changes: dict[Path, bytes]) -> list[tuple[Path, Path, bytes, int]]:
    staged = []
    try:
        for path, new_data in changes.items():
            old_data = path.read_bytes()
            if old_data == new_data:
                continue
            mode = stat.S_IMODE(path.stat().st_mode)
            fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            temp_path = Path(name)
            try:
                with os.fdopen(fd, "wb") as output:
                    output.write(new_data)
                    output.flush()
                    os.fsync(output.fileno())
                os.chmod(temp_path, mode)
            except Exception:
                temp_path.unlink(missing_ok=True)
                raise
            staged.append((path, temp_path, old_data, mode))
    except Exception:
        for _, temp_path, _, _ in staged:
            temp_path.unlink(missing_ok=True)
        raise
    return staged


def _commit(project_files: list[tuple[Path, Path, bytes, int]],
            staged_image: Path | None, output_image: Path | None) -> None:
    committed = []
    image_added = False
    try:
        if staged_image is not None and output_image is not None:
            os.link(staged_image, output_image)
            image_added = True
        for path, temporary, original, mode in project_files:
            if path.read_bytes() != original:
                raise UpdateError(f"{path} changed while the update was being prepared.")
            os.replace(temporary, path)
            committed.append((path, original, mode))
    except Exception as error:
        rollback_errors = []
        for path, original, mode in reversed(committed):
            try:
                fd, name = tempfile.mkstemp(prefix=f".{path.name}.restore-", dir=path.parent)
                temp_path = Path(name)
                with os.fdopen(fd, "wb") as output:
                    output.write(original)
                    output.flush()
                    os.fsync(output.fileno())
                os.chmod(temp_path, mode)
                os.replace(temp_path, path)
            except OSError as rollback_error:
                rollback_errors.append(f"{path}: {rollback_error}")
        if image_added and output_image is not None:
            try:
                output_image.unlink()
            except OSError as rollback_error:
                rollback_errors.append(f"{output_image}: {rollback_error}")
        suffix = " Rollback incomplete: " + "; ".join(rollback_errors) if rollback_errors else ""
        raise UpdateError(f"Could not complete the update: {error}.{suffix}") from error
    finally:
        for _, temporary, _, _ in project_files:
            temporary.unlink(missing_ok=True)
        if staged_image is not None:
            staged_image.unlink(missing_ok=True)


def main() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    window = tk.Tk()
    window.title("G-Bible Version Updater")
    window.geometry("700x330")
    window.minsize(600, 300)

    project_var = tk.StringVar()
    image_var = tk.StringVar()
    version_var = tk.StringVar()
    output_var = tk.StringVar(value="AppImage is optional; the original is preserved.")
    status_var = tk.StringVar(value="Select your G-Bible project folder.")
    messages: Queue = Queue()
    running = False

    body = ttk.Frame(window, padding=18)
    body.pack(fill="both", expand=True)
    body.columnconfigure(1, weight=1)

    def choose_project() -> None:
        selected = filedialog.askdirectory(title="Select G-Bible project folder")
        if selected:
            project_var.set(selected)

    def choose_image() -> None:
        selected = filedialog.askopenfilename(
            title="Select a G-Bible AppImage",
            filetypes=[("AppImage files", "*.AppImage"), ("All files", "*")],
        )
        if selected:
            image_var.set(selected)

    ttk.Label(body, text="Project folder").grid(row=0, column=0, sticky="w", pady=6)
    ttk.Entry(body, textvariable=project_var).grid(row=0, column=1, sticky="ew", padx=8)
    ttk.Button(body, text="Browse…", command=choose_project).grid(row=0, column=2)
    ttk.Label(body, text="AppImage (optional)").grid(row=1, column=0, sticky="w", pady=6)
    ttk.Entry(body, textvariable=image_var).grid(row=1, column=1, sticky="ew", padx=8)
    ttk.Button(body, text="Browse…", command=choose_image).grid(row=1, column=2)
    ttk.Label(body, text="New version").grid(row=2, column=0, sticky="w", pady=6)
    ttk.Entry(body, textvariable=version_var).grid(row=2, column=1, sticky="w", padx=8)
    ttk.Label(body, text="Example: 1.2.3 or 1.2.3-beta.1").grid(
        row=2, column=2, sticky="w"
    )
    ttk.Label(body, textvariable=output_var, wraplength=650).grid(
        row=3, column=0, columnspan=3, sticky="w", pady=(10, 4)
    )
    progress = ttk.Progressbar(body, mode="indeterminate")
    progress.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 4))
    ttk.Label(body, textvariable=status_var, wraplength=650).grid(
        row=5, column=0, columnspan=3, sticky="w", pady=4
    )
    update_button = ttk.Button(body, text="Update")
    update_button.grid(row=6, column=2, sticky="e", pady=(10, 0))

    def refresh_output(*_args) -> None:
        raw_image, raw_version = image_var.get().strip(), version_var.get().strip()
        if not raw_image:
            output_var.set("AppImage is optional; the original is preserved.")
        elif VERSION_FORMAT.fullmatch(raw_version):
            try:
                output_var.set(
                    f"Updated AppImage: {image_output_path(Path(raw_image), raw_version)} "
                    "(original preserved)"
                )
            except UpdateError:
                output_var.set("The updated AppImage will be saved beside the original.")
        else:
            output_var.set("The updated AppImage will be saved beside the original.")

    image_var.trace_add("write", refresh_output)
    version_var.trace_add("write", refresh_output)

    def poll() -> None:
        nonlocal running
        try:
            while True:
                kind, text = messages.get_nowait()
                if kind == "status":
                    status_var.set(text)
                else:
                    running = False
                    progress.stop()
                    update_button.configure(state="normal")
                    status_var.set("Update complete." if kind == "done" else "Update failed.")
                    if kind == "done":
                        messagebox.showinfo("Version updated", text, parent=window)
                    else:
                        messagebox.showerror("Could not update version", text, parent=window)
        except Empty:
            pass
        window.after(150, poll)

    def begin_update() -> None:
        nonlocal running
        if running:
            return
        project = Path(project_var.get().strip()).expanduser()
        raw_image = image_var.get().strip()
        image = Path(raw_image).expanduser() if raw_image else None
        try:
            version = validate_version(version_var.get())
            old_version, _changes = project_changes(project, version)
            destination = image_output_path(image, version) if image else None
            if image is not None:
                if not image.is_file():
                    raise UpdateError(f"AppImage not found: {image}")
                if image.resolve() == destination.resolve():
                    raise UpdateError(
                        "The output would replace the selected AppImage. Rename the source first."
                    )
                if destination.exists():
                    raise UpdateError(f"Will not overwrite existing output: {destination}")
        except (OSError, UpdateError) as error:
            messagebox.showerror("Check the selected files", str(error), parent=window)
            return

        question = f"Update the project from {old_version} to {version}?"
        if destination:
            question += (
                f"\n\nA new AppImage will be saved as:\n{destination}"
                "\n\nThe selected AppImage will remain unchanged."
            )
        if not messagebox.askyesno("Confirm update", question, parent=window):
            return

        running = True
        update_button.configure(state="disabled")
        progress.start(12)
        status_var.set("Preparing update…")

        def worker() -> None:
            staged_image = None
            staged_files = []
            try:
                image_old_version = None
                if image is not None and destination is not None:
                    fd, name = tempfile.mkstemp(
                        prefix=".gbible-updated-", suffix=APPIMAGE_EXT, dir=destination.parent
                    )
                    os.close(fd)
                    staged_image = Path(name)
                    messages.put(("status", "Rebuilding the AppImage…"))
                    image_old_version = build_appimage(image, version, staged_image)

                messages.put(("status", "Saving project version…"))
                current_old_version, changes = project_changes(project, version)
                if current_old_version != old_version:
                    raise UpdateError("The project version changed during the update. Try again.")
                staged_files = _stage_files(changes)
                _commit(staged_files, staged_image, destination)
                if destination:
                    result = (
                        f"Project updated from {old_version} to {version}.\n"
                        f"AppImage updated from {image_old_version} to {version}:\n{destination}"
                    )
                else:
                    result = f"Project version updated from {old_version} to {version}."
                messages.put(("done", result))
            except Exception as error:
                for _, temp_path, _, _ in staged_files:
                    temp_path.unlink(missing_ok=True)
                if staged_image is not None:
                    staged_image.unlink(missing_ok=True)
                messages.put(("error", str(error)))

        threading.Thread(target=worker, daemon=True).start()

    update_button.configure(command=begin_update)
    window.after(150, poll)
    window.mainloop()


if __name__ == "__main__":
    main()
