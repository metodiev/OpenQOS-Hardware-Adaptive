# Hardware support and detection limits

This page describes exactly what the Phase 1 scanner reads, and what it
deliberately does not report.

## Detection matrix

| Area | Detected | Source | Notes |
| --- | --- | --- | --- |
| Distribution | ID, version, variant, build ID | `/etc/os-release` | Quoted values are unquoted |
| Kernel | release, version, architecture, cmdline | `/proc/sys/kernel/osrelease`, `/proc/version`, `/proc/cmdline` | cmdline omitted in privacy mode |
| Firmware | UEFI/BIOS, Secure Boot, Setup Mode | `/sys/firmware/efi`, EFI variables | Value byte read after the 4-byte attribute mask |
| Virtualization | hypervisor vendor/product | DMI IDs, CPU flags, `/sys/hypervisor/type` | Best effort |
| CPU | vendor, model, microcode, flags, bugs, topology, cache, frequency | `/proc/cpuinfo`, `/sys/devices/system/cpu` | One record per logical CPU |
| Memory | total, free, available, buffers, cached, swap | `/proc/meminfo` | Missing keys are `null`, never zero |
| PCI | vendor/device/subsystem IDs, class, driver, driver version | `/sys/bus/pci/devices` | Includes bridges; not filtered |
| Graphics | adapter list, hybrid detection, primary adapter, VRAM (AMD) | PCI class `03xx`, `/sys/class/drm` | NVIDIA VRAM is not exposed in sysfs |
| USB | vendor/product IDs, manufacturer, product, serial, interfaces | `/sys/bus/usb/devices` | Serial omitted in privacy mode |
| Storage | size, model, serial, rotational, removable, transport, partitions | `/sys/block` | Loop, ram, zram, and floppy devices excluded |
| Network | name, type, MAC, state, speed, driver, firmware, PCI slot | `/sys/class/net` | Wireless detected via `wireless`/`phy80211` |
| Audio | card id and bound module | `/proc/asound` | Full codec topology is not collected |
| Cameras | device name and driver | `/sys/class/video4linux` | |
| Input | name, bus, vendor/product, handlers | `/proc/bus/input/devices` | |
| Bluetooth | adapter address, type, bus | `/sys/class/bluetooth` | Address omitted in privacy mode |
| Power | battery status/capacity/energy/power/cycles, cpufreq driver and governors, EPP, ACPI platform profile | `/sys/class/power_supply`, `/sys/devices/system/cpu/cpu0/cpufreq`, `/sys/firmware/acpi` | |

## Known gaps

These are reported as `unavailable` entries rather than being guessed:

* **Memory module detail** (type, speed, slot, manufacturer). This requires DMI
  access through `dmidecode` and root privileges. Phase 1 does not run external
  tools, so `memory.modules` is always empty and an `unavailable` entry explains
  why.
* **Platform profile / cpufreq** on machines where the firmware or driver does
  not expose them.
* **Audio, Bluetooth, camera, input** on machines where the subsystems are not
  present (containers, WSL, servers).
* **NVIDIA VRAM size.** The proprietary driver does not expose it in sysfs.
* **Thunderbolt/USB4 topology**, **fan sensors**, **thermal zones**, and
  **display panel information** are not collected yet.
* **Firmware update capability** (`fwupd` state) is not inspected.

## Environment caveats

* Inside **WSL2** the scanner works but reports the Microsoft virtual GPU and the
  host block devices. That is the truth of what the kernel exposes; it is not a
  detected laptop.
* Inside a **container without `/sys` mounted read-only from the host**, many
  collectors report `unavailable`. This is expected.
* On **Windows and macOS** there is no `/sys` or `/proc`; only tests and the
  image planner are meaningful. The hidden `--root` option exists for tests and
  for scanning a mounted image, not for normal use.

## Compatibility claims

No physical-hardware compatibility claim is made in Phase 1. The scanner was
executed successfully on:

* Ubuntu 24.04 under WSL2 (kernel 6.6.87.2-microsoft-standard-WSL2) on an AMD
  Ryzen 9 9950X3D host;
* synthetic sysfs trees representing an Intel hybrid laptop, an AMD desktop, and
  a nearly empty machine.

Fedora 44 on real hardware is **untested** at this point and must be verified
before the compatibility database is populated.
