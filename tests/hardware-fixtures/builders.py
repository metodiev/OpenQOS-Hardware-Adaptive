"""Synthetic sysfs/procfs trees used by the hardware tests.

The trees are generated at test time instead of being committed. That keeps the
fixtures readable, avoids symlink portability problems on Windows, and makes it
easy to describe new machines.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

_SECURE_BOOT_GUID = "8be4df61-93ca-11d2-aa0d-00e098032b8c"


class TreeBuilder:
    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, relative: str, content: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def write_bytes(self, relative: str, content: bytes) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def uevent(self, relative: str, **values: str) -> None:
        body = "\n".join(f"{key}={value}" for key, value in values.items())
        self.write(f"{relative}/uevent", body + "\n")

    def directory(self, relative: str) -> None:
        (self.root / relative).mkdir(parents=True, exist_ok=True)

    def pci_device(
        self,
        slot: str,
        *,
        vendor: str,
        device: str,
        class_code: str,
        driver: str | None = None,
        subsystem_vendor: str = "0000",
        subsystem_device: str = "0000",
    ) -> None:
        slot_dir = slot.replace(":", "_")
        base = f"sys/bus/pci/devices/{slot_dir}"
        values = {
            "DRIVER": driver or "",
            "PCI_CLASS": class_code,
            "PCI_ID": f"{vendor}:{device}",
            "PCI_SUBSYS_ID": f"{subsystem_vendor}:{subsystem_device}",
            "PCI_SLOT_NAME": slot,
            "MODALIAS": f"pci:v{vendor}d{device}",
        }
        self.uevent(base, **{key: value for key, value in values.items() if value})
        self.write(f"{base}/vendor", f"0x{vendor}\n")
        self.write(f"{base}/device", f"0x{device}\n")
        self.write(f"{base}/class", f"0x{class_code}\n")
        if driver:
            self.write(f"sys/module/{driver}/version", "1.0.0\n")

    def usb_device(
        self,
        bus_port: str,
        *,
        vendor: str,
        product: str,
        manufacturer: str,
        product_name: str,
        serial: str | None,
        driver: str = "usb",
        binterface_class: str = "ff",
        interface_driver: str = "usbhid",
    ) -> None:
        base = f"sys/bus/usb/devices/{bus_port}"
        self.uevent(
            base,
            DEVTYPE="usb_device",
            DRIVER=driver,
            PRODUCT=f"{vendor}/{product}/100",
            TYPE="0/0/0",
        )
        self.write(f"{base}/manufacturer", manufacturer)
        self.write(f"{base}/product", product_name)
        if serial is not None:
            self.write(f"{base}/serial", serial)
        interface = f"{base}:1.0"
        # ':' is a legal sysfs separator but not a legal character in Windows
        # paths, so interface directories are only created on Linux hosts.
        if os.name != "nt":
            self.uevent(
                interface,
                DEVTYPE="usb_interface",
                DRIVER=interface_driver,
                INTERFACE=f"{binterface_class}/1/1",
                MODALIAS=f"usb:v{vendor}p{product}",
            )

    def block_device(
        self,
        name: str,
        *,
        sectors: int,
        model: str,
        serial: str | None,
        rotational: bool,
        removable: bool = False,
        driver: str | None = None,
        partitions: dict[str, int] | None = None,
    ) -> None:
        base = f"sys/block/{name}"
        self.write(f"{base}/size", f"{sectors}\n")
        self.write(f"{base}/removable", "1\n" if removable else "0\n")
        self.write(f"{base}/queue/rotational", "1\n" if rotational else "0\n")
        self.write(f"{base}/device/model", f"{model}\n")
        if serial is not None:
            self.write(f"{base}/device/serial", f"{serial}\n")
        if driver:
            self.uevent(f"{base}/device", DRIVER=driver)
        for partition, partition_sectors in (partitions or {}).items():
            self.write(f"{base}/{partition}/size", f"{partition_sectors}\n")

    def network_interface(
        self,
        name: str,
        *,
        mac: str,
        state: str = "up",
        speed: int | None = None,
        wireless: bool = False,
        driver: str | None = None,
        firmware_version: str | None = None,
        pci_slot: str | None = None,
    ) -> None:
        base = f"sys/class/net/{name}"
        self.write(f"{base}/address", mac)
        self.write(f"{base}/operstate", state)
        self.write(f"{base}/type", "1\n")
        if speed is not None:
            self.write(f"{base}/speed", f"{speed}\n")
        if wireless:
            (self.root / base / "wireless").mkdir(parents=True, exist_ok=True)
        if driver or firmware_version or pci_slot:
            values = {}
            if driver:
                values["DRIVER"] = driver
            if pci_slot:
                values["PCI_SLOT_NAME"] = pci_slot
            self.uevent(f"{base}/device", **values)
            if firmware_version:
                self.write(f"{base}/device/firmware_version", firmware_version)

    def cpu(
        self, index: int, *, package: int, core: int, max_khz: int, online: bool = True
    ) -> None:
        base = f"sys/devices/system/cpu/cpu{index}"
        self.write(f"{base}/topology/physical_package_id", f"{package}\n")
        self.write(f"{base}/topology/core_id", f"{core}\n")
        self.write(f"{base}/topology/thread_siblings_list", f"{index}\n")
        self.write(f"{base}/online", "1\n" if online else "0\n")
        self.write(f"{base}/cpufreq/cpuinfo_max_freq", f"{max_khz}\n")

    def battery(self, name: str = "BAT0", **values: str) -> None:
        base = f"sys/class/power_supply/{name}"
        self.write(f"{base}/type", "Battery\n")
        for key, value in values.items():
            self.write(f"{base}/{key}", f"{value}\n")


def _cpuinfo(entries: list[dict[str, str]]) -> str:
    blocks = []
    for entry in entries:
        blocks.append("\n".join(f"{key}\t: {value}" for key, value in entry.items()))
    return "\n\n".join(blocks) + "\n"


def _efi_var(enabled: bool) -> bytes:
    return struct.pack("<I", 0x6) + (b"\x01" if enabled else b"\x00")


def _core_count(n: int) -> str:
    return ",".join(str(index) for index in range(n))


INTEL_LAPTOP_CPUINFO_FLAGS = (
    "fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat pse36 "
    "clflush mmx fxsr sse sse2 ss ht syscall nx pdpe1gb rdtscp lm constant_tsc "
    "rep_good nopl xtopology cpuid pni pclmulqdq ssse3 fma cx16 pcid sse4_1 "
    "sse4_2 x2apic movbe popcnt aes xsave avx f16c rdrand lahf_lm "
    "abm 3dnowprefetch invpcid_single ssbd ibrs ibpb stibp ibrs_enhanced fsgsbase "
    "bmi1 avx2 smep bmi2 erms invpcid avx512f avx512dq rdseed adx smap avx512ifma "
    "clwb avx512cd sha_ni avx512bw avx512vl xsaveopt xsavec xgetbv1 xsaves"
)

AMD_DESKTOP_CPUINFO_FLAGS = (
    "fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat pse36 "
    "clflush mmx fxsr sse sse2 ht syscall nx mmxext fxsr_opt pdpe1gb rdtscp lm "
    "constant_tsc rep_good amd_lbr_v2 nopl xtopology cpuid extd_apicid aperfmperf "
    "rapl pni pclmulqdq monitor ssse3 fma cx16 sse4_1 sse4_2 movbe popcnt aes "
    "xsave avx f16c rdrand lahf_lm cmp_legacy svm extapic cr8_legacy abm sse4a "
    "misalignsse 3dnowprefetch osvw ibs skinit wdt tce topoext perfctr_core "
    "perfctr_nb bpext perfctr_llc mwaitx cpb cat_l3 cdp_l3 hw_pstate ssbd mba "
    "ibrs ibpb stibp vmmcall fsgsbase bmi1 avx2 smep bmi2 cqm rdt_a rdseed adx "
    "smap clflushopt clwb sha_ni xsaveopt xsavec xgetbv1 xsaves cqm_llc "
    "cqm_occup_llc cqm_mbm_total cqm_mbm_local user_shstk clzero irperf xsaveerptr"
)


def intel_laptop(root: Path) -> Path:
    """Intel laptop with hybrid Intel + NVIDIA graphics, NVMe, Wi-Fi, battery."""
    tree = TreeBuilder(root)
    tree.write(
        "etc/os-release",
        'NAME="Fedora Linux"\nVERSION="44 (KDE Plasma Desktop Edition)"\n'
        'ID=fedora\nVERSION_ID=44\nPRETTY_NAME="Fedora Linux 44 (KDE Plasma Desktop Edition)"\n'
        'VARIANT="KDE Plasma Desktop Edition"\nVARIANT_ID=kde\nBUILD_ID=20260424.n.0\n',
    )
    tree.write("proc/sys/kernel/osrelease", "6.16.3-200.fc44.x86_64\n")
    tree.write("proc/version", "Linux version 6.16.3-200.fc44.x86_64 (mockbuild@x86-64) #1 SMP\n")
    tree.write("proc/cmdline", "BOOT_IMAGE=/vmlinuz root=UUID=abcd ro rhgb quiet\n")
    tree.write(
        "proc/cpuinfo",
        _cpuinfo(
            [
                {
                    "processor": str(index),
                    "vendor_id": "GenuineIntel",
                    "model name": "12th Gen Intel(R) Core(TM) i7-1260P",
                    "cpu family": "6",
                    "model": "154",
                    "stepping": "3",
                    "microcode": "0x191",
                    "flags": INTEL_LAPTOP_CPUINFO_FLAGS,
                    "bugs": "spectre_v1 spectre_v2",
                }
                for index in range(8)
            ]
        ),
    )
    tree.write(
        "proc/meminfo",
        "MemTotal:       15728640 kB\nMemFree:         4194304 kB\n"
        "MemAvailable:   10485760 kB\nBuffers:          524288 kB\n"
        "Cached:          5242880 kB\nSwapTotal:       8388608 kB\nSwapFree:        8388608 kB\n",
    )
    tree.write(
        "proc/modules",
        "amdgpu 12345678 12 - Live 0x0000000000000000\nnvidia 98765432 3 - Live 0x0\n",
    )
    tree.write("proc/asound/card0/id", "sofhdadsp\n")
    tree.write(
        "proc/bus/input/devices",
        "I: Bus=0011 Vendor=0001 Product=0001 Version=ab41\n"
        "N: Name=\"AT Translated Set 2 keyboard\"\n"
        "P: Phys=isa0060/serio0/input0\n"
        "H: Handlers=sysrq kbd leds event0\n\n"
        "I: Bus=0018 Vendor=06cb Product=ce44 Version=0100\n"
        "N: Name=\"SYNA8004:00 06CB:CE44 Touchpad\"\n"
        "H: Handlers=mouse0 event5\n\n",
    )

    tree.write_bytes(f"sys/firmware/efi/efivars/SecureBoot-{_SECURE_BOOT_GUID}", _efi_var(True))
    tree.write_bytes(f"sys/firmware/efi/efivars/SetupMode-{_SECURE_BOOT_GUID}", _efi_var(False))
    tree.write("sys/firmware/acpi/platform_profile", "balanced\n")
    tree.write("sys/firmware/acpi/platform_profile_choices", "low-power balanced performance\n")
    tree.write("sys/class/dmi/id/sys_vendor", "LENOVO\n")
    tree.write("sys/class/dmi/id/product_name", "21CBCTO1WW\n")
    tree.write("sys/class/dmi/id/product_serial", "PF3ABCDE\n")

    for index in range(8):
        tree.cpu(index, package=0, core=index // 2, max_khz=4700000)
    cache = root / "sys/devices/system/cpu/cpu0/cache"
    for index, (level, kind, size) in enumerate(
        [
            ("1", "Data", "48K"),
            ("1", "Instruction", "32K"),
            ("2", "Unified", "1280K"),
            ("3", "Unified", "24576K"),
        ]
    ):
        (cache / f"index{index}").mkdir(parents=True, exist_ok=True)
        tree.write(f"sys/devices/system/cpu/cpu0/cache/index{index}/level", f"{level}\n")
        tree.write(f"sys/devices/system/cpu/cpu0/cache/index{index}/type", f"{kind}\n")
        tree.write(f"sys/devices/system/cpu/cpu0/cache/index{index}/size", f"{size}\n")
    tree.write("sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq", "4700000\n")
    tree.write("sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_min_freq", "400000\n")
    tree.write("sys/devices/system/cpu/cpu0/cpufreq/scaling_driver", "intel_pstate\n")
    tree.write("sys/devices/system/cpu/cpu0/cpufreq/scaling_governor", "powersave\n")
    tree.write(
        "sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors",
        "performance powersave\n",
    )
    tree.write(
        "sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference", "balance_performance\n"
    )
    tree.write(
        "sys/devices/system/cpu/cpu0/cpufreq/energy_performance_available_preferences",
        "default performance balance_performance balance_power power\n",
    )
    (root / "sys/devices/system/cpu/cpu0/node0").mkdir(parents=True, exist_ok=True)

    tree.pci_device(
        "0000:00:02.0",
        vendor="8086",
        device="46a6",
        class_code="030000",
        driver="i915",
    )
    tree.pci_device(
        "0000:01:00.0",
        vendor="10de",
        device="25a2",
        class_code="030200",
        driver="nvidia",
        subsystem_vendor="17aa",
        subsystem_device="22c2",
    )
    tree.pci_device(
        "0000:00:1f.3", vendor="8086", device="51c8", class_code="040300", driver="snd_hda_intel"
    )
    tree.pci_device(
        "0000:00:14.0", vendor="8086", device="51ed", class_code="0c0330", driver="xhci_hcd"
    )
    tree.pci_device(
        "0000:00:1f.2", vendor="8086", device="51d3", class_code="010601", driver="ahci"
    )
    tree.pci_device(
        "0000:00:14.3", vendor="8086", device="51f0", class_code="028000", driver="iwlwifi"
    )

    tree.block_device(
        "nvme0n1",
        sectors=1_000_204_800,
        model="SAMSUNG MZVL2512HCJQ-00BL7",
        serial="S64ANJ0R123456",
        rotational=False,
        driver="nvme",
        partitions={"nvme0n1p1": 1_048_576, "nvme0n1p2": 2_097_152, "nvme0n1p3": 997_000_000},
    )
    tree.network_interface(
        "wlan0",
        mac="a4:bb:6d:11:22:33",
        wireless=True,
        driver="iwlwifi",
        firmware_version="89.6fd758c1.0",
        pci_slot="0000:00:14.3",
    )
    tree.network_interface(
        "enp0s31f6", mac="54:ee:75:44:55:66", state="down", speed=1000, driver="e1000e"
    )

    tree.usb_device(
        "1-3",
        vendor="046d",
        product="c52b",
        manufacturer="Logitech",
        product_name="USB Receiver",
        serial="1234ABCD",
        interface_driver="usbhid",
    )
    tree.usb_device(
        "1-5",
        vendor="5986",
        product="2119",
        manufacturer="Chicony",
        product_name="Integrated Camera",
        serial=None,
        binterface_class="0e",
        interface_driver="uvcvideo",
    )
    tree.write("sys/class/video4linux/video0/name", "Integrated Camera: Integrated C\n")
    tree.write("sys/class/bluetooth/hci0/address", "a4:bb:6d:11:22:34\n")
    tree.write("sys/class/bluetooth/hci0/type", "primary\n")
    tree.write("sys/class/bluetooth/hci0/bus", "usb\n")
    tree.battery(
        "BAT0",
        status="Discharging",
        capacity="76",
        energy_full="57000000",
        energy_now="43000000",
        power_now="8100000",
        cycle_count="122",
        charge_control_end_threshold="100",
    )
    tree.write("sys/class/drm/card1/device/mem_info_vram_total", "4294967296\n")
    tree.uevent("sys/class/drm/card1/device", PCI_SLOT_NAME="0000:01:00.0")
    return root


def amd_desktop(root: Path) -> Path:
    """AMD desktop with integrated graphics, NVMe + SATA disk, wired network."""
    tree = TreeBuilder(root)
    tree.write(
        "etc/os-release",
        'NAME="Fedora Linux"\nVERSION="44 (KDE Plasma Desktop Edition)"\n'
        'ID=fedora\nVERSION_ID=44\nPRETTY_NAME="Fedora Linux 44 (KDE Plasma Desktop Edition)"\n'
        'VARIANT="KDE Plasma Desktop Edition"\nVARIANT_ID=kde\n',
    )
    tree.write("proc/sys/kernel/osrelease", "6.16.3-200.fc44.x86_64\n")
    tree.write("proc/cmdline", "root=/dev/nvme0n1p3 ro\n")
    tree.write(
        "proc/cpuinfo",
        _cpuinfo(
            [
                {
                    "processor": str(index),
                    "vendor_id": "AuthenticAMD",
                    "model name": "AMD Ryzen 9 7950X 16-Core Processor",
                    "cpu family": "25",
                    "model": "97",
                    "stepping": "2",
                    "microcode": "0xa601206",
                    "flags": AMD_DESKTOP_CPUINFO_FLAGS,
                }
                for index in range(32)
            ]
        ),
    )
    tree.write(
        "proc/meminfo",
        "MemTotal:       65766688 kB\nMemAvailable:   60000000 kB\nSwapTotal:       8388608 kB\n",
    )
    tree.write("proc/modules", "amdgpu 12345678 40 - Live 0x0\n")
    tree.write(
        "proc/bus/input/devices",
        "I: Bus=0019 Vendor=0000 Product=0001 Version=0000\n"
        "N: Name=\"Power Button\"\n"
        "H: Handlers=kbd event0\n\n",
    )
    tree.write("sys/class/dmi/id/sys_vendor", "ASUSTeK COMPUTER INC.\n")
    tree.write("sys/class/dmi/id/product_name", "ROG STRIX X670E-E GAMING WIFI\n")
    tree.directory("sys/firmware/acpi")

    for index in range(32):
        tree.cpu(index, package=0, core=index // 2, max_khz=5900000)
    tree.write("sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq", "5900000\n")
    tree.write("sys/devices/system/cpu/cpu0/cpufreq/scaling_driver", "amd-pstate-epp\n")
    tree.write("sys/devices/system/cpu/cpu0/cpufreq/scaling_governor", "powersave\n")
    tree.write(
        "sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors",
        "performance powersave\n",
    )
    tree.write(
        "sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference", "balance_performance\n"
    )

    tree.pci_device(
        "0000:0c:00.0", vendor="1002", device="164e", class_code="030000", driver="amdgpu"
    )
    tree.uevent("sys/class/drm/card0/device", PCI_SLOT_NAME="0000:0c:00.0")
    tree.write("sys/class/drm/card0/device/mem_info_vram_total", "2147483648\n")
    tree.pci_device("0000:0d:00.0", vendor="1022", device="1483", class_code="060000")
    tree.pci_device("0000:0e:00.0", vendor="1022", device="1483", class_code="060000")
    tree.pci_device(
        "0000:10:00.0", vendor="10ec", device="8125", class_code="020000", driver="r8169"
    )
    tree.pci_device(
        "0000:11:00.0", vendor="144d", device="a80a", class_code="010802", driver="nvme"
    )
    tree.pci_device(
        "0000:12:00.0", vendor="1b21", device="0612", class_code="010601", driver="ahci"
    )

    tree.block_device(
        "nvme0n1",
        sectors=2_000_409_600,
        model="Samsung SSD 990 PRO 1TB",
        serial="S7KHNJ0R999999",
        rotational=False,
        driver="nvme",
        partitions={"nvme0n1p1": 1_048_576, "nvme0n1p2": 1_999_000_000},
    )
    tree.block_device(
        "sda",
        sectors=7_814_037_168,
        model="WDC WD40EZAZ-00SF3B0",
        serial="WD-WX12D80ABCDE",
        rotational=True,
        driver="ahci",
        partitions={"sda1": 7_813_000_000},
    )
    tree.network_interface("enp10s0", mac="9c:6b:00:aa:bb:cc", speed=2500, driver="r8169")
    tree.usb_device(
        "3-1",
        vendor="1532",
        product="0091",
        manufacturer="Razer",
        product_name="Razer Mouse",
        serial="RAZER0001",
        interface_driver="usbhid",
    )
    return root


def minimal_unknown(root: Path) -> Path:
    """Almost empty tree: every collector must degrade gracefully."""
    tree = TreeBuilder(root)
    tree.write("proc/meminfo", "MemTotal:        2048000 kB\nMemAvailable:    1500000 kB\n")
    tree.write("proc/sys/kernel/osrelease", "6.1.0-generic\n")
    return root
