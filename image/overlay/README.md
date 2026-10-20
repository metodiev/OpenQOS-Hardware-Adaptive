# OpenQOS image overlay

This directory is copied into a checked-out
[Fedora KIWI description](https://forge.fedoraproject.org/releng/kiwi-descriptions)
by `openqos image build`.

| Path | Purpose |
| --- | --- |
| `components/openqos.xml` | Extra packages installed in the live image |
| `root/usr/local/bin/openqos` | Wrapper that runs the OpenQOS CLI from `/opt/openqos/src` |

`apply_overlay` also:

* copies `src/openqos` into `root/opt/openqos/src/openqos`, so the live image
  contains exactly the sources from the revision that was built;
* writes `root/etc/openqos-release` from the pinned Fedora release and the
  OpenQOS version;
* normalises file modes (`0755` for the wrapper, `0644` otherwise), because the
  sources may come from a Windows or bind-mounted checkout.

KIWI imports everything under a description's `root/` directory into the image
root, so no post-install script is needed. Nothing here modifies the host
system.
