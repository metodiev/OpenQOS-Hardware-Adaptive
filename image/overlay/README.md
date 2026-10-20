# OpenQOS image overlay

This directory is copied into a checked-out
[Fedora KIWI description](https://forge.fedoraproject.org/releng/kiwi-descriptions)
by `openqos image build`.

| Path | Purpose |
| --- | --- |
| `components/openqos.xml` | Extra packages installed in the live image |
| `root/usr/local/bin/openqos` | Wrapper that runs the OpenQOS CLI from `/opt/openqos/src` |
| `config.sh.append` | Appended once to the description's `config.sh` |

`apply_overlay` also copies `src/openqos` into `root/opt/openqos/src/openqos`, so
the live image always contains exactly the sources from the revision that was
built. Nothing here modifies the host system.
