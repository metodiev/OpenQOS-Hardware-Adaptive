# Live USB integration

Phase 4 makes the live image do useful work on its own, without a network
connection and without asking the user to run anything.

## What happens at boot

1. `openqos-scan.service` runs after `local-fs.target`, before the display
   manager:

   ```
   openqos hardware scan   --privacy --output /var/lib/openqos/inventory.json
   openqos profile build   --inventory ... --output /var/lib/openqos/profile.json
   openqos optimize        --inventory ... --format json --output /var/lib/openqos/plan.json
   openqos status          --state-dir /var/lib/openqos --write-summary /var/lib/openqos/summary.txt
   ```

2. The KDE session starts. `/etc/xdg/autostart/openqos-summary.desktop` opens a
   Konsole window with `summary.txt`, so the detected hardware, the selected
   profile, the planned changes, and every compatibility issue are visible
   immediately.

3. Nothing on the machine is modified. The scan is read-only, the plan is not
   applied, and `--privacy` keeps hostnames, serial numbers, MAC addresses and
   the kernel command line out of the report.

## Files produced

| Path | Content |
| --- | --- |
| `/var/lib/openqos/inventory.json` | Full hardware inventory (schema 1.0.0) |
| `/var/lib/openqos/profile.json` | Normalised profile used for rule matching |
| `/var/lib/openqos/plan.json` | Optimization plan with decisions and rollback |
| `/var/lib/openqos/summary.txt` | Human readable report shown in the session |

They are ordinary files on the live filesystem (RAM), so they disappear on
reboot. Collection logs are in the journal:

```bash
journalctl -u openqos-scan.service --no-pager
```

## Offline behaviour

Detection uses only `/sys`, `/proc` and `/etc/os-release`. No network access is
attempted by the service. If a collector cannot read something, the reason ends
up in `unavailable` and is listed at the bottom of the report instead of being
retried online.

## Manual use

```bash
openqos hardware scan --privacy --output /tmp/inventory.json
openqos profile explain --inventory /tmp/inventory.json
openqos optimize --inventory /tmp/inventory.json --policy power-saving
openqos status --state-dir /var/lib/openqos
```

On an installed system the same command works; `status` simply reports that no
scan has run yet until one does.

## Testing the live image

```bash
qemu-system-x86_64 -enable-kvm -m 4096 -smp 4 -machine q35 -cpu host \
  -drive if=pflash,format=raw,readonly=on,file=/usr/share/edk2/ovmf/OVMF_CODE.fd \
  -drive if=pflash,format=raw,file=/var/tmp/OVMF_VARS.fd \
  -drive file=openqos-generic-44.iso,media=cdrom,readonly=on \
  -boot d -device virtio-vga -display none -vnc :0 \
  -monitor unix:/var/tmp/mon.sock,server=on,wait=off
```

Expected result: the KDE desktop appears with a *OpenQOS hardware report* window
listing the virtual hardware, the selected profile (`virtual-machine` in QEMU,
because the guest reports a hypervisor), planned changes, and the "Nothing has
been changed on this system" line.

From the host, the same information is available over the serial console only if
a console was configured; use the screenshot/monitor as the primary check.

## Not part of Phase 4

* Applying the plan (installer, Phase 5).
* Persistent storage of the report on an installed system (runtime service,
  Phase 6).
